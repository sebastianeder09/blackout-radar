"""Störmeldungen der LINZ NETZ GmbH (Linz und Umgebung, Teile des Mühlviertels).

Die öffentliche Seite "Aktuelle Störmeldungen" enthält einen Bereich, der nur bei
einer Störung gefüllt ist. Steht dort Text, gilt das als Störung in Oberösterreich
und der Text wird in die Meldung übernommen.

Vorsicht: Beim Einrichten war keine Störung aktiv. Wie die Seite eine echte Störung
darstellt, ist deshalb noch nicht an einem echten Fall geprüft. Die Quelle lässt sich
in der Konfiguration abschalten ([sources.utility] enabled = false).
"""
from __future__ import annotations

import html
import re

from .. import http
from ..http import HttpError
from ..model import Signal, iso, parse_ts
from .news import count_people

SOURCE = "utility"
AREA = "AT-4"
# Bereiche der Seite, die nur bei einer Störung Inhalt haben
BLOCKS = (
    re.compile(r"<!--\s*disturbance detail\s*-->(.*?)<!--\s*\./disturbance detail\s*-->", re.S | re.I),
    re.compile(r"<!--\s*disturbance\s*-->(.*?)<!--\s*\./disturbance\s*-->", re.S | re.I),
)
MAX_TEXT = 400


def extract(page: str) -> str | None:
    """Liefert den Text der Störmeldung, leer wenn keine vorliegt, None wenn die Seite anders aufgebaut ist."""
    found, texts = False, []
    for pattern in BLOCKS:
        for block in pattern.findall(page):
            found = True
            block = re.sub(r"<(script|style)\b.*?</\1>", " ", block, flags=re.S | re.I)
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", block))).strip()
            if text and text not in texts:
                texts.append(text)
    if not found:
        return None
    return " / ".join(texts)


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    page = http.get_text(cfg["url"], timeout=20)
    text = extract(page)
    if text is None:
        raise HttpError("Seite der LINZ NETZ ist anders aufgebaut als erwartet (Störungsbereich nicht gefunden)")
    cursor["data_time"] = iso(now)
    cursor["note"] = ""
    event = cursor.get("event")
    if not text:
        if event is None:
            return []
        del cursor["event"]
        return [Signal(SOURCE, "utility_outage", AREA, observed_at=now, active=False, severity=0.0,
                       started_at=parse_ts(event["start"]), ended_at=now,
                       detail="LINZ NETZ meldet keine Störung mehr")]
    if event is None:
        event = cursor["event"] = {"start": iso(now)}
    event["text"] = text[:MAX_TEXT]
    shown = text if len(text) <= MAX_TEXT else text[:MAX_TEXT].rstrip() + " …"
    people = count_people(text)
    population = 1_530_000
    severity = round(min(people, population) / population, 4) if people else None
    return [Signal(SOURCE, "utility_outage", AREA, observed_at=now, active=True, severity=severity,
                   started_at=parse_ts(event["start"]), confirmed_power=True, url=cfg["url"],
                   detail=f"LINZ NETZ meldet eine Störung: {shown}", metrics={"people": people})]
