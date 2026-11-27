"""Holt das amtliche Gemeindeverzeichnis von Statistik Austria (vorläufig: nur roh ausgeben)."""
from __future__ import annotations

import base64
import gzip
import io
import sys
import urllib.request
import zipfile

QUELLE = "https://www.statistik.at/verzeichnis/reglisten/reglisten.zip"


def holen(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "blackout-radar (Gemeindeverzeichnis)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def roh() -> int:
    data = holen(QUELLE)
    print(f"{QUELLE}: {len(data)} Bytes")
    archive = zipfile.ZipFile(io.BytesIO(data))
    for info in archive.infolist():
        print(f"  {info.filename}: {info.file_size} Bytes, {info.date_time}")
    for info in archive.infolist():
        name = info.filename.lower()
        if not name.endswith((".csv", ".txt")):
            continue
        content = archive.read(info)
        print(f"===== {info.filename}: erste Zeilen =====")
        for line in content.splitlines()[:6]:
            print("   ", line[:200])
        if any(key in name for key in ("gemliste", "polbez", "bezirk")):
            packed = base64.b64encode(gzip.compress(content, 9)).decode()
            print(f"-----BEGIN {info.filename}-----")
            for start in range(0, len(packed), 100):
                print(packed[start:start + 100])
            print(f"-----END {info.filename}-----")
    return 0


if __name__ == "__main__":
    sys.exit(roh())
