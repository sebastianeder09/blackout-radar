"""Versand: Postausgang, Wiederholung, Kanäle, keine Zugangsdaten im gespeicherten Zustand."""
import json
import unittest
from datetime import timedelta
from unittest import mock

from blackout_radar import notify
from blackout_radar.model import Message

from .helpers import at, make_cfg

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

    def test_secret_values(self):
        hidden = notify.secrets(make_cfg(**SECRETS)["notify"])
        self.assertEqual(set(hidden), set(SECRETS.values()))
        self.assertEqual(notify.scrub("Fehler bei pw-123456 und chef@example.org", hidden), "Fehler bei *** und ***")
        own = make_cfg(NTFY_TOPIC="thema", NTFY_SERVER="https://push.example.net")["notify"]
        self.assertIn("push.example.net", notify.secrets(own))


if __name__ == "__main__":
    unittest.main()
