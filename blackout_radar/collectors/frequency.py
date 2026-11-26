"""Netzfrequenz des Verbundnetzes Kontinentaleuropa (Soll 50,00 Hz).

Die Frequenz ist im ganzen Verbundnetz gleich. Eine Abweichung ab 200 mHz ist
selten und zeigt eine schwere Störung an, lange bevor Nachrichten erscheinen.

Anbieter in dieser Reihenfolge:
  energy_charts        Sekundenwerte, Messung Fraunhofer ISE Freiburg (CC BY 4.0).
                       Jeder Lauf holt alle Werte seit dem letzten Lauf, damit auch
                       kurze Einbrüche zwischen zwei Läufen nicht verloren gehen.
  netzfrequenzmessung  ein aktueller Wert als XML (laut Anbieter für privaten Gebrauch).
                       Nur Ersatz: zwischen zwei Läufen sieht dieser Weg nichts.
"""
from __future__ import annotations

import statistics
import xml.etree.ElementTree as ET
from datetime import timedelta

from .. import http
from ..http import HttpError
from ..model import Signal, iso, parse_ts

SOURCE = "frequency"
AREA = "EU-CE"

# Schwellen laut FNN-Beispielplan zur automatischen Frequenzentlastung (Quelle: netzfrequenzmessung.de)
STAGES = [
    (47.5, "Kraftwerke trennen sich vom Netz"),
    (48.4, "automatischer Lastabwurf Stufe 4, rund 50 % der Last"),
    (48.6, "automatischer Lastabwurf Stufe 3, rund 37,5 % der Last"),
    (48.8, "automatischer Lastabwurf Stufe 2, rund 25 % der Last"),
    (49.0, "automatischer Lastabwurf Stufe 1, rund 12,5 % der Last"),
    (49.2, "Abwurf von Speicherpumpen"),
    (49.8, "Aktivierung der Leistungsreserven"),
]


def stage_text(freq: float) -> str:
    for limit, text in STAGES:
        if freq <= limit:
            return text
    return "Überfrequenz, zu viel Einspeisung im Netz" if freq >= 50.2 else ""


def hz(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def _fmt(when) -> str:
    return when.strftime("%Y-%m-%dT%H:%MZ")


def _smooth(rows: list) -> list:
    """Gleitender Median über 5 Sekundenwerte, damit einzelne Messfehler keinen Alarm auslösen."""
    if len(rows) < 5:
        return rows
    values = [value for _, value in rows]
    return [(rows[i][0], statistics.median(values[max(0, i - 2): i + 3])) for i in range(len(rows))]


def _sample(rows: list, cfg: dict) -> dict:
    """Fasst Messwerte (Zeit, Hz) zu einem Befund zusammen."""
    alarm, clear = cfg["alarm_mhz"] / 1000.0, cfg["clear_mhz"] / 1000.0
    low, high = min(rows, key=lambda r: r[1]), max(rows, key=lambda r: r[1])
    return {
        "t": rows[-1][0], "f": rows[-1][1], "n": len(rows),
        "min": low[1], "t_min": low[0], "max": high[1], "t_max": high[0],
        "t_breach": next((t for t, v in rows if abs(v - 50.0) >= alarm), None),    # erste Verletzung der Alarmgrenze
        "t_uneasy": next((t for t, v in reversed(rows) if abs(v - 50.0) >= clear), None),  # zuletzt außerhalb der Ruhegrenze
    }


def from_energy_charts(cfg: dict, cursor: dict, now) -> dict:
    base = cfg["energy_charts_url"].rstrip("/")
    seen = parse_ts(cursor.get("ec_last"))
    start = now - timedelta(minutes=cfg["window_minutes"])
    if seen:
        start = max(seen - timedelta(seconds=30), now - timedelta(minutes=cfg["catchup_minutes"]))
    doc = http.get_json(f"{base}/v2/frequency", timeout=30, params={
        "region": cfg["energy_charts_region"], "start": _fmt(start), "end": _fmt(now + timedelta(minutes=1))})
    rows = []
    for row in doc.get("data") or []:
        value = (row.get("values") or {}).get("frequency")
        when = parse_ts(row.get("timestamp"))
        if value is not None and when is not None and 45.0 <= float(value) <= 55.0:
            rows.append((when, float(value)))
    if not rows:
        raise HttpError("Energy-Charts lieferte keine Frequenzwerte")
    rows.sort()
    newest = rows[-1][0]
    if now - newest > timedelta(minutes=cfg["max_age_minutes"]):
        raise HttpError(f"Frequenzdaten von Energy-Charts veraltet (Stand {iso(newest)})")
    fresh = [row for row in _smooth(rows) if seen is None or row[0] > seen] or [rows[-1]]
    cursor["ec_last"] = iso(newest)
    return _sample(fresh, cfg)


def from_netzfrequenzmessung(cfg: dict, cursor: dict, now) -> dict:
    text = http.get_text(cfg["nfm_url"], timeout=10)
    root = ET.fromstring(text)
    try:
        value = float((root.findtext("f") or "").replace(",", "."))
    except ValueError:
        raise HttpError("netzfrequenzmessung.de lieferte keinen Frequenzwert") from None
    when = parse_ts(root.findtext("z"))
    if not 45.0 <= value <= 55.0:
        raise HttpError(f"unplausibler Frequenzwert {value}")
    if when is None or now - when > timedelta(minutes=cfg["max_age_minutes"]):
        raise HttpError("Frequenzwert von netzfrequenzmessung.de veraltet")
    return _sample([(when, value)], cfg)


PROVIDERS = {"energy_charts": from_energy_charts, "netzfrequenzmessung": from_netzfrequenzmessung}


def analyse(sample: dict, cfg: dict, cursor: dict) -> list[Signal]:
    clear = cfg["clear_mhz"] / 1000.0
    low, high = 50.0 - sample["min"], sample["max"] - 50.0
    worst_hz = sample["min"] if low >= high else sample["max"]
    event = cursor.get("event")
    fresh = False
    if sample["t_breach"] is not None:
        if event is None:
            event = cursor["event"] = {"start": iso(sample["t_breach"]), "worst_hz": worst_hz}
            fresh = True
        elif abs(worst_hz - 50.0) > abs(event["worst_hz"] - 50.0):
            event["worst_hz"] = worst_hz
    if event is None:
        return []
    if sample["t_uneasy"] is not None:
        event["uneasy"] = iso(sample["t_uneasy"])
    worst = event["worst_hz"]
    start = parse_ts(event["start"])
    uneasy = parse_ts(event.get("uneasy")) or start
    metrics = {"worst_hz": worst, "current_hz": sample["f"], "provider": sample.get("provider", "")}
    # Ein kurzer Einbruch ist oft schon vorbei, wenn er entdeckt wird. Er wird trotzdem zuerst
    # als Alarm gemeldet und erst im nächsten Lauf als beendet.
    calm = abs(sample["f"] - 50.0) < clear and sample["t"] - uneasy >= timedelta(minutes=cfg["calm_minutes"])
    if calm and not fresh:
        del cursor["event"]
        return [Signal(SOURCE, "frequency", AREA, observed_at=sample["t"], active=False, severity=0.0,
                       started_at=start, ended_at=max(uneasy, start), metrics=metrics,
                       detail=f"Netzfrequenz wieder bei {hz(sample['f'])} Hz, größte Abweichung war {hz(worst)} Hz")]
    detail = (f"Netzfrequenz {hz(worst)} Hz statt 50,000 Hz "
              f"(Alarmgrenze ±{cfg['alarm_mhz']} mHz), aktuell {hz(sample['f'])} Hz")
    stage = stage_text(worst)
    if stage:
        detail += f". Stufe laut Notfallplan: {stage}"
    return [Signal(SOURCE, "frequency", AREA, observed_at=sample["t"], active=True,
                   severity=round(min(1.0, abs(worst - 50.0)), 3), started_at=start, detail=detail, metrics=metrics)]


def remember(cursor: dict, sample: dict) -> None:
    """Merkt sich je Stunde den kleinsten und größten Wert, für die Spanne der letzten 24 Stunden."""
    hours = cursor.setdefault("hours", {})
    key = iso(sample["t"])[:13]
    low, high = hours.get(key) or (sample["min"], sample["max"])
    hours[key] = [min(low, sample["min"]), max(high, sample["max"])]
    for old in sorted(hours)[:-25]:
        del hours[old]


def day_range(cursor: dict, now) -> tuple[float, float] | None:
    limit = iso(now - timedelta(hours=24))[:13]
    spans = [span for key, span in (cursor.get("hours") or {}).items() if key >= limit]
    if not spans:
        return None
    return min(span[0] for span in spans), max(span[1] for span in spans)


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    sample, errors = None, []
    for provider in cfg["providers"]:
        func = PROVIDERS.get(provider)
        if func is None:
            continue
        try:
            sample = func(cfg, cursor, now)
            sample["provider"] = provider
            break
        except (HttpError, ET.ParseError) as err:
            errors.append(f"{provider}: {err}")
    cursor["note"] = "; ".join(errors)
    if sample is None:
        raise HttpError("; ".join(errors) or "kein Frequenz-Anbieter eingestellt")
    cursor["data_time"] = iso(sample["t"])
    cursor["last"] = {"hz": sample["f"], "min": sample["min"], "max": sample["max"], "t": iso(sample["t"]),
                      "provider": sample["provider"], "n": sample["n"]}
    remember(cursor, sample)
    return analyse(sample, cfg, cursor)
