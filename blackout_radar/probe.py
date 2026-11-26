"""Diagnose: fragt jede Datenquelle einmal roh ab und zeigt, was zurückkommt.

Aufruf:  python -m blackout_radar probe [--only load,frequency,news,utility,ioda,ntfy]

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
from .collectors import linznetz, news
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
    section = cfg["sources"]["load"]
    base = section["base_url"].rstrip("/")
    for index, country in enumerate(section["countries"]):
        if index:
            time.sleep(1)
        doc = _json(_fetch(f"{base}/v2/public_power", {
            "country": country, "start": _fmt(now - timedelta(hours=5)), "end": _fmt(now)}))
        if not isinstance(doc, dict):
            continue
        rows = doc.get("data") or []
        loads = [(row.get("timestamp"), (row.get("values") or {}).get("load")) for row in rows]
        known = [(t, v) for t, v in loads if v]
        if index == 0:  # das erste Land ausführlich, die übrigen in einer Zeile
            print("  Kopf:", {k: v for k, v in doc.items() if k not in ("data", "series")})
            print("  Reihen:", outline(doc.get("series"), limit=2))
            print(f"  {len(rows)} Zeilen, letzte 10 Lastwerte:", loads[-10:])
        if known:
            print(f"  {country}: {len(known)} Lastwerte, letzter {known[-1][1]} MW von {known[-1][0]}, "
                  f"Verzögerung {now - parse_ts(known[-1][0])}")
        else:
            print(f"  {country}: KEINE Lastwerte in {len(rows)} Zeilen")


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
    items.sort(key=lambda item: item["when"], reverse=True)
    hits = sum(1 for item in items if news.relevant(item["title"]))
    print(f"  {len(items)} Einträge, davon {hits} über einen Stromausfall")
    for item in items[:limit]:
        title = item["title"]
        kind = "–" if not news.relevant(title) else "Erstbericht" if news.is_lead(title) else "Folgebericht"
        people = news.count_people(title)
        age = int((now - item["when"]).total_seconds() // 60)
        print(f"    vor {age:>4} min | {kind:<12} | {','.join(gazetteer.find(title)) or '?':<10} "
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


def run(cfg: dict, now, only: list[str] | None = None) -> None:
    unknown = sorted(set(only or []) - set(PROBES))
    if unknown:
        print(f"Unbekannte Quelle: {', '.join(unknown)}. Möglich sind: {', '.join(PROBES)}")
    print(f"Diagnose der Datenquellen, {iso(now)}")
    for name, (label, func) in PROBES.items():
        if only and name not in only:
            continue
        print(f"\n===== {label} =====")
        try:
            func(cfg, now)
        except Exception:  # die Diagnose soll bei einer kaputten Quelle weiterlaufen
            traceback.print_exc()
