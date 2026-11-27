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
  "Europa" (Schlagzeilen, die nur den Kontinent nennen) zählt wie ein Vorrang-Gebiet,
  wenn das eigene Land in Europa liegt: sofort ab dem Anteil aus priority.min_severity.

Messwerte und Medien
  Messwerte (Stromlast, Netzbetreiber, Internet) bestimmen Beginn, Ende und
  Wiederherstellung. Medienberichte allein können einen Ausfall melden, aber
  weder Dauer noch Ende belegen. Deshalb gibt es dazu keine Entwarnung.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from . import areas
from .model import Message, Signal, fmt_duration, fmt_pct, iso, parse_ts, zone

ANOMALY_KINDS = {"internet_drop", "load_drop", "utility_outage", "confirmed_outage", "site_down", "frequency",
                 "media_outage"}
SOFT_KINDS = {"media_outage"}  # belegt einen Ausfall, aber weder Dauer noch Ende
SOURCE_LABELS = {
    "ioda": "Internet", "cloudflare": "Internet (Cloudflare)", "load": "Stromlast",
    "frequency": "Netzfrequenz", "utility": "Netzbetreiber", "media": "Medien",
}
CONFIRM_LABELS = {
    "load": "Lastdaten", "cloudflare": "Cloudflare Radar", "utility": "Netzbetreiber",
    "frequency": "Netzfrequenz", "media": "Medien",
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
    "confirm": "Strom als Ursache bestätigt", "measured": "Messwerte liegen vor",
}
CLASS_RANK = {"Stromausfall": 0, "Großer Stromausfall": 1, "Blackout": 2}
HEADLINE_PHASES = {"start", "retro", "escalate", "spread", "measured", "confirm"}  # hier stehen Schlagzeilen dabei
HINT_PHASES = {"start", "escalate", "measured"}
APG_HINT = ("Richtwert der APG aus Simulationen (2021): Nach einem Blackout läuft die Versorgung in Österreich "
            "im besten Fall nach etwa 10 Stunden wieder, längstens nach 20 bis 30 Stunden. Das ist keine Prognose.")


def _soft_only(inc) -> bool:
    """Wahr, wenn eine Störung nur auf Medienberichten beruht."""
    return all(entry.get("kind") in SOFT_KINDS for entry in inc["sources"].values())


class Engine:
    def __init__(self, cfg: dict, state: dict):
        self.cfg = cfg
        self.f = cfg["filter"]
        self.p = cfg["priority"]
        self.state = state
        state.setdefault("events", {})
        state.setdefault("history", [])
        self.tz = zone(cfg.get("timezone", "Europe/Vienna"))
        home = {areas.parent(area) for area in self.p["areas"]}
        self.home = home
        self.near = home | {other for country in home for other in areas.NEIGHBOURS.get(country, ())}
        # Vorrang-Gebiete, für die die Größenschwelle gilt (alles außer always_areas)
        self.wide = list(self.p["areas"])
        if home & areas.EUROPE:
            self.near.add(areas.EUROPE_WIDE)
            self.wide.append(areas.EUROPE_WIDE)

    # ------------------------------------------------------------------ Ablauf
    def tick(self, signals: list[Signal], now: datetime) -> list[Message]:
        self._ingest(signals, now)
        messages = []
        for event in list(self.state["events"].values()):
            message = self._decide(event, now)
            if message:
                messages.append(message)
        self._archive(now)
        return messages

    def active_areas(self) -> list[str]:
        """Gebiete mit laufendem Messsignal, zu denen noch Medienberichte fehlen (wichtigste zuerst)."""
        found = []
        for event in self.state["events"].values():
            if event["kind"] != "outage":
                continue
            for area, inc in event["incidents"].items():
                if inc["ended_at"] or "Medien" in inc["confirmed_by"] or _soft_only(inc):
                    continue
                found.append((0 if area in self.p["areas"] else 1, -(inc.get("peak") or 0), area))
        return [area for _, _, area in sorted(found)]

    # ------------------------------------------------------------- Aufnehmen
    def _ingest(self, signals, now):
        ignore = set(self.f.get("ignore_areas") or [])
        signals = [s for s in signals if s.area not in ignore and areas.parent(s.area) not in ignore]
        by_area = defaultdict(list)
        for sig in signals:
            if sig.kind in ANOMALY_KINDS:
                by_area[sig.area].append(sig)
        for area, sigs in by_area.items():
            hard = [s for s in sigs if s.active and s.kind not in SOFT_KINDS]
            soft = [s for s in sigs if s.active and s.kind in SOFT_KINDS]
            found = self._find_incident(area, now)
            if found is None:
                if not hard and not soft:
                    continue
                if not hard and self._covered(area, min(s.started_at or s.observed_at for s in soft)):
                    continue  # Nachhall einer Lage, die schon gemeldet und beendet ist
                event, inc = self._new_incident(area, hard or soft, now)
            else:
                event, inc = found
                # Medienberichte öffnen eine Störung nur wieder, wenn es dazu nie Messwerte gab.
                reopen = hard or (soft and _soft_only(inc) and not inc.get("closed_by_event"))
                if inc["ended_at"] and reopen:
                    inc.update({"ended_at": None, "restoring_since": None, "unclear": False})
                    event["ended_at"] = None
                    event["end_notified"] = False
                    if hard:
                        for other in event["incidents"].values():
                            other.pop("closed_by_event", None)
                    self._log(inc, now, "erneut ausgefallen" if hard else "neue Medienberichte")
            for sig in sigs:
                # Eine Entwarnung zählt nur von einer Quelle, die den Ausfall auch gemeldet hat.
                if sig.active or sig.source in inc["sources"]:
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
        """Laufende Störung des Gebiets, sonst die zuletzt beendete innerhalb des Zeitfensters."""
        reopen = timedelta(hours=self.f["link_window_hours"])
        best = None
        for event in self.state["events"].values():
            inc = event["incidents"].get(area)
            if inc is None:
                continue
            if not inc["ended_at"]:
                return event, inc
            if now - parse_ts(inc["ended_at"]) <= reopen and (best is None or inc["ended_at"] > best[1]["ended_at"]):
                best = (event, inc)
        return best

    def _covered(self, area, start) -> bool:
        """Wahr, wenn eine frühere Störung des Gebiets den Beginn dieser Medienlage schon abdeckt."""
        stamp = iso(start)
        for event in self.state["events"].values():
            inc = event["incidents"].get(area)
            if inc is not None and inc["ended_at"] and inc["ended_at"] >= stamp:
                return True
        return any(area in row["areas"] and row["ended_at"] >= stamp for row in self.state["history"])

    def _new_incident(self, area, active, now):
        start = min([s.started_at or s.observed_at for s in active] + [now])
        kind = "frequency" if all(s.kind == "frequency" for s in active) else "outage"
        inc = {
            "area": area, "started_at": iso(start), "first_seen": iso(now), "last_active": iso(now),
            "ended_at": None, "severity": None, "peak": None, "peak_measured": None, "sources": {},
            "confirmed_power": False, "confirmed_by": [], "cause": None, "not_power": False,
            "news": [], "timeline": [], "restoring_since": None, "unclear": False,
        }
        event = self._find_event(area, kind, now)
        if event is None:
            event_id = f"{area}-{start.strftime('%Y%m%dT%H%M')}"
            while event_id in self.state["events"]:
                event_id += "x"
            event = {
                "id": event_id, "kind": kind, "started_at": iso(start), "ended_at": None, "incidents": {},
                "reported_at": None, "last_notified": None, "end_notified": False, "seq": 0, "notice_times": [],
                "notified": {"areas": [], "ended": [], "restoring": [], "confirmed": False, "measured": True,
                             "class": None},
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
                    if sig.kind not in SOFT_KINDS:
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
        # Messwerte bestimmen Ende und Verlauf. Medienberichte halten eine Störung nur offen,
        # solange es zu ihr keine Messwerte gibt.
        measured = [e for e in entries if e.get("kind") not in SOFT_KINDS]
        deciding = measured or entries
        active = [e for e in deciding if e.get("active")]
        if not active:
            closed = [e for e in deciding if e.get("ended_at")]
            last = max(closed, key=lambda e: e["ended_at"], default=None)
            ended = parse_ts(last["ended_at"]) if last else now
            inc["ended_at"] = iso(max(ended, parse_ts(inc["started_at"])))
            inc["severity"] = 0.0
            # Verstummt eine Quelle, ohne Entwarnung zu geben, ist das Ende nicht belegt.
            inc["unclear"] = bool(measured) and bool(last and last.get("stale"))
            if not measured:
                text = "keine neuen Medienberichte"
            else:
                text = "keine aktuellen Daten mehr" if inc["unclear"] else "wieder versorgt"
            self._log(inc, parse_ts(inc["ended_at"]), text)
            return
        inc["last_active"] = iso(now)
        severities = [e["severity"] for e in entries if e.get("active") and e.get("severity") is not None]
        if severities:
            inc["peak"] = max([inc["peak"] or 0.0] + severities)
        if not measured:
            inc["severity"] = max(severities) if severities else None
            return
        # Der frischeste Messwert bestimmt den aktuellen Stand. Hat die Quelle mit den
        # neuesten Daten schon Erholung gemeldet, läuft die Wiederherstellung.
        newest = max(measured, key=lambda e: e.get("observed_at") or e.get("seen") or "")
        known = [e["severity"] for e in active if e.get("severity") is not None]
        if newest.get("active"):
            severity = newest.get("severity")
            if severity is None:
                severity = max(known) if known else None
        else:
            severity = 0.0
        inc["severity"] = severity
        if known:
            inc["peak_measured"] = max([inc.get("peak_measured") or 0.0] + known)
        top = inc.get("peak_measured") or 0.0
        if severity is not None and top >= 0.1 and severity <= 0.5 * top and not inc["restoring_since"]:
            inc["restoring_since"] = iso(now)
            self._log(inc, now, "Wiederherstellung läuft")

    @staticmethod
    def _refresh_event(event):
        """Ein Ereignis endet mit seinen Messwerten. Ohne Messwerte endet es, wenn die Berichte verstummen."""
        incidents = list(event["incidents"].values())
        event["started_at"] = min(i["started_at"] for i in incidents)
        measured = [i for i in incidents if not _soft_only(i)]
        deciding = measured or incidents
        if not all(i["ended_at"] for i in deciding):
            event["ended_at"] = None
            return
        end = max(i["ended_at"] for i in deciding)
        for inc in incidents:
            if not inc["ended_at"]:  # Medienlage ohne eigene Messwerte endet mit dem Ereignis
                inc.update({"ended_at": max(end, inc["started_at"]), "closed_by_event": True, "severity": None})
        event["ended_at"] = end

    def _attach_news(self, sig, now) -> bool:
        """Hängt einen Bericht an die passende Störung: erst dasselbe Gebiet, sonst derselbe Staat."""
        exact, same_state = None, None
        for event in self.state["events"].values():
            if event["kind"] != "outage":
                continue
            for area, inc in event["incidents"].items():
                if inc["ended_at"] and now - parse_ts(inc["ended_at"]) > timedelta(hours=6):
                    continue
                if area == sig.area:
                    exact = exact or inc
                elif areas.parent(area) == areas.parent(sig.area):
                    same_state = same_state or inc
        target = exact or same_state
        if target is None:
            return False
        domain = sig.metrics.get("domain", "")
        if not any(item["title"] == sig.detail and item["domain"] == domain for item in target["news"]):
            target["news"].append({
                "title": sig.detail, "url": sig.url, "domain": domain,
                "seen": iso(sig.observed_at), "power": bool(sig.metrics.get("power", True)),
            })
            target["news"].sort(key=lambda item: item["seen"] or "", reverse=True)
            del target["news"][12:]
        domains = {item["domain"] for item in target["news"] if item.get("power")}
        if len(domains) >= self.f["news_confirm_count"] and "Medien" not in target["confirmed_by"]:
            target["confirmed_by"].append("Medien")
            target["confirmed_power"] = True
            self._log(target, now, "Medien berichten über Stromausfall")
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
        total, europe, inside = 0.0, 0.0, 0.0
        for area, inc in incidents.items():
            if areas.parent(area) != area and areas.parent(area) in countries:
                continue  # Bundesland steckt schon im Staat
            people = (inc.get("peak") or 0.0) * areas.population(area)
            if area == areas.EUROPE_WIDE:
                europe = people
            elif areas.EUROPE_WIDE in incidents and areas.parent(area) in areas.EUROPE:
                inside += people  # steckt schon in "Europa": es zählt der größere der beiden Werte
            else:
                total += people
        return total + max(europe, inside)

    def _notable(self, area, inc) -> bool:
        """Wahr, wenn ein Gebiet für sich allein eine Meldung wert ist."""
        peak = inc.get("peak") or 0.0
        if area in (self.p.get("always_areas") or []):
            return True
        if area in self.wide and peak >= self.p["min_severity"]:
            return True
        return peak * areas.population(area) >= self.f["min_affected_people"]

    def is_priority(self, event) -> bool:
        """Vorrang: ein Gebiet, in dem jedes Signal zählt, oder ein großer Ausfall in einem Vorrang-Gebiet."""
        always = self.p.get("always_areas") or []
        return any(area in always or (area in self.wide and (inc.get("peak") or 0.0) >= self.p["min_severity"])
                   for area, inc in event["incidents"].items())

    def urgent(self, event) -> bool:
        """Großer Ausfall in einem Vorrang-Gebiet: höchste Dringlichkeit und kurze Abstände."""
        return any(area in self.wide and (inc.get("peak") or 0.0) >= self.p["min_severity"]
                   for area, inc in event["incidents"].items())

    def is_near(self, event) -> bool:
        """Wahr, wenn das eigene Land oder ein Nachbarland betroffen ist."""
        return any(areas.parent(area) in self.near for area in event["incidents"])

    @staticmethod
    def media_only(event) -> bool:
        return all(_soft_only(inc) for inc in event["incidents"].values())

    def _load_only(self, event) -> bool:
        """Wahr, wenn nur die (verzögerten) Lastdaten anschlagen und das für eine Meldung nicht reicht.

        Lastdaten allein sind anfällig für Feiertage und unvollständige Meldungen. Sie reichen
        deshalb nur bei einem massiven, anhaltenden Einbruch in einem Vorrang-Gebiet. Einzelne
        Schlagzeilen aus demselben Land ändern daran nichts (irgendwo fällt immer der Strom aus),
        es braucht eine zweite Quelle oder eine Medienlage, die für sich allein zählt.
        """
        incidents = list(event["incidents"].values())
        if any(set(i["sources"]) - {"load"} for i in incidents):
            return False
        minimum = timedelta(minutes=self.f["load_alone_min_minutes"])
        for inc in incidents:
            entry = inc["sources"].get("load") or {}
            start, seen = parse_ts(entry.get("started_at")), parse_ts(entry.get("observed_at"))
            lasting = start is not None and seen is not None and seen - start >= minimum
            if inc["area"] in self.p["areas"] and (inc.get("peak") or 0.0) >= self.f["load_alone_min_drop"] and lasting:
                return False
        return True

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
            known = any(i.get("peak") for i in incidents)
            reasons.append("zu klein für eine Meldung" if known else "Größe unbekannt")
        if self.f["require_power_confirmation"] and not any(i["confirmed_power"] for i in incidents):
            reasons.append("Strom als Ursache nicht bestätigt")
        return reasons

    def _update_reason(self, event, now):
        incidents = event["incidents"]
        known = event["notified"]
        gap = now - parse_ts(event["last_notified"])
        minutes = self.p["update_interval_minutes"] if self.urgent(event) else self.f["update_interval_minutes"]
        interval = timedelta(minutes=minutes)
        if event["kind"] == "frequency":
            return "periodic" if gap >= interval else None
        if CLASS_RANK[self.classify(event)] > CLASS_RANK.get(known.get("class"), 0):
            return "escalate"
        if not known.get("measured", True) and not self.media_only(event):
            return "measured"
        if any(area not in known["areas"] and self._notable(area, inc) for area, inc in incidents.items()):
            return "spread"
        if self.media_only(event):
            return None  # Medien allein belegen weder Fortdauer noch Wiederherstellung
        if any(not incidents[a]["ended_at"] for a in known["ended"] if a in incidents):
            return "relapse"
        if gap < timedelta(minutes=self.f["min_update_gap_minutes"]):
            return None
        for area, inc in incidents.items():
            if _soft_only(inc) or inc.get("unclear"):
                continue
            if inc["ended_at"] and area not in known["ended"]:
                return "restore"
            if inc["restoring_since"] and area not in known["restoring"]:
                return "restore"
        if not known["confirmed"] and any(i["confirmed_power"] for i in incidents.values()):
            return "confirm"
        return "periodic" if gap >= interval else None

    def _capped(self, event, now) -> bool:
        """Begrenzt die Zahl der Meldungen je Ereignis und Stunde (Schutz vor flatternden Signalen)."""
        recent = [t for t in event.get("notice_times") or [] if now - parse_ts(t) < timedelta(hours=1)]
        event["notice_times"] = recent
        return len(recent) >= self.f["max_notices_per_hour"]

    def _decide(self, event, now):
        end = parse_ts(event["ended_at"])
        first = not event["reported_at"]
        if first:
            if self.hold_reasons(event, now):
                return None
            phase = "retro" if end else "start"
        elif end is None:
            phase = self._update_reason(event, now)
            if not phase:
                return None
        else:
            if event["end_notified"] or now - end < timedelta(minutes=self.f["end_confirm_minutes"]):
                return None
            if self.media_only(event):
                event["end_notified"] = True
                return None  # ohne Messwerte gibt es keine belegbare Entwarnung
            phase = "end"
        if not first and self._capped(event, now):
            return None
        if first:
            event["reported_at"] = iso(now)
        if end:
            event["end_notified"] = True
        message = self._compose(event, phase, now)
        incidents = event["incidents"]
        event["last_notified"] = iso(now)
        event["notice_times"] = (event.get("notice_times") or []) + [iso(now)]
        event["notified"] = {
            "areas": list(incidents),
            "ended": [a for a, i in incidents.items() if i["ended_at"] and not _soft_only(i)],
            "restoring": [a for a, i in incidents.items() if i["restoring_since"]],
            "confirmed": any(i["confirmed_power"] for i in incidents.values()),
            "measured": not self.media_only(event),
            "class": self.classify(event) if event["kind"] == "outage" else None,
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

    def _ranked(self, event) -> list:
        """Störungen für die Überschrift: Vorrang-Gebiete zuerst, dann nach Beginn."""
        rank = {area: index for index, area in enumerate(self.p["areas"])}
        return sorted(event["incidents"].values(),
                      key=lambda i: (rank.get(i["area"], len(rank)), i["started_at"], i["area"]))

    def classify(self, event) -> str:
        peak = max((i.get("peak") or 0.0) for i in event["incidents"].values())
        impact = self.impact(event)
        if peak >= 0.5 and impact >= self.f["min_affected_people"]:
            return "Blackout"
        if impact >= 5 * self.f["min_affected_people"]:
            return "Großer Stromausfall"
        return "Stromausfall"

    def headline(self, event) -> str:
        if event["kind"] == "frequency":
            return "Netzfrequenz-Alarm"
        ranked = self._ranked(event)
        names = self.names([i["area"] for i in ranked])
        if self.media_only(event):
            return f"{self.classify(event)}: {names} (laut Medien)"
        if any(i["confirmed_power"] for i in ranked):
            return f"{self.classify(event)}: {names}"
        return f"Verdacht auf Stromausfall: {names}"

    def course_lines(self, event, now) -> list[str]:
        """Verlauf der Ausbreitung, Reihenfolge der Wiederversorgung und Beleglage."""
        order = sorted(event["incidents"].values(), key=lambda i: (i["started_at"], i["area"]))
        lines = []
        if len(order) > 1:
            lines.append("Verlauf: " + " → ".join(
                f"{self.clock(parse_ts(i['started_at']), now)} {areas.name(i['area'])}"
                + (" (Medienbericht)" if _soft_only(i) and not self.media_only(event) else "") for i in order))
        restored = sorted((i for i in order if i["ended_at"] and not _soft_only(i) and not i.get("unclear")),
                          key=lambda i: i["ended_at"])
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
            if inc.get("closed_by_event"):
                return f"{label}: nur Medienberichte, keine eigenen Messwerte"
            if _soft_only(inc):
                return f"{label}: keine neuen Medienberichte seit {self.clock(end, now)}"
            if inc.get("unclear"):
                return f"{label}: keine aktuellen Daten seit {self.clock(end, now)}, Ende nicht belegt"
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
            elif entry.get("ended_at") and not entry.get("stale") and entry.get("kind") not in SOFT_KINDS:
                parts.append(f"{name} wieder normal seit {self.clock(parse_ts(entry['ended_at']), now)}")
        text = f"{label}: " + ("; ".join(parts) or "kein aktuelles Signal")
        if inc["restoring_since"]:
            text += " (Wiederherstellung läuft)"
        return text

    @staticmethod
    def confirmation_line(incidents) -> str:
        by = list(dict.fromkeys(label for inc in incidents for label in inc["confirmed_by"]))
        news = {(item["domain"], item["title"]) for inc in incidents for item in inc["news"]}
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

    @staticmethod
    def _data_time(event):
        """Zeitpunkt der neuesten Messwerte zu den noch laufenden Störungen (None ohne Messwerte)."""
        times = [entry.get("observed_at") for inc in event["incidents"].values() if not inc["ended_at"]
                 for entry in inc["sources"].values() if entry.get("active") and entry.get("kind") not in SOFT_KINDS]
        return parse_ts(max(times)) if any(times) else None

    @staticmethod
    def _headlines(incidents, limit: int = 2) -> list[str]:
        lines, shown = [], set()
        for inc in incidents:
            for item in inc["news"]:
                key = (item["domain"], item["title"])
                if len(shown) < limit and key not in shown:
                    shown.add(key)
                    lines.append(f"» {item['title']} ({item['domain']})")
        return lines

    def _compose(self, event, phase, now) -> Message:
        event["seq"] += 1
        key = f"{event['id']}:{phase}:{event['seq']}"
        url = self.cfg.get("status_url", "")
        order = sorted(event["incidents"].values(), key=lambda i: (i["started_at"], i["area"]))
        ranked = self._ranked(event)
        start, end = parse_ts(event["started_at"]), parse_ts(event["ended_at"])
        duration = fmt_duration((end or now) - start)
        if event["kind"] == "frequency":
            return self._compose_frequency(order[0], phase, duration, key, url)
        names = self.names([i["area"] for i in ranked])
        kind = self.classify(event)
        media_only = self.media_only(event)
        priority, urgent = self.is_priority(event), self.urgent(event)
        calm = "warn" if priority or self.is_near(event) else "info"  # Dringlichkeit ohne Alarm
        unclear = any(i.get("unclear") for i in order)
        stand = self._data_time(event)
        lagging = stand is not None and not end and now - stand > timedelta(minutes=30) and stand > start
        if phase == "start":
            title = self.headline(event)
            level = "alarm" if urgent else calm
        elif phase == "retro":
            title = f"{kind} nachträglich erkannt: {names}"
            title += " (laut Medien)" if media_only else f" (Dauer {duration})"
            level = "warn" if priority else "info"
        elif phase == "end" and unclear:
            title = f"Keine Daten mehr: {names}"
            level = "info"
        elif phase == "end":
            states = {areas.parent(i["area"]) for i in order if not _soft_only(i)}
            cleared = [i["area"] for i in ranked if not _soft_only(i) or areas.parent(i["area"]) in states]
            title = f"Entwarnung: {self.names(cleared)} (Dauer {duration})"
            level = "ok"
        elif phase == "escalate":
            title = f"Update {names}: jetzt als {kind} eingestuft"
            level = "alarm" if urgent else calm
        else:
            label = UPDATE_LABELS.get(phase)
            if not label:  # Zwischenstand
                label = f"dauert an, Stand {self.clock(stand, now)}" if lagging else f"dauert an, bisher {duration}"
            title = f"Update {names}: {label}"
            level = "warn" if priority and phase in ("spread", "relapse", "measured") else "info"
        lines = []
        headlines = self._headlines(ranked) if phase in HEADLINE_PHASES else []
        if media_only:
            lines += headlines
            lines.append(f"Erster Medienbericht um {self.clock(start, now)} Uhr. "
                         "Dauer und Ende lassen sich aus Medienberichten nicht ablesen.")
        elif end:
            lines.append(f"Beginn {self.clock(start, now)}, Ende {self.clock(end, now)}, Dauer {duration}")
        elif lagging:
            lines.append(f"Seit {self.clock(start, now)} Uhr. Neueste Messwerte von {self.clock(stand, now)} Uhr, "
                         f"bis dahin {fmt_duration(stand - start)} ohne Strom. Die Daten kommen verzögert.")
        else:
            lines.append(f"Seit {self.clock(start, now)} Uhr, Dauer bisher {duration}")
        if phase == "end" and unclear:
            lines.append("Die Datenquellen liefern zu diesem Ereignis keine Werte mehr. Das ist keine Entwarnung.")
        lines += ["• " + self.area_line(inc, now) for inc in ranked]
        lines += self.course_lines(event, now)
        if not media_only:
            lines += headlines
        austria = any(areas.parent(i["area"]) == "AT" for i in order) or (
            "AT" in self.home and areas.EUROPE_WIDE in event["incidents"])
        if phase in HINT_PHASES and kind == "Blackout" and austria:
            lines.append(APG_HINT)
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

    # ------------------------------------------------------------ Aufräumen
    def _archive(self, now):
        """Verschiebt beendete Ereignisse ins Archiv. Nur gemeldete Ereignisse zählen für die Statistik."""
        keep = timedelta(hours=self.f["keep_ended_hours"])
        for event_id, event in list(self.state["events"].items()):
            end = parse_ts(event["ended_at"])
            if end is None:
                continue
            limit = keep if event["reported_at"] else timedelta(hours=6)
            if now - end < limit:
                continue
            incidents = event["incidents"]
            if event["reported_at"]:
                self.state["history"].append({
                    "id": event_id, "kind": event["kind"], "started_at": event["started_at"],
                    "ended_at": event["ended_at"], "reported": True,
                    "areas": sorted(incidents, key=lambda a: incidents[a]["started_at"]),
                    "peak": max((i.get("peak") or 0.0) for i in incidents.values()),
                    "class": self.classify(event) if event["kind"] == "outage" else "Netzfrequenz",
                    "confirmed": any(i["confirmed_power"] for i in incidents.values()),
                    "impact": round(self.impact(event)),
                    "media_only": self.media_only(event),
                })
            del self.state["events"][event_id]
        cutoff = iso(now - timedelta(days=90))
        self.state["history"] = [h for h in self.state["history"] if h["ended_at"] >= cutoff]
