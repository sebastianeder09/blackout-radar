"""Erzeuger des Gemeindeverzeichnisses (tools/orte_at.py): Liest er die Listen von Statistik Austria richtig?"""
import tempfile
import unittest
from pathlib import Path

from blackout_radar import gemeindeliste
from tools import orte_at

GEMEINDEN = """Gemeindeliste sortiert nach Gemeindekennziffer, Gebietsstand 2026;;;;;
Erstellt am:;26.11.2026 08:47:08;;;;
Gemeindekennziffer;Gemeindename;Gemeindecode;Status;PLZ des Gem.Amtes;weitere Postleitzahlen
10101;Eisenstadt;10101;SR;7000;
41122;Tragwein;41122;M;4284;
60629;Lieboch;60629;M;8501;
90001;Wien;90101;SR;1010;
90001;Wien;90201;SR;1020;
Quelle: STATISTIK AUSTRIA. erstellt am 26.11.2026 08:47:08
"""
BEZIRKE = """Politische Bezirke, Gebietsstand 2026;;;;
Erstellt am:;26.11.2026 08:47:01;;;
Bundeslandkennziffer;Bundesland;Kennziffer pol. Bezirk;Politischer Bezirk;Politischer Bez. Code
1;Burgenland;101;Eisenstadt(Stadt);101
4;Oberösterreich;411;Perg;411
9;Wien;900;Wien(Stadt);900
9;Wien;900;Wien  1.,Innere Stadt;901
9;Wien;900;Wien 10.,Favoriten;910
"""


class Lesen(unittest.TestCase):
    def test_towns_are_grouped_by_province(self):
        # Wien steht je Gemeindebezirk einmal in der Liste und zählt als eine Gemeinde.
        self.assertEqual(orte_at.gemeinden(GEMEINDEN),
                         {"AT-1": ["Eisenstadt"], "AT-4": ["Tragwein"], "AT-6": ["Lieboch"], "AT-9": ["Wien"]})

    def test_districts_and_the_districts_of_vienna(self):
        districts, vienna = orte_at.bezirke(BEZIRKE)
        self.assertEqual(districts, {"AT-1": ["Eisenstadt(Stadt)"], "AT-4": ["Perg"]})
        self.assertEqual(vienna, ["Innere Stadt", "Favoriten"])

    def test_date_of_the_directory(self):
        self.assertEqual(orte_at.stand(GEMEINDEN), "Gebietsstand 2026, erstellt am 26.11.2026")
        with self.assertRaises(ValueError):
            orte_at.stand("Gemeindekennziffer;Gemeindename\n10101;Eisenstadt\n")

    def test_incomplete_directory_is_not_written(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "gemeindeliste.py"
            with self.assertRaises(ValueError):
                orte_at.schreiben({"gemliste_knz.csv": GEMEINDEN, "polbezirke.csv": BEZIRKE}, target)
            self.assertFalse(target.exists())

    def test_names_with_a_separator_are_refused(self):
        with self.assertRaises(ValueError):
            orte_at.block(["Linz", "Wels|Steyr"], "    ")


class Schreiben(unittest.TestCase):
    def test_shipped_list_is_what_the_generator_writes(self):
        """Die Liste im Repository ist unverändert das, was der Erzeuger aus dem Verzeichnis macht."""
        year, made = gemeindeliste.STAND.removeprefix("Gebietsstand ").split(", erstellt am ")
        towns = [f"Gemeindeliste sortiert nach Gemeindekennziffer, Gebietsstand {year};;;;;",
                 f"Erstellt am:;{made} 08:47:08;;;;",
                 "Gemeindekennziffer;Gemeindename;Gemeindecode;Status;PLZ des Gem.Amtes;weitere Postleitzahlen"]
        for land, names in gemeindeliste.GEMEINDEN.items():
            towns += [f"{land[-1]}{number:04d};{name};;;;" for number, name in enumerate(names.split("|"), 1)]
        districts = ["Bundeslandkennziffer;Bundesland;Kennziffer pol. Bezirk;Politischer Bezirk;Politischer Bez. Code"]
        for land, names in gemeindeliste.BEZIRKE.items():
            districts += [f"{land[-1]};;;{name};" for name in names.split("|")]
        districts += [f"9;Wien;900;Wien {number:>2}.,{name};" for number, name
                      in enumerate(gemeindeliste.WIEN.split("|"), 1)]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "gemeindeliste.py"
            summary = orte_at.schreiben({"gemliste_knz.csv": "\n".join(towns), "polbezirke.csv": "\n".join(districts)},
                                        target)
            self.assertEqual(target.read_text(encoding="utf-8"),
                             Path(gemeindeliste.__file__).read_text(encoding="utf-8"))
        self.assertIn("23 Wiener Bezirke", summary)


if __name__ == "__main__":
    unittest.main()
