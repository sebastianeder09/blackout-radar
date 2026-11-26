"""Versand der Meldungen: ntfy (Push) und E-Mail.

Was nicht zugestellt werden kann, bleibt im Postausgang und wird beim nächsten
Lauf erneut versucht, getrennt je Kanal. Jede Meldung hat einen Schlüssel und
geht pro Kanal nur einmal hinaus.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo

from . import http
from .http import HttpError
from .model import Message, iso, parse_ts

log = logging.getLogger("blackout_radar")

NTFY_PRIORITY = {"alarm": 5, "warn": 4, "info": 3, "ok": 3, "daily": 2}
NTFY_TAGS = {"alarm": ["rotating_light"], "warn": ["warning"], "info": ["zap"],
             "ok": ["white_check_mark"], "daily": ["bar_chart"]}
KEEP_HOURS = 12   # so lange wird ein fehlgeschlagener Versand wiederholt
SENT_LOG = 40     # so viele verschickte Meldungen zeigt der Lagebericht


class DeliveryError(Exception):
    pass


def clip(text: str, max_bytes: int) -> str:
    """Kürzt Text auf eine Byte-Länge, ohne ein Zeichen zu zerschneiden."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[: max_bytes - 4].decode("utf-8", errors="ignore").rstrip() + " …"


def send_ntfy(cfg: dict, message: Message) -> None:
    # JSON an die Server-Adresse: so kommen Umlaute und Zeilenumbrüche sicher an.
    payload = {
        "topic": cfg["topic"],
        "title": clip(message.title, 240),
        "message": clip(message.body, 3800),  # ntfy erlaubt 4096 Bytes je Nachricht
        "priority": NTFY_PRIORITY.get(message.level, 3),
        "tags": NTFY_TAGS.get(message.level, []),
    }
    if message.url:
        payload["click"] = message.url
    headers = {"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else None
    try:
        http.post_json(cfg["server"].rstrip("/") + "/", payload, headers=headers)
    except HttpError as err:
        raise DeliveryError(f"ntfy: {err}") from None


def build_email(cfg: dict, message: Message) -> tuple[EmailMessage, list[str]]:
    recipients = [a.strip() for a in str(cfg["recipient"]).replace(";", ",").split(",") if a.strip()]
    mail = EmailMessage()
    mail["Subject"] = f"[Blackout-Radar] {message.title}"
    mail["From"] = cfg["sender"]
    mail["To"] = ", ".join(recipients)
    mail["Date"] = formatdate(localtime=False)
    mail["Message-ID"] = make_msgid(domain=str(cfg["sender"]).rsplit("@", 1)[-1].strip("> ") or None)
    if message.level in ("alarm", "warn"):
        mail["X-Priority"] = "1"
        mail["Importance"] = "high"
    body = message.body
    if message.url:
        body += f"\n\nLagebericht: {message.url}"
    mail.set_content(body + "\n")
    return mail, recipients


def send_email(cfg: dict, message: Message) -> None:
    mail, recipients = build_email(cfg, message)
    port = int(cfg.get("port") or 587)
    context = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(cfg["host"], port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(cfg["host"], port, timeout=30)
        with server:
            encrypted = port == 465
            if not encrypted:
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls(context=context)
                    server.ehlo()
                    encrypted = True
            if cfg.get("user"):
                if not encrypted and not cfg.get("allow_unencrypted"):
                    raise DeliveryError("E-Mail: Server bietet keine Verschlüsselung, Anmeldung abgebrochen")
                server.login(cfg["user"], cfg.get("password", ""))
            server.send_message(mail, to_addrs=recipients)
    except (smtplib.SMTPException, OSError) as err:
        raise DeliveryError(f"E-Mail: {type(err).__name__}: {str(err)[:160]}") from None


SENDERS = {"ntfy": send_ntfy, "email": send_email}


class Notifier:
    def __init__(self, cfg: dict, state: dict):
        self.cfg = cfg["notify"]
        self.tz = ZoneInfo(cfg.get("timezone", "Europe/Vienna"))
        self.outbox: list = state.setdefault("outbox", [])
        self.sent: list = state.setdefault("sent", [])

    def channels(self, level: str | None = None) -> list[str]:
        return [name for name in SENDERS
                if self.cfg[name].get("enabled") and level not in (self.cfg[name].get("skip_levels") or [])]

    def queue(self, messages: list[Message], now) -> None:
        known = {item["message"].get("key") for item in self.outbox} | {entry.get("key") for entry in self.sent}
        for message in messages:
            if message.key and message.key in known:
                continue
            known.add(message.key)
            self.outbox.append({"message": message.to_dict(), "pending": self.channels(message.level),
                                "done": [], "errors": {}, "queued_at": iso(now)})

    def flush(self, now) -> int:
        """Versucht alles im Postausgang zuzustellen. Liefert die Zahl der Zustellungen."""
        delivered, remaining = 0, []
        for item in self.outbox:
            message = Message.from_dict(item["message"])
            queued = parse_ts(item["queued_at"]) or now
            if now - queued > timedelta(minutes=20):
                when = queued.astimezone(self.tz).strftime("%d.%m. %H:%M")
                message.body = f"Verspätet zugestellt, erstellt am {when} Uhr.\n{message.body}"
            for channel in list(item["pending"]):
                if not self.cfg.get(channel, {}).get("enabled"):
                    item["pending"].remove(channel)  # Kanal wurde inzwischen abgeschaltet
                    continue
                try:
                    SENDERS[channel](self.cfg[channel], message)
                except DeliveryError as err:
                    item["errors"][channel] = str(err)[:200]
                    log.warning("Versand fehlgeschlagen (%s): %s", message.title, err)
                else:
                    item["pending"].remove(channel)
                    item["done"].append(channel)
                    item["errors"].pop(channel, None)
                    delivered += 1
            if item["pending"] and now - queued <= timedelta(hours=KEEP_HOURS):
                remaining.append(item)
                continue
            if not item["done"]:
                log.warning("Meldung nicht zugestellt (%s): %s", message.title,
                            "; ".join(item["errors"].values()) or "kein Kanal eingerichtet")
            self.sent.insert(0, {"t": item["queued_at"], "title": item["message"]["title"],
                                 "level": item["message"]["level"], "key": item["message"]["key"],
                                 "channels": item["done"], "failed": item["pending"]})
        del self.sent[SENT_LOG:]
        self.outbox[:] = remaining
        return delivered

    def test(self, message: Message) -> dict:
        """Schickt eine Meldung sofort an alle Kanäle und liefert je Kanal 'ok' oder den Fehler."""
        result = {}
        for channel in self.channels():
            try:
                SENDERS[channel](self.cfg[channel], message)
                result[channel] = "ok"
            except DeliveryError as err:
                result[channel] = str(err)
        return result
