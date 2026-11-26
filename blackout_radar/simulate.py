"""Planspiel: ein Blackout in Österreich im Zeitraffer.

Zeigt, welche Meldungen in welcher Reihenfolge kämen. Es werden keine Datenquellen
abgefragt, alle Signale sind erfunden. Der Kern (Filter, Verlauf, Entwarnung) ist
derselbe wie im echten Betrieb.
"""
from __future__ import annotations

from datetime import timedelta

from .engine import Engine
from .model import Message, Signal, fmt_pct

# Minute seit Beginn -> Änderungen (Quelle, Gebiet, Wert). Wert None heißt "wieder normal".
STEPS = [
    (0, [("frequency", "EU-CE", 49.31)]),
    (5, [("ioda", "AT", 0.78), ("ioda", "AT-4", 0.85)]),
    (10, [("ioda", "AT", 0.91), ("ioda", "AT-4", 0.93), ("ioda", "CZ", 0.35), ("ioda", "SI", 0.55),
          ("frequency", "EU-CE", None)]),
    (20, [("news", "AT", "Großflächiger Stromausfall legt Österreich lahm|orf.at"),
          ("news", "AT", "Blackout: Ganz Österreich ohne Strom|derstandard.at")]),
    (60, [("ioda", "HU", 0.30)]),
    (150, [("load", "AT", 0.86), ("load", "CZ", 0.33)]),
    (200, [("ioda", "CZ", None)]),
    (230, [("ioda", "SI", None), ("load", "CZ", None)]),
    (360, [("ioda", "AT", 0.55), ("ioda", "AT-4", 0.70), ("load", "AT", 0.60)]),
    (500, [("ioda", "HU", None)]),
    (540, [("ioda", "AT", 0.20), ("ioda", "AT-4", 0.25), ("load", "AT", 0.35)]),
    (650, [("ioda", "AT-4", None)]),
    (705, [("ioda", "AT", None)]),
    (720, [("load", "AT", None)]),
]
END_MINUTE = 760
EXPECTED_MW = {"AT": 9400, "CZ": 8900}


def _mw(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _signal(source: str, area: str, value, since, now) -> Signal:
    active = value is not None
    if source == "frequency":
        if active:
            return Signal("frequency", "frequency", area, observed_at=now, severity=round(abs(value - 50), 3),
                          started_at=since, metrics={"worst_hz": value, "current_hz": value},
                          detail=f"Netzfrequenz {value:.3f} Hz statt 50,000 Hz (Alarmgrenze ±200 mHz)".replace(".", ","))
        return Signal("frequency", "frequency", area, observed_at=now, active=False, severity=0.0, started_at=since,
                      ended_at=now, metrics={"worst_hz": 49.31, "current_hz": 49.98},
                      detail="Netzfrequenz wieder bei 49,980 Hz")
    if source == "load":
        data_time = now - timedelta(minutes=135)  # Lastdaten kommen mit gut zwei Stunden Verzögerung
        if active:
            expected = EXPECTED_MW.get(area, 5000)
            detail = f"Stromlast {fmt_pct(value)} ({_mw(expected * (1 - value))} statt {_mw(expected)} MW)"
            return Signal("load", "load_drop", area, observed_at=data_time, severity=value, started_at=since,
                          confirmed_power=True, detail=detail)
        return Signal("load", "load_drop", area, observed_at=data_time, active=False, severity=0.0, started_at=since,
                      ended_at=data_time, confirmed_power=True, detail="Stromlast wieder normal")
    if active:
        return Signal("ioda", "internet_drop", area, observed_at=now, severity=value, started_at=since,
                      detail=f"Internet-Erreichbarkeit {fmt_pct(value)}")
    return Signal("ioda", "internet_drop", area, observed_at=now, active=False, severity=0.0, started_at=since,
                  ended_at=now, detail="Internet-Erreichbarkeit wieder normal")


def run(cfg: dict, start, step_minutes: int = 5) -> list[tuple]:
    """Spielt das Szenario durch und liefert (Zeitpunkt, Meldung) in der Reihenfolge des Versands."""
    engine = Engine(cfg, {})
    changes = dict(STEPS)
    current: dict[tuple, tuple] = {}  # (Quelle, Gebiet) -> (Wert, seit)
    sent = []
    for minute in range(0, END_MINUTE + 1, step_minutes):
        now = start + timedelta(minutes=minute)
        signals = []
        for source, area, value in changes.get(minute, []):
            if source == "news":
                title, domain = value.split("|")
                signals.append(Signal("news", "news", area, observed_at=now, active=False, detail=title,
                                      url=f"https://{domain}/beispiel", metrics={"domain": domain, "power": True}))
            elif value is None:
                _, since = current.pop((source, area), (None, now))
                signals.append(_signal(source, area, None, since, now))
            else:
                since = current.get((source, area), (None, now - timedelta(minutes=4)))[1]
                if source == "load" and (source, area) not in current:
                    since = start + timedelta(minutes=5)
                current[(source, area)] = (value, since)
        signals += [_signal(source, area, value, since, now) for (source, area), (value, since) in current.items()]
        for message in engine.tick(signals, now):
            sent.append((now, message))
    return sent


def render(cfg: dict, start, tz) -> str:
    lines = ["Planspiel: Blackout in Österreich. Alle Signale sind erfunden.", ""]
    for when, message in run(cfg, start):
        lines.append(f"── {when.astimezone(tz).strftime('%H:%M')} Uhr  [{message.level}]  {message.title}")
        lines += ["   " + line for line in message.body.splitlines()]
        lines.append("")
    return "\n".join(lines)


def as_test(message: Message) -> Message:
    return Message("[TEST] " + message.title, "Planspiel, kein echter Ausfall.\n" + message.body,
                   message.level, "test:" + message.key, message.url)
