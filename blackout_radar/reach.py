"""Erreichbarkeit der Messquellen in Europa.

Der Radar läuft bei GitHub in den USA, Push-Dienst und Nachrichtenquellen stehen ebenfalls dort. In Europa
stehen nur die Messquellen (Netzfrequenz, Stromlast, Störmeldungen). Antwortet keine von ihnen mehr, während
Quellen außerhalb Europas antworten, ist das ein eigenes Warnsignal: Es passt zu einem großflächigen Strom-
oder Netzausfall in Europa, aber auch zu einer gestörten Verbindung zwischen den USA und Europa. Einen
Stromausfall belegt es nicht, deshalb gibt es dazu eine Warnung und keinen Alarm.

Grundlage ist das Protokoll der Anfragen dieses Laufs (http.JOURNAL): Ein Host gilt als erreicht, sobald
er antwortet, auch mit einer Fehlermeldung. Nicht erreicht heißt: keine Verbindung oder keine Antwort.
"""
from __future__ import annotations

from datetime import timedelta

from .model import Message, fmt_duration, iso, parse_ts, zone

# Bekannte Hosts in Europa (Standort gemessen am 27.11.2026). Welche Hosts zählen, steht in der
# Konfiguration unter health.europe_hosts.
PLACES = {
    "api.energy-charts.info": "Energy-Charts (Freiburg)",
    "dat.netzfrequenzmessung.de": "netzfrequenzmessung.de (Nürnberg)",
    "www.linznetz.at": "LINZ NETZ (Linz)",
}
EUROPEAN_SOURCES = {"frequency", "load", "utility"}  # Quellen, die an diesen Hosts hängen
FRESH = timedelta(minutes=20)  # es zählen nur Hosts, die in dieser Zeit abgefragt wurden
MIN_HOSTS = 2                  # ein einzelner Host, der schweigt, ist nur eine gestörte Quelle


def label(host: str) -> str:
    return PLACES.get(host, host)


def silent_since(state: dict):
    """Zeitpunkt, seit dem keine Messquelle in Europa antwortet (None: mindestens eine antwortet)."""
    return parse_ts((state.get("reach") or {}).get("silent_since"))


def hosts(cfg: dict, state: dict, now) -> list[dict]:
    """Stand je Host für den Lagebericht: reached ist None, wenn der Host zuletzt nicht abgefragt wurde."""
    book = (state.get("reach") or {}).get("hosts") or {}
    rows = []
    for host in cfg["health"].get("europe_hosts") or []:
        entry = book.get(host) or {}
        checked = parse_ts(entry.get("checked"))
        fresh = checked is not None and now - checked <= FRESH
        rows.append({"host": host, "label": label(host), "checked": entry.get("checked"),
                     "reached": (not entry.get("fail_since")) if fresh else None,
                     "fail_since": entry.get("fail_since") if fresh else None})
    return rows


def update(cfg: dict, state: dict, now, journal: list[tuple[str, bool]]) -> list[Message]:
    """Trägt die Anfragen dieses Laufs ein und meldet, wenn Europa verstummt oder wieder antwortet."""
    health = cfg["health"]
    watched = set(health.get("europe_hosts") or [])
    book = state.setdefault("reach", {})
    book.setdefault("hosts", {})
    book.setdefault("silent_since", None)
    seen: dict[str, bool] = {}
    for host, reached in journal:
        seen[host] = seen.get(host, False) or reached
    for host, reached in seen.items():
        if host not in watched:
            continue
        entry = book["hosts"].setdefault(host, {"fail_since": None})
        entry["checked"] = iso(now)
        entry["fail_since"] = None if reached else (entry.get("fail_since") or iso(now))
    for host in [host for host in book["hosts"] if host not in watched]:
        del book["hosts"][host]
    outside = any(reached for host, reached in seen.items() if host not in watched)
    fresh = {host: entry for host, entry in book["hosts"].items()
             if parse_ts(entry.get("checked")) and now - parse_ts(entry["checked"]) <= FRESH}
    down = {host: entry for host, entry in fresh.items() if entry.get("fail_since")}

    tz = zone(cfg.get("timezone", "Europe/Vienna"))
    url = cfg.get("status_url", "")

    def clock(when) -> str:
        return when.astimezone(tz).strftime("%H:%M")

    since = parse_ts(book["silent_since"])
    if since is None:
        if len(down) < MIN_HOSTS or len(down) < len(fresh) or not outside:
            return []
        start = max(parse_ts(entry["fail_since"]) for entry in down.values())  # seit wann alle zugleich
        if now - start < timedelta(minutes=health.get("europe_silent_minutes", 10)):
            return []
        book["silent_since"] = iso(start)
        names = ", ".join(label(host) for host in sorted(down))
        return [Message(
            "Messquellen in Europa nicht erreichbar",
            f"Seit {clock(start)} Uhr antwortet keine der Messquellen in Europa mehr: {names}. "
            "Quellen außerhalb Europas antworten.\n"
            "Das passt zu einem großflächigen Strom- oder Netzausfall in Europa, kann aber auch eine gestörte "
            "Verbindung zwischen den USA und Europa sein. Ein Stromausfall ist damit nicht belegt.\n"
            "Der Radar läuft in den USA weiter und wertet Medienberichte aus Übersee aus. "
            "Netzfrequenz, Stromlast und Störmeldungen fehlen, bis die Quellen wieder antworten.",
            "warn", f"europe-silent:{iso(start)}", url)]
    if fresh and len(down) == len(fresh):
        return []  # weiter still
    book["silent_since"] = None
    if not fresh:
        return []  # die Quellen werden nicht mehr abgefragt (abgeschaltet)
    back = ", ".join(label(host) for host in sorted(fresh) if host not in down)
    return [Message(
        "Messquellen in Europa wieder erreichbar",
        f"Seit {clock(now)} Uhr antwortet wieder: {back}. Die Unterbrechung dauerte {fmt_duration(now - since)} "
        f"(seit {clock(since)} Uhr). Das ist keine Entwarnung für einen Stromausfall, nur die Messwerte kommen wieder.",
        "info", f"europe-back:{iso(now)}", url)]
