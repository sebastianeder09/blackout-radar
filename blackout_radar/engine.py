"""Kern: verdichtet Signale zu Ereignissen und entscheidet, was gemeldet wird.

Begriffe
  Signal    eine Beobachtung einer Quelle für ein Gebiet
  Störung   (incident) alles, was in einem Gebiet gerade ausgefallen ist
  Ereignis  (event) zeitlich zusammenhängende Störungen in Nachbargebieten,
            daraus entstehen Verlauf (wo begonnen, wohin ausgebreitet) und Dauer

Melderegeln
  Vorrang-Gebiete (z. B. Oberösterreich): sofort, ohne Wartezeit.
  Rest der Welt: erst ab Mindestdauer und Mindestgröße, und nur wenn Strom
  als Ursache belegt ist (Lastdaten, Netzbetreiber, Cloudflare oder Medien).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import areas
from .model import Message, Signal, fmt_duration, fmt_pct, iso, parse_ts

ANOMALY_KINDS = {"internet_drop", "load_drop", "utility_outage", "confirmed_outage", "site_down", "frequency"}
SOURCE_LABELS = {
    "ioda": "Internet", "cloudflare": "Internet (Cloudflare)", "load": "Stromlast",
    "frequency": "Netzfrequenz", "utility": "Netzbetreiber", "sensor": "eigener Sensor",
}
CONFIRM_LABELS = {
    "load": "Lastdaten", "cloudflare": "Cloudflare Radar", "utility": "Netzbetreiber",
    "frequency": "Netzfrequenz", "sensor": "eigener Sensor",
}
CAUSE_LABELS = {
    "GOVERNMENT_DIRECTED": "staatlich angeordnete Abschaltung", "CABLE_CUT": "Kabelschaden",
    "CYBERATTACK": "Cyberangriff", "MAINTENANCE": "Wartung", "MISCONFIGURATION": "Fehlkonfiguration",
    "NETWORK_PROBLEM": "Netzwerkproblem", "TECHNICAL_PROBLEM": "technisches Problem",
    "SOFTWARE": "Softwarefehler", "BLOCKING": "Sperre", "DNS": "DNS-Problem",
    "MILITARY_ACTION": "Kriegshandlung", "FIRE": "Brand", "NATURAL_DISASTER": "Naturkatastrophe",
    "WEATHER": "Unwetter", "MECHANICAL": "mechanischer Schaden", "POWER_OUTAGE": "Stromausfall",
}
NON_POWER_CAUSES = {
    "GOVERNMENT_DIRECTED", "CABLE_CUT", "CYBERATTACK", "MAINTENANCE", "MISCONFIGURATION",
    "NETWORK_PROBLEM", "TECHNICAL_PROBLEM", "SOFTWARE", "BLOCKING", "DNS",
}
UPDATE_LABELS = {
    "spread": "Ausbreitung", "restore": "Wiederherstellung", "relapse": "erneut ausgefallen",
    "confirm": "Strom als Ursache bestätigt",
}


class Engine:
    def __init__(self, cfg: dict, state: dict):
        self.cfg = cfg
        self.f = cfg["filter"]
        self.p = cfg["priority"]
        self.state = state
        state.setdefault("events", {})
        state.setdefault("history", [])
        state.setdefault("notices", {"sent": [], "seen": {}})
        self.tz = ZoneInfo(cfg.get("timezone", "Europe/Vienna"))

    # ------------------------------------------------------------------ Ablauf
    def tick(self, signals: list[Signal], now: datetime) -> list[Message]:
        self._ingest(signals, now)
        messages = []
        for event in list(self.state["events"].values()):
            message = self._decide(event, now)
            if message:
                messages.append(message)
        messages += self._notices(signals, now)
        self._archive(now)
        return messages

    def active_areas(self) -> list[str]:
        """Gebiete mit laufender Störung, wichtigste zuerst (für die Mediensuche)."""
        found = []
        for event in self.state["events"].values():
            for area, inc in event["incidents"].items():
                if not inc["ended_at"] and event["kind"] == "outage":
                    found.append((0 if area in self.p["areas"] else 1, -(inc.get("peak") or 0), area))
        return [area for _, _, area in sorted(found)]

    # ------------------------------------------------------------- Aufnehmen
    def _ingest(self, signals, now):
        by_area = defaultdict(list)
        for sig in signals:
            if sig.kind in ANOMALY_KINDS:
                by_area[sig.area].append(sig)
        for area, sigs in by_area.items():
            active = [s for s in sigs if s.active]
            found = self._find_incident(area, now)
            if found is None:
                if not active:
                    continue
                event, inc = self._new_incident(area, active, now)
            else:
                event, inc = found
                if inc["ended_at"] and active:
                    inc["ended_at"] = None
                    inc["restoring_since"] = None
                    event["ended_at"] = None
                    event["end_notified"] = False
                    self._log(inc, now, "erneut ausgefallen")
            for sig in sigs:
                self._apply(inc, sig, now)
        for sig in signals:
            if sig.kind == "news":
                self._attach_news(sig, now)
            elif sig.kind == "annotation":
                self._attach_cause(sig, now)
        for event in self.state["events"].values():
            for inc in event["incidents"].values():
                if not inc["ended_at"]:
                    self._refresh(inc, now)
            self._refresh_event(event)

    def _find_incident(self, area, now):
        reopen = timedelta(hours=self.f["link_window_hours"])
        for event in self.state["events"].values():
            inc = event["incidents"].get(area)
            if inc is None:
                continue
            if not inc["ended_at"] or now - parse_ts(inc["ended_at"]) <= reopen:
                return event, inc
        return None

    def _new_incident(self, area, active, now):
        start = min([s.started_at or s.observed_at for s in active] + [now])
        kind = "frequency" if all(s.kind == "frequency" for s in active) else "outage"
        inc = {
            "area": area, "started_at": iso(start), "first_seen": iso(now), "last_active": iso(now),
            "ended_at": None, "severity": None, "peak": None, "sources": {},
            "confirmed_power": False, "confirmed_by": [], "cause": None, "not_power": False,
            "news": [], "timeline": [], "restoring_since": None,
        }
        event = self._find_event(area, kind, now)
        if event is None:
            event_id = f"{area}-{start.strftime('%Y%m%dT%H%M')}"
            while event_id in self.state["events"]:
                event_id += "x"
            event = {
                "id": event_id, "kind": kind, "started_at": iso(start), "ended_at": None, "incidents": {},
                "reported_at": None, "last_notified": None, "end_notified": False, "seq": 0,
                "notified": {"areas": [], "ended": [], "restoring": [], "confirmed": False},
            }
            self.state["events"][event_id] = event
        event["incidents"][area] = inc
        self._log(inc, start, "Beginn")
        return event, inc

    def _find_event(self, area, kind, now):
        window = timedelta(hours=self.f["link_window_hours"])
        best = None
        for event in self.state["events"].values():
            if event["kind"] != kind:
                continue
            for other, inc in event["incidents"].items():
                recent = not inc["ended_at"] or now - parse_ts(inc["ended_at"]) <= window
                if recent and areas.related(area, other):
                    if best is None or event["started_at"] < best["started_at"]:
                        best = event
                    break
        return best

    def _apply(self, inc, sig, now):
        entry = inc["sources"].setdefault(sig.source, {})
        entry.update({
            "kind": sig.kind, "active": bool(sig.active), "severity": sig.severity, "detail": sig.detail,
            "observed_at": iso(sig.observed_at), "seen": iso(now), "url": sig.url, "metrics": sig.metrics,
            "stale": False,
        })
        if sig.active:
            entry["ended_at"] = None
            if sig.started_at:
                entry["started_at"] = iso(sig.started_at)
                if sig.started_at < parse_ts(inc["started_at"]):
                    inc["started_at"] = iso(sig.started_at)
            if sig.confirmed_power:
                label = CONFIRM_LABELS.get(sig.source, sig.source)
                if label not in inc["confirmed_by"]:
                    inc["confirmed_by"].append(label)
                    if not inc["confirmed_power"]:
                        self._log(inc, now, f"Strom als Ursache bestätigt ({label})")
                inc["confirmed_power"] = True
        else:
            entry["ended_at"] = iso(sig.ended_at or sig.observed_at or now)

    def _refresh(self, inc, now):
        stale_after = timedelta(minutes=self.f["source_stale_minutes"])
        entries = list(inc["sources"].values())
        for entry in entries:
            if entry.get("active") and now - parse_ts(entry["seen"]) > stale_after:
                entry.update({"active": False, "stale": True, "ended_at": entry["seen"]})
        active = [e for e in entries if e.get("active")]
        if not active:
            ends = [parse_ts(e["ended_at"]) for e in entries if e.get("ended_at")]
            ended = max(ends) if ends else now
            inc["ended_at"] = iso(max(ended, parse_ts(inc["started_at"])))
            inc["severity"] = 0.0
            self._log(inc, parse_ts(inc["ended_at"]), "wieder versorgt")
            return
        inc["last_active"] = iso(now)
        severities = [e["severity"] for e in active if e.get("severity") is not None]
        if severities:
            inc["peak"] = max([inc["peak"] or 0.0] + severities)
        # Der frischeste Messwert bestimmt den aktuellen Stand. Hat die Quelle mit den
        # neuesten Daten schon Erholung gemeldet, läuft die Wiederherstellung.
        newest = max(entries, key=lambda e: e.get("observed_at") or e.get("seen") or "")
        if newest.get("active"):
            severity = newest.get("severity")
            if severity is None and severities:
                severity = max(severities)
        else:
            severity = 0.0
        inc["severity"] = severity
        peak = inc["peak"] or 0.0
        if severity is not None and peak >= 0.1 and severity <= 0.5 * peak and not inc["restoring_since"]:
            inc["restoring_since"] = iso(now)
            self._log(inc, now, "Wiederherstellung läuft")

    @staticmethod
    def _refresh_event(event):
        incidents = event["incidents"].values()
        event["started_at"] = min(i["started_at"] for i in incidents)
        if all(i["ended_at"] for i in incidents):
            event["ended_at"] = max(i["ended_at"] for i in incidents)
        else:
            event["ended_at"] = None

    def _attach_news(self, sig, now) -> bool:
        target = None
        for event in self.state["events"].values():
            if event["kind"] != "outage":
                continue
            for area, inc in event["incidents"].items():
                if inc["ended_at"] and now - parse_ts(inc["ended_at"]) > timedelta(hours=6):
                    continue
                if area == sig.area or areas.parent(area) == areas.parent(sig.area):
                    target = inc
                    break
            if target:
                break
        if target is None:
            return False
        url = sig.url or sig.detail
        if not any(item["url"] == url for item in target["news"]):
            target["news"].insert(0, {
                "title": sig.detail, "url": url, "domain": sig.metrics.get("domain", ""),
                "seen": iso(sig.observed_at), "power": bool(sig.metrics.get("power", True)),
            })
            del target["news"][12:]
        domains = {item["domain"] for item in target["news"] if item.get("power")}
        if len(domains) >= self.f["news_confirm_count"] and "Medien" not in target["confirmed_by"]:
            target["confirmed_by"].append("Medien")
            target["confirmed_power"] = True
            self._log(target, now, "Medien berichten über Stromausfall")
        sig.metrics["attached"] = True
        return True

    def _attach_cause(self, sig, now):
        cause = sig.metrics.get("cause")
        found = self._find_incident(sig.area, now)
        if not cause or found is None:
            return
        _, inc = found
        if inc.get("cause") != cause:
            inc["cause"] = cause
            inc["not_power"] = cause in NON_POWER_CAUSES and not inc["confirmed_power"]
            self._log(inc, now, f"Ursache laut Cloudflare: {CAUSE_LABELS.get(cause, cause)}")

    @staticmethod
    def _log(inc, when, text):
        inc["timeline"].append({"t": iso(when), "text": text})
        del inc["timeline"][:-30]

    # ------------------------------------------------------------ Entscheiden
    def impact(self, event) -> float:
        """Grobe Zahl betroffener Menschen: Spitzen-Anteil mal Einwohner."""
        incidents = event["incidents"]
        countries = {a for a in incidents if areas.parent(a) == a}
        total = 0.0
        for area, inc in incidents.items():
            if areas.parent(area) != area and areas.parent(area) in countries:
                continue  # Bundesland steckt schon im Staat
            total += (inc.get("peak") or 0.0) * areas.population(area)
        return total

    def is_priority(self, event) -> bool:
        for area, inc in event["incidents"].items():
            if area in self.p["areas"]:
                peak = inc.get("peak")
                if peak is None or peak >= self.p["min_severity"]:
                    return True
        return False

    def _load_only(self, event) -> bool:
        """Wahr, wenn nur die (verzögerten) Lastdaten anschlagen und kein zweites Signal.

        Lastdaten allein sind anfällig für Feiertage und unvollständige Meldungen und
        reichen deshalb nur bei einem massiven Einbruch in einem Vorrang-Gebiet.
        """
        incidents = event["incidents"].values()
        if any(set(i["sources"]) - {"load"} or "Medien" in i["confirmed_by"] for i in incidents):
            return False
        peak = max((i.get("peak") or 0.0) for i in incidents)
        return not (self.is_priority(event) and peak >= self.f["load_alone_min_drop"])

    def hold_reasons(self, event, now) -> list[str]:
        """Gründe, warum ein Ereignis (noch) nicht gemeldet wird. Leer heißt: melden."""
        if event["kind"] == "frequency":
            return []
        if self._load_only(event):
            return ["nur Lastdaten, kein zweites Signal"]
        if self.is_priority(event):
            return []
        reasons = []
        incidents = event["incidents"].values()
        duration = (parse_ts(event["ended_at"]) or now) - parse_ts(event["started_at"])
        minimum = self.f["min_duration_minutes"]
        if duration < timedelta(minutes=minimum):
            reasons.append(f"Dauer erst {fmt_duration(duration)}, Meldung ab {minimum} min")
        if self.impact(event) < self.f["min_affected_people"]:
            reasons.append("zu klein für eine Meldung")
        if self.f["require_power_confirmation"] and not any(i["confirmed_power"] for i in incidents):
            reasons.append("Strom als Ursache nicht bestätigt")
        return reasons

    def _update_reason(self, event, now, priority):
        incidents = event["incidents"]
        known = event["notified"]
        gap = now - parse_ts(event["last_notified"])
        interval = self.p["update_interval_minutes"] if priority else self.f["update_interval_minutes"]
        if event["kind"] == "frequency":
            return "periodic" if gap >= timedelta(minutes=interval) else None
        if any(area not in known["areas"] for area in incidents):
            return "spread"
        if any(not incidents[a]["ended_at"] for a in known["ended"] if a in incidents):
            return "relapse"
        if gap < timedelta(minutes=self.f["min_update_gap_minutes"]):
            return None
        for area, inc in incidents.items():
            if inc["ended_at"] and area not in known["ended"]:
                return "restore"
            if inc["restoring_since"] and area not in known["restoring"]:
                return "restore"
        if not known["confirmed"] and any(i["confirmed_power"] for i in incidents.values()):
            return "confirm"
        if gap >= timedelta(minutes=interval):
            return "periodic"
        return None

    def _decide(self, event, now):
        start = parse_ts(event["started_at"])
        end = parse_ts(event["ended_at"])
        active = end is None
        priority = self.is_priority(event)
        if not event["reported_at"]:
            if self.hold_reasons(event, now):
                return None
            event["reported_at"] = iso(now)
            phase = "start" if active else "retro"
            if not active:
                event["end_notified"] = True
        elif active:
            phase = self._update_reason(event, now, priority)
            if not phase:
                return None
        else:
            if event["end_notified"]:
                return None
            if now - end < timedelta(minutes=self.f["end_confirm_minutes"]):
                return None
            event["end_notified"] = True
            phase = "end"
        message = self._compose(event, phase, now, priority)
        incidents = event["incidents"]
        event["last_notified"] = iso(now)
        event["notified"] = {
            "areas": list(incidents),
            "ended": [a for a, i in incidents.items() if i["ended_at"]],
            "restoring": [a for a, i in incidents.items() if i["restoring_since"]],
            "confirmed": any(i["confirmed_power"] for i in incidents.values()),
        }
        return message

    # ------------------------------------------------------------ Formulieren
    def clock(self, when: datetime, now: datetime) -> str:
        local, ref = when.astimezone(self.tz), now.astimezone(self.tz)
        return local.strftime("%H:%M") if local.date() == ref.date() else local.strftime("%d.%m. %H:%M")

    @staticmethod
    def names(area_list) -> str:
        names = [areas.name(a) for a in area_list]
        return ", ".join(names[:3]) + (f" und {len(names) - 3} weitere" if len(names) > 3 else "")

    def classify(self, event) -> str:
        peak = max((i.get("peak") or 0.0) for i in event["incidents"].values())
        impact = self.impact(event)
        if peak >= 0.5 and impact >= self.f["min_affected_people"]:
            return "Blackout"
        if impact >= 5 * self.f["min_affected_people"]:
            return "Großer Stromausfall"
        return "Stromausfall"

    def headline(self, event) -> str:
        order = sorted(event["incidents"].values(), key=lambda i: i["started_at"])
        if event["kind"] == "frequency":
            return "Netzfrequenz-Alarm"
        names = self.names([i["area"] for i in order])
        if any(i["confirmed_power"] for i in order):
            return f"{self.classify(event)}: {names}"
        return f"Verdacht auf Stromausfall: {names}"

    def course_lines(self, event, now) -> list[str]:
        """Verlauf der Ausbreitung, Reihenfolge der Wiederversorgung und Beleglage."""
        order = sorted(event["incidents"].values(), key=lambda i: i["started_at"])
        lines = []
        if len(order) > 1:
            lines.append("Verlauf: " + " → ".join(
                f"{self.clock(parse_ts(i['started_at']), now)} {areas.name(i['area'])}" for i in order))
        restored = sorted((i for i in order if i["ended_at"]), key=lambda i: i["ended_at"])
        if restored and len(order) > 1:
            head = "Reihenfolge der Wiederversorgung: " if event["ended_at"] else "Zuerst wieder versorgt: "
            lines.append(head + " → ".join(
                f"{areas.name(i['area'])} {self.clock(parse_ts(i['ended_at']), now)}" for i in restored))
        if event["kind"] == "outage":
            lines.append(self.confirmation_line(order))
        return lines

    def area_line(self, inc, now) -> str:
        label = areas.name(inc["area"])
        if inc["ended_at"]:
            start, end = parse_ts(inc["started_at"]), parse_ts(inc["ended_at"])
            peak = f", Spitze {fmt_pct(inc['peak'])}" if inc.get("peak") else ""
            return f"{label}: wieder versorgt seit {self.clock(end, now)} (nach {fmt_duration(end - start)}{peak})"
        parts = []
        for source, entry in inc["sources"].items():
            name = SOURCE_LABELS.get(source, source)
            observed = parse_ts(entry.get("observed_at"))
            stand = f", Stand {self.clock(observed, now)}" if observed and now - observed > timedelta(minutes=20) else ""
            if entry.get("active"):
                if entry.get("detail"):
                    parts.append(entry["detail"] + stand)
                elif entry.get("severity") is not None:
                    parts.append(f"{name} {fmt_pct(entry['severity'])}{stand}")
                else:
                    parts.append(f"{name} gestört{stand}")
            elif entry.get("ended_at") and not entry.get("stale"):
                parts.append(f"{name} wieder normal seit {self.clock(parse_ts(entry['ended_at']), now)}")
        text = f"{label}: " + "; ".join(parts)
        if inc["restoring_since"]:
            text += " (Wiederherstellung läuft)"
        return text

    @staticmethod
    def confirmation_line(incidents) -> str:
        by = list(dict.fromkeys(label for inc in incidents for label in inc["confirmed_by"]))
        news = {item["url"] for inc in incidents for item in inc["news"]}
        causes = sorted({CAUSE_LABELS.get(i["cause"], i["cause"]) for i in incidents if i.get("cause")})
        if by:
            text = "Strom als Ursache bestätigt durch: " + ", ".join(by)
        else:
            text = "Strom als Ursache noch nicht bestätigt, bisher nur Indizien"
        if causes:
            text += ". Ursache laut Cloudflare: " + ", ".join(causes)
        if news:
            text += f". {len(news)} Medienbericht{'e' if len(news) != 1 else ''}"
        return text

    def _compose(self, event, phase, now, priority) -> Message:
        event["seq"] += 1
        key = f"{event['id']}:{phase}:{event['seq']}"
        url = self.cfg.get("status_url", "")
        order = sorted(event["incidents"].values(), key=lambda i: i["started_at"])
        start, end = parse_ts(event["started_at"]), parse_ts(event["ended_at"])
        duration = fmt_duration((end or now) - start)
        if event["kind"] == "frequency":
            return self._compose_frequency(order[0], phase, duration, key, url)
        names = self.names([i["area"] for i in order])
        kind = self.classify(event)
        if phase == "start":
            title = self.headline(event)
            level = "alarm" if priority else "warn"
        elif phase == "retro":
            title = f"{kind} nachträglich erkannt: {names} (Dauer {duration})"
            level = "warn" if priority else "info"
        elif phase == "end":
            title = f"Entwarnung: {names} (Dauer {duration})"
            level = "ok"
        else:
            label = UPDATE_LABELS.get(phase, f"dauert an, bisher {duration}")
            title = f"Update {names}: {label}"
            level = "warn" if priority and phase in ("spread", "relapse") else "info"
        lines = []
        if end:
            lines.append(f"Beginn {self.clock(start, now)}, Ende {self.clock(end, now)}, Dauer {duration}")
        else:
            lines.append(f"Seit {self.clock(start, now)} Uhr, Dauer bisher {duration}")
        lines += ["• " + self.area_line(inc, now) for inc in order]
        lines += self.course_lines(event, now)
        shown = set()
        for inc in order:
            for item in inc["news"]:
                if len(shown) < 2 and item["url"] not in shown:
                    shown.add(item["url"])
                    lines.append(f"» {item['title']} ({item['domain']})")
        if not end and kind == "Blackout" and any(areas.parent(i["area"]) == "AT" for i in order):
            lines.append("Richtwert APG: Netzwiederaufbau nach einem Blackout in 10 bis 24 Stunden.")
        return Message(title, "\n".join(lines), level, key, url)

    @staticmethod
    def _compose_frequency(inc, phase, duration, key, url) -> Message:
        entry = inc["sources"].get("frequency", {})
        metrics = entry.get("metrics") or {}
        worst, current = metrics.get("worst_hz"), metrics.get("current_hz")

        def hz(value):
            return f"{value:.2f}".replace(".", ",") if value is not None else "?"

        if phase in ("start", "retro"):
            title = f"Netzfrequenz-Alarm: {hz(worst)} Hz"
            level = "alarm" if worst is not None and abs(worst - 50.0) >= 0.5 else "warn"
        elif phase == "end":
            title = f"Netzfrequenz wieder normal: {hz(current)} Hz (Störung {duration})"
            level = "ok"
        else:
            title = f"Update Netzfrequenz: {hz(current)} Hz, Störung seit {duration}"
            level = "info"
        lines = [entry.get("detail") or f"Größte Abweichung {hz(worst)} Hz, aktuell {hz(current)} Hz"]
        if phase != "end":
            lines.append("Betrifft das ganze Verbundnetz Kontinentaleuropa, also auch Österreich.")
            lines.append("Eine so große Abweichung deutet auf eine schwere Störung hin (Kraftwerksausfall, "
                         "Netztrennung). Ein Stromausfall kann folgen, muss aber nicht.")
        return Message(title, "\n".join(lines), level, key, url)

    # ----------------------------------------------------- Medien-Hinweise
    def _notices(self, signals, now) -> list[Message]:
        """Medienberichte aus Vorrang-Gebieten, zu denen noch keine Störung läuft."""
        book = self.state["notices"]
        hour_ago = now - timedelta(hours=1)
        book["sent"] = [t for t in book["sent"] if parse_ts(t) > hour_ago]
        cutoff = now - timedelta(days=3)
        book["seen"] = {k: t for k, t in book["seen"].items() if parse_ts(t) > cutoff}
        messages = []
        for sig in signals:
            if sig.kind != "news" or sig.area not in self.p["areas"]:
                continue
            key = sig.metrics.get("key") or sig.url or sig.detail
            if key in book["seen"]:
                continue
            book["seen"][key] = iso(now)
            if sig.metrics.get("attached") or len(book["sent"]) >= self.p["max_notices_per_hour"]:
                continue
            book["sent"].append(iso(now))
            age = fmt_duration(now - sig.observed_at)
            source = sig.metrics.get("domain") or "Medienbericht"
            messages.append(Message(
                f"Medien melden Stromausfall: {areas.name(sig.area)}",
                f"{sig.detail}\n{source}, vor {age}. Noch kein Messsignal dazu vorhanden.",
                "warn", f"news:{key}", sig.url or self.cfg.get("status_url", "")))
        return messages

    # ------------------------------------------------------------ Aufräumen
    def _archive(self, now):
        keep = timedelta(hours=self.f["keep_ended_hours"])
        for event_id, event in list(self.state["events"].items()):
            end = parse_ts(event["ended_at"])
            if end is None:
                continue
            limit = keep if event["reported_at"] else timedelta(hours=6)
            if now - end < limit:
                continue
            incidents = event["incidents"]
            self.state["history"].append({
                "id": event_id, "kind": event["kind"], "started_at": event["started_at"],
                "ended_at": event["ended_at"], "reported": bool(event["reported_at"]),
                "areas": sorted(incidents, key=lambda a: incidents[a]["started_at"]),
                "peak": max((i.get("peak") or 0.0) for i in incidents.values()),
                "class": self.classify(event) if event["kind"] == "outage" else "Netzfrequenz",
                "confirmed": any(i["confirmed_power"] for i in incidents.values()),
                "impact": round(self.impact(event)),
            })
            del self.state["events"][event_id]
        cutoff = iso(now - timedelta(days=90))
        self.state["history"] = [h for h in self.state["history"] if h["ended_at"] >= cutoff]
