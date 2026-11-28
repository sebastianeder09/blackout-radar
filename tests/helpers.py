"""Gemeinsame Bausteine der Tests: feste Uhrzeit, Standard-Konfiguration, Signale."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from blackout_radar import config
from blackout_radar.model import Signal

UTC = timezone.utc
T0 = datetime(2026, 11, 26, 11, 0, tzinfo=UTC)  # 12:00 Uhr in Wien


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def make_cfg(**env) -> dict:
    """Standard-Konfiguration ohne Datei. Umgebungsvariablen nur, wenn ausdrücklich übergeben."""
    return config.load(None, env=env)


def media(area: str, share, since: datetime, now: datetime, active: bool = True, text: str = "") -> Signal:
    if not active:
        return Signal("media", "media_outage", area, observed_at=now, active=False, severity=0.0,
                      started_at=since, ended_at=now, detail="keine neuen Medienberichte")
    return Signal("media", "media_outage", area, observed_at=now, severity=share, started_at=since,
                  confirmed_power=True, detail=text or "3 Medien berichten")


def load(area: str, drop, since: datetime, data_time: datetime, active: bool = True) -> Signal:
    if not active:
        return Signal("load", "load_drop", area, observed_at=data_time, active=False, severity=0.0,
                      started_at=since, ended_at=data_time, confirmed_power=True,
                      detail="Stromlast wieder im üblichen Bereich")
    return Signal("load", "load_drop", area, observed_at=data_time, severity=drop, started_at=since,
                  confirmed_power=True, detail=f"Stromlast −{round(drop * 100)} %")


def internet(area: str, drop, since: datetime, now: datetime, active: bool = True) -> Signal:
    if not active:
        return Signal("ioda", "internet_drop", area, observed_at=now, active=False, severity=0.0,
                      started_at=since, ended_at=now, detail="Internet-Erreichbarkeit wieder normal")
    return Signal("ioda", "internet_drop", area, observed_at=now, severity=drop, started_at=since,
                  detail=f"Internet-Erreichbarkeit −{round(drop * 100)} %")


def utility(area: str, since: datetime, now: datetime, active: bool = True) -> Signal:
    if not active:
        return Signal("utility", "utility_outage", area, observed_at=now, active=False, severity=0.0,
                      started_at=since, ended_at=now, detail="LINZ NETZ meldet keine Störung mehr")
    return Signal("utility", "utility_outage", area, observed_at=now, started_at=since, confirmed_power=True,
                  detail="LINZ NETZ meldet eine Störung: Stromausfall in Urfahr")


def frequency(value, since: datetime, now: datetime) -> Signal:
    if value is None:
        return Signal("frequency", "frequency", "EU-CE", observed_at=now, active=False, severity=0.0,
                      started_at=since, ended_at=now, metrics={"worst_hz": 49.7, "current_hz": 50.0},
                      detail="Netzfrequenz wieder bei 50,000 Hz")
    return Signal("frequency", "frequency", "EU-CE", observed_at=now, severity=round(abs(value - 50), 3),
                  started_at=since, metrics={"worst_hz": value, "current_hz": value},
                  detail=f"Netzfrequenz {value} Hz")


def play(engine, script, until: int, step: int = 5) -> list[tuple]:
    """Spielt Signale im Zeitraffer ab. script(minute, now) liefert die Signale des Laufs."""
    sent = []
    for minute in range(0, until + 1, step):
        now = at(minute)
        for message in engine.tick(script(minute, now), now):
            sent.append((minute, message))
    return sent


# Schlüssel für die Tests des öffentlichen Alarms. Es ist der Beispielschlüssel aus RFC 6979 (A.2.5): Sein
# geheimer Teil ist allgemein bekannt. Nur Testfassungen der App nehmen ihn an, die echte App nie.
TEST_KEY = "BRKEY1:test:c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721"
TEST_KEY_PUBLIC = ("0460fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb6"
                   "7903fe1008b8bc99a41ae9e95628bc64f2f1b20c2d7e9f5177a3c294d4462299")
