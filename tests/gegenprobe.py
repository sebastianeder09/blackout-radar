"""Gegenprobe: setzt gedachte Ausfälle in die echten ruhigen Lastreihen und prüft, wie die Auswertung sie erkennt.

Kein Teil der schnellen Tests, ein Lauf dauert je Reihe einige Minuten:

    python3 -m tests.gegenprobe                 # alle ruhigen Reihen
    python3 -m tests.gegenprobe at-2026-11      # eine Reihe
    python3 -m tests.gegenprobe -v at-2026-11   # jeden Fall zeigen, nicht nur die ungenauen

Je Tag vier Beginnzeiten (3, 8, 13 und 19 Uhr UTC), drei Tiefen (25, 50 und 95 % weniger Last) und zwei
Dauern (2 und 9 Stunden). Die Last fällt sofort auf die Tiefe und kehrt im letzten Drittel gleichmäßig zurück.

Als richtig gilt: genau ein Einbruch, Beginn auf eine Stunde genau, Tiefe auf 8 Prozentpunkte genau,
Ende während der Rückkehr der Last (frühestens eine gute halbe Stunde davor) und höchstens eineinhalb
Stunden nach dem wirklichen Ende.
"""
from __future__ import annotations

import functools
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta

from blackout_radar import probe
from blackout_radar.collectors import energy_charts
from blackout_radar.model import iso, parse_ts

from .helpers import make_cfg
from .test_real_load import DATA, real

QUIET = ("at-2026-11", "at-2026-05-01", "at-2026-01-01", "de-2026-11")
HOURS = (3, 8, 13, 19)
DEPTHS = (0.25, 0.5, 0.95)
DURATIONS = (2, 9)
DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


@functools.cache
def series(name: str) -> tuple:
    country, points = real(name)
    return country, [(parse_ts(stamp), value) for stamp, value in points]


def cases(name: str) -> list:
    """Alle Fälle einer Reihe als (Beginn, Tiefe, Stunden). Der erste Tag ist der erste, der ganz ausgewertet wird."""
    _, points = series(name)
    first = points[0][0] + timedelta(days=max(energy_charts.REFERENCE_DAYS), hours=4)
    day, found = first.replace(hour=0, minute=0) + timedelta(days=1), []
    while day + timedelta(days=1, hours=12) <= points[-1][0]:
        found += [(day + timedelta(hours=hour), depth, hours)
                  for hour in HOURS for depth in DEPTHS for hours in DURATIONS]
        day += timedelta(days=1)
    return found


def check(name: str, case: tuple) -> tuple:
    """Spielt einen Fall durch. Liefert (Zahl der Schritte mit laufendem Einbruch, größte Tiefe, Abweichungen)."""
    begin, depth, hours = case
    country, points = series(name)
    end = begin + timedelta(hours=hours)
    ramp = end - timedelta(hours=hours / 3)
    changed = []
    for when, value in points:
        if begin <= when < ramp:
            value *= 1 - depth
        elif ramp <= when < end:
            value *= 1 - depth * (end - when) / (end - ramp)
        changed.append([iso(when), value])
    found = probe.replay(country, changed, make_cfg()["sources"]["load"])
    active = [signal for _, signal in found if signal.active]
    ends = [signal for _, signal in found if not signal.active]
    starts = sorted({iso(signal.started_at) for _, signal in found})
    peak = max((signal.severity for signal in active), default=0.0)
    notes = []
    if not found:
        notes.append("nicht erkannt")
    else:
        if len(starts) > 1:
            notes.append(f"{len(starts)} Einbrüche")
        if abs(parse_ts(starts[0]) - begin) > timedelta(hours=1):
            notes.append(f"Beginn {starts[0][5:16]}")
        if abs(peak - depth) > 0.08:
            notes.append("Tiefe ungenau")
        if not ends:
            notes.append("kein Ende")
        else:
            late = (ends[-1].ended_at - end) / timedelta(hours=1)
            if not -hours / 3 - 0.6 <= late <= 1.5:
                notes.append(f"Ende {late:+.1f} h")
    return len(active), peak, notes


def run(name: str, verbose: bool = False) -> tuple:
    """Prüft alle Fälle einer Reihe. Liefert (Zahl der Fälle, Zahl der ungenauen)."""
    country, points = series(name)
    quiet = probe.replay(country, [[iso(when), value] for when, value in points], make_cfg()["sources"]["load"])
    print(f"{name} ({DATA[name]['note']}): {len(points)} Werte, ohne Eingriff {len(quiet)} Befunde", flush=True)
    todo, wrong = cases(name), 0
    with ProcessPoolExecutor() as pool:
        for (begin, depth, hours), (steps, peak, notes) in zip(
                todo, pool.map(functools.partial(check, name), todo, chunksize=4), strict=True):
            wrong += bool(notes)
            if notes or verbose:
                print(f"  {DAYS[begin.weekday()]} {begin:%d.%m. %H:%M} −{depth:.0%} {hours} h: "
                      f"{steps} Schritte, größte Tiefe {peak:.0%}, {'; '.join(notes) or 'richtig'}", flush=True)
    print(f"  {len(todo)} Fälle, {len(todo) - wrong} richtig, {wrong} ungenau", flush=True)
    return len(todo), wrong


def main(argv: list) -> int:
    verbose = "-v" in argv
    names = [name for name in argv if name != "-v"] or list(QUIET)
    unknown = [name for name in names if name not in DATA]
    if unknown:
        print(f"unbekannte Reihe: {', '.join(unknown)}. Vorhanden: {', '.join(DATA)}")
        return 2
    total = [run(name, verbose) for name in names]
    print(f"Gesamt: {sum(count for count, _ in total)} Fälle, {sum(wrong for _, wrong in total)} ungenau")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
