"""Datenquellen. Jede Quelle liefert Signale und vermerkt, wie frisch ihre Daten sind."""
from __future__ import annotations

import logging

from ..model import iso
from . import cloudflare, energy_charts, frequency, ioda, news

log = logging.getLogger("blackout_radar")

COLLECTORS = {
    "frequency": frequency.collect,
    "load": energy_charts.collect,
    "ioda": ioda.collect,
    "cloudflare": cloudflare.collect,
    "news": news.collect,
}


def collect_all(cfg: dict, state: dict, now, context: dict | None = None):
    """Fragt alle eingeschalteten Quellen ab. Ein Fehler einer Quelle stoppt die anderen nicht."""
    signals, health = [], {}
    cursors = state.setdefault("cursors", {})
    book = state.setdefault("sources", {})
    for name, func in COLLECTORS.items():
        section = cfg["sources"].get(name) or {}
        if not section.get("enabled"):
            continue
        cursor = cursors.setdefault(name, {})
        entry = book.setdefault(name, {"last_ok": None, "fail_since": None, "last_error": None, "alerted": False})
        try:
            found = func(section, cursor, now, context or {})
            signals += found
            entry.update({"last_ok": iso(now), "fail_since": None, "last_error": None})
            health[name] = {"ok": True, "signals": len(found), "data_time": cursor.get("data_time"),
                            "note": cursor.get("note", "")}
        except Exception as err:  # eine kaputte Quelle darf den Lauf nicht abbrechen
            log.warning("Quelle %s fehlgeschlagen: %s", name, err)
            entry["last_error"] = str(err)[:300]
            entry["fail_since"] = entry["fail_since"] or iso(now)
            health[name] = {"ok": False, "error": str(err)[:300], "data_time": cursor.get("data_time")}
    return signals, health
