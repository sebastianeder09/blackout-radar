"""Kleiner HTTP-Helfer auf Basis der Standardbibliothek."""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
import zlib

USER_AGENT = "blackout-radar/0.1 (privater Stromausfall-Monitor)"


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


def request(url: str, *, params: dict | None = None, data: bytes | None = None,
            headers: dict | None = None, method: str | None = None, timeout: float = 20):
    """Führt eine Anfrage aus und liefert (Status, Header, Body als Bytes)."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    host = urllib.parse.urlsplit(url).netloc
    all_headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "gzip"}
    all_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as err:
        head = dict(err.headers) if err.headers else {}
        raise HttpError(f"HTTP {err.code} von {host}", status=err.code, retry_after=head.get("Retry-After"),
                        headers=head, body=_error_text(err)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        reason = getattr(err, "reason", err)
        raise HttpError(f"{host} nicht erreichbar ({reason})") from None


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
