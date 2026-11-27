#!/usr/bin/env python3
"""Liest die Seite der App im Emulator, so wie die WebView sie gerade zeigt.

Aufruf:  seite.py <paket> [ausdruck]

Ohne Ausdruck kommt der Text, der gerade in der Seite steht (document.body.innerText).
Mit Ausdruck wird dieser in der Seite ausgewertet und sein Ergebnis ausgegeben, bei einem
Promise das, was es am Ende liefert. So lässt sich auch ein Knopf drücken:
seite.py <paket> "document.querySelector('button').click()"

Der Weg führt über die Entwickler-Schnittstelle der WebView (dieselbe, die Chrome unter
chrome://inspect nutzt). Auf Emulator-Abbildern ("google_apis", zum Entwickeln gebautes
Android) gibt die WebView sie für jede App frei, auch für die fertige. Auf einem
gewöhnlichen Handy ist sie in der fertigen App geschlossen.

Ende mit 0 bei Erfolg, mit 2 wenn die Seite nicht erreichbar ist, mit 1 bei einem Fehler
im Ausdruck. Braucht nur adb und Python, keine weiteren Bibliotheken.
"""
import base64
import http.client
import json
import os
import socket
import struct
import subprocess
import sys

HOST = "127.0.0.1"


class Unreachable(Exception):
    """Die Seite ist nicht erreichbar: App läuft nicht, oder die Schnittstelle ist zu."""


def adb(*args):
    return subprocess.run(["adb", *args], capture_output=True, text=True, timeout=30)


class WebSocket:
    """Gerade so viel WebSocket, wie ein Aufruf mit einer Antwort braucht."""

    def __init__(self, host, port, path, timeout=15):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buffer = b""
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        while b"\r\n\r\n" not in self.buffer:
            self._fill()
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in status + " ":
            raise Unreachable(f"Die WebView lehnt die Verbindung ab ({status}).")

    def _fill(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise Unreachable("Die WebView hat die Verbindung geschlossen.")
        self.buffer += chunk

    def _take(self, count):
        while len(self.buffer) < count:
            self._fill()
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def _frame(self, opcode, payload):
        size = len(payload)
        head = bytearray([0x80 | opcode])
        if size < 126:
            head.append(0x80 | size)
        elif size < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", size)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", size)
        mask = os.urandom(4)  # Der Aufrufer muss seine Daten verschleiern, so will es das Protokoll.
        self.sock.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, text):
        self._frame(0x1, text.encode("utf-8"))

    def receive(self):
        """Liefert die nächste vollständige Nachricht als Text."""
        parts = []
        while True:
            first, second = self._take(2)
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._take(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._take(8))[0]
            mask = self._take(4) if second & 0x80 else None
            payload = self._take(size)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            opcode = first & 0x0F
            if opcode == 0x8:
                raise Unreachable("Die WebView hat die Verbindung geschlossen.")
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            parts.append(payload)
            if first & 0x80:
                return b"".join(parts).decode("utf-8")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def pages(port):
    try:
        connection = http.client.HTTPConnection(HOST, port, timeout=10)
        connection.request("GET", "/json")
        body = connection.getresponse().read()
        connection.close()
        return json.loads(body)
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise Unreachable(f"Die WebView bietet keine Entwickler-Schnittstelle an ({error}).")


def evaluate(port, expression):
    """Wertet den Ausdruck in der Seite aus, die auf diesem Anschluss erreichbar ist."""
    found = [p for p in pages(port) if p.get("type") == "page" and p.get("webSocketDebuggerUrl")]
    if not found:
        raise Unreachable("Die App zeigt gerade keine Seite.")
    path = "/" + found[0]["webSocketDebuggerUrl"].split("/", 3)[3]
    ws = WebSocket(HOST, port, path)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            answer = json.loads(ws.receive())
            if answer.get("id") == 1:
                break
    except (OSError, ValueError) as error:
        raise Unreachable(f"Keine Antwort der Seite ({error}).")
    finally:
        ws.close()
    if "error" in answer:
        raise ValueError(answer["error"].get("message", "unbekannter Fehler"))
    result = answer.get("result", {})
    if "exceptionDetails" in result:
        details = result["exceptionDetails"]
        raise ValueError(details.get("exception", {}).get("description") or details.get("text", "Fehler im Ausdruck"))
    return result.get("result", {}).get("value")


def read_app(package, expression):
    pid = adb("shell", "pidof", package).stdout.split()
    if not pid:
        raise Unreachable(f"{package} läuft nicht.")
    forward = adb("forward", "tcp:0", f"localabstract:webview_devtools_remote_{pid[0]}")
    if forward.returncode != 0 or not forward.stdout.strip().isdigit():
        raise Unreachable(f"adb forward fehlgeschlagen: {forward.stderr.strip() or forward.stdout.strip()}")
    port = int(forward.stdout.strip())
    try:
        return evaluate(port, expression)
    finally:
        adb("forward", "--remove", f"tcp:{port}")


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    expression = argv[2] if len(argv) > 2 else "document.body.innerText"
    sys.stdout.reconfigure(encoding="utf-8")  # Umlaute auch dann, wenn die Umgebung nur ASCII kennt
    try:
        # Zum Ausprobieren am Rechner: "tcp:<anschluss>" statt eines Pakets spricht einen Browser direkt an.
        value = evaluate(int(argv[1][4:]), expression) if argv[1].startswith("tcp:") else read_app(argv[1], expression)
    except Unreachable as error:
        print(error, file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"Fehler im Ausdruck: {error}", file=sys.stderr)
        return 1
    if value is not None:
        print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
