"""Erzeugt blackout_radar/gemeindeliste.py aus dem amtlichen Gemeindeverzeichnis von Statistik Austria.

Aufruf:  python3 tools/orte_at.py                   holt das Verzeichnis von statistik.at
         python3 tools/orte_at.py --quelle ORDNER   liest gemliste_knz.csv und polbezirke.csv aus einem Ordner

Das Verzeichnis ändert sich mit Gemeindezusammenlegungen, meist zum Jahreswechsel. Einmal im Jahr neu
erzeugen reicht. Danach die Tests laufen lassen: Sie prüfen, ob die Liste vollständig und lesbar ist.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

QUELLE = "https://www.statistik.at/verzeichnis/reglisten/reglisten.zip"
ZIEL = Path(__file__).resolve().parent.parent / "blackout_radar" / "gemeindeliste.py"
DATEIEN = ("gemliste_knz.csv", "polbezirke.csv")
BREITE = 110


def holen(quelle: str) -> dict[str, str]:
    """Liefert den Text der beiden Listen, aus dem ZIP von Statistik Austria oder aus einem Ordner."""
    if not quelle.startswith("http"):
        return {name: (Path(quelle) / name).read_text(encoding="utf-8-sig") for name in DATEIEN}
    request = urllib.request.Request(quelle, headers={"User-Agent": "blackout-radar (Gemeindeverzeichnis)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    return {name: archive.read(name).decode("utf-8-sig") for name in DATEIEN}


def zeilen(text: str) -> list[list[str]]:
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), delimiter=";")]


def stand(text: str) -> str:
    """Gebietsstand und Erstellungsdatum aus den Kopfzeilen, z. B. "Gebietsstand 2026, erstellt am 26.11.2026"."""
    year = re.search(r"Gebietsstand (\d{4})", text)
    made = re.search(r"Erstellt am:;(\d{2}\.\d{2}\.\d{4})", text)
    if not year or not made:
        raise ValueError("Kopfzeilen des Gemeindeverzeichnisses sind anders aufgebaut als erwartet")
    return f"Gebietsstand {year.group(1)}, erstellt am {made.group(1)}"


def gemeinden(text: str) -> dict[str, list[str]]:
    """Bundesland (ISO 3166-2) -> Gemeindenamen. Die erste Ziffer der Kennziffer ist das Bundesland."""
    found: dict[str, list[str]] = {}
    seen = set()
    for row in zeilen(text):
        if len(row) < 2 or not re.fullmatch(r"\d{5}", row[0]) or row[0] in seen:
            continue  # Kopf- und Fußzeilen, Wien steht je Gemeindebezirk einmal in der Liste
        seen.add(row[0])
        found.setdefault(f"AT-{row[0][0]}", []).append(row[1])
    return found


def bezirke(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Bundesland -> politische Bezirke, dazu die Wiener Gemeindebezirke ("Wien  2.,Leopoldstadt")."""
    found: dict[str, list[str]] = {}
    vienna = []
    for row in zeilen(text):
        if len(row) < 4 or not re.fullmatch(r"\d", row[0]):
            continue
        match = re.fullmatch(r"Wien\s+\d+\.,\s*(.+)", row[3])
        if match:
            vienna.append(match.group(1))
        elif row[0] != "9":
            found.setdefault(f"AT-{row[0]}", []).append(row[3])
    return found, vienna


def block(names: list[str], indent: str) -> str:
    """Namen als mehrzeilige Zeichenkette, mit | getrennt."""
    lines, line = [], ""
    for name in names:
        if "|" in name or '"' in name:
            raise ValueError(f"Name mit Trennzeichen: {name!r}")
        piece = name + "|"
        if line and len(line) + len(piece) > BREITE:
            lines.append(line)
            line = ""
        line += piece
    lines.append(line.rstrip("|"))
    return "\n".join(f'{indent}"{part}"' for part in lines)


def schreiben(listen: dict[str, str], ziel: Path) -> str:
    towns = gemeinden(listen["gemliste_knz.csv"])
    districts, vienna = bezirke(listen["polbezirke.csv"])
    count = sum(len(names) for names in towns.values())
    if count < 2000 or len(towns) != 9 or len(vienna) != 23 or len(districts) != 8:
        raise ValueError(f"Verzeichnis unvollständig: {count} Gemeinden in {len(towns)} Bundesländern, "
                         f"{len(vienna)} Wiener Bezirke, Bezirke in {len(districts)} Bundesländern")
    state = stand(listen["gemliste_knz.csv"])
    out = ['"""Gemeinden, politische Bezirke und Wiener Gemeindebezirke je Bundesland.',
           "",
           "Erzeugt von tools/orte_at.py aus dem Gemeindeverzeichnis. Nicht von Hand ändern.",
           f"Quelle: STATISTIK AUSTRIA, {state}.",
           '"""',
           "",
           f'STAND = "{state}"',
           "",
           "# Bundesland (ISO 3166-2) -> amtliche Gemeindenamen, mit | getrennt",
           "GEMEINDEN = {"]
    for land in sorted(towns):
        out += [f'    "{land}": (', block(towns[land], " " * 8), "    ),"]
    out += ["}", "", "# Bundesland -> politische Bezirke", "BEZIRKE = {"]
    for land in sorted(districts):
        out += [f'    "{land}": (', block(districts[land], " " * 8), "    ),"]
    out += ["}", "", "# Wiener Gemeindebezirke", "WIEN = (", block(vienna, "    "), ")", ""]
    ziel.write_text("\n".join(out), encoding="utf-8")
    return f"{count} Gemeinden, {sum(len(v) for v in districts.values())} Bezirke, {len(vienna)} Wiener Bezirke ({state})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quelle", default=QUELLE, help="Adresse des ZIP oder Ordner mit den beiden Listen")
    parser.add_argument("--ziel", default=str(ZIEL), help="Datei, die geschrieben wird")
    args = parser.parse_args(argv)
    print(f"{args.ziel}: {schreiben(holen(args.quelle), Path(args.ziel))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
