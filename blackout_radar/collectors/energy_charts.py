"""Stromlast je Land von Energy-Charts (Fraunhofer ISE, Daten von ENTSO-E, CC BY 4.0).

Die Lastdaten kommen mit zwei bis fünf Stunden Verzögerung. Sie eignen sich deshalb
nicht für den ersten Alarm, aber als Bestätigung ("es ist wirklich Strom") und um
den Netzwiederaufbau zu verfolgen, solange der Netzbetreiber weiter meldet.

Erwartungswert: die Last zur selben Uhrzeit an drei Vergleichstagen (gestern, vorgestern,
derselbe Wochentag der Vorwoche), jeweils angepasst um das Niveau der letzten Stunden
(Wetter, Feiertag). Als Einbruch zählt nur, was gegenüber allen Vergleichstagen fehlt.
Ein einzelner Vergleichstag führt in die Irre: Der Samstag nach einem heißen Freitag
sieht sonst wie ein Ausfall aus, ebenso der Tag nach einem echten Ausfall.

Was echte Daten gezeigt haben (tests/data/lastreihen.json, tests/test_real_load.py):
  - Die neuesten Werte sind manchmal erst zum Teil gemeldet und werden später ergänzt.
    Sie zählen deshalb erst, wenn sie eine halbe Stunde alt sind (settle_minutes).
  - Bei einem großen Ausfall können die Werte ganz ausbleiben: In Spanien fehlten sie
    am 28.04.2025 ab Beginn des Ausfalls eineinhalb Tage lang. Dann gibt es von hier
    keinen Befund, der Lagebericht zeigt "keine neuen Werte seit ...".
  - Portugal (28.04.2025), Tschechien (04.07.2025) und Bosnien und Montenegro (21.06.2024)
    haben weiter gemeldet: Beginn, Tiefe und Wiederaufbau sind dort in den Werten zu sehen.
"""
from __future__ import annotations

import bisect
import functools
import statistics
from datetime import timedelta

from .. import http
from ..http import HttpError
from ..model import Signal, fmt_pct, iso, parse_ts

SOURCE = "load"
REFERENCE_DAYS = (1, 2, 7)  # Vergleichstage: gestern, vorgestern, derselbe Wochentag der Vorwoche
MAX_SLOTS = 5000            # größte Reihe, die als Raster gespeichert wird


@functools.lru_cache(maxsize=60_000)
def _when(stamp: str):
    return parse_ts(stamp)


def _fmt(when) -> str:
    return when.strftime("%Y-%m-%dT%H:%MZ")


def _mw(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def area_code(country: str) -> str:
    return "GB" if country.lower() == "uk" else country.upper()


# ------------------------------------------------------------------- Abruf
def to_points(doc: dict) -> list:
    """Lastwerte einer Antwort als [Zeit, MW], nach Zeit geordnet. Fehlende Werte (leer oder 0) entfallen."""
    points = []
    for row in doc.get("data") or []:
        value = (row.get("values") or {}).get("load")
        when = parse_ts(row.get("timestamp"))
        if value and when is not None and float(value) > 0:
            points.append([iso(when), float(value)])
    points.sort()
    return points


def fetch_load(base: str, country: str, now, hours: int) -> list:
    doc = http.get_json(f"{base}/v2/public_power", timeout=30, params={
        "country": country, "start": _fmt(now - timedelta(hours=hours)), "end": _fmt(now)})
    points = to_points(doc)
    if not points:
        raise HttpError(f"keine Lastdaten für {country}")
    return points


def merge(known: list, fresh: list, now, hours: int, keep_hours: int) -> list:
    """Setzt neu abgerufene Werte in die gespeicherte Reihe ein.

    Im abgerufenen Zeitraum gilt nur die neue Antwort (Werte können nachträglich verschwinden),
    ältere Werte bleiben, bis sie aus dem Verlauf fallen.
    """
    since, oldest = iso(now - timedelta(hours=hours)), iso(now - timedelta(hours=keep_hours))
    return [point for point in known if oldest <= point[0] < since] + [p for p in fresh if p[0] >= oldest]


def pack(points: list):
    """Reihe platzsparend für den gespeicherten Zustand: Beginn, Raster in Minuten und Werte."""
    if len(points) < 2:
        return points
    times = [_when(stamp) for stamp, _ in points]
    step = min(later - earlier for earlier, later in zip(times, times[1:], strict=False))
    slots = (times[-1] - times[0]) / step + 1 if step > timedelta(0) else 0
    if not 0 < slots <= MAX_SLOTS or any((when - times[0]) % step for when in times):
        return points  # passt in kein Raster: unverändert speichern
    values = [None] * int(slots)
    for when, (_, value) in zip(times, points, strict=True):
        values[(when - times[0]) // step] = round(value)
    return {"t0": points[0][0], "step": int(step.total_seconds() // 60), "v": values}


def unpack(stored) -> list:
    if not isinstance(stored, dict):
        return stored or []
    start, step = _when(stored["t0"]), timedelta(minutes=stored["step"])
    return [[iso(start + step * index), value] for index, value in enumerate(stored["v"]) if value is not None]


def settled(points: list, minutes: int) -> list:
    """Die Reihe ohne ihre neuesten, noch vorläufigen Werte."""
    if not points:
        return points
    limit = iso(_when(points[-1][0]) - timedelta(minutes=minutes))
    return [point for point in points if point[0] <= limit]


# -------------------------------------------------------------- Auswertung
def analyse(country: str, points: list, events: dict, cfg: dict, now, past: dict | None = None) -> list[Signal]:
    """Sucht einen Einbruch der Last und verfolgt ihn bis zur Erholung.

    events: laufender Einbruch je Land (Beginn und Niveau-Faktoren), wird hier fortgeschrieben.
    past:   beendete Einbrüche je Land als [Beginn, Ende]. Diese Zeiten taugen nicht als Vergleich.
    """
    if not points or now - _when(points[-1][0]) > timedelta(hours=cfg["max_data_age_hours"]):
        return []  # veraltete Daten erlauben keine Aussage
    series = [(_when(stamp), value) for stamp, value in settled(points, cfg["settle_minutes"])]
    if len(series) < 8:
        return []
    lookup = dict(series)
    times = [when for when, _ in series]
    latest_t, latest_v = series[-1]
    event = events.get(country)
    event_start = parse_ts(event["start"]) if event else None
    spans = [(parse_ts(start), parse_ts(end)) for start, end in (past or {}).get(country, [])]

    def usable(when) -> bool:
        """Wahr, wenn ein Wert als Vergleich taugt: Er stammt weder aus diesem noch aus einem früheren Einbruch."""
        if event_start and when >= event_start:
            return False
        return not any(start <= when < end for start, end in spans)

    def reference(when, days):
        ref_time = when - timedelta(days=days)
        return lookup.get(ref_time) if usable(ref_time) else None

    def level_factors(before) -> dict:
        """Je Vergleichstag: um wie viel die Last in den drei Stunden davor höher oder tiefer lag."""
        first = bisect.bisect_left(times, before - timedelta(hours=3))
        window = [(when, value) for when, value in series[first: bisect.bisect_left(times, before)] if usable(when)]
        factors = {}
        for days in REFERENCE_DAYS:
            ratios = [value / ref for when, value in window if (ref := reference(when, days))]
            if len(ratios) >= 3:
                factors[str(days)] = round(min(1.25, max(0.75, statistics.median(ratios))), 4)
        return factors

    def drop_at(when, value, factors, plain: bool = False):
        """Einbruch gegenüber dem günstigsten Vergleichstag als (Anteil, erwartete Last), sonst None.

        plain: zusätzlich ohne Niveau-Faktor vergleichen. Das gilt für die Erholung: Der Faktor stammt
        aus den Stunden vor dem Einbruch und passt Stunden später oft nicht mehr.
        """
        found = []
        for days in REFERENCE_DAYS:
            ref = reference(when, days)
            if ref:
                expected = ref * factors.get(str(days), 1.0)
                found.append((1 - value / expected, expected))
                if plain:
                    found.append((1 - value / ref, ref))
        return min(found) if found else None

    area = area_code(country)
    if event is None:
        run = []
        for when, value in series[bisect.bisect_left(times, latest_t - timedelta(hours=3)):]:
            factors = run[0][1] if run else level_factors(when)
            found = drop_at(when, value, factors)
            if found is not None and found[0] >= cfg["drop_threshold"]:
                run.append((when, factors))
            else:
                run = []
        if len(run) < cfg["confirm_points"]:
            return []
        event_start, factors = run[0]
        event = events[country] = {"start": iso(event_start), "factors": factors}
    factors = event.get("factors") or {}

    calm = []
    for when, value in reversed(series):
        if when < event_start:
            break
        found = drop_at(when, value, factors, plain=True)
        if found is None or found[0] >= cfg["recover_threshold"]:
            break
        calm.append(when)
    if len(calm) >= 2:
        del events[country]
        if past is not None:
            past.setdefault(country, []).append([iso(event_start), iso(calm[-1])])
        return [Signal(SOURCE, "load_drop", area, observed_at=latest_t, active=False, severity=0.0,
                       started_at=event_start, ended_at=calm[-1], confirmed_power=True,
                       detail="Stromlast wieder im üblichen Bereich")]

    found = drop_at(latest_t, latest_v, factors)
    if found is None:
        drop, expected = event.get("last_drop", cfg["drop_threshold"]), None
        detail = f"Stromlast {fmt_pct(drop)} (kein Vergleichswert, {_mw(latest_v)} MW)"
    else:
        drop, expected = max(0.0, found[0]), found[1]
        detail = f"Stromlast {fmt_pct(drop)} ({_mw(latest_v)} statt {_mw(expected)} MW)"
    event["last_drop"] = round(drop, 3)
    return [Signal(SOURCE, "load_drop", area, observed_at=latest_t, active=True, severity=round(drop, 3),
                   started_at=event_start, confirmed_power=True, detail=detail,
                   metrics={"load_mw": latest_v, "expected_mw": expected})]


# ----------------------------------------------------------------- Sammeln
def _note_arrival(seen: dict, country: str, stamp: str, now) -> None:
    """Merkt sich, wie alt neue Werte üblicherweise sind, wenn sie eintreffen."""
    entry = seen.setdefault(country, {})
    if entry.get("t") != stamp:
        age = (now - _when(stamp)).total_seconds() / 60
        usual = entry.get("usual")
        entry["usual"] = round(age if usual is None else 0.8 * usual + 0.2 * age)
        entry["t"] = stamp
    entry["checked"] = iso(now)


def _silent(entry: dict | None, newest, cfg: dict, now) -> bool:
    """Wahr, wenn der Dienst antwortet, für dieses Land aber deutlich länger als üblich nichts Neues kommt."""
    if not entry or entry.get("usual") is None:
        return False
    checked = parse_ts(entry.get("checked"))
    if checked is None or now - checked > timedelta(minutes=2 * cfg["poll_minutes"]):
        return False  # schon länger nicht abgefragt: keine Aussage
    return now - newest > timedelta(minutes=entry["usual"] + cfg["silent_after_minutes"])


def _refresh(base: str, country: str, known: list, seen: dict, cfg: dict, now) -> list:
    """Holt neue Werte. Einmal am Tag den ganzen Verlauf, sonst nur die letzten Stunden."""
    entry = seen.setdefault(country, {})
    full_at = parse_ts(entry.get("full"))
    recent = cfg["refresh_hours"]
    full = (not known or full_at is None or now - full_at >= timedelta(hours=24)
            or _when(known[-1][0]) < now - timedelta(hours=recent - 2))
    hours = cfg["history_hours"] if full else recent
    fresh = fetch_load(base, country, now, hours)
    if full:
        entry["full"] = iso(now)
    return merge(known, fresh, now, hours, cfg["history_hours"])


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    base = cfg["base_url"].rstrip("/")
    countries = cfg["countries"]
    series = cursor.setdefault("series", {})
    plan = cursor.setdefault("next_poll", {})
    events = cursor.setdefault("events", {})
    past = cursor.setdefault("past", {})
    seen = cursor.setdefault("seen", {})  # je Land: neuester Zeitstempel, übliches Alter neuer Werte, letzte Abfrage
    for gone in set(series) - set(countries):
        for book in (series, plan, events, past, seen):
            book.pop(gone, None)
    horizon = now - timedelta(days=max(REFERENCE_DAYS) + 2)
    for country in list(past):
        past[country] = [span for span in past[country] if parse_ts(span[1]) > horizon]

    due = [c for c in countries if not plan.get(c) or parse_ts(plan[c]) <= now]
    due.sort(key=lambda c: (c != countries[0], plan.get(c) or ""))
    errors, fetched, loaded = [], 0, {}
    for country in due[: cfg["max_requests_per_run"]]:
        try:
            loaded[country] = _refresh(base, country, unpack(series.get(country)), seen, cfg, now)
            series[country] = pack(loaded[country])
            minutes = cfg["poll_minutes_primary"] if country == countries[0] else cfg["poll_minutes"]
            fetched += 1
            _note_arrival(seen, country, loaded[country][-1][0], now)
        except HttpError as err:
            errors.append(f"{country}: {err}")
            # Land unbekannt oder gesperrt: selten erneut versuchen, damit die anderen an die Reihe kommen
            minutes = 360 if err.status in (400, 403, 404, 422) else 20 if err.status == 429 else 10
        plan[country] = iso(now + timedelta(minutes=minutes))

    signals, newest, latest = [], None, {}
    for country in countries:
        points = loaded.get(country) or unpack(series.get(country))
        if not points:
            continue
        signals += analyse(country, points, events, cfg, now, past)
        last = _when(points[-1][0])
        newest = last if newest is None else max(newest, last)
        stamp, value = (settled(points, cfg["settle_minutes"]) or points)[-1]
        day_before = dict(points).get(iso(_when(stamp) - timedelta(days=1)))
        latest[area_code(country)] = {"t": stamp, "mw": value, "ref_mw": day_before, "newest": points[-1][0],
                                      "silent": _silent(seen.get(country), last, cfg, now)}
    cursor["latest"] = latest
    cursor["data_time"] = iso(newest)
    cursor["note"] = "; ".join(errors)
    too_old = newest is None or now - newest > timedelta(hours=cfg["max_data_age_hours"])
    if errors and not fetched and too_old:
        raise HttpError("; ".join(errors))
    return signals
