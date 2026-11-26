"""Diagnose: fragt jede Datenquelle einmal roh ab und zeigt, was zurückkommt.

Aufruf:  python -m blackout_radar probe [--only load,frequency,ioda,news,utility,ntfy]

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

from . import http
from .http import HttpError
from .model import iso, parse_ts


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


def _fetch(url: str, params: dict | None = None, timeout: float = 30) -> str | None:
    shown = url + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
    print(f"  GET {shown}")
    try:
        status, head, body = http.request(url, params=params, timeout=timeout)
    except HttpError as err:
        print(f"  FEHLER: {err}")
        return None
    print(f"  HTTP {status}, {head.get('Content-Type', '?')}, {len(body)} Bytes")
    return body.decode("utf-8", errors="replace")


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
def probe_load(cfg: dict, now) -> None:
    base = cfg["sources"]["load"]["base_url"].rstrip("/")
    doc = _json(_fetch(f"{base}/v2/public_power", {
        "country": "at", "start": _fmt(now - timedelta(hours=5)), "end": _fmt(now)}))
    if not isinstance(doc, dict):
        return
    print("  Kopf:", {k: v for k, v in doc.items() if k not in ("data", "series")})
    print("  Reihen:", outline(doc.get("series"), limit=2))
    rows = doc.get("data") or []
    loads = [(row.get("timestamp"), (row.get("values") or {}).get("load")) for row in rows]
    print(f"  {len(rows)} Zeilen, letzte 10 Lastwerte:", loads[-10:])
    known = [(t, v) for t, v in loads if v is not None]
    if known:
        print(f"  letzter Lastwert {known[-1]}, Verzögerung {now - parse_ts(known[-1][0])}")


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

    if call("/entities/query", {"entityType": "country", "entityCode": "AT"}, timeout=90) is None:
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
def probe_news(cfg: dict, now) -> None:
    section = cfg["sources"]["news"]
    for query in section.get("priority_queries") or []:
        language, country = query.get("hl", "de"), query.get("gl", "AT")
        text = _fetch("https://news.google.com/rss/search", {
            "q": query["q"] + " when:7d", "hl": language, "gl": country, "ceid": f"{country}:{language}"})
        if text is None:
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError as err:
            print(f"  kein XML ({err}): {text[:300]!r}")
            continue
        items = list(root.iter("item"))
        print(f"  {len(items)} Einträge")
        for item in items:
            print(f"    {item.findtext('pubDate')} | {item.findtext('title')}")
    text = _fetch("https://news.google.com/rss/search", {
        "q": '("power outage" OR blackout OR "power cut" OR "without power") Cuba when:7d',
        "hl": "en-US", "gl": "US", "ceid": "US:en"})
    if text is not None:
        try:
            items = list(ET.fromstring(text).iter("item"))
            print(f"  {len(items)} Einträge")
            for item in items[:12]:
                print(f"    {item.findtext('pubDate')} | {item.findtext('title')}")
        except ET.ParseError as err:
            print(f"  kein XML ({err}): {text[:300]!r}")
    for attempt in (1, 2):
        doc = _json(_fetch(section["gdelt_url"], {
            "query": '(blackout OR "power outage" OR Stromausfall) (Austria OR Österreich)', "mode": "artlist",
            "format": "json", "timespan": "2880min", "maxrecords": 5, "sort": "datedesc"}))
        if doc is not None:
            print("  Aufbau:", outline(doc))
            for article in (doc.get("articles") or [])[:3] if isinstance(doc, dict) else []:
                print("   ", article)
            break
        time.sleep(8)


# ----------------------------------------------------------- Netzbetreiber OÖ
UTILITY_PAGES = (
    "https://status.netzooe.at/",
    "https://status.netzooe.at/netzweb/SpannungsloseStationen.html",
    "https://www.linznetz.at/portal/de/home/online_services/aktuelle_stoermeldungen",
)


STATIC = (".css", ".png", ".jpg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".map")


def _paths(text: str) -> list[str]:
    """Adressen und Pfade, die in einem Skript oder einer Seite vorkommen."""
    found = set(re.findall(r"""["'`]((?:https?:)?/{1,2}[A-Za-z0-9_\-./?=&%{}$:]{3,200})["'`]""", text))
    return sorted(item for item in found if not item.lower().split("?")[0].endswith(STATIC))


def probe_utility(cfg: dict, now) -> None:
    for url in UTILITY_PAGES:
        text = _fetch(url)
        if text is None:
            continue
        if len(text) < 6000:
            print("  Rohtext:", text)
            host = "/".join(url.split("/")[:3])
            scripts = sorted(set(re.findall(r"""([A-Za-z0-9_\-./]+\.js)\b""", text)))
            print("  Skripte:", scripts)
            for script in scripts[:6]:
                target = script if script.startswith("http") else host + "/" + script.lstrip("./")
                if not target.startswith(host):
                    print("  übersprungen (anderer Server):", target)
                    continue
                code = _fetch(target)
                if code is None:
                    continue
                paths = _paths(code)
                print(f"  {len(paths)} Adressen im Skript:")
                for item in paths[:120]:
                    print("     ", item[:200])
            continue
        body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
        index = body.rfind("Aktuelle Störmeldungen")
        print("  Inhalt ab der letzten Überschrift:", body[max(0, index - 100): index + 3000])
        for marker in ("stoermeldung", "Störung", "ui-datatable", "<table"):
            hits = [m.start() for m in re.finditer(marker, text)]
            print(f"  '{marker}': {len(hits)} Treffer")
        table = re.search(r"<table.*?</table>", text, re.S | re.I)
        if table:
            print("  erste Tabelle:", re.sub(r"\s+", " ", table.group(0))[:2500])


# --------------------------------------------------------------------- ntfy
def probe_ntfy(cfg: dict, now) -> None:
    server = cfg["notify"]["ntfy"]["server"].rstrip("/")
    text = _fetch(f"{server}/v1/health", timeout=15)
    if text is not None:
        print("  Antwort:", text[:200])


PROBES = {
    "load": ("Stromlast (Energy-Charts)", probe_load),
    "frequency": ("Netzfrequenz", probe_frequency),
    "ioda": ("Internet-Ausfälle (IODA)", probe_ioda),
    "news": ("Medien (Google News, GDELT)", probe_news),
    "utility": ("Netzbetreiber Oberösterreich", probe_utility),
    "ntfy": ("Push-Dienst ntfy", probe_ntfy),
}


def run(cfg: dict, now, only: list[str] | None = None) -> None:
    print(f"Diagnose der Datenquellen, {iso(now)}")
    for name, (label, func) in PROBES.items():
        if only and name not in only:
            continue
        print(f"\n===== {label} =====")
        try:
            func(cfg, now)
        except Exception:  # die Diagnose soll bei einer kaputten Quelle weiterlaufen
            traceback.print_exc()


if __name__ == "__main__":
    import sys

    from . import config
    from .model import now_utc

    chosen = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    run(config.load("config.toml"), now_utc(), chosen)
