"""Unterschrift für den öffentlichen Alarm: Rechnung, Form der Meldung, Schutz gegen Fälschungen."""
import hashlib
import json
import os
import unittest
from pathlib import Path

from blackout_radar import sign

from .helpers import T0, TEST_KEY, TEST_KEY_PUBLIC

VECTORS = Path(__file__).resolve().parent / "data" / "unterschrift.json"
TOPIC = "blackout-radar-alarm"
KEYS = {"test": TEST_KEY_PUBLIC}


def other_key() -> sign.Key:
    """Ein zweiter, fremder Schlüssel unter demselben Namen."""
    return sign.Key("test", int.from_bytes(hashlib.sha256(b"fremder Schluessel").digest(), "big") % sign.N)


class Curve(unittest.TestCase):
    """Beispielwerte aus RFC 6979, Anhang A.2.5 (P-256 mit SHA-256)."""

    D = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721

    def test_public_key(self):
        key = sign.parse_key(TEST_KEY)
        self.assertEqual(key.d, self.D)
        self.assertEqual(key.public_hex, TEST_KEY_PUBLIC)
        self.assertEqual(key.public, (0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
                                      0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299))

    def test_signatures_match_the_standard(self):
        expected = {
            b"sample": (0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60,
                        0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716,
                        0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8),
            b"test": (0xD16B6AE827F17175E040871A1C7EC3500192C4C92677336EC2537ACAEE0008E0,
                      0xF1ABB023518351CD71D881567B1EA663ED3EFCF6C5132B354F28D3B0B7D38367,
                      0x019F4113742A2B14BD25926B49C649155F267E60D3814B4C0CC84250E46F0083),
        }
        for data, (k, r, s) in expected.items():
            self.assertEqual(next(sign._nonces(self.D, hashlib.sha256(data).digest())), k)
            self.assertEqual(sign.sign_numbers(self.D, data), (r, s))

    def test_verify(self):
        point = sign.parse_point(TEST_KEY_PUBLIC)
        signature = sign.sign(self.D, b"Blackout")
        self.assertTrue(sign.verify(point, b"Blackout", signature))
        self.assertFalse(sign.verify(point, b"Blackouts", signature))
        self.assertFalse(sign.verify(other_key().public, b"Blackout", signature))
        for position in range(len(signature)):
            damaged = bytearray(signature)
            damaged[position] ^= 0x01
            self.assertFalse(sign.verify(point, b"Blackout", bytes(damaged)), position)
        self.assertFalse(sign.verify(point, b"Blackout", b""))
        self.assertFalse(sign.verify(point, b"Blackout", signature + b"\x00"))
        self.assertFalse(sign.verify(point, b"Blackout", sign.der(0, 1)))
        self.assertFalse(sign.verify(point, b"Blackout", sign.der(1, sign.N)))
        self.assertFalse(sign.verify((1, 1), b"Blackout", signature))  # Punkt liegt nicht auf der Kurve

    def test_der(self):
        self.assertEqual(sign.der(1, 0x80).hex(), "300702010102020080")
        self.assertEqual(sign.parse_der(bytes.fromhex("300702010102020080")), (1, 0x80))
        self.assertIsNone(sign.parse_der(bytes.fromhex("30080201010203000080")))  # überflüssiges Nullbyte
        self.assertIsNone(sign.parse_der(bytes.fromhex("3006020101020180")))      # negative Zahl
        big = sign.N - 1
        self.assertEqual(sign.parse_der(sign.der(big, big)), (big, big))
        self.assertEqual(len(sign.der(big, big)), 72)

    def test_signature_has_one_form(self):
        # Zu (r, s) gilt auch (r, n - s). Der Radar liefert immer das kleinere s.
        point = sign.parse_point(TEST_KEY_PUBLIC)
        for data in (b"sample", b"test", b"Blackout"):
            r, s = sign.parse_der(sign.sign(self.D, data))
            self.assertLessEqual(s, sign.N // 2)
            self.assertEqual((r, min(s, sign.N - s)), (r, s))
            self.assertIn(s, (sign.sign_numbers(self.D, data)[1], sign.N - sign.sign_numbers(self.D, data)[1]))
            self.assertTrue(sign.verify(point, data, sign.der(r, sign.N - s)))  # die andere Form gilt ebenfalls

    def test_matches_another_implementation(self):
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:
            self.skipTest("Paket cryptography ist nicht installiert")
        private = ec.derive_private_key(self.D, ec.SECP256R1())
        point = sign.parse_point(TEST_KEY_PUBLIC)
        for size in range(0, 200, 7):
            data = hashlib.sha256(bytes([size])).digest() * 8
            data = data[:size]
            private.public_key().verify(sign.sign(self.D, data), data, ec.ECDSA(hashes.SHA256()))
            self.assertTrue(sign.verify(point, data, private.sign(data, ec.ECDSA(hashes.SHA256()))))


class Keys(unittest.TestCase):
    def test_key_format(self):
        key = sign.parse_key("  " + TEST_KEY + "\n")
        self.assertEqual((key.kid, key.export()), ("test", TEST_KEY))
        fresh = sign.generate("k7")
        self.assertEqual(sign.parse_key(fresh.export()), fresh)
        self.assertTrue(sign.on_curve(fresh.public))

    def test_bad_keys_are_refused_without_naming_them(self):
        secret = "c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721"
        for text in ("", "BRKEY1:test:" + secret[:-1], "BRKEY2:test:" + secret, "BRKEY1:Zu Lang!:" + secret,
                     "BRKEY1:test:" + "0" * 64, "BRKEY1:test:" + f"{sign.N:064x}", secret):
            with self.assertRaises(sign.BadKey) as caught:
                sign.parse_key(text)
            self.assertNotIn(secret[:20], str(caught.exception))

    def test_keys_of_the_app_are_points_on_the_curve(self):
        self.assertIn("k1", sign.PUBLIC_KEYS)
        for name, text in sign.PUBLIC_KEYS.items():
            self.assertRegex(name, r"^[a-z0-9]{1,8}$")
            self.assertTrue(sign.on_curve(sign.parse_point(text)))
        self.assertNotIn("test", sign.PUBLIC_KEYS)  # den Testschlüssel kennt jeder, die echte App nimmt ihn nie an
        self.assertNotIn(TEST_KEY_PUBLIC, sign.PUBLIC_KEYS.values())

    def test_public_key_must_be_on_the_curve(self):
        with self.assertRaises(ValueError):
            sign.parse_point("04" + "00" * 64)
        with self.assertRaises(ValueError):
            sign.parse_point(TEST_KEY_PUBLIC[:-2])


class Text(unittest.TestCase):
    def test_title_is_one_line_without_edges(self):
        self.assertEqual(sign.clean_title("  Blackout:\r\nÖsterreich   jetzt\n"), "Blackout: Österreich   jetzt")
        self.assertEqual(sign.clean_title("Titel =?utf-8?q?x?="), "Titel = ?utf-8?q?x?=")
        self.assertEqual(sign.clean_title("a\x00b\x07c"), "abc")

    def test_body_keeps_its_lines(self):
        self.assertEqual(sign.clean_body("\n  Zeile 1\r\nZeile 2\rZeile 3 \n\n"), "Zeile 1\nZeile 2\nZeile 3")
        self.assertEqual(sign.clean_body("a\x00b\tc\x1fd"), "ab\tcd")
        self.assertEqual(sign.clean_body("kaputt \ud83d ende"), "kaputt ? ende")  # halbes Zeichenpaar

    def test_cleaning_is_stable(self):
        for text in ("  Titel \n mit Umbruch", "Zeile 1\r\n\r\nZeile 2  ", "🚨 Blackout: Österreich"):
            self.assertEqual(sign.clean_title(sign.clean_title(text)), sign.clean_title(text))
            self.assertEqual(sign.clean_body(sign.clean_body(text)), sign.clean_body(text))


def sealed(title="Blackout: Österreich", body="Seit 12:00 Uhr, Dauer bisher 10 min\n• Österreich: Stromlast −52 %",
           click="https://example.org/status", level="alarm", ident="AT-20261126T1100:start:1",
           created=int(T0.timestamp()), topic=TOPIC, key=None) -> str:
    key = key or sign.parse_key(TEST_KEY)
    return sign.attach(body, sign.seal(key, topic, title, body, click, level, ident, created))


class Sealing(unittest.TestCase):
    TITLE = "Blackout: Österreich"
    BODY = "Seit 12:00 Uhr, Dauer bisher 10 min\n• Österreich: Stromlast −52 %"
    CLICK = "https://example.org/status"

    def check(self, message, title=TITLE, click=CLICK, topic=TOPIC, keys=KEYS):
        return sign.unseal(keys, topic, title, message, click)

    def test_round_trip(self):
        message = sealed()
        result = self.check(message)
        self.assertEqual(result, {"k": "test", "t": int(T0.timestamp()), "l": "alarm",
                                  "i": "AT-20261126T1100:start:1", "body": self.BODY})
        self.assertEqual(message.split("\n")[-2], "")  # Leerzeile vor der Unterschrift
        self.assertRegex(message.split("\n")[-1], r"^br1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
        self.assertLess(len(message.split("\n")[-1]), 260)

    def test_same_message_gives_the_same_signature(self):
        self.assertEqual(sealed(), sealed())
        self.assertNotEqual(sealed(), sealed(created=int(T0.timestamp()) + 1))

    def test_empty_body_and_no_link(self):
        message = sealed(body="", click="")
        self.assertNotIn("\n", message)
        self.assertEqual(self.check(message, click="")["body"], "")

    def test_any_change_breaks_the_signature(self):
        message = sealed()
        self.assertIsNone(self.check(message, title="Entwarnung: Österreich"))
        self.assertIsNone(self.check(message.replace("52 %", "5 %")))
        self.assertIsNone(self.check(message, click="https://example.org/falle"))
        self.assertIsNone(self.check(message, topic="anderes-thema"))
        self.assertIsNone(self.check("Vorspann\n" + message))
        self.assertIsNone(self.check(message + "\nNachsatz"))
        self.assertIsNone(self.check(self.BODY))  # ohne Unterschrift
        self.assertIsNone(self.check(message, keys={"k1": TEST_KEY_PUBLIC}))  # Name des Schlüssels unbekannt
        self.assertIsNone(self.check(sealed(key=other_key())))  # fremder Schlüssel unter bekanntem Namen

    def test_urgency_and_time_are_signed(self):
        message = sealed(level="info")
        body, line = sign.split(message)
        _, meta, signature = line.split(".")
        fields = json.loads(sign.unb64(meta))
        for change in ({"l": "alarm"}, {"t": fields["t"] + 3600}, {"i": "anderer-schluessel"}):
            forged = sign.b64(json.dumps({**fields, **change}, separators=(",", ":")).encode())
            self.assertIsNone(self.check(sign.attach(body, f"br1.{forged}.{signature}")), change)

    def test_fields_cannot_be_shifted(self):
        # Ohne Gegenwehr ließe sich der Link in den Titel und die erste Textzeile in den Link schieben:
        # Die unterschriebenen Daten wären dieselben.
        message = sealed()
        body, line = sign.split(message)
        first, rest = body.split("\n", 1)
        shifted = sign.attach(rest, line)
        self.assertIsNone(self.check(shifted, title=self.TITLE + "\n" + self.CLICK, click=first))
        self.assertIsNone(self.check(message, title=self.TITLE + "\r"))

    def test_garbage_is_refused(self):
        body, line = sign.split(sealed())
        _, meta, signature = line.split(".")
        for bad in ("br1.x.y", "br1." + "A" * 40 + "." + signature, f"br1.{meta}." + "A" * 90,
                    f"br2.{meta}.{signature}", f"br1.{meta}.{signature}.x", f"br1.{meta}", line.replace(".", " ")):
            self.assertIsNone(self.check(sign.attach(body, bad)), bad)
        for fields in ({"k": "test", "t": "1795777200", "l": "alarm", "i": "x"}, {"k": "test", "t": True, "l": "a", "i": "x"},
                       {"k": "test", "t": 1, "l": 5, "i": "x"}, {"k": "test", "t": 1, "l": "alarm"}, ["test"]):
            forged = sign.b64(json.dumps(fields).encode())
            self.assertIsNone(self.check(sign.attach(body, f"br1.{forged}.{signature}")), fields)

    def test_line_inside_the_text_does_not_count(self):
        inner = sign.split(sealed(level="alarm"))[1]
        message = sealed(body="Zitat einer alten Meldung:\n" + inner + "\nEnde", level="info")
        self.assertEqual(self.check(message)["l"], "info")


class Vectors(unittest.TestCase):
    """Beispiele als Datei: Die App prüft mit denselben Fällen, dass sie gleich urteilt (Kotlin-Test)."""

    def cases(self) -> list[dict]:
        body = "Seit 12:00 Uhr, Dauer bisher 10 min\n• Österreich: Stromlast −52 % 🚨\n» „Ganz Österreich ohne Strom“ (orf.at)"
        title, click = "Blackout: Österreich", "https://example.org/status"
        good = sealed(title, body, click)
        text, line = sign.split(good)
        _, meta, signature = line.split(".")
        fields = json.loads(sign.unb64(meta))
        r, s = sign.parse_der(sign.unb64(signature))
        louder = sign.b64(json.dumps({**fields, "l": "alarm"}, ensure_ascii=False, separators=(",", ":")).encode())
        quiet = sealed(title, body, click, level="info")
        first, rest = body.split("\n", 1)

        def case(name, message, valid, title=title, click=click, topic=TOPIC):
            return {"name": name, "topic": topic, "title": title, "click": click, "message": message, "valid": valid}

        return [
            case("gültig", good, True),
            case("gültig, ohne Link", sealed(title, body, ""), True, click=""),
            case("gültig, ohne Text", sealed(title, "", click), True),
            case("gültig, verspätet zugestellt",
                 sealed(title, "Verspätet zugestellt, erstellt am 26.11. 12:00 Uhr.\n" + body, click), True),
            case("gültig, tägliche Übersicht", sealed("Lagebericht 26.11.: keine größeren Stromausfälle",
                                                      "Datenquellen: alle 4 in Ordnung.", click, "daily",
                                                      "daily:2026-11-26"),
                 True, title="Lagebericht 26.11.: keine größeren Stromausfälle"),
            case("gültig, zweite Form derselben Unterschrift",
                 sign.attach(text, f"br1.{meta}.{sign.b64(sign.der(r, sign.N - s))}"), True),
            case("gültig, Zeile im Text zählt nicht", sealed(title, "Zitat:\n" + line + "\nEnde", click, "info"), True),
            case("Titel geändert", good, False, title="Entwarnung: Österreich"),
            case("Text geändert", good.replace("52 %", "5 %"), False),
            case("Link geändert", good, False, click="https://example.org/falle"),
            case("anderes Thema", good, False, topic="anderes-thema"),
            case("Dringlichkeit geändert", sign.attach(text, f"br1.{louder}.{quiet.rsplit('.', 1)[1]}"), False),
            case("ohne Unterschrift", body, False),
            case("Text nach der Unterschrift", good + "\nNachsatz", False),
            case("unbekannter Schlüssel", sealed(title, body, click, key=sign.Key("k9", sign.parse_key(TEST_KEY).d)), False),
            case("fremder Schlüssel", sealed(title, body, click, key=other_key()), False),
            case("Felder verschoben", sign.attach(rest, line), False, title=title + "\n" + click, click=first),
            case("Unterschrift beschädigt", good[:-2] + ("A" if good[-2] != "A" else "B") + good[-1], False),
            case("Angaben kein JSON", sign.attach(text, f"br1.{sign.b64(b'kein json, nur text')}.{signature}"), False),
            case("nur Unsinn", "br1.x.y", False),
        ]

    def test_file_is_current(self):
        cases = self.cases()
        document = {"hinweis": "Erzeugt von tests/test_sign.py (UPDATE_VECTORS=1). Nicht von Hand ändern.",
                    "keys": KEYS, "cases": cases}
        text = json.dumps(document, ensure_ascii=False, indent=1) + "\n"
        if os.environ.get("UPDATE_VECTORS"):
            VECTORS.write_text(text, encoding="utf-8")
        self.assertEqual(VECTORS.read_text(encoding="utf-8"), text,
                         "tests/data/unterschrift.json ist veraltet: UPDATE_VECTORS=1 python3 -m unittest tests.test_sign")

    def test_cases(self):
        for case in json.loads(VECTORS.read_text(encoding="utf-8"))["cases"]:
            result = sign.unseal(KEYS, case["topic"], case["title"], case["message"], case["click"])
            self.assertEqual(result is not None, case["valid"], case["name"])


if __name__ == "__main__":
    unittest.main()
