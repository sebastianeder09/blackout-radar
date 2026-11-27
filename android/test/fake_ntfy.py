"""Nachgestellter ntfy-Server, Lagebericht und Radar für die Prüfung im Emulator.

ntfy, so wie ntfy.sh antwortet:
  GET  /<thema>/json    Meldungen des Themas (since=, mit poll=1 einmalig, sonst als Datenstrom mit Lebenszeichen)
  POST /<thema>         neue Meldung, Titel und Dringlichkeit in den Kopfzeilen (wie mit curl)
  POST /                neue Meldung als JSON. So sendet der Radar.

Lagebericht:
  GET  /status.json, /status.md

Radar, nur für die Prüfung. Dahinter läuft der echte Versand des Radars (blackout_radar.notify) mit seinem
Postausgang. Was im Lagebericht unter "notices" steht, kommt also aus demselben Code wie im Betrieb:
  POST /radar/meldung   {"title", "body", "level"}  Der Radar erstellt eine Meldung und versucht sie zuzustellen.
  POST /radar/lauf      {"minuten_spaeter": 0}      Der nächste Lauf: Der Radar versucht den Postausgang noch einmal.
  POST /schalter        {"radar_erreicht_ntfy": true, "handy_erreicht_ntfy": true, "thema_des_radars": "testthema"}
                        Stellt Störungen nach. Jede Angabe ist freiwillig.

  python3 android/test/fake_ntfy.py <ordner> [port]

Der Ordner kommt von fixtures.py.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fixtures  # noqa: E402
from blackout_radar import config, report  # noqa: E402
from blackout_radar.model import Message, iso, now_utc  # noqa: E402
from blackout_radar.notify import Notifier  # noqa: E402

FOLDER = Path(sys.argv[1])
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
TOPIC = "testthema"
MESSAGES: list[dict] = json.loads((FOLDER / "meldungen.json").read_text(encoding="utf-8"))
LOCK = threading.Condition()
SWITCH = {"radar_erreicht_ntfy": True, "handy_erreicht_ntfy": True, "thema_des_radars": TOPIC}

# Der Radar: Einstellungen wie im Betrieb, nur dass sein ntfy dieser Server ist.
CFG = config.load(str(Path(__file__).resolve().parents[2] / "config.toml"))
CFG["status_url"] = fixtures.STATUS_URL
CFG["notify"]["ntfy"].update(enabled=True, server=f"http://127.0.0.1:{PORT}", topic=TOPIC, token="")
CFG["notify"]["email"]["enabled"] = False
STATE: dict = json.loads((FOLDER / "zustand.json").read_text(encoding="utf-8"))
RADAR = threading.Lock()  # immer nur ein Lauf des Radars zur selben Zeit
BODIES: dict[str, str] = {}
COUNTER = 0


def radar_notices() -> list[dict]:
    """Die Meldungen so, wie der Radar sie in den Lagebericht schreibt."""
    with RADAR:
        try:
            listed = report.Report(CFG, STATE, now_utc()).snapshot().get("notices")
        except Exception as err:  # noqa: BLE001 - der Server soll weiterlaufen, der Fehler steht im Protokoll
            sys.stderr.write(f"fake_ntfy: Lagebericht des Radars nicht erstellbar: {type(err).__name__}: {err}\n")
            listed = None
        # Führt der Radar die Liste noch nicht selbst, gilt das abgesprochene Format.
        return listed if listed is not None else fixtures.notices(STATE, BODIES)


def radar_post(title: str, body: str, level: str) -> dict:
    """Der Radar erstellt eine Meldung und versucht sofort, sie zuzustellen."""
    global COUNTER
    with RADAR:
        now = now_utc()
        COUNTER += 1
        key = f"pruefung:{iso(now)}:{COUNTER}"
        BODIES[key] = body
        notifier = Notifier(CFG, STATE)
        notifier.queue([Message(title, body, level, key, fixtures.STATUS_URL)], now)
        delivered = notifier.flush(now)
    return {"key": key, "zugestellt": delivered, "wartet": len(STATE.get("outbox") or [])}


def radar_run(minutes_later: int) -> dict:
    """Ein weiterer Lauf des Radars. Mit minutes_later geht seine Uhr vor, damit er verspätet zustellt."""
    with RADAR:
        delivered = Notifier(CFG, STATE).flush(now_utc() + timedelta(minutes=minutes_later))
    return {"zugestellt": delivered, "wartet": len(STATE.get("outbox") or [])}


def since_filter(topic: str, since: str) -> list[dict]:
    with LOCK:
        items = list(MESSAGES)
    if since.isdigit():
        items = [m for m in items if m["time"] > int(since)]
    elif since not in ("", "all"):
        ids = [m["id"] for m in items]
        if since in ids:
            items = items[ids.index(since) + 1:]
    return [m for m in items if m["topic"] == topic]


def publish(topic: str, title: str, body: str, priority: int, tags: list, click: str = "") -> dict:
    with LOCK:
        message = {"id": f"neu{int(time.time() * 1000)}n{len(MESSAGES)}", "time": int(time.time()), "event": "message",
                   "topic": topic, "title": title, "message": body, "priority": priority, "tags": tags}
        if click:
            message["click"] = click
        MESSAGES.append(message)
        LOCK.notify_all()
    return message


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

    def send_json(self, code: int, data) -> None:
        self.send_body(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def do_GET(self):  # noqa: N802
        url = urlsplit(self.path)
        name = url.path.strip("/")
        if name == "status.json":
            status = json.loads((FOLDER / name).read_text(encoding="utf-8"))
            status["notices"] = radar_notices()
            self.send_json(200, status)
            return
        if name == "status.md":
            self.send_body(200, (FOLDER / name).read_bytes(), "text/markdown; charset=utf-8")
            return
        parts = name.split("/")
        if len(parts) != 2 or parts[1] != "json":
            self.send_body(404, b"not found", "text/plain")
            return
        if not SWITCH["handy_erreicht_ntfy"]:
            self.send_body(503, b"ntfy ist fuer das Handy abgeschaltet", "text/plain")
            return
        topic = parts[0]
        query = parse_qs(url.query)
        since = query.get("since", [""])[0]
        lines = [json.dumps(m, ensure_ascii=False) + "\n" for m in since_filter(topic, since)]
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
            chunk(json.dumps({"id": "open", "time": int(time.time()), "event": "open", "topic": topic}) + "\n")
            for line in lines:
                chunk(line)
            with LOCK:
                seen = len(MESSAGES)
            while True:
                with LOCK:
                    LOCK.wait(timeout=30)
                    fresh = [m for m in MESSAGES[seen:] if m["topic"] == topic]
                    seen = len(MESSAGES)
                if not SWITCH["handy_erreicht_ntfy"]:
                    # ntfy fällt aus: Die Verbindung reißt ab, ohne dass noch etwas ankommt.
                    self.close_connection = True
                    return
                for m in fresh:
                    chunk(json.dumps(m, ensure_ascii=False) + "\n")
                if not fresh:
                    chunk(json.dumps({"id": "ka", "time": int(time.time()), "event": "keepalive", "topic": topic}) + "\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):  # noqa: N802
        path = urlsplit(self.path).path.strip("/")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if path in ("", "radar/meldung", "radar/lauf", "schalter"):
            try:
                data = json.loads(body or "{}")
            except ValueError:
                self.send_body(400, b"kein JSON", "text/plain")
                return
            if path == "":  # der Radar sendet
                if not SWITCH["radar_erreicht_ntfy"]:
                    self.send_body(503, b"ntfy ist fuer den Radar abgeschaltet", "text/plain")
                    return
                self.send_json(200, publish(data["topic"], data.get("title", ""), data.get("message", ""),
                                            int(data.get("priority") or 3), data.get("tags") or [], data.get("click", "")))
            elif path == "radar/meldung":
                self.send_json(200, radar_post(data["title"], data.get("body", ""), data.get("level", "info")))
            elif path == "radar/lauf":
                self.send_json(200, radar_run(int(data.get("minuten_spaeter") or 0)))
            else:
                with LOCK:
                    SWITCH.update({name: value for name, value in data.items() if name in SWITCH})
                    LOCK.notify_all()  # offene Datenströme sehen nach, ob sie abreißen sollen
                with RADAR:
                    CFG["notify"]["ntfy"]["topic"] = SWITCH["thema_des_radars"]
                self.send_json(200, SWITCH)
            return
        self.send_json(200, publish(path, self.headers.get("Title", ""), body, int(self.headers.get("Priority") or 3),
                                    [t for t in (self.headers.get("Tags") or "").split(",") if t]))


if __name__ == "__main__":
    print(f"fake_ntfy: {len(MESSAGES)} Meldungen, Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
