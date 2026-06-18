#!/usr/bin/env python3
"""Offline tests for the `plan-sprint` skill — NO network, NO
live org, NO mutation. Everything is exercised against an injected fake `gh`
runner (the CountingRunner / WriteVerbRunner pattern) and pure date fixtures.

plan-sprint OWNS the scheduling fields (Sprint/Milestone/Start/Target) + Ready
order. It REUSES the lib verbs (`gh.set_milestone`, `gh.reorder_item`) and the
sprint math (`sprint.working_day_capacity`, `sprint.recommend_ready_order`) —
this module does not re-implement them. The ONE new piece of logic plan-sprint
needs is **active-iteration selection**, which the skill cannot place in `lib/`
(it must not edit lib). So the rule is documented in SKILL.md and proven here by a
SELF-CONTAINED pure helper (`active_iteration`) that mirrors the documented rule.
A shared helper, if ever wanted, belongs in `lib/sprint.py`.

Covers:
  - active Iteration computed offline from the field config —
    in-window / gap (next-upcoming) / boundary fixtures → expected iteration;
    Milestone + dates set via the engine (set_milestone reused).
  - working-day capacity vs assigned load → over-allocation WARNING emitted,
    plan still previewed (advisory, not a hard block).
  - reorder the Ready queue to recommend_ready_order via reorder_item, in the
    recommended order (top, then each --after the previous).
  - dry-by-default — no write verb runs without --force; --force writes.
  - frontmatter: disable-model-invocation true, model claude-opus-4-8, effort high,
    and NO guard hooks block (the guard excludes plan-sprint).
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import gh  # noqa: E402  (reuse write verbs — set_milestone, reorder_item)
import sprint  # noqa: E402  (reuse math — working_day_capacity, recommend_ready_order)

PLUGIN_ROOT = os.path.dirname(LIB)
SKILL_PATH = os.path.join(PLUGIN_ROOT, "skills", "plan-sprint", "SKILL.md")


def _q(args):
    return " ".join(str(a) for a in args)


# --------------------------------------------------------------------------- #
# Self-contained ACTIVE-ITERATION helper (the one new piece of plan-sprint
# logic). The skill must NOT edit lib/, so the rule lives here, mirroring the
# documented SKILL.md rule exactly. Pure function of (iterations, today):
#   * each iteration spans the HALF-OPEN window [startDate, startDate+duration)
#   * completed iterations are excluded (only the live `iterations` list)
#   * today in a window  -> that iteration
#   * today in a gap     -> the NEXT upcoming iteration (smallest startDate > today)
#   * stable order by startDate ascending
# Returns the iteration dict, or None if none is active/upcoming.
# --------------------------------------------------------------------------- #
def _parse(d) -> _dt.date:
    return d if isinstance(d, _dt.date) else _dt.date.fromisoformat(str(d)[:10])


def active_iteration(iterations, today):
    today = _parse(today)
    ordered = sorted(
        (it for it in (iterations or []) if it.get("startDate")),
        key=lambda it: _parse(it["startDate"]),
    )
    # 1) today inside some half-open window -> that iteration
    for it in ordered:
        start = _parse(it["startDate"])
        end = start + _dt.timedelta(days=int(it.get("duration", 0) or 0))
        if start <= today < end:
            return it
    # 2) gap (or before the first) -> next upcoming (smallest start strictly > today)
    for it in ordered:
        if _parse(it["startDate"]) > today:
            return it
    # 3) nothing upcoming -> no active iteration
    return None


# A three-iteration config with a deliberate GAP between iter B and iter C.
#   A: 2026-06-01 .. 2026-06-15  (14d, half-open -> ends 06-15 exclusive)
#   B: 2026-06-15 .. 2026-06-29  (adjacent, no gap with A)
#   <gap 2026-06-29 .. 2026-07-06>
#   C: 2026-07-06 .. 2026-07-20
_ITERS = [
    {"id": "IT_A", "title": "Sprint A", "startDate": "2026-06-01", "duration": 14},
    {"id": "IT_B", "title": "Sprint B", "startDate": "2026-06-15", "duration": 14},
    {"id": "IT_C", "title": "Sprint C", "startDate": "2026-07-06", "duration": 14},
]


# --------------------------------------------------------------------------- #
# Fake runner — mirrors WriteVerbRunner for the verbs plan-sprint calls
# (set_milestone reads/writes the issue; reorder_item rides gh api graphql).
# --------------------------------------------------------------------------- #
class SprintRunner:
    def __init__(self, *, milestone=None):
        self.calls = []
        self.milestone = milestone

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)
        if "api -X GET" in body and "/issues/" in body:
            ms = {"number": self.milestone} if self.milestone is not None else None
            return '{"milestone": %s, "assignees": []}' % ("null" if ms is None else '{"number": %d}' % self.milestone)
        if "api -X PATCH" in body and "/issues/" in body:
            return '{"ok": true}'
        if "updateProjectV2ItemPosition" in body:
            return '{"data": {"updateProjectV2ItemPosition": {"items": {"totalCount": 3}}}}'
        return "{}"

    def count(self, predicate):
        return sum(1 for c in self.calls if predicate(_q(c)))


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = gh.RUN

    def tearDown(self):
        gh.RUN = self._orig


# --------------------------------------------------------------------------- #
# Active Iteration computed offline (in-window / gap / boundary)
# --------------------------------------------------------------------------- #
class TestActiveIteration(Base):
    def test_today_in_window_picks_that_iteration(self):
        # 2026-06-20 falls inside Sprint B [06-15, 06-29)
        it = active_iteration(_ITERS, "2026-06-20")
        self.assertEqual(it["id"], "IT_B")

    def test_today_in_gap_picks_next_upcoming(self):
        # 2026-07-01 is in the gap between B (ends 06-29) and C (starts 07-06)
        # -> next upcoming is Sprint C
        it = active_iteration(_ITERS, "2026-07-01")
        self.assertEqual(it["id"], "IT_C")

    def test_boundary_start_is_inclusive(self):
        # 06-15 is the exclusive END of A and the inclusive START of B -> B wins
        it = active_iteration(_ITERS, "2026-06-15")
        self.assertEqual(it["id"], "IT_B")

    def test_boundary_end_is_exclusive(self):
        # 06-29 is the exclusive end of B and start of the gap -> next upcoming C
        it = active_iteration(_ITERS, "2026-06-29")
        self.assertEqual(it["id"], "IT_C")

    def test_before_first_picks_first_upcoming(self):
        it = active_iteration(_ITERS, "2026-05-01")
        self.assertEqual(it["id"], "IT_A")

    def test_after_last_is_none(self):
        # past the end of the last live iteration, nothing upcoming
        self.assertIsNone(active_iteration(_ITERS, "2026-08-01"))

    def test_completed_iterations_excluded(self):
        # only the live `iterations` list is passed in; a completed-only config
        # (e.g. all windows in the past) yields no active iteration.
        past = [{"id": "OLD", "title": "Old", "startDate": "2026-01-01", "duration": 14}]
        self.assertIsNone(active_iteration(past, "2026-06-20"))


# --------------------------------------------------------------------------- #
# Milestone + dates set via the engine (reused gh.set_milestone)
# --------------------------------------------------------------------------- #
class TestSchedulingWrites(Base):
    def test_milestone_assigned_via_engine_verb(self):
        runner = SprintRunner(milestone=None)
        gh.RUN = runner
        res = gh.set_milestone("acme/web", 42, 7)
        self.assertTrue(res["changed"])
        self.assertEqual(runner.count(lambda q: "api -X PATCH" in q), 1)

    def test_milestone_reassign_same_is_noop(self):
        runner = SprintRunner(milestone=7)
        gh.RUN = runner
        res = gh.set_milestone("acme/web", 42, 7)
        self.assertFalse(res["changed"])
        self.assertEqual(runner.count(lambda q: "api -X PATCH" in q), 0)


# --------------------------------------------------------------------------- #
# Capacity vs load: over-allocation WARNS, plan still previewed
# --------------------------------------------------------------------------- #
class TestCapacityWarning(Base):
    def _plan_capacity_vs_load(self, iteration, issues):
        """Mirror the SKILL's advisory capacity check: capacity is the
        working-day count of the active iteration's half-open window; load is the
        number of issues assigned. Returns (capacity, load, over_allocated, plan).
        The plan is ALWAYS produced (capacity does not hard-block)."""
        start = _dt.date.fromisoformat(iteration["startDate"])
        end = start + _dt.timedelta(days=int(iteration["duration"]))
        capacity = sprint.working_day_capacity(start, end)
        load = len(issues)
        plan = {"iteration": iteration["id"], "assign": [i["id"] for i in issues]}
        return capacity, load, load > capacity, plan

    def test_over_allocation_warns_but_previews(self):
        # Sprint B: 14-day half-open window -> 10 working days capacity.
        issues = [{"id": f"I{n}"} for n in range(12)]  # load 12 > capacity 10
        cap, load, over, plan = self._plan_capacity_vs_load(_ITERS[1], issues)
        self.assertEqual(cap, 10)
        self.assertEqual(load, 12)
        self.assertTrue(over, "12 issues over a 10-working-day sprint is over-allocated")
        # advisory: the plan is still produced in full (no hard block)
        self.assertEqual(len(plan["assign"]), 12)

    def test_within_capacity_no_warning(self):
        issues = [{"id": f"I{n}"} for n in range(8)]  # load 8 <= capacity 10
        cap, load, over, plan = self._plan_capacity_vs_load(_ITERS[1], issues)
        self.assertEqual(cap, 10)
        self.assertFalse(over)
        self.assertEqual(len(plan["assign"]), 8)


# --------------------------------------------------------------------------- #
# Reorder Ready queue to recommend_ready_order, in recommended order
# --------------------------------------------------------------------------- #
class TestReadyReorder(Base):
    def test_reorder_calls_in_recommended_order(self):
        # An out-of-order Ready queue; recommend_ready_order sorts Priority↑,Target↑.
        items = [
            {"id": "C", "priority": "P2", "target": "2026-07-01"},
            {"id": "A", "priority": "P0", "target": "2026-06-20"},
            {"id": "B", "priority": "P1", "target": "2026-06-25"},
        ]
        order = [it["id"] for it in sprint.recommend_ready_order(items)]
        self.assertEqual(order, ["A", "B", "C"])

        runner = SprintRunner()
        gh.RUN = runner
        # Apply: first recommended item to TOP (no --after), then each after the
        # previous — exactly the SKILL's reorder loop.
        prev = None
        for iid in order:
            gh.reorder_item("PVT_p", iid, prev)
            prev = iid

        pos = [c for c in runner.calls if "updateProjectV2ItemPosition" in _q(c)]
        self.assertEqual(len(pos), 3)
        # A goes to the top (no afterId literal in the TOP mutation)
        self.assertIn("item=A", _q(pos[0]))
        self.assertNotIn("afterId:$after", _q(pos[0]))
        # B after A, C after B
        self.assertIn("after=A", _q(pos[1]))
        self.assertIn("after=B", _q(pos[2]))

    def test_reorder_rides_app_token_graphql_path(self):
        # The reorder is a Projects v2 write over `gh api graphql`
        # (App token via the engine), never GITHUB_TOKEN.
        runner = SprintRunner()
        gh.RUN = runner
        gh.reorder_item("PVT_p", "X", None)
        call = next(c for c in runner.calls if "updateProjectV2ItemPosition" in _q(c))
        self.assertEqual(call[0], "api")
        self.assertEqual(call[1], "graphql")
        self.assertNotIn("GITHUB_TOKEN", _q(call))


# --------------------------------------------------------------------------- #
# Dry-by-default: no write verb runs without --force; --force writes.
# Exercised against the real engine.sh rail (the seam plan-sprint calls).
# --------------------------------------------------------------------------- #
class TestDryByDefault(unittest.TestCase):
    ENGINE = os.path.join(LIB, "engine.sh")

    def _run(self, argv):
        import subprocess
        return subprocess.run(["bash", self.ENGINE, *argv],
                              capture_output=True, text=True)

    def test_dry_run_does_not_execute_write_verb(self):
        # set-milestone without --force: the engine previews and exits 0 WITHOUT
        # invoking gh.py (so no GET/PATCH against the issue happens).
        proc = self._run(["set-milestone", "--repo", "acme/web",
                          "--number", "42", "--milestone", "7"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertIn("pass --force", proc.stderr)

    def test_dry_run_reorder_is_preview_only(self):
        proc = self._run(["reorder-item", "--project-id", "PVT_p",
                          "--item", "ITEM_1"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertIn("pass --force", proc.stderr)


# --------------------------------------------------------------------------- #
# Frontmatter assertions — model/effort/disable-model-invocation + NO guard.
# The guard explicitly EXCLUDES plan-sprint (it neither merges nor
# deploys), so the PreToolUse guard.sh block must NOT be present.
# --------------------------------------------------------------------------- #
class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        with open(SKILL_PATH, "r", encoding="utf-8") as fh:
            self.text = fh.read()
        # isolate the YAML frontmatter block (between the first two `---` fences)
        parts = self.text.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "SKILL.md must have YAML frontmatter")
        self.fm = parts[1]

    def test_disable_model_invocation_true(self):
        self.assertIn("disable-model-invocation: true", self.fm)

    def test_model_is_opus(self):
        self.assertIn("model: claude-opus-4-8", self.fm)

    def test_effort_high(self):
        self.assertIn("effort: high", self.fm)

    def test_name_is_plan_sprint(self):
        self.assertIn("name: plan-sprint", self.fm)

    def test_no_guard_hooks_block(self):
        # The guard excludes plan-sprint: no PreToolUse hook / guard.sh wiring anywhere.
        self.assertNotIn("guard.sh", self.text)
        self.assertNotIn("PreToolUse", self.text)
        self.assertNotIn("hooks:", self.fm)

    def test_least_privilege_allowed_tools(self):
        # mirrors scaffold-repo/sync-signals; plan-sprint shells python3/bash only
        # (no direct `gh` — it goes through engine.sh), plus Read + AskUserQuestion.
        self.assertIn("allowed-tools:", self.fm)
        self.assertIn("Bash(python3 *)", self.fm)
        self.assertIn("Bash(bash *)", self.fm)
        self.assertNotIn("Bash(gh *)", self.fm)


if __name__ == "__main__":
    unittest.main()
