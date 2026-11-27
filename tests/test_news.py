"""Medienberichte: Schlagzeilen lesen, Gebiete erkennen, Lage je Gebiet verdichten."""
import logging
import unittest
from unittest import mock

from blackout_radar import gazetteer, gemeindeliste
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


# Feed in der alten Kodierung, wie ihn die Folha de S.Paulo ausliefert
RSS_LATIN = """<?xml version="1.0" encoding="ISO-8859-1"?>
<rss version="0.91"><channel><title>Mundo</title>
<item><title>Apagão atinge cidades da Colômbia após ataque</title>
<link>https://www1.folha.uol.com.br/mundo/a.shtml</link>
<pubDate>Thu, 26 Nov 2026 07:40:00 -0300</pubDate></item>
<item><title>Sem data</title><link>https://example.org/x</link></item>
</channel></rss>""".encode("iso-8859-1")
ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>World</title>
<entry><title type="html">Massive blackout hits Europe &amp;amp; millions are in the dark</title>
<link rel="self" href="https://example.com/self"/><link rel="alternate" href="https://example.com/a"/>
<updated>2026-11-26T10:45:00Z</updated><published>2026-11-26T10:40:00Z</published></entry>
</feed>"""


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


class Europe(unittest.TestCase):
    def test_europe_counts_only_if_no_country_is_named(self):
        cases = {
            "Massive blackout hits Europe": ["EU"],
            "Europaweiter Stromausfall legt Bahnverkehr lahm": ["EU"],
            "Stromausfall in weiten Teilen Europas": ["EU"],
            "Major power outage hits Balkans": ["EU"],
            "European power grid failure leaves millions in the dark": ["EU"],
            # mit einem Land in der Schlagzeile ist das Land gemeint
            "Spain blackout: Europe's worst power outage": ["ES"],
            "Blackout in halb Europa: Auch Österreich betroffen": ["AT"],
            "Power outage hits Spain, Portugal and parts of France": ["ES", "PT", "FR"],
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(gazetteer.find(title), expected)

    def test_europe_as_the_place_of_the_outage(self):
        for title in ("Stromausfall in Europa", "Europa ohne Strom", "Europa-Blackout: Millionen ohne Strom",
                      "Stromausfall im Süden Europas", "Europas Stromnetz bricht zusammen",
                      "Europaweit ohne Strom: Lage unklar", "Blackout across Europe leaves millions without power",
                      "Europe's power grid collapses", "European blackout enters second day",
                      "Power outage hits several European countries",
                      "Europe-wide blackout leaves millions in the dark", "L'Europe plongée dans le noir",
                      "Apagón masivo en Europa"):
            with self.subTest(title=title):
                self.assertEqual(gazetteer.find(title), ["EU"])

    def test_europe_as_part_of_a_name_or_as_owner_is_no_place(self):
        """Solche Schlagzeilen gibt es mehrmals im Jahr, sie hätten als "Europa ohne Strom" gezählt."""
        cases = {
            "Stromausfall im Europa-Park: Achterbahnen stehen still": ["DE"],
            "Stromausfall bei Europa-League-Spiel: Flutlicht aus": [],
            "Power outage halts Europa League match": [],
            "Europas größtes Atomkraftwerk erneut ohne Strom": [],
            "Europe's largest nuclear power plant loses power again": [],
            "Europe’s largest nuclear plant suffers blackout": [],
            "European Union leaders meet after blackout": [],
            "European Parliament suffers blackout": [],
            "Europas Börsen nach Stromausfall im Minus": [],
            "Stromausfall: Zugverkehr europaweit gestört": [],
            "Europe-wide travel chaos after power outage": [],
            "Blackout: Europe 1 interrompt ses programmes": [],
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(gazetteer.find(title), expected)

    def test_whole_of_europe_wording(self):
        for title in ("Europaweiter Stromausfall legt Bahnverkehr lahm", "Ganz Europa ohne Strom",
                      "Stromausfall in ganz Europa", "Europaweit ohne Strom: Lage unklar",
                      "Europe-wide blackout leaves millions in the dark", "Blackout plunges all of Europe into darkness",
                      "Entire continent plunged into darkness after blackout", "Apagón masivo en toda Europa"):
            with self.subTest(title=title):
                self.assertTrue(news.nationwide(title, "EU"))
        for title in ("Massive blackout hits Europe", "Storm leaves 1.2 million without power across Europe",
                      "Nationwide blackout hits Europe's neighbours",
                      # nur die Folgen reichen europaweit, nicht der Ausfall
                      "Stromausfall bei der Bahn sorgt europaweit für Verspätungen",
                      "Blackout in Europa: Ganz Europa blickt nach Spanien"):
            with self.subTest(title=title):
                self.assertFalse(news.nationwide(title, "EU"))


class Directory(unittest.TestCase):
    """Amtliches Gemeindeverzeichnis: In welchem Bundesland liegt ein Ort, den die grobe Liste nicht kennt?"""

    def test_places_with_one_possible_province(self):
        cases = {
            "Immer wieder Stromausfälle in Lieboch: Bürgermeister klärt auf": "AT-6",  # der Anlass, 27.11.2026
            "Stromausfall in Tragwein": "AT-4",
            "Tragweins Feuerwehr nach Stromausfall im Einsatz": "AT-4",
            "Stromausfall in St. Georgen an der Gusen": "AT-4",
            "Stromausfall in Sankt Georgen an der Gusen": "AT-4",
            "Stromausfall in Zwettl an der Rodl": "AT-4",
            "Stromausfall in Wartberg ob der Aist": "AT-4",
            "Stromausfall in Bad Leonfelden und Reichenthal": "AT-4",
            "Stromausfall: Feuerwehr Schwertberg im Dauereinsatz": "AT-4",
            "Stromausfall im Bezirk Horn": "AT-3",
            "2.000 Haushalte im Bezirk Urfahr-Umgebung ohne Strom": "AT-4",
            "Stromausfall in St. Valentin": "AT-3",
            "Stromausfall in Wien-Favoriten": "AT-9",
            "Stromausfall legt Favoriten lahm": "AT-9",
            "Nach Stromausfall: Polizei ermittelt in Hallein": "AT-5",
            "Stromausfall in Bruck-Mürzzuschlag": "AT-6",
        }
        for title, land in cases.items():
            with self.subTest(title=title):
                self.assertEqual(gazetteer.austria(title), ({land}, set()))

    def test_names_that_exist_in_several_provinces_decide_nothing(self):
        for title in ("Stromausfall in Neumarkt", "Stromausfall in Sankt Georgen", "Stromausfall in Zwettl",
                      "Stromausfall in Kirchberg"):
            with self.subTest(title=title):
                certain, possible = gazetteer.austria(title)
                self.assertEqual(certain, set())
                self.assertIn("AT-4", possible)
                self.assertGreater(len(possible), 1)

    def test_everyday_words_and_twins_elsewhere_are_no_places(self):
        for title in ("Stromausfall in weiten Teilen des Bezirks", "Straßen gesperrt: Brand legt Stromversorgung lahm",
                      "Stromausfall am Sonntag: Markt und Spital betroffen", "Tausende Haushalte ohne Strom",
                      "Stromausfall in Liebenau",    # auch Graz-Liebenau
                      "Stromausfall in Wartberg",    # auch Wartberg im Mürztal
                      "Stromausfall in Weißenbach",  # gibt es in mehreren Bundesländern als Ortsteil
                      "Kein Strom in Teilen von Hamburg-Ohlsdorf"):
            with self.subTest(title=title):
                self.assertEqual(gazetteer.austria(title), (set(), set()))

    def test_directory_is_complete(self):
        towns = {land: names.split("|") for land, names in gemeindeliste.GEMEINDEN.items()}
        self.assertEqual(sorted(towns), [f"AT-{number}" for number in range(1, 10)])
        self.assertGreater(sum(len(names) for names in towns.values()), 2000)
        self.assertTrue(all(name.strip() == name and name for names in towns.values() for name in names))
        self.assertEqual(towns["AT-9"], ["Wien"])
        self.assertIn("Tragwein", towns["AT-4"])
        self.assertEqual(len(gemeindeliste.WIEN.split("|")), 23)
        self.assertEqual(sorted(gemeindeliste.BEZIRKE), [f"AT-{number}" for number in range(1, 9)])
        self.assertRegex(gemeindeliste.STAND, r"^Gebietsstand \d{4}, erstellt am \d{2}\.\d{2}\.\d{4}$")


class Feed(unittest.TestCase):
    def test_rss_in_an_old_encoding(self):
        items = news.parse_feed(RSS_LATIN, "uol.com.br")
        self.assertEqual(len(items), 1)  # der Eintrag ohne Datum fällt weg
        self.assertEqual(items[0], {"title": "Apagão atinge cidades da Colômbia após ataque", "domain": "uol.com.br",
                                    "when": at(-20), "url": "https://www1.folha.uol.com.br/mundo/a.shtml"})

    def test_atom(self):
        items = news.parse_feed(ATOM, "example.com")
        self.assertEqual(items, [{"title": "Massive blackout hits Europe & millions are in the dark",
                                  "domain": "example.com", "when": at(-20), "url": "https://example.com/a"}])

    def test_feed_is_fetched_with_a_size_limit(self):
        feed = {"domain": "uol.com.br", "hl": "pt", "url": "https://feeds.folha.uol.com.br/mundo/rss091.xml"}
        with mock.patch.object(news.http, "request", return_value=(200, {}, RSS_LATIN)) as request:
            items = news.fetch_feed(feed)
        self.assertEqual(request.call_args.args, (feed["url"],))
        self.assertEqual(request.call_args.kwargs["limit"], news.FEED_MAX_BYTES)
        self.assertEqual([entry["domain"] for entry in items], ["uol.com.br"])

    def test_every_configured_feed_has_a_medium_and_a_language(self):
        feeds = make_cfg()["sources"]["news"]["feeds"]
        self.assertEqual(len({feed["domain"] for feed in feeds}), len(feeds))
        for feed in feeds:
            with self.subTest(feed=feed["domain"]):
                self.assertTrue(feed["url"].startswith("https://"))
                self.assertIn(feed["hl"], ("en", "es", "pt"))

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
        self.wires = {}  # Medium -> Einträge seines Feeds aus Übersee
        self.asked = []  # abgefragte Feeds
        logging.disable(logging.CRITICAL)  # fehlgeschlagene Abfragen stehen im Protokoll, hier stören sie
        self.addCleanup(logging.disable, logging.NOTSET)
        for name, fake in (("PAUSE_SECONDS", 0), ("fetch", mock.Mock(side_effect=self.fake_fetch)),
                           ("fetch_feed", mock.Mock(side_effect=self.fake_feed))):
            patcher = mock.patch.object(news, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_fetch(self, query, language, country, edition=None):
        for part, items in self.feeds.items():
            if part in query:
                if isinstance(items, Exception):
                    raise items
                return items
        return []

    def fake_feed(self, feed):
        self.asked.append(feed["domain"])
        items = self.wires.get(feed["domain"], [])
        if isinstance(items, Exception):
            raise items
        return items

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
            self.assertNotIn("lookback", self.cursor)
            self.assertIn("HTTP 429", self.cursor["note"])
            self.collect(5)
            self.assertEqual(self.cursor["lookback"], iso(at(5)))
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

    def test_everything_failing_is_an_error(self):
        for feed in self.cfg["feeds"]:
            self.wires[feed["domain"]] = HttpError(f"{feed['domain']} nicht erreichbar")
        with mock.patch.object(news, "fetch", side_effect=HttpError("HTTP 429 von news.google.com")):
            with self.assertRaises(HttpError):
                self.collect(0)

    # ------------------------------------------------------------ Orte in Österreich
    def test_place_in_another_province_does_not_count_for_upper_austria(self):
        # So stand es am 27.11.2026 in der Suche für Oberösterreich. Lieboch liegt in der Steiermark.
        self.feeds["Mühlviertel"] = [
            item("Immer wieder Stromausfälle in Lieboch: Bürgermeister klärt auf", "meinbezirk.at", at(-20)),
            item("Stromausfall in Lieboch: Hunderte Haushalte betroffen", "kleinezeitung.at", at(-10))]
        signals = self.collect(0)
        self.assertEqual({s.area for s in signals}, {"AT"})
        self.assertNotIn("AT-4", self.cursor["stories"])
        self.assertEqual(sorted(self.cursor["stories"]["AT"]["named"]), ["kleinezeitung.at", "meinbezirk.at"])

    def test_village_in_upper_austria_counts_with_one_report(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Tragwein: Trafo defekt", "tips.at", at(-10))]
        self.assertTrue(self.media_signals(self.collect(0))["AT-4"].active)

    def test_village_in_upper_austria_found_by_the_austria_search(self):
        self.feeds["Österreich"] = [item("Stromausfall in Schwertberg", "krone.at", at(-10))]
        self.assertEqual(list(self.media_signals(self.collect(0))), ["AT-4"])

    def test_headline_that_only_says_austria_is_placed_by_the_directory(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Schwertberg: Österreichs Netzbetreiber im Großeinsatz",
                                          "tips.at", at(-10))]
        self.assertEqual(list(self.media_signals(self.collect(0))), ["AT-4"])
        self.feeds["Mühlviertel"] = [item("Wiener Netze: Stromausfall in Favoriten", "heute.at", at(2))]
        signals = self.collect(5)
        self.assertEqual({s.area for s in signals if s.kind == "news"}, {"AT"})  # Wien bleibt Österreich

    def test_village_elsewhere_found_by_the_austria_search_counts_for_austria(self):
        self.feeds["Österreich"] = [item("Stromausfall in Lieboch", "krone.at", at(-10))]
        signals = self.collect(0)
        self.assertEqual(self.media_signals(signals), {})  # Österreich braucht zwei Medien
        self.assertEqual([s.area for s in signals], ["AT"])

    def test_place_name_found_in_several_provinces_counts_for_austria_in_the_austria_search(self):
        self.feeds["Österreich"] = [item("Stromausfall in Neumarkt", "krone.at", at(-10))]
        signals = self.collect(0)
        self.assertEqual([s.area for s in signals], ["AT"])
        self.assertEqual(list(self.cursor["stories"]["AT"]["named"]), ["krone.at"])

    def test_place_name_shared_with_upper_austria_still_needs_a_second_medium(self):
        self.feeds["Mühlviertel"] = [item("Stromausfall in Neumarkt", "tips.at", at(-10))]
        self.assertEqual(self.media_signals(self.collect(0)), {})
        self.assertEqual(self.cursor["stories"]["AT-4"]["named"], {})
        self.feeds["Mühlviertel"].append(item("Neumarkt: Stromausfall nach Sturm", "nachrichten.at", at(2)))
        self.assertEqual(self.media_signals(self.collect(5))["AT-4"].metrics["sources"], 2)

    def test_earlier_outage_is_remembered_next_to_a_story_that_does_not_count_yet(self):
        # Zustand eines Radars von vor dem Gemeindeverzeichnis: Rückschau erledigt, daneben ein Bericht ohne Ort.
        self.cursor["lookback"] = iso(at(-600))
        self.feeds["Mühlviertel"] = [item("Stromausfall legt Betriebe lahm", "tips.at", at(-10))]
        self.assertEqual(self.media_signals(self.collect(0)), {})
        self.assertFalse(self.cursor["stories"]["AT-4"]["active"])
        self.cursor["history"] = self.cursor.pop("lookback")  # so hieß der Merker bisher
        asked = []

        def fake(query, language, country, edition=None):
            asked.append(query)
            if "Mühlviertel" not in query:
                return []
            if "when:7d" in query:
                return [item("Stromausfall in Linz: 20.000 Haushalte ohne Strom", "nachrichten.at", at(-4 * 24 * 60))]
            return [item("Stromausfall legt Betriebe lahm", "tips.at", at(-10)),
                    item("Linzer Stromausfall: Verdächtiger festgenommen", "krone.at", at(3))]

        with mock.patch.object(news, "fetch", side_effect=fake):
            self.assertEqual(self.media_signals(self.collect(5)), {})  # die Festnahme ist Aufarbeitung
            self.assertEqual(sum("when:7d" in query for query in asked), 2)  # die Rückschau wurde nachgeholt
            self.assertEqual(self.cursor["closed"], {"AT-4": iso(at(-4 * 24 * 60))})
            self.assertEqual(self.cursor["lookback"], iso(at(5)))
            self.assertNotIn("history", self.cursor)
            asked.clear()
            self.collect(10)
            self.assertEqual(sum("when:7d" in query for query in asked), 0)

    # ------------------------------------------------------------ Feeds aus Übersee
    def europe_goes_dark(self):
        self.wires["nytimes.com"] = [item("Europe-wide blackout leaves millions in the dark", "nytimes.com", at(-20))]
        self.wires["abc.net.au"] = [item("Massive blackout hits Europe", "abc.net.au", at(-15))]
        self.wires["thehindu.com"] = [item("Blackout plunges all of Europe into darkness", "thehindu.com", at(-10))]

    def test_overseas_feeds_report_a_blackout_in_europe(self):
        self.europe_goes_dark()
        signal = self.media_signals(self.collect(0))["EU"]
        self.assertEqual(signal.severity, 0.5)  # "Europe-wide": mindestens die Hälfte angenommen
        self.assertEqual(signal.detail, "3 Medien berichten, europaweiter Ausfall laut Schlagzeilen")
        self.assertEqual(signal.started_at, at(-20))

    def test_europe_without_a_number_counts_as_large_once_many_media_report(self):
        for index, feed in enumerate(self.cfg["feeds"][:6]):
            self.wires[feed["domain"]] = [item("Blackout hits Europe", feed["domain"], at(-30 + index))]
        self.assertEqual(self.media_signals(self.collect(0))["EU"].severity, None)  # vier Medien, Größe unbekannt
        signal = self.media_signals(self.collect(5))["EU"]
        self.assertEqual(signal.metrics["people"], 1_000_000)
        self.assertIn("großer Ausfall laut Schlagzeilen, Zahl unbekannt", signal.detail)

    def test_feeds_take_turns(self):
        for minute in range(0, 25, 5):
            self.collect(minute)
        self.assertEqual(len(self.asked), 20)
        self.assertEqual(sorted(self.asked), sorted(feed["domain"] for feed in self.cfg["feeds"]))
        self.assertEqual(self.asked[:4], ["nytimes.com", "aljazeera.com", "abc.net.au", "thehindu.com"])

    def test_same_medium_in_search_and_feed_counts_once(self):
        self.feeds["nationwide blackout"] = [item("Massive blackout hits Chile", "nytimes.com", at(-20)),
                                             item("Chile blackout: millions without power", "b.example", at(-18))]
        self.wires["nytimes.com"] = [item("Massive Blackout Hits Chile, Leaving Millions in the Dark", "nytimes.com",
                                          at(-15))]
        self.assertEqual(self.media_signals(self.collect(0)), {})
        self.assertEqual(sorted(self.cursor["stories"]["CL"]["domains"]), ["b.example", "nytimes.com"])

    def test_google_news_failing_alone_keeps_the_feeds_running(self):
        self.europe_goes_dark()
        logging.disable(logging.NOTSET)
        with mock.patch.object(news, "fetch", side_effect=HttpError("HTTP 429 von news.google.com")):
            with self.assertLogs("blackout_radar", "WARNING") as logs:
                signals = self.collect(0)
        self.assertIn("EU", self.media_signals(signals))
        self.assertEqual(self.cursor["degraded"],
                         "Google News ohne Antwort (Google News: HTTP 429 von news.google.com)")
        self.assertIn("Medien: Abfrage fehlgeschlagen (Google News, Gebiet AT-4): HTTP 429 von news.google.com",
                      "\n".join(logs.output))
        self.collect(5)
        self.assertEqual(self.cursor["degraded"], "")

    def test_feeds_failing_alone_is_visible_too(self):
        for feed in self.cfg["feeds"]:
            self.wires[feed["domain"]] = HttpError(f"{feed['domain']} nicht erreichbar (timed out)")
        self.feeds["Mühlviertel"] = [item("Stromausfall in Linz", "nachrichten.at", at(-20))]
        self.assertIn("AT-4", self.media_signals(self.collect(0)))
        self.assertTrue(self.cursor["degraded"].startswith("Feeds aus Übersee ohne Antwort (Feed "))

    def test_single_failed_feed_is_only_a_note(self):
        self.wires["aljazeera.com"] = HttpError("HTTP 503 von www.aljazeera.com")
        self.collect(0)
        self.assertEqual(self.cursor["note"], "Feed aljazeera.com: HTTP 503 von www.aljazeera.com")
        self.assertEqual(self.cursor["degraded"], "")


if __name__ == "__main__":
    unittest.main()
