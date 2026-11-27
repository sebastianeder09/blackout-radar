"""Medienberichte: Schlagzeilen lesen, Gebiete erkennen, Lage je Gebiet verdichten."""
import unittest
from unittest import mock

from blackout_radar import gazetteer
from blackout_radar.collectors import news
from blackout_radar.http import HttpError
from blackout_radar.model import iso

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
            # So stand es am 27.11.2026 auf gmx.at
            "Heftige Stürme an US-Ostküste: Fast eine Million ohne Strom": 1_000_000,
            "Storm leaves more than a million without power": 1_000_000,
            "Storm leaves half a million without power": 500_000,
            "Sturm: Eine halbe Million Menschen ohne Strom": 500_000,
            "Stromausfall verursacht eine Million Euro Schaden": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(news.count_people(title), expected)

    def test_relevant_headlines(self):
        for language, title in (("de", "Stromausfall in Linz: 20.000 Haushalte ohne Strom"),
                                ("de", "Blackout: Ganz Österreich ohne Strom"),
                                ("de", "Stromausfälle und Unfälle nach Schneefall"),
                                ("de", "Stromstörung in Linz-Kleinmünchen: Polizei ermittelt wegen Sachbeschädigung"),
                                ("es-419", "Apagón masivo en Cuba deja sin luz a millones"),
                                ("es-419", "Apagón afecta a Nariño y Putumayo por falla simultánea en circuitos"),
                                ("en-US", "Massive power outage hits Chile"),
                                ("en-US", "Massive blackout hits occupied Crimea"),
                                ("en-US", "Blackout-hit Cuba struggles to keep hospitals running")):
            with self.subTest(title=title):
                self.assertTrue(news.relevant(title, language))

    def test_irrelevant_headlines(self):
        for language, title in (("de", "Blackout-Vorsorge: Gemeinde lädt zum Infoabend"),
                                ("de", "Experte warnt: Blackout könnte Österreich Milliarden kosten"),
                                ("de", 'Thriller "Blackout": Ganz Europa ohne Strom'),
                                ("de", "Bürgermeister eröffnet neues Umspannwerk"),
                                ("de", "So bereiten sich Gemeinden auf einen Stromausfall vor"),
                                ("de", "Stromausfall: Diese Vorräte sollten Sie daheim haben"),
                                ("de", "Bundesheer übt Stromausfall-Szenario"),
                                ("de", "Wels simuliert großflächigen Stromausfall"),
                                ("de", "Blackout-Dorf Feldbach: So übersteht man einen Stromausfall"),
                                ("de", "Nach Stromausfall: Mehr Schutz geplant"),
                                ("es-419", "CFE anuncia cortes de luz programados en Monterrey"),
                                ("en-US", "Media blackout as election nears"),
                                ("en-US", "Blackout Wednesday: bars brace for the busiest night"),
                                ("en-US", "Rolling blackouts return to South Africa"),
                                ("en-US", "A powerful storm threatens to leave millions without power")):
            with self.subTest(title=title):
                self.assertFalse(news.relevant(title, language))

    def test_blackout_alone_counts_in_english_but_not_in_german(self):
        # Im Deutschen steht "Blackout" fast immer für Vorsorge. Alle drei standen am 26.11.2026 so in der Zeitung.
        for title in ("Was Vorarlberg dem „Blackout“-Dorf voraushat",
                      "BlackAUT prüft E-Autos als Speicher für Blackout in Graz",
                      "Blackout: Freistadt rüstet Feuerwehrhäuser auf"):
            with self.subTest(title=title):
                self.assertFalse(news.relevant(title, "de"))
        self.assertTrue(news.relevant("Blackout in Spain strands thousands of travellers", "en-US"))

    def test_kinds_of_reports(self):
        cases = {
            "Stromausfall in Linz: 20.000 Haushalte ohne Strom": "lead",
            "Kärnten: Tausende Haushalte ohne Strom": "lead",
            "Massive Blackout Hits Colombia Following Terrorist Attack on Power Grid": "lead",
            # Ursache und Ermittlungen: am Tag des Ausfalls oft schon die erste Schlagzeile
            "Stromstörung in Linz-Kleinmünchen: Polizei ermittelt wegen Sachbeschädigung": "cause",
            "Sabotage im Umspannwerk? Großer Stromausfall in Linz": "cause",
            "20.000 Haushalte ohne Strom: Polizei vermutet Vorsatz": "cause",
            "Autoridades investigan si apagón en Nariño fue un atentado de grupos armados": "cause",
            # Aufarbeitung und Wiederherstellung
            "Nach Stromausfall und Schaden an Linzer Umspannwerk ermittelt der Staatsschutz": "follow",
            "Nach Stromstörung in Kleinmünchen: Linz Netz verschärft Schutz der Umspannwerke": "follow",
            "Stromausfall in Linz behoben: Strom wieder da": "follow",
            "Power being restored in stages after massive blackout hits Sabah’s east coast": "follow",
            "Tras el apagón masivo, el gobierno investiga las causas": "follow",
            # Kritik und Politik sind Aufarbeitung. Die erste Schlagzeile stand am 26.11.2026 auf heute.at.
            "„Grob fahrlässig“ – ÖVP-Attacke nach Stromausfall": "follow",
            "Kritik an Linz AG nach Stromausfall": "follow",
            "Linzer Stromausfall: Schaden in Millionenhöhe": "follow",
            "Stromausfall in Linz hat politisches Nachspiel": "follow",
            "Stromausfall in Linz: Täter weiter flüchtig": "cause",
            "Stromausfall in Linz: Polizei regelt den Verkehr": "cause",
            # Folgen: am Tag des Ausfalls ein Erstbericht, später Aufarbeitung
            "Verkehrschaos nach Stromausfall in Linz": "cause",
            "Thousands stranded after massive power outage hits Heathrow": "cause",
            # "Ursache unklar" steht fast immer im ersten Bericht
            "Stromausfall in Linz: Ursache noch unklar": "lead",
            "Stromausfälle und Unfälle nach Schneefall": "lead",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertTrue(news.relevant(title))
                self.assertEqual(news.phase(title), expected)

    def test_medium_is_the_site_without_regional_subdomain(self):
        cases = {"ooe.orf.at": "orf.at", "kaernten.orf.at": "orf.at", "www.nachrichten.at": "nachrichten.at",
                 "thestar.com.my": "thestar.com.my", "www.bbc.co.uk": "bbc.co.uk", "newsukraine.rbc.ua": "rbc.ua",
                 "en.hespress.com": "hespress.com", "diariodelsur.com.co": "diariodelsur.com.co"}
        for host, expected in cases.items():
            with self.subTest(host=host):
                self.assertEqual(news.medium(host), expected)

    def test_nationwide_wording(self):
        cases = {
            ("Blackout: Ganz Österreich ohne Strom", "AT"): True,
            ("Colapso total del sistema eléctrico en Cuba", "CU"): True,
            ("Island-wide blackout hits Puerto Rico", "PR"): True,
            ("Nationwide blackout hits Brazil", "BR"): True,
            ("Apagón general en España", "ES"): True,
            ("Ganz Deutschland ohne Strom", "DE"): True,
            ("Stromausfall in Linz", "AT-4"): False,
            # In großen Staaten ist mit "alles ohne Strom" meist eine Region, Stadt oder Insel gemeint.
            # Die erste Schlagzeile stand am 27.11.2026 auf reportermaceio.com.br.
            ("Apagão Geral Afeta Manaus e Municípios do Amazonas, Roraima e Pará, Deixando Milhares Sem Energia",
             "BR"): False,
            ("Island-wide power outage hits Oahu, Hawaii", "US"): False,
            ("Entire island of Tenerife without power", "ES"): False,
            ("Ganz Berlin ohne Strom", "DE"): False,
        }
        for (title, area), expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(news.nationwide(title, area), expected)


class Places(unittest.TestCase):
    def test_areas_named_in_headlines(self):
        cases = {
            "Stromausfall in Linz: 20.000 Haushalte ohne Strom": ["AT-4"],
            "Blackout in Linz-Kleinmünchen": ["AT-4"],
            "Stromausfall im Mühlviertel, Österreich": ["AT-4"],  # das Bundesland schließt den Staat ein
            "Stromausfall in Wien-Favoriten": ["AT"],
            "Stromausfall in OÖ: 5.000 Haushalte betroffen": ["AT-4"],
            "Stromausfall legt Linzer Innenstadt lahm": ["AT-4"],
            "Stromausfall in Freistadt und Perg": ["AT-4"],
            "Kärnten: Tausende Haushalte ohne Strom": ["AT"],
            "Österreichs Staatsschutz ermittelt nach Stromausfall": ["AT"],
            "Apagón masivo en Nariño, Putumayo, Cauca y Huila: reportan presunto ataque": ["CO"],
            "Apagón masivo en Salta: varios municipios quedaron sin energía": ["AR"],
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

    def test_short_forms_of_the_united_states(self):
        cases = {
            # Die ersten beiden standen am 27.11.2026 so in der Zeitung und blieben ohne Zuordnung.
            "Thanksgiving storm slams U.S., leaving millions without power": ["US"],
            "Heftige Stürme an US-Ostküste: Fast eine Million ohne Strom": ["US"],
            "Millions without power in US storm": ["US"],
            "USA: Millionen ohne Strom nach Wintersturm": ["US"],
            "Stromausfall in den USA und Kanada": ["US", "CA"],
            "Tormenta deja sin luz a millones en EE.UU.": ["US"],
            "Tempestade deixa milhões sem energia nos EUA": ["US"],
            "Massive power outage hits US Midwest": ["US"],
            # Handelnder oder Beobachter, nicht betroffen
            "Cuba blackout: US embassy urges citizens to conserve fuel": ["CU"],
            "Blackout in Kuba: USA schicken Hilfe": ["CU"],
            "Cuba's grid collapses as US fuel blockade tightens": ["CU"],
            "Kuba: Stromausfall nach neuen US-Sanktionen": ["CU"],
            "Venezuela blames US for nationwide blackout": ["VE"],
            "Stromausfall: US-Konzern stoppt Produktion in Linz": ["AT-4"],
            "Stromausfall bei US-Konzern": [],
            "Apagón deja pérdidas por US$ 10 millones": [],
            "Apagón: pérdidas en US$ 10 millones": [],
            "Stromausfall in US-Konzern": [],
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(gazetteer.find(title), expected)

    def test_island_is_iceland_only_in_german(self):
        self.assertEqual(gazetteer.find("Stromausfall auf Island: Sturm legt Leitungen lahm", "de"), ["IS"])
        self.assertEqual(gazetteer.find("Island-wide blackout hits Puerto Rico", "en-US"), ["PR"])
        self.assertEqual(gazetteer.find("Entire Island Without Power After Storm", "en-US"), [])
        self.assertEqual(gazetteer.find("Power outage on Long Island leaves thousands in the dark", "en-US"), ["US"])
        self.assertEqual(gazetteer.find("Stromausfall auf Long Island"), ["US"])
        # Puerto Rico ist ein Außengebiet der USA, betroffen ist nur die Insel
        self.assertEqual(gazetteer.find("Island-wide blackout hits US territory of Puerto Rico", "en-US"), ["PR"])


class Feed(unittest.TestCase):
    def test_google_news_feed_is_parsed(self):
        with mock.patch.object(news.http, "get_text", return_value=FEED) as get_text:
            items = news.fetch("Stromausfall Linz", "de", "AT")
        self.assertEqual(get_text.call_args.kwargs["params"]["ceid"], "AT:de")
        self.assertEqual(len(items), 1)  # der Eintrag ohne Datum fällt weg
        item = items[0]
        self.assertEqual(item["title"], "Stromausfall in Linz: 20.000 Haushalte ohne Strom")
        self.assertEqual(item["domain"], "orf.at")  # die Landesstudios des ORF zählen als ein Medium
        self.assertEqual(item["when"], at(-20))


def item(title, domain, when):
    return {"title": title, "domain": domain, "when": when, "url": f"https://{domain}/{abs(hash(title))}"}


class Stories(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["news"]
        self.cursor = {"since": iso(at(-24 * 60))}  # die Überwachung läuft schon seit gestern
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

    def test_first_headline_with_the_cause_counts_as_first_report(self):
        # So begann die Berichterstattung über den Linzer Stromausfall vom 23.11.2026.
        self.feeds["Mühlviertel"] = [item("Stromstörung in Linz-Kleinmünchen: Polizei ermittelt wegen Sachbeschädigung",
                                          "tips.at", at(-5))]
        signal = self.media_signals(self.collect(0))["AT-4"]
        self.assertTrue(signal.active)
        self.assertEqual(signal.started_at, at(-5))

    def test_headline_without_a_place_needs_a_second_medium(self):
        reports = [item("Großflächiger Stromausfall: Ermittlungen wegen schwerer Sachbeschädigung in Umspannwerk",
                        "laumat.at", at(-20))]
        self.feeds["Mühlviertel"] = reports
        self.assertEqual(self.media_signals(self.collect(0)), {})
        reports.append(item("20.000 Haushalte ohne Strom: Polizei vermutet Vorsatz", "kurier.at", at(3)))
        signal = self.media_signals(self.collect(5))["AT-4"]
        self.assertEqual(signal.metrics["sources"], 2)
        self.assertAlmostEqual(signal.severity, 40_000 / 1_530_000, places=3)

    def test_reports_about_the_cause_on_later_days_trigger_nothing(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Linz: 20.000 Haushalte ohne Strom", "nachrichten.at", at(-20))]
        self.assertTrue(self.media_signals(self.collect(0))["AT-4"].active)
        # vier Stunden später: Die Lage läuft noch, Berichte über die Ursache verlängern sie nicht
        self.feeds["Mühlviertel"] = [item("Sabotage im Umspannwerk? Großer Stromausfall in Linz", "5min.at", at(230))]
        self.assertEqual(self.media_signals(self.collect(240))["AT-4"].metrics["sources"], 1)
        self.assertFalse(self.media_signals(self.collect(345))["AT-4"].active)  # sechs Stunden nach dem Erstbericht
        # am nächsten Tag: Aufarbeitung
        day = 24 * 60
        self.feeds["Mühlviertel"] = [
            item("Staatsschutz ermittelt nach Stromausfall in Linz", "diepresse.com", at(day - 30)),
            item("20.000 von Stromausfall in Linz betroffen: Jetzt ermittelt Staatsschutz", "5min.at", at(day - 10))]
        signals = self.collect(day)
        self.assertEqual(self.media_signals(signals), {})
        self.assertEqual(len([s for s in signals if s.kind == "news"]), 2)  # als Beleg bleiben die Berichte erhalten
        # ein neuer Ausfall im selben Gebiet wird trotzdem sofort erkannt
        self.feeds["Mühlviertel"] = [item("Stromausfall in Wels: 3.000 Haushalte ohne Strom", "tips.at", at(day + 50))]
        self.assertTrue(self.media_signals(self.collect(day + 60))["AT-4"].active)

    def test_after_a_restart_reports_about_the_cause_do_not_start_a_story(self):
        self.cursor.clear()  # Vorgeschichte unbekannt
        self.feeds["Mühlviertel"] = [item("Stromausfall durch Sabotage in Umspannwerk in Linz", "orf.at", at(-30))]
        self.assertEqual(self.media_signals(self.collect(0)), {})
        self.assertEqual(self.media_signals(self.collect(170)), {})
        self.feeds["Mühlviertel"] = [item("Stromausfall in Linz: 20.000 Haushalte ohne Strom", "orf.at", at(175))]
        self.assertTrue(self.media_signals(self.collect(180))["AT-4"].active)  # ein Erstbericht zählt immer

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

    def test_austria_search_counts_only_headlines_that_name_a_place_in_austria(self):
        # Die Suche findet auch Auslandsberichte österreichischer Medien. Der erste stand am 27.11.2026 auf gmx.at.
        self.feeds["Österreich"] = [
            item("Heftige Stürme an US-Ostküste: Fast eine Million ohne Strom", "gmx.at", at(-50)),
            item("Wintersturm: Millionen Menschen ohne Strom", "krone.at", at(-40)),
            item("Millionen ohne Strom: Sturm legt Stromnetz lahm", "heute.at", at(-30)),
            item("Schneesturm: Millionen Haushalte ohne Strom", "oe24.at", at(-20))]
        signals = self.collect(0)
        self.assertEqual(self.media_signals(signals), {})
        self.assertEqual({s.area for s in signals}, {"US"})  # nur der Bericht mit Ort bleibt als Beleg
        self.assertNotIn("AT", self.cursor["stories"])
        # Zwei Medien, die Österreich nennen, reichen weiterhin
        self.feeds["Österreich"] += [item("Stromausfall in Wien und Niederösterreich", "orf.at", at(2)),
                                     item("Großer Stromausfall in Wien", "kurier.at", at(4))]
        signal = self.media_signals(self.collect(5))["AT"]
        self.assertEqual(signal.metrics["sources"], 2)
        self.assertIsNone(signal.severity)  # die Millionen aus den Auslandsberichten zählen nicht mit

    def test_whole_island_is_not_the_whole_country_in_a_large_state(self):
        self.feeds["nationwide blackout"] = [
            item("Island-wide power outage hits Oahu, Hawaii", "hawaiinewsnow.com", at(-30)),
            item("Entire island of Oahu without power, Hawaii officials say", "khon2.com", at(-25)),
            item("Island-wide blackout on Oahu: Hawaii utility investigates", "staradvertiser.com", at(-20))]
        seen = {}
        for minute in range(0, 20, 5):
            seen.update(self.media_signals(self.collect(minute)))
        signal = seen["US"]
        self.assertFalse(signal.metrics["nationwide"])
        self.assertIsNone(signal.severity)
        self.assertEqual(signal.detail, "3 Medien berichten, Größe unbekannt")
        self.assertNotIn("IS", seen)  # "Island" ist hier nicht der Staat Island

    def test_aftermath_of_an_earlier_outage_after_a_fresh_start(self):
        # Der Monitor ging am 27.11.2026 in Betrieb, vier Tage nach dem Linzer Stromausfall. So sahen die
        # Berichte aus. Ohne Vorgeschichte würde der nächste Bericht über die Ermittlungen als neuer Ausfall zählen.
        self.cursor.clear()
        aftermath = [
            item("Nach Stromstörung in Kleinmünchen: Linz Netz verschärft Schutz der Umspannwerke", "meinbezirk.at",
                 at(-1133)),
            item("Nach einem massiven Stromausfall in Linz ermittelt der Staatsschutz.", "heute.at", at(-762))]
        self.feeds["Mühlviertel"] = aftermath
        self.assertEqual(self.collect(0), [])
        self.assertEqual(self.cursor["closed"], {"AT-4": iso(at(-762))})
        aftermath.append(item("Staatsschutz ermittelt: Sabotage hinter Stromausfall in Linz?", "krone.at", at(230)))
        aftermath.append(item("Verkehrschaos nach Stromausfall in Linz: Das sind die Lehren", "tips.at", at(232)))
        self.assertEqual(self.media_signals(self.collect(240)), {})
        # ein neuer Ausfall wird trotzdem sofort erkannt
        aftermath.append(item("Stromausfall in Wels: 3.000 Haushalte ohne Strom", "nachrichten.at", at(250)))
        self.assertTrue(self.media_signals(self.collect(255))["AT-4"].active)

    def test_first_run_looks_back_a_week(self):
        self.cursor.clear()
        asked = []

        def fake(query, language, country, edition=None):
            asked.append(query)
            if "when:7d" in query and "Mühlviertel" in query:
                return [item("Stromausfall in Linz: 20.000 Haushalte ohne Strom", "nachrichten.at", at(-4 * 24 * 60)),
                        item("Stromausfall in Wels", "tips.at", at(-10))]  # frische Berichte liest die übliche Suche
            if "Mühlviertel" in query:
                return [item("Linzer Stromausfall: Verdächtiger festgenommen", "krone.at", at(190))]
            return []

        with mock.patch.object(news, "fetch", side_effect=fake):
            self.assertEqual(self.collect(0), [])
            self.assertEqual(sum("when:7d" in query for query in asked), 2)  # je Vorrang-Suche eine Rückschau
            self.assertEqual(self.cursor["closed"], {"AT-4": iso(at(-4 * 24 * 60))})
            asked.clear()
            self.assertEqual(self.media_signals(self.collect(200)), {})  # die Festnahme ist Aufarbeitung
            self.assertEqual(sum("when:7d" in query for query in asked), 0)

    def test_failed_look_back_is_repeated(self):
        self.cursor.clear()
        asked = []

        def fake(query, language, country, edition=None):
            asked.append(query)
            if "when:7d" in query and len(asked) < 3:
                raise HttpError("HTTP 429 von news.google.com")
            return []

        with mock.patch.object(news, "fetch", side_effect=fake):
            self.collect(0)
            self.assertNotIn("history", self.cursor)
            self.assertIn("HTTP 429", self.cursor["note"])
            self.collect(5)
            self.assertEqual(self.cursor["history"], iso(at(5)))
            self.assertEqual(sum("when:7d" in query for query in asked), 4)

    def test_without_earlier_reports_the_first_headline_may_name_the_cause(self):
        self.feeds["Mühlviertel"] = [item("Staatsschutz ermittelt: Sabotage hinter Stromausfall in Linz?", "krone.at",
                                          at(-10))]
        self.assertTrue(self.media_signals(self.collect(0))["AT-4"].active)

    def test_criticism_after_an_outage_is_aftermath(self):
        self.feeds["Mühlviertel"] = [item("„Grob fahrlässig“ – ÖVP-Attacke nach Stromausfall", "heute.at", at(-30)),
                                     item("Kritik an Linz AG nach Stromausfall", "krone.at", at(-20))]
        self.assertEqual(self.media_signals(self.collect(0)), {})
        # danach gelten auch Berichte über die Ermittlungen als Aufarbeitung
        self.feeds["Mühlviertel"].append(item("Stromausfall in Linz: Polizei ermittelt wegen Sabotage", "orf.at", at(3)))
        self.assertEqual(self.media_signals(self.collect(5)), {})

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
