"""Lastauswertung an echten Reihen: drei große Stromausfälle in sechs Ländern und ruhige Wochen mit Feiertagen.

Die Reihen in tests/data/lastreihen.json stammen von Energy-Charts (Fraunhofer ISE, Daten von
ENTSO-E, CC BY 4.0). Sie wurden mit "python -m blackout_radar probe --only replay" abgerufen.
Jede Reihe beginnt gut eine Woche vor dem Tag, um den es geht, weil die Auswertung mit
demselben Wochentag der Vorwoche vergleicht.
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


class Replay(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["load"]

    def course(self, name: str) -> list:
        """Befunde einer Reihe als (Zeit des neuesten Werts, Signal), so wie der Monitor sie gesehen hätte."""
        country, points = real(name)
        return probe.replay(country, points, self.cfg)

    def one_outage(self, name: str):
        """Prüft, dass es genau einen Einbruch mit einem Ende gibt. Liefert (Beginn, tiefster Stand, Ende)."""
        found = self.course(name)
        starts = {iso(signal.started_at) for _, signal in found}
        ends = [signal for _, signal in found if not signal.active]
        self.assertEqual(len(starts), 1, f"{name}: mehrere Einbrüche {sorted(starts)}")
        self.assertEqual(len(ends), 1, name)
        self.assertIs(found[-1][1], ends[0], f"{name}: nach dem Ende kam noch ein Befund")
        return starts.pop(), max(signal.severity for _, signal in found), iso(ends[0].ended_at)


class QuietWeeks(Replay):
    """Wochenenden und Feiertage senken die Last deutlich. Das darf kein Befund sein."""

    def test_no_finding_in_eight_real_weeks(self):
        # Österreich: drei Wochen im November, die Wochen um den 1. Mai, Weihnachten bis Dreikönig.
        # Deutschland: drei Wochen im November. Ausgewertet wird jeweils ab dem achten Tag.
        for name in ("at-2026-11", "at-2026-05-01", "at-2026-01-01", "de-2026-11"):
            self.assertEqual(self.course(name), [], name)


class SunnySunday(Replay):
    """Am Sonntag, 26.04.2026 lag die Last in Österreich nachmittags um mehr als ein Viertel unter der des Vorsonntags.

    Das ist das Wetter (Sonne, Photovoltaik) und kein Ausfall. Der Samstag davor verlief ähnlich wie der Sonntag.
    """

    def test_sunday_afternoon_far_below_the_sunday_before(self):
        _, points = real("at-2026-05-01")
        load = dict(points)
        self.assertLess(load["2026-04-26T14:00:00Z"] / load["2026-04-19T14:00:00Z"], 0.74)
        self.assertGreater(load["2026-04-26T14:00:00Z"] / load["2026-04-25T14:00:00Z"], 0.90)

    def test_outage_in_the_morning_does_not_drag_on_into_the_afternoon(self):
        """Gedachter Ausfall von 8 bis 10 Uhr UTC, halbe Last. Die echten Werte danach sind unverändert."""
        country, points = real("at-2026-05-01")
        changed = [[stamp, value * 0.5 if "2026-04-26T08:00:00Z" <= stamp < "2026-04-26T10:00:00Z" else value]
                   for stamp, value in points if stamp < "2026-04-27T12:00:00Z"]
        found = probe.replay(country, changed, self.cfg)
        self.assertEqual({iso(signal.started_at) for _, signal in found}, {"2026-04-26T08:00:00Z"})
        self.assertAlmostEqual(max(signal.severity for _, signal in found), 0.5, delta=0.03)
        self.assertFalse(found[-1][1].active)
        self.assertEqual(iso(found[-1][1].ended_at), "2026-04-26T10:00:00Z")
        self.assertEqual(iso(found[-1][0]), "2026-04-26T10:45:00Z")  # zwei ruhige Werte, die schon zählen


class RealOutages(Replay):
    def test_portugal_2025(self):
        """Landesweiter Ausfall am 28.04.2025 ab 10:33 UTC, Netz gegen 23 Uhr UTC wieder aufgebaut."""
        start, lowest, end = self.one_outage("pt-2025-04-28")
        self.assertEqual(start, "2025-04-28T10:00:00Z")  # Stundenwerte: die Stunde, in der es begann
        self.assertGreater(lowest, 0.97)
        self.assertEqual(end, "2025-04-28T23:00:00Z")
        rebuild = {iso(when): signal.severity for when, signal in self.course("pt-2025-04-28") if signal.active}
        # Wiederaufbau am Abend: neuester gültiger Wert ist jeweils der der Vorstunde
        self.assertGreater(rebuild["2025-04-28T19:00:00Z"], 0.90)
        self.assertLess(rebuild["2025-04-28T22:00:00Z"], 0.40)
        self.assertLess(rebuild["2025-04-28T23:00:00Z"], 0.25)

    def test_czech_republic_2025(self):
        """Ausfall in Prag und Nordböhmen am 04.07.2025 ab etwa 10:00 UTC, bis zum Abend behoben."""
        start, lowest, end = self.one_outage("cz-2025-07-04")
        self.assertEqual(start, "2025-07-04T10:00:00Z")
        self.assertTrue(0.25 < lowest < 0.30, lowest)
        self.assertEqual(end, "2025-07-04T14:00:00Z")

    def test_bosnia_2024(self):
        """Westbalkan am 21.06.2024 ab etwa 10:20 UTC. Am Tag danach darf nichts mehr anschlagen."""
        start, lowest, end = self.one_outage("ba-2024-06-21")
        self.assertEqual(start, "2024-06-21T10:00:00Z")
        self.assertGreater(lowest, 0.80)
        self.assertEqual(end, "2024-06-21T13:00:00Z")

    def test_montenegro_2024(self):
        start, lowest, end = self.one_outage("me-2024-06-21")
        self.assertEqual(start, "2024-06-21T10:00:00Z")
        self.assertGreater(lowest, 0.60)
        self.assertEqual(end, "2024-06-21T12:00:00Z")

    def test_croatia_2024_stays_quiet(self):
        """Nur Dalmatien war betroffen, landesweit zu wenig für einen Befund.

        Der Samstag danach lag nach einem heißen Freitag um ein Viertel unter dem Vortag.
        Im Vergleich mit dem Samstag der Vorwoche ist das kein Einbruch.
        """
        self.assertEqual(self.course("hr-2024-06-21"), [])


class Spain2025(Replay):
    """Stromausfall auf der Iberischen Halbinsel am 28.04.2025, Beginn 10:33 UTC.

    Die spanischen Lastwerte brechen nicht ein, sie bleiben aus: von 10:30 UTC bis zum
    Abend des nächsten Tages gibt es keinen einzigen Wert.
    """

    def setUp(self):
        super().setUp()
        self.cfg["countries"] = ["es"]
        self.country, self.points = real("es-2025-04-28")

    def test_values_are_missing_from_the_first_minute(self):
        stamps = {stamp for stamp, _ in self.points}
        self.assertIn("2025-04-28T10:15:00Z", stamps)
        self.assertFalse({stamp for stamp in stamps if "2025-04-28T10:30:00Z" <= stamp < "2025-04-29T22:00:00Z"})
        self.assertIn("2025-04-29T22:00:00Z", stamps)

    def test_no_false_statement_from_missing_values(self):
        self.assertEqual(self.course("es-2025-04-28"), [])

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
