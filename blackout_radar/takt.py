"""Taktgeber in GitHub Actions: eine Kette von Läufen, die sich selbst fortsetzt.

GitHub startet Zeitpläne nur "nach Möglichkeit". Läufe kommen spät, selten oder in neuen Repositories gar
nicht. Der Taktgeber ist davon unabhängig: Jedes Glied der Kette wartet in der Umgebung "takt" die dort
eingestellte Wartezeit ab (währenddessen ist kein Rechner belegt), stößt dann das nächste Glied und einen
Lauf des Radars an und endet.

Sicherungen:
  * Ein Glied setzt die Kette nur fort, wenn es selbst lange genug gewartet hat. Fehlt die Wartezeit in der
    Umgebung, endet die Kette deshalb sofort, statt ohne Pause zu laufen.
  * Gibt es ein jüngeres Glied, setzt nur dieses die Kette fort. So bleibt es bei einer einzigen Kette.
  * Jeder Lauf des Radars im Hauptzweig sieht nach, ob ein Glied wartet, und startet sonst ein neues. Das
    geschieht nur, wenn die Umgebung eine Wartezeit hat: Sie ist der Schalter für den Taktgeber.
"""
from __future__ import annotations

import os
import time
from datetime import timedelta

from . import http
from .http import HttpError
from .model import fmt_duration, now_utc, parse_ts

ENVIRONMENT = "takt"
WORKFLOW = "monitor.yml"
LINK_TITLE = "Taktgeber"          # "run-name" der Glieder in monitor.yml, daran werden sie erkannt
MIN_WAIT_MINUTES = 4              # so viel Wartezeit muss die Umgebung mindestens haben
MIN_WAIT_S = 225                  # so alt muss ein Glied sein, bevor es das nächste anstößt (knapp 4 Minuten)
MAX_AGE = timedelta(minutes=30)   # ältere unfertige Glieder gelten als hängengeblieben


class GitHub:
    """Die wenigen Aufrufe der GitHub-Schnittstelle, die der Taktgeber braucht."""

    def __init__(self, repo: str, token: str, api: str = "https://api.github.com",
                 attempts: int = 3, pause: float = 4.0, sleep=time.sleep):
        self.base = f"{api.rstrip('/')}/repos/{repo}/"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}
        self.attempts, self.pause, self.sleep = attempts, pause, sleep

    def _call(self, action):
        for attempt in range(1, self.attempts + 1):
            try:
                return action()
            except HttpError as err:
                # Nur wiederholen, was vorübergehend sein kann: Netzfehler, Überlastung, Serverfehler.
                if attempt == self.attempts or (err.status is not None and err.status < 500 and err.status != 429):
                    raise
                self.sleep(self.pause * attempt)

    def get(self, path: str, **params) -> dict:
        data = self._call(lambda: http.get_json(self.base + path, params=params or None, headers=self.headers))
        return data if isinstance(data, dict) else {}

    def dispatch(self, ref: str, action: str) -> None:
        """Stößt monitor.yml mit der gewählten Aktion an. Ein doppelter Anstoß nach einem Netzfehler schadet nicht:
        Von zwei Gliedern setzt nur das jüngere die Kette fort, und Läufe des Radars laufen nie gleichzeitig."""
        payload = {"ref": ref, "inputs": {"aktion": action}}
        self._call(lambda: http.post_json(self.base + f"actions/workflows/{WORKFLOW}/dispatches", payload,
                                          headers=self.headers))


def wait_minutes(environment: dict) -> int:
    """Wartezeit der Umgebung in Minuten, 0 wenn keine eingestellt ist."""
    minutes = 0
    for rule in environment.get("protection_rules") or []:
        if isinstance(rule, dict) and rule.get("type") == "wait_timer":
            try:
                minutes = max(minutes, int(rule.get("wait_timer") or 0))
            except (TypeError, ValueError):
                pass
    return minutes


def links(api, now) -> list[dict]:
    """Glieder der Kette, die noch nicht fertig sind. Hängengebliebene alte Läufe zählen nicht."""
    data = api.get(f"actions/workflows/{WORKFLOW}/runs", event="workflow_dispatch", per_page=50)
    found = []
    for run in data.get("workflow_runs") or []:
        if not isinstance(run, dict) or run.get("display_title") != LINK_TITLE or run.get("status") == "completed":
            continue
        created = parse_ts(run.get("created_at"))
        if created is not None and now - created <= MAX_AGE and isinstance(run.get("id"), int):
            found.append(run)
    return found


def link(api, run_id: int, ref: str, now) -> int:
    """Ein Glied der Kette, aufgerufen nach der Wartezeit: nächstes Glied anstoßen, dann einen Lauf."""
    try:
        started = parse_ts(api.get(f"actions/runs/{run_id}").get("run_started_at"))
    except HttpError as err:
        print(f"::error::Der Taktgeber endet: Der eigene Lauf ist nicht lesbar ({err}).")
        return 1
    if started is None:
        print("::error::Der Taktgeber endet: Die Startzeit des eigenen Laufs fehlt.")
        return 1
    waited = (now - started).total_seconds()
    if waited < MIN_WAIT_S:
        print(f"::error::Der Taktgeber endet: Dieses Glied hat nur {max(0, int(waited))} Sekunden gewartet. "
              f"Die Umgebung „{ENVIRONMENT}“ braucht eine Wartezeit von 5 Minuten (Settings → Environments → "
              f"{ENVIRONMENT} → Wait timer). Ohne sie würde die Kette ohne Pause laufen.")
        return 1
    print(f"Gewartet: {fmt_duration(timedelta(seconds=waited))}.")

    try:
        newer = [run["id"] for run in links(api, now) if run["id"] > run_id]
    except HttpError as err:
        # Lieber kurz zwei Ketten (das jüngere Glied gewinnt beim nächsten Mal) als gar keine.
        print(f"Andere Glieder nicht lesbar ({err}), die Kette läuft weiter.")
        newer = []
    code = 0
    if newer:
        print(f"Ein jüngeres Glied ist unterwegs (Lauf {max(newer)}). Dieses Glied setzt die Kette nicht fort.")
    else:
        try:
            api.dispatch(ref, "takt")
            print("Nächstes Glied angestoßen.")
        except HttpError as err:
            print(f"::error::Das nächste Glied ließ sich nicht anstoßen ({err}). "
                  "Der folgende Lauf des Radars startet den Taktgeber neu.")
            code = 1
    try:
        api.dispatch(ref, "lauf")
        print("Lauf des Radars angestoßen.")
    except HttpError as err:
        print(f"::error::Der Lauf des Radars ließ sich nicht anstoßen ({err}).")
        code = 1
    return code


def check(api, ref: str, default_branch: str, now) -> int:
    """Nach jedem Lauf des Radars: Wartet kein Glied, obwohl der Taktgeber eingerichtet ist, eines starten."""
    try:
        minutes = wait_minutes(api.get(f"environments/{ENVIRONMENT}"))
    except HttpError as err:
        if err.status == 404:
            print(f"Taktgeber: nicht eingerichtet (es gibt keine Umgebung „{ENVIRONMENT}“).")
        else:
            print(f"::warning::Taktgeber: Die Umgebung „{ENVIRONMENT}“ ist nicht lesbar ({err}).")
        return 0
    if minutes < MIN_WAIT_MINUTES:
        print(f"Taktgeber: nicht eingerichtet (die Umgebung „{ENVIRONMENT}“ hat keine Wartezeit von mindestens "
              f"{MIN_WAIT_MINUTES} Minuten).")
        return 0
    try:
        # Ein Glied, das gerade arbeitet, zählt nicht: Sein Nachfolger müsste schon warten.
        waiting = [run["id"] for run in links(api, now) if run.get("status") != "in_progress"]
    except HttpError as err:
        print(f"::warning::Taktgeber: Die Läufe sind nicht lesbar ({err}).")
        return 0
    if waiting:
        print(f"Taktgeber läuft (Wartezeit {minutes} Minuten, nächstes Glied: Lauf {max(waiting)}).")
        return 0
    if not ref or ref != default_branch:
        print(f"Taktgeber: Kein Glied wartet. Von selbst startet er nur im Hauptzweig, nicht in „{ref}“.")
        return 0
    try:
        api.dispatch(ref, "takt")
    except HttpError as err:
        print(f"::warning::Taktgeber: Kein Glied wartet, und ein neues ließ sich nicht starten ({err}).")
        return 1
    print(f"Taktgeber gestartet (Wartezeit {minutes} Minuten).")
    return 0


def run(check_only: bool, env=None, now=None) -> int:
    """Einstieg für die Kommandozeile. Liest alles Nötige aus den Variablen von GitHub Actions."""
    env = os.environ if env is None else env
    repo = env.get("GITHUB_REPOSITORY", "")
    token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or ""
    ref = env.get("GITHUB_REF_NAME", "")
    if not repo or not token:
        print("Der Taktgeber läuft nur in GitHub Actions (GITHUB_REPOSITORY oder GITHUB_TOKEN fehlt).")
        return 0 if check_only else 1
    api = GitHub(repo, token, env.get("GITHUB_API_URL") or "https://api.github.com")
    now = now or now_utc()
    if check_only:
        return check(api, ref, env.get("DEFAULT_BRANCH", ""), now)
    try:
        run_id = int(env.get("GITHUB_RUN_ID", ""))
    except ValueError:
        print("::error::Der Taktgeber endet: GITHUB_RUN_ID fehlt.")
        return 1
    return link(api, run_id, ref, now)
