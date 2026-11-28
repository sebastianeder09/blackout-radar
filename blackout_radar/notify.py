"""Versand der Meldungen: ntfy (Push), E-Mail und der öffentliche Alarm.

Was nicht zugestellt werden kann, bleibt im Postausgang und wird beim nächsten
Lauf erneut versucht, getrennt je Kanal. Jede Meldung hat einen Schlüssel und
geht pro Kanal nur einmal hinaus.

Der öffentliche Alarm ist ein festes, öffentliches Thema bei ntfy für alle, die die App
installieren. Jede Meldung dorthin trägt eine Unterschrift (siehe sign.py). Meldungen über
den Betrieb des Radars und Tests gehen nie dorthin.
"""
from __future__ import annotations

import json
import logging
import re
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.parse import urlsplit

from . import http, sign
from .http import HttpError
from .model import Message, iso, now_utc, parse_ts, zone

log = logging.getLogger("blackout_radar")

NTFY_PRIORITY = {"alarm": 5, "warn": 4, "info": 3, "ok": 3, "daily": 2}
NTFY_TAGS = {"alarm": ["rotating_light"], "warn": ["warning"], "info": ["zap"],
             "ok": ["white_check_mark"], "daily": ["bar_chart"]}
KEEP_HOURS = 12   # so lange wird ein fehlgeschlagener Versand wiederholt
SENT_LOG = 40     # so viele verschickte Meldungen zeigt der Lagebericht
PUBLIC = "public"         # Name des Kanals für den öffentlichen Alarm
PUBLIC_BODY_BYTES = 3600  # so lang darf der Text dort sein, damit er mit Unterschrift unter 4096 Bytes bleibt
NTFY_MESSAGE_BYTES = 4096  # längere Nachrichten macht ntfy zu einem Anhang


class DeliveryError(Exception):
    pass


class Damaged(DeliveryError):
    """Die Meldung kam beim Dienst an, aber verändert. Ein neuer Versuch würde daran nichts ändern."""


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


def public_payload(cfg: dict, message: Message) -> dict:
    """Die Nachricht für den öffentlichen Alarm, samt Unterschrift als letzter Zeile des Textes."""
    try:
        key = sign.parse_key(cfg.get("key") or "")
    except sign.BadKey as err:
        raise DeliveryError(f"öffentlicher Alarm: {err}") from None
    # Titel und Text in der Form, die ntfy unverändert weitergibt. Sonst passt die Unterschrift nicht mehr.
    title = clip(sign.clean_title(message.title), 240)
    body = clip(sign.clean_body(message.body), PUBLIC_BODY_BYTES)
    click = (message.url or "").strip()
    if re.search(r"\s", click):
        click = ""
    created = message.created or now_utc()
    try:
        line = sign.seal(key, cfg["topic"], title, body, click, message.level, message.key, int(created.timestamp()))
    except ValueError as err:
        raise DeliveryError(f"öffentlicher Alarm: {err}") from None
    payload = {
        "topic": cfg["topic"],
        "title": title,
        "message": sign.attach(body, line),
        "priority": NTFY_PRIORITY.get(message.level, 3),
        "tags": NTFY_TAGS.get(message.level, []),
    }
    if click:
        payload["click"] = click
    if len(payload["message"].encode("utf-8")) > NTFY_MESSAGE_BYTES:
        raise DeliveryError("öffentlicher Alarm: Meldung ist mit Unterschrift zu lang")
    return payload


def send_public(cfg: dict, message: Message) -> None:
    """Öffentlicher Alarm: die Meldung mit Unterschrift an das öffentliche Thema."""
    payload = public_payload(cfg, message)
    headers = {"Authorization": f"Bearer {cfg['token']}"} if cfg.get("token") else None
    try:
        _, _, answer = http.post_json(cfg["server"].rstrip("/") + "/", payload, headers=headers)
    except HttpError as err:
        raise DeliveryError(f"öffentlicher Alarm: {err}") from None
    check_echo(answer, payload)


def check_echo(answer: bytes, payload: dict) -> None:
    """ntfy antwortet mit der Nachricht, wie es sie gespeichert hat.

    Weicht sie von der geschickten ab, gilt die Unterschrift nicht mehr.
    """
    try:
        echo = json.loads(answer.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return  # keine lesbare Antwort: kein Urteil
    if not isinstance(echo, dict) or "id" not in echo:
        return
    for name in ("title", "message", "click"):
        if (echo.get(name) or "") != (payload.get(name) or ""):
            raise Damaged(f"öffentlicher Alarm: ntfy hat das Feld {name} verändert, die Unterschrift gilt nicht mehr")


SENDERS = {"ntfy": send_ntfy, "email": send_email, PUBLIC: send_public}


def secrets(cfg: dict) -> list[str]:
    """Zugangsdaten und Adressen, die in keiner gespeicherten Fehlermeldung stehen dürfen."""
    ntfy, mail, public = cfg.get("ntfy") or {}, cfg.get("email") or {}, cfg.get(PUBLIC) or {}
    values = [ntfy.get("topic"), ntfy.get("token"), mail.get("host"), mail.get("user"), mail.get("password"),
              mail.get("sender"), public.get("key"), public.get("token")]
    values += str(public.get("key") or "").split(":")[2:]  # auch die geheime Zahl allein
    values += str(mail.get("recipient") or "").replace(";", ",").split(",")
    server = urlsplit(str(ntfy.get("server") or "")).netloc
    if server and server != "ntfy.sh":
        values.append(server)
    found = {str(value).strip() for value in values if value and len(str(value).strip()) >= 3}
    return sorted(found, key=len, reverse=True)


def scrub(text: str, hidden: list[str]) -> str:
    for value in hidden:
        text = text.replace(value, "***")
    return text


class Notifier:
    def __init__(self, cfg: dict, state: dict):
        self.cfg = cfg["notify"]
        self.tz = zone(cfg.get("timezone", "Europe/Vienna"))
        self.hidden = secrets(self.cfg)
        self.outbox: list = state.setdefault("outbox", [])
        self.sent: list = state.setdefault("sent", [])

    def channels(self, level: str | None = None, scope: str = "all") -> list[str]:
        found = []
        for name in SENDERS:
            cfg = self.cfg.get(name) or {}
            if not cfg.get("enabled") or level in (cfg.get("skip_levels") or []):
                continue
            if name == PUBLIC and scope != "all":
                continue  # Meldungen über den Betrieb gehen nur an den Betreiber
            found.append(name)
        return found

    def queue(self, messages: list[Message], now) -> None:
        known = {item["message"].get("key") for item in self.outbox} | {entry.get("key") for entry in self.sent}
        for message in messages:
            if message.key and message.key in known:
                continue
            known.add(message.key)
            self.outbox.append({"message": message.to_dict(),
                                "pending": self.channels(message.level, message.scope),
                                "done": [], "errors": {}, "queued_at": iso(now)})

    def flush(self, now) -> int:
        """Versucht alles im Postausgang zuzustellen. Liefert die Zahl der Zustellungen."""
        delivered, remaining = 0, []
        for item in self.outbox:
            message = Message.from_dict(item["message"])
            queued = parse_ts(item["queued_at"]) or now
            message.created = queued
            if now - queued > timedelta(minutes=20):
                when = queued.astimezone(self.tz).strftime("%d.%m. %H:%M")
                message.body = f"Verspätet zugestellt, erstellt am {when} Uhr.\n{message.body}"
            for channel in list(item["pending"]):
                if not self.cfg.get(channel, {}).get("enabled"):
                    item["pending"].remove(channel)  # Kanal wurde inzwischen abgeschaltet
                    continue
                try:
                    SENDERS[channel](self.cfg[channel], message)
                except Damaged as err:
                    # Nicht wiederholen: Jeder weitere Versuch käme ebenso verändert an. Die Meldung gilt für
                    # diesen Kanal als nicht zugestellt, die App holt sie über den Lagebericht nach.
                    item["pending"].remove(channel)
                    item.setdefault("lost", []).append(channel)
                    item["errors"][channel] = scrub(str(err), self.hidden)[:200]
                    log.error("Versand aufgegeben (%s): %s", message.title, item["errors"][channel])
                except DeliveryError as err:
                    item["errors"][channel] = scrub(str(err), self.hidden)[:200]
                    log.warning("Versand fehlgeschlagen (%s): %s", message.title, item["errors"][channel])
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
            # Mit Text: Der Lagebericht gibt die letzten Meldungen weiter (status.json, "notices"), damit die
            # App nachholen kann, was der Push nicht zugestellt hat.
            self.sent.insert(0, {"t": item["queued_at"], "title": item["message"]["title"],
                                 "body": item["message"]["body"],
                                 "level": item["message"]["level"], "key": item["message"]["key"],
                                 "scope": item["message"].get("scope") or "all",
                                 "channels": item["done"], "failed": item["pending"] + (item.get("lost") or [])})
        del self.sent[SENT_LOG:]
        self.outbox[:] = remaining
        return delivered

    def test(self, message: Message, channels: list[str] | None = None) -> dict:
        """Schickt eine Meldung sofort und liefert je Kanal 'ok' oder den Fehler.

        Ohne Angabe gehen Tests an die eigenen Kanäle des Betreibers und nie an den öffentlichen Alarm:
        Dort lesen fremde Menschen mit.
        """
        if channels is None:
            channels = [name for name in self.channels() if name != PUBLIC]
        message.created = message.created or now_utc()
        result = {}
        for channel in channels:
            try:
                SENDERS[channel](self.cfg[channel], message)
                result[channel] = "ok"
            except DeliveryError as err:
                result[channel] = scrub(str(err), self.hidden)
        return result
