"""Vorläufige Diagnose: Was läuft außerhalb Europas, und welche Quellen aus Übersee taugen?

Nur zum Messen aus GitHub Actions gedacht. Es werden keine Zugangsdaten gelesen oder ausgegeben.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blackout_radar import config, gazetteer, http, probe  # noqa: E402
from blackout_radar.collectors import news  # noqa: E402
from blackout_radar.http import HttpError  # noqa: E402
from blackout_radar.model import UTC, now_utc, parse_ts  # noqa: E402

STARTED = time.monotonic()
BUDGET = 8.5 * 60  # Sekunden, danach werden weitere Abschnitte übersprungen

HOSTS = [
    ("Push ntfy", "ntfy.sh", 443),
    ("Netzfrequenz/Stromlast Energy-Charts", "api.energy-charts.info", 443),
    ("Netzfrequenz netzfrequenzmessung.de", "dat.netzfrequenzmessung.de", 9080),
    ("LINZ NETZ", "www.linznetz.at", 443),
    ("Google News", "news.google.com", 443),
    ("IODA", "api.ioda.inetintel.cc.gatech.edu", 443),
    ("GDELT", "api.gdeltproject.org", 443),
    ("Bing", "www.bing.com", 443),
    ("GitHub API", "api.github.com", 443),
    ("GitHub Rohdaten", "raw.githubusercontent.com", 443),
    ("Cloudflare API", "api.cloudflare.com", 443),
]

FEEDS = [
    ("en", "NYT World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("en", "NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("en", "Washington Post World", "https://feeds.washingtonpost.com/rss/world"),
    ("en", "CBS World", "https://www.cbsnews.com/latest/rss/world"),
    ("en", "ABC News International", "https://abcnews.go.com/abcnews/internationalheadlines"),
    ("en", "NBC News", "https://feeds.nbcnews.com/nbcnews/public/news"),
    ("en", "Fox World", "https://moxie.foxnews.com/google-publisher/world.xml"),
    ("en", "CBC World", "https://www.cbc.ca/webfeed/rss/rss-world"),
    ("en", "Global News World", "https://globalnews.ca/world/feed/"),
    ("en", "ABC Australia", "https://www.abc.net.au/news/feed/51120/rss.xml"),
    ("en", "SMH World", "https://www.smh.com.au/rss/world.xml"),
    ("en", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("en", "Times of India World", "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms"),
    ("en", "The Hindu International", "https://www.thehindu.com/news/international/feeder/default.rss"),
    ("en", "NDTV World", "https://feeds.feedburner.com/ndtvnews-world-news"),
    ("en", "Japan Times", "https://www.japantimes.co.jp/feed/"),
    ("en", "SCMP World", "https://www.scmp.com/rss/5/feed"),
    ("en", "Straits Times World", "https://www.straitstimes.com/news/world/rss.xml"),
    ("en", "CNA World", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6311"),
    ("en", "Yonhap", "https://en.yna.co.kr/RSS/news.xml"),
    ("en", "News24 World", "https://feeds.24.com/articles/news24/World/rss"),
    ("pt", "Folha Mundo", "https://feeds.folha.uol.com.br/mundo/rss091.xml"),
    ("pt", "G1 Mundo", "https://g1.globo.com/rss/g1/mundo/"),
    ("es", "Clarín Mundo", "https://www.clarin.com/rss/mundo/"),
    ("es", "El Universal Mundo", "https://www.eluniversal.com.mx/arc/outboundfeeds/rss/section/mundo/?outputType=xml"),
    ("es", "Infobae América", "https://www.infobae.com/arc/outboundfeeds/rss/category/america/"),
    ("en", "BBC World (zum Vergleich, Europa)", "https://feeds.bbci.co.uk/news/world/rss.xml"),
]


def left() -> float:
    return BUDGET - (time.monotonic() - STARTED)


def head(title: str) -> None:
    print(f"\n===== {title} ===== (Restzeit {left():.0f} s)", flush=True)


def get(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 15):
    try:
        status, head_, body = http.request(url, params=params, headers=headers, timeout=timeout)
        return status, head_, body
    except HttpError as err:
        print(f"  FEHLER {url[:90]}: {err}" + (f" | {err.body[:160]}" if err.body else ""))
        return None, {}, b""


# ------------------------------------------------------------------ Standort des Rechners
def standort() -> None:
    head("Standort dieses Rechners")
    status, _, body = get("https://api.ipify.org", timeout=8)
    if status:
        address = body.decode().strip()
        print("  öffentliche Adresse:", address, "|", wo(address))


def wo(address: str) -> str:
    """Ort einer Adresse laut ipinfo.io (ohne Anmeldung, nur für diese Diagnose)."""
    try:
        status, _, body = http.request(f"https://ipinfo.io/{address}/json", timeout=8)
        doc = json.loads(body)
        return ", ".join(str(doc.get(key)) for key in ("city", "region", "country", "org") if doc.get(key))
    except (HttpError, ValueError) as err:
        return f"ipinfo: {err}"


# ---------------------------------------------------------------------------- Hosts
def connect_ms(address: str, port: int, family) -> float | None:
    best = None
    for _ in range(3):
        started = time.monotonic()
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((address, port))
        except OSError:
            continue
        took = (time.monotonic() - started) * 1000
        best = took if best is None else min(best, took)
    return best


def hosts() -> dict:
    head("Dienste: Adressen, Ort laut ipinfo.io, Verbindungsaufbau von hier")
    found = {}
    for label, host, port in HOSTS:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as err:
            print(f"  {label} ({host}): nicht auflösbar ({err})")
            continue
        addresses = list(dict.fromkeys((info[0], info[4][0]) for info in infos))
        found[host] = [address for _, address in addresses]
        print(f"  {label} ({host}:{port})")
        for family, address in addresses[:3]:
            took = connect_ms(address, port, family)
            place = wo(address)
            print(f"      {address:<40} {'keine Verbindung' if took is None else f'{took:6.1f} ms':<17} {place}")
    return found


def digitalocean(addresses: list) -> None:
    head("ntfy.sh im Geofeed von DigitalOcean")
    status, _, body = get("https://digitalocean.com/geo/google.csv", timeout=30)
    if not status:
        return
    rows = [line.split(",") for line in body.decode("utf-8", errors="replace").splitlines() if line.strip()]
    print(f"  {len(rows)} Zeilen im Geofeed")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        hits = []
        for row in rows:
            try:
                if ip in ipaddress.ip_network(row[0].strip(), strict=False):
                    hits.append(row)
            except ValueError:
                continue
        print(f"  {address}: {hits or 'nicht im Geofeed'}")


def ntfy() -> None:
    head("ntfy.sh: Antwort und Kopfzeilen")
    status, head_, body = get("https://ntfy.sh/v1/health", timeout=15)
    if status:
        print(f"  HTTP {status}: {body[:120]!r}")
        print("  Kopfzeilen:", {k: v for k, v in head_.items()
                               if k.lower() in ("server", "via", "cf-ray", "x-served-by", "alt-svc", "date")})


# ---------------------------------------------------------------------------- Feeds
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"


def parse_feed(text: str) -> list:
    root = ET.fromstring(text)
    items = []
    for node in list(root.iter("item")) + list(root.iter(f"{ATOM}entry")):
        title = (node.findtext("title") or node.findtext(f"{ATOM}title") or "").strip()
        stamp = (node.findtext("pubDate") or node.findtext(f"{DC}date") or node.findtext(f"{ATOM}updated")
                 or node.findtext(f"{ATOM}published") or "")
        when = None
        try:
            when = parsedate_to_datetime(stamp)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            when = parse_ts(stamp)
        items.append((when, " ".join(title.split())))
    return items


def feeds(now) -> None:
    head("Nachrichten-Feeds aus Übersee")
    for language, label, url in FEEDS:
        if left() < 240:
            print("  Zeit knapp, restliche Feeds übersprungen")
            return
        started = time.monotonic()
        status, head_, body = get(url, timeout=15)
        if not status:
            continue
        try:
            items = parse_feed(body.decode("utf-8", errors="replace"))
        except ET.ParseError as err:
            print(f"  {label}: HTTP {status}, {len(body)} Bytes, kein gültiges XML ({err}) | {body[:80]!r}")
            continue
        dated = sorted((when for when, _ in items if when), reverse=True)
        newest = f"neuester vor {int((now - dated[0]).total_seconds() // 60)} min" if dated else "ohne Datum"
        oldest = f", ältester vor {int((now - dated[-1]).total_seconds() // 3600)} h" if dated else ""
        hits = [title for _, title in items if news.relevant(title, language)]
        cache = {k: v for k, v in head_.items() if k.lower() in ("etag", "last-modified", "cache-control")}
        print(f"  {label}: HTTP {status}, {len(body)} Bytes in {time.monotonic() - started:.1f} s, {len(items)} Einträge, "
              f"{newest}{oldest}, {len(hits)} über Stromausfall | {cache}")
        for _, title in items[:2]:
            print(f"      {title[:140]}")
        for title in hits[:4]:
            print(f"      TREFFER [{news.phase(title)}] {gazetteer.find(title, language)} {title[:160]}")


def gdelt(now) -> None:
    head("GDELT DOC 2.0")
    queries = [
        '(blackout OR "power outage" OR "grid collapse" OR "without power") sourcelang:english',
        '(Stromausfall OR "ohne Strom") sourcelang:german',
        '(Stromausfall OR "ohne Strom") sourcecountry:austria',
    ]
    for index, query in enumerate(queries):
        if index:
            time.sleep(6)  # der Dienst bittet um höchstens eine Abfrage alle 5 Sekunden
        started = time.monotonic()
        status, head_, body = get("https://api.gdeltproject.org/api/v2/doc/doc", timeout=30, params={
            "query": query, "mode": "artlist", "format": "json", "timespan": "1d", "maxrecords": 40,
            "sort": "datedesc"})
        if not status:
            continue
        print(f"  {query}: HTTP {status}, {len(body)} Bytes in {time.monotonic() - started:.1f} s, "
              f"{head_.get('Content-Type')}")
        try:
            rows = json.loads(body).get("articles") or []
        except ValueError:
            print("    kein JSON:", body[:200])
            continue
        print(f"    {len(rows)} Artikel. Felder: {sorted(rows[0]) if rows else '-'}")
        for row in rows[:6]:
            print(f"      {row.get('seendate')} | {row.get('sourcecountry')} | {row.get('language')} | "
                  f"{row.get('domain')} | {str(row.get('title'))[:120]}")


def bing(now) -> None:
    head("Bing News als RSS")
    for query, market in (("Stromausfall Österreich", "de-AT"), ('"power outage" OR blackout', "en-US")):
        status, head_, body = get("https://www.bing.com/news/search", timeout=20,
                                  params={"q": query, "format": "rss", "setmkt": market})
        if not status:
            continue
        text = body.decode("utf-8", errors="replace")
        try:
            items = parse_feed(text)
        except ET.ParseError as err:
            print(f"  {query}: HTTP {status}, {len(body)} Bytes, kein XML ({err}) | {text[:120]!r}")
            continue
        print(f"  {query}: HTTP {status}, {len(body)} Bytes, {len(items)} Einträge")
        for when, title in items[:6]:
            print(f"      {when} | {title[:130]}")


# ----------------------------------------------------------------------------- IODA
def ioda(cfg: dict, now) -> None:
    head("IODA: Diagnose des Programms")
    probe.probe_ioda(cfg, now)
    if left() < 60:
        return
    head("IODA: mehrere Länder in einer Abfrage, Alarme der letzten 7 Tage")
    base = cfg["sources"]["ioda"]["base_url"].rstrip("/")
    until = int(now.timestamp())
    for path, params in (
        ("/signals/raw/country/AT,DE,CH,IT,CZ,SK,HU,SI", {"from": until - 3 * 3600, "until": until,
                                                         "datasource": "ping-slash24"}),
        ("/outages/alerts", {"from": until - 7 * 86400, "until": until, "entityType": "country", "limit": 2000}),
        ("/outages/alerts", {"from": until - 7 * 86400, "until": until, "entityType": "country",
                             "relatedTo": "country/AT", "limit": 50}),
        ("/outages/events", {"from": until - 7 * 86400, "until": until, "entityType": "country", "limit": 20,
                             "includeAlerts": "false", "format": "ioda"}),
    ):
        if left() < 45:
            print("  Zeit knapp, Rest übersprungen")
            return
        started = time.monotonic()
        status, _, body = get(base + path, params=params, timeout=40)
        if not status:
            continue
        print(f"  {path} {params}: HTTP {status}, {len(body)} Bytes in {time.monotonic() - started:.1f} s")
        try:
            doc = json.loads(body)
        except ValueError:
            print("    kein JSON:", body[:200])
            continue
        print("    Aufbau:", probe.outline(doc))
        rows = probe._flatten(doc.get("data") if isinstance(doc, dict) else doc)
        if "signals/raw" in path:
            for row in rows[:12]:
                values = row.get("values") or []
                print("    Reihe:", {k: v for k, v in row.items() if k != "values"},
                      f"| {len(values)} Werte, letzte: {values[-4:]}")
        elif "alerts" in path:
            counts: dict = {}
            for row in rows:
                key = ((row.get("entity") or {}).get("code"), row.get("datasource"), row.get("level"))
                counts[key] = counts.get(key, 0) + 1
            print(f"    {len(rows)} Alarme, {len({key[0] for key in counts})} Länder")
            for key, count in sorted(counts.items(), key=lambda item: -item[1])[:25]:
                print(f"      {key}: {count}")
            for row in rows[-4:]:
                print("    Beispiel:", json.dumps(row, ensure_ascii=False)[:500])
        else:
            for row in rows[:5]:
                print("    Ereignis:", json.dumps(row, ensure_ascii=False)[:500])


def main() -> int:
    cfg = config.load("config.toml", env={})
    now = now_utc()
    print("Diagnose außerhalb Europas,", now.isoformat(timespec="seconds"))
    steps = [("standort", standort), ("hosts", None), ("ntfy", ntfy), ("feeds", lambda: feeds(now)),
             ("gdelt", lambda: gdelt(now)), ("bing", lambda: bing(now)), ("ioda", lambda: ioda(cfg, now))]
    for name, func in steps:
        try:
            if name == "hosts":
                found = hosts()
                digitalocean(found.get("ntfy.sh") or [])
            else:
                func()
        except Exception:  # die Diagnose soll weiterlaufen
            traceback.print_exc()
    print(f"\nFertig nach {time.monotonic() - STARTED:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
