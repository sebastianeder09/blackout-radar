"""Lastauswertung an echten Reihen: echte Stromausfälle und ruhige Wochen.

Die Reihen in tests/data/lastreihen.json stammen von Energy-Charts (Fraunhofer ISE, Daten von
ENTSO-E, CC BY 4.0). Sie wurden mit "python -m blackout_radar probe --only replay" abgerufen.
"""
import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from blackout_radar import probe
from blackout_radar.collectors import energy_charts
from blackout_radar.model import iso, parse_ts

from .helpers import make_cfg

DATA = json.loads((Path(__file__).parent / "data" / "lastreihen.json").read_text(encoding="utf-8"))["reihen"]


def real(name: str) -> tuple[str, list]:
    """Land und Lastwerte einer echten Reihe als [Zeit, MW], fehlende Werte ausgelassen."""
    row = DATA[name]
    start = parse_ts(row["start"])
    return row["country"], [[iso(start + timedelta(minutes=row["step_min"] * index)), float(value)]
                            for index, value in enumerate(row["load"]) if value is not None]


class QuietWeeks(unittest.TestCase):
    """Wochenenden und Feiertage senken die Last deutlich. Das darf kein Befund sein."""

    def setUp(self):
        self.cfg = make_cfg()["sources"]["load"]

    def test_no_finding_in_five_real_weeks(self):
        for name in ("at-2026-11", "at-2026-05-01", "at-2026-01-01", "de-2026-11"):
            country, points = real(name)
            self.assertGreater(len(points), 700, name)
            self.assertEqual(probe.replay(country, points, self.cfg), [], name)


class Spain2025(unittest.TestCase):
    """Stromausfall auf der Iberischen Halbinsel am 28.04.2025, Beginn 10:33 UTC.

    Die spanischen Lastwerte brechen nicht ein, sie bleiben aus: von 10:30 UTC bis zum
    Abend des nächsten Tages gibt es keinen einzigen Wert.
    """

    def setUp(self):
        self.cfg = make_cfg()["sources"]["load"]
        self.cfg["countries"] = ["es"]
        self.country, self.points = real("es-2025-04-28")

    def test_values_are_missing_from_the_first_minute(self):
        stamps = {stamp for stamp, _ in self.points}
        self.assertIn("2025-04-28T10:15:00Z", stamps)
        self.assertFalse({stamp for stamp in stamps if "2025-04-28T10:30:00Z" <= stamp < "2025-04-29T22:00:00Z"})
        self.assertIn("2025-04-29T22:00:00Z", stamps)

    def test_no_false_statement_from_missing_values(self):
        self.assertEqual(probe.replay(self.country, self.points, self.cfg), [])

    def test_report_says_that_values_stopped(self):
        """So hätte es der Monitor gesehen: Abfrage alle 15 Minuten, Werte zweieinhalb Stunden alt."""
        cursor, silent = {}, []
        now, end = parse_ts("2025-04-28T06:00:00Z"), parse_ts("2025-04-30T06:00:00Z")

        def fetch(base, country, moment, hours):
            limit, first = iso(moment - timedelta(minutes=150)), iso(moment - timedelta(hours=hours))
            return [point for point in self.points if first <= point[0] <= limit]

        with mock.patch.object(energy_charts, "fetch_load", side_effect=fetch):
            while now <= end:
                self.assertEqual(energy_charts.collect(self.cfg, cursor, now, {}), [])
                silent.append((iso(now), cursor["latest"]["ES"]["silent"]))
                now += timedelta(minutes=15)
        marked = [stamp for stamp, flag in silent if flag]
        self.assertEqual(marked[0], "2025-04-28T15:00:00Z")   # zweieinhalb Stunden üblich, zwei Stunden Geduld
        self.assertEqual(marked[-1], "2025-04-30T00:15:00Z")  # danach kommen wieder Werte
        self.assertEqual(cursor["latest"]["ES"]["newest"], "2025-04-30T03:30:00Z")


if __name__ == "__main__":
    unittest.main()
