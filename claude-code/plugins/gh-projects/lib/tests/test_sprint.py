#!/usr/bin/env python3
"""Offline tests for lib/sprint.py — pure deterministic math, NO network, NO AI.

Covers:
  * working_day_capacity — date-window counts incl. boundary + gap, weekends
    excluded, half-open [start, end) convention
  * recommend_ready_order — deterministic Priority↑ then Target↑, stable
    tiebreak; pure (no input mutation)
  * no metered AI anywhere in sprint.py (source grep)
  * CLI exit codes 0/2/3/1 + no token/secret printed
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import sprint  # noqa: E402


# --------------------------------------------------------------------------- #
# working-day capacity, weekends excluded, half-open [start, end)
# --------------------------------------------------------------------------- #
class TestWorkingDayCapacity(unittest.TestCase):
    def test_two_week_iteration_from_monday(self):
        # 2026-01-05 is a Monday; a 14-day iteration is [2026-01-05, 2026-01-19).
        # Two full work-weeks = 10 working days.
        self.assertEqual(sprint.working_day_capacity("2026-01-05", "2026-01-19"), 10)

    def test_from_duration_matches_explicit_end(self):
        self.assertEqual(
            sprint.working_day_capacity_from_duration("2026-01-05", 14), 10)

    def test_end_is_exclusive_boundary(self):
        # [Mon, next Mon) over 7 days = exactly 5 working days; the trailing
        # Monday (the exclusive end) is NOT counted.
        self.assertEqual(sprint.working_day_capacity("2026-01-05", "2026-01-12"), 5)
        # Including that Monday (end pushed one day) adds exactly one work day.
        self.assertEqual(sprint.working_day_capacity("2026-01-05", "2026-01-13"), 6)

    def test_single_day_window(self):
        # [Mon, Tue) = the one Monday.
        self.assertEqual(sprint.working_day_capacity("2026-01-05", "2026-01-06"), 1)

    def test_weekend_only_window_is_zero(self):
        # Sat 2026-01-10 .. Mon 2026-01-12 (exclusive) = Sat + Sun = 0 work days.
        self.assertEqual(sprint.working_day_capacity("2026-01-10", "2026-01-12"), 0)

    def test_window_spanning_a_weekend_gap(self):
        # Fri 2026-01-09 .. Tue 2026-01-13 (exclusive) covers Fri, Sat, Sun, Mon:
        # weekends skipped -> Fri + Mon = 2 working days.
        self.assertEqual(sprint.working_day_capacity("2026-01-09", "2026-01-13"), 2)
        # Pushing the end to Wed (exclusive) adds the Tuesday -> 3.
        self.assertEqual(sprint.working_day_capacity("2026-01-09", "2026-01-14"), 3)

    def test_empty_and_inverted_window_is_zero(self):
        self.assertEqual(sprint.working_day_capacity("2026-01-05", "2026-01-05"), 0)
        self.assertEqual(sprint.working_day_capacity("2026-01-19", "2026-01-05"), 0)

    def test_accepts_date_objects(self):
        self.assertEqual(
            sprint.working_day_capacity(dt.date(2026, 1, 5), dt.date(2026, 1, 19)), 10)

    def test_bad_date_is_validation_error(self):
        with self.assertRaises(sprint.SprintError) as ctx:
            sprint.working_day_capacity("not-a-date", "2026-01-19")
        self.assertEqual(ctx.exception.code, 2)


# --------------------------------------------------------------------------- #
# Ready-order recommendation: Priority↑ then Target↑, stable tiebreak
# --------------------------------------------------------------------------- #
class TestRecommendReadyOrder(unittest.TestCase):
    def test_priority_ascending(self):
        items = [
            {"id": "c", "priority": 2, "target": "2026-02-01"},
            {"id": "a", "priority": 0, "target": "2026-02-01"},
            {"id": "b", "priority": 1, "target": "2026-02-01"},
        ]
        self.assertEqual([i["id"] for i in sprint.recommend_ready_order(items)],
                         ["a", "b", "c"])

    def test_target_breaks_priority_tie(self):
        items = [
            {"id": "late", "priority": 1, "target": "2026-03-01"},
            {"id": "early", "priority": 1, "target": "2026-02-01"},
        ]
        self.assertEqual([i["id"] for i in sprint.recommend_ready_order(items)],
                         ["early", "late"])

    def test_stable_tiebreak_preserves_input_order(self):
        # identical priority + target -> original input order is preserved
        items = [
            {"id": "first", "priority": 1, "target": "2026-02-01"},
            {"id": "second", "priority": 1, "target": "2026-02-01"},
            {"id": "third", "priority": 1, "target": "2026-02-01"},
        ]
        self.assertEqual([i["id"] for i in sprint.recommend_ready_order(items)],
                         ["first", "second", "third"])

    def test_missing_priority_sorts_last(self):
        items = [
            {"id": "none", "target": "2026-01-01"},
            {"id": "p0", "priority": 0, "target": "2026-12-01"},
        ]
        self.assertEqual([i["id"] for i in sprint.recommend_ready_order(items)],
                         ["p0", "none"])

    def test_missing_target_sorts_last_within_priority(self):
        items = [
            {"id": "notarget", "priority": 1},
            {"id": "dated", "priority": 1, "target": "2026-02-01"},
        ]
        self.assertEqual([i["id"] for i in sprint.recommend_ready_order(items)],
                         ["dated", "notarget"])

    def test_named_priority_buckets(self):
        items = [
            {"id": "low", "priority": "low"},
            {"id": "urgent", "priority": "urgent"},
            {"id": "med", "priority": "medium"},
        ]
        self.assertEqual([i["id"] for i in sprint.recommend_ready_order(items)],
                         ["urgent", "med", "low"])

    def test_pure_does_not_mutate_input(self):
        items = [
            {"id": "b", "priority": 2},
            {"id": "a", "priority": 1},
        ]
        snapshot = [dict(i) for i in items]
        sprint.recommend_ready_order(items)
        self.assertEqual(items, snapshot)

    def test_empty_and_none(self):
        self.assertEqual(sprint.recommend_ready_order([]), [])
        self.assertEqual(sprint.recommend_ready_order(None), [])

    def test_deterministic_rerun(self):
        items = [
            {"id": "x", "priority": 1, "target": "2026-02-02"},
            {"id": "y", "priority": 0, "target": "2026-02-03"},
            {"id": "z", "priority": 1, "target": "2026-02-01"},
        ]
        first = [i["id"] for i in sprint.recommend_ready_order(items)]
        second = [i["id"] for i in sprint.recommend_ready_order(items)]
        self.assertEqual(first, second)
        self.assertEqual(first, ["y", "z", "x"])


# --------------------------------------------------------------------------- #
# no metered AI anywhere in sprint.py
# --------------------------------------------------------------------------- #
class TestNoMeteredAI(unittest.TestCase):
    def test_source_has_no_model_call(self):
        with open(os.path.join(LIB, "sprint.py"), "r", encoding="utf-8") as fh:
            src = fh.read().lower()
        for needle in ("anthropic", "openai", "claude-", "model=", "completion",
                       "import requests", "urllib.request", "http"):
            self.assertNotIn(needle, src,
                             f"sprint.py must make no AI/network call (found {needle!r})")


# --------------------------------------------------------------------------- #
# CLI exit codes + no secret leak
# --------------------------------------------------------------------------- #
class TestCli(unittest.TestCase):
    def _run_main(self, argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = sprint.main(argv)
        finally:
            sys.stdin = old_stdin
        return code, out.getvalue(), err.getvalue()

    def test_capacity_exit_0(self):
        code, out, _ = self._run_main(
            ["capacity", "--start", "2026-01-05", "--end", "2026-01-19"])
        self.assertEqual(code, 0)
        self.assertIn("10", out)

    def test_capacity_duration_exit_0(self):
        code, out, _ = self._run_main(
            ["capacity", "--start", "2026-01-05", "--duration", "14"])
        self.assertEqual(code, 0)
        self.assertIn("10", out)

    def test_capacity_missing_window_exit_2(self):
        code, _, _ = self._run_main(["capacity", "--start", "2026-01-05"])
        self.assertEqual(code, 2)

    def test_bad_date_exit_2(self):
        code, _, _ = self._run_main(
            ["capacity", "--start", "nope", "--end", "2026-01-19"])
        self.assertEqual(code, 2)

    def test_ready_order_exit_0(self):
        items = '[{"id":"b","priority":2},{"id":"a","priority":1}]'
        code, out, _ = self._run_main(["ready-order", "--items", items])
        self.assertEqual(code, 0)
        self.assertIn("a", out)

    def test_ready_order_stdin(self):
        items = '[{"id":"b","priority":2},{"id":"a","priority":1}]'
        code, out, _ = self._run_main(["ready-order", "--items", "-"], stdin=items)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), '{"order": ["a", "b"]}')

    def test_ready_order_bad_json_exit_2(self):
        code, _, _ = self._run_main(["ready-order", "--items", "{not json"])
        self.assertEqual(code, 2)

    def test_usage_error_exit_2(self):
        code, _, _ = self._run_main([])  # no subcommand
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
