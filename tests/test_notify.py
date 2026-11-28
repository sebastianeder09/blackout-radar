"""Versand: Postausgang, Wiederholung, Kanäle, keine Zugangsdaten im gespeicherten Zustand."""
import json
import logging
import unittest
from datetime import timedelta
from unittest import mock

from blackout_radar import notify, sign
from blackout_radar.http import HttpError
from blackout_radar.model import Message

from .helpers import TEST_KEY, TEST_KEY_PUBLIC, at, make_cfg

SECRETS = {"NTFY_TOPIC": "geheimes-thema-123", "SMTP_HOST": "mail.example.org", "SMTP_USER": "radar@example.org",
           "SMTP_PASSWORD": "pw-123456", "MAIL_TO": "chef@example.org"}


class Delivery(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg(**SECRETS)
        self.state = {}
        self.calls = []
        self.failing = set()
        senders = {name: self.sender(name) for name in ("ntfy", "email")}
        patcher = mock.patch.dict(notify.SENDERS, senders)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sender(self, channel):
        def send(cfg, message):
            if channel in self.failing:
                raise notify.DeliveryError(f"{channel}: abgelehnt für chef@example.org bei geheimes-thema-123")
            self.calls.append((channel, message.title, message.body))
        return send

    def notifier(self):
        return notify.Notifier(self.cfg, self.state)

    def test_message_goes_to_all_channels_once(self):
        message = Message("Stromausfall: Oberösterreich", "Text", "warn", "e1:start:1")
        notifier = self.notifier()
        notifier.queue([message, message], at(0))
        self.assertEqual(notifier.flush(at(0)), 2)
        self.notifier().queue([message], at(5))  # derselbe Schlüssel im nächsten Lauf: kein zweiter Versand
        self.assertEqual(self.notifier().flush(at(5)), 0)
        self.assertEqual([call[0] for call in self.calls], ["ntfy", "email"])
        self.assertEqual(self.state["outbox"], [])
        self.assertEqual(self.state["sent"][0]["channels"], ["ntfy", "email"])
        self.assertEqual(self.state["sent"][0]["body"], "Text")  # für die Liste der letzten Meldungen im Lagebericht

    def test_daily_summary_is_not_mailed(self):
        notifier = self.notifier()
        notifier.queue([Message("Lagebericht 26.11.", "Text", "daily", "daily:2026-11-26")], at(0))
        notifier.flush(at(0))
        self.assertEqual([call[0] for call in self.calls], ["ntfy"])

    def test_failed_channel_is_retried_without_repeating_the_others(self):
        self.failing = {"email"}
        notifier = self.notifier()
        notifier.queue([Message("Titel", "Text", "warn", "k1")], at(0))
        self.assertEqual(notifier.flush(at(0)), 1)
        self.assertEqual(self.state["outbox"][0]["pending"], ["email"])
        stored = json.dumps(self.state, ensure_ascii=False)
        for secret in SECRETS.values():
            self.assertNotIn(secret, stored)  # der Zustand ist öffentlich lesbar
        self.assertIn("***", self.state["outbox"][0]["errors"]["email"])

        self.failing = set()
        self.assertEqual(self.notifier().flush(at(30)), 1)
        self.assertEqual([call[0] for call in self.calls], ["ntfy", "email"])
        self.assertTrue(self.calls[1][2].startswith("Verspätet zugestellt, erstellt am 26.11. 12:00 Uhr.\nText"))
        self.assertEqual(self.state["outbox"], [])

    def test_gives_up_after_twelve_hours(self):
        self.failing = {"email", "ntfy"}
        notifier = self.notifier()
        notifier.queue([Message("Titel", "Text", "warn", "k1")], at(0))
        notifier.flush(at(0))
        self.assertEqual(len(self.state["outbox"]), 1)
        self.notifier().flush(at(0) + timedelta(hours=13))
        self.assertEqual(self.state["outbox"], [])
        self.assertEqual((self.state["sent"][0]["channels"], sorted(self.state["sent"][0]["failed"])),
                         ([], ["email", "ntfy"]))

    def test_without_channels_nothing_breaks(self):
        state = {}
        notifier = notify.Notifier(make_cfg(), state)
        self.assertEqual(notifier.channels(), [])
        notifier.queue([Message("Titel", "Text", "warn", "k1")], at(0))
        self.assertEqual(notifier.flush(at(0)), 0)
        self.assertEqual(state["sent"][0]["channels"], [])

    def test_sent_log_is_limited(self):
        notifier = self.notifier()
        notifier.queue([Message(f"Titel {index}", "Text", "info", f"k{index}") for index in range(60)], at(0))
        notifier.flush(at(0))
        self.assertEqual(len(self.state["sent"]), notify.SENT_LOG)


class PublicAlarm(unittest.TestCase):
    """Öffentlicher Alarm: unterschrieben, nur was für alle gedacht ist, nie ein Test."""

    TOPIC = "blackout-radar-alarm"

    def setUp(self):
        keys = mock.patch.dict(sign.PUBLIC_KEYS, {"test": TEST_KEY_PUBLIC})
        keys.start()
        self.addCleanup(keys.stop)
        self.cfg = make_cfg(NTFY_TOPIC="geheimes-thema-123", ALARM_KEY=TEST_KEY)
        self.state = {}
        self.posts = []      # was an ntfy ging: (Thema, Nachricht)
        self.offline = False
        self.change = {}     # so verändert ntfy die Nachricht in seiner Antwort
        post = mock.patch.object(notify.http, "post_json", self.fake_post)
        post.start()
        self.addCleanup(post.stop)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def fake_post(self, url, payload, headers=None, timeout=20):
        if self.offline:
            raise HttpError("HTTP 429 von ntfy.sh", status=429)
        self.posts.append((payload["topic"], payload))
        echo = {"id": "x1", "time": 1, "event": "message", **payload, **self.change}
        return 200, {}, json.dumps(echo).encode("utf-8")

    def notifier(self):
        return notify.Notifier(self.cfg, self.state)

    def public(self):
        return [payload for topic, payload in self.posts if topic == self.TOPIC]

    def opened(self, payload):
        return sign.unseal({"test": TEST_KEY_PUBLIC}, self.TOPIC, payload["title"], payload["message"],
                           payload.get("click", ""))

    def test_channel_needs_the_key_the_app_knows(self):
        self.assertTrue(self.cfg["notify"]["public"]["enabled"])
        self.assertEqual(self.notifier().channels(), ["ntfy", "public"])
        for env, problem in (({}, ""),
                             ({"ALARM_KEY": "abc"}, "ALARM_KEY hat nicht die Form"),
                             ({"ALARM_KEY": sign.generate("test").export()}, "passt nicht zum Schlüssel „test“"),
                             ({"ALARM_KEY": sign.generate("k1").export()}, "passt nicht zum Schlüssel „k1“"),
                             ({"ALARM_KEY": sign.generate("neu").export()}, "passt nicht zum Schlüssel „neu“")):
            public = make_cfg(NTFY_TOPIC="thema", **env)["notify"]["public"]
            self.assertFalse(public["enabled"], env)
            self.assertIn(problem, public["problem"])
            if ":" in env.get("ALARM_KEY", ""):
                self.assertNotIn(env["ALARM_KEY"].split(":")[2], public["problem"])  # der Schlüssel steht nie im Text
        self.assertEqual(make_cfg()["notify"]["public"]["topic"], self.TOPIC)  # steht so auch fest in der App

    def test_message_goes_out_signed(self):
        message = Message("Blackout: Österreich", "Seit 12:00 Uhr\n• Österreich: Stromlast −52 %", "alarm",
                          "AT-20261126T1100:start:1", "https://example.org/status")
        notifier = self.notifier()
        notifier.queue([message], at(0))
        self.assertEqual(notifier.flush(at(0)), 2)
        self.assertEqual([topic for topic, _ in self.posts], ["geheimes-thema-123", self.TOPIC])
        private, public = self.posts[0][1], self.posts[1][1]
        self.assertEqual(private["message"], message.body)  # der eigene Kanal bleibt, wie er war
        self.assertEqual((public["title"], public["priority"], public["tags"], public["click"]),
                         ("Blackout: Österreich", 5, ["rotating_light"], "https://example.org/status"))
        self.assertEqual(self.opened(public), {"k": "test", "t": int(at(0).timestamp()), "l": "alarm",
                                               "i": "AT-20261126T1100:start:1", "body": message.body})
        self.assertEqual(self.state["sent"][0]["channels"], ["ntfy", "public"])

    def test_messages_about_operation_stay_with_the_operator(self):
        notifier = self.notifier()
        notifier.queue([Message("Datenquelle gestört: Netzfrequenz", "Text", "info", "source-down:x", scope="operator"),
                        Message("Lagebericht 26.11.", "Text", "daily", "daily:2026-11-26")], at(0))
        self.assertEqual(self.state["outbox"][0]["pending"], ["ntfy"])
        self.assertEqual(self.state["outbox"][0]["message"]["scope"], "operator")
        self.assertEqual(self.state["outbox"][1]["pending"], ["ntfy", "public"])
        self.assertNotIn("scope", self.state["outbox"][1]["message"])
        notifier.flush(at(0))
        self.assertEqual([payload["title"] for payload in self.public()], ["Lagebericht 26.11."])
        self.assertEqual([entry["scope"] for entry in self.state["sent"]], ["all", "operator"])

    def test_tests_never_reach_the_public(self):
        notifier = self.notifier()
        outcome = notifier.test(Message("Testmeldung", "Text", "alarm", "test:1"))
        self.assertEqual(outcome, {"ntfy": "ok"})
        self.assertEqual(self.public(), [])
        outcome = notifier.test(Message("Testmeldung", "Text", "info", "test:2"), ["public"])
        self.assertEqual(outcome, {"public": "ok"})
        self.assertEqual(self.opened(self.public()[0])["l"], "info")

    def test_late_delivery_keeps_the_time_of_creation(self):
        self.offline = True
        notifier = self.notifier()
        notifier.queue([Message("Blackout: Österreich", "Text", "alarm", "k1")], at(0))
        self.assertEqual(notifier.flush(at(0)), 0)
        self.assertEqual(self.state["outbox"][0]["pending"], ["ntfy", "public"])
        self.offline = False
        self.assertEqual(self.notifier().flush(at(45)), 2)
        opened = self.opened(self.public()[0])
        self.assertEqual(opened["t"], int(at(0).timestamp()))  # die App rechnet das Alter ab dem Entstehen
        self.assertTrue(opened["body"].startswith("Verspätet zugestellt, erstellt am 26.11. 12:00 Uhr.\nText"))

    def test_text_is_sent_in_the_form_ntfy_keeps(self):
        message = Message("  Titel\nmit Umbruch ", "\n Text mit Rand \r\nzweite Zeile\n\n", "warn", "k2", " https://example.org/x ")
        self.notifier().test(message, ["public"])
        payload = self.public()[0]
        self.assertEqual(payload["title"], "Titel mit Umbruch")
        self.assertEqual(payload["click"], "https://example.org/x")
        self.assertEqual(payload["message"], payload["message"].strip())
        self.assertEqual(self.opened(payload)["body"], "Text mit Rand \nzweite Zeile")

    def test_long_text_stays_a_message(self):
        message = Message("Ü" * 400, "Größe und Maß 😀 " * 1000, "info", "k3", "https://example.org/status")
        self.notifier().test(message, ["public"])
        payload = self.public()[0]
        self.assertLessEqual(len(payload["message"].encode("utf-8")), 4096)  # darüber macht ntfy einen Anhang daraus
        self.assertLessEqual(len(payload["title"].encode("utf-8")), 240)
        self.assertTrue(self.opened(payload)["body"].endswith(" …"))

    def test_link_with_spaces_is_left_out(self):
        self.notifier().test(Message("Titel", "Text", "info", "k4", "https://example.org/a b"), ["public"])
        self.assertNotIn("click", self.public()[0])
        self.assertIsNotNone(self.opened(self.public()[0]))

    def test_message_changed_by_the_service_is_given_up_at_once(self):
        # Kommt die Meldung verändert an, gilt die Unterschrift nicht. Ein neuer Versuch käme ebenso an.
        self.change = {"message": "You received a file: attachment.txt"}
        notifier = self.notifier()
        notifier.queue([Message("Blackout: Österreich", "Text", "alarm", "k1")], at(0))
        self.assertEqual(notifier.flush(at(0)), 1)
        self.assertEqual(self.state["outbox"], [])
        entry = self.state["sent"][0]
        self.assertEqual((entry["channels"], entry["failed"]), (["ntfy"], ["public"]))  # die App holt sie nach
        self.assertEqual(len(self.public()), 1)
        self.notifier().flush(at(5))
        self.assertEqual(len(self.public()), 1)

    def test_unreadable_answer_is_no_verdict(self):
        payload = {"title": "Titel", "message": "Text"}
        for answer in (b"", b"kein json", b"[]", b'{"ok": true}', None):
            notify.check_echo(answer, payload)
        notify.check_echo(json.dumps({"id": "a", **payload}).encode(), payload)
        for change in ({"title": "Titel "}, {"message": "Text."}, {"click": "https://example.org"}):
            with self.assertRaises(notify.Damaged):
                notify.check_echo(json.dumps({"id": "a", **payload, **change}).encode(), payload)

    def test_levels_can_be_left_out(self):
        self.cfg["notify"]["public"]["skip_levels"] = ["daily"]
        notifier = self.notifier()
        notifier.queue([Message("Lagebericht 26.11.", "Text", "daily", "daily:2026-11-26")], at(0))
        notifier.flush(at(0))
        self.assertEqual(self.public(), [])

    def test_key_stays_out_of_stored_errors(self):
        hidden = notify.secrets(self.cfg["notify"])
        self.assertIn(TEST_KEY, hidden)
        self.assertIn(TEST_KEY.split(":")[2], hidden)
        self.assertNotIn(self.TOPIC, hidden)  # das öffentliche Thema ist kein Geheimnis
        self.offline = True
        notifier = self.notifier()
        notifier.queue([Message("Titel", "Text", "warn", "k1")], at(0))
        notifier.flush(at(0))
        self.assertNotIn(TEST_KEY.split(":")[2], json.dumps(self.state))
        self.assertIn("öffentlicher Alarm: HTTP 429", self.state["outbox"][0]["errors"]["public"])


class Formats(unittest.TestCase):
    def test_clip_respects_bytes_and_characters(self):
        text = notify.clip("ä" * 3000, 240)
        self.assertLessEqual(len(text.encode("utf-8")), 240)
        self.assertTrue(text.endswith(" …"))
        self.assertEqual(notify.clip("kurz", 240), "kurz")

    def test_ntfy_request(self):
        cfg = make_cfg(NTFY_TOPIC="thema", NTFY_TOKEN="tk_abc")["notify"]["ntfy"]
        message = Message("Blackout: Österreich", "Zeile 1\nZeile 2", "alarm", "k", "https://example.org/status")
        with mock.patch.object(notify.http, "post_json") as post:
            notify.send_ntfy(cfg, message)
        url, payload = post.call_args.args
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual(payload, {"topic": "thema", "title": "Blackout: Österreich", "message": "Zeile 1\nZeile 2",
                                   "priority": 5, "tags": ["rotating_light"], "click": "https://example.org/status"})
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer tk_abc"})

    def test_ntfy_priorities(self):
        self.assertEqual(notify.NTFY_PRIORITY, {"alarm": 5, "warn": 4, "info": 3, "ok": 3, "daily": 2})

    def test_email(self):
        cfg = make_cfg(**SECRETS)["notify"]["email"]
        message = Message("Blackout: Österreich", "Zeile 1", "alarm", "k", "https://example.org/status")
        mail, recipients = notify.build_email(cfg, message)
        self.assertEqual(recipients, ["chef@example.org"])
        self.assertEqual(mail["Subject"], "[Blackout-Radar] Blackout: Österreich")
        self.assertEqual(mail["From"], "radar@example.org")
        self.assertEqual(mail["X-Priority"], "1")
        self.assertIn("Lagebericht: https://example.org/status", mail.get_content())

    def test_scope_survives_the_outbox(self):
        message = Message("Titel", "Text", "info", "k", "https://example.org", scope="operator")
        self.assertEqual(Message.from_dict(message.to_dict()), message)
        self.assertEqual(Message.from_dict({"title": "Titel", "body": "Text"}).scope, "all")  # Postausgang von früher

    def test_secret_values(self):
        hidden = notify.secrets(make_cfg(**SECRETS)["notify"])
        self.assertEqual(set(hidden), set(SECRETS.values()))
        self.assertEqual(notify.scrub("Fehler bei pw-123456 und chef@example.org", hidden), "Fehler bei *** und ***")
        own = make_cfg(NTFY_TOPIC="thema", NTFY_SERVER="https://push.example.net")["notify"]
        self.assertIn("push.example.net", notify.secrets(own))


if __name__ == "__main__":
    unittest.main()
