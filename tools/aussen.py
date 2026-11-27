"""Vorläufige Diagnose: Antwortet IODA auf Anfragen aus GitHub Actions, und mit welchem Aufruf?

Nur zum Messen gedacht. Jede Anfrage nennt sich ehrlich (kein Browser wird vorgetäuscht).
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.ioda.inetintel.cc.gatech.edu/v2"
QUERY = BASE + "/entities/query?entityType=country&entityCode=AT"
UA = "blackout-radar/0.1 (privater Stromausfall-Monitor; +https://github.com/sebastianeder09/blackout-radar)"


def curl(label: str, *args: str) -> None:
    started = time.monotonic()
    result = subprocess.run(
        ["curl", "-sS", "-m", "45", "-o", "/tmp/ioda.out", "-w",
         "HTTP %{http_code}, Version %{http_version}, %{size_download} Bytes, verbunden nach %{time_connect} s, "
         "TLS nach %{time_appconnect} s, erstes Byte nach %{time_starttransfer} s, gesamt %{time_total} s",
         *args], capture_output=True, text=True, check=False)
    print(f"  {label}: {result.stdout.strip()} {result.stderr.strip()[:200]} ({time.monotonic() - started:.1f} s)",
          flush=True)
    try:
        with open("/tmp/ioda.out", encoding="utf-8", errors="replace") as handle:
            text = handle.read(600)
        if text:
            print("      Anfang:", " ".join(text.split())[:500])
    except OSError:
        pass
    open("/tmp/ioda.out", "w").close()


def python(label: str, url: str, headers: dict, timeout: float = 45) -> None:
    started = time.monotonic()
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            print(f"  {label}: HTTP {response.status}, {len(body)} Bytes in {time.monotonic() - started:.1f} s, "
                  f"{response.headers.get('Content-Type')}, {response.headers.get('Content-Encoding')}")
            print("      Kopfzeilen:", dict(response.headers))
            print("      Anfang:", body[:300])
    except urllib.error.HTTPError as err:
        print(f"  {label}: HTTP {err.code} in {time.monotonic() - started:.1f} s | {err.read(300)!r}")
    except Exception as err:  # Zeitüberschreitung und Ähnliches
        print(f"  {label}: {type(err).__name__}: {err} nach {time.monotonic() - started:.1f} s")
    sys.stdout.flush()


def main() -> int:
    print("===== curl =====", flush=True)
    subprocess.run(["curl", "--version"], check=False)
    curl("curl, Vorgabe", QUERY)
    curl("curl, HTTP/1.1", "--http1.1", QUERY)
    curl("curl, HTTP/1.1, unser Name", "--http1.1", "-A", UA, QUERY)
    curl("curl, unser Name, gzip", "-A", UA, "--compressed", QUERY)
    curl("curl, Startseite der API", BASE + "/")
    curl("curl, Oberfläche", "https://ioda.inetintel.cc.gatech.edu/")
    curl("curl, Oberfläche /api/v2", "https://ioda.inetintel.cc.gatech.edu/api/v2/entities/query?entityType=country&entityCode=AT")
    until = int(time.time())
    curl("curl, Rohsignal AT", "-A", UA, "--compressed",
         f"{BASE}/signals/raw/country/AT?from={until - 3 * 3600}&until={until}&datasource=ping-slash24")
    curl("curl, Alarme 24 h", "-A", UA, "--compressed",
         f"{BASE}/outages/alerts?from={until - 86400}&until={until}&entityType=country&limit=5")
    print("===== Python =====", flush=True)
    python("urllib, Vorgabe", QUERY, {})
    python("urllib, unser Name", QUERY, {"User-Agent": UA})
    python("urllib, unser Name, Accept */*", QUERY, {"User-Agent": UA, "Accept": "*/*"})
    python("urllib, wie das Programm (gzip)", QUERY,
           {"User-Agent": "blackout-radar/0.1 (privater Stromausfall-Monitor)", "Accept": "*/*",
            "Accept-Encoding": "gzip"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
