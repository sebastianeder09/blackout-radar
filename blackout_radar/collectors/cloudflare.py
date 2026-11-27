"""Cloudflare Radar (optional, braucht ein kostenloses API-Token).

Zwei Dinge:
  Ausfall-Einträge   von Cloudflare geprüft, mit Ursache. POWER_OUTAGE bestätigt Strom
                     als Ursache, andere Ursachen (Kabelschaden, staatliche Abschaltung)
                     verhindern einen Fehlalarm. Diese Einträge erscheinen oft erst Stunden später.
  Verkehrs-Anomalien automatisch erkannt, landesweit, zeitnah, aber ohne Größenangabe.
"""
from __future__ import annotations

from datetime import timedelta

from .. import http
from ..model import Signal, parse_ts

SOURCE = "cloudflare"


def _rank(signal: Signal) -> tuple:
    return (signal.active, signal.kind == "confirmed_outage", signal.kind == "internet_drop")


def collect(cfg: dict, cursor: dict, now, context: dict) -> list[Signal]:
    base = cfg["base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {cfg['token']}"}
    best: dict[str, Signal] = {}
    extra: list[Signal] = []

    def keep(signal: Signal):
        current = best.get(signal.area)
        if current is None or _rank(signal) > _rank(current):
            best[signal.area] = signal

    doc = http.get_json(f"{base}/annotations/outages", headers=headers, timeout=30,
                        params={"dateRange": "7d", "limit": 200, "format": "json"})
    for item in (doc.get("result") or {}).get("annotations") or []:
        start, end = parse_ts(item.get("startDate")), parse_ts(item.get("endDate"))
        if start is None or (end is not None and now - end > timedelta(hours=6)):
            continue
        outage = item.get("outage") or {}
        cause, scope = outage.get("outageCause"), outage.get("outageType")
        active = end is None or end > now
        for location in item.get("locations") or []:
            code = str(location).upper()
            if cause == "POWER_OUTAGE":
                nationwide = scope == "NATIONWIDE"
                text = "Cloudflare Radar bestätigt Stromausfall, " + ("landesweit" if nationwide else "regional")
                if item.get("scope"):
                    text += f" ({item['scope']})"
                keep(Signal(SOURCE, "confirmed_outage", code, observed_at=now, active=active,
                            severity=(0.5 if nationwide else None) if active else 0.0,
                            started_at=start, ended_at=end, confirmed_power=True, detail=text,
                            url=item.get("linkedUrl") or "", metrics={"estimated": True, "scope": scope}))
            elif cause and cause != "UNKNOWN":
                extra.append(Signal(SOURCE, "annotation", code, observed_at=now, active=False,
                                    metrics={"cause": cause}))

    doc = http.get_json(f"{base}/traffic_anomalies", headers=headers, timeout=30,
                        params={"dateRange": "1d", "limit": 200, "format": "json"})
    for item in (doc.get("result") or {}).get("trafficAnomalies") or []:
        location = (item.get("locationDetails") or {}).get("code")
        start, end = parse_ts(item.get("startDate")), parse_ts(item.get("endDate"))
        if item.get("type") != "LOCATION" or not location or start is None:
            continue
        if end is not None and now - end > timedelta(hours=6):
            continue
        active = end is None or end > now
        keep(Signal(SOURCE, "internet_drop", str(location).upper(), observed_at=now, active=active,
                    severity=0.3 if active else 0.0, started_at=start, ended_at=end,
                    detail="Cloudflare meldet landesweiten Einbruch im Internetverkehr",
                    metrics={"estimated": True, "status": item.get("status")}))
    cursor["data_time"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor["note"] = ""
    return list(best.values()) + extra
