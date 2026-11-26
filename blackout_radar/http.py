"""Kleiner HTTP-Helfer auf Basis der Standardbibliothek."""
from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "blackout-radar/0.1 (privater Stromausfall-Monitor)"


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: str | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


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
        retry_after = err.headers.get("Retry-After") if err.headers else None
        raise HttpError(f"HTTP {err.code} von {host}", status=err.code, retry_after=retry_after) from None
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
