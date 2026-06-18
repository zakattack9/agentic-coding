#!/usr/bin/env python3
"""Offline tests for lib/pm.py — PM-#### monotonic allocator (AC-5) + flow-style
front-matter round-trip property test (AC-5). Stdlib only, no network."""
from __future__ import annotations

import io
import json
import os
import random
import sys
import tempfile
import unittest
from collections import OrderedDict
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import pm  # noqa: E402


class TestAllocator(unittest.TestCase):
    def test_monotonic_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, "registry.json")
            ids = [pm.allocate_id(reg, "PM") for _ in range(5)]
        self.assertEqual(ids, ["PM-0001", "PM-0002", "PM-0003", "PM-0004", "PM-0005"])

    def test_strictly_increasing_and_unique(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, "registry.json")
            nums = [int(pm.allocate_id(reg, "PM").split("-")[1]) for _ in range(50)]
        self.assertEqual(nums, sorted(nums))
        self.assertEqual(len(nums), len(set(nums)))

    def test_persists_across_fresh_loads(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, "registry.json")
            self.assertEqual(pm.allocate_id(reg), "PM-0001")
            # A fresh call re-reads the file (simulates a new process).
            self.assertEqual(pm.allocate_id(reg), "PM-0002")
            with open(reg) as fh:
                self.assertEqual(json.load(fh)["next"], 3)

    def test_custom_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, "registry.json")
            self.assertEqual(pm.allocate_id(reg, "GH"), "GH-0001")

    def test_corrupt_registry_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, "registry.json")
            with open(reg, "w") as fh:
                json.dump({"prefix": "PM", "next": 0}, fh)
            with self.assertRaises(pm.PmError):
                pm.allocate_id(reg)


# --------------------------------------------------------------------------- #
# AC-5 — front-matter round-trips flow-style collections without loss
# --------------------------------------------------------------------------- #
class TestFrontMatterRoundTrip(unittest.TestCase):
    def test_known_shapes(self):
        data = OrderedDict([
            ("id", "PM-0042"),
            ("title", "Wire the board: sync, signals & more"),  # colon + commas
            ("type", "Feature"),
            ("tier", "T3"),
            ("size", "L"),
            ("depends_on", ["PM-0001", "PM-0002"]),
            ("blocked_by", []),
            ("labels", ["area:board", "release:v1.4"]),
            ("board", OrderedDict([("owner", "acme"), ("number", 7)])),
            ("priority", "P0"),
            ("done", True),
            ("archived", False),
            ("spec", None),
        ])
        text = pm.compose(data, "Body stays.\n")
        parsed, body = pm.split_front_matter(text)
        self.assertEqual(parsed, data)
        self.assertEqual(body.strip(), "Body stays.")

    def test_body_preserved(self):
        data = OrderedDict([("id", "PM-0001")])
        body = "## Acceptance Criteria\n\n| AC | Criterion |\n|----|-----------|\n| 1 | X is true |\n"
        text = pm.compose(data, body)
        _parsed, out_body = pm.split_front_matter(text)
        self.assertIn("| 1 | X is true |", out_body)

    def test_property_random_records(self):
        rng = random.Random(20260617)
        words = ["alpha", "beta", "P0", "T1", "T2", "T3", "S", "M", "L",
                 "acme/web", "PM-0001", "Feature", "Bug", "Infra"]
        for _ in range(200):
            data = OrderedDict()
            data["id"] = f"PM-{rng.randint(1, 9999):04d}"  # always present (normalize needs it)
            n = rng.randint(0, 6)
            for k in range(n):
                key = f"k{k}"
                roll = rng.random()
                if roll < 0.35:
                    data[key] = rng.choice(words)
                elif roll < 0.5:
                    data[key] = rng.randint(-50, 5000)
                elif roll < 0.6:
                    data[key] = rng.choice([True, False])
                elif roll < 0.7:
                    data[key] = None
                elif roll < 0.85:
                    data[key] = [rng.choice(words) for _ in range(rng.randint(0, 4))]
                else:
                    data[key] = OrderedDict(
                        (f"s{i}", rng.choice(words)) for i in range(rng.randint(0, 3))
                    )
            text = pm.compose(data, "body\n")
            parsed, _ = pm.split_front_matter(text)
            self.assertEqual(parsed, data, f"round-trip lost data for {data!r}")

    def test_special_chars_quoted(self):
        data = OrderedDict([("id", "PM-1"), ("title", "a: b, c [x] {y}")])
        parsed, _ = pm.split_front_matter(pm.compose(data, ""))
        self.assertEqual(parsed["title"], "a: b, c [x] {y}")


# --------------------------------------------------------------------------- #
# AC-3 (pm.py share) — exit codes + normalize
# --------------------------------------------------------------------------- #
class TestPmCli(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pm.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_new_id_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            reg = os.path.join(d, "registry.json")
            code, out, _ = self._run(["new-id", "--registry", reg])
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), "PM-0001")

    def test_read_missing_exit_3(self):
        code, _, _ = self._run(["read", "/no/such/file.md"])
        self.assertEqual(code, 3)

    def test_set_usage_exit_2(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("---\nid: PM-1\n---\nbody\n")
            path = f.name
        try:
            code, _, _ = self._run(["set", path])  # no KEY=VALUE
            self.assertEqual(code, 2)
        finally:
            os.unlink(path)

    def test_normalize_lifts_scalar_to_list(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("---\nid: PM-1\ndepends_on: PM-0\n---\nb\n")
            path = f.name
        try:
            code, out, _ = self._run(["normalize", path])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["depends_on"], ["PM-0"])
        finally:
            os.unlink(path)

    def test_normalize_requires_id_exit_2(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("---\ntitle: no id\n---\nb\n")
            path = f.name
        try:
            code, _, _ = self._run(["normalize", path])
            self.assertEqual(code, 2)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
