"""Erreichbarkeit der Messquellen in Europa: Verstummen alle zugleich, ist das ein eigenes Warnsignal."""
import gzip
import io
import unittest
import urllib.error
from unittest import mock

from blackout_radar import http, reach
from blackout_radar.http import HttpError
from blackout_radar.model import iso

from .helpers import at, make_cfg

ENERGY, NFM, LINZ = "api.energy-charts.info", "dat.netzfrequenzmessung.de", "www.linznetz.at"
GOOGLE = "news.google.com"


class Silence(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.state = {}

    def update(self, minute, **reached):
        """reached: Host -> hat geantwortet. Kurzformen: energy, nfm, linz, google."""
        names = {"energy": ENERGY, "nfm": NFM, "linz": LINZ, "google": GOOGLE}
        journal = [(names[name], value) for name, value in reached.items()]
        return reach.update(self.cfg, self.state, at(minute), journal)

    def test_normal_operation_is_quiet(self):
        for minute in range(0, 60, 5):
            self.assertEqual(self.update(minute, energy=True, linz=True, google=True), [])
        self.assertIsNone(reach.silent_since(self.state))

    def test_all_european_sources_silent_for_ten_minutes_is_a_warning(self):
        self.update(0, energy=True, linz=True, google=True)
        self.assertEqual(self.update(5, energy=False, nfm=False, linz=False, google=True), [])
        self.assertEqual(self.update(10, energy=False, nfm=False, linz=False, google=True), [])
        messages = self.update(15, energy=False, nfm=False, linz=False, google=True)
        self.assertEqual([(m.title, m.level) for m in messages], [("Messquellen in Europa nicht erreichbar", "warn")])
        self.assertIn("Seit 12:05 Uhr antwortet keine der Messquellen in Europa mehr: Energy-Charts (Freiburg), "
                      "netzfrequenzmessung.de (Nürnberg), LINZ NETZ (Linz).", messages[0].body)
        self.assertIn("Ein Stromausfall ist damit nicht belegt.", messages[0].body)
        self.assertEqual(messages[0].key, f"europe-silent:{iso(at(5))}")
        self.assertEqual(reach.silent_since(self.state), at(5))
        self.assertEqual(self.update(20, energy=False, nfm=False, linz=False, google=True), [])  # nur einmal

    def test_no_warning_if_nothing_outside_europe_answers_either(self):
        # Dann liegt es am Rechner des Radars selbst, nicht an Europa.
        for minute in range(0, 60, 5):
            self.assertEqual(self.update(minute, energy=False, nfm=False, linz=False, google=False), [])

    def test_no_warning_while_one_european_source_answers(self):
        for minute in range(0, 60, 5):
            self.assertEqual(self.update(minute, energy=False, nfm=False, linz=True, google=True), [])

    def test_a_single_silent_source_is_not_europe(self):
        for minute in range(0, 60, 5):
            self.assertEqual(self.update(minute, linz=False, google=True), [])

    def test_a_host_that_was_not_asked_lately_does_not_count(self):
        self.update(0, nfm=True, google=True)  # die Ersatzquelle wird nur gefragt, wenn die erste ausfällt
        for minute in (60, 65):
            self.assertEqual(self.update(minute, energy=False, linz=False, google=True), [])
        self.assertEqual(len(self.update(70, energy=False, linz=False, google=True)), 1)

    def test_sources_answering_again(self):
        for minute in (0, 5, 10):
            self.update(minute, energy=False, nfm=False, linz=False, google=True)
        self.assertEqual(self.update(60, energy=False, nfm=False, linz=False, google=False), [])  # Lauf ohne Netz
        messages = self.update(100, energy=True, linz=False, google=True)
        self.assertEqual([(m.title, m.level) for m in messages], [("Messquellen in Europa wieder erreichbar", "info")])
        self.assertIn("Seit 13:40 Uhr antwortet wieder: Energy-Charts (Freiburg). "
                      "Die Unterbrechung dauerte 1 h 40 min (seit 12:00 Uhr).", messages[0].body)
        self.assertIsNone(reach.silent_since(self.state))
        self.assertEqual(self.update(105, energy=True, linz=True, google=True), [])

    def test_rows_for_the_status_report(self):
        self.update(0, energy=True, linz=False, google=True)
        rows = {row["host"]: row for row in reach.hosts(self.cfg, self.state, at(5))}
        self.assertEqual((rows[ENERGY]["reached"], rows[LINZ]["reached"], rows[NFM]["reached"]), (True, False, None))
        self.assertEqual(rows[LINZ]["fail_since"], iso(at(0)))
        self.assertEqual(rows[LINZ]["label"], "LINZ NETZ (Linz)")
        self.assertIsNone(reach.hosts(self.cfg, self.state, at(60))[0]["reached"])  # zu lange her


class Journal(unittest.TestCase):
    """Der HTTP-Helfer vermerkt je Anfrage, ob der Server geantwortet hat."""

    def setUp(self):
        http.drain()
        self.addCleanup(http.drain)

    @staticmethod
    def response(body: bytes, packed: bool = False):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.status = 200
        resp.headers = {"Content-Encoding": "gzip"} if packed else {}
        stream = io.BytesIO(gzip.compress(body) if packed else body)
        resp.read.side_effect = stream.read
        return resp

    def test_answer_counts_as_reached_even_if_it_is_an_error(self):
        error = urllib.error.HTTPError("https://news.google.com/rss", 429, "Too Many Requests", {}, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=[self.response(b"ok"), error]):
            http.request("https://www.linznetz.at/portal")
            with self.assertRaises(HttpError):
                http.request("https://news.google.com/rss")
        self.assertEqual(http.drain(), [("www.linznetz.at", True), ("news.google.com", True)])
        self.assertEqual(http.drain(), [])

    def test_no_connection_or_no_answer_counts_as_not_reached(self):
        failures = [urllib.error.URLError("Name or service not known"), TimeoutError("The read operation timed out")]
        with mock.patch("urllib.request.urlopen", side_effect=failures):
            for url in ("https://dat.netzfrequenzmessung.de:9080/frequenz.xml", "https://api.energy-charts.info/x"):
                with self.assertRaises(HttpError):
                    http.request(url)
        self.assertEqual(http.drain(), [("dat.netzfrequenzmessung.de", False), ("api.energy-charts.info", False)])

    def test_size_limit(self):
        for packed in (False, True):
            with self.subTest(packed=packed):
                with mock.patch("urllib.request.urlopen", return_value=self.response(b"x" * 500, packed)):
                    self.assertEqual(http.request("https://example.org/feed", limit=500)[2], b"x" * 500)
                with mock.patch("urllib.request.urlopen", return_value=self.response(b"x" * 5000, packed)):
                    with self.assertRaisesRegex(HttpError, "größer als 1 kB"):
                        http.request("https://example.org/feed", limit=1000)


if __name__ == "__main__":
    unittest.main()
