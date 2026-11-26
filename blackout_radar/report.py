"""Lagebericht: der Zustand als lesbarer Text (Markdown), als JSON und als tägliche Zusammenfassung."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

from . import areas
from .collectors import frequency
from .engine import Engine
from .model import Message, fmt_duration, fmt_pct, iso, parse_ts
from .model import fmt_number as number
from .model import fmt_people as people

SOURCE_NAMES = {
    "frequency": "Netzfrequenz",
    "load": "Stromlast (Energy-Charts, Daten von ENTSO-E)",
    "ioda": "Internet-Ausfälle (IODA)",
    "cloudflare": "Cloudflare Radar",
    "utility": "Störmeldungen LINZ NETZ",
    "news": "Medien (Google News)",
}
SOURCE_SHORT = {"frequency": "Netzfrequenz", "load": "Stromlast", "ioda": "IODA",
                "cloudflare": "Cloudflare", "utility": "LINZ NETZ", "news": "Medien"}
CHANNEL_NAMES = {"ntfy": "ntfy", "email": "E-Mail"}
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
WINDOWS = ((1, "24 Stunden"), (7, "7 Tage"), (30, "30 Tage"), (90, "90 Tage"))

BACKGROUND = """## Einordnung

- **Blackout**: unerwarteter, großflächiger und überregionaler Stromausfall. Hier so eingestuft, wenn mindestens die Hälfte eines Gebiets betroffen ist.
- **Brownout**: Spannung oder Versorgung wird abgesenkt oder Verbraucher werden gezielt abgeschaltet (Lastabwurf), um einen Blackout zu verhindern.
- **Netzfrequenz**: Soll 50,00 Hz. Ab 49,8 Hz werden Reserven aktiviert, ab 49,0 Hz schaltet das Netz automatisch Verbraucher ab, bei 47,5 Hz trennen sich Kraftwerke vom Netz.
- **Netzwiederaufbau Österreich**: Schwarzstartfähige Kraftwerke (vor allem Speicherkraftwerke) bauen Netzinseln auf, die Schritt für Schritt zusammengeschaltet werden. Richtwerte: Die APG nannte 2021 aus ihren Simulationen im besten Fall etwa 10 Stunden und längstens 20 bis 30 Stunden, bis die Versorgung wieder läuft. Eine Studie für das Parlament (2022) nennt 10 bis 24 Stunden bis zu einem voll versorgten Übertragungsnetz. Das sind Richtwerte und keine Prognose.
- **Grenzen dieser Übersicht**: Medienberichte belegen einen Ausfall, aber weder Dauer noch Ende. Lastdaten kommen je nach Land mit zwei bis fünf Stunden Verzögerung, die Zeiten daraus stimmen aber. Bei einem großen Ausfall können sie ganz ausbleiben, und rund um Feiertage sind Tiefe und Ende daraus ungenau. Betroffenenzahlen sind grobe Schätzungen (Zahlen aus Schlagzeilen oder Anteil mal Einwohner).
"""
CREDITS = ("Datenquellen: Energy-Charts (Fraunhofer ISE, CC BY 4.0, energy-charts.info), "
           "netzfrequenzmessung.de, Google News, Störmeldungen der LINZ NETZ GmbH, "
           "optional IODA (Georgia Tech) und Cloudflare Radar.")


def md(text: str) -> str:
    """Entschärft Zeichen, die eine Markdown-Tabelle oder einen Link zerbrechen würden."""
    return str(text).replace("|", "/").replace("[", "(").replace("]", ")").replace("\n", " ").strip()


class Report:
    def __init__(self, cfg: dict, state: dict, now):
        self.cfg, self.state, self.now = cfg, state, now
        self.engine = Engine(cfg, state)
        self.tz = self.engine.tz

    # ------------------------------------------------------------------ Helfer
    def clock(self, when) -> str:
        return self.engine.clock(when, self.now) if when else "?"

    def stamp(self) -> str:
        local = self.now.astimezone(self.tz)
        return f"{WEEKDAYS[local.weekday()]}., {local.strftime('%d.%m.%Y, %H:%M')} Uhr"

    def partition(self):
        """Teilt die Ereignisse in laufend (gemeldet), beendet (gemeldet) und beobachtet."""
        active, ended, watching = [], [], []
        for event in self.state["events"].values():
            if not event["reported_at"]:
                if not event["ended_at"]:
                    watching.append(event)
            elif event["ended_at"]:
                ended.append(event)
            else:
                active.append(event)
        active.sort(key=lambda e: e["started_at"])
        ended.sort(key=lambda e: e["ended_at"], reverse=True)
        watching.sort(key=lambda e: -self.engine.impact(e))
        return active, ended, watching

    def duration(self, row) -> timedelta:
        return (parse_ts(row["ended_at"]) or self.now) - parse_ts(row["started_at"])

    def history(self) -> list[dict]:
        """Alle gemeldeten Ereignisse, neueste zuerst: Archiv plus noch nicht archivierte."""
        rows = [dict(row) for row in self.state.get("history", []) if row.get("reported")]
        for event in self.state["events"].values():
            if not event["reported_at"]:
                continue
            incidents = event["incidents"]
            rows.append({
                "id": event["id"], "kind": event["kind"], "started_at": event["started_at"],
                "ended_at": event["ended_at"],
                "areas": sorted(incidents, key=lambda a: incidents[a]["started_at"]),
                "peak": max((i.get("peak") or 0.0) for i in incidents.values()),
                "class": self.engine.classify(event) if event["kind"] == "outage" else "Netzfrequenz",
                "confirmed": any(i["confirmed_power"] for i in incidents.values()),
                "impact": round(self.engine.impact(event)),
                "media_only": event["kind"] == "outage" and self.engine.media_only(event),
            })
        rows.sort(key=lambda row: row["started_at"], reverse=True)
        return rows

    def statistics(self) -> list[dict]:
        rows, result = self.history(), []
        for days, label in WINDOWS:
            since = iso(self.now - timedelta(days=days))
            chosen = [r for r in rows if r["started_at"] >= since or not r["ended_at"] or r["ended_at"] >= since]
            outages = [r for r in chosen if r["kind"] == "outage"]
            # Für Ausfälle, die nur aus Medienberichten bekannt sind, gibt es keine belegte Dauer.
            longest = max((r for r in outages if not r.get("media_only")), key=self.duration, default=None)
            result.append({
                "days": days, "label": label, "outages": len(outages),
                "frequency_alarms": sum(1 for r in chosen if r["kind"] == "frequency"),
                "longest": None if longest is None else {
                    "duration": fmt_duration(self.duration(longest)), "areas": self.engine.names(longest["areas"])},
            })
        return result

    def figures(self) -> list[tuple[str, str]]:
        rows = []
        cursors = self.state.get("cursors", {})
        freq = cursors.get("frequency", {})
        last = freq.get("last")
        if last:
            text = f"{frequency.hz(last['hz'])} Hz (Stand {self.clock(parse_ts(last['t']))})"
            span = frequency.day_range(freq, self.now)
            if span:
                text += f", letzte 24 Stunden {frequency.hz(span[0])} bis {frequency.hz(span[1])} Hz"
            rows.append(("Netzfrequenz Kontinentaleuropa", text))
        for area, entry in (cursors.get("ioda", {}).get("levels") or {}).items():
            drop = entry.get("drop") or 0.0
            state = "normal" if drop < 0.1 else f"Einbruch {fmt_pct(drop)}"
            rows.append((f"Internet-Erreichbarkeit {areas.name(area)}",
                         f"{state} (Stand {self.clock(parse_ts(entry.get('t')))})"))
        for area, entry in (cursors.get("load", {}).get("latest") or {}).items():
            if entry.get("silent"):
                since = self.clock(parse_ts(entry.get("newest") or entry["t"]))
                rows.append((f"Stromlast {areas.name(area)}",
                             f"keine neuen Werte seit {since} (zuletzt {number(entry['mw'])} MW)"))
                continue
            text = f"{number(entry['mw'])} MW (Stand {self.clock(parse_ts(entry['t']))})"
            if entry.get("ref_mw"):
                change = entry["mw"] / entry["ref_mw"] - 1
                text += f", {'+' if change >= 0 else '−'}{abs(round(change * 100))} % gegenüber dem Vortag"
            rows.append((f"Stromlast {areas.name(area)}", text))
        return rows

    def sources(self) -> list[dict]:
        rows = []
        book, cursors = self.state.get("sources", {}), self.state.get("cursors", {})
        for name, label in SOURCE_NAMES.items():
            if not (self.cfg["sources"].get(name) or {}).get("enabled"):
                continue
            entry, cursor = book.get(name) or {}, cursors.get(name) or {}
            if entry.get("fail_since"):
                state = f"gestört seit {self.clock(parse_ts(entry['fail_since']))}"
                note = entry.get("last_error") or ""
            elif entry.get("last_ok"):
                state, note = "in Ordnung", cursor.get("note") or ""
            else:
                state, note = "noch nicht abgefragt", ""
            rows.append({"name": name, "label": label, "ok": not entry.get("fail_since") and bool(entry.get("last_ok")),
                         "state": state, "data_time": cursor.get("data_time"), "note": note})
        return rows

    # ---------------------------------------------------------------- Markdown
    def event_block(self, event) -> list[str]:
        engine, now = self.engine, self.now
        order = sorted(event["incidents"].values(), key=lambda i: i["started_at"])
        start, end = parse_ts(event["started_at"]), parse_ts(event["ended_at"])
        media_only = event["kind"] == "outage" and engine.media_only(event)
        icon = "🔴" if not end else "⚪" if media_only else "🟢"
        lines = [f"### {icon} {md(engine.headline(event))}", ""]
        if media_only:
            text = (f"Erster Medienbericht um {self.clock(start)} Uhr. "
                    "Dauer und Ende lassen sich aus Medienberichten nicht ablesen.")
        elif end:
            text = f"Beginn {self.clock(start)}, Ende {self.clock(end)}, Dauer {fmt_duration(end - start)}."
        else:
            text = f"Seit {self.clock(start)} Uhr, Dauer bisher {fmt_duration(now - start)}."
        impact = engine.impact(event) if event["kind"] == "outage" else 0
        if impact >= 100:
            text += f" Größenordnung: rund {people(impact)} Betroffene."
        lines += [text, ""]
        lines += [f"- {md(engine.area_line(inc, now))}" for inc in order]
        lines += [""] + [f"{md(line)}  " for line in engine.course_lines(event, now)]
        timeline = sorted((entry["t"], areas.name(inc["area"]), entry["text"])
                          for inc in order for entry in inc["timeline"])
        if timeline:
            lines += ["", "| Zeit | Gebiet | Ereignis |", "|---|---|---|"]
            lines += [f"| {self.clock(parse_ts(t))} | {md(name)} | {md(text)} |" for t, name, text in timeline[-25:]]
        news, seen = [], set()
        for inc in order:
            for item in inc["news"]:
                if item["url"] not in seen:
                    seen.add(item["url"])
                    news.append(item)
        if news:
            lines += ["", "Medienberichte:", ""]
            for item in news[:8]:
                title = md(item["title"])
                link = f"[{title}]({item['url']})" if str(item["url"]).startswith("http") else title
                lines.append(f"- {link} ({md(item.get('domain') or '?')}, {self.clock(parse_ts(item.get('seen')))})")
        return lines + [""]

    def markdown(self) -> str:
        engine, now = self.engine, self.now
        active, ended, watching = self.partition()
        lines = ["# Lagebericht Stromausfälle", "",
                 f"Stand: **{self.stamp()}** ({self.cfg.get('timezone', 'Europe/Vienna')})", "", "## Aktuell", ""]
        if active:
            for event in active:
                lines += self.event_block(event)
        else:
            lines += ["**Keine größeren Stromausfälle erkannt.**", ""]
        if ended:
            lines += ["## Kürzlich beendet", ""]
            for event in ended:
                lines += self.event_block(event)
        if watching:
            lines += ["## Unter Beobachtung", "",
                      "Störungen, die (noch) nicht gemeldet werden:", "",
                      "| Gebiet | Seit | Signal | Nicht gemeldet, weil |", "|---|---|---|---|"]
            for event in watching[:25]:
                order = sorted(event["incidents"].values(), key=lambda i: i["started_at"])
                signal = "; ".join(engine.area_line(inc, now).split(": ", 1)[-1] for inc in order[:2])
                lines.append(f"| {md(engine.names([i['area'] for i in order]))} "
                             f"| {self.clock(parse_ts(event['started_at']))} | {md(signal)} "
                             f"| {md(', '.join(engine.hold_reasons(event, now)))} |")
            lines.append("")
        figures = self.figures()
        if figures:
            lines += ["## Kennzahlen", "", "| Messgröße | Wert |", "|---|---|"]
            lines += [f"| {md(label)} | {md(value)} |" for label, value in figures]
            lines.append("")
        lines += ["## Statistik", "", "| Zeitraum | Stromausfälle | Frequenz-Alarme | Längster Ausfall |",
                  "|---|---|---|---|"]
        for row in self.statistics():
            longest = row["longest"]
            text = f"{longest['duration']} ({md(longest['areas'])})" if longest else "–"
            lines.append(f"| {row['label']} | {row['outages']} | {row['frequency_alarms']} | {text} |")
        minimum = self.cfg["filter"]
        created = parse_ts(self.state.get("created"))
        lines += ["", f"Gezählt werden gemeldete Ereignisse: ab {minimum['min_duration_minutes']} Minuten Dauer und rund "
                      f"{number(minimum['min_affected_people'])} Betroffenen, in den Vorrang-Gebieten "
                      f"({engine.names(self.cfg['priority']['areas'])}) alle."
                      + (f" Die Zählung läuft seit {created.astimezone(self.tz).strftime('%d.%m.%Y')}." if created else ""),
                  ""]
        history = self.history()
        if history:
            lines += ["### Letzte Ereignisse", "", "| Beginn | Dauer | Gebiete | Art | Spitze |", "|---|---|---|---|---|"]
            for row in history[:15]:
                if row.get("media_only"):
                    duration, kind = "nicht belegt", f"{row['class']} (laut Medien)"
                else:
                    duration = fmt_duration(self.duration(row)) + ("" if row["ended_at"] else " (läuft)")
                    kind = row["class"]
                peak = fmt_pct(row["peak"]) if row.get("peak") and row["kind"] == "outage" else "–"
                lines.append(f"| {self.clock(parse_ts(row['started_at']))} | {duration} "
                             f"| {md(engine.names(row['areas']))} | {md(kind)} | {peak} |")
            lines.append("")
        lines += ["## Datenquellen", "", "| Quelle | Zustand | Datenstand | Hinweis |", "|---|---|---|---|"]
        for row in self.sources():
            stand = self.clock(parse_ts(row["data_time"])) if row["data_time"] else "–"
            lines.append(f"| {row['label']} | {row['state']} | {stand} | {md(row['note'])[:160]} |")
        lines.append("")
        sent = self.state.get("sent") or []
        if sent:
            lines += ["## Letzte Meldungen", "", "| Zeit | Meldung | Zugestellt über |", "|---|---|---|"]
            for entry in sent[:15]:
                channels = ", ".join(CHANNEL_NAMES.get(c, c) for c in entry.get("channels") or []) or "nicht zugestellt"
                lines.append(f"| {self.clock(parse_ts(entry['t']))} | {md(entry['title'])} | {channels} |")
            lines.append("")
        lines += [BACKGROUND, CREDITS, ""]
        return "\n".join(lines)

    # -------------------------------------------------------------------- JSON
    def snapshot(self) -> dict:
        engine, now = self.engine, self.now
        active, ended, watching = self.partition()

        def brief(event):
            order = sorted(event["incidents"].values(), key=lambda i: i["started_at"])
            return {
                "id": event["id"], "kind": event["kind"], "headline": engine.headline(event),
                "started_at": event["started_at"], "ended_at": event["ended_at"],
                "reported": bool(event["reported_at"]), "priority": engine.is_priority(event),
                "affected_people": round(engine.impact(event)),
                "hold_reasons": engine.hold_reasons(event, now),
                "areas": [{"area": i["area"], "name": areas.name(i["area"]), "started_at": i["started_at"],
                           "ended_at": i["ended_at"], "severity": i["severity"], "peak": i["peak"],
                           "confirmed_power": i["confirmed_power"], "confirmed_by": i["confirmed_by"],
                           "restoring_since": i["restoring_since"], "text": engine.area_line(i, now)}
                          for i in order],
            }

        return {
            "generated_at": iso(now), "timezone": self.cfg.get("timezone", "Europe/Vienna"),
            "active": [brief(e) for e in active], "recently_ended": [brief(e) for e in ended],
            "watching": [brief(e) for e in watching],
            "figures": [{"label": label, "value": value} for label, value in self.figures()],
            "statistics": self.statistics(), "history": self.history()[:50], "sources": self.sources(),
        }

    # ---------------------------------------------------- tägliche Zusammenfassung
    def daily(self, first: bool = False) -> Message:
        engine, now = self.engine, self.now
        active, _, watching = self.partition()
        day = now.astimezone(self.tz).strftime("%d.%m.")
        if active:
            count = len(active)
            state = f"{count} laufendes Ereignis" if count == 1 else f"{count} laufende Ereignisse"
        else:
            state = "keine größeren Stromausfälle"
        title = f"Blackout-Radar ist aktiv: {state}" if first else f"Lagebericht {day}: {state}"
        lines = []
        if first:
            lines.append("Die Überwachung läuft. Ab jetzt kommen Meldungen bei größeren Stromausfällen, "
                         f"für {engine.names(self.cfg['priority']['areas'])} sofort.")
        for event in active:
            start = parse_ts(event["started_at"])
            lines.append(f"Läuft: {engine.headline(event)}, seit {self.clock(start)} ({fmt_duration(now - start)})")
        since = iso(now - timedelta(days=1))
        recent = [r for r in self.history() if r["ended_at"] and r["ended_at"] >= since and r["kind"] == "outage"]
        if recent:
            lines.append("Letzte 24 Stunden beendet: " + "; ".join(
                f"{engine.names(r['areas'])} "
                f"({'laut Medien' if r.get('media_only') else fmt_duration(self.duration(r))})" for r in recent[:4]))
        elif not active and not first:
            lines.append("Letzte 24 Stunden: keine gemeldeten Stromausfälle.")
        stats = {row["days"]: row for row in self.statistics()}
        if not first:
            lines.append(f"Gemeldete Stromausfälle: {stats[7]['outages']} in 7 Tagen, {stats[30]['outages']} in 30 Tagen.")
        if watching:
            lines.append(f"Unter Beobachtung: {len(watching)} kleinere oder unbestätigte Störungen weltweit.")
        lines += [f"{label}: {value}" for label, value in self.figures()
                  if label.startswith("Netzfrequenz") or label == f"Stromlast {areas.name('AT')}"]
        sources = self.sources()
        broken = [SOURCE_SHORT.get(row["name"], row["name"]) for row in sources if not row["ok"]]
        if broken:
            lines.append(f"Datenquellen: {len(sources) - len(broken)} von {len(sources)} in Ordnung, gestört: "
                         + ", ".join(broken))
        else:
            lines.append(f"Datenquellen: alle {len(sources)} in Ordnung.")
        book = self.state.get("daily") or {}
        if book.get("runs") and not first:
            pause = fmt_duration(timedelta(seconds=book.get("max_gap_s") or 0))
            lines.append(f"Überwachung: {book['runs']} Läufe seit dem letzten Lagebericht, längste Pause {pause}.")
        key = f"{'hello' if first else 'daily'}:{now.astimezone(self.tz).date().isoformat()}"
        return Message(title, "\n".join(lines), "daily" if not first else "info", key, self.cfg.get("status_url", ""))


def write(out_dir, cfg: dict, state: dict, now) -> None:
    """Schreibt status.md und status.json in den Ausgabeordner."""
    report = Report(cfg, state, now)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, text in (("status.md", report.markdown()),
                       ("status.json", json.dumps(report.snapshot(), ensure_ascii=False, indent=1) + "\n")):
        temp = target / (name + ".tmp")
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, target / name)
