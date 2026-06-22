#!/usr/bin/env python3
"""Offline tests for lib/analysis.py — the ranked-findings engine.

NO network, NO live org, NO mutation. The pure core `compute_findings` is driven
on crafted fixtures; the read-seam fetch is driven through a fake `RUN` that
serves a canned board read and records every round-trip (so we can prove the
engine NEVER issues a write).

Covers:
  * each finding kind fires on a crafted fixture, carries machine-checkable
    evidence + a resolving-skill action
  * STABLE ordering — shuffling the input items yields the identical output order
  * the engine is read-only — the fetch path makes no write-shaped round-trip, and
    compute_findings/rollup_counts perform no I/O
  * analyze-sprint capacity reuse produces the expected working-day numbers
  * CLI exit-code map 0/2/3/1 + no token printed
  * the two analyze SKILL.md files are model-invocable, pin model+effort, declare
    read-only allowed-tools, and analyze-board references both rules files
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
PLUGIN = os.path.dirname(LIB)
sys.path.insert(0, LIB)

import analysis  # noqa: E402
import sprint  # noqa: E402

BOARD_SKILL = os.path.join(PLUGIN, "skills", "analyze-board", "SKILL.md")
SPRINT_SKILL = os.path.join(PLUGIN, "skills", "analyze-sprint", "SKILL.md")

TODAY = date(2026, 6, 17)


# --------------------------------------------------------------------------- #
# A board snapshot fixture that fires EVERY finding kind exactly once.
# --------------------------------------------------------------------------- #
def snapshot_fixture():
    return [
        # #10 — release-blocker that is itself blocked -> critical_chain.
        {"number": 10, "status": "In Progress", "type": "Feature", "size": "M",
         "target": "2026-07-01", "assignees": ["alice"], "has_ac_table": True,
         "schedule_health": "Blocked", "blast_radius": "Blocks release",
         "blocked": "Blocked", "impact": "Release blocker",
         "decision_needed": "No decision", "blocked_by": [19]},
        # #20 — overdue AND high blast radius -> overdue_high_blast.
        {"number": 20, "status": "In Progress", "type": "Feature", "size": "L",
         "target": "2026-06-01", "assignees": ["bob"], "has_ac_table": True,
         "schedule_health": "Overdue", "blast_radius": "Blocks many",
         "blocked": "Unblocked", "impact": "High",
         "decision_needed": "No decision", "blocked_by": []},
        # #30 — At risk epic with incomplete sub-issues -> stalled_epic.
        {"number": 30, "status": "In Progress", "type": "Epic", "size": "L",
         "target": "2026-06-25", "assignees": ["carol"], "has_ac_table": True,
         "sub_issues_total": 5, "sub_issues_done": 2,
         "schedule_health": "At risk", "blast_radius": "Blocks 1",
         "blocked": "Unblocked", "impact": "Medium",
         "decision_needed": "No decision", "blocked_by": []},
        # #40 — Ready but missing AC table + Size + Target -> intake_hygiene.
        {"number": 40, "status": "Ready", "type": "Feature", "size": None,
         "target": None, "assignees": ["dave"], "has_ac_table": False,
         "schedule_health": "On track", "blast_radius": "Blocks none",
         "blocked": "Unblocked", "impact": "Low",
         "decision_needed": "No decision", "blocked_by": []},
        # #50 — in-sprint with no assignee -> unassigned_in_sprint.
        {"number": 50, "status": "In Progress", "type": "Feature", "size": "S",
         "target": "2026-07-10", "assignees": [], "has_ac_table": True,
         "schedule_health": "On track", "blast_radius": "Blocks none",
         "blocked": "Unblocked", "impact": "Low",
         "decision_needed": "No decision", "blocked_by": []},
        # #60 — Decision needed = Move date -> decision_needed.
        {"number": 60, "status": "In Progress", "type": "Feature", "size": "M",
         "target": "2026-07-05", "assignees": ["alice"], "has_ac_table": True,
         "schedule_health": "At risk", "blast_radius": "Blocks none",
         "blocked": "Unblocked", "impact": "Low",
         "decision_needed": "Move date", "blocked_by": []},
        # #70 — clean item that fires NOTHING (Done, assigned, all set).
        {"number": 70, "status": "Done", "type": "Feature", "size": "S",
         "target": "2026-05-01", "assignees": ["bob"], "has_ac_table": True,
         "schedule_health": "Done", "blast_radius": "Blocks none",
         "blocked": "Unblocked", "impact": "Low",
         "decision_needed": "No decision", "blocked_by": []},
    ]


def _by_kind(findings):
    out = {}
    for f in findings:
        out.setdefault(f["kind"], []).append(f)
    return out


# --------------------------------------------------------------------------- #
# Each finding kind fires + carries evidence + a resolving-skill action.
# --------------------------------------------------------------------------- #
class TestFindingKinds(unittest.TestCase):
    def setUp(self):
        self.findings = analysis.compute_findings(snapshot_fixture(), today=TODAY)
        self.by_kind = _by_kind(self.findings)

    def test_every_kind_fires_exactly_once(self):
        for kind in (analysis.KIND_CRITICAL_CHAIN, analysis.KIND_OVERDUE_HIGH_BLAST,
                     analysis.KIND_STALLED_EPIC, analysis.KIND_INTAKE_HYGIENE,
                     analysis.KIND_UNASSIGNED_IN_SPRINT, analysis.KIND_DECISION_NEEDED):
            self.assertEqual(len(self.by_kind.get(kind, [])), 1,
                             f"{kind} must fire exactly once on the fixture")

    def test_clean_item_fires_nothing(self):
        # #70 is Done + clean — it must not appear in any finding.
        self.assertFalse(any(f["number"] == "70" for f in self.findings))

    def test_critical_chain_routes_to_start_issue_on_the_blocker(self):
        f = self.by_kind[analysis.KIND_CRITICAL_CHAIN][0]
        self.assertEqual(f["number"], "10")
        self.assertEqual(f["evidence"]["blocked_by"], ["19"])
        self.assertEqual(f["evidence"]["impact"], "Release blocker")
        self.assertEqual(f["action"]["skill"], analysis.SKILL_START_ISSUE)
        self.assertIn("19", f["action"]["args"])  # the upstream blocker

    def test_overdue_high_blast_routes_to_plan_sprint(self):
        f = self.by_kind[analysis.KIND_OVERDUE_HIGH_BLAST][0]
        self.assertEqual(f["number"], "20")
        self.assertEqual(f["evidence"]["schedule_health"], "Overdue")
        self.assertEqual(f["evidence"]["blast_radius"], "Blocks many")
        self.assertEqual(f["action"]["skill"], analysis.SKILL_PLAN_SPRINT)

    def test_stalled_epic_carries_progress_and_routes_to_plan_sprint(self):
        f = self.by_kind[analysis.KIND_STALLED_EPIC][0]
        self.assertEqual(f["number"], "30")
        self.assertEqual(f["evidence"]["sub_issues_done"], 2)
        self.assertEqual(f["evidence"]["sub_issues_total"], 5)
        self.assertEqual(f["action"]["skill"], analysis.SKILL_PLAN_SPRINT)

    def test_intake_hygiene_lists_gaps_and_routes_to_create_issues(self):
        f = self.by_kind[analysis.KIND_INTAKE_HYGIENE][0]
        self.assertEqual(f["number"], "40")
        self.assertEqual(set(f["evidence"]["missing"]),
                         {"AC table", "Size", "Target date"})
        self.assertEqual(f["action"]["skill"], analysis.SKILL_CREATE_ISSUES)

    def test_unassigned_in_sprint_routes_to_plan_sprint(self):
        f = self.by_kind[analysis.KIND_UNASSIGNED_IN_SPRINT][0]
        self.assertEqual(f["number"], "50")
        self.assertEqual(f["evidence"]["assignees"], [])
        self.assertEqual(f["action"]["skill"], analysis.SKILL_PLAN_SPRINT)

    def test_decision_needed_records_the_named_option_no_skill(self):
        f = self.by_kind[analysis.KIND_DECISION_NEEDED][0]
        self.assertEqual(f["number"], "60")
        self.assertEqual(f["evidence"]["decision_needed"], "Move date")
        # No skill resolves a PM/CTO product call — the action names the move owed.
        self.assertIsNone(f["action"]["skill"])
        self.assertEqual(f["action"]["note"], "Move date")

    def test_every_finding_has_evidence_and_an_action(self):
        for f in self.findings:
            self.assertIn("evidence", f)
            self.assertIn(f["number"], f["evidence"].get("number", ""))
            self.assertIn("action", f)
            self.assertIn("skill", f["action"])  # skill key always present (may be None)

    def test_critical_chain_also_fires_on_blast_release_without_impact(self):
        # A release-blocker by Blast radius (not Impact) that is blocked still fires.
        snap = [{"number": 5, "status": "In Progress", "blast_radius": "Blocks release",
                 "blocked": "Blocked", "impact": "Low", "blocked_by": [4]}]
        f = _by_kind(analysis.compute_findings(snap, today=TODAY))
        self.assertIn(analysis.KIND_CRITICAL_CHAIN, f)

    def test_unblocked_release_blocker_is_not_critical_chain(self):
        snap = [{"number": 5, "status": "In Progress", "impact": "Release blocker",
                 "blocked": "Unblocked", "blocked_by": []}]
        f = _by_kind(analysis.compute_findings(snap, today=TODAY))
        self.assertNotIn(analysis.KIND_CRITICAL_CHAIN, f)


# --------------------------------------------------------------------------- #
# Stable ordering — shuffling the input yields the identical output order.
# --------------------------------------------------------------------------- #
class TestStableOrdering(unittest.TestCase):
    def _order(self, items):
        return [(f["severity"], f["number"], f["kind"])
                for f in analysis.compute_findings(items, today=TODAY)]

    def test_shuffle_input_identical_output_order(self):
        import random
        base = snapshot_fixture()
        expected = self._order(base)
        for seed in range(8):
            shuffled = list(base)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(self._order(shuffled), expected,
                             f"order must be stable under shuffle (seed {seed})")

    def test_rerun_is_identical(self):
        base = snapshot_fixture()
        self.assertEqual(self._order(base), self._order(base))

    def test_sorted_by_severity_then_number(self):
        order = self._order(snapshot_fixture())
        # severity is non-decreasing across the ranked list.
        sevs = [s for (s, _n, _k) in order]
        self.assertEqual(sevs, sorted(sevs))

    def test_same_severity_breaks_by_issue_number(self):
        # Two intake-hygiene findings (same severity) sort by issue number.
        # Assigned so the in-sprint-unassigned finding does not also fire.
        snap = [
            {"number": 200, "status": "Ready", "has_ac_table": False, "size": None,
             "target": None, "assignees": ["alice"]},
            {"number": 100, "status": "Ready", "has_ac_table": False, "size": None,
             "target": None, "assignees": ["alice"]},
        ]
        hygiene = [f["number"] for f in analysis.compute_findings(snap, today=TODAY)
                   if f["kind"] == analysis.KIND_INTAKE_HYGIENE]
        self.assertEqual(hygiene, ["100", "200"])


# --------------------------------------------------------------------------- #
# Rollup counts (pure).
# --------------------------------------------------------------------------- #
class TestRollupCounts(unittest.TestCase):
    def test_counts(self):
        c = analysis.rollup_counts(snapshot_fixture())
        self.assertEqual(c["items"], 7)
        self.assertEqual(c["overdue"], 1)   # #20
        self.assertEqual(c["at_risk"], 2)   # #30, #60
        self.assertEqual(c["blocked"], 1)   # #10
        self.assertEqual(c["decisions_owed"], 1)  # #60


# --------------------------------------------------------------------------- #
# READ-ONLY: the fetch path makes no write-shaped round-trip; the core has no I/O.
# --------------------------------------------------------------------------- #
class FakeReadRunner:
    """A fake gh runner that serves the read-only board query and records every
    round-trip. It refuses to model any mutation — if the engine ever issued one
    the test would catch the write-shaped body."""

    WRITE_NEEDLES = (
        "mutation", "updateprojectv2itemfieldvalue", "createprojectv2statusupdate",
        "addprojectv2itembyid", "createlinkedbranch", "-x post", "-x patch",
        "-x put", "-x delete", "issue edit",
    )

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        body = " ".join(str(a) for a in args)
        if "items(first:100" in body:
            return json.dumps(self._items_response())
        return "{}"

    def writes(self):
        out = []
        for c in self.calls:
            low = " ".join(str(a) for a in c).lower()
            if any(n in low for n in self.WRITE_NEEDLES):
                out.append(low)
        return out

    def _items_response(self):
        nodes = []
        for it in self.snapshot:
            nodes.append({
                "content": {
                    "__typename": "Issue",
                    "number": int(it["number"]),
                    "body": ("## Acceptance Criteria\n| AC | end-state |\n|--|--|\n| 1 | x |"
                             if it.get("has_ac_table") else "some prose"),
                    "issueType": {"name": it.get("type", "")},
                    "assignees": {"nodes": [{"login": a} for a in it.get("assignees", [])]},
                    "subIssuesSummary": {"total": it.get("sub_issues_total", 0),
                                         "completed": it.get("sub_issues_done", 0)},
                    "blockedBy": {"blockedBy": [int(b) for b in it.get("blocked_by", [])]},
                },
                "status": {"name": it.get("status", "")},
                "size": {"name": it["size"]} if it.get("size") else None,
                "target": {"date": it.get("target")} if it.get("target") else None,
                "health": {"name": it.get("schedule_health", "")},
                "blast": {"name": it.get("blast_radius", "")},
                "blockedField": {"name": it.get("blocked", "")},
                "impact": {"name": it.get("impact", "")},
                "decision": {"name": it.get("decision_needed", "No decision")},
            })
        return {"data": {"organization": {"projectV2": {
            "id": "PVT_proj1",
            "items": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                      "nodes": nodes}}}}}


class TestReadOnly(unittest.TestCase):
    def setUp(self):
        self._orig = analysis.RUN

    def tearDown(self):
        analysis.RUN = self._orig

    def test_fetch_path_issues_no_write(self):
        runner = FakeReadRunner(snapshot_fixture())
        analysis.RUN = runner
        result = analysis.run("acme", 7, today=TODAY)
        self.assertEqual(runner.writes(), [],
                         "the analysis engine must issue NO write round-trip")
        # The live read reproduces the same findings as the pure core.
        direct = analysis.compute_findings(snapshot_fixture(), today=TODAY)
        self.assertEqual([f["kind"] for f in result["findings"]],
                         [f["kind"] for f in direct])

    def test_core_does_no_io(self):
        # compute_findings + rollup_counts run with NO RUN seam available at all,
        # proving they perform no I/O.
        analysis.RUN = lambda args: (_ for _ in ()).throw(
            AssertionError("compute_findings must not call RUN"))
        analysis.compute_findings(snapshot_fixture(), today=TODAY)
        analysis.rollup_counts(snapshot_fixture())

    def test_load_board_reads_signal_values_and_ac_table(self):
        runner = FakeReadRunner(snapshot_fixture())
        analysis.RUN = runner
        snap = analysis.load_board("acme", 7)
        by_num = {it["number"]: it for it in snap}
        self.assertTrue(by_num["10"]["has_ac_table"])
        self.assertFalse(by_num["40"]["has_ac_table"])  # prose-only body
        self.assertEqual(by_num["10"]["impact"], "Release blocker")
        self.assertEqual(by_num["60"]["decision_needed"], "Move date")

    def test_missing_project_is_not_found(self):
        analysis.RUN = lambda args: json.dumps(
            {"data": {"organization": {"projectV2": None}}})
        with self.assertRaises(analysis.AnalysisError) as ctx:
            analysis.load_board("acme", 99)
        self.assertEqual(ctx.exception.code, 3)


# --------------------------------------------------------------------------- #
# analyze-sprint capacity reuse — the working-day engine produces expected nums.
# --------------------------------------------------------------------------- #
class TestSprintCapacityReuse(unittest.TestCase):
    def test_two_week_iteration_capacity(self):
        # analyze-sprint reuses sprint.working_day_capacity — a 14-day iteration
        # from a Monday is 10 working days.
        self.assertEqual(
            sprint.working_day_capacity_from_duration("2026-01-05", 14), 10)

    def test_capacity_matches_explicit_window(self):
        self.assertEqual(
            sprint.working_day_capacity("2026-01-05", "2026-01-19"), 10)


# --------------------------------------------------------------------------- #
# No metered AI anywhere in analysis.py (source grep).
# --------------------------------------------------------------------------- #
class TestNoMeteredAI(unittest.TestCase):
    def test_source_has_no_model_call(self):
        with open(os.path.join(LIB, "analysis.py"), "r", encoding="utf-8") as fh:
            src = fh.read().lower()
        for needle in ("anthropic", "openai", "x-api-key", "messages.create",
                       "/v1/messages", "/v1/chat/completions", "agent-sdk",
                       "import requests", "urllib.request"):
            self.assertNotIn(needle, src,
                             f"analysis.py must make no AI call (found {needle!r})")


# --------------------------------------------------------------------------- #
# CLI exit codes + no secret leak.
# --------------------------------------------------------------------------- #
class TestCli(unittest.TestCase):
    def _run_main(self, argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = analysis.main(argv)
        finally:
            sys.stdin = old_stdin
        return code, out.getvalue(), err.getvalue()

    def test_snapshot_stdin_exit_0(self):
        snap = json.dumps(snapshot_fixture())
        code, out, _ = self._run_main(["--snapshot", "-", "--today", "2026-06-17"],
                                      stdin=snap)
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["counts"]["items"], 7)
        self.assertTrue(result["findings"])

    def test_live_read_exit_0(self):
        orig = analysis.RUN
        analysis.RUN = FakeReadRunner(snapshot_fixture())
        try:
            code, out, _ = self._run_main(
                ["--owner", "acme", "--number", "7", "--today", "2026-06-17"])
        finally:
            analysis.RUN = orig
        self.assertEqual(code, 0)
        self.assertIn("findings", out)

    def test_missing_args_exit_2(self):
        code, _, _ = self._run_main([])  # no --owner/--number and no --snapshot
        self.assertEqual(code, 2)

    def test_bad_snapshot_json_exit_2(self):
        code, _, _ = self._run_main(["--snapshot", "-"], stdin="{not json")
        self.assertEqual(code, 2)

    def test_bad_today_exit_2(self):
        code, _, _ = self._run_main(["--snapshot", "-", "--today", "nope"],
                                    stdin="[]")
        self.assertEqual(code, 2)

    def test_not_found_exit_3(self):
        orig = analysis.RUN
        analysis.RUN = lambda args: json.dumps(
            {"data": {"organization": {"projectV2": None}}})
        try:
            code, _, _ = self._run_main(["--owner", "acme", "--number", "99"])
        finally:
            analysis.RUN = orig
        self.assertEqual(code, 3)

    def test_unexpected_exit_1(self):
        orig = analysis.RUN
        def boom(args):
            raise RuntimeError("kaboom")
        analysis.RUN = boom
        try:
            code, _, _ = self._run_main(["--owner", "acme", "--number", "7"])
        finally:
            analysis.RUN = orig
        self.assertEqual(code, 1)

    def test_no_token_printed(self):
        orig = analysis.RUN
        def leaky(args):
            raise analysis.AnalysisError("upstream ghp_leakytoken1234567890abcdef")
        analysis.RUN = leaky
        try:
            code, out, err = self._run_main(["--owner", "acme", "--number", "7"])
        finally:
            analysis.RUN = orig
        self.assertNotIn("ghp_leakytoken1234567890abcdef", out + err)
        self.assertIn("[REDACTED]", err)


# --------------------------------------------------------------------------- #
# The two analyze SKILL.md files — model-invocable, read-only, rules-cited.
# --------------------------------------------------------------------------- #
class TestSkillFrontmatter(unittest.TestCase):
    def _fm(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        parts = text.split("---", 2)
        return (parts[1] if len(parts) >= 3 else ""), text

    def test_model_invocable_not_disabled(self):
        # Read-only analyze skills are model-invocable: NO disable-model-invocation.
        for path in (BOARD_SKILL, SPRINT_SKILL):
            fm, _ = self._fm(path)
            self.assertNotRegex(fm, r"(?m)^disable-model-invocation:",
                                f"{os.path.basename(os.path.dirname(path))} "
                                "must be model-invocable")

    def test_pins_model_and_effort(self):
        for path in (BOARD_SKILL, SPRINT_SKILL):
            fm, _ = self._fm(path)
            self.assertRegex(fm, r"(?m)^model:\s*claude-opus-4-8\s*$")
            self.assertRegex(fm, r"(?m)^effort:\s*high\s*$")

    def test_allowed_tools_are_read_only(self):
        # No field-write verb, no `gh issue edit`, no engine --force/--apply, and
        # gh is restricted to read GETs (`gh api *`), not the full gh surface.
        for path in (BOARD_SKILL, SPRINT_SKILL):
            fm, text = self._fm(path)
            self.assertRegex(fm, r"(?m)^allowed-tools:\s")
            tools_line = next(l for l in fm.splitlines()
                              if l.strip().startswith("allowed-tools:"))
            self.assertIn("Bash(python3 *)", tools_line)
            self.assertIn("Bash(gh api *)", tools_line)
            # No broad gh, no write verbs in the allowed-tools line.
            self.assertNotIn("Bash(gh *)", tools_line)
            self.assertNotIn("gh issue edit", tools_line)
            self.assertNotIn("write-field", tools_line)
            # The skill body must not invoke a write verb or --force/--apply.
            for forbidden in ("gh issue edit", "write-field", "--force", "--apply",
                              "createProjectV2StatusUpdate", "set-field"):
                self.assertNotIn(forbidden, text,
                                 f"{os.path.basename(os.path.dirname(path))} "
                                 f"must not invoke {forbidden!r} (read-only)")

    def test_analyze_board_references_both_rules(self):
        fm, _ = self._fm(BOARD_SKILL)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md", fm)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/rules/composition.md", fm)

    def test_names_match_dirs(self):
        fm_b, _ = self._fm(BOARD_SKILL)
        fm_s, _ = self._fm(SPRINT_SKILL)
        self.assertRegex(fm_b, r"(?m)^name:\s*analyze-board\s*$")
        self.assertRegex(fm_s, r"(?m)^name:\s*analyze-sprint\s*$")


if __name__ == "__main__":
    unittest.main()
