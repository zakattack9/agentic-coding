#!/usr/bin/env python3
"""Offline tests for lib/gh.py — NO network, NO live org, NO mutation.

Every test installs a fake RUN that returns canned JSON and counts round-trips,
so the whole GraphQL/REST surface is exercised deterministically. Verifies
resolve+cache (1 resolve for 2 lookups), the two-phase round-trip, exit codes +
no token/secret printed, and the capability probe both ways + no label
dependency fallback.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import gh  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake command runner: dispatch on the gh argv, return canned JSON, count calls.
# --------------------------------------------------------------------------- #
PROJECT_RESOLVE = {
    "data": {
        "organization": {
            "projectV2": {
                "id": "PVT_proj1",
                "title": "Golden",
                "fields": {
                    "nodes": [
                        {"__typename": "ProjectV2FieldCommon", "id": "F_status", "name": "Status",
                         "dataType": "SINGLE_SELECT",
                         "options": [
                             {"id": "OPT_inprog", "name": "In Progress", "description": ""},
                             {"id": "OPT_done", "name": "Done", "description": ""},
                         ]},
                        {"__typename": "ProjectV2FieldCommon", "id": "F_pmid", "name": "PM-ID",
                         "dataType": "TEXT"},
                        {"__typename": "ProjectV2FieldCommon", "id": "F_blast", "name": "Blast count",
                         "dataType": "NUMBER"},
                        {"__typename": "ProjectV2IterationField", "id": "F_sprint", "name": "Sprint",
                         "configuration": {
                             "iterations": [{"id": "IT_1", "title": "Sprint 1",
                                             "startDate": "2026-01-01", "duration": 14}],
                             "completedIterations": [],
                         }},
                    ]
                },
            }
        }
    }
}


def _q(args):
    """The query/body string of a gh api/graphql invocation (for dispatch)."""
    return " ".join(str(a) for a in args)


class CountingRunner:
    """A fake gh runner that returns canned JSON keyed by the operation and
    counts every round-trip (so "1 resolve for 2 lookups" is testable)."""

    def __init__(self):
        self.calls = []
        self.item_value = None  # last written field value, for read-back

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)
        # --- resolve (the fields query) ---
        if "projectV2(number:" in body or "fields(first:100)" in body:
            return json.dumps(PROJECT_RESOLVE)
        # --- addProjectV2ItemById ---
        if "addProjectV2ItemById" in body:
            return json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": "ITEM_1"}}}})
        # --- updateProjectV2ItemFieldValue ---
        if "updateProjectV2ItemFieldValue" in body:
            # capture the written option/number/text for read-back fidelity
            if "singleSelectOptionId:" in body:
                self.item_value = ("optionId", body.split('singleSelectOptionId:"')[1].split('"')[0])
            elif "number:" in body:
                self.item_value = ("number", float(body.split("number:")[1].split("}")[0]))
            elif "text:" in body:
                self.item_value = ("text", body.split('text:"')[1].split('"}')[0])
            return json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_1"}}}})
        # --- read-back ---
        if "fieldValueByName" in body or "ProjectV2ItemFieldSingleSelectValue" in body:
            kind, val = self.item_value
            node = {"id": "ITEM_1", "fieldValueByName": {"nodes": [
                {"__typename": "x",
                 ("optionId" if kind == "optionId" else kind): val,
                 "field": {"id": self._last_field_id()}},
            ]}}
            return json.dumps({"data": {"node": node}})
        return "{}"

    def _last_field_id(self):
        # the field id is carried in the readback variables (-F field=...)
        for c in reversed(self.calls):
            for a in c:
                if str(a).startswith("field=F_"):
                    return str(a).split("=", 1)[1]
        return "F_status"

    def count(self, predicate):
        return sum(1 for c in self.calls if predicate(_q(c)))


class HelpRunner:
    """Fake runner that serves `--help` text to exercise capability probing."""

    def __init__(self, *, blocked_by=True, develop=True):
        self.blocked_by = blocked_by
        self.develop = develop
        self.native_calls = []

    def __call__(self, args):
        body = _q(args)
        if "--help" in body:
            if "issue edit" in body:
                flags = ["--title", "--body", "--add-label"]
                if self.blocked_by:
                    flags.append("--add-blocked-by")
                return "Edit issue. Flags:\n" + "\n".join(flags)
            if "issue develop" in body:
                if self.develop:
                    return "Manage linked branches for an issue.\n  --name string"
                raise gh.GhError("unknown command develop")
            return ""
        # a real (native) mutation call — record it
        self.native_calls.append(list(args))
        return ""


class GhTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_run = gh.RUN

    def tearDown(self):
        gh.RUN = self._orig_run


# --------------------------------------------------------------------------- #
# resolve + cache: 1 resolve serves 2 lookups
# --------------------------------------------------------------------------- #
class TestResolveCache(GhTestBase):
    def test_one_resolve_for_two_lookups(self):
        runner = CountingRunner()
        gh.RUN = runner
        proj = gh.Project("acme", 7).resolve()

        # Two distinct lookups in the same run.
        self.assertEqual(proj.field_id("Status"), "F_status")
        self.assertEqual(proj.option_id("Status", "In Progress"), "OPT_inprog")
        self.assertEqual(proj.iteration_id("Sprint", "Sprint 1"), "IT_1")

        resolves = runner.count(lambda q: "fields(first:100)" in q)
        self.assertEqual(resolves, 1, "two+ lookups must reuse one cached resolve")

    def test_resolve_idempotent(self):
        runner = CountingRunner()
        gh.RUN = runner
        proj = gh.Project("acme", 7)
        proj.resolve()
        proj.resolve()  # second call must NOT round-trip
        self.assertEqual(runner.count(lambda q: "fields(first:100)" in q), 1)

    def test_missing_project_is_not_found(self):
        gh.RUN = lambda args: json.dumps({"data": {"organization": {"projectV2": None}}})
        with self.assertRaises(gh.GhError) as ctx:
            gh.Project("acme", 99).resolve()
        self.assertEqual(ctx.exception.code, 3)


# --------------------------------------------------------------------------- #
# two-phase add -> update -> read-back identical
# --------------------------------------------------------------------------- #
class TestTwoPhaseWrite(GhTestBase):
    def test_single_select_round_trip(self):
        runner = CountingRunner()
        gh.RUN = runner
        proj = gh.Project("acme", 7).resolve()
        result = gh.write_field(proj, "I_kj…content", "Status", "In Progress")
        self.assertTrue(result["verified"])
        self.assertEqual(result["value"], "OPT_inprog")
        # Sequence: add -> update -> readback (in that order).
        seq = [_q(c) for c in runner.calls]
        add_i = next(i for i, q in enumerate(seq) if "addProjectV2ItemById" in q)
        upd_i = next(i for i, q in enumerate(seq) if "updateProjectV2ItemFieldValue" in q)
        rb_i = next(i for i, q in enumerate(seq) if "ProjectV2ItemFieldSingleSelectValue" in q)
        self.assertLess(add_i, upd_i)
        self.assertLess(upd_i, rb_i)

    def test_number_round_trip(self):
        runner = CountingRunner()
        gh.RUN = runner
        proj = gh.Project("acme", 7).resolve()
        item = gh.add_item(proj.id, "content")
        res = gh.set_field(proj, item, "Blast count", 3)
        self.assertTrue(res["verified"])
        self.assertEqual(res["value"], 3.0)

    def test_text_round_trip(self):
        runner = CountingRunner()
        gh.RUN = runner
        proj = gh.Project("acme", 7).resolve()
        item = gh.add_item(proj.id, "content")
        res = gh.set_field(proj, item, "PM-ID", "PM-0042")
        self.assertTrue(res["verified"])
        self.assertEqual(res["value"], "PM-0042")

    def test_readback_mismatch_raises(self):
        runner = CountingRunner()
        gh.RUN = runner
        proj = gh.Project("acme", 7).resolve()
        item = gh.add_item(proj.id, "content")
        # Corrupt the read-back so it differs from what we wrote.
        orig = runner.__call__

        def tamper(args):
            out = orig(args)
            if "ProjectV2ItemFieldTextValue" in _q(args):
                d = json.loads(out)
                d["data"]["node"]["fieldValueByName"]["nodes"][0]["text"] = "WRONG"
                return json.dumps(d)
            return out

        gh.RUN = tamper
        with self.assertRaises(gh.GhError):
            gh.set_field(proj, item, "PM-ID", "PM-0042")


# --------------------------------------------------------------------------- #
# monotonic status advance
# --------------------------------------------------------------------------- #
class TestMonotonicStatus(unittest.TestCase):
    def test_advances_forward(self):
        self.assertEqual(gh.advance_status("In Progress", "In Review"), "In Review")

    def test_stale_event_is_noop(self):
        self.assertIsNone(gh.advance_status("On Staging", "In Progress"))

    def test_same_stage_is_noop(self):
        self.assertIsNone(gh.advance_status("Done", "Done"))

    def test_reopen_regresses(self):
        self.assertEqual(gh.advance_status("Done", "In Progress", reopen=True), "In Progress")

    def test_first_write_from_none(self):
        self.assertEqual(gh.advance_status(None, "Backlog"), "Backlog")


# --------------------------------------------------------------------------- #
# diff before mutate (iteration + option ID stability)
# --------------------------------------------------------------------------- #
class TestSchemaDiff(unittest.TestCase):
    def test_iterations_skip_when_unchanged(self):
        existing = [{"title": "S1", "startDate": "2026-01-01", "duration": 14}]
        desired = [{"title": "S1", "startDate": "2026-01-01", "duration": 14}]
        self.assertFalse(gh.iterations_need_update(existing, desired))

    def test_iterations_update_when_changed(self):
        existing = [{"title": "S1", "startDate": "2026-01-01", "duration": 14}]
        desired = existing + [{"title": "S2", "startDate": "2026-01-15", "duration": 14}]
        self.assertTrue(gh.iterations_need_update(existing, desired))

    def test_options_skip_when_unchanged(self):
        ex = [{"name": "S", "description": ""}, {"name": "M", "description": ""}]
        self.assertFalse(gh.options_need_update(ex, list(ex)))

    def test_options_update_when_changed(self):
        ex = [{"name": "S", "description": ""}]
        des = ex + [{"name": "L", "description": ""}]
        self.assertTrue(gh.options_need_update(ex, des))


# --------------------------------------------------------------------------- #
# capability probe both ways; native preferred when present, else GraphQL
# --------------------------------------------------------------------------- #
class TestCapabilityProbe(GhTestBase):
    def test_blocked_by_native_when_present(self):
        runner = HelpRunner(blocked_by=True)
        gh.RUN = runner
        caps = gh.Capabilities()
        self.assertTrue(caps.has("add_blocked_by"))
        res = gh.add_blocked_by("acme/web", 12, 7, caps=caps)
        self.assertEqual(res["via"], "native")
        # Native path actually invoked `gh issue edit --add-blocked-by`.
        self.assertTrue(any("--add-blocked-by" in _q(c) for c in runner.native_calls))

    def test_blocked_by_graphql_when_absent(self):
        runner = HelpRunner(blocked_by=False)

        captured = {}

        def fake(args):
            body = _q(args)
            if "--help" in body:
                return runner(args)
            captured["graphql"] = body
            return json.dumps({"data": {"addIssueDependency": {"issue": {"id": "x"}}}})

        gh.RUN = fake
        caps = gh.Capabilities()
        self.assertFalse(caps.has("add_blocked_by"))
        res = gh.add_blocked_by("acme/web", 12, 7, caps=caps)
        self.assertEqual(res["via"], "graphql")
        self.assertIn("addIssueDependency", captured["graphql"])

    def test_linked_branch_probe_both_ways(self):
        gh.RUN = HelpRunner(develop=True)
        self.assertTrue(gh.Capabilities().has("linked_branch"))
        gh.RUN = HelpRunner(develop=False)
        self.assertFalse(gh.Capabilities().has("linked_branch"))

    def test_capability_cached(self):
        runner = HelpRunner(blocked_by=True)
        # count help round-trips
        n = {"c": 0}
        orig = runner.__call__

        def counting(args):
            if "--help" in _q(args):
                n["c"] += 1
            return orig(args)

        gh.RUN = counting
        caps = gh.Capabilities()
        caps.has("add_blocked_by")
        caps.has("add_blocked_by")
        self.assertEqual(n["c"], 1, "capability probe must cache (one --help)")


# --------------------------------------------------------------------------- #
# NO label-based dependency fallback exists anywhere in gh.py
# --------------------------------------------------------------------------- #
class TestNoLabelDependencyFallback(unittest.TestCase):
    def test_source_has_no_label_dependency_fallback(self):
        with open(os.path.join(LIB, "gh.py"), "r", encoding="utf-8") as fh:
            src = fh.read()
        lowered = src.lower()
        # No code path that turns a dependency into a `type:`/`blocked`/`dep` label.
        for needle in ("add-label", "add_label", "--label", "type:label", "blocked-label"):
            # allow the word "label" only in comments forbidding it; assert no
            # label MUTATION verb is present.
            self.assertNotIn(needle, lowered,
                             f"gh.py must contain no label-based fallback (found {needle!r})")


# --------------------------------------------------------------------------- #
# App token, never GITHUB_TOKEN
# --------------------------------------------------------------------------- #
class TestAppToken(GhTestBase):
    def test_injected_token_used(self):
        os.environ["GH_APP_TOKEN"] = "ghs_injectedinstallationtoken1234567890"
        try:
            self.assertEqual(gh.get_app_token(), "ghs_injectedinstallationtoken1234567890")
        finally:
            del os.environ["GH_APP_TOKEN"]

    def test_no_creds_is_usage_error(self):
        saved = {k: os.environ.pop(k, None) for k in
                 ("GH_APP_TOKEN", "APP_ID", "APP_PRIVATE_KEY", "APP_PRIVATE_KEY_PATH")}
        try:
            with self.assertRaises(gh.GhError) as ctx:
                gh.get_app_token()
            self.assertEqual(ctx.exception.code, 2)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_github_token_never_read(self):
        # GITHUB_TOKEN present, no App creds -> still a usage error (never used).
        saved = {k: os.environ.pop(k, None) for k in
                 ("GH_APP_TOKEN", "APP_ID", "APP_PRIVATE_KEY", "APP_PRIVATE_KEY_PATH")}
        os.environ["GITHUB_TOKEN"] = "ghp_thisistheforbiddentoken1234567890"
        try:
            with self.assertRaises(gh.GhError):
                gh.get_app_token()
        finally:
            del os.environ["GITHUB_TOKEN"]
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_source_never_uses_github_token_for_writes(self):
        with open(os.path.join(LIB, "gh.py"), "r", encoding="utf-8") as fh:
            src = fh.read()
        # GITHUB_TOKEN may only appear in get_app_token's refusal comment, never
        # as an os.environ read feeding a token return.
        self.assertNotIn('os.environ.get("GITHUB_TOKEN")', src)
        self.assertNotIn("os.environ['GITHUB_TOKEN']", src)


# --------------------------------------------------------------------------- #
# exit codes for each entrypoint + secret scan (prints no token)
# --------------------------------------------------------------------------- #
class TestExitCodesAndSecretScan(GhTestBase):
    def _run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gh.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_resolve_ok_exit_0(self):
        gh.RUN = CountingRunner()
        code, out, _ = self._run_main(["resolve", "--owner", "acme", "--number", "7"])
        self.assertEqual(code, 0)
        self.assertIn("PVT_proj1", out)

    def test_usage_error_exit_2(self):
        code, _, _ = self._run_main(["resolve"])  # missing required args
        self.assertEqual(code, 2)

    def test_not_found_exit_3(self):
        gh.RUN = lambda args: json.dumps({"data": {"organization": {"projectV2": None}}})
        code, _, err = self._run_main(["resolve", "--owner", "acme", "--number", "99"])
        self.assertEqual(code, 3)

    def test_unexpected_exit_1(self):
        def boom(args):
            raise RuntimeError("kaboom")

        gh.RUN = boom
        code, _, _ = self._run_main(["resolve", "--owner", "acme", "--number", "7"])
        self.assertEqual(code, 1)

    def test_token_command_redacts(self):
        os.environ["GH_APP_TOKEN"] = "ghs_supersecretinstallationtoken1234567890"
        try:
            code, out, err = self._run_main(["token"])
        finally:
            del os.environ["GH_APP_TOKEN"]
        self.assertEqual(code, 0)
        self.assertNotIn("ghs_supersecretinstallationtoken1234567890", out + err)
        self.assertIn("[REDACTED]", out)

    def test_secret_scan_no_token_in_any_output(self):
        # Drive an error whose stderr carries a token-shaped string; assert the
        # printed output is scrubbed.
        def leaky(args):
            raise gh.GhError("upstream said ghp_leakytoken1234567890abcdefghijklmnop")

        gh.RUN = leaky
        code, out, err = self._run_main(["resolve", "--owner", "acme", "--number", "7"])
        self.assertNotIn("ghp_leakytoken1234567890abcdefghijklmnop", out + err)
        self.assertIn("[REDACTED]", err)

    def test_capabilities_exit_0(self):
        gh.RUN = HelpRunner()
        code, out, _ = self._run_main(["capabilities"])
        self.assertEqual(code, 0)
        self.assertIn("add_blocked_by", out)


if __name__ == "__main__":
    unittest.main()
