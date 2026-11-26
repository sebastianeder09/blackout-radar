"""IODA (Internet Outage Detection and Analysis, Georgia Tech): weltweite Internet-Ausfälle.

Ein großer Stromausfall lässt die Internet-Erreichbarkeit eines Landes einbrechen,
weil Router und Mobilfunkstationen ausfallen. IODA misst das weltweit und ohne
Anmeldung. Es ist ein Indiz, kein Beweis: auch Kabelschäden oder staatliche
Abschaltungen sehen so aus. Deshalb verlangt der Kern außerhalb der Vorrang-Gebiete
eine Bestätigung, dass Strom die Ursache ist.

Zwei Wege:
  Alarme      alle Länder der Welt in einer Abfrage (Schwellen-Übergänge)
  Rohsignal   direkte Messung für Vorrang-Gebiete (Österreich, Oberösterreich)
"""
from __future__ import annotations

import statistics
import unicodedata
from datetime import timedelta

from .. import areas, http
from ..http import HttpError
from ..model import Signal, fmt_pct, iso, parse_ts

SOURCE = "ioda"
STRONG = ("ping-slash24", "bgp", "gtr", "gtr-norm")  # Messverfahren, die allein eine Störung begründen


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def _flatten(node) -> list:
    if isinstance(node, dict):
        return [node]
    found = []
    for item in node or []:
        found += _flatten(item)
    return found


def _get(base: str, path: str, params: dict):
    doc = http.get_json(f"{base}{path}", params=params, timeout=30)
    if isinstance(doc, dict) and doc.get("error"):
        raise HttpError(f"IODA meldet Fehler: {str(doc['error'])[:120]}")
    return doc.get("data") if isinstance(doc, dict) else doc


# ---------------------------------------------------------------- Alarme weltweit
def collect_alerts(base: str, cfg: dict, cursor: dict, now, skip: set) -> list[Signal]:
    active = cursor.setdefault("active", {})  # Land -> Messverfahren -> Zustand
    last = parse_ts(cursor.get("alerts_until"))
    start = max(last - timedelta(minutes=30), now - timedelta(hours=48)) if last else now - timedelta(hours=24)
    rows = _flatten(_get(base, "/outages/alerts", {
        "from": int(start.timestamp()), "until": int(now.timestamp()), "entityType": "country", "limit": 2000}))
    rows.sort(key=lambda row: row.get("time") or 0)
    minimum = cfg["alert_min_drop"]
    cleared = {}
    for row in rows:
        entity = row.get("entity") or {}
        code = str(entity.get("code") or "").upper()
        method = row.get("datasource")
        when = parse_ts(row.get("time"))
        if entity.get("type") != "country" or len(code) != 2 or not method or when is None:
            continue
        slot = active.setdefault(code, {})
        value, history = row.get("value"), row.get("historyValue")
        drop = None
        if isinstance(value, (int, float)) and isinstance(history, (int, float)) and history > 0:
            drop = max(0.0, 1 - value / history)
        alarming = row.get("level") in ("warning", "critical") and drop is not None \
            and drop >= minimum.get(method, 0.25)
        if alarming:
            previous = slot.get(method)
            slot[method] = {"since": previous["since"] if previous else iso(when),
                            "drop": round(drop, 3), "time": iso(when)}
        elif method in slot:
            del slot[method]
            cleared[code] = max(cleared.get(code, when), when)
        if not slot:
            active.pop(code, None)
    cursor["alerts_until"] = iso(now)
    # Zustände ohne jede Auffrischung verfallen nach 14 Tagen
    limit = now - timedelta(days=14)
    for code in list(active):
        active[code] = {m: s for m, s in active[code].items() if parse_ts(s["time"]) > limit}
        if not active[code]:
            del active[code]

    signals = []
    for code, slot in active.items():
        if code in skip:
            continue
        strong = [m for m in STRONG if m in slot]
        if not strong:
            continue  # nur das Teleskop-Signal reicht nicht
        drop = slot[strong[0]]["drop"]
        since = min(parse_ts(s["since"]) for s in slot.values())
        detail = f"Internet-Erreichbarkeit {fmt_pct(drop)}"
        if len(slot) > 1:
            detail += f" ({len(slot)} Messverfahren schlagen an)"
        signals.append(Signal(SOURCE, "internet_drop", code, observed_at=now, active=True, severity=drop,
                              started_at=since, detail=detail, metrics={"methods": sorted(slot)}))
    for code, when in cleared.items():
        if code not in active and code not in skip:
            signals.append(Signal(SOURCE, "internet_drop", code, observed_at=now, active=False, severity=0.0,
                                  ended_at=when, detail="Internet-Erreichbarkeit wieder normal"))
    return signals


# ------------------------------------------------------------- Rohsignal je Gebiet
def measure(base: str, entity_type: str, code: str, area: str, threshold: float, cursor: dict, now):
    rows = _flatten(_get(base, f"/signals/raw/{entity_type}/{code}", {
        "from": int((now - timedelta(hours=26)).timestamp()), "until": int(now.timestamp()),
        "datasource": "ping-slash24"}))
    series = next((r for r in rows if r.get("values") and r.get("datasource", "ping-slash24") == "ping-slash24"), None)
    if series is None:
        raise HttpError(f"kein IODA-Rohsignal für {area}")
    step = series.get("step") or series.get("nativeStep") or 600
    begin = parse_ts(series.get("from"))
    if begin is None:
        raise HttpError(f"IODA-Rohsignal für {area} ohne Startzeit")
    points = [(begin + timedelta(seconds=step * i), float(v))
              for i, v in enumerate(series["values"]) if v is not None]
    if len(points) < 12:
        raise HttpError(f"zu wenige IODA-Messpunkte für {area}")
    latest_t = points[-1][0]
    if now - latest_t > timedelta(minutes=120):
        raise HttpError(f"IODA-Rohsignal für {area} veraltet (Stand {iso(latest_t)})")
    watch = cursor.setdefault("raw", {})
    state = watch.get(area)
    if state:
        baseline = state["baseline"]
    else:
        earlier = [v for t, v in points if t <= latest_t - timedelta(hours=2)]
        if len(earlier) < 6:
            raise HttpError(f"zu wenig IODA-Vorgeschichte für {area}")
        baseline = statistics.median(earlier)
    if baseline <= 0:
        raise HttpError(f"IODA-Grundwert für {area} ist null")
    current = statistics.fmean(v for _, v in points[-2:])
    drop = max(0.0, 1 - current / baseline)
    cursor.setdefault("levels", {})[area] = {"t": iso(latest_t), "drop": round(drop, 3)}
    previous = parse_ts(cursor.get("data_time"))
    cursor["data_time"] = iso(max(previous, latest_t) if previous else latest_t)
    detail = f"Internet-Erreichbarkeit {fmt_pct(drop)}"
    if state is None and drop >= threshold:
        start = latest_t
        for when, value in reversed(points):
            if value >= baseline * (1 - threshold / 2):
                break
            start = when
        state = watch[area] = {"since": iso(start), "baseline": baseline}
    if state is None:
        return None
    if drop < threshold / 2:
        del watch[area]
        return Signal(SOURCE, "internet_drop", area, observed_at=latest_t, active=False, severity=0.0,
                      started_at=parse_ts(state["since"]), ended_at=latest_t,
                      detail="Internet-Erreichbarkeit wieder normal")
    return Signal(SOURCE, "internet_drop", area, observed_at=latest_t, active=True, severity=round(drop, 3),
                  started_at=parse_ts(state["since"]), detail=detail, metrics={"baseline": baseline})


def region_code(base: str, area: str, names: list, cursor: dict, now) -> str | None:
    cache = cursor.setdefault("regions", {})
    entry = cache.get(area)
    if entry and now - parse_ts(entry["checked"]) < timedelta(days=7):
        return entry["code"]
    rows = _flatten(_get(base, "/entities/query", {
        "entityType": "region", "relatedTo": f"country/{areas.parent(area)}"}))
    wanted = {_norm(name) for name in names}
    code = None
    for row in rows:
        if _norm(str(row.get("name", ""))) in wanted:
            code = str(row.get("code"))
            break
    cache[area] = {"code": code, "checked": iso(now)}
    return code


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    base = cfg["base_url"].rstrip("/")
    signals, errors, parts, measured = [], [], 0, set()
    for country in cfg.get("watch_countries") or []:
        parts += 1
        try:
            signal = measure(base, "country", country, country, cfg["drop_threshold"], cursor, now)
            measured.add(country)
            if signal:
                signals.append(signal)
        except HttpError as err:
            errors.append(str(err))
    for area, names in (cfg.get("watch_regions") or {}).items():
        parts += 1
        try:
            code = region_code(base, area, names, cursor, now)
            if code is None:
                raise HttpError(f"IODA kennt das Gebiet {area} nicht")
            signal = measure(base, "region", code, area, cfg["region_drop_threshold"], cursor, now)
            if signal:
                signals.append(signal)
        except HttpError as err:
            errors.append(str(err))
    parts += 1
    try:
        signals += collect_alerts(base, cfg, cursor, now, measured)
        if not cursor.get("data_time"):
            cursor["data_time"] = iso(now)
    except HttpError as err:
        errors.append(f"Alarme: {err}")
    cursor["note"] = "; ".join(errors)
    if len(errors) == parts:
        raise HttpError("; ".join(errors))
    return signals
