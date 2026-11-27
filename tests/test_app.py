"""Gesamtablauf: ein Lauf von den Quellen bis zu Meldung, Lagebericht und gespeichertem Zustand."""
import contextlib
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blackout_radar import __main__ as app
from blackout_radar import collectors, config, http, notify, report
from blackout_radar.engine import Engine
from blackout_radar.http import HttpError
from blackout_radar.model import iso

from .helpers import at, make_cfg, media

ROOT = Path(__file__).resolve().parent.parent


class Harness(unittest.TestCase):
    """Ersetzt die Datenquellen und den Versand durch Attrappen."""

    def setUp(self):
        self.signals = []      # was die Quelle "news" im nächsten Lauf liefert
        self.broken = False    # True: die Quelle "news" schlägt fehl
        self.partial = ""      # Text: ein Teil der Quelle "news" fällt aus
        self.europe_up = True  # False: die Messquellen in Europa antworten nicht
        self.offline = False   # True: der Push-Dienst nimmt nichts an
        self.pushed = []       # zugestellte Meldungen
        sources = mock.patch.dict(collectors.COLLECTORS, {"news": self.fake_news}, clear=True)
        senders = mock.patch.dict(notify.SENDERS, {"ntfy": self.fake_push})
        sources.start()
        senders.start()
        self.addCleanup(sources.stop)
        self.addCleanup(senders.stop)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def fake_news(self, cfg, cursor, now, context):
        if self.broken:
            raise HttpError("HTTP 503 von news.google.com")
        http.JOURNAL.append(("news.google.com", True))
        cursor["data_time"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor["degraded"] = self.partial
        return list(self.signals)

    def european_source(self, *hosts):
        """Attrappe einer Messquelle in Europa: fragt ihre Hosts ab und scheitert, wenn Europa schweigt."""
        def collect(cfg, cursor, now, context):
            http.JOURNAL.extend((host, self.europe_up) for host in hosts)
            if not self.europe_up:
                raise HttpError(f"{hosts[0]} nicht erreichbar (timed out)")
            return []
        return collect

    def fake_push(self, cfg, message):
        if self.offline:
            raise notify.DeliveryError("ntfy: ntfy.sh nicht erreichbar (thema)")
        self.pushed.append(message)

    def titles(self):
        return [message.title for message in self.pushed]


class Upkeep(Harness):
    def setUp(self):
        super().setUp()
        self.cfg = make_cfg(NTFY_TOPIC="thema")
        for name in ("frequency", "load", "utility"):  # in diesen Tests gibt es nur die Quelle "news"
            self.cfg["sources"][name]["enabled"] = False
        self.state = {}

    def tick(self, minute):
        return app.tick(self.cfg, self.state, at(minute))

    def test_first_run_says_hello_once(self):
        self.tick(0)
        self.tick(5)
        self.assertEqual(self.titles(), ["Blackout-Radar ist aktiv: keine größeren Stromausfälle"])
        self.assertIn("für Oberösterreich, Österreich sofort", self.pushed[0].body)
        self.assertEqual(self.pushed[0].level, "info")

    def test_no_hello_before_a_channel_exists(self):
        state = {}
        app.tick(make_cfg(), state, at(0))
        self.assertNotIn("welcomed", state)
        app.tick(self.cfg, state, at(5))  # jetzt ist ntfy eingerichtet
        self.assertEqual(self.titles(), ["Blackout-Radar ist aktiv: keine größeren Stromausfälle"])

    def test_daily_summary_once_a_day_after_seven(self):
        self.cfg["health"]["gap_minutes"] = 10_000
        self.tick(0)                  # 26.11. 12:00 Uhr: erste Meldung
        self.tick(60 * 18 + 50)       # 27.11. 06:50 Uhr: noch zu früh
        self.assertEqual(len(self.pushed), 1)
        self.tick(60 * 19 + 5)        # 27.11. 07:05 Uhr
        self.tick(60 * 19 + 10)
        self.assertEqual(self.titles()[1:], ["Lagebericht 27.11.: keine größeren Stromausfälle"])
        daily = self.pushed[1]
        self.assertEqual(daily.level, "daily")
        self.assertIn("Letzte 24 Stunden: keine gemeldeten Stromausfälle.", daily.body)
        self.assertIn("Überwachung: 3 Läufe seit dem letzten Lagebericht", daily.body)
        self.assertIn("Datenquellen: alle 1 in Ordnung.", daily.body)

    def test_daily_summary_can_be_switched_off(self):
        self.cfg["health"]["gap_minutes"] = 10_000
        self.cfg["daily_summary"]["enabled"] = False
        self.tick(0)
        self.tick(60 * 20)
        self.assertEqual(len(self.pushed), 1)

    def test_gap_is_reported(self):
        self.tick(0)
        self.tick(200)
        self.assertEqual(self.titles()[1], "Überwachung war unterbrochen: 3 h 20 min ohne Lauf")
        self.assertIn("Zwischen 26.11. 12:00 und 26.11. 15:20 Uhr wurde nichts geprüft", self.pushed[1].body)

    def test_broken_source_is_reported_once_and_recovery_too(self):
        self.tick(0)
        self.broken = True
        for minute in range(30, 60 * 8, 30):
            self.tick(minute)
        self.assertEqual(self.titles()[1:], ["Datenquelle gestört: Medien (Google News, Feeds aus Übersee)"])
        self.assertIn("HTTP 503 von news.google.com", self.pushed[1].body)
        self.broken = False
        self.tick(60 * 8)
        self.assertEqual(self.titles()[2:], ["Datenquelle wieder in Ordnung: Medien (Google News, Feeds aus Übersee)"])

    def test_part_of_a_source_failing_is_reported_as_restricted(self):
        self.tick(0)
        self.partial = "Google News ohne Antwort (Google News: HTTP 429 von news.google.com)"
        self.signals = [media("CU", None, at(0), at(30))]  # was der Rest der Quelle liefert, zählt weiter
        for minute in range(30, 60 * 8, 30):
            self.assertEqual(self.tick(minute)["signals"], 1)
        self.assertEqual(self.titles()[1:], ["Datenquelle eingeschränkt: Medien (Google News, Feeds aus Übersee)"])
        self.assertIn("Seit 26.11. 12:30 Uhr fällt ein Teil dieser Quelle aus (Google News ohne Antwort",
                      self.pushed[1].body)
        text = report.Report(self.cfg, self.state, at(60 * 8)).markdown()
        self.assertIn("| Medien (Google News, Feeds aus Übersee) | eingeschränkt seit 12:30 |", text)
        self.partial = ""
        self.tick(60 * 8)
        self.assertEqual(self.titles()[2:], ["Datenquelle wieder in Ordnung: Medien (Google News, Feeds aus Übersee)"])

    def test_silent_europe_is_one_warning_instead_of_an_alert_per_source(self):
        fakes = {"frequency": self.european_source("api.energy-charts.info", "dat.netzfrequenzmessung.de"),
                 "utility": self.european_source("www.linznetz.at")}
        for name in fakes:
            self.cfg["sources"][name]["enabled"] = True
        with mock.patch.dict(collectors.COLLECTORS, fakes):
            self.tick(0)
            self.europe_up = False
            for minute in range(5, 60 * 5, 5):
                self.tick(minute)
            self.assertEqual(self.titles()[1:], ["Messquellen in Europa nicht erreichbar"])
            self.assertEqual(self.pushed[1].level, "warn")
            current = report.Report(self.cfg, self.state, at(60 * 5))
            self.assertIn("⚠️ **Seit 12:05 Uhr antwortet keine der Messquellen in Europa (Energy-Charts (Freiburg), "
                          "netzfrequenzmessung.de (Nürnberg), LINZ NETZ (Linz)), Quellen außerhalb Europas antworten.",
                          current.markdown())
            europe = current.snapshot()["europe"]
            self.assertEqual(europe["silent_since"], iso(at(5)))
            self.assertEqual([row["reached"] for row in europe["hosts"]], [False, False, False])
            self.europe_up = True
            self.tick(60 * 5)
            self.assertEqual(self.titles()[2:], ["Messquellen in Europa wieder erreichbar"])
            self.assertIsNone(report.Report(self.cfg, self.state, at(60 * 5)).snapshot()["europe"]["silent_since"])
            self.assertNotIn("⚠️", report.Report(self.cfg, self.state, at(60 * 5)).markdown())

    def test_single_broken_source_in_europe_is_still_reported(self):
        fakes = {"frequency": self.european_source("api.energy-charts.info", "dat.netzfrequenzmessung.de")}
        self.cfg["sources"]["frequency"]["enabled"] = True
        self.cfg["sources"]["utility"]["enabled"] = True

        def linz(cfg, cursor, now, context):
            http.JOURNAL.append(("www.linznetz.at", True))
            return []

        with mock.patch.dict(collectors.COLLECTORS, {**fakes, "utility": linz}):
            self.tick(0)
            self.europe_up = False
            for minute in range(5, 60 * 4, 5):
                self.tick(minute)
        self.assertEqual(self.titles()[1:], ["Datenquelle gestört: Netzfrequenz"])

    def test_last_messages_are_part_of_the_status_file(self):
        # Für die App: Sie holt nach, was als Push nicht ankam.
        self.tick(0)
        self.signals = [media("AT-4", 0.026, at(0), at(5), text="1 Medium berichtet, rund 40.000 Betroffene laut Schlagzeilen")]
        self.offline = True
        self.tick(5)
        notices = report.Report(self.cfg, self.state, at(5)).snapshot()["notices"]
        self.assertEqual([entry["title"] for entry in notices],
                         ["Stromausfall: Oberösterreich (laut Medien)", "Blackout-Radar ist aktiv: keine größeren Stromausfälle"])
        waiting, hello = notices
        self.assertEqual(sorted(waiting), ["body", "delivered", "key", "level", "pending", "t", "title"])
        self.assertEqual((waiting["level"], waiting["t"], waiting["delivered"], waiting["pending"]),
                         ("warn", iso(at(5)), [], ["ntfy"]))
        self.assertIn("Dauer und Ende lassen sich aus Medienberichten nicht ablesen.", waiting["body"])
        self.assertEqual((hello["level"], hello["t"], hello["delivered"], hello["pending"]),
                         ("info", iso(at(0)), ["ntfy"], []))
        self.assertTrue(hello["body"].startswith("Die Überwachung läuft."))
        self.assertNotIn("thema", json.dumps(notices))  # weder Fehlertexte noch Zugangsdaten
        self.offline = False
        self.tick(10)
        notices = report.Report(self.cfg, self.state, at(10)).snapshot()["notices"]
        self.assertEqual((notices[0]["key"], notices[0]["delivered"], notices[0]["pending"]),
                         (waiting["key"], ["ntfy"], []))
        self.assertEqual(notices[0]["body"], waiting["body"])

    def test_outage_in_upper_austria_ends_up_as_push_and_in_the_report(self):
        self.tick(0)
        self.signals = [media("AT-4", 0.026, at(0), at(5), text="1 Medium berichtet, rund 40.000 Betroffene laut Schlagzeilen")]
        result = self.tick(5)
        self.assertEqual(self.titles()[1], "Stromausfall: Oberösterreich (laut Medien)")
        self.assertEqual((result["signals"], result["delivered"]), (1, 1))
        text = report.Report(self.cfg, self.state, at(5)).markdown()
        self.assertIn("### 🔴 Stromausfall: Oberösterreich (laut Medien)", text)
        self.assertIn("- Oberösterreich: 1 Medium berichtet, rund 40.000 Betroffene laut Schlagzeilen", text)
        self.assertIn("| 24 Stunden | 1 | 0 | – |", text)
        self.assertIn("| 12:05 | Stromausfall: Oberösterreich (laut Medien) | ntfy |", text)
        snapshot = report.Report(self.cfg, self.state, at(5)).snapshot()
        self.assertEqual(snapshot["active"][0]["areas"][0]["area"], "AT-4")
        json.dumps(snapshot)


class CommandLine(Harness):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.state_path = self.folder / "state" / "state.json"
        env = mock.patch.dict(os.environ, {"NTFY_TOPIC": "thema"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = app.main(["--config", str(self.folder / "fehlt.toml"), *args])
        return code, out.getvalue()

    def test_run_writes_state_and_report(self):
        self.assertEqual(self.run_cli("run", "--state", str(self.state_path))[0], 0)
        self.assertEqual(self.run_cli("run", "--state", str(self.state_path))[0], 0)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["daily"]["runs"], 2)
        self.assertEqual(state["outbox"], [])
        status = (self.state_path.parent / "status.md").read_text(encoding="utf-8")
        self.assertIn("# Lagebericht Stromausfälle", status)
        self.assertIn("**Keine größeren Stromausfälle erkannt.**", status)
        self.assertIn("| Medien (Google News, Feeds aus Übersee) | in Ordnung |", status)
        snapshot = json.loads((self.state_path.parent / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["active"], [])
        self.assertEqual(self.titles(), ["Blackout-Radar ist aktiv: keine größeren Stromausfälle"])

    def test_dry_run_sends_and_stores_nothing(self):
        code, out = self.run_cli("run", "--dry-run", "--state", str(self.state_path))
        self.assertEqual(code, 0)
        self.assertIn("# Lagebericht Stromausfälle", out)
        self.assertIn("Blackout-Radar ist aktiv", out)
        self.assertEqual(self.pushed, [])
        self.assertFalse(self.state_path.exists())

    def test_unreadable_state_is_set_aside_and_reported(self):
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text("{kaputt", encoding="utf-8")
        self.assertEqual(self.run_cli("run", "--state", str(self.state_path))[0], 0)
        self.assertTrue((self.state_path.parent / "state.json.defekt").exists())
        self.assertIn("Blackout-Radar: Zustand neu begonnen", self.titles())
        json.loads(self.state_path.read_text(encoding="utf-8"))

    def test_crash_is_reported_once_a_day_and_state_stays_untouched(self):
        self.run_cli("run", "--state", str(self.state_path))
        before = self.state_path.read_text(encoding="utf-8")
        with mock.patch.object(Engine, "tick", side_effect=RuntimeError("kaputt bei thema")):
            self.assertEqual(self.run_cli("run", "--state", str(self.state_path))[0], 1)
            self.assertEqual(self.run_cli("run", "--state", str(self.state_path))[0], 1)
        self.assertEqual(self.titles()[1:], ["Blackout-Radar: Fehler im Programm"])
        self.assertIn("RuntimeError: kaputt bei ***", self.pushed[1].body)  # Zugangsdaten bleiben draußen
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_status_shows_the_saved_report(self):
        self.assertEqual(self.run_cli("status", "--state", str(self.state_path))[0], 1)
        self.run_cli("run", "--state", str(self.state_path))
        code, out = self.run_cli("status", "--state", str(self.state_path))
        self.assertEqual(code, 0)
        self.assertIn("## Datenquellen", out)

    def test_test_push(self):
        code, out = self.run_cli("test-push", "--level", "alarm")
        self.assertEqual((code, out.strip()), (0, "ntfy: ok"))
        self.assertEqual((self.pushed[0].title, self.pushed[0].level), ("Testmeldung vom Blackout-Radar", "alarm"))
        with mock.patch.dict(os.environ, {}, clear=True):
            code, out = self.run_cli("test-push")
        self.assertEqual(code, 1)
        self.assertIn("Kein Kanal eingerichtet", out)

    def test_simulation_prints_the_course_of_a_blackout(self):
        code, out = self.run_cli("simulate")
        self.assertEqual(code, 0)
        self.assertIn("Planspiel: Blackout in Österreich. Alle Signale sind erfunden.", out)
        self.assertIn("[alarm]  Netzfrequenz-Alarm: 49,31 Hz", out)
        self.assertIn("Entwarnung: Oberösterreich, Österreich, Tschechien (Dauer 10 h 40 min)", out)
        self.assertEqual(self.pushed, [])

    def test_simulation_can_send_test_messages(self):
        with mock.patch.object(app.time, "sleep"):
            code, _ = self.run_cli("simulate", "--send")
        self.assertEqual(code, 0)
        self.assertTrue(all(message.title.startswith("[TEST] ") for message in self.pushed))
        self.assertTrue(all(message.body.startswith("Planspiel, kein echter Ausfall.") for message in self.pushed))
        self.assertGreater(len(self.pushed), 8)


class StatusReport(unittest.TestCase):
    def test_media_only_events_have_no_duration(self):
        cfg = make_cfg()
        engine = Engine(cfg, {})
        for minute in range(0, 70, 5):
            engine.tick([media("CU", 0.5, at(-40), at(minute))], at(minute))
        engine.tick([media("CU", None, at(-40), at(70), active=False)], at(70))
        text = report.Report(cfg, engine.state, at(90)).markdown()
        self.assertIn("### ⚪ Blackout: Kuba (laut Medien)", text)
        self.assertIn("- Kuba: keine neuen Medienberichte seit 13:10", text)
        self.assertIn("| nicht belegt | Kuba | Blackout (laut Medien) | −50 % |", text)
        self.assertIn("| 24 Stunden | 1 | 0 | – |", text)

    def test_missing_load_values_are_not_shown_as_normal(self):
        cfg = make_cfg()
        state = {"cursors": {"load": {"latest": {
            "AT": {"t": iso(at(-300)), "mw": 9378.0, "ref_mw": 8831.0, "newest": iso(at(-285)), "silent": True},
            "DE": {"t": iso(at(-120)), "mw": 73768.0, "ref_mw": 73014.0, "newest": iso(at(-90)), "silent": False}}}}}
        text = report.Report(cfg, state, at(0)).markdown()
        self.assertIn("| Stromlast Österreich | keine neuen Werte seit 07:15 (zuletzt 9.378 MW) |", text)
        self.assertIn("| Stromlast Deutschland | 73.768 MW (Stand 10:00), +1 % gegenüber dem Vortag |", text)

    def test_watch_list_explains_why_nothing_was_sent(self):
        cfg = make_cfg()
        engine = Engine(cfg, {})
        engine.tick([media("AT", 0.004, at(-40), at(0), text="2 Medien berichten, rund 37.000 Betroffene")], at(0))
        text = report.Report(cfg, engine.state, at(0)).markdown()
        self.assertIn("## Unter Beobachtung", text)
        self.assertIn("| Österreich | 11:20 | 2 Medien berichten, rund 37.000 Betroffene | zu klein für eine Meldung |", text)


class Configuration(unittest.TestCase):
    def test_defaults_match_the_request(self):
        cfg = make_cfg()
        self.assertEqual(cfg["filter"]["min_duration_minutes"], 30)
        self.assertEqual(cfg["priority"]["areas"], ["AT-4", "AT"])
        self.assertEqual(cfg["priority"]["always_areas"], ["AT-4"])
        self.assertFalse(cfg["notify"]["ntfy"]["enabled"])
        self.assertFalse(cfg["notify"]["email"]["enabled"])
        self.assertFalse(cfg["sources"]["ioda"]["enabled"])

    def test_secrets_come_from_the_environment(self):
        cfg = make_cfg(NTFY_TOPIC=" thema ", SMTP_HOST="mail.example.org", SMTP_PORT="465", MAIL_TO="a@example.org",
                       CLOUDFLARE_API_TOKEN="cf", STATUS_URL="https://example.org/status")
        self.assertTrue(cfg["notify"]["ntfy"]["enabled"])
        self.assertEqual(cfg["notify"]["ntfy"]["topic"], "thema")
        self.assertEqual((cfg["notify"]["email"]["enabled"], cfg["notify"]["email"]["port"]), (True, 465))
        self.assertEqual(cfg["notify"]["email"]["sender"], "a@example.org")
        self.assertTrue(cfg["sources"]["cloudflare"]["enabled"])
        self.assertEqual(cfg["status_url"], "https://example.org/status")

    def test_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.toml"
            path.write_text('[filter]\nmin_duration_minutes = 45\nignore_areas = ["UA"]\n\n'
                            '[daily_summary]\nenabled = false\n', encoding="utf-8")
            cfg = config.load(path, env={})
        self.assertEqual(cfg["filter"]["min_duration_minutes"], 45)
        self.assertEqual(cfg["filter"]["ignore_areas"], ["UA"])
        self.assertEqual(cfg["filter"]["min_affected_people"], 500_000)  # nicht genannte Werte bleiben
        self.assertFalse(cfg["daily_summary"]["enabled"])

    def test_shipped_config_file_is_valid_and_keeps_the_defaults(self):
        self.assertTrue((ROOT / "config.toml").exists())
        self.assertEqual(config.load(ROOT / "config.toml", env={}), make_cfg())


if __name__ == "__main__":
    unittest.main()
