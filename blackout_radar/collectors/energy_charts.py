"""Stromlast je Land von Energy-Charts (Fraunhofer ISE, Daten von ENTSO-E, CC BY 4.0).

Die Lastdaten kommen mit rund zwei Stunden Verzögerung. Sie eignen sich deshalb
nicht für den ersten Alarm, aber gut als Bestätigung ("es ist wirklich Strom")
und um den Netzwiederaufbau zu verfolgen.

Erwartungswert: Last zur selben Uhrzeit am Vortag, angepasst um das Niveau der
letzten Stunden (Wochentag, Feiertag, Wetter).
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from .. import http
from ..http import HttpError
from ..model import Signal, fmt_pct, iso, parse_ts

SOURCE = "load"


def _fmt(when) -> str:
    return when.strftime("%Y-%m-%dT%H:%MZ")


def _mw(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def area_code(country: str) -> str:
    return "GB" if country.lower() == "uk" else country.upper()


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


def fetch_load(base: str, country: str, now) -> list:
    doc = http.get_json(f"{base}/v2/public_power", timeout=30, params={
        "country": country, "start": _fmt(now - timedelta(hours=58)), "end": _fmt(now)})
    points = to_points(doc)
    if not points:
        raise HttpError(f"keine Lastdaten für {country}")
    return points


def analyse(country: str, points: list, events: dict, cfg: dict, now) -> list[Signal]:
    series = [(parse_ts(t), v) for t, v in points]
    if len(series) < 8:
        return []
    lookup = dict(series)
    latest_t, latest_v = series[-1]
    if now - latest_t > timedelta(hours=cfg["max_data_age_hours"]):
        return []  # veraltete Daten erlauben keine Aussage
    event = events.get(country)
    event_start = parse_ts(event["start"]) if event else None

    def reference(when):
        for days in (1, 2):
            ref_time = when - timedelta(days=days)
            if event_start and ref_time >= event_start:
                continue  # Vergleichstag liegt selbst im Ausfall
            value = lookup.get(ref_time)
            if value:
                return value
        return None

    def level_factor(before):
        ratios = []
        for when, value in series:
            if before - timedelta(hours=3) <= when < before:
                ref = reference(when)
                if ref:
                    ratios.append(value / ref)
        if len(ratios) < 3:
            return 1.0
        return min(1.25, max(0.75, statistics.median(ratios)))

    def drop_at(when, value, factor):
        ref = reference(when)
        return None if not ref else 1 - value / (ref * factor)

    area = area_code(country)
    if event is None:
        run = []
        for when, value in series:
            if when < latest_t - timedelta(hours=3):
                continue
            factor = run[0][1] if run else level_factor(when)
            drop = drop_at(when, value, factor)
            if drop is not None and drop >= cfg["drop_threshold"]:
                run.append((when, factor))
            else:
                run = []
        if len(run) < cfg["confirm_points"]:
            return []
        event_start, factor = run[0]
        event = events[country] = {"start": iso(event_start), "factor": round(factor, 4)}
    factor = event["factor"]

    calm = []
    for when, value in reversed(series):
        if when < event_start:
            break
        drop = drop_at(when, value, factor)
        if drop is None or drop >= cfg["recover_threshold"]:
            break
        calm.append(when)
    if len(calm) >= 2:
        del events[country]
        return [Signal(SOURCE, "load_drop", area, observed_at=latest_t, active=False, severity=0.0,
                       started_at=event_start, ended_at=calm[-1], confirmed_power=True,
                       detail="Stromlast wieder normal")]

    drop = drop_at(latest_t, latest_v, factor)
    if drop is None:
        drop = event.get("last_drop", cfg["drop_threshold"])
        detail = f"Stromlast {fmt_pct(drop)} (kein Vergleichswert, {_mw(latest_v)} MW)"
        expected = None
    else:
        drop = max(0.0, drop)
        expected = reference(latest_t) * factor
        detail = f"Stromlast {fmt_pct(drop)} ({_mw(latest_v)} statt {_mw(expected)} MW)"
    event["last_drop"] = round(drop, 3)
    return [Signal(SOURCE, "load_drop", area, observed_at=latest_t, active=True, severity=round(drop, 3),
                   started_at=event_start, confirmed_power=True, detail=detail,
                   metrics={"load_mw": latest_v, "expected_mw": expected})]


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    base = cfg["base_url"].rstrip("/")
    countries = cfg["countries"]
    series = cursor.setdefault("series", {})
    plan = cursor.setdefault("next_poll", {})
    events = cursor.setdefault("events", {})
    for gone in set(series) - set(countries):
        series.pop(gone, None)
        plan.pop(gone, None)
        events.pop(gone, None)

    due = [c for c in countries if not plan.get(c) or parse_ts(plan[c]) <= now]
    due.sort(key=lambda c: (c != countries[0], plan.get(c) or ""))
    errors, fetched = [], 0
    for country in due[: cfg["max_requests_per_run"]]:
        try:
            series[country] = fetch_load(base, country, now)
            minutes = cfg["poll_minutes_primary"] if country == countries[0] else cfg["poll_minutes"]
            fetched += 1
        except HttpError as err:
            errors.append(f"{country}: {err}")
            # Land unbekannt oder gesperrt: selten erneut versuchen, damit die anderen an die Reihe kommen
            minutes = 360 if err.status in (400, 403, 404, 422) else 20 if err.status == 429 else 10
        plan[country] = iso(now + timedelta(minutes=minutes))

    signals, newest, latest = [], None, {}
    for country in countries:
        points = series.get(country)
        if not points:
            continue
        signals += analyse(country, points, events, cfg, now)
        last = parse_ts(points[-1][0])
        newest = last if newest is None else max(newest, last)
        day_before = dict(points).get(iso(last - timedelta(days=1)))
        latest[area_code(country)] = {"t": points[-1][0], "mw": points[-1][1], "ref_mw": day_before}
    cursor["latest"] = latest
    cursor["data_time"] = iso(newest)
    cursor["note"] = "; ".join(errors)
    too_old = newest is None or now - newest > timedelta(hours=cfg["max_data_age_hours"])
    if errors and not fetched and too_old:
        raise HttpError("; ".join(errors))
    return signals
