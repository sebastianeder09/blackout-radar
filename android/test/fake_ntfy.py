"""Nachgestellter ntfy-Server und Lagebericht für die Bildschirmfotos im Emulator.

Liefert die Meldungen aus <ordner>/meldungen.json so, wie ntfy.sh sie liefert
(GET /<thema>/json mit since= und poll=1, sonst als Datenstrom mit Lebenszeichen),
nimmt neue Meldungen per POST /<thema> an und gibt status.json und status.md aus.

  python3 android/test/fake_ntfy.py <ordner> [port]
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FOLDER = Path(sys.argv[1])
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
MESSAGES: list[dict] = json.loads((FOLDER / "meldungen.json").read_text(encoding="utf-8"))
LOCK = threading.Condition()


def since_filter(since: str) -> list[dict]:
    with LOCK:
        items = list(MESSAGES)
    if since in ("", "all"):
        return items
    if since.isdigit():
        return [m for m in items if m["time"] > int(since)]
    ids = [m["id"] for m in items]
    return items[ids.index(since) + 1:] if since in ids else items


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # knapp halten
        sys.stderr.write("fake_ntfy: " + (fmt % args) + "\n")

    def send_body(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlsplit(self.path)
        name = url.path.strip("/")
        if name in ("status.json", "status.md"):
            kind = "application/json" if name.endswith("json") else "text/markdown; charset=utf-8"
            self.send_body(200, (FOLDER / name).read_bytes(), kind)
            return
        parts = name.split("/")
        if len(parts) != 2 or parts[1] != "json":
            self.send_body(404, b"not found", "text/plain")
            return
        query = parse_qs(url.query)
        since = query.get("since", [""])[0]
        lines = [json.dumps(m, ensure_ascii=False) + "\n" for m in since_filter(since)]
        if query.get("poll", ["0"])[0] == "1":
            self.send_body(200, "".join(lines).encode(), "application/x-ndjson; charset=utf-8")
            return
        # Datenstrom: open, verpasste Meldungen, dann neue sofort und alle 30 s ein Lebenszeichen.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def chunk(text: str) -> None:
            data = text.encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        try:
            chunk(json.dumps({"id": "open", "time": int(time.time()), "event": "open", "topic": parts[0]}) + "\n")
            for line in lines:
                chunk(line)
            with LOCK:
                seen = len(MESSAGES)
            while True:
                with LOCK:
                    LOCK.wait(timeout=30)
                    fresh = MESSAGES[seen:]
                    seen = len(MESSAGES)
                for m in fresh:
                    chunk(json.dumps(m, ensure_ascii=False) + "\n")
                if not fresh:
                    chunk(json.dumps({"id": "ka", "time": int(time.time()), "event": "keepalive", "topic": parts[0]}) + "\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):  # noqa: N802
        topic = urlsplit(self.path).path.strip("/")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        message = {"id": f"neu{int(time.time() * 1000)}", "time": int(time.time()), "event": "message", "topic": topic,
                   "title": self.headers.get("Title", ""), "message": body,
                   "priority": int(self.headers.get("Priority") or 3),
                   "tags": [t for t in (self.headers.get("Tags") or "").split(",") if t]}
        with LOCK:
            MESSAGES.append(message)
            LOCK.notify_all()
        self.send_body(200, json.dumps(message).encode(), "application/json")


if __name__ == "__main__":
    print(f"fake_ntfy: {len(MESSAGES)} Meldungen, Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
