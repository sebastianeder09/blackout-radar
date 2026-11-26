"""Medienberichte: Schlagzeilen lesen, Gebiete erkennen, Lage je Gebiet verdichten."""
import unittest
from unittest import mock

from blackout_radar import gazetteer
from blackout_radar.collectors import news
from blackout_radar.http import HttpError

from .helpers import at, make_cfg

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Suche</title>
<item><title>Stromausfall in Linz: 20.000 Haushalte ohne Strom - ooe.ORF.at</title>
<link>https://news.google.com/rss/articles/abc</link><guid isPermaLink="false">abc</guid>
<pubDate>Thu, 26 Nov 2026 10:40:00 GMT</pubDate>
<source url="https://ooe.orf.at">ooe.ORF.at</source></item>
<item><title>Ohne Datum - Beispiel</title><link>https://example.org/x</link>
<source url="https://www.example.org">Beispiel</source></item>
</channel></rss>"""


class Headlines(unittest.TestCase):
    def test_people_counts(self):
        cases = {
            "Stromausfall in Linz: 20.000 Haushalte ohne Strom": 40_000,
            "Blackout leaves 1.2 million customers without power in Texas": 2_400_000,
            "Apagón masivo en Cuba deja sin luz a millones": 2_000_000,
            "Power outage: 5,000 people affected": 5_000,
            "Hunderttausende ohne Strom nach Sturm": 200_000,
            "Tens of thousands without power after storm": 20_000,
            "Stromausfall verursacht 3 Millionen Euro Schaden": None,
            "Stromausfall in Wels": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(news.count_people(title), expected)

    def test_relevant_headlines(self):
        for title in ("Stromausfall in Linz: 20.000 Haushalte ohne Strom",
                      "Apagón masivo en Cuba deja sin luz a millones",
                      "Massive power outage hits Chile",
                      "Blackout: Ganz Österreich ohne Strom"):
            with self.subTest(title=title):
                self.assertTrue(news.relevant(title))

    def test_irrelevant_headlines(self):
        for title in ("Blackout-Vorsorge: Gemeinde lädt zum Infoabend",
                      "Experte warnt: Blackout könnte Österreich Milliarden kosten",
                      "CFE anuncia cortes de luz programados en Monterrey",
                      "Media blackout as election nears",
                      "Blackout Wednesday: bars brace for the busiest night",
                      'Thriller "Blackout": Ganz Europa ohne Strom',
                      "Rolling blackouts return to South Africa",
                      "Bürgermeister eröffnet neues Umspannwerk"):
            with self.subTest(title=title):
                self.assertFalse(news.relevant(title))

    def test_follow_up_reports_do_not_start_a_story(self):
        for title in ("Nach Stromausfall in Linz: Staatsschutz ermittelt",
                      "Sabotage an Umspannwerk: Ermittlungen nach Linzer Stromausfall",
                      "Stromausfall in Linz behoben: Strom wieder da",
                      "Power restored after massive blackout in Chile",
                      "Tras el apagón masivo, el gobierno investiga las causas"):
            with self.subTest(title=title):
                self.assertTrue(news.relevant(title))
                self.assertFalse(news.is_lead(title))
        self.assertTrue(news.is_lead("Stromausfall in Linz: 20.000 Haushalte ohne Strom"))

    def test_nationwide_wording(self):
        self.assertTrue(news.NATIONWIDE.search("Blackout: Ganz Österreich ohne Strom"))
        self.assertTrue(news.NATIONWIDE.search("Colapso total del sistema eléctrico en Cuba"))
        self.assertFalse(news.NATIONWIDE.search("Stromausfall in Linz"))


class Places(unittest.TestCase):
    def test_areas_named_in_headlines(self):
        cases = {
            "Stromausfall in Linz: 20.000 Haushalte ohne Strom": ["AT-4"],
            "Blackout in Linz-Kleinmünchen": ["AT-4"],
            "Stromausfall im Mühlviertel, Österreich": ["AT-4"],  # das Bundesland schließt den Staat ein
            "Stromausfall in Wien-Favoriten": ["AT"],
            "Blackout: Ganz Österreich ohne Strom": ["AT"],
            "Großflächiger Stromausfall in Spanien und Portugal": ["ES", "PT"],
            "Blackout in Spanien: Österreicher sitzen fest": ["ES"],
            "Apagón masivo en Cuba deja a millones sin luz": ["CU"],
            "Crimea blackout: Russia-installed officials report outage": ["UA-43"],
            "Russia strikes leave Kyiv without power": ["UA"],  # der Angreifer ist nicht betroffen
            "Massive power outage hits New Mexico": ["US"],
            "Naples power outage: thousands without power in Florida": ["US"],
            "Power outage reported in Georgia": [],  # Staat oder US-Bundesstaat: bewusst nicht zugeordnet
            "Stromausfall legt Bahnverkehr lahm": [],
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(gazetteer.find(title), expected)


class Feed(unittest.TestCase):
    def test_google_news_feed_is_parsed(self):
        with mock.patch.object(news.http, "get_text", return_value=FEED) as get_text:
            items = news.fetch("Stromausfall Linz", "de", "AT")
        self.assertEqual(get_text.call_args.kwargs["params"]["ceid"], "AT:de")
        self.assertEqual(len(items), 1)  # der Eintrag ohne Datum fällt weg
        item = items[0]
        self.assertEqual(item["title"], "Stromausfall in Linz: 20.000 Haushalte ohne Strom")
        self.assertEqual(item["domain"], "ooe.orf.at")
        self.assertEqual(item["when"], at(-20))


def item(title, domain, when):
    return {"title": title, "domain": domain, "when": when, "url": f"https://{domain}/{abs(hash(title))}"}


class Stories(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["news"]
        self.cursor = {}
        self.feeds = {}  # Suchtext -> Einträge
        pause = mock.patch.object(news, "PAUSE_SECONDS", 0)
        fetch = mock.patch.object(news, "fetch", side_effect=self.fake_fetch)
        pause.start()
        fetch.start()
        self.addCleanup(pause.stop)
        self.addCleanup(fetch.stop)

    def fake_fetch(self, query, language, country, edition=None):
        for part, items in self.feeds.items():
            if part in query:
                if isinstance(items, Exception):
                    raise items
                return items
        return []

    def collect(self, minute, active_areas=()):
        return news.collect(self.cfg, self.cursor, at(minute), {"active_areas": list(active_areas)})

    @staticmethod
    def media_signals(signals):
        return {s.area: s for s in signals if s.kind == "media_outage"}

    def test_one_report_is_enough_for_upper_austria(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Linz: 20.000 Haushalte ohne Strom", "nachrichten.at", at(-20))]
        signals = self.collect(0)
        signal = self.media_signals(signals)["AT-4"]
        self.assertTrue(signal.active and signal.confirmed_power)
        self.assertEqual(signal.started_at, at(-20))
        self.assertAlmostEqual(signal.severity, 40_000 / 1_530_000, places=3)
        self.assertEqual(signal.detail, "1 Medium berichtet, rund 40.000 Betroffene laut Schlagzeilen")
        self.assertEqual([s.detail for s in signals if s.kind == "news"],
                         ["Stromausfall in Linz: 20.000 Haushalte ohne Strom"])

    def test_follow_up_reports_alone_trigger_nothing(self):
        self.feeds["Mühlviertel"] = [item("Nach Stromausfall in Linz: Staatsschutz ermittelt", "nachrichten.at", at(-20))]
        signals = self.collect(0)
        self.assertEqual(self.media_signals(signals), {})
        self.assertEqual(len([s for s in signals if s.kind == "news"]), 1)  # als Beleg bleibt der Bericht erhalten

    def test_old_reports_trigger_nothing(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Linz", "nachrichten.at", at(-200))]
        self.assertEqual(self.collect(0), [])

    def test_austria_needs_two_media(self):
        self.feeds["Österreich"] = [item("Blackout: Ganz Österreich ohne Strom", "orf.at", at(-10))]
        self.assertEqual(self.media_signals(self.collect(0)), {})
        self.feeds["Österreich"].append(item("Stromausfall legt ganz Österreich lahm", "derstandard.at", at(-2)))
        signal = self.media_signals(self.collect(5))["AT"]
        self.assertEqual(signal.severity, 0.5)  # "ganz Österreich": mindestens die Hälfte angenommen
        self.assertIn("landesweiter Ausfall laut Schlagzeilen", signal.detail)

    def test_headline_about_upper_austria_found_by_the_austria_search(self):
        self.feeds["Österreich"] = [item("Stromausfall in Wels: Tausende ohne Strom", "heute.at", at(-10))]
        self.assertIn("AT-4", self.media_signals(self.collect(0)))

    def test_world_needs_three_media(self):
        world = [item("Apagón masivo en Cuba deja sin luz a millones", "a.example", at(-30)),
                 item("Gran apagón en Cuba: millones sin electricidad", "b.example", at(-25))]
        self.feeds["apagón masivo"] = world
        for minute in range(0, 20, 5):  # die Welt-Suchen wechseln sich ab
            self.assertEqual(self.media_signals(self.collect(minute)), {})
        world.append(item("Apagón general en Cuba tras colapso del sistema eléctrico", "c.example", at(15)))
        seen = {}
        for minute in range(20, 40, 5):
            seen.update(self.media_signals(self.collect(minute)))
        self.assertEqual(seen["CU"].metrics["sources"], 3)
        self.assertEqual(seen["CU"].severity, 0.5)

    def test_story_ends_when_reports_stop(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Linz", "nachrichten.at", at(-20))]
        self.assertTrue(self.media_signals(self.collect(0))["AT-4"].active)
        self.feeds.clear()
        self.assertTrue(self.media_signals(self.collect(300))["AT-4"].active)  # nach 5 Stunden noch offen
        ended = self.media_signals(self.collect(345))["AT-4"]
        self.assertFalse(ended.active)
        self.assertEqual(ended.ended_at, at(-20))
        self.assertEqual(self.cursor["stories"], {})

    def test_confirmation_search_for_measured_areas(self):
        self.feeds['"Spanien"'] = [item("Blackout in Spanien", "a.example", at(-10))]
        signals = self.collect(0, active_areas=["ES"])
        self.assertEqual([(s.kind, s.area) for s in signals], [("news", "ES")])

    def test_single_failed_search_is_only_a_note(self):
        self.feeds["Mühlviertel"] = HttpError("HTTP 503 von news.google.com")
        self.collect(0)
        self.assertIn("HTTP 503", self.cursor["note"])

    def test_all_searches_failing_is_an_error(self):
        with mock.patch.object(news, "fetch", side_effect=HttpError("HTTP 429 von news.google.com")):
            with self.assertRaises(HttpError):
                self.collect(0)


if __name__ == "__main__":
    unittest.main()
