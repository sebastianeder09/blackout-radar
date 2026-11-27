"""Stichprobe aus der Gegenprobe (tests/gegenprobe.py): gedachte Ausfälle in echten ruhigen Wochen.

Die ganze Gegenprobe dauert Minuten und läuft von Hand. Hier stehen die Fälle, an denen die
Auswertung nachgeschärft wurde, und eine bekannte Grenze.
"""
import unittest
from datetime import datetime, timezone

from . import gegenprobe


def utc(day: int, month: int, hour: int):
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


class Sample(unittest.TestCase):
    def test_every_day_has_its_cases(self):
        found = gegenprobe.cases("at-2026-11")
        self.assertEqual(len(found), 13 * 24)  # 13 Tage, je 4 Beginnzeiten, 3 Tiefen und 2 Dauern
        self.assertEqual(found[0], (utc(13, 11, 3), 0.25, 2))

    def test_monday_from_the_small_hours_into_the_morning(self):
        """Ein Viertel weniger Last von 4 bis 13 Uhr Ortszeit. Der Sonntag davor taugt nicht als Vergleich."""
        steps, peak, notes = gegenprobe.check("at-2026-11", (utc(16, 11, 3), 0.25, 9))
        self.assertEqual(notes, [])
        self.assertAlmostEqual(peak, 0.25, delta=0.03)

    def test_sunny_sunday(self):
        """26.04.2026: mittags ein Viertel weniger Last als am Vorsonntag, ganz ohne Ausfall."""
        steps, peak, notes = gegenprobe.check("at-2026-05-01", (utc(26, 4, 8), 0.25, 9))
        self.assertEqual(notes, [])

    @unittest.expectedFailure
    def test_known_limit_outage_early_on_a_holiday(self):
        """Bekannte Grenze: Das Programm kennt keine Feiertage.

        Ein Ausfall von 5 bis 7 Uhr früh am 1. Mai wird erkannt. Danach liegt die Last wegen des
        Feiertags weiter unter der eines Werktags, und das Ende wird erst am Abend gemeldet.
        """
        steps, peak, notes = gegenprobe.check("at-2026-05-01", (utc(1, 5, 3), 0.5, 2))
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
