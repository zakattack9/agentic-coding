#!/usr/bin/env python3
"""Offline tests for the SIGNALS phase — NO network, NO live org, NO mutation.

Covers:
  * the vendored signals computer derives Schedule health / Slippage /
    Slippage days / Blast radius / Blast count / Blocked DETERMINISTICALLY from a
    fixture board (expected values) — and ZERO AI calls exist (grep the workflow
    + the vendored script for anthropic/claude/model API calls -> none).
  * rollup fixtures -> expected health enum (the documented rules).
  * DAG cross-check: the vendored DAG math reproduces lib/dag.compute exactly.
  * App-token discipline: --apply refuses to write without GH_APP_TOKEN and the
    workflow never feeds GITHUB_TOKEN to a Project write.

The vendored script is imported from templates/github/signals.py and driven with
a fake `RUN` that returns canned GraphQL JSON and counts round-trips. Nothing
here touches a network or mutates anything.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
PLUGIN = os.path.dirname(LIB)
TEMPLATES = os.path.join(PLUGIN, "templates", "github")
WORKFLOW = os.path.join(TEMPLATES, "workflows", "signals-sync.yml")
SIGNALS_PY = os.path.join(TEMPLATES, "signals.py")
SKILL_MD = os.path.join(PLUGIN, "skills", "sync-signals", "SKILL.md")

sys.path.insert(0, LIB)        # for lib/dag.py
sys.path.insert(0, TEMPLATES)  # for the vendored signals.py

import dag  # noqa: E402  (the plugin's lib/dag.py — tests may import it)
import signals  # noqa: E402  (the VENDORED computer — self-contained)


TODAY = date(2026, 6, 17)


# --------------------------------------------------------------------------- #
# Fixture board — a hand-checked dependency + schedule graph.
#
# Edges (blocked_by): 2 blocked-by 1; 3 blocked-by 2; 4 blocked-by 1.
# So #1 blocks {2,3,4} (transitively) and #4 is a release blocker reachable from
# #1 -> #1's blast radius is "Blocks release". #1 itself is open & past target.
# --------------------------------------------------------------------------- #
def board_fixture():
    return {
        "1": {"state": "open", "target": "2026-06-10",          # 7 days late -> Overdue, 1+wk
              "release_blocker": False, "blocked_by": [], "milestone_state": "open"},
        "2": {"state": "open", "target": "2026-06-30",          # future -> not late, blocked by 1
              "release_blocker": False, "blocked_by": ["1"], "milestone_state": "open"},
        "3": {"state": "open", "target": "2026-06-19",          # 2 days out -> At risk (window 3)
              "release_blocker": False, "blocked_by": ["2"], "milestone_state": "open"},
        "4": {"state": "open", "target": "2026-12-01",          # far future, release blocker
              "release_blocker": True, "blocked_by": ["1"], "milestone_state": "open"},
        "5": {"state": "closed", "target": "2026-05-01",        # closed -> Done (ignore lateness)
              "release_blocker": False, "blocked_by": [], "milestone_state": "open"},
    }


# --------------------------------------------------------------------------- #
# fixture board -> expected DETERMINISTIC signal values.
# --------------------------------------------------------------------------- #
class TestSignalValues(unittest.TestCase):
    def setUp(self):
        self.sig = signals.compute_signals(board_fixture(), today=TODAY)

    def test_blocked_flag(self):
        # #2,#3,#4 have OPEN blockers; #1,#5 do not.
        self.assertEqual(self.sig["1"]["blocked"], "Unblocked")
        self.assertEqual(self.sig["2"]["blocked"], "Blocked")
        self.assertEqual(self.sig["3"]["blocked"], "Blocked")
        self.assertEqual(self.sig["4"]["blocked"], "Blocked")
        self.assertEqual(self.sig["5"]["blocked"], "Unblocked")

    def test_blast_radius_and_count(self):
        # #1 transitively blocks {2,3,4}; 4 is a release blocker -> Blocks release.
        self.assertEqual(self.sig["1"]["blast_radius"], "Blocks release")
        self.assertEqual(self.sig["1"]["blast_count"], 3)
        # #2 blocks {3} -> Blocks 1.
        self.assertEqual(self.sig["2"]["blast_radius"], "Blocks 1")
        self.assertEqual(self.sig["2"]["blast_count"], 1)
        # #3,#4,#5 block nothing.
        self.assertEqual(self.sig["3"]["blast_radius"], "Blocks none")
        self.assertEqual(self.sig["3"]["blast_count"], 0)
        self.assertEqual(self.sig["4"]["blast_radius"], "Blocks none")
        self.assertEqual(self.sig["5"]["blast_count"], 0)

    def test_schedule_health(self):
        self.assertEqual(self.sig["1"]["schedule_health"], "Overdue")   # open, 7d past
        self.assertEqual(self.sig["2"]["schedule_health"], "Blocked")   # blocked, not late
        self.assertEqual(self.sig["3"]["schedule_health"], "Blocked")   # blocked wins over At risk
        self.assertEqual(self.sig["4"]["schedule_health"], "Blocked")   # blocked, far target
        self.assertEqual(self.sig["5"]["schedule_health"], "Done")      # closed

    def test_at_risk_when_unblocked_and_near_target(self):
        # An open, UNBLOCKED item whose target is inside the window is At risk.
        b = {"x": {"state": "open", "target": "2026-06-18", "release_blocker": False,
                   "blocked_by": [], "milestone_state": "open"}}
        s = signals.compute_signals(b, today=TODAY)
        self.assertEqual(s["x"]["schedule_health"], "At risk")

    def test_on_track_when_far_out(self):
        b = {"x": {"state": "open", "target": "2026-09-01", "release_blocker": False,
                   "blocked_by": [], "milestone_state": "open"}}
        s = signals.compute_signals(b, today=TODAY)
        self.assertEqual(s["x"]["schedule_health"], "On track")

    def test_slippage_days_and_bucket(self):
        self.assertEqual(self.sig["1"]["slippage_days"], 7)
        self.assertEqual(self.sig["1"]["slippage"], "1+wk")
        self.assertEqual(self.sig["2"]["slippage_days"], 0)
        self.assertEqual(self.sig["2"]["slippage"], "Not late")

    def test_slippage_buckets_exhaustive(self):
        self.assertEqual(signals.slippage_bucket(0), "Not late")
        self.assertEqual(signals.slippage_bucket(1), "1–2d")
        self.assertEqual(signals.slippage_bucket(2), "1–2d")
        self.assertEqual(signals.slippage_bucket(3), "3–5d")
        self.assertEqual(signals.slippage_bucket(5), "3–5d")
        self.assertEqual(signals.slippage_bucket(6), "1+wk")
        self.assertEqual(signals.slippage_bucket(13), "1+wk")
        self.assertEqual(signals.slippage_bucket(14), "2+wk")
        self.assertEqual(signals.slippage_bucket(40), "2+wk")

    def test_closed_blocker_does_not_block(self):
        # If #1 closes, #2/#4 are no longer blocked.
        b = board_fixture()
        b["1"]["state"] = "closed"
        s = signals.compute_signals(b, today=TODAY)
        self.assertEqual(s["2"]["blocked"], "Unblocked")
        self.assertEqual(s["4"]["blocked"], "Unblocked")


# --------------------------------------------------------------------------- #
# DAG cross-check — the VENDORED dag math == lib/dag.compute, edge for edge.
# --------------------------------------------------------------------------- #
class TestDagCrossCheck(unittest.TestCase):
    def _items_for_dag(self, board):
        # lib/dag.compute consumes {blocked_by, state, release_blocker}.
        return {k: {"blocked_by": v["blocked_by"], "state": v["state"],
                    "release_blocker": v["release_blocker"]}
                for k, v in board.items()}

    def test_vendored_matches_lib_dag(self):
        board = board_fixture()
        vendored = signals.dag_signals(board)
        lib = dag.compute(self._items_for_dag(board))
        for k in board:
            self.assertEqual(vendored[k]["blocked"], lib[k]["blocked"], f"blocked@{k}")
            self.assertEqual(vendored[k]["blast_radius"], lib[k]["blast_radius"], f"radius@{k}")
            self.assertEqual(vendored[k]["blast_count"], lib[k]["blast_count"], f"count@{k}")

    def test_cross_check_on_cycle(self):
        # A dependency cycle must not hang either implementation (cycle-safe).
        board = {
            "a": {"blocked_by": ["b"], "state": "open", "release_blocker": False},
            "b": {"blocked_by": ["a"], "state": "open", "release_blocker": False},
        }
        v = signals.dag_signals(board)
        l = dag.compute(board)
        for k in board:
            self.assertEqual(v[k]["blast_count"], l[k]["blast_count"])
            self.assertEqual(v[k]["blocked"], l[k]["blocked"])


# --------------------------------------------------------------------------- #
# rollup fixtures -> expected health enum.
# --------------------------------------------------------------------------- #
class TestRollup(unittest.TestCase):
    def _rollup(self, board, *, rel_closed=None):
        sig = signals.compute_signals(board, today=TODAY)
        if rel_closed is None:
            rel_closed = signals.release_milestone_closed(board)
        return signals.rollup_health(sig, board, release_milestone_closed=rel_closed)

    def test_off_track_on_overdue(self):
        # The full fixture has #1 Overdue -> OFF_TRACK.
        self.assertEqual(self._rollup(board_fixture()), "OFF_TRACK")

    def test_off_track_on_blocked_blocking_release(self):
        # No overdue item, but a Blocked item whose blast radius is Blocks release.
        # #1 blocks release and is itself blocked by an open #0.
        board = {
            "0": {"state": "open", "target": "2026-09-01", "release_blocker": False,
                  "blocked_by": [], "milestone_state": "open"},
            "1": {"state": "open", "target": "2026-09-01", "release_blocker": False,
                  "blocked_by": ["0"], "milestone_state": "open"},
            "2": {"state": "open", "target": "2026-12-01", "release_blocker": True,
                  "blocked_by": ["1"], "milestone_state": "open"},
        }
        sig = signals.compute_signals(board, today=TODAY)
        # #1 is blocked AND its blast radius is Blocks release.
        self.assertEqual(sig["1"]["blocked"], "Blocked")
        self.assertEqual(sig["1"]["blast_radius"], "Blocks release")
        # No item is Overdue here.
        self.assertFalse(any(s["schedule_health"] == "Overdue" for s in sig.values()))
        self.assertEqual(self._rollup(board), "OFF_TRACK")

    def test_at_risk_when_only_at_risk(self):
        board = {
            "1": {"state": "open", "target": "2026-06-18", "release_blocker": False,
                  "blocked_by": [], "milestone_state": "open"},
            "2": {"state": "open", "target": "2026-09-01", "release_blocker": False,
                  "blocked_by": [], "milestone_state": "open"},
        }
        self.assertEqual(self._rollup(board), "AT_RISK")

    def test_complete_when_release_milestone_closed(self):
        board = {
            "1": {"state": "closed", "target": "2026-05-01", "release_blocker": True,
                  "blocked_by": [], "milestone_state": "closed"},
            "2": {"state": "closed", "target": "2026-05-01", "release_blocker": True,
                  "blocked_by": [], "milestone_state": "closed"},
        }
        self.assertEqual(self._rollup(board), "COMPLETE")

    def test_on_track_default(self):
        board = {
            "1": {"state": "open", "target": "2026-09-01", "release_blocker": False,
                  "blocked_by": [], "milestone_state": "open"},
        }
        self.assertEqual(self._rollup(board), "ON_TRACK")

    def test_overdue_beats_complete(self):
        # A closed release milestone but a still-open Overdue item -> OFF_TRACK,
        # not COMPLETE (OFF_TRACK has precedence).
        board = {
            "1": {"state": "closed", "target": "2026-05-01", "release_blocker": True,
                  "blocked_by": [], "milestone_state": "closed"},
            "2": {"state": "open", "target": "2026-06-01", "release_blocker": False,
                  "blocked_by": [], "milestone_state": "open"},
        }
        self.assertEqual(self._rollup(board, rel_closed=True), "OFF_TRACK")

    def test_at_risk_beats_complete(self):
        board = {
            "1": {"state": "closed", "target": "2026-05-01", "release_blocker": True,
                  "blocked_by": [], "milestone_state": "closed"},
            "2": {"state": "open", "target": "2026-06-18", "release_blocker": False,
                  "blocked_by": [], "milestone_state": "open"},
        }
        self.assertEqual(self._rollup(board, rel_closed=True), "AT_RISK")

    def test_body_is_deterministic_one_line(self):
        sig = signals.compute_signals(board_fixture(), today=TODAY)
        health = signals.rollup_health(sig, board_fixture(), release_milestone_closed=False)
        body = signals.rollup_body(health, sig)
        self.assertNotIn("\n", body)
        self.assertIn("OFF_TRACK", body)
        # Same inputs -> identical body every time (no randomness / no AI).
        self.assertEqual(body, signals.rollup_body(health, sig))


# --------------------------------------------------------------------------- #
# ZERO AI calls (grep the workflow + the vendored script).
# --------------------------------------------------------------------------- #
class TestNoAiCalls(unittest.TestCase):
    # Call-site-shaped tokens that would indicate a metered-LLM invocation: a
    # provider SDK import, an inference endpoint, or an LLM API key. (We do NOT
    # forbid the bare words "claude"/"anthropic" — the SKILL.md legitimately
    # pins `model: claude-opus-4-8` and these files' own prose says there is no
    # such call; only a real CALL SITE would carry one of these needles.)
    AI_NEEDLES = [
        "anthropic-ai", "import anthropic", "from anthropic",
        "openai", "x-api-key", "anthropic_api_key", "messages.create",
        "/v1/messages", "/v1/chat/completions", "api.anthropic.com",
        "agent-sdk", "bedrock-runtime", "generativelanguage",
    ]

    def _assert_no_ai(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read().lower()
        for needle in self.AI_NEEDLES:
            self.assertNotIn(
                needle.lower(), text,
                f"{os.path.basename(path)} must contain NO AI call (found {needle!r})",
            )

    def test_workflow_has_no_ai(self):
        self._assert_no_ai(WORKFLOW)

    def test_vendored_script_has_no_ai(self):
        self._assert_no_ai(SIGNALS_PY)

    def test_skill_declares_no_ai(self):
        # The skill is explicit/user-invoked. Its frontmatter legitimately PINS a
        # model (`model: claude-opus-4-8`) for the orchestrating turn, but its
        # WORK is the deterministic script — it must make no AI/model API CALL.
        # So we forbid actual API-endpoint needles (not the `model:` pin) and
        # assert it is disable-model-invocation + points at the vendored script.
        with open(SKILL_MD, "r", encoding="utf-8") as fh:
            text = fh.read()
        lowered = text.lower()
        for needle in ("anthropic-ai", "import anthropic", "from anthropic",
                       "openai", "x-api-key", "anthropic_api_key",
                       "messages.create", "/v1/messages", "agent-sdk"):
            self.assertNotIn(needle.lower(), lowered,
                             f"SKILL.md must make no AI call (found {needle!r})")
        self.assertIn("disable-model-invocation: true", text)
        self.assertIn("signals.py", text)

    def test_run_apply_makes_zero_ai_round_trips(self):
        # Drive the whole --apply orchestration through a fake runner and assert
        # every gh round-trip is a GraphQL/REST call (never an AI endpoint).
        runner = FakeRunner(board_fixture())
        orig = signals.RUN
        signals.RUN = runner
        os.environ["GH_APP_TOKEN"] = "ghs_fakeinstallationtoken1234567890"
        try:
            plan = signals.run("acme", 7, apply=True, today=TODAY)
        finally:
            signals.RUN = orig
            del os.environ["GH_APP_TOKEN"]
        self.assertTrue(plan["applied"])
        # No call body may reference an AI endpoint.
        for call in runner.calls:
            body = " ".join(str(a) for a in call).lower()
            for needle in ("anthropic", "claude", "/v1/messages", "x-api-key"):
                self.assertNotIn(needle, body)


# --------------------------------------------------------------------------- #
# Vendored script offline — fake runner over the real GraphQL surface.
# --------------------------------------------------------------------------- #
class FakeRunner:
    """A fake gh runner: serves the items query + schema query from a board
    fixture, accepts mutations, and records every round-trip. No network."""

    def __init__(self, board):
        self.board = board
        self.calls = []
        self.writes = []
        self.status_updates = []

    def __call__(self, args):
        self.calls.append(list(args))
        body = " ".join(str(a) for a in args)
        if "items(first:100" in body:
            return json.dumps(self._items_response())
        if "fields(first:100" in body:
            return json.dumps(self._schema_response())
        if "updateProjectV2ItemFieldValue" in body:
            self.writes.append(body)
            return json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}})
        if "createProjectV2StatusUpdate" in body:
            self.status_updates.append(body)
            return json.dumps({"data": {"createProjectV2StatusUpdate": {"statusUpdate": {"id": "SU_1"}}}})
        return "{}"

    def _items_response(self):
        nodes = []
        for num, meta in self.board.items():
            nodes.append({
                "id": f"PVTI_{num}",
                "content": {
                    "__typename": "Issue",
                    "number": int(num),
                    "state": meta["state"].upper(),
                    "milestone": {"state": meta.get("milestone_state", "open").upper()},
                    "labels": {"nodes": ([{"name": "release-blocker"}]
                                         if meta.get("release_blocker") else [])},
                    "blockedBy": {"blockedBy": [int(b) for b in meta["blocked_by"]]},
                },
                "targetVal": {"date": meta["target"]},
                "impact": {"name": "Release blocker" if meta.get("release_blocker") else "Low"},
            })
        return {"data": {"organization": {"projectV2": {
            "id": "PVT_proj1",
            "items": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes},
        }}}}

    def _schema_response(self):
        def ss(name, opts):
            return {"__typename": "ProjectV2SingleSelectField", "id": f"F_{name}",
                    "name": name, "dataType": "SINGLE_SELECT",
                    "options": [{"id": f"O_{name}_{i}", "name": o} for i, o in enumerate(opts)]}
        def num(name):
            return {"__typename": "ProjectV2FieldCommon", "id": f"F_{name}",
                    "name": name, "dataType": "NUMBER"}
        fields = [
            ss("Blocked", ["Unblocked", "Blocked"]),
            ss("Blast radius", ["Blocks none", "Blocks 1", "Blocks many", "Blocks release"]),
            num("Blast count"),
            ss("Schedule health", ["On track", "At risk", "Blocked", "Overdue", "Done"]),
            ss("Slippage", ["Not late", "1–2d", "3–5d", "1+wk", "2+wk"]),
            num("Slippage days"),
        ]
        return {"data": {"organization": {"projectV2": {"id": "PVT_proj1",
                "fields": {"nodes": fields}}}}}


class TestVendoredOffline(unittest.TestCase):
    def _drive(self, *, apply, board=None, app_token=True):
        runner = FakeRunner(board or board_fixture())
        orig = signals.RUN
        signals.RUN = runner
        had = os.environ.pop("GH_APP_TOKEN", None)
        if app_token:
            os.environ["GH_APP_TOKEN"] = "ghs_fakeinstallationtoken1234567890"
        try:
            plan = signals.run("acme", 7, apply=apply, today=TODAY)
        finally:
            signals.RUN = orig
            os.environ.pop("GH_APP_TOKEN", None)
            if had is not None:
                os.environ["GH_APP_TOKEN"] = had
        return plan, runner

    def test_plan_writes_nothing(self):
        plan, runner = self._drive(apply=False)
        self.assertFalse(plan["applied"])
        self.assertEqual(runner.writes, [])
        self.assertEqual(runner.status_updates, [])
        # Plan still carries the full computed signals + rollup.
        self.assertEqual(plan["items"], 5)
        self.assertEqual(plan["rollup"]["status"], "OFF_TRACK")
        self.assertEqual(plan["signals"]["1"]["schedule_health"], "Overdue")

    def test_apply_writes_fields_and_posts_status(self):
        plan, runner = self._drive(apply=True)
        self.assertTrue(plan["applied"])
        # 5 items x 6 signal fields = 30 field-value writes.
        self.assertEqual(plan["field_writes"], 30)
        self.assertEqual(len(runner.writes), 30)
        # Exactly one Status update posted, carrying the rolled-up enum.
        self.assertEqual(len(runner.status_updates), 1)
        self.assertIn("OFF_TRACK", runner.status_updates[0])

    def test_apply_refuses_without_app_token(self):
        # constraint #2: a write must NEVER fall back to GITHUB_TOKEN; with no
        # GH_APP_TOKEN the orchestration refuses with the usage code (2).
        with self.assertRaises(signals.SignalsError) as ctx:
            self._drive(apply=True, app_token=False)
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_project_is_not_found(self):
        orig = signals.RUN
        signals.RUN = lambda args: json.dumps({"data": {"organization": {"projectV2": None}}})
        try:
            with self.assertRaises(signals.SignalsError) as ctx:
                signals.load_board("acme", 99)
            self.assertEqual(ctx.exception.code, 3)
        finally:
            signals.RUN = orig


# --------------------------------------------------------------------------- #
# CLI exit codes + secret scrubbing.
# --------------------------------------------------------------------------- #
class TestCli(unittest.TestCase):
    def _main(self, argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = signals.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_plan_exit_0(self):
        orig = signals.RUN
        signals.RUN = FakeRunner(board_fixture())
        try:
            code, out, _ = self._main(["--owner", "acme", "--number", "7", "--plan"])
        finally:
            signals.RUN = orig
        self.assertEqual(code, 0)
        self.assertIn("OFF_TRACK", out)

    def test_usage_error_exit_2(self):
        code, _, _ = self._main(["--plan"])  # missing required --owner/--number
        self.assertEqual(code, 2)

    def test_not_found_exit_3(self):
        orig = signals.RUN
        signals.RUN = lambda args: json.dumps({"data": {"organization": {"projectV2": None}}})
        try:
            code, _, _ = self._main(["--owner", "acme", "--number", "99", "--plan"])
        finally:
            signals.RUN = orig
        self.assertEqual(code, 3)

    def test_unexpected_exit_1(self):
        orig = signals.RUN
        def boom(args):
            raise RuntimeError("kaboom")
        signals.RUN = boom
        try:
            code, _, _ = self._main(["--owner", "acme", "--number", "7", "--plan"])
        finally:
            signals.RUN = orig
        self.assertEqual(code, 1)

    def test_no_token_printed(self):
        # An error whose text carries a token-shaped string must be scrubbed.
        orig = signals.RUN
        def leaky(args):
            raise signals.SignalsError("upstream ghp_leakytoken1234567890abcdefghij")
        signals.RUN = leaky
        try:
            code, out, err = self._main(["--owner", "acme", "--number", "7", "--plan"])
        finally:
            signals.RUN = orig
        self.assertNotIn("ghp_leakytoken1234567890abcdefghij", out + err)
        self.assertIn("[REDACTED]", err)


# --------------------------------------------------------------------------- #
# the WORKFLOW never feeds GITHUB_TOKEN to a Project write.
# --------------------------------------------------------------------------- #
class TestWorkflowAppToken(unittest.TestCase):
    def setUp(self):
        with open(WORKFLOW, "r", encoding="utf-8") as fh:
            self.wf = fh.read()

    def test_uses_app_token_for_writes(self):
        # The script receives GH_APP_TOKEN, minted from the App creds.
        self.assertIn("GH_APP_TOKEN:", self.wf)
        self.assertIn("create-github-app-token", self.wf)

    def test_no_github_token_drives_a_write(self):
        # GITHUB_TOKEN / secrets.GITHUB_TOKEN must NOT be wired into the signals
        # step's env (the script reads GH_APP_TOKEN only).
        # Isolate the run step's env block and assert GITHUB_TOKEN is absent there.
        self.assertNotIn("secrets.GITHUB_TOKEN", self.wf)
        # The script invocation reads GH_APP_TOKEN, never GITHUB_TOKEN.
        self.assertNotIn("GH_APP_TOKEN: ${{ secrets.GITHUB_TOKEN", self.wf)

    def test_no_projects_v2_item_trigger(self):
        # constraint #1: never react to the org-level projects_v2_item webhook.
        # The comment legitimately NAMES it ("We do NOT use ..."), so we forbid
        # the actual TRIGGER form, not the substring: no non-comment line may
        # declare `projects_v2_item:` as an `on:` key.
        for line in self.wf.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # explanatory prose may name it
            self.assertNotIn("projects_v2_item", stripped,
                             "no projects_v2_item trigger (constraint #1)")

    def test_triggers_on_events_and_cron(self):
        self.assertRegex(self.wf, r"on:\s")
        self.assertIn("issues:", self.wf)
        self.assertIn("pull_request:", self.wf)
        self.assertIn("schedule:", self.wf)
        self.assertIn("cron:", self.wf)

    def test_vendored_script_never_reads_github_token(self):
        with open(SIGNALS_PY, "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn('os.environ.get("GITHUB_TOKEN")', src)
        self.assertNotIn("os.environ['GITHUB_TOKEN']", src)


if __name__ == "__main__":
    unittest.main()
