"""Testdaten für die App: Lagebericht und Meldungen aus dem Planspiel des Radars.

Spielt das Planspiel (Blackout in Österreich) bis zu einer gewählten Minute durch, so dass
es jetzt gerade so weit ist, und schreibt daraus:

  <ziel>/status.json, <ziel>/status.md   der Lagebericht in diesem Moment
  <ziel>/meldungen.json                  die Meldungen bis dahin, so wie ntfy sie liefert
  <ziel>/zustand.json                    der Zustand des Radars dazu, für fake_ntfy.py

Aufruf aus dem Hauptordner des Repositorys:
  python3 android/test/fixtures.py <ziel> [minute]
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from blackout_radar import config, report, simulate  # noqa: E402
from blackout_radar.engine import Engine  # noqa: E402
from blackout_radar.model import Signal, iso, now_utc  # noqa: E402
from blackout_radar.notify import NTFY_PRIORITY, NTFY_TAGS  # noqa: E402

STATUS_URL = "https://github.com/sebastianeder09/blackout-radar/blob/state/status.md"


def play(cfg: dict, start, stop_minute: int):
    """Wie simulate.run, aber bis stop_minute und mit dem Zustand am Ende."""
    state: dict = {}
    engine = Engine(cfg, state)
    changes = dict(simulate.STEPS)
    current: dict = {}
    sent = []
    now = start
    for minute in range(0, stop_minute + 1, 5):
        now = start + timedelta(minutes=minute)
        signals = []
        for source, area, value in changes.get(minute, []):
            if source == "news":
                title, domain = value.split("|")
                signals.append(Signal("news", "news", area, observed_at=now, active=False, detail=title,
                                      url=f"https://{domain}/beispiel", metrics={"domain": domain, "power": True}))
            elif value is None:
                _, since = current.pop((source, area), (None, now))
                signals.append(simulate._signal(source, area, None, since, now))
            else:
                since = current.get((source, area), (None, now))[1]
                if source == "load" and (source, area) not in current:
                    since = start + timedelta(minutes=5)
                current[(source, area)] = (value, since)
        signals += [simulate._signal(s, a, v, since, now) for (s, a), (v, since) in current.items()]
        for message in engine.tick(signals, now):
            sent.append((now, message))
    return state, sent, now


def notices(state: dict, bodies: dict | None = None, limit: int = 20) -> list[dict]:
    """Die Meldungen des Radars, wie er sie im Lagebericht führt, damit die App fehlende selbst zeigen kann.

    So ist das Format zwischen Radar und App abgesprochen. Gebraucht wird diese Fassung nur, solange der
    Radar die Liste noch nicht selbst schreibt: fake_ntfy.py nimmt immer zuerst, was der Radar liefert.
    """
    bodies = bodies or {}
    rows = []
    for item in state.get("outbox") or []:
        message = item["message"]
        rows.append({"key": message.get("key", ""), "t": item["queued_at"], "title": message["title"],
                     "body": message.get("body", ""), "level": message["level"],
                     "delivered": list(item.get("done") or []), "pending": list(item.get("pending") or [])})
    for entry in state.get("sent") or []:
        rows.append({"key": entry.get("key", ""), "t": entry["t"], "title": entry["title"],
                     "body": entry.get("body") or bodies.get(entry.get("key"), ""), "level": entry["level"],
                     "delivered": list(entry.get("channels") or []), "pending": list(entry.get("failed") or [])})
    rows.sort(key=lambda row: row["t"], reverse=True)
    return rows[:limit]


def main() -> None:
    out = Path(sys.argv[1])
    stop = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    out.mkdir(parents=True, exist_ok=True)
    cfg = config.load(str(Path(__file__).resolve().parents[2] / "config.toml"))
    cfg["status_url"] = STATUS_URL
    end = now_utc().replace(second=0, microsecond=0)
    state, sent, now = play(cfg, end - timedelta(minutes=stop), stop)
    state["sent"] = [{"t": iso(t), "title": m.title, "body": m.body, "level": m.level, "key": m.key,
                      "channels": ["ntfy"], "failed": []} for t, m in reversed(sent)]
    rep = report.Report(cfg, state, now)
    (out / "status.md").write_text(rep.markdown(), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(rep.snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
    messages = [{"id": f"planspiel{i:04d}", "time": int(t.timestamp()), "event": "message", "topic": "testthema",
                 "title": m.title, "message": m.body, "priority": NTFY_PRIORITY.get(m.level, 3),
                 "tags": NTFY_TAGS.get(m.level, []), "click": m.url} for i, (t, m) in enumerate(sent)]
    (out / "meldungen.json").write_text(json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "zustand.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"{len(messages)} Meldungen bis Minute {stop}, Lagebericht von {iso(now)}")


if __name__ == "__main__":
    main()
