"""Kleiner HTTP-Helfer auf Basis der Standardbibliothek."""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
import zlib

USER_AGENT = "blackout-radar/0.1 (privater Stromausfall-Monitor)"

# Je Anfrage: (Host, erreicht). "Erreicht" heißt, der Server hat geantwortet, auch mit einem Fehler.
# Daraus liest reach.py, ob die Messquellen in Europa noch antworten.
JOURNAL: list[tuple[str, bool]] = []


def drain() -> list[tuple[str, bool]]:
    """Liefert das Protokoll der Anfragen seit dem letzten Aufruf und leert es."""
    entries = JOURNAL[:]
    JOURNAL.clear()
    return entries


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: str | None = None,
                 headers: dict | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.headers = headers or {}
        self.body = body  # Anfang der Fehlerantwort, nur für die Diagnose


def _error_text(err) -> str:
    try:
        raw = err.read(65536)
        if (err.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
    except (OSError, EOFError, zlib.error):
        return ""
    return " ".join(raw.decode("utf-8", errors="replace").split())[:300]


def _body(resp, limit: int | None, host: str) -> bytes:
    """Liest die Antwort, auf Wunsch mit Obergrenze (auch für den entpackten Inhalt)."""
    packed = resp.headers.get("Content-Encoding", "").lower() == "gzip"
    if limit is None:
        raw = resp.read()
        return gzip.decompress(raw) if packed else raw
    raw = resp.read(limit + 1)
    if packed and len(raw) <= limit:
        raw = zlib.decompressobj(wbits=31).decompress(raw, limit + 1)
    if len(raw) > limit:
        raise HttpError(f"Antwort von {host} ist größer als {limit // 1000} kB")
    return raw


def request(url: str, *, params: dict | None = None, data: bytes | None = None,
            headers: dict | None = None, method: str | None = None, timeout: float = 20,
            limit: int | None = None):
    """Führt eine Anfrage aus und liefert (Status, Header, Body als Bytes)."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    parts = urllib.parse.urlsplit(url)
    host, name = parts.netloc, parts.hostname or parts.netloc
    all_headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "gzip"}
    all_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    reached = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reached = True
            return resp.status, dict(resp.headers), _body(resp, limit, host)
    except urllib.error.HTTPError as err:
        reached = True
        head = dict(err.headers) if err.headers else {}
        raise HttpError(f"HTTP {err.code} von {host}", status=err.code, retry_after=head.get("Retry-After"),
                        headers=head, body=_error_text(err)) from None
    except (urllib.error.URLError, TimeoutError, OSError, EOFError, zlib.error) as err:
        reason = getattr(err, "reason", err)
        raise HttpError(f"{host} nicht erreichbar ({reason})") from None
    finally:
        JOURNAL.append((name, reached))


def get_text(url: str, **kwargs) -> str:
    _, _, body = request(url, **kwargs)
    return body.decode("utf-8", errors="replace")


def get_json(url: str, **kwargs):
    text = get_text(url, **kwargs)
    try:
        return json.loads(text)
    except ValueError:
        host = urllib.parse.urlsplit(url).netloc
        raise HttpError(f"{host} lieferte kein JSON: {text[:80]!r}") from None


def post_json(url: str, payload: dict, *, headers: dict | None = None, timeout: float = 20):
    all_headers = {"Content-Type": "application/json; charset=utf-8"}
    all_headers.update(headers or {})
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return request(url, data=data, headers=all_headers, method="POST", timeout=timeout)


def post_form(url: str, fields: dict, *, timeout: float = 20):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    return request(url, data=data, method="POST", timeout=timeout,
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
