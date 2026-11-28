"""Blackout-Radar: Aufruf über die Kommandozeile.

  python -m blackout_radar run         ein Lauf: Quellen abfragen, melden, Lagebericht schreiben
  python -m blackout_radar daemon      Dauerbetrieb auf einem eigenen Rechner
  python -m blackout_radar status      Lagebericht aus dem gespeicherten Zustand anzeigen
  python -m blackout_radar test-push   Testmeldung an die eigenen Kanäle (--public: an den öffentlichen Alarm)
  python -m blackout_radar simulate    Planspiel: Blackout in Österreich im Zeitraffer
  python -m blackout_radar probe       Diagnose: jede Datenquelle einmal roh abfragen
  python -m blackout_radar takt        Taktgeber in GitHub Actions: ein Glied der Kette (siehe takt.py)
  python -m blackout_radar key         neues Schlüsselpaar für den öffentlichen Alarm erzeugen
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

from . import collectors, config, http, probe, reach, report, sign, simulate, takt
from .engine import Engine
from .model import Message, fmt_duration, iso, now_utc, parse_ts, zone
from .notify import PUBLIC, Notifier, scrub, secrets

log = logging.getLogger("blackout_radar")
OPERATOR = "operator"  # Meldungen über den Betrieb: nur an den Betreiber, nie an den öffentlichen Alarm


# ------------------------------------------------------------------- Zustand
def load_state(path: Path) -> tuple[dict, str | None]:
    """Liest den gespeicherten Zustand. Eine defekte Datei wird beiseitegelegt und gemeldet."""
    if not path.exists():
        return {}, None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("kein JSON-Objekt")
        return state, None
    except (ValueError, OSError) as err:
        backup = path.with_name(path.name + ".defekt")
        try:
            os.replace(path, backup)
        except OSError:
            pass
        log.error("Zustandsdatei %s nicht lesbar: %s", path, err)
        return {}, (f"Der gespeicherte Zustand war nicht lesbar ({type(err).__name__}). Die Überwachung hat neu "
                    f"begonnen, Verlauf und Statistik beginnen von vorn. Die alte Datei liegt unter {backup.name}.")


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, path)


# ------------------------------------------------------------------ ein Lauf
def _daily_due(cfg: dict, local) -> bool:
    try:
        hour, minute = (int(part) for part in str(cfg["daily_summary"]["time"]).split(":"))
    except ValueError:
        hour, minute = 7, 0
    return (local.hour, local.minute) >= (hour, minute)


def upkeep(cfg: dict, state: dict, now, notice: str | None = None) -> list[Message]:
    """Meldungen über den Betrieb selbst: Lücken, gestörte Quellen, erste Meldung, tägliche Übersicht."""
    messages = []
    url = cfg.get("status_url", "")
    tz = zone(cfg.get("timezone", "Europe/Vienna"))
    health = cfg["health"]

    def clock(when) -> str:
        return when.astimezone(tz).strftime("%d.%m. %H:%M")

    book = state.setdefault("daily", {"last": None, "runs": 0, "max_gap_s": 0})
    last_run = parse_ts(state.get("last_run"))
    if last_run:
        gap = now - last_run
        book["max_gap_s"] = max(book.get("max_gap_s") or 0, int(gap.total_seconds()))
        if gap >= timedelta(minutes=health["gap_minutes"]):
            messages.append(Message(
                f"Überwachung war unterbrochen: {fmt_duration(gap)} ohne Lauf",
                f"Zwischen {clock(last_run)} und {clock(now)} Uhr wurde nichts geprüft. Ausfälle aus dieser Zeit "
                "können fehlen. Die Überwachung läuft wieder.", "info", f"gap:{iso(last_run)}", url, OPERATOR))
    book["runs"] = (book.get("runs") or 0) + 1
    if notice:
        messages.append(Message("Blackout-Radar: Zustand neu begonnen", notice, "info", f"reset:{iso(now)}", url,
                                OPERATOR))

    silent = reach.silent_since(state) is not None
    for name, entry in (state.get("sources") or {}).items():
        if not (cfg["sources"].get(name) or {}).get("enabled"):
            continue
        label = report.SOURCE_NAMES.get(name, name)
        failing = parse_ts(entry.get("fail_since"))
        if failing and not entry.get("alerted") and now - failing >= timedelta(hours=health["alert_after_hours"]):
            if silent and name in reach.EUROPEAN_SOURCES:
                continue  # steckt schon in der Meldung "Messquellen in Europa nicht erreichbar"
            entry["alerted"] = True
            error = entry.get("last_error") or "Fehler unbekannt"
            if entry.get("partial"):
                title = f"Datenquelle eingeschränkt: {label}"
                body = (f"Seit {clock(failing)} Uhr fällt ein Teil dieser Quelle aus ({error}). "
                        "Der Rest der Quelle und die übrigen Quellen laufen weiter.")
            else:
                title = f"Datenquelle gestört: {label}"
                body = (f"Seit {clock(failing)} Uhr liefert diese Quelle keine Daten ({error}). "
                        "Die übrigen Quellen laufen weiter.")
            messages.append(Message(title, body, "info", f"source-down:{name}:{entry['fail_since']}", url,
                                    OPERATOR))
        elif not failing and entry.get("alerted"):
            entry["alerted"] = False
            messages.append(Message(f"Datenquelle wieder in Ordnung: {label}", "Die Quelle liefert wieder Daten.",
                                    "info", f"source-up:{name}:{iso(now)}", url, OPERATOR))

    local = now.astimezone(tz)
    today = local.date().isoformat()
    reachable = any((cfg["notify"].get(channel) or {}).get("enabled") for channel in ("ntfy", "email", "public"))
    if not state.get("welcomed"):
        if reachable:  # erste Meldung, sobald ein Kanal eingerichtet ist
            state["welcomed"] = iso(now)
            book["last"] = today
            messages.append(report.Report(cfg, state, now).daily(first=True))
    elif cfg["daily_summary"]["enabled"] and book.get("last") != today and _daily_due(cfg, local):
        messages.append(report.Report(cfg, state, now).daily())
        book.update({"last": today, "runs": 0, "max_gap_s": 0})
    return messages


def tick(cfg: dict, state: dict, now, deliver: bool = True, notice: str | None = None) -> dict:
    """Ein vollständiger Lauf auf dem übergebenen Zustand."""
    state.setdefault("created", iso(now))
    engine = Engine(cfg, state)
    http.drain()  # Anfragen von vor diesem Lauf (Versand) zählen nicht für die Erreichbarkeit
    # Verdacht auf einen großen Ausfall in Europa: Die Messquellen dort schweigen oder die Netzfrequenz schlägt
    # aus. Dann fragt die Quelle "news" alle Feeds aus Übersee in jedem Lauf.
    wide = reach.silent_since(state) is not None or any(
        event["kind"] == "frequency" and not event["ended_at"] for event in state["events"].values())
    context = {"active_areas": engine.active_areas(), "wide": wide}
    signals, health = collectors.collect_all(cfg, state, now, context)
    messages = engine.tick(signals, now)
    messages += reach.update(cfg, state, now, http.drain())
    messages += upkeep(cfg, state, now, notice)
    notifier = Notifier(cfg, state)
    notifier.queue(messages, now)
    delivered = notifier.flush(now) if deliver else 0
    state["last_run"] = iso(now)
    return {"signals": len(signals), "messages": messages, "delivered": delivered, "health": health}


def _summary(result: dict) -> str:
    parts = [f"{name} {'ok' if entry['ok'] else 'eingeschränkt' if entry.get('partial') else 'FEHLER'}"
             for name, entry in result["health"].items()]
    return (f"Lauf fertig: {result['signals']} Signale, {len(result['messages'])} neue Meldungen, "
            f"{result['delivered']} zugestellt. Quellen: {', '.join(parts) or 'keine eingeschaltet'}")


def alert_crash(cfg: dict, folder: Path, now, err: Exception) -> None:
    """Meldet einen Programmabbruch, höchstens einmal am Tag. Ein toter Wächter soll nicht still sein."""
    marker = folder / "crash.json"
    today = now.astimezone(zone(cfg.get("timezone", "Europe/Vienna"))).date().isoformat()
    try:
        if json.loads(marker.read_text(encoding="utf-8")).get("last") == today:
            return
    except (OSError, ValueError, AttributeError):
        pass
    text = scrub(f"{type(err).__name__}: {err}", secrets(cfg["notify"]))[:300]
    message = Message("Blackout-Radar: Fehler im Programm",
                      f"Ein Lauf ist abgebrochen ({text}). Solange der Fehler besteht, wird nicht überwacht.",
                      "warn", f"crash:{today}", cfg.get("status_url", ""), OPERATOR)
    outcome = Notifier(cfg, {}).test(message)
    log.error("Abbruch gemeldet: %s", outcome or "kein Kanal eingerichtet")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"last": today, "error": text}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ Befehle
def cmd_run(args) -> int:
    cfg = config.load(args.config)
    state_path = Path(args.state)
    out_dir = Path(args.out) if args.out else state_path.parent
    state, notice = load_state(state_path)
    now = now_utc()
    if cfg["notify"][PUBLIC].get("problem"):
        log.warning("Öffentlicher Alarm nicht in Betrieb: %s", cfg["notify"][PUBLIC]["problem"])
    try:
        result = tick(cfg, state, now, deliver=not args.dry_run, notice=notice)
        if args.dry_run:
            for message in result["messages"]:
                print(f"── [{message.level}] {message.title}\n{message.body}\n")
            print(report.Report(cfg, state, now).markdown())
        else:
            report.write(out_dir, cfg, state, now)
            save_state(state_path, state)
    except Exception as err:  # der Abbruch soll sichtbar werden, nicht still bleiben
        log.exception("Lauf abgebrochen")
        if not args.dry_run:
            alert_crash(cfg, out_dir, now, err)
        return 1
    log.info(_summary(result))
    return 0


def cmd_daemon(args) -> int:
    log.info("Dauerbetrieb, ein Lauf alle %d Sekunden. Ende mit Strg+C.", args.interval)
    try:
        while True:
            started = time.monotonic()
            cmd_run(args)
            time.sleep(max(5.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


def cmd_status(args) -> int:
    cfg = config.load(args.config)
    state, _ = load_state(Path(args.state))
    if not state:
        print("Noch kein gespeicherter Zustand. Zuerst einen Lauf starten: python -m blackout_radar run")
        return 1
    Engine(cfg, state)  # ergänzt fehlende Grundeinträge
    print(report.Report(cfg, state, now_utc()).markdown())
    return 0


def cmd_test_push(args) -> int:
    cfg = config.load(args.config)
    notifier = Notifier(cfg, {})
    if args.public:
        # Geht an alle, die die App mit dem öffentlichen Alarm nutzen. Deshalb nur auf ausdrücklichen Wunsch.
        public = cfg["notify"][PUBLIC]
        if not public["enabled"]:
            reason = public["problem"] or "Das Secret ALARM_KEY fehlt."
            print(f"Der öffentliche Alarm ist nicht in Betrieb. {reason}")
            return 1
        message = Message("Testmeldung vom Blackout-Radar",
                          "Das ist nur ein Test, es gibt keinen Stromausfall.\n"
                          "Der öffentliche Alarm funktioniert: Diese Meldung ist unterschrieben, "
                          "und die App hat die Unterschrift geprüft.",
                          args.level, f"test:{iso(now_utc())}", cfg.get("status_url", ""))
        outcome = notifier.test(message, [PUBLIC])
    else:
        if not [name for name in notifier.channels() if name != PUBLIC]:
            print("Kein Kanal eingerichtet. Für ntfy fehlt NTFY_TOPIC, für E-Mail fehlen SMTP_HOST und MAIL_TO.")
            return 1
        message = Message("Testmeldung vom Blackout-Radar",
                          "Wenn du das liest, funktioniert der Versand.\n"
                          "Echte Meldungen sehen genauso aus und führen per Antippen zum Lagebericht.",
                          args.level, f"test:{iso(now_utc())}", cfg.get("status_url", ""), OPERATOR)
        outcome = notifier.test(message)
    for channel, result in outcome.items():
        print(f"{report.CHANNEL_NAMES.get(channel, channel)}: {result}")
    return 0 if all(result == "ok" for result in outcome.values()) else 1


def cmd_simulate(args) -> int:
    cfg = config.load(args.config)
    tz = zone(cfg.get("timezone", "Europe/Vienna"))
    start = now_utc().replace(second=0, microsecond=0) - timedelta(minutes=simulate.END_MINUTE)
    if not args.send:
        print(simulate.render(cfg, start, tz))
        return 0
    notifier = Notifier(cfg, {})
    if not [name for name in notifier.channels() if name != PUBLIC]:
        print("Kein Kanal eingerichtet, es wird nichts verschickt.")
        return 1
    failed = 0
    for when, message in simulate.run(cfg, start):
        outcome = notifier.test(simulate.as_test(message))
        failed += sum(1 for result in outcome.values() if result != "ok")
        print(f"{when.astimezone(tz).strftime('%H:%M')} {message.title}: {outcome}")
        time.sleep(1.5)
    return 1 if failed else 0


def cmd_probe(args) -> int:
    only = [name.strip() for name in args.only.split(",") if name.strip()] if args.only else None
    probe.run(config.load(args.config), now_utc(), only)
    return 0


def cmd_takt(args) -> int:
    return takt.run(check_only=args.pruefen)


def cmd_key(args) -> int:
    if not sign.KEY_FORMAT.fullmatch(f"BRKEY1:{args.name}:{'0' * 64}"):
        print("Der Name darf nur aus Kleinbuchstaben und Ziffern bestehen, höchstens 8 Zeichen.")
        return 1
    key = sign.generate(args.name)
    print("Neues Schlüsselpaar für den öffentlichen Alarm.\n")
    print("Geheimer Teil. Nur als Secret ALARM_KEY bei GitHub eintragen, sonst nirgends aufbewahren:")
    print(f"  {key.export()}\n")
    print("Öffentlicher Teil. In blackout_radar/sign.py (PUBLIC_KEYS) und in der App eintragen:")
    print(f'  "{key.kid}": "{key.public_hex}"')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blackout_radar", description="Meldet größere Stromausfälle per Push.")
    parser.add_argument("--config", default="config.toml", help="Konfigurationsdatei (Standard: config.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_state(name: str, text: str):
        command = sub.add_parser(name, help=text)
        command.add_argument("--state", default="data/state.json", help="Zustandsdatei (Standard: data/state.json)")
        return command

    run = with_state("run", "ein Lauf: Quellen abfragen, melden, Lagebericht schreiben")
    run.add_argument("--out", help="Ordner für status.md und status.json (Standard: Ordner der Zustandsdatei)")
    run.add_argument("--dry-run", action="store_true", help="nichts verschicken und nichts speichern, nur anzeigen")
    run.set_defaults(func=cmd_run)

    daemon = with_state("daemon", "Dauerbetrieb auf einem eigenen Rechner")
    daemon.add_argument("--out", help="Ordner für status.md und status.json")
    daemon.add_argument("--interval", type=int, default=300, help="Sekunden zwischen zwei Läufen (Standard: 300)")
    daemon.set_defaults(func=cmd_daemon, dry_run=False)

    with_state("status", "Lagebericht aus dem gespeicherten Zustand anzeigen").set_defaults(func=cmd_status)

    test = sub.add_parser("test-push", help="Testmeldung an die eigenen Kanäle")
    test.add_argument("--level", default="info", choices=["alarm", "warn", "info", "ok", "daily"])
    test.add_argument("--public", action="store_true",
                      help="stattdessen an den öffentlichen Alarm: Das erreicht alle, die die App nutzen")
    test.set_defaults(func=cmd_test_push)

    sim = sub.add_parser("simulate", help="Planspiel: Blackout in Österreich im Zeitraffer")
    sim.add_argument("--send", action="store_true", help="Meldungen als [TEST] wirklich verschicken")
    sim.set_defaults(func=cmd_simulate)

    diag = sub.add_parser("probe", help="Diagnose: jede Datenquelle einmal roh abfragen")
    diag.add_argument("--only", help="nur diese Quellen, mit Komma getrennt (load,frequency,news,feeds,utility,ntfy,"
                                     "public). "
                                     "replay spielt die Lastauswertung an echten Tagen nach, ioda fragt IODA ab")
    diag.set_defaults(func=cmd_probe)

    clock = sub.add_parser("takt", help="Taktgeber in GitHub Actions: nächstes Glied und einen Lauf anstoßen")
    clock.add_argument("--pruefen", action="store_true",
                       help="nur nachsehen, ob ein Glied wartet, und sonst eines starten (nach jedem Lauf)")
    clock.set_defaults(func=cmd_takt)

    key = sub.add_parser("key", help="neues Schlüsselpaar für den öffentlichen Alarm erzeugen")
    key.add_argument("--name", default="k1", help="Name des Schlüssels, steht in jeder Meldung (Standard: k1)")
    key.set_defaults(func=cmd_key)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
