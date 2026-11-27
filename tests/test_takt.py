"""Taktgeber: die Kette von Läufen in GitHub Actions und ihre Sicherungen."""
import contextlib
import io
import json
import re
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from blackout_radar import __main__ as app
from blackout_radar import http, takt
from blackout_radar.http import HttpError
from blackout_radar.model import iso

from .helpers import T0

ROOT = Path(__file__).resolve().parent.parent
NOW = T0
TIMER = {"protection_rules": [{"id": 1, "type": "wait_timer", "wait_timer": 5}]}


def entry(run_id: int, status: str = "waiting", age_minutes: float = 1, title: str = takt.LINK_TITLE) -> dict:
    return {"id": run_id, "status": status, "display_title": title,
            "created_at": iso(NOW - timedelta(minutes=age_minutes))}


def down(status: int | None = 502) -> HttpError:
    text = f"HTTP {status} von api.github.com" if status else "api.github.com nicht erreichbar (Zeitüberschreitung)"
    return HttpError(text, status=status)


class FakeApi:
    """Steht für die GitHub-Schnittstelle. Merkt sich, was angestoßen wurde."""

    def __init__(self, waited_s: float | None = 320, runs=(), environment: dict | None = None, broken=()):
        self.started = None if waited_s is None else NOW - timedelta(seconds=waited_s)
        self.runs, self.environment, self.broken = list(runs), environment, set(broken)
        self.dispatched = []

    def get(self, path: str, **params) -> dict:
        if path == "actions/runs/100":
            if "run" in self.broken:
                raise down()
            return {"id": 100, "run_started_at": iso(self.started)} if self.started else {"id": 100}
        if path == f"actions/workflows/{takt.WORKFLOW}/runs":
            if "runs" in self.broken:
                raise down()
            assert params == {"event": "workflow_dispatch", "per_page": 50}, params
            return {"total_count": len(self.runs), "workflow_runs": self.runs}
        if path == f"environments/{takt.ENVIRONMENT}":
            if "environment" in self.broken:
                raise down()
            if self.environment is None:
                raise down(404)
            return self.environment
        raise AssertionError(f"unerwarteter Aufruf: {path}")

    def dispatch(self, ref: str, action: str) -> None:
        if action in self.broken:
            raise down()
        self.dispatched.append((ref, action))


def quiet(function, *args):
    """Ruft die Funktion auf und liefert (Rückgabewert, Ausgabe)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = function(*args)
    return code, out.getvalue()


class Link(unittest.TestCase):
    """Ein Glied der Kette nach seiner Wartezeit."""

    def link(self, api, ref="main"):
        return quiet(takt.link, api, 100, ref, NOW)

    def test_after_the_wait_the_next_link_comes_first_and_then_a_run(self):
        api = FakeApi(waited_s=320)
        code, text = self.link(api)
        self.assertEqual(api.dispatched, [("main", "takt"), ("main", "lauf")])
        self.assertEqual(code, 0)
        self.assertIn("Gewartet: 5 min", text)

    def test_the_chain_stays_on_its_branch(self):
        api = FakeApi()
        self.link(api, ref="claude/probe")
        self.assertEqual(api.dispatched, [("claude/probe", "takt"), ("claude/probe", "lauf")])

    def test_without_a_wait_timer_the_chain_ends_at_once(self):
        api = FakeApi(waited_s=12)
        code, text = self.link(api)
        self.assertEqual(api.dispatched, [])
        self.assertEqual(code, 1)
        self.assertIn("::error::", text)
        self.assertIn("Wait timer", text)
        self.assertIn("12 Sekunden", text)

    def test_the_limit_is_just_below_four_minutes(self):
        self.assertEqual(self.link(FakeApi(waited_s=takt.MIN_WAIT_S - 1))[0], 1)
        api = FakeApi(waited_s=takt.MIN_WAIT_S)
        self.assertEqual(self.link(api)[0], 0)
        self.assertEqual(len(api.dispatched), 2)
        self.assertLess(takt.MIN_WAIT_S, takt.MIN_WAIT_MINUTES * 60)   # Spielraum für ungleiche Uhren
        self.assertGreaterEqual(takt.MIN_WAIT_S, 180)

    def test_a_run_started_in_the_future_does_not_count_as_waited(self):
        api = FakeApi(waited_s=-30)
        self.assertEqual(self.link(api)[0], 1)
        self.assertEqual(api.dispatched, [])

    def test_unknown_start_time_ends_the_chain(self):
        for api in (FakeApi(waited_s=None), FakeApi(broken={"run"})):
            code, text = self.link(api)
            self.assertEqual(api.dispatched, [])
            self.assertEqual(code, 1)
            self.assertIn("::error::", text)

    def test_a_newer_link_takes_over_but_the_run_still_happens(self):
        api = FakeApi(runs=[entry(101, "pending"), entry(100, "in_progress", 5.3)])
        code, text = self.link(api)
        self.assertEqual(api.dispatched, [("main", "lauf")])
        self.assertEqual(code, 0)
        self.assertIn("Lauf 101", text)

    def test_only_newer_unfinished_links_take_over(self):
        others = [
            entry(99, "waiting", 6),                           # älter: muss selbst nachgeben
            entry(100, "in_progress", 5.3),                    # dieses Glied
            entry(101, "completed", 0.5),                      # schon fertig
            entry(102, "in_progress", 0.2, "Blackout-Radar"),  # ein Lauf des Radars, kein Glied
        ]
        api = FakeApi(runs=others)
        self.assertEqual(self.link(api)[0], 0)
        self.assertEqual(api.dispatched, [("main", "takt"), ("main", "lauf")])

    def test_unreadable_run_list_does_not_break_the_chain(self):
        api = FakeApi(broken={"runs"})
        code, _ = self.link(api)
        self.assertEqual(api.dispatched, [("main", "takt"), ("main", "lauf")])
        self.assertEqual(code, 0)

    def test_failed_start_of_the_next_link_still_starts_a_run_which_restarts_the_chain(self):
        api = FakeApi(broken={"takt"})
        code, text = self.link(api)
        self.assertEqual(api.dispatched, [("main", "lauf")])
        self.assertEqual(code, 1)
        self.assertIn("::error::", text)

    def test_failed_start_of_the_run_keeps_the_chain(self):
        api = FakeApi(broken={"lauf"})
        code, _ = self.link(api)
        self.assertEqual(api.dispatched, [("main", "takt")])
        self.assertEqual(code, 1)


class Check(unittest.TestCase):
    """Nach jedem Lauf des Radars: Läuft der Taktgeber noch?"""

    def check(self, api, ref="main"):
        return quiet(takt.check, api, ref, "main", NOW)

    def test_without_the_environment_nothing_happens(self):
        api = FakeApi(environment=None)
        code, text = self.check(api)
        self.assertEqual((code, api.dispatched), (0, []))
        self.assertIn("nicht eingerichtet", text)

    def test_the_wait_timer_is_the_switch(self):
        for rules in ([], [{"type": "required_reviewers", "reviewers": []}], [{"type": "wait_timer", "wait_timer": 1}],
                      [{"type": "wait_timer", "wait_timer": None}], [{"type": "branch_policy"}]):
            api = FakeApi(environment={"protection_rules": rules})
            code, text = self.check(api)
            self.assertEqual((code, api.dispatched), (0, []), rules)
            self.assertIn("nicht eingerichtet", text)

    def test_wait_minutes(self):
        self.assertEqual(takt.wait_minutes(TIMER), 5)
        self.assertEqual(takt.wait_minutes({}), 0)
        self.assertEqual(takt.wait_minutes({"protection_rules": None}), 0)
        self.assertEqual(takt.wait_minutes({"protection_rules": ["x", {"type": "wait_timer", "wait_timer": "7"},
                                                                 {"type": "wait_timer", "wait_timer": "viel"}]}), 7)

    def test_no_link_waiting_starts_the_chain(self):
        api = FakeApi(environment=TIMER)
        code, text = self.check(api)
        self.assertEqual((code, api.dispatched), (0, [("main", "takt")]))
        self.assertIn("gestartet", text)

    def test_a_waiting_link_is_left_alone(self):
        for status in ("waiting", "pending", "queued", "requested"):
            api = FakeApi(environment=TIMER, runs=[entry(101, status)])
            code, text = self.check(api)
            self.assertEqual((code, api.dispatched), (0, []), status)
            self.assertIn("Taktgeber läuft", text)

    def test_a_working_link_without_successor_is_replaced(self):
        # Das Glied arbeitet gerade (oder ist dabei gescheitert), ein Nachfolger wartet nicht.
        api = FakeApi(environment=TIMER, runs=[entry(100, "in_progress", 5.3), entry(98, "completed", 11)])
        self.assertEqual(self.check(api)[0], 0)
        self.assertEqual(api.dispatched, [("main", "takt")])

    def test_stuck_links_and_other_runs_do_not_count(self):
        runs = [entry(60, "queued", 45), entry(102, "queued", 0.1, "Blackout-Radar"),
                {"id": 103, "status": "waiting", "display_title": takt.LINK_TITLE, "created_at": None}, "kaputt"]
        api = FakeApi(environment=TIMER, runs=runs)
        self.check(api)
        self.assertEqual(api.dispatched, [("main", "takt")])

    def test_the_chain_starts_by_itself_only_on_the_default_branch(self):
        api = FakeApi(environment=TIMER)
        code, text = self.check(api, ref="claude/probe")
        self.assertEqual((code, api.dispatched), (0, []))
        self.assertIn("Hauptzweig", text)

    def test_unreadable_data_never_starts_a_second_chain(self):
        for broken in ({"environment"}, {"runs"}):
            api = FakeApi(environment=TIMER, broken=broken)
            code, text = self.check(api)
            self.assertEqual((code, api.dispatched), (0, []), broken)
            self.assertIn("::warning::", text)

    def test_failed_start_is_visible(self):
        api = FakeApi(environment=TIMER, broken={"takt"})
        code, text = self.check(api)
        self.assertEqual((code, api.dispatched), (1, []))
        self.assertIn("::warning::", text)


class Client(unittest.TestCase):
    """Die Aufrufe der Schnittstelle selbst."""

    def setUp(self):
        self.naps = []
        self.api = takt.GitHub("ich/radar", "geheim", sleep=self.naps.append)

    def test_dispatch_sends_ref_and_action(self):
        with mock.patch.object(http, "request", return_value=(204, {}, b"")) as request:
            self.api.dispatch("main", "takt")
        (url,), kwargs = request.call_args
        self.assertEqual(url, "https://api.github.com/repos/ich/radar/actions/workflows/monitor.yml/dispatches")
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(json.loads(kwargs["data"]), {"ref": "main", "inputs": {"aktion": "takt"}})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer geheim")
        self.assertEqual(kwargs["headers"]["Accept"], "application/vnd.github+json")

    def test_get_reads_json_with_parameters(self):
        with mock.patch.object(http, "request", return_value=(200, {}, b'{"workflow_runs": []}')) as request:
            data = self.api.get("actions/workflows/monitor.yml/runs", event="workflow_dispatch", per_page=50)
        self.assertEqual(data, {"workflow_runs": []})
        (url,), kwargs = request.call_args
        self.assertEqual(url, "https://api.github.com/repos/ich/radar/actions/workflows/monitor.yml/runs")
        self.assertEqual(kwargs["params"], {"event": "workflow_dispatch", "per_page": 50})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer geheim")

    def test_other_address_of_the_interface(self):
        api = takt.GitHub("ich/radar", "geheim", api="https://github.example/api/v3/")
        self.assertEqual(api.base, "https://github.example/api/v3/repos/ich/radar/")

    def test_temporary_errors_are_retried(self):
        for first in (down(502), down(None), down(429)):
            self.naps.clear()
            with mock.patch.object(http, "request", side_effect=[first, down(503), (204, {}, b"")]) as request:
                self.api.dispatch("main", "lauf")
            self.assertEqual(request.call_count, 3)
            self.assertEqual(self.naps, [4.0, 8.0])

    def test_lasting_errors_are_passed_on(self):
        with mock.patch.object(http, "request", side_effect=down(502)) as request:
            with self.assertRaises(HttpError):
                self.api.dispatch("main", "lauf")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(self.naps, [4.0, 8.0])

    def test_refusals_are_not_retried(self):
        for status in (401, 403, 404, 422):
            with mock.patch.object(http, "request", side_effect=down(status)) as request:
                with self.assertRaises(HttpError) as caught:
                    self.api.get("environments/takt")
            self.assertEqual(request.call_count, 1, status)
            self.assertEqual(caught.exception.status, status)
        self.assertEqual(self.naps, [])

    def test_unexpected_answer_is_an_empty_object(self):
        with mock.patch.object(http, "request", return_value=(200, {}, b"[1, 2]")):
            self.assertEqual(self.api.get("environments/takt"), {})


class CommandLine(unittest.TestCase):
    ENV = {"GITHUB_REPOSITORY": "ich/radar", "GITHUB_TOKEN": "geheim", "GITHUB_REF_NAME": "main",
           "GITHUB_RUN_ID": "100", "DEFAULT_BRANCH": "main"}

    def run_with(self, api, check_only, **changes):
        env = {key: value for key, value in {**self.ENV, **changes}.items() if value is not None}
        with mock.patch.object(takt, "GitHub", return_value=api) as client:
            code, text = quiet(lambda: takt.run(check_only, env=env, now=NOW))
        return code, text, client

    def test_link_uses_run_and_branch_from_the_environment(self):
        api = FakeApi()
        code, _, client = self.run_with(api, False)
        self.assertEqual((code, api.dispatched), (0, [("main", "takt"), ("main", "lauf")]))
        client.assert_called_once_with("ich/radar", "geheim", "https://api.github.com")

    def test_check_uses_the_default_branch(self):
        api = FakeApi(environment=TIMER)
        self.assertEqual(self.run_with(api, True, GITHUB_REF_NAME="claude/probe")[0], 0)
        self.assertEqual(api.dispatched, [])
        self.assertEqual(self.run_with(api, True)[0], 0)
        self.assertEqual(api.dispatched, [("main", "takt")])

    def test_without_default_branch_nothing_starts(self):
        api = FakeApi(environment=TIMER)
        self.run_with(api, True, DEFAULT_BRANCH=None)
        self.assertEqual(api.dispatched, [])

    def test_token_may_come_as_gh_token_and_the_address_from_the_runner(self):
        api = FakeApi()
        _, _, client = self.run_with(api, False, GITHUB_TOKEN=None, GH_TOKEN="anders",
                                     GITHUB_API_URL="https://github.example/api/v3")
        client.assert_called_once_with("ich/radar", "anders", "https://github.example/api/v3")

    def test_outside_github_actions_nothing_is_called(self):
        for missing in ("GITHUB_REPOSITORY", "GITHUB_TOKEN"):
            api = FakeApi(environment=TIMER)
            self.assertEqual(self.run_with(api, True, **{missing: None})[0], 0)
            code, text, client = self.run_with(api, False, **{missing: None})
            self.assertEqual(code, 1)
            self.assertIn("nur in GitHub Actions", text)
            client.assert_not_called()
            self.assertEqual(api.dispatched, [])

    def test_missing_run_number_ends_the_chain(self):
        api = FakeApi()
        code, text, _ = self.run_with(api, False, GITHUB_RUN_ID="")
        self.assertEqual((code, api.dispatched), (1, []))
        self.assertIn("GITHUB_RUN_ID", text)

    def test_command(self):
        with mock.patch.object(takt, "run", return_value=0) as run:
            self.assertEqual(app.main(["takt"]), 0)
            run.assert_called_once_with(check_only=False)
            run.reset_mock()
            self.assertEqual(app.main(["takt", "--pruefen"]), 0)
            run.assert_called_once_with(check_only=True)


class Workflow(unittest.TestCase):
    """Die Workflow-Datei und das Programm müssen dieselben Namen verwenden."""

    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / takt.WORKFLOW).read_text(encoding="utf-8")
        self.jobs = dict(re.findall(r"^  (\w+):\n((?:(?:    .*)?\n)+)", self.text.split("\njobs:\n", 1)[1], re.M))

    def test_links_are_recognised_by_their_run_name(self):
        self.assertRegex(self.text, rf"(?m)^run-name: \$\{{\{{ inputs\.aktion == 'takt' && '{takt.LINK_TITLE}' \|\| ")

    def test_action_can_be_chosen(self):
        options = re.search(r"options:\n((?: +- .+\n)+)", self.text).group(1).split()
        self.assertIn("takt", options)
        self.assertIn("lauf", options)

    def test_link_waits_in_the_environment_without_deployments(self):
        job = self.jobs["takt"]
        self.assertRegex(job, rf"environment:\n +name: {takt.ENVIRONMENT}\n +deployment: false\n")
        self.assertIn("inputs.aktion == 'takt'", job)
        self.assertIn("python3 -m blackout_radar takt\n", job)
        self.assertRegex(job, r"permissions:\n +actions: write\n +contents: read\n")
        self.assertNotIn("secrets.", job)

    def test_radar_does_not_run_in_a_link_and_checks_the_chain_after_each_run(self):
        job = self.jobs["radar"]
        self.assertRegex(job, r"(?m)^    if: inputs\.aktion != 'takt'$")
        self.assertIn("python3 -m blackout_radar takt --pruefen\n", job)
        self.assertIn("DEFAULT_BRANCH: ${{ github.event_name == 'schedule' && github.ref_name || "
                      "github.event.repository.default_branch }}", job)

    def test_links_have_their_own_queue(self):
        group = re.search(r"concurrency:\n(?:\s*#.*\n)*\s*group: (.+)\n", self.text).group(1)
        self.assertIn("inputs.aktion != 'lauf'", group)
        self.assertIn("format('blackout-radar-{0}', inputs.aktion)", group)


if __name__ == "__main__":
    unittest.main()
