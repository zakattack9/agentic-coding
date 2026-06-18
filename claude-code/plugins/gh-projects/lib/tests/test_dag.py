#!/usr/bin/env python3
"""Offline tests for lib/dag.py — Blocked / Blast radius / Blast-count derived
from native blocked-by edges, matched against a HAND-CHECKED fixture.

Fixture graph (edge `blocked_by[A]=[B]` means "B blocks A"):

    REL  (release_blocker=True)
     ^
     |  blocked_by REL <- A        (A blocks REL)
    A <- B           (B blocks A)
    A <- C           (C blocks A)
    D                (isolated; blocks nothing, blocked by nothing)
    E <- F (closed)  (F is closed, so E is NOT blocked)

Reversed (blocks) edges:
    B -> A ;  C -> A ;  A -> REL ;  F -> E (but F closed, dropped)

Downstream (transitive "blocks") sets:
    B: {A, REL}      -> count 2, reaches release blocker -> "Blocks release"
    C: {A, REL}      -> count 2, reaches release blocker -> "Blocks release"
    A: {REL}         -> count 1, REL is release blocker  -> "Blocks release"
    REL: {}          -> count 0                          -> "None"
    D: {}            -> count 0                          -> "None"
    E: {}            -> count 0                          -> "None"
    F: {} (closed)   -> count 0                          -> "None"

Blocked (>=1 OPEN blocker):
    A: blocked_by [B,C] both open  -> yes
    REL: blocked_by [A] open       -> yes
    E: blocked_by [F] but F closed -> no
    B,C,D,F: no blockers           -> no
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import dag  # noqa: E402

FIXTURE = {
    "REL": {"blocked_by": ["A"], "state": "open", "release_blocker": True},
    "A": {"blocked_by": ["B", "C"], "state": "open"},
    "B": {"blocked_by": [], "state": "open"},
    "C": {"blocked_by": [], "state": "open"},
    "D": {"blocked_by": [], "state": "open"},
    "E": {"blocked_by": ["F"], "state": "open"},
    "F": {"blocked_by": [], "state": "closed"},
}

EXPECTED = {
    "REL": {"blocked": True, "blast_radius": "None", "blast_count": 0},
    "A": {"blocked": True, "blast_radius": "Blocks release", "blast_count": 1},
    "B": {"blocked": False, "blast_radius": "Blocks release", "blast_count": 2},
    "C": {"blocked": False, "blast_radius": "Blocks release", "blast_count": 2},
    "D": {"blocked": False, "blast_radius": "None", "blast_count": 0},
    "E": {"blocked": False, "blast_radius": "None", "blast_count": 0},
    "F": {"blocked": False, "blast_radius": "None", "blast_count": 0},
}


class TestDagFixture(unittest.TestCase):
    def test_compute_matches_hand_checked(self):
        self.assertEqual(dag.compute(FIXTURE), EXPECTED)

    def test_signals_for_each_item(self):
        for item_id, expected in EXPECTED.items():
            self.assertEqual(dag.signals_for(item_id, FIXTURE), expected, item_id)

    def test_blocks_many_without_release(self):
        # X blocks Y and Z (neither a release blocker) -> "Blocks many", count 2.
        g = {
            "X": {"blocked_by": [], "state": "open"},
            "Y": {"blocked_by": ["X"], "state": "open"},
            "Z": {"blocked_by": ["X"], "state": "open"},
        }
        self.assertEqual(dag.signals_for("X", g),
                         {"blocked": False, "blast_radius": "Blocks many", "blast_count": 2})

    def test_blocks_one(self):
        g = {"P": {"blocked_by": [], "state": "open"},
             "Q": {"blocked_by": ["P"], "state": "open"}}
        self.assertEqual(dag.signals_for("P", g),
                         {"blocked": False, "blast_radius": "Blocks 1", "blast_count": 1})

    def test_cycle_is_safe(self):
        g = {"A": {"blocked_by": ["B"], "state": "open"},
             "B": {"blocked_by": ["A"], "state": "open"}}
        out = dag.compute(g)  # must terminate, not recurse forever
        self.assertEqual(out["A"]["blast_count"], 1)
        self.assertEqual(out["B"]["blast_count"], 1)
        self.assertTrue(out["A"]["blocked"])

    def test_diamond_dedup_count(self):
        # X blocks Y and Z; both block W. X's downstream = {Y,Z,W} = 3 distinct.
        g = {
            "X": {"blocked_by": [], "state": "open"},
            "Y": {"blocked_by": ["X"], "state": "open"},
            "Z": {"blocked_by": ["X"], "state": "open"},
            "W": {"blocked_by": ["Y", "Z"], "state": "open"},
        }
        self.assertEqual(dag.signals_for("X", g)["blast_count"], 3)

    def test_unknown_blocker_id_ignored(self):
        g = {"A": {"blocked_by": ["GHOST"], "state": "open"}}
        self.assertEqual(dag.signals_for("A", g),
                         {"blocked": False, "blast_radius": "None", "blast_count": 0})

    def test_no_ai_in_source(self):
        # Deterministic: no model call, no network import.
        with open(os.path.join(LIB, "dag.py"), "r", encoding="utf-8") as fh:
            src = fh.read().lower()
        for needle in ("anthropic", "openai", "claude", "import requests", "urllib.request"):
            self.assertNotIn(needle, src, f"dag.py must be deterministic (found {needle!r})")

    def test_no_label_based_dependency_in_source(self):
        # The DAG derives from native blocked-by edges only — never from labels.
        with open(os.path.join(LIB, "dag.py"), "r", encoding="utf-8") as fh:
            src = fh.read().lower()
        for needle in ('"labels"', "'labels'", "get(\"labels\")", "label:", "add-label"):
            self.assertNotIn(needle, src,
                             f"dag.py must not derive dependencies from labels (found {needle!r})")


class TestDagCli(unittest.TestCase):
    def _run(self, argv, stdin=None):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        old = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = dag.main(argv)
        finally:
            sys.stdin = old
        return code, out.getvalue(), err.getvalue()

    def test_stdin_compute_exit_0(self):
        code, out, _ = self._run([], stdin=json.dumps(FIXTURE))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), EXPECTED)

    def test_single_item(self):
        code, out, _ = self._run(["--item", "B"], stdin=json.dumps(FIXTURE))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), EXPECTED["B"])

    def test_empty_input_exit_2(self):
        code, _, _ = self._run([], stdin="")
        self.assertEqual(code, 2)

    def test_bad_json_exit_2(self):
        code, _, _ = self._run([], stdin="{not json")
        self.assertEqual(code, 2)

    def test_missing_file_exit_3(self):
        code, _, _ = self._run(["/no/such/graph.json"])
        self.assertEqual(code, 3)

    def test_unknown_item_exit_3(self):
        code, _, _ = self._run(["--item", "NOPE"], stdin=json.dumps(FIXTURE))
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
