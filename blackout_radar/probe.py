"""Diagnose: fragt jede Datenquelle einmal roh ab und zeigt, was zurückkommt.

Aufruf:  python -m blackout_radar probe [--only load,frequency,news,utility,ioda,ntfy]
         python -m blackout_radar probe --only replay   Lastauswertung an echten Tagen nachspielen

Gedacht zum Einrichten und für den Fall, dass eine Quelle ihr Format ändert.
Es werden nur die festen Adressen der Datenquellen abgefragt, nichts wird gespeichert
oder verschickt.
"""
from __future__ import annotations

import json
import re
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import timedelta

from . import gazetteer, http
from .collectors import energy_charts, linznetz, news
from .http import HttpError
from .model import fmt_number, iso, parse_ts


def outline(value, depth: int = 0, limit: int = 4) -> str:
    """Beschreibt den Aufbau einer JSON-Antwort in Kurzform."""
    if isinstance(value, dict):
        if depth >= limit:
            return f"{{…{len(value)} Schlüssel}}"
        inner = ", ".join(f"{key!r}: {outline(item, depth + 1, limit)}" for key, item in list(value.items())[:25])
        return "{" + inner + (f", …+{len(value) - 25}" if len(value) > 25 else "") + "}"
    if isinstance(value, list):
        return "[]" if not value else f"[{len(value)}× {outline(value[0], depth + 1, limit)}]"
    if isinstance(value, str):
        return f"str({value[:40]!r})"
    return f"{type(value).__name__}({value!r})"


def _fmt(when) -> str:
    return when.strftime("%Y-%m-%dT%H:%MZ")


def _limits(head: dict) -> str:
    """Was der Dienst zur Begrenzung der Abfragen mitschickt."""
    return ", ".join(f"{key}: {value}" for key, value in head.items() if re.search(r"ratelimit|retry", key, re.I))


def _fetch(url: str, params: dict | None = None, timeout: float = 30, patient: bool = False) -> str | None:
    """Holt eine Adresse. Mit patient=True wird nach "zu viele Abfragen" gewartet und zweimal wiederholt."""
    shown = url + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
    for attempt in range(3 if patient else 1):
        print(f"  GET {shown}")
        try:
            status, head, body = http.request(url, params=params, timeout=timeout)
        except HttpError as err:
            print(f"  FEHLER: {err}" + (f" | Antwort: {err.body}" if err.body else ""))
            if _limits(err.headers):
                print(f"  Begrenzung: {_limits(err.headers)}")
            if err.status != 429 or attempt == 2 or not patient:
                return None
            wait = min(60, int(err.retry_after)) if (err.retry_after or "").isdigit() else 20
            print(f"  warte {wait} s und frage noch einmal")
            time.sleep(wait)
            continue
        print(f"  HTTP {status}, {head.get('Content-Type', '?')}, {len(body)} Bytes"
              + (f", Begrenzung: {_limits(head)}" if _limits(head) else ""))
        return body.decode("utf-8", errors="replace")
    return None


def _json(text: str | None):
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        print(f"  kein JSON: {text[:300]!r}")
        return None


def _flatten(node) -> list:
    if isinstance(node, dict):
        return [node]
    found = []
    for item in node or []:
        found += _flatten(item)
    return found


# ------------------------------------------------------------------ Stromlast
# Nachbarländer, deren Lastdaten bei der Prüfung unvollständig oder nicht abrufbar waren. Die Diagnose
# zeigt sie weiter an, damit sich später beurteilen lässt, ob sie in die Überwachung dürfen.
LOAD_CANDIDATES = ["it", "ch", "si"]

def probe_load(cfg: dict, now) -> None:
    """Zeigt je Land die neuesten Lastwerte neben denen vom Vortag. Unvollständige Meldungen fallen so auf."""
    section = cfg["sources"]["load"]
    base = section["base_url"].rstrip("/")
    countries = list(section["countries"]) + [c for c in LOAD_CANDIDATES if c not in section["countries"]]
    for index, country in enumerate(countries):
        if index:
            time.sleep(4)  # der Dienst begrenzt schnelle Abfragen
        doc = _json(_fetch(f"{base}/v2/public_power", {
            "country": country, "start": _fmt(now - timedelta(hours=30)), "end": _fmt(now)}, patient=True))
        if not isinstance(doc, dict):
            continue
        rows = doc.get("data") or []
        known = [(parse_ts(row.get("timestamp")), (row.get("values") or {}).get("load"), row.get("values") or {})
                 for row in rows]
        known = [(when, value, values) for when, value, values in known if when and value]
        if index == 0:  # das erste Land ausführlich
            print("  Kopf:", {k: v for k, v in doc.items() if k not in ("data", "series")})
            print("  Reihen:", [item.get("id") for item in doc.get("series") or [] if isinstance(item, dict)])
        if not known:
            print(f"  {country}: KEINE Lastwerte in {len(rows)} Zeilen")
            continue
        lookup = {when: value for when, value, _ in known}
        last_time, last_value, last_row = known[-1]
        loads = [value for _, value, _ in known]
        used = "" if country in section["countries"] else " (nur Diagnose, nicht überwacht)"
        print(f"  {country}{used}: {len(known)} Werte, Raster {doc.get('interval_minutes')} min, "
              f"kleinster {min(loads):.0f}, größter {max(loads):.0f} MW, Verzögerung {now - last_time}")

        def beside(when, value, lookup=lookup):
            ref = lookup.get(when - timedelta(days=1))
            return f"{when.strftime('%H:%M')} {value:.0f} ({f'{ref:.0f}' if ref else '?'})"

        print("    neueste (Vortag):", ", ".join(beside(when, value) for when, value, _ in known[-8:]))
        ref = lookup.get(last_time - timedelta(days=1))
        if ref and abs(last_value / ref - 1) >= 0.15:
            before = next((values for when, _, values in known if when == last_time - timedelta(days=1)), {})
            print(f"    AUFFÄLLIG: letzter Wert {last_value / ref - 1:+.0%} gegenüber dem Vortag")
            print("    alle Reihen jetzt: ", json.dumps(last_row, ensure_ascii=False))
            print("    alle Reihen Vortag:", json.dumps(before, ensure_ascii=False))


# ------------------------------------------------------------------ Rückblick
# Echte Zeiträume, an denen sich die Lastauswertung messen lässt: ein Stromausfall und ruhige Tage
# mit Wochenenden und Feiertagen, an denen sie nichts melden darf. None steht für "die letzten 14 Tage".
REPLAYS = [
    ("es", "2025-04-18T00:00Z", "2025-04-30T12:00Z", "Stromausfall Iberische Halbinsel, 28.04.2025"),
    ("pt", "2025-04-18T00:00Z", "2025-04-30T12:00Z", "Stromausfall Iberische Halbinsel, 28.04.2025"),
    ("cz", "2025-06-24T00:00Z", "2025-07-07T00:00Z", "Stromausfall in Prag und Nordböhmen, 04.07.2025"),
    ("hr", "2024-06-11T00:00Z", "2024-06-25T00:00Z", "Stromausfall am Westbalkan, 21.06.2024"),
    ("ba", "2024-06-11T00:00Z", "2024-06-25T00:00Z", "Stromausfall am Westbalkan, 21.06.2024"),
    ("me", "2024-06-11T00:00Z", "2024-06-25T00:00Z", "Stromausfall am Westbalkan, 21.06.2024"),
    ("at", None, None, "die letzten 21 Tage, Normalbetrieb"),
    ("at", "2026-04-17T00:00Z", "2026-05-05T00:00Z", "Wochen um den Feiertag am Freitag, 01.05.2026"),
    ("at", "2025-12-15T00:00Z", "2026-01-08T00:00Z", "Weihnachten und Jahreswechsel 2025/26"),
    ("de", None, None, "die letzten 21 Tage, Normalbetrieb"),
]
_NOT_GENERATION = {"load", "residual_load", "renewable_share_of_load", "renewable_share_of_generation",
                   "cross_border_electricity_trading"}


def _generation(values: dict):
    """Summe der Erzeugung einer Zeile, None wenn dazu nichts gemeldet ist."""
    parts = [value for key, value in values.items()
             if key not in _NOT_GENERATION and not key.endswith("_consumption") and value is not None]
    return round(sum(parts)) if parts else None


def replay(country: str, points: list, section: dict) -> list:
    """Geht eine Lastreihe Punkt für Punkt durch, so wie der Monitor sie nach und nach gesehen hätte.

    Die Auswertung beginnt, sobald der Verlauf für alle Vergleichstage reicht.
    Liefert je Schritt mit Befund (Zeit des neuesten Werts, Signal).
    """
    events, past, found = {}, {}, []
    times = [parse_ts(stamp) for stamp, _ in points]
    begin = times[0] + timedelta(days=max(energy_charts.REFERENCE_DAYS), hours=4)
    first = 0
    for index, when in enumerate(times):
        if when < begin:
            continue
        while times[first] < when - timedelta(hours=section["history_hours"]):
            first += 1
        for signal in energy_charts.analyse(country, points[first: index + 1], events, section,
                                            when + timedelta(hours=2), past):
            found.append((when, signal))
    return found


def probe_replay(cfg: dict, now) -> None:
    section = cfg["sources"]["load"]
    base = section["base_url"].rstrip("/")
    for index, (country, start, end, label) in enumerate(REPLAYS):
        if index:
            time.sleep(6)
        print(f"\n  --- {country}: {label}")
        doc = _json(_fetch(f"{base}/v2/public_power", {
            "country": country, "start": start or _fmt(now - timedelta(days=21)), "end": end or _fmt(now)},
            timeout=60, patient=True))
        if not isinstance(doc, dict):
            continue
        rows = doc.get("data") or []
        points = energy_charts.to_points(doc)
        if len(points) < 60:
            print(f"  zu wenige Lastwerte: {len(points)} in {len(rows)} Zeilen")
            continue
        step = int(doc.get("interval_minutes") or 15)
        lookup = {parse_ts(stamp): value for stamp, value in points}
        produced = {parse_ts(row.get("timestamp")): _generation(row.get("values") or {}) for row in rows}
        first, last = parse_ts(points[0][0]), parse_ts(points[-1][0])
        grid, made, when = [], [], first
        while when <= last:
            value = lookup.get(when)
            grid.append(None if value is None else round(value))
            made.append(produced.get(when))
            when += timedelta(minutes=step)
        gaps = [iso(first + timedelta(minutes=step * i)) for i, value in enumerate(grid) if value is None]
        print(f"  {len(points)} Werte im Raster {step} min von {iso(first)} bis {iso(last)}, "
              f"{len(gaps)} Lücken" + (f", erste: {gaps[:6]}" if gaps else ""))
        print("  REIHE", json.dumps({"country": country, "start": iso(first), "step_min": step, "load": grid,
                                     "generation": made if start else None}, separators=(",", ":")))
        found = replay(country, points, section)
        if not found:
            print("  Auswertung: kein Befund im ganzen Zeitraum")
            continue
        print(f"  Auswertung: {len(found)} Schritte mit Befund")
        for when, signal in found:
            print(f"    {iso(when)} {'AKTIV' if signal.active else 'ENDE '} {signal.severity:5.0%} "
                  f"Beginn {iso(signal.started_at)}"
                  + (f" Ende {iso(signal.ended_at)}" if signal.ended_at else "") + f" | {signal.detail}")


# --------------------------------------------------------------- Netzfrequenz
def probe_frequency(cfg: dict, now) -> None:
    section = cfg["sources"]["frequency"]
    base = section["energy_charts_url"].rstrip("/")
    for minutes in (10, 240):
        doc = _json(_fetch(f"{base}/v2/frequency", {
            "region": "DE-Freiburg", "start": _fmt(now - timedelta(minutes=minutes)),
            "end": _fmt(now + timedelta(minutes=1))}))
        if not isinstance(doc, dict):
            continue
        rows = doc.get("data") or []
        print(f"  Fenster {minutes} min: {len(rows)} Zeilen. Kopf:",
              {k: v for k, v in doc.items() if k not in ("data", "series")})
        if rows:
            print("  erste Zeile:", rows[0], "letzte Zeile:", rows[-1])
            last = parse_ts(rows[-1].get("timestamp"))
            if last:
                print(f"  Verzögerung {now - last}")
            break
    text = _fetch(section["nfm_url"], timeout=10)
    if text is not None:
        print("  Inhalt:", text[:300].replace("\n", " "))


# -------------------------------------------------------------------- IODA
def probe_ioda(cfg: dict, now) -> None:
    base = cfg["sources"]["ioda"]["base_url"].rstrip("/")
    until = int(now.timestamp())

    def call(path: str, params: dict, timeout: float = 30):
        started = time.monotonic()
        doc = _json(_fetch(f"{base}{path}", params, timeout=timeout))
        print(f"  Dauer {time.monotonic() - started:.1f} s")
        if doc is not None:
            print("  Aufbau:", outline(doc))
        return doc

    if call("/entities/query", {"entityType": "country", "entityCode": "AT"}, timeout=40) is None:
        print("  IODA antwortet nicht, weitere Abfragen übersprungen")
        return
    doc = call("/outages/alerts", {"from": until - 12 * 3600, "until": until, "entityType": "country", "limit": 5})
    rows = _flatten(doc.get("data") if isinstance(doc, dict) else doc)
    for row in rows[:3]:
        print("  Alarm:", json.dumps(row, ensure_ascii=False)[:600])

    call("/outages/events", {"from": until - 24 * 3600, "until": until, "entityType": "country", "limit": 3})
    call("/outages/summary", {"from": until - 24 * 3600, "until": until, "entityType": "country", "limit": 3})

    for params in ({"from": until - 3 * 3600, "until": until, "datasource": "ping-slash24"},
                   {"from": until - 3 * 3600, "until": until}):
        doc = _json(_fetch(f"{base}/signals/raw/country/AT", params))
        rows = _flatten(doc.get("data") if isinstance(doc, dict) else doc)
        for row in rows[:8]:
            values = row.get("values") or []
            print("  Reihe:", {k: v for k, v in row.items() if k != "values"},
                  f"| {len(values)} Werte, letzte: {values[-5:]}")

    doc = _json(_fetch(f"{base}/entities/query", {"entityType": "region", "relatedTo": "country/AT"}))
    rows = _flatten(doc.get("data") if isinstance(doc, dict) else doc)
    print(f"  {len(rows)} Regionen:", [(row.get("code"), row.get("name")) for row in rows[:40]])
    if rows:
        print("  erste Region:", json.dumps(rows[0], ensure_ascii=False)[:500])
        wanted = next((row for row in rows if "ber" in str(row.get("name", "")) and "sterreich" in str(row.get("name", ""))
                       or "Upper" in str(row.get("name", ""))), None)
        if wanted:
            doc = _json(_fetch(f"{base}/signals/raw/region/{wanted.get('code')}", {
                "from": until - 3 * 3600, "until": until, "datasource": "ping-slash24"}))
            for row in _flatten(doc.get("data") if isinstance(doc, dict) else doc)[:4]:
                values = row.get("values") or []
                print("  Reihe:", {k: v for k, v in row.items() if k != "values"},
                      f"| {len(values)} Werte, letzte: {values[-5:]}")


# ------------------------------------------------------------------- Medien
def _headlines(query: dict, now, limit: int) -> None:
    """Zeigt, was eine Suche liefert und wie das Programm jede Schlagzeile einordnet."""
    print(f"  Suche ({query.get('hl', 'de')}, {query.get('gl', 'AT')}): {query['q']}")
    try:
        items = news.fetch(query["q"] + " when:1d", query.get("hl", "de"), query.get("gl", "AT"), query.get("ceid"))
    except (HttpError, ET.ParseError) as err:
        print(f"  FEHLER: {err}")
        return
    language = query.get("hl", "de")
    kinds = {"lead": "Erstbericht", "cause": "Ursache", "follow": "Aufarbeitung"}
    items.sort(key=lambda item: item["when"], reverse=True)
    hits = sum(1 for item in items if news.relevant(item["title"], language))
    print(f"  {len(items)} Einträge, davon {hits} über einen Stromausfall")
    for item in items[:limit]:
        title = item["title"]
        kind = kinds[news.phase(title)] if news.relevant(title, language) else "–"
        people = news.count_people(title)
        age = int((now - item["when"]).total_seconds() // 60)
        print(f"    vor {age:>4} min | {kind:<12} | {','.join(gazetteer.find(title, language)) or '?':<10} "
              f"| {fmt_number(people) if people else '–':>9} | {item['domain']} | {title}")


def probe_news(cfg: dict, now) -> None:
    section = cfg["sources"]["news"]
    for query in section.get("priority_queries") or []:
        _headlines(query, now, limit=12)
        time.sleep(2)
    for query in section.get("world_queries") or []:
        _headlines(query, now, limit=25)
        time.sleep(2)


# ------------------------------------------------------------ Störmeldungen OÖ
def probe_utility(cfg: dict, now) -> None:
    text = _fetch(cfg["sources"]["utility"]["url"])
    if text is None:
        return
    for pattern in linznetz.BLOCKS:
        for block in pattern.findall(text):
            raw = re.sub(r"\s+", " ", block).strip()
            print(f"  Störungsbereich, {len(raw)} Zeichen:", raw[:3000] or "(leer)")
    found = linznetz.extract(text)
    if found is None:
        print("  Seite ist anders aufgebaut als erwartet: Störungsbereich nicht gefunden")
    elif found:
        print("  Störung gemeldet:", found[:1500])
    else:
        print("  keine Störung gemeldet")


# --------------------------------------------------------------------- ntfy
def probe_ntfy(cfg: dict, now) -> None:
    server = cfg["notify"]["ntfy"]["server"].rstrip("/")
    text = _fetch(f"{server}/v1/health", timeout=15)
    if text is not None:
        print("  Antwort:", text[:200])


PROBES = {
    "load": ("Stromlast (Energy-Charts)", probe_load),
    "frequency": ("Netzfrequenz", probe_frequency),
    "news": ("Medien (Google News)", probe_news),
    "utility": ("Störmeldungen LINZ NETZ", probe_utility),
    "ioda": ("Internet-Ausfälle (IODA)", probe_ioda),
    "ntfy": ("Push-Dienst ntfy", probe_ntfy),
}


# Läuft nur auf ausdrücklichen Wunsch (--only), weil es mehrere große Abfragen braucht.
EXTRAS = {
    "replay": ("Rückblick: Lastauswertung an echten Tagen", probe_replay),
}


def run(cfg: dict, now, only: list[str] | None = None) -> None:
    known = {**PROBES, **EXTRAS}
    unknown = sorted(set(only or []) - set(known))
    if unknown:
        print(f"Unbekannte Quelle: {', '.join(unknown)}. Möglich sind: {', '.join(known)}")
    print(f"Diagnose der Datenquellen, {iso(now)}")
    for name, (label, func) in known.items():
        if name not in (only or PROBES):
            continue
        print(f"\n===== {label} =====")
        try:
            func(cfg, now)
        except Exception:  # die Diagnose soll bei einer kaputten Quelle weiterlaufen
            traceback.print_exc()
