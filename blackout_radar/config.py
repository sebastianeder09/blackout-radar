"""Konfiguration: Standardwerte, TOML-Datei und Umgebungsvariablen (für Zugangsdaten)."""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "timezone": "Europe/Vienna",
    "status_url": "",
    "filter": {
        "min_duration_minutes": 30,       # erst melden, wenn der Ausfall so lange dauert
        "min_affected_people": 500_000,   # und grob so viele Menschen betrifft (Anteil x Einwohner)
        "require_power_confirmation": True,  # weltweit nur melden, wenn Strom als Ursache belegt ist
        "update_interval_minutes": 120,   # Zwischenstand bei laufenden Ereignissen
        "min_update_gap_minutes": 10,
        "end_confirm_minutes": 15,        # so lange muss es ruhig sein, bevor Entwarnung kommt
        "link_window_hours": 3,           # Ausfälle in Nachbarländern in diesem Abstand gelten als ein Ereignis
        "source_stale_minutes": 240,      # Signal ohne Auffrischung verfällt nach dieser Zeit
        "news_confirm_count": 2,          # so viele Medien müssen Stromausfall melden
        "keep_ended_hours": 48,
    },
    "priority": {
        "areas": ["AT-4", "AT"],          # hier sofort melden, ohne 30-Minuten-Regel
        "min_severity": 0.15,
        "update_interval_minutes": 30,
        "max_notices_per_hour": 3,
    },
    "daily_summary": {"enabled": True, "time": "07:00"},
    "health": {"alert_after_hours": 6},
    "notify": {
        "ntfy": {"enabled": True, "server": "https://ntfy.sh", "topic": "", "token": ""},
        "pushover": {"enabled": False, "token": "", "user": ""},
        "email": {"enabled": False, "host": "", "port": 587, "user": "", "password": "",
                  "sender": "", "recipient": ""},
    },
    "sources": {
        "frequency": {
            "enabled": True,
            "providers": ["energy_charts", "netzfrequenzmessung"],
            "alarm_mhz": 200, "clear_mhz": 100, "window_minutes": 12, "max_age_minutes": 10,
            "energy_charts_url": "https://api.energy-charts.info",
            "nfm_url": "https://dat.netzfrequenzmessung.de:9080/frequenz.xml",
        },
        "load": {
            "enabled": True,
            "base_url": "https://api.energy-charts.info",
            "countries": ["at", "de", "cz", "sk", "hu", "si", "it", "ch"],
            "drop_threshold": 0.20, "recover_threshold": 0.08, "confirm_points": 2,
            "poll_minutes_primary": 15, "poll_minutes": 45, "max_requests_per_run": 2,
            "max_data_age_hours": 6,
        },
        "ioda": {
            "enabled": True,
            "base_url": "https://api.ioda.inetintel.cc.gatech.edu/v2",
            "watch_countries": ["AT"],        # hier wird das Rohsignal direkt gemessen
            "watch_regions": {"AT-4": ["Oberösterreich", "Upper Austria", "Oberosterreich"]},
            "drop_threshold": 0.20, "region_drop_threshold": 0.30,
            "alert_min_drop": {"ping-slash24": 0.20, "bgp": 0.10, "gtr": 0.30, "merit-nt": 0.60},
        },
        "cloudflare": {"enabled": False, "token": "",
                       "base_url": "https://api.cloudflare.com/client/v4/radar"},
        "news": {
            "enabled": True,
            "gdelt_url": "https://api.gdeltproject.org/api/v2/doc/doc",
            "max_areas_per_run": 3, "max_age_minutes": 180,
            "priority_queries": [
                {"area": "AT-4", "hl": "de", "gl": "AT",
                 "q": "Stromausfall (Oberösterreich OR Mühlviertel OR Linz OR Wels OR Steyr OR Freistadt OR Tragwein)"},
            ],
        },
    },
}

# Umgebungsvariable -> Pfad in der Konfiguration
ENV_MAP = {
    "NTFY_TOPIC": ("notify", "ntfy", "topic"),
    "NTFY_SERVER": ("notify", "ntfy", "server"),
    "NTFY_TOKEN": ("notify", "ntfy", "token"),
    "PUSHOVER_TOKEN": ("notify", "pushover", "token"),
    "PUSHOVER_USER": ("notify", "pushover", "user"),
    "SMTP_HOST": ("notify", "email", "host"),
    "SMTP_PORT": ("notify", "email", "port"),
    "SMTP_USER": ("notify", "email", "user"),
    "SMTP_PASSWORD": ("notify", "email", "password"),
    "MAIL_FROM": ("notify", "email", "sender"),
    "MAIL_TO": ("notify", "email", "recipient"),
    "CLOUDFLARE_API_TOKEN": ("sources", "cloudflare", "token"),
    "STATUS_URL": ("status_url",),
}


def _merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load(path: str | os.PathLike | None = None, env: dict | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path and Path(path).exists():
        with open(path, "rb") as handle:
            _merge(cfg, tomllib.load(handle))
    env = os.environ if env is None else env
    for var, keys in ENV_MAP.items():
        value = env.get(var)
        if not value:
            continue
        node = cfg
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = int(value) if var == "SMTP_PORT" else value.strip()
    # Kanäle schalten sich ein, sobald ihre Zugangsdaten vorhanden sind
    notify = cfg["notify"]
    notify["ntfy"]["enabled"] = bool(notify["ntfy"]["enabled"] and notify["ntfy"]["topic"])
    notify["pushover"]["enabled"] = bool(notify["pushover"]["token"] and notify["pushover"]["user"])
    mail = notify["email"]
    mail["enabled"] = bool(mail["host"] and mail["recipient"])
    if not mail["sender"]:
        mail["sender"] = mail["user"] or mail["recipient"]
    cfg["sources"]["cloudflare"]["enabled"] = bool(cfg["sources"]["cloudflare"]["token"])
    return cfg
