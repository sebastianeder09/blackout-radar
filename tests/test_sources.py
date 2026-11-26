"""Messquellen: Netzfrequenz, Stromlast, Störmeldungen LINZ NETZ."""
import math
import unittest
from datetime import timedelta
from unittest import mock

from blackout_radar.collectors import energy_charts, frequency, linznetz
from blackout_radar.http import HttpError
from blackout_radar.model import iso, parse_ts

from .helpers import at, make_cfg


def seconds(start, values):
    return [(start + timedelta(seconds=index), value) for index, value in enumerate(values)]


class FrequencyAnalysis(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["frequency"]
        self.cursor = {}

    def analyse(self, rows):
        return frequency.analyse(frequency._sample(frequency._smooth(rows), self.cfg), self.cfg, self.cursor)

    def test_normal_frequency_gives_no_signal(self):
        self.assertEqual(self.analyse(seconds(at(0), [50.0, 50.02, 49.97] * 100)), [])

    def test_single_bad_reading_is_ignored(self):
        self.assertEqual(self.analyse(seconds(at(0), [50.0] * 50 + [49.2] + [50.0] * 50)), [])

    def test_short_dip_is_reported_even_if_already_over(self):
        # 30 Sekunden bei 49,72 Hz, danach sieben ruhige Minuten: erst Alarm, im nächsten Lauf Entwarnung
        signals = self.analyse(seconds(at(0), [50.0] * 60 + [49.72] * 30 + [50.0] * 420))
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertTrue(signal.active)
        self.assertEqual(signal.started_at, at(1))
        self.assertEqual(signal.metrics["worst_hz"], 49.72)
        self.assertEqual(signal.severity, 0.28)
        self.assertIn("Netzfrequenz 49,720 Hz statt 50,000 Hz", signal.detail)
        self.assertIn("Aktivierung der Leistungsreserven", signal.detail)

        signals = self.analyse(seconds(at(8.5), [50.0] * 300))
        self.assertEqual(len(signals), 1)
        self.assertFalse(signals[0].active)
        self.assertEqual(signals[0].ended_at, at(0) + timedelta(seconds=89))
        self.assertNotIn("event", self.cursor)
        self.assertEqual(self.analyse(seconds(at(14), [50.0] * 300)), [])

    def test_lasting_deviation_stays_active_and_tracks_the_worst_value(self):
        first = self.analyse(seconds(at(0), [49.75] * 300))[0]
        second = self.analyse(seconds(at(5), [49.4] * 300))[0]
        third = self.analyse(seconds(at(10), [49.95] * 120))[0]  # erholt, aber noch keine fünf ruhigen Minuten
        self.assertTrue(first.active and second.active and third.active)
        self.assertEqual(second.metrics["worst_hz"], 49.4)
        self.assertEqual(third.metrics["worst_hz"], 49.4)
        self.assertEqual(third.started_at, at(0))

    def test_overfrequency_counts_too(self):
        signal = self.analyse(seconds(at(0), [50.31] * 60))[0]
        self.assertEqual(signal.metrics["worst_hz"], 50.31)
        self.assertIn("Überfrequenz", signal.detail)

    def test_day_range(self):
        frequency.remember(self.cursor, {"t": at(0), "min": 49.95, "max": 50.04})
        frequency.remember(self.cursor, {"t": at(90), "min": 49.91, "max": 50.02})
        self.assertEqual(frequency.day_range(self.cursor, at(100)), (49.91, 50.04))
        self.assertIsNone(frequency.day_range(self.cursor, at(60 * 30)))


class FrequencyProviders(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["frequency"]

    @staticmethod
    def document(now, count=120, age=80):
        rows = [{"timestamp": (now - timedelta(seconds=age + count - 1 - index)).astimezone().isoformat(),
                 "values": {"frequency": 50.0 + index * 0.0001}} for index in range(count)]
        return {"data": rows, "available_until": iso(now)}

    def test_energy_charts_rows(self):
        cursor = {}
        with mock.patch.object(frequency.http, "get_json", return_value=self.document(at(0))) as get_json:
            sample = frequency.from_energy_charts(self.cfg, cursor, at(0))
        self.assertTrue(get_json.call_args.args[0].endswith("/v2/frequency"))
        self.assertEqual(get_json.call_args.kwargs["params"]["region"], "DE-Freiburg")
        self.assertEqual(sample["n"], 120)
        self.assertEqual(sample["t"], at(0) - timedelta(seconds=80))
        self.assertEqual(cursor["ec_last"], iso(at(0) - timedelta(seconds=80)))
        # Der nächste Lauf wertet nur neue Sekunden aus und fragt ab dem letzten Stand
        with mock.patch.object(frequency.http, "get_json", return_value=self.document(at(1))) as get_json:
            sample = frequency.from_energy_charts(self.cfg, cursor, at(1))
        self.assertEqual(sample["n"], 60)
        self.assertEqual(get_json.call_args.kwargs["params"]["start"], "2026-11-26T10:58Z")

    def test_stale_or_empty_data_is_an_error(self):
        with mock.patch.object(frequency.http, "get_json", return_value=self.document(at(0), age=1200)):
            with self.assertRaises(HttpError):
                frequency.from_energy_charts(self.cfg, {}, at(0))
        with mock.patch.object(frequency.http, "get_json", return_value={"data": []}):
            with self.assertRaises(HttpError):
                frequency.from_energy_charts(self.cfg, {}, at(0))

    def test_netzfrequenzmessung_xml(self):
        xml = "<r><f>49.980</f><z>2026-11-26T10:59:30+00:00</z></r>"
        with mock.patch.object(frequency.http, "get_text", return_value=xml):
            sample = frequency.from_netzfrequenzmessung(self.cfg, {}, at(0))
        self.assertEqual((sample["f"], sample["n"]), (49.98, 1))
        with mock.patch.object(frequency.http, "get_text", return_value="<r><f>49.980</f><z>2026-11-26T08:00:00+00:00</z></r>"):
            with self.assertRaises(HttpError):
                frequency.from_netzfrequenzmessung(self.cfg, {}, at(0))

    def test_second_provider_takes_over(self):
        def broken(cfg, cursor, now):
            raise HttpError("HTTP 503 von api.energy-charts.info")

        def working(cfg, cursor, now):
            return frequency._sample([(now, 49.99)], cfg)

        cursor = {}
        with mock.patch.dict(frequency.PROVIDERS, {"energy_charts": broken, "netzfrequenzmessung": working}):
            self.assertEqual(frequency.collect(self.cfg, cursor, at(0), {}), [])
        self.assertEqual(cursor["last"]["provider"], "netzfrequenzmessung")
        self.assertIn("HTTP 503", cursor["note"])
        with mock.patch.dict(frequency.PROVIDERS, {"energy_charts": broken, "netzfrequenzmessung": broken}):
            with self.assertRaises(HttpError):
                frequency.collect(self.cfg, cursor, at(5), {})


def load_series(newest, points=220, dropped=0, drop=0.0, recovered=0):
    """Viertelstundenwerte mit Tagesgang bis `newest`. Am Ende wahlweise Einbruch und Erholung."""
    series = []
    for index in range(points):
        when = newest - timedelta(minutes=15 * (points - 1 - index))
        value = 7000 + 1500 * math.sin(2 * math.pi * (when.hour * 60 + when.minute) / 1440)
        from_end = points - 1 - index
        if recovered <= from_end < recovered + dropped:
            value *= 1 - drop
        series.append([iso(when), round(value, 1)])
    return series


class LoadAnalysis(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["load"]
        self.events = {}
        self.newest = at(-165)  # Lastdaten sind rund 2 h 45 min alt

    def test_normal_load_gives_no_signal(self):
        self.assertEqual(energy_charts.analyse("at", load_series(self.newest), self.events, self.cfg, at(0)), [])

    def test_newest_values_are_provisional(self):
        """Die neuesten Werte sind oft erst zum Teil gemeldet (gesehen bei Italien und Slowenien)."""
        for dropped in (1, 2, 3):
            series = load_series(self.newest, dropped=dropped, drop=0.8)
            self.assertEqual(energy_charts.analyse("at", series, self.events, self.cfg, at(0)), [], dropped)
        self.assertEqual(self.events, {})

    def test_single_low_value_in_between_is_not_enough(self):
        series = load_series(self.newest, dropped=1, drop=0.8, recovered=6)
        self.assertEqual(energy_charts.analyse("at", series, self.events, self.cfg, at(0)), [])

    def test_hourly_values_only_the_newest_is_provisional(self):
        hourly = load_series(self.newest, points=880, dropped=12, drop=0.5)[3::4]  # 3 Stundenwerte im Einbruch
        signal = energy_charts.analyse("sk", hourly, self.events, self.cfg, at(0))[0]
        self.assertEqual(signal.area, "SK")
        self.assertEqual(signal.started_at, self.newest - timedelta(minutes=120))
        self.assertEqual(signal.observed_at, self.newest - timedelta(minutes=60))

    def test_drop_and_recovery(self):
        series = load_series(self.newest, dropped=4, drop=0.5)
        signal = energy_charts.analyse("at", series, self.events, self.cfg, at(0))[0]
        self.assertTrue(signal.active and signal.confirmed_power)
        self.assertEqual((signal.area, signal.kind), ("AT", "load_drop"))
        self.assertAlmostEqual(signal.severity, 0.5, places=2)
        self.assertEqual(signal.started_at, self.newest - timedelta(minutes=45))
        self.assertEqual(signal.observed_at, self.newest - timedelta(minutes=30))  # der neueste Wert, der schon zählt
        self.assertRegex(signal.detail, r"^Stromlast −50 % \(\d\.\d{3} statt \d\.\d{3} MW\)$")

        later = self.newest + timedelta(minutes=30)
        series = load_series(later, dropped=4, drop=0.5, recovered=2)
        signal = energy_charts.analyse("at", series, self.events, self.cfg, at(30))[0]
        self.assertTrue(signal.active)  # die beiden normalen Werte sind noch vorläufig

        later = self.newest + timedelta(minutes=60)
        series = load_series(later, dropped=4, drop=0.5, recovered=4)
        signal = energy_charts.analyse("at", series, self.events, self.cfg, at(60))[0]
        self.assertFalse(signal.active)
        self.assertEqual(signal.ended_at, later - timedelta(minutes=45))
        self.assertEqual(self.events, {})

    def test_old_data_allows_no_statement(self):
        series = load_series(at(-600), dropped=4, drop=0.5)
        self.assertEqual(energy_charts.analyse("at", series, self.events, self.cfg, at(0)), [])


class LoadCollector(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["load"]

    def test_response_rows(self):
        doc = {"data": [
            {"timestamp": "2026-11-26T09:00:00+01:00", "values": {"load": 7000.5, "solar": 12.0}},
            {"timestamp": "2026-11-26T09:15:00+01:00", "values": {"load": None}},
            {"timestamp": "2026-11-26T09:30:00+01:00", "values": {"load": 0}},
        ], "available_until": "2026-11-26T09:15:00+01:00"}
        with mock.patch.object(energy_charts.http, "get_json", return_value=doc) as get_json:
            points = energy_charts.fetch_load("https://api.energy-charts.info", "at", at(0), 30)
        self.assertEqual(points, [["2026-11-26T08:00:00Z", 7000.5]])
        params = get_json.call_args.kwargs["params"]
        self.assertEqual((params["country"], params["start"], params["end"]),
                         ("at", "2026-11-25T05:00Z", "2026-11-26T11:00Z"))

    def test_collect_keeps_latest_values_and_spares_the_api(self):
        cursor = {}
        calls = []

        def fake(base, country, now, hours):
            calls.append(country)
            if country == "de":
                raise HttpError("HTTP 404 von api.energy-charts.info", status=404)
            return load_series(at(-165))

        with mock.patch.object(energy_charts, "fetch_load", side_effect=fake):
            self.assertEqual(energy_charts.collect(self.cfg, cursor, at(0), {}), [])
            self.assertEqual(calls, ["at", "de"])  # das wichtigste Land zuerst, höchstens zwei Abfragen je Lauf
            self.assertIn("de: HTTP 404", cursor["note"])
            energy_charts.collect(self.cfg, cursor, at(5), {})
        self.assertEqual(calls[2:], ["cz", "sk"])
        latest = cursor["latest"]["AT"]
        self.assertEqual(latest["t"], iso(at(-195)))  # der neueste Wert, der nicht mehr vorläufig ist
        self.assertEqual(latest["newest"], iso(at(-165)))
        self.assertFalse(latest["silent"])
        self.assertAlmostEqual(latest["mw"], latest["ref_mw"], places=1)  # gleicher Tagesgang wie am Vortag
        self.assertEqual(parse_ts(cursor["next_poll"]["de"]), at(360))  # unbekanntes Land: erst in 6 Stunden wieder
        self.assertEqual(parse_ts(cursor["next_poll"]["at"]), at(15))

    def test_values_that_stop_coming_are_marked(self):
        """Beim Stromausfall in Spanien am 28.04.2025 blieben die Lastwerte eineinhalb Tage lang aus."""
        cursor = {}
        frozen = load_series(at(-165))
        with mock.patch.object(energy_charts, "fetch_load", return_value=frozen):
            for minute in range(0, 135, 15):
                energy_charts.collect(self.cfg, cursor, at(minute), {})
                self.assertFalse(cursor["latest"]["AT"]["silent"], minute)
            energy_charts.collect(self.cfg, cursor, at(135), {})  # zwei Stunden über dem üblichen Alter
        self.assertTrue(cursor["latest"]["AT"]["silent"])
        self.assertEqual(cursor["latest"]["AT"]["newest"], iso(at(-165)))

        moving = load_series(at(-15))
        with mock.patch.object(energy_charts, "fetch_load", return_value=moving):
            energy_charts.collect(self.cfg, cursor, at(150), {})
        self.assertFalse(cursor["latest"]["AT"]["silent"])

    def test_no_claim_about_missing_values_while_the_service_is_down(self):
        cursor = {}
        with mock.patch.object(energy_charts, "fetch_load", return_value=load_series(at(-165))):
            energy_charts.collect(self.cfg, cursor, at(0), {})
        with mock.patch.object(energy_charts, "fetch_load", side_effect=HttpError("HTTP 503 von api.energy-charts.info")):
            for minute in range(15, 300, 15):
                energy_charts.collect(self.cfg, cursor, at(minute), {})
        self.assertFalse(cursor["latest"]["AT"]["silent"])
        self.assertIn("at: HTTP 503", cursor["note"])


PAGE = """<html><body><main id="netz-main-content"> <span class="solrindex">
<!-- disturbance --> <!-- ./disturbance -->
<div class="container"><h1>Aktuelle Störmeldungen</h1></div>
<!-- disturbance detail --> <div class="container"> </div> <!-- ./disturbance detail -->
<div class="netz-editor-output"><p><b>Bitte beachten Sie:</b></p><p>Wir sind bemüht, auftretende Störungen
so schnell als möglich zu beheben.</p></div></span></main></body></html>"""
OUTAGE = PAGE.replace('<div class="container"> </div>',
                      '<div class="container"><h2>St&ouml;rung im Bereich Urfahr</h2>'
                      '<p>Seit 14:05 Uhr sind rund 2.300 Kunden ohne Strom.</p><script>var x = 1;</script></div>')


class LinzNetz(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()["sources"]["utility"]
        self.cursor = {}

    def collect(self, page, minute):
        with mock.patch.object(linznetz.http, "get_text", return_value=page):
            return linznetz.collect(self.cfg, self.cursor, at(minute), {})

    def test_page_without_outage(self):
        self.assertEqual(linznetz.extract(PAGE), "")
        self.assertEqual(self.collect(PAGE, 0), [])
        self.assertEqual(self.cursor["data_time"], iso(at(0)))

    def test_outage_text_is_taken_over(self):
        self.assertEqual(linznetz.extract(OUTAGE),
                         "Störung im Bereich Urfahr Seit 14:05 Uhr sind rund 2.300 Kunden ohne Strom.")
        signal = self.collect(OUTAGE, 0)[0]
        self.assertTrue(signal.active and signal.confirmed_power)
        self.assertEqual((signal.area, signal.kind, signal.started_at), ("AT-4", "utility_outage", at(0)))
        self.assertEqual(signal.severity, 0.003)  # 2.300 Kunden, also rund 4.600 Menschen
        self.assertTrue(signal.detail.startswith("LINZ NETZ meldet eine Störung: Störung im Bereich Urfahr"))
        again = self.collect(OUTAGE, 5)[0]
        self.assertEqual(again.started_at, at(0))

    def test_all_clear_when_the_text_disappears(self):
        self.collect(OUTAGE, 0)
        signal = self.collect(PAGE, 20)[0]
        self.assertFalse(signal.active)
        self.assertEqual((signal.started_at, signal.ended_at), (at(0), at(20)))
        self.assertEqual(self.collect(PAGE, 25), [])

    def test_changed_page_layout_is_an_error_not_an_all_clear(self):
        self.collect(OUTAGE, 0)
        with self.assertRaises(HttpError):
            self.collect("<html><body>Neue Seite</body></html>", 5)
        self.assertIn("event", self.cursor)


if __name__ == "__main__":
    unittest.main()
