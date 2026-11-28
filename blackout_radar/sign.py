"""Unterschrift für den öffentlichen Alarm.

Das öffentliche Thema bei ntfy kann jeder lesen und jeder beschreiben. Damit eine fremde Nachricht dort
keinen Alarm auslöst, unterschreibt der Radar jede Meldung. Die App kennt nur den öffentlichen Schlüssel,
prüft die Unterschrift und verwirft alles andere.

Verfahren: ECDSA mit der Kurve P-256 und SHA-256, weil jedes Android das prüfen kann. Unterschrieben wird
in reinem Python, ohne Zusatzpakete. Die Zahl k je Unterschrift wird nach RFC 6979 aus Schlüssel und
Nachricht abgeleitet, ein Zufallsgenerator ist beim Unterschreiben nicht im Spiel. Die Rechnung läuft
nicht in gleichbleibender Zeit. Das ist hier vertretbar: Unterschrieben wird in einem Lauf bei GitHub,
dessen Rechenzeit niemand von außen ausmessen kann.

Eine unterschriebene Meldung trägt als letzte Zeile ihres Textes:

    br1.<Angaben>.<Unterschrift>

Angaben: JSON als base64url ohne Füllzeichen, {"k": Name des Schlüssels, "t": Zeit der Meldung in
Unix-Sekunden, "l": Dringlichkeit, "i": Schlüssel der Meldung}. Die Unterschrift (DER, base64url) deckt
Thema, Angaben, Titel, Link und Text ab, siehe signing_input(). Die App zeigt nur an, was unterschrieben
ist: Dringlichkeit und Zeit nimmt sie aus den Angaben, nicht aus den Feldern von ntfy.

Gegen das erneute Einspielen einer alten echten Meldung hilft die Zeit "t" zusammen mit dem Schlüssel der
Meldung: Die App merkt sich beides und verwirft, was sie schon kennt oder was zu alt ist.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets as random
from dataclasses import dataclass

VERSION = "br1"
DOMAIN = "blackout-radar/1"

# Öffentliche Schlüssel, die die App kennt (Name -> Punkt der Kurve, unkomprimiert, hexadezimal).
# Dieselben Werte stehen in der App. Der geheime Teil liegt nur als Secret ALARM_KEY bei GitHub.
PUBLIC_KEYS: dict[str, str] = {
    "k1": "04b81db61af18d998f74e1530279007b00c56b947532f8e6aa6c5a344cc4de0817"
          "ddd8e9f6ad66f8e226627f7999783343a4653d11f364c79a79753fb2ad9d2ef0",
}

# Kurve P-256 (secp256r1)
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)

KEY_FORMAT = re.compile(r"BRKEY1:([a-z0-9]{1,8}):([0-9a-f]{64})")
LINE_FORMAT = re.compile(r"br1\.([A-Za-z0-9_-]{8,600})\.([A-Za-z0-9_-]{16,128})")
# Die Zeit einer Meldung ist eine ganze Zahl von Sekunden seit 1970, kleiner als dieser Wert. So rechnet jede
# Sprache mit ihr genau (auch eine, die nur Kommazahlen kennt).
MAX_TIME = 1 << 53
# Zeichen, die in einer Meldung nichts verloren haben (Steuerzeichen außer Zeilenumbruch und Tabulator)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
LINE_BREAKS = re.compile(r"[\r\n\x0b\x0c\x1c-\x1e\x85  ]+")


class BadKey(ValueError):
    """Der Schlüssel aus ALARM_KEY ist nicht brauchbar."""


# ------------------------------------------------------------------- Kurve
def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        slope = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (slope * slope - x1 - x2) % P
    return x3, (slope * (x1 - x3) - y1) % P


def _mul(k: int, point):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


def on_curve(point) -> bool:
    if point is None:
        return False
    x, y = point
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


# --------------------------------------------------------------- Schlüssel
@dataclass(frozen=True)
class Key:
    kid: str   # Name des Schlüssels, steht in jeder Meldung
    d: int     # geheime Zahl

    @property
    def public(self) -> tuple[int, int]:
        return _mul(self.d, G)

    @property
    def public_hex(self) -> str:
        return point_hex(self.public)

    def export(self) -> str:
        """Der Wert für das Secret ALARM_KEY."""
        return f"BRKEY1:{self.kid}:{self.d:064x}"


def point_hex(point) -> str:
    return "04" + f"{point[0]:064x}" + f"{point[1]:064x}"


def parse_point(text: str) -> tuple[int, int]:
    raw = bytes.fromhex(text)
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("öffentlicher Schlüssel: erwartet sind 65 Bytes, beginnend mit 04")
    point = int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big")
    if not on_curve(point):
        raise ValueError("öffentlicher Schlüssel liegt nicht auf der Kurve")
    return point


def parse_key(text: str) -> Key:
    """Liest den Wert aus ALARM_KEY. Die Fehlermeldung nennt nie den Schlüssel selbst."""
    match = KEY_FORMAT.fullmatch((text or "").strip())
    if not match:
        raise BadKey("ALARM_KEY hat nicht die Form BRKEY1:<Name>:<64 Hex-Zeichen>")
    d = int(match.group(2), 16)
    if not 1 <= d < N:
        raise BadKey("ALARM_KEY liegt außerhalb des gültigen Bereichs")
    return Key(match.group(1), d)


def generate(kid: str = "k1") -> Key:
    return Key(kid, random.randbelow(N - 1) + 1)


# ------------------------------------------------------------ Unterschrift
def _nonces(d: int, digest: bytes):
    """Die Zahlen k nach RFC 6979, Abschnitt 3.2 (SHA-256, Kurve mit 256 Bit)."""
    secret = d.to_bytes(32, "big")
    reduced = (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + secret + reduced, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + secret + reduced, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < N:
            yield candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign_numbers(d: int, data: bytes) -> tuple[int, int]:
    digest = hashlib.sha256(data).digest()
    z = int.from_bytes(digest, "big")
    for k in _nonces(d, digest):
        r = _mul(k, G)[0] % N
        if r == 0:
            continue
        s = pow(k, -1, N) * (z + r * d) % N
        if s:
            return r, s
    raise AssertionError("unerreichbar")


def _der_int(value: int) -> bytes:
    raw = value.to_bytes((value.bit_length() + 8) // 8, "big")  # führendes Nullbyte, wenn das oberste Bit gesetzt ist
    return b"\x02" + bytes([len(raw)]) + raw


def der(r: int, s: int) -> bytes:
    body = _der_int(r) + _der_int(s)
    return b"\x30" + bytes([len(body)]) + body


def parse_der(raw: bytes) -> tuple[int, int] | None:
    """Liest eine DER-Unterschrift. Streng: Was nicht genau passt, gilt als ungültig."""
    try:
        if raw[0] != 0x30 or raw[1] != len(raw) - 2 or raw[1] > 0x7F:
            return None
        numbers, pos = [], 2
        for _ in range(2):
            if raw[pos] != 0x02:
                return None
            size = raw[pos + 1]
            chunk = raw[pos + 2: pos + 2 + size]
            if size == 0 or size > 33 or len(chunk) != size or chunk[0] & 0x80:
                return None
            if size > 1 and chunk[0] == 0 and not chunk[1] & 0x80:
                return None  # überflüssiges Nullbyte
            numbers.append(int.from_bytes(chunk, "big"))
            pos += 2 + size
        return (numbers[0], numbers[1]) if pos == len(raw) else None
    except IndexError:
        return None


def sign(d: int, data: bytes) -> bytes:
    """Unterschreibt die Daten und liefert die Unterschrift in DER.

    Zu jeder Unterschrift (r, s) gilt auch (r, n - s). Geliefert wird immer die mit dem kleineren s,
    so hat jede Meldung genau eine Form.
    """
    r, s = sign_numbers(d, data)
    return der(r, min(s, N - s))


def verify(point, data: bytes, signature: bytes) -> bool:
    numbers = parse_der(signature)
    if numbers is None or not on_curve(point):
        return False
    r, s = numbers
    if not (1 <= r < N and 1 <= s < N):
        return False
    z = int.from_bytes(hashlib.sha256(data).digest(), "big")
    w = pow(s, -1, N)
    result = _add(_mul(z * w % N, G), _mul(r * w % N, point))
    return result is not None and result[0] % N == r


# ------------------------------------------------------------ Meldungstext
def _valid_utf8(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8")


def clean_title(title: str) -> str:
    """Titel in der Form, die ntfy unverändert weitergibt: eine Zeile, keine Leerzeichen an den Enden."""
    text = LINE_BREAKS.sub(" ", CONTROL.sub("", _valid_utf8(title))).strip()
    return text.replace("=?", "= ?")  # sonst hält ntfy den Titel für kodiert (RFC 2047) und wandelt ihn um


def clean_body(body: str) -> str:
    """Text in der Form, die ntfy unverändert weitergibt."""
    text = _valid_utf8(body).replace("\r\n", "\n").replace("\r", "\n")
    return CONTROL.sub("", text).strip()


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_input(topic: str, meta: str, title: str, click: str, body: str) -> bytes:
    """Die Daten, über die unterschrieben wird.

    Thema, Angaben, Titel und Link sind je eine Zeile ohne Zeilenumbruch, der Text steht am Schluss.
    So lässt sich nichts von einem Feld in ein anderes schieben. Das Thema gehört dazu, damit eine
    Meldung nicht in ein anderes Thema kopiert werden kann.
    """
    return "\n".join((DOMAIN, topic, meta, title, click, body)).encode("utf-8")


def seal(key: Key, topic: str, title: str, body: str, click: str, level: str, ident: str, created: int) -> str:
    """Liefert die Zeile mit der Unterschrift. Titel, Text und Link müssen schon bereinigt sein."""
    for name, value in (("Thema", topic), ("Titel", title), ("Link", click)):
        if "\n" in value or "\r" in value:
            raise ValueError(f"{name} enthält einen Zeilenumbruch")
    fields = {"k": key.kid, "t": int(created), "l": level, "i": ident}
    meta = b64(json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    data = signing_input(topic, meta, title, click, body)
    signature = sign(key.d, data)
    if not verify(key.public, data, signature):  # lieber kein Versand als eine Meldung, die jede App verwirft
        raise ValueError("Unterschrift hält der eigenen Prüfung nicht stand")
    return f"{VERSION}.{meta}.{b64(signature)}"


def attach(body: str, line: str) -> str:
    """Hängt die Zeile mit der Unterschrift an den Text."""
    return f"{body}\n\n{line}" if body else line


def split(message: str) -> tuple[str, str] | None:
    """Trennt Text und Zeile mit der Unterschrift. None, wenn die letzte Zeile keine ist."""
    head, _, last = message.rpartition("\n")
    if not LINE_FORMAT.fullmatch(last):
        return None
    return head.rstrip("\n"), last


def unseal(keys: dict[str, str], topic: str, title: str, message: str, click: str = "") -> dict | None:
    """Prüft eine empfangene Meldung so, wie es die App tut.

    Liefert die Angaben samt Text ("body") oder None, wenn die Unterschrift fehlt oder nicht passt.
    """
    parts = split(message)
    # Ein Zeilenumbruch in Titel oder Link ließe Text von einem Feld ins andere wandern, ohne dass sich die
    # unterschriebenen Daten ändern. Der Radar schickt so etwas nie.
    if parts is None or any(mark in title + click for mark in "\r\n"):
        return None
    body, line = parts
    _, meta, signature = line.split(".")
    try:
        fields = json.loads(unb64(meta).decode("utf-8"))
        raw = unb64(signature)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(fields, dict) or not isinstance(fields.get("k"), str) or fields["k"] not in keys:
        return None
    if not isinstance(fields.get("t"), int) or isinstance(fields["t"], bool) or not 0 <= fields["t"] < MAX_TIME:
        return None
    if not isinstance(fields.get("l"), str) or not isinstance(fields.get("i"), str):
        return None
    try:
        point = parse_point(keys[fields["k"]])
        data = signing_input(topic, meta, title, click, body)
    except ValueError:  # auch: ein halbes Zeichenpaar im Text, das sich nicht als UTF-8 schreiben lässt
        return None
    if not verify(point, data, raw):
        return None
    return {**fields, "body": body}
