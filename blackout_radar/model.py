"""Gemeinsame Datentypen und Zeit-Helfer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_ts(value) -> datetime | None:
    """Liest Unix-Sekunden, ISO-8601-Text oder datetime und liefert UTC-bewusste Zeit."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_duration(td: timedelta) -> str:
    minutes = max(0, int(td.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {rest:02d} min"
    days, hours = divmod(hours, 24)
    return f"{days} T {hours} h"


def fmt_pct(share: float | None) -> str:
    if share is None:
        return "?"
    return f"−{round(share * 100)} %"


@dataclass
class Signal:
    """Eine Beobachtung einer Datenquelle für ein Gebiet.

    kind:
      internet_drop     Einbruch der Internet-Erreichbarkeit (Indiz für Stromausfall)
      load_drop         Einbruch der Stromlast (gemessen, aber zeitverzögert)
      frequency         Netzfrequenz außerhalb der Alarmgrenze
      confirmed_outage  von der Quelle selbst als Stromausfall eingestuft
      utility_outage    Störungsmeldung eines Netzbetreibers
      site_down         eigener Sensor meldet Ausfall
      news              Medienbericht (Bestätigung bzw. Hinweis)
      annotation        Ursachenangabe einer Quelle (z. B. Kabelschaden)
    """

    source: str
    kind: str
    area: str
    observed_at: datetime
    active: bool = True
    severity: float | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    confirmed_power: bool = False
    detail: str = ""
    url: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class Message:
    """Eine Meldung an den Menschen. level: alarm | warn | info | ok | daily."""

    title: str
    body: str
    level: str = "info"
    key: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "body": self.body, "level": self.level, "key": self.key, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(data.get("title", ""), data.get("body", ""), data.get("level", "info"),
                   data.get("key", ""), data.get("url", ""))
