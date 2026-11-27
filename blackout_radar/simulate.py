"""Planspiel: ein Blackout in Österreich im Zeitraffer.

Zeigt, welche Meldungen in welcher Reihenfolge kämen, mit den Quellen, die im
Normalbetrieb eingeschaltet sind: Netzfrequenz (sofort), Medien (nach rund 20 Minuten)
und Stromlast (mit gut zwei Stunden Verzögerung). Es werden keine Datenquellen
abgefragt, alle Signale sind erfunden. Der Kern (Filter, Verlauf, Entwarnung) ist
derselbe wie im echten Betrieb.
"""
from __future__ import annotations

from datetime import timedelta

from .engine import Engine
from .model import Message, Signal, fmt_pct

LOAD_DELAY = timedelta(minutes=135)  # so alt sind Lastdaten, wenn sie eintreffen

# Minute seit Beginn -> Änderungen (Quelle, Gebiet, Wert). Wert None heißt "wieder normal".
# Medien: (Anteil der Betroffenen oder None, Text). Stromlast: Einbruch als Anteil.
STEPS = [
    (0, [("frequency", "EU-CE", 49.31)]),
    (10, [("frequency", "EU-CE", None)]),
    (20, [("media", "AT-4", (None, "1 Medium berichtet, Größe unbekannt")),
          ("news", "AT-4", "Stromausfall in weiten Teilen Oberösterreichs|nachrichten.at")]),
    (25, [("media", "AT-4", (None, "3 Medien berichten, Größe unbekannt")),
          ("media", "AT", (0.5, "4 Medien berichten, landesweiter Ausfall laut Schlagzeilen")),
          ("news", "AT", "Blackout: Ganz Österreich ohne Strom|derstandard.at"),
          ("news", "AT", "Großflächiger Stromausfall legt Österreich lahm|orf.at")]),
    (165, [("load", "AT", 0.86), ("load", "CZ", 0.33)]),
    (240, [("load", "CZ", None)]),
    (420, [("load", "AT", 0.60)]),
    (600, [("load", "AT", 0.35)]),
    (780, [("load", "AT", None)]),
]
END_MINUTE = 830
EXPECTED_MW = {"AT": 9400, "CZ": 8900}


def _mw(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _signal(source: str, area: str, value, since, now) -> Signal:
    active = value is not None
    if source == "frequency":
        if active:
            detail = f"Netzfrequenz {value:.3f} Hz statt 50,000 Hz (Alarmgrenze ±200 mHz)".replace(".", ",")
            return Signal("frequency", "frequency", area, observed_at=now, severity=round(abs(value - 50), 3),
                          started_at=since, metrics={"worst_hz": value, "current_hz": value},
                          detail=detail + ". Stufe laut Notfallplan: Abwurf von Speicherpumpen")
        return Signal("frequency", "frequency", area, observed_at=now, active=False, severity=0.0, started_at=since,
                      ended_at=now, metrics={"worst_hz": 49.31, "current_hz": 49.98},
                      detail="Netzfrequenz wieder bei 49,980 Hz, größte Abweichung war 49,310 Hz")
    if source == "load":
        data_time = now - LOAD_DELAY
        if active:
            expected = EXPECTED_MW.get(area, 5000)
            detail = f"Stromlast {fmt_pct(value)} ({_mw(expected * (1 - value))} statt {_mw(expected)} MW)"
            return Signal("load", "load_drop", area, observed_at=data_time, severity=value, started_at=since,
                          confirmed_power=True, detail=detail)
        return Signal("load", "load_drop", area, observed_at=data_time, active=False, severity=0.0, started_at=since,
                      ended_at=data_time, confirmed_power=True, detail="Stromlast wieder im üblichen Bereich")
    share, detail = value
    return Signal("media", "media_outage", area, observed_at=now, severity=share, started_at=since,
                  confirmed_power=True, detail=detail)


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
                since = current.get((source, area), (None, now))[1]
                if source == "load" and (source, area) not in current:
                    since = start + timedelta(minutes=5)  # Lastdaten zeigen den wahren Beginn im Nachhinein
                current[(source, area)] = (value, since)
        signals += [_signal(source, area, value, since, now) for (source, area), (value, since) in current.items()]
        for message in engine.tick(signals, now):
            sent.append((now, message))
    return sent


def render(cfg: dict, start, tz) -> str:
    lines = ["Planspiel: Blackout in Österreich. Alle Signale sind erfunden.",
             "Beginn des gedachten Ausfalls: " + (start + timedelta(minutes=5)).astimezone(tz).strftime("%H:%M Uhr"), ""]
    for when, message in run(cfg, start):
        lines.append(f"── {when.astimezone(tz).strftime('%H:%M')} Uhr  [{message.level}]  {message.title}")
        lines += ["   " + line for line in message.body.splitlines()]
        lines.append("")
    return "\n".join(lines)


def as_test(message: Message) -> Message:
    return Message("[TEST] " + message.title, "Planspiel, kein echter Ausfall.\n" + message.body,
                   message.level, "test:" + message.key, message.url)
