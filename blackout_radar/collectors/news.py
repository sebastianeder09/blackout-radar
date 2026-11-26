"""Medienberichte: bestätigen, dass Strom die Ursache ist, und liefern Hintergründe.

  Google News (RSS)  feste Suchen für Vorrang-Gebiete, z. B. Oberösterreich
  GDELT              weltweite Nachrichtensuche zu Gebieten, in denen gerade eine Störung läuft
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from .. import areas, http
from ..http import HttpError
from ..model import UTC, Signal, iso, parse_ts

SOURCE = "news"
POWER_WORDS = re.compile(
    r"blackout|power outage|power cut|outage|without power|electricity|load.?shedding|"
    r"stromausfall|stromausfälle|ohne strom|stromversorgung|strom weg|"
    r"apag[oó]n|corte de luz|corte de energ|apag[aã]o|panne de courant|panne d.électricité|"
    r"coupure de courant|stroomstoring|stroomuitval|strømbrud|strömavbrott|awaria prądu|"
    r"výpadek proudu|áramszünet|pană de curent|elektrik kesintisi|отключени|блэкаут|"
    r"відключенн|انقطاع الكهرباء|停电|停電|정전|mất điện|pemadaman listrik", re.IGNORECASE)
EXCLUDE = re.compile(
    r"vorsorge|übung|ratgeber|was tun|jahrestag|planspiel|simulation|checkliste|podcast|quiz|"
    r"testalarm|probealarm|vortrag|infoabend|blackout-gefahr|wie wahrscheinlich|"
    r"preparedness|drill|anniversary|how to prepare", re.IGNORECASE)
GDELT_TERMS = '(blackout OR "power outage" OR "power cut" OR Stromausfall OR apagón OR "load shedding")'


def _key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()[:120]


def google_news(query: dict, cfg: dict, now) -> list[Signal]:
    language, country = query.get("hl", "de"), query.get("gl", "AT")
    text = http.get_text("https://news.google.com/rss/search", timeout=20, params={
        "q": query["q"] + " when:1d", "hl": language, "gl": country, "ceid": f"{country}:{language}"})
    root = ET.fromstring(text)
    max_age = timedelta(minutes=cfg["max_age_minutes"])
    signals = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        if now - when > max_age or when > now + timedelta(minutes=10):
            continue
        if not POWER_WORDS.search(title) or EXCLUDE.search(title):
            continue
        signals.append(Signal(SOURCE, "news", query["area"], observed_at=when, active=False, detail=title,
                              url=(item.findtext("link") or "").strip(),
                              metrics={"domain": source, "power": True, "key": _key(title)}))
    return signals


def gdelt(cfg: dict, area: str, now) -> list[Signal]:
    names = " OR ".join(f'"{name}"' for name in areas.search_names(area))
    doc = http.get_json(cfg["gdelt_url"], timeout=30, params={
        "query": f"{GDELT_TERMS} ({names})", "mode": "artlist", "format": "json",
        "timespan": f"{cfg['max_age_minutes']}min", "maxrecords": 25, "sort": "datedesc"})
    signals = []
    for article in doc.get("articles") or []:
        title = (article.get("title") or "").strip()
        try:
            when = datetime.strptime(article.get("seendate") or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            when = now
        if not title or not POWER_WORDS.search(title) or EXCLUDE.search(title):
            continue
        signals.append(Signal(SOURCE, "news", area, observed_at=when, active=False, detail=title,
                              url=article.get("url") or "",
                              metrics={"domain": article.get("domain") or "", "power": True, "key": _key(title)}))
    return signals


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    signals, errors, attempts = [], [], 0
    for query in cfg.get("priority_queries") or []:
        attempts += 1
        try:
            signals += google_news(query, cfg, now)
        except (HttpError, ET.ParseError) as err:
            errors.append(f"Google News: {err}")
    todo = (context.get("active_areas") or [])[: cfg["max_areas_per_run"]]
    for index, area in enumerate(todo):
        attempts += 1
        if index:
            time.sleep(cfg.get("gdelt_pause_seconds", 6))  # GDELT erlaubt eine Anfrage alle 5 Sekunden
        try:
            signals += gdelt(cfg, area, now)
        except HttpError as err:
            errors.append(f"GDELT {area}: {err}")
    cursor["note"] = "; ".join(errors)
    if attempts > len(errors):
        cursor["data_time"] = iso(now)
    if attempts and len(errors) == attempts:
        raise HttpError("; ".join(errors))
    return signals
