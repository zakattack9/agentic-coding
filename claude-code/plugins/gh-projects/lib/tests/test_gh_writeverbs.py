#!/usr/bin/env python3
"""Offline tests for lib/gh.py's write verbs — NO network, NO
live org, NO mutation. Every test installs a fake RUN that returns canned JSON
and counts round-trips.

Covers:
  open_or_update_pr — non-closing `Relates to #N`; create -> edit round-trip
  pr_check_state — green / red / pending verdicts
  set_milestone — assign + re-assign = ONE effective write (idempotent)
  reorder_item — position mutation calls (top vs after)
  set_assignee — add/remove + idempotency
  merge_pr — --merge/--rebase only, never --squash (bad method -> code 2)
  App-token path for the Projects v2 (reorder) write
  CLI surface exit codes 0/2/3/1 + no secret leak
  NO closing keyword anywhere in the PR path (grep + runtime guard)
  "second call is a no-op" for every idempotent verb
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


def _q(args):
    return " ".join(str(a) for a in args)


class WriteVerbRunner:
    """Fake gh runner for the write verbs: dispatches on argv, returns canned
    JSON, and records every call so round-trips and write counts are testable.

    State the tests can preset:
      * existing_pr   — dict {number,url} returned by `gh pr list --head`, or None
      * check_states  — list of check `state` strings for `gh pr checks --json`
      * milestone     — the issue's current milestone number (or None)
      * assignees     — the issue's current assignee logins (a set)
    """

    def __init__(self, *, existing_pr=None, check_states=None,
                 milestone=None, assignees=None):
        self.calls = []
        self.existing_pr = existing_pr
        self.check_states = check_states or []
        self.milestone = milestone
        self.assignees = set(assignees or [])

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)
        # --- gh pr list --head (read: existing PR detection) ---
        if body.startswith("pr list") or ("pr list" in body and "--json" in body):
            if self.existing_pr:
                return json.dumps([self.existing_pr])
            return json.dumps([])
        # --- gh pr create / gh pr edit ---
        if body.startswith("pr create"):
            return "https://github.com/acme/web/pull/101\n"
        if body.startswith("pr edit"):
            return ""
        # --- gh pr checks --json state ---
        if body.startswith("pr checks"):
            return json.dumps([{"state": s} for s in self.check_states])
        # --- gh pr merge ---
        if body.startswith("pr merge"):
            return ""
        # --- REST GET issue (milestone + assignees current state) ---
        if "api -X GET" in body and "/issues/" in body:
            ms = {"number": self.milestone} if self.milestone is not None else None
            return json.dumps({
                "milestone": ms,
                "assignees": [{"login": a} for a in sorted(self.assignees)],
            })
        # --- REST PATCH issue (milestone write) ---
        if "api -X PATCH" in body and "/issues/" in body:
            return json.dumps({"ok": True})
        # --- gh issue edit (assignee add/remove) ---
        if body.startswith("issue edit"):
            return ""
        # --- updateProjectV2ItemPosition (reorder) ---
        if "updateProjectV2ItemPosition" in body:
            return json.dumps({"data": {"updateProjectV2ItemPosition": {"items": {"totalCount": 3}}}})
        return "{}"

    def count(self, predicate):
        return sum(1 for c in self.calls if predicate(_q(c)))


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = gh.RUN

    def tearDown(self):
        gh.RUN = self._orig


# --------------------------------------------------------------------------- #
# open_or_update_pr: non-closing, create -> edit
# --------------------------------------------------------------------------- #
class TestOpenOrUpdatePr(Base):
    def test_creates_when_no_existing_pr(self):
        runner = WriteVerbRunner(existing_pr=None)
        gh.RUN = runner
        res = gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        self.assertEqual(res["action"], "created")
        # the PR number is parsed from the created URL (…/pull/101) so a fresh PR
        # is immediately addressable by pr-checks / merge-pr.
        self.assertEqual(res["number"], 101)
        self.assertEqual(res["url"], "https://github.com/acme/web/pull/101")
        self.assertTrue(runner.count(lambda q: q.startswith("pr create")))
        self.assertFalse(runner.count(lambda q: q.startswith("pr edit")))

    def test_edits_when_pr_exists(self):
        runner = WriteVerbRunner(existing_pr={"number": 101, "url": "u"})
        gh.RUN = runner
        res = gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        self.assertEqual(res["action"], "updated")
        self.assertEqual(res["number"], 101)
        self.assertTrue(runner.count(lambda q: q.startswith("pr edit")))
        self.assertFalse(runner.count(lambda q: q.startswith("pr create")))

    def test_create_then_edit_round_trip(self):
        # First run: no PR -> create. Second run: PR now exists -> edit (no dup).
        runner = WriteVerbRunner(existing_pr=None)
        gh.RUN = runner
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        runner.existing_pr = {"number": 101, "url": "u"}
        res2 = gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        self.assertEqual(res2["action"], "updated")
        # exactly one create across the round-trip (no duplicate-PR 422)
        self.assertEqual(runner.count(lambda q: q.startswith("pr create")), 1)

    def test_body_is_non_closing_relates_to(self):
        runner = WriteVerbRunner(existing_pr=None)
        gh.RUN = runner
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        create = next(c for c in runner.calls if _q(c).startswith("pr create"))
        body = create[create.index("--body") + 1]
        self.assertIn("Relates to #42", body)
        low = body.lower()
        for kw in ("closes", "fixes", "resolves", "close #", "fix #", "resolve #"):
            self.assertNotIn(kw, low)

    def test_closing_keyword_in_extra_is_rejected(self):
        runner = WriteVerbRunner(existing_pr=None)
        gh.RUN = runner
        with self.assertRaises(gh.GhError) as ctx:
            gh.open_or_update_pr("acme/web", "feat/x", "main", 42,
                                 body_extra="Closes #42 — done")
        self.assertEqual(ctx.exception.code, 2)

    def test_no_closing_keyword_in_pr_source_path(self):
        with open(os.path.join(LIB, "gh.py"), "r", encoding="utf-8") as fh:
            src = fh.read()
        # The PR-building body literal must not emit a closer; locate the helper.
        start = src.index("def _relates_body")
        end = src.index("def _find_pr_for_branch")
        body_src = src[start:end].lower()
        # `Relates to` only; no Closes/Fixes/Resolves emitted as the link.
        self.assertIn("relates to", body_src)
        self.assertNotIn('f"closes', body_src)
        self.assertNotIn('"closes #', body_src)
        self.assertNotIn('"fixes #', body_src)
        self.assertNotIn('"resolves #', body_src)


# --------------------------------------------------------------------------- #
# pr_check_state: green / red / pending
# --------------------------------------------------------------------------- #
class TestPrCheckState(Base):
    def test_green_when_all_pass(self):
        gh.RUN = WriteVerbRunner(check_states=["SUCCESS", "SUCCESS"])
        self.assertEqual(gh.pr_check_state("acme/web", 101), "green")

    def test_red_when_any_fail(self):
        gh.RUN = WriteVerbRunner(check_states=["SUCCESS", "FAILURE"])
        self.assertEqual(gh.pr_check_state("acme/web", 101), "red")

    def test_pending_when_any_in_progress(self):
        gh.RUN = WriteVerbRunner(check_states=["SUCCESS", "IN_PROGRESS"])
        self.assertEqual(gh.pr_check_state("acme/web", 101), "pending")

    def test_red_wins_over_pending(self):
        gh.RUN = WriteVerbRunner(check_states=["PENDING", "FAILURE"])
        self.assertEqual(gh.pr_check_state("acme/web", 101), "red")

    def test_empty_check_set_is_green(self):
        gh.RUN = WriteVerbRunner(check_states=[])
        self.assertEqual(gh.pr_check_state("acme/web", 101), "green")


# --------------------------------------------------------------------------- #
# merge_pr: --merge/--rebase only, never --squash
# --------------------------------------------------------------------------- #
class TestMergePr(Base):
    def test_merge_method(self):
        runner = WriteVerbRunner()
        gh.RUN = runner
        res = gh.merge_pr("acme/web", 101, "merge")
        self.assertTrue(res["merged"])
        call = next(c for c in runner.calls if _q(c).startswith("pr merge"))
        self.assertIn("--merge", call)
        self.assertNotIn("--squash", call)

    def test_rebase_method(self):
        runner = WriteVerbRunner()
        gh.RUN = runner
        gh.merge_pr("acme/web", 101, "rebase")
        call = next(c for c in runner.calls if _q(c).startswith("pr merge"))
        self.assertIn("--rebase", call)
        self.assertNotIn("--squash", call)

    def test_squash_is_rejected_code_2(self):
        gh.RUN = WriteVerbRunner()
        with self.assertRaises(gh.GhError) as ctx:
            gh.merge_pr("acme/web", 101, "squash")
        self.assertEqual(ctx.exception.code, 2)

    def test_source_never_emits_squash(self):
        # `--squash` must never appear as a STRING LITERAL handed to RUN — only
        # in prose/error text. Assert no quoted `--squash` token in the source.
        with open(os.path.join(LIB, "gh.py"), "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn('"--squash"', src)
        self.assertNotIn("'--squash'", src)


# --------------------------------------------------------------------------- #
# set_milestone: assign + re-assign = one effective write
# --------------------------------------------------------------------------- #
class TestSetMilestone(Base):
    def test_assign_writes_once(self):
        runner = WriteVerbRunner(milestone=None)
        gh.RUN = runner
        res = gh.set_milestone("acme/web", 42, 5)
        self.assertTrue(res["changed"])
        self.assertEqual(runner.count(lambda q: "api -X PATCH" in q), 1)

    def test_reassign_same_is_noop(self):
        # already on milestone 5 -> a re-assign to 5 makes NO write
        runner = WriteVerbRunner(milestone=5)
        gh.RUN = runner
        res = gh.set_milestone("acme/web", 42, 5)
        self.assertFalse(res["changed"])
        self.assertEqual(runner.count(lambda q: "api -X PATCH" in q), 0)

    def test_assign_then_reassign_one_write_total(self):
        # call 1: not set -> writes; call 2: now set to 5 -> no-op
        runner = WriteVerbRunner(milestone=None)
        gh.RUN = runner
        gh.set_milestone("acme/web", 42, 5)
        runner.milestone = 5  # the write took effect
        gh.set_milestone("acme/web", 42, 5)
        self.assertEqual(runner.count(lambda q: "api -X PATCH" in q), 1,
                         "re-assign to same milestone = one effective write total")


# --------------------------------------------------------------------------- #
# reorder_item: position mutation calls, App token
# --------------------------------------------------------------------------- #
class TestReorderItem(Base):
    def test_top_omits_after(self):
        runner = WriteVerbRunner()
        gh.RUN = runner
        gh.reorder_item("PVT_p", "ITEM_1", None)
        call = next(c for c in runner.calls if "updateProjectV2ItemPosition" in _q(c))
        q = _q(call)
        self.assertIn("updateProjectV2ItemPosition", q)
        # the top mutation omits the afterId input
        self.assertNotIn("afterId:$after", q)

    def test_after_passes_afterid(self):
        runner = WriteVerbRunner()
        gh.RUN = runner
        gh.reorder_item("PVT_p", "ITEM_2", "ITEM_1")
        call = next(c for c in runner.calls if "updateProjectV2ItemPosition" in _q(c))
        q = _q(call)
        self.assertIn("afterId:$after", q)
        self.assertIn("after=ITEM_1", q)

    def test_reorder_sequence_position_calls(self):
        # reorder a 3-item queue into [A, B, C]: A to top, then B after A, C after B
        runner = WriteVerbRunner()
        gh.RUN = runner
        gh.reorder_item("PVT_p", "A", None)
        gh.reorder_item("PVT_p", "B", "A")
        gh.reorder_item("PVT_p", "C", "B")
        pos = [c for c in runner.calls if "updateProjectV2ItemPosition" in _q(c)]
        self.assertEqual(len(pos), 3)
        self.assertIn("item=A", _q(pos[0]))
        self.assertIn("after=A", _q(pos[1]))
        self.assertIn("after=B", _q(pos[2]))

    def test_reorder_uses_app_token_path(self):
        # reorder_item goes through graphql() -> gh api graphql, the App-token
        # write path (engine.sh's --force rail + get_app_token upstream). Assert
        # it never shells GITHUB_TOKEN and rides `gh api graphql`.
        runner = WriteVerbRunner()
        gh.RUN = runner
        gh.reorder_item("PVT_p", "ITEM_1", None)
        call = next(c for c in runner.calls if "updateProjectV2ItemPosition" in _q(c))
        self.assertEqual(call[0], "api")
        self.assertEqual(call[1], "graphql")
        self.assertNotIn("GITHUB_TOKEN", _q(call))


# --------------------------------------------------------------------------- #
# set_assignee: add / remove + idempotency
# --------------------------------------------------------------------------- #
class TestSetAssignee(Base):
    def test_add_when_absent(self):
        runner = WriteVerbRunner(assignees=set())
        gh.RUN = runner
        res = gh.set_assignee("acme/web", 42, "octocat")
        self.assertTrue(res["changed"])
        self.assertTrue(runner.count(lambda q: "--add-assignee" in q))

    def test_add_already_present_is_noop(self):
        runner = WriteVerbRunner(assignees={"octocat"})
        gh.RUN = runner
        res = gh.set_assignee("acme/web", 42, "octocat")
        self.assertFalse(res["changed"])
        self.assertEqual(runner.count(lambda q: "issue edit" in q), 0)

    def test_remove_when_present(self):
        runner = WriteVerbRunner(assignees={"octocat"})
        gh.RUN = runner
        res = gh.set_assignee("acme/web", 42, "octocat", remove=True)
        self.assertTrue(res["changed"])
        self.assertTrue(runner.count(lambda q: "--remove-assignee" in q))

    def test_remove_absent_is_noop(self):
        runner = WriteVerbRunner(assignees=set())
        gh.RUN = runner
        res = gh.set_assignee("acme/web", 42, "octocat", remove=True)
        self.assertFalse(res["changed"])
        self.assertEqual(runner.count(lambda q: "issue edit" in q), 0)


# --------------------------------------------------------------------------- #
# "second call is a no-op" for every idempotent write verb
# --------------------------------------------------------------------------- #
class TestSecondCallIsNoop(Base):
    def test_pr_second_call_no_duplicate(self):
        runner = WriteVerbRunner(existing_pr={"number": 101, "url": "u"})
        gh.RUN = runner
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        self.assertEqual(runner.count(lambda q: q.startswith("pr create")), 0)

    def test_milestone_second_call_no_write(self):
        runner = WriteVerbRunner(milestone=5)
        gh.RUN = runner
        gh.set_milestone("acme/web", 42, 5)
        gh.set_milestone("acme/web", 42, 5)
        self.assertEqual(runner.count(lambda q: "api -X PATCH" in q), 0)

    def test_assignee_add_second_call_no_write(self):
        runner = WriteVerbRunner(assignees={"octocat"})
        gh.RUN = runner
        gh.set_assignee("acme/web", 42, "octocat")
        gh.set_assignee("acme/web", 42, "octocat")
        self.assertEqual(runner.count(lambda q: "issue edit" in q), 0)


# --------------------------------------------------------------------------- #
# CLI surface: exit codes + no secret leak
# --------------------------------------------------------------------------- #
class TestCliExitAndSecret(Base):
    def _run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gh.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_open_pr_exit_0(self):
        gh.RUN = WriteVerbRunner(existing_pr=None)
        code, out, _ = self._run_main(
            ["open-pr", "--repo", "acme/web", "--head", "feat/x",
             "--base", "main", "--number", "42"])
        self.assertEqual(code, 0)
        self.assertIn("created", out)

    def test_pr_checks_exit_0(self):
        gh.RUN = WriteVerbRunner(check_states=["SUCCESS"])
        code, out, _ = self._run_main(["pr-checks", "--repo", "acme/web", "--pr", "101"])
        self.assertEqual(code, 0)
        self.assertIn("green", out)

    def test_merge_squash_choice_rejected_exit_2(self):
        # argparse `choices` rejects squash at parse time -> usage exit 2
        code, _, _ = self._run_main(
            ["merge-pr", "--repo", "acme/web", "--pr", "101", "--method", "squash"])
        self.assertEqual(code, 2)

    def test_set_milestone_usage_error_exit_2(self):
        code, _, _ = self._run_main(["set-milestone", "--repo", "acme/web"])
        self.assertEqual(code, 2)

    def test_unexpected_exit_1(self):
        def boom(args):
            raise RuntimeError("kaboom")

        gh.RUN = boom
        code, _, _ = self._run_main(
            ["set-assignee", "--repo", "acme/web", "--number", "42", "--login", "octocat"])
        self.assertEqual(code, 1)

    def test_no_secret_in_output(self):
        # An error carrying a token-shaped string must be scrubbed in stderr.
        def leaky(args):
            raise gh.GhError("boom ghp_leakytoken1234567890abcdefghijklmnop")

        gh.RUN = leaky
        code, out, err = self._run_main(["pr-checks", "--repo", "acme/web", "--pr", "1"])
        self.assertNotIn("ghp_leakytoken1234567890abcdefghijklmnop", out + err)
        self.assertIn("[REDACTED]", err)


if __name__ == "__main__":
    unittest.main()
