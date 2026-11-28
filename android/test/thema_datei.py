#!/usr/bin/env python3
"""Das Thema in der Installationsdatei der App, vom Rechner aus: lesen und hineinlegen.

  python3 thema_datei.py lesen <apk>                    gibt das Thema aus, das die Datei mitbringt
  python3 thema_datei.py schreiben <apk> <ziel> <thema> schreibt eine Kopie, die das Thema enthält

Die App legt das Thema beim Weitergeben in den Signaturblock ihrer Installationsdatei (ApkTopic.kt). Dieses
Skript tut dasselbe mit eigenem Code. Der Emulator-Test vergleicht damit die Datei, die das Handy schreibt, Byte
für Byte mit der erwarteten, und er installiert eine hier geschriebene Datei, aus der die App ihr Thema lesen muss.
So prüfen sich die beiden Fassungen gegenseitig.

Aufbau des Blocks: Länge (8 Bytes), Einträge aus Länge (8), Kennung (4) und Inhalt, noch einmal die Länge (8),
Schlusswort "APK Sig Block 42". Er steht direkt vor dem Inhaltsverzeichnis des Archivs.
"""
import struct
import sys

MAGIC = b"APK Sig Block 42"
TOPIC = 0x42524B31    # Eintrag mit dem Thema ("BRK1")
PADDING = 0x42726577  # leerer Eintrag, der den Block auf ein Vielfaches von 4096 Bytes bringt
PAGE = 4096


def parts(data):
    """Anfang des Blocks, des Inhaltsverzeichnisses und des Schlusses, dazu die Einträge des Blocks."""
    # Der Schluss steht ganz hinten. Hinter ihm folgt höchstens sein Kommentar, und dessen Länge reicht genau bis zum Ende.
    end, lowest = len(data) - 22, max(0, len(data) - 22 - 0xFFFF)
    while end >= lowest and not (data[end:end + 4] == b"PK\x05\x06" and struct.unpack_from("<H", data, end + 20)[0] == len(data) - end - 22):
        end -= 1
    if end < lowest:
        raise ValueError("kein Archiv: der Schluss fehlt")
    dir_size, dir_start = struct.unpack_from("<II", data, end + 12)
    if dir_start + dir_size != end or data[dir_start - 16:dir_start] != MAGIC:
        raise ValueError("kein Signaturblock vor dem Inhaltsverzeichnis")
    size = struct.unpack_from("<Q", data, dir_start - 24)[0]
    start = dir_start - size - 8
    if start < 0 or struct.unpack_from("<Q", data, start)[0] != size:
        raise ValueError("die Längenangaben des Signaturblocks passen nicht zusammen")
    entries, pos, stop = [], start + 8, dir_start - 24
    while pos < stop:
        length, ident = struct.unpack_from("<QI", data, pos)
        if length < 4 or pos + 8 + length > stop:
            raise ValueError("ein Eintrag des Signaturblocks reicht über den Block hinaus")
        entries.append((ident, data[pos + 12:pos + 8 + length]))
        pos += 8 + length
    return start, dir_start, end, entries


def block(entries):
    """Der Block aus seinen Einträgen, aufgefüllt so wie es das Signierwerkzeug tut."""
    body = b"".join(struct.pack("<QI", len(value) + 4, ident) + value for ident, value in entries)
    size = 8 + len(body) + 24
    if size % PAGE:
        gap = PAGE - size % PAGE
        if gap < 12:  # auch ein leerer Eintrag braucht 12 Bytes
            gap += PAGE
        body += struct.pack("<QI", gap - 8, PADDING) + bytes(gap - 12)
        size += gap
    return struct.pack("<Q", size - 8) + body + struct.pack("<Q", size - 8) + MAGIC


def topic_of(data):
    for ident, value in parts(data)[3]:
        if ident == TOPIC:
            return value.decode("utf-8")
    return None


def with_topic(data, topic):
    start, dir_start, end, entries = parts(data)
    new = block([entry for entry in entries if entry[0] not in (TOPIC, PADDING)] + [(TOPIC, topic.encode("utf-8"))])
    tail = bytearray(data[end:])
    struct.pack_into("<I", tail, 16, start + len(new))  # der Schluss nennt, wo das Inhaltsverzeichnis jetzt beginnt
    return data[:start] + new + data[dir_start:end] + bytes(tail)


def main(args):
    if len(args) == 2 and args[0] == "lesen":
        with open(args[1], "rb") as source:
            topic = topic_of(source.read())
        if topic is None:
            print("Die Datei bringt kein Thema mit.", file=sys.stderr)
            return 1
        print(topic)
        return 0
    if len(args) == 4 and args[0] == "schreiben":
        with open(args[1], "rb") as source:
            data = with_topic(source.read(), args[3])
        with open(args[2], "wb") as target:
            target.write(data)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, struct.error) as problem:
        print(f"Fehler: {problem}", file=sys.stderr)
        sys.exit(1)
