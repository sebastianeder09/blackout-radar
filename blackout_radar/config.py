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
        "load_alone_min_drop": 0.40,      # Lastdaten ohne zweites Signal zählen nur bei so großem Einbruch
        "load_alone_min_minutes": 30,     # und nur, wenn er in den Daten mindestens so lange anhält
        "max_notices_per_hour": 4,        # höchstens so viele Meldungen je Ereignis und Stunde
        "source_stale_minutes": 240,      # Signal ohne Auffrischung verfällt nach dieser Zeit
        "news_confirm_count": 2,          # so viele Medien müssen Stromausfall melden
        "keep_ended_hours": 48,
        "ignore_areas": [],               # Gebiete, die nie gemeldet werden, z. B. ["UA"]
    },
    "priority": {
        "areas": ["AT-4", "AT"],          # hier sofort melden, ohne 30-Minuten-Regel
        "always_areas": ["AT-4"],         # hier zählt jedes Signal, auch ein kleiner Ausfall
        "min_severity": 0.15,             # übrige Vorrang-Gebiete: erst ab diesem betroffenen Anteil
        "update_interval_minutes": 60,    # Zwischenstand bei einem großen Ausfall im Vorrang-Gebiet
    },
    "daily_summary": {"enabled": True, "time": "07:00"},
    "health": {"alert_after_hours": 3, "gap_minutes": 90},
    "notify": {
        "ntfy": {"enabled": True, "server": "https://ntfy.sh", "topic": "", "token": "", "skip_levels": []},
        "email": {"enabled": False, "host": "", "port": 587, "user": "", "password": "",
                  "sender": "", "recipient": "", "skip_levels": ["daily"]},
    },
    "sources": {
        "frequency": {
            "enabled": True,
            "providers": ["energy_charts", "netzfrequenzmessung"],
            "alarm_mhz": 200, "clear_mhz": 100, "calm_minutes": 5,
            "window_minutes": 12, "catchup_minutes": 120, "max_age_minutes": 10,
            "energy_charts_url": "https://api.energy-charts.info", "energy_charts_region": "DE-Freiburg",
            "nfm_url": "https://dat.netzfrequenzmessung.de:9080/frequenz.xml",
        },
        "load": {
            "enabled": True,
            "base_url": "https://api.energy-charts.info",
            "countries": ["at", "de", "cz", "sk", "hu", "si", "it", "ch", "fr", "es", "pt", "pl"],
            "drop_threshold": 0.20, "recover_threshold": 0.08, "confirm_points": 2,
            "poll_minutes_primary": 15, "poll_minutes": 45, "max_requests_per_run": 2,
            "max_data_age_hours": 6,
        },
        "ioda": {
            "enabled": False,  # Abfrage noch nicht gegen echte Daten geprüft (Dienst antwortete nicht)
            "base_url": "https://api.ioda.inetintel.cc.gatech.edu/v2",
            "watch_countries": ["AT"],        # hier wird das Rohsignal direkt gemessen
            "watch_regions": {"AT-4": ["Oberösterreich", "Upper Austria", "Oberosterreich"]},
            "drop_threshold": 0.20, "region_drop_threshold": 0.30,
            "alert_min_drop": {"ping-slash24": 0.20, "bgp": 0.10, "gtr": 0.30, "merit-nt": 0.60},
        },
        "cloudflare": {"enabled": False, "token": "",
                       "base_url": "https://api.cloudflare.com/client/v4/radar"},
        "utility": {  # Störmeldungen der LINZ NETZ (öffentliche Seite), zählt für Oberösterreich
            "enabled": True,
            "url": "https://www.linznetz.at/portal/de/home/online_services/aktuelle_stoermeldungen",
        },
        "news": {
            "enabled": True,
            "max_age_minutes": 180,        # ältere Berichte lösen nichts mehr aus
            "quiet_hours": 6,              # so lange ohne neuen Erstbericht, dann gilt die Lage als beendet
            "priority_min_sources": 1,     # Gebiet mit eigener Suche: schon ein Medium reicht (je Suche änderbar)
            "world_min_sources": 3,        # sonst müssen so viele verschiedene Medien berichten
            "big_sources": 6,              # ab so vielen Medien gilt ein Ausfall ohne Zahlenangabe als groß
            "world_per_run": 2,            # so viele Welt-Suchen je Lauf (reihum)
            "max_areas_per_run": 2,        # so viele Nachweis-Suchen je Lauf
            "priority_queries": [
                {"area": "AT-4", "hl": "de", "gl": "AT",
                 "q": "(Stromausfall OR Stromstörung OR \"ohne Strom\") "
                      "(Oberösterreich OR Mühlviertel OR Linz OR Wels OR Steyr OR Freistadt OR Perg)"},
                {"area": "AT", "hl": "de", "gl": "AT", "min_sources": 2,
                 "q": "(Blackout OR Stromausfall OR \"ohne Strom\") Österreich"},
            ],
            "world_queries": [
                {"hl": "en-US", "gl": "US", "ceid": "US:en",
                 "q": "\"nationwide blackout\" OR \"massive blackout\" OR \"massive power outage\" OR "
                      "\"major power outage\" OR \"widespread power outage\" OR \"grid collapse\" OR "
                      "\"millions without power\""},
                {"hl": "es-419", "gl": "US", "ceid": "US:es-419",
                 "q": "\"apagón masivo\" OR \"apagón general\" OR \"apagón nacional\" OR \"gran apagón\" OR "
                      "\"colapso del sistema eléctrico\""},
                {"hl": "de", "gl": "DE", "ceid": "DE:de",
                 "q": "\"großflächiger Stromausfall\" OR \"flächendeckender Stromausfall\" OR "
                      "\"massiver Stromausfall\" OR \"landesweiter Stromausfall\" OR \"Millionen ohne Strom\""},
                {"hl": "fr", "gl": "FR", "ceid": "FR:fr",
                 "q": "\"panne de courant géante\" OR \"panne d'électricité géante\" OR "
                      "\"coupure de courant massive\" OR \"panne d'électricité massive\""},
                {"hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419",
                 "q": "\"apagão nacional\" OR \"apagão geral\" OR \"grande apagão\" OR \"milhões sem energia\""},
                {"hl": "it", "gl": "IT", "ceid": "IT:it",
                 "q": "\"maxi blackout\" OR \"blackout elettrico\" OR \"milioni senza corrente\""},
            ],
        },
    },
}

# Umgebungsvariable -> Pfad in der Konfiguration
ENV_MAP = {
    "NTFY_TOPIC": ("notify", "ntfy", "topic"),
    "NTFY_SERVER": ("notify", "ntfy", "server"),
    "NTFY_TOKEN": ("notify", "ntfy", "token"),
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
        value = value.strip()
        if var == "SMTP_PORT":
            if not value.isdigit():
                continue  # Tippfehler: es bleibt beim Standard-Port
            value = int(value)
        node[keys[-1]] = value
    # Kanäle schalten sich ein, sobald ihre Zugangsdaten vorhanden sind
    notify = cfg["notify"]
    notify["ntfy"]["enabled"] = bool(notify["ntfy"]["enabled"] and notify["ntfy"]["topic"])
    mail = notify["email"]
    mail["enabled"] = bool(mail["host"] and mail["recipient"])
    if not mail["sender"]:
        mail["sender"] = mail["user"] or mail["recipient"]
    cfg["sources"]["cloudflare"]["enabled"] = bool(cfg["sources"]["cloudflare"]["token"])
    return cfg
