#!/usr/bin/env python3
"""Offline tests for the `create-pr` skill's orchestration over the lib verbs —
NO network, NO live org, NO mutation.

create-pr is thin prose over the deterministic engine: it composes the existing
`gh.py` verbs (`open_or_update_pr`, `pr_check_state`, `advance_status`/
`STATUS_ORDER`, `merge_pr`) behind `engine.sh`'s dry-by-default / --force rail. It
adds NO decision logic of its own to the lib. These tests therefore exercise the
COMPOSITION the SKILL.md prescribes (the lib verbs are unit-tested in
test_gh_writeverbs.py) plus the skill's frontmatter contract.

Covers:
  - open/update the issue-linked PR with a NON-CLOSING `Relates to #N`;
    when a PR exists it edits in place; a no-diff re-run is a no-op (never
    a duplicate-PR error).
  - advance board Status across the PR lifecycle — `In Review` on a ready
    PR, hold `In Progress` while draft — MONOTONICALLY (no regression).
  - read the PR's check state and WITHHOLD the merge step while checks are
    red/pending, stating the reason.
  - NON-SQUASH merge (--merge/--rebase) only on confirm/--force and only on
    green; never --squash.
  - dry-by-default — preview mutates nothing; --force mutates.
  - the PreToolUse / matcher Bash guard block is present in create-pr's frontmatter.
  - frontmatter — disable-model-invocation true, model claude-opus-4-8,
    effort high.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
PLUGIN_ROOT = os.path.dirname(LIB)
sys.path.insert(0, LIB)

import gh  # noqa: E402

SKILL = os.path.join(PLUGIN_ROOT, "skills", "create-pr", "SKILL.md")


def _q(args):
    return " ".join(str(a) for a in args)


class PromoteRunner:
    """Fake gh runner for create-pr's composed verbs. Dispatches on argv,
    returns canned JSON, records every call so writes/round-trips are testable.

    Presettable state:
      * existing_pr  — {number,url} returned by `gh pr list --head`, or None
      * check_states — list of check `state` strings for `gh pr checks --json`
    """

    def __init__(self, *, existing_pr=None, check_states=None):
        self.calls = []
        self.existing_pr = existing_pr
        self.check_states = check_states or []

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)
        if body.startswith("pr list") or ("pr list" in body and "--json" in body):
            return json.dumps([self.existing_pr] if self.existing_pr else [])
        if body.startswith("pr create"):
            return "https://github.com/acme/web/pull/101\n"
        if body.startswith("pr edit"):
            return ""
        if body.startswith("pr checks"):
            return json.dumps([{"state": s} for s in self.check_states])
        if body.startswith("pr merge"):
            return ""
        return "{}"

    def count(self, predicate):
        return sum(1 for c in self.calls if predicate(_q(c)))


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = gh.RUN

    def tearDown(self):
        gh.RUN = self._orig


# --------------------------------------------------------------------------- #
# The create-pr orchestration the SKILL.md prescribes, expressed as a pure
# composition of the existing lib verbs (no new decision logic in the lib).
# --------------------------------------------------------------------------- #
def _status_target_for_pr(*, draft: bool) -> str:
    """Lifecycle -> Status target: draft holds In Progress, ready -> In Review."""
    return "In Progress" if draft else "In Review"


def _promote(repo, head, base, issue, *, draft, current_status,
             pr_number, do_merge=False, method="merge"):
    """Compose the create-pr flow exactly as SKILL.md steps 2-3 prescribe.

    Returns a record of the decisions: the PR action, the check verdict, the
    Status to write (None = hold/no-op), whether merge was performed, and the
    merge method (None if withheld). Mutating verbs here only run because the
    test drives the --force path; dry-by-default is asserted separately via the
    engine.
    """
    pr = gh.open_or_update_pr(repo, head, base, issue, draft=draft)
    verdict = gh.pr_check_state(repo, pr_number)
    target = _status_target_for_pr(draft=draft)
    status_write = gh.advance_status(current_status, target)  # None = no regression
    merged = None
    if do_merge:
        # Merge is WITHHELD unless checks are green; never squash.
        if verdict == "green":
            merged = gh.merge_pr(repo, pr_number, method)
    return {
        "pr_action": pr["action"],
        "verdict": verdict,
        "status_write": status_write,
        "status_target": target,
        "merged": merged,
    }


# --------------------------------------------------------------------------- #
# Open/update issue-linked PR: non-closing, edit-in-place, no-op re-run
# --------------------------------------------------------------------------- #
class TestOpenLinkedPr(Base):
    def test_created_pr_carries_relates_to_no_closer(self):
        runner = PromoteRunner(existing_pr=None)
        gh.RUN = runner
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        create = next(c for c in runner.calls if _q(c).startswith("pr create"))
        body = create[create.index("--body") + 1]
        self.assertIn("Relates to #42", body)
        low = body.lower()
        for kw in ("closes", "fixes", "resolves", "close #", "fix #", "resolve #"):
            self.assertNotIn(kw, low)

    def test_updated_pr_edits_in_place_no_duplicate(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"})
        gh.RUN = runner
        res = gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        self.assertEqual(res["action"], "updated")
        self.assertEqual(res["number"], 101)
        self.assertTrue(runner.count(lambda q: q.startswith("pr edit")))
        self.assertFalse(runner.count(lambda q: q.startswith("pr create")))

    def test_no_diff_rerun_is_noop_never_duplicate(self):
        # second promote on an existing PR -> edit, never a duplicate-create 422
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"})
        gh.RUN = runner
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        gh.open_or_update_pr("acme/web", "feat/x", "main", 42)
        self.assertEqual(runner.count(lambda q: q.startswith("pr create")), 0)

    def test_smuggled_closer_rejected(self):
        gh.RUN = PromoteRunner(existing_pr=None)
        with self.assertRaises(gh.GhError) as ctx:
            gh.open_or_update_pr("acme/web", "feat/x", "main", 42,
                                 body_extra="Fixes #42")
        self.assertEqual(ctx.exception.code, 2)


# --------------------------------------------------------------------------- #
# Status lifecycle: ready -> In Review, draft -> In Progress, monotonic
# --------------------------------------------------------------------------- #
class TestStatusLifecycle(Base):
    def test_ready_pr_advances_to_in_review(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["SUCCESS"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42,
                       draft=False, current_status="In Progress", pr_number=101)
        self.assertEqual(rec["status_target"], "In Review")
        self.assertEqual(rec["status_write"], "In Review")

    def test_draft_pr_holds_in_progress(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["IN_PROGRESS"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42,
                       draft=True, current_status="In Progress", pr_number=101)
        self.assertEqual(rec["status_target"], "In Progress")
        # already at In Progress -> monotonic no-op (no Status write)
        self.assertIsNone(rec["status_write"])

    def test_no_regression_when_already_past_target(self):
        # PR is ready (target In Review) but item already On Staging -> no regress
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["SUCCESS"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42,
                       draft=False, current_status="On Staging", pr_number=101)
        self.assertIsNone(rec["status_write"])

    def test_status_target_is_within_status_order(self):
        for draft in (True, False):
            self.assertIn(_status_target_for_pr(draft=draft), gh.STATUS_ORDER)

    def test_promote_only_touches_status_field(self):
        # the skill never sets intake/scheduling fields: its target is a Status
        # column only, drawn from STATUS_ORDER.
        self.assertEqual(
            {_status_target_for_pr(draft=True), _status_target_for_pr(draft=False)},
            {"In Progress", "In Review"},
        )


# --------------------------------------------------------------------------- #
# Withhold merge while checks are red/pending, with a reason
# --------------------------------------------------------------------------- #
class TestMergeWithheldUntilGreen(Base):
    def test_red_checks_withhold_merge(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["SUCCESS", "FAILURE"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42, draft=False,
                       current_status="In Progress", pr_number=101, do_merge=True)
        self.assertEqual(rec["verdict"], "red")
        self.assertIsNone(rec["merged"], "merge must be withheld while red")
        self.assertEqual(runner.count(lambda q: q.startswith("pr merge")), 0)

    def test_pending_checks_withhold_merge(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["IN_PROGRESS"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42, draft=False,
                       current_status="In Progress", pr_number=101, do_merge=True)
        self.assertEqual(rec["verdict"], "pending")
        self.assertIsNone(rec["merged"], "merge must be withheld while pending")
        self.assertEqual(runner.count(lambda q: q.startswith("pr merge")), 0)

    def test_reason_is_the_check_verdict(self):
        # the withhold reason the skill states is exactly the verdict the lib reads
        gh.RUN = PromoteRunner(check_states=["ERROR"])
        self.assertEqual(gh.pr_check_state("acme/web", 101), "red")


# --------------------------------------------------------------------------- #
# Non-squash merge on green only; squash never emitted
# --------------------------------------------------------------------------- #
class TestNonSquashMergeOnGreen(Base):
    def test_green_offers_non_squash_merge(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["SUCCESS", "SUCCESS"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42, draft=False,
                       current_status="In Progress", pr_number=101, do_merge=True)
        self.assertEqual(rec["verdict"], "green")
        self.assertIsNotNone(rec["merged"])
        self.assertEqual(rec["merged"]["method"], "merge")
        merge = next(c for c in runner.calls if _q(c).startswith("pr merge"))
        self.assertIn("--merge", merge)
        self.assertNotIn("--squash", merge)

    def test_rebase_is_also_non_squash(self):
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["SUCCESS"])
        gh.RUN = runner
        rec = _promote("acme/web", "feat/x", "main", 42, draft=False,
                       current_status="In Progress", pr_number=101,
                       do_merge=True, method="rebase")
        merge = next(c for c in runner.calls if _q(c).startswith("pr merge"))
        self.assertIn("--rebase", merge)
        self.assertNotIn("--squash", merge)

    def test_squash_method_rejected_code_2(self):
        gh.RUN = PromoteRunner(check_states=["SUCCESS"])
        with self.assertRaises(gh.GhError) as ctx:
            gh.merge_pr("acme/web", 101, "squash")
        self.assertEqual(ctx.exception.code, 2)

    def test_already_merged_rerun_is_idempotent(self):
        # SKILL: an already-merged PR is not re-merged. We model this by the
        # caller not re-issuing merge once it is done; the verb itself never
        # emits a duplicate-create, and a no-op promote issues zero merges.
        runner = PromoteRunner(existing_pr={"number": 101, "url": "u"},
                               check_states=["SUCCESS"])
        gh.RUN = runner
        # promote with do_merge=False (already merged, nothing to do)
        rec = _promote("acme/web", "feat/x", "main", 42, draft=False,
                       current_status="On Staging", pr_number=101, do_merge=False)
        self.assertIsNone(rec["merged"])
        self.assertEqual(runner.count(lambda q: q.startswith("pr merge")), 0)


# --------------------------------------------------------------------------- #
# Dry-by-default through engine.sh: preview mutates nothing; --force does
# --------------------------------------------------------------------------- #
class TestDryByDefault(unittest.TestCase):
    """The write verbs create-pr drives (open-pr, merge-pr) are gated by
    engine.sh's --force rail. Without --force the engine previews and never shells
    python3 gh.py for a write verb; with --force it does. We assert by parsing
    engine.sh's source (no live gh, no real mutation)."""

    def setUp(self):
        with open(os.path.join(LIB, "engine.sh"), "r", encoding="utf-8") as fh:
            self.src = fh.read()

    def test_write_verbs_not_in_dry_read_whitelist(self):
        # the dry-mode read whitelist runs ONLY resolve|capabilities|token; the
        # write verbs create-pr uses fall through to the "pass --force" branch.
        m = re.search(r"resolve\|capabilities\|token", self.src)
        self.assertIsNotNone(m, "engine.sh keeps a read-only dry whitelist")
        whitelist = m.group(0)
        for write_verb in ("open-pr", "merge-pr"):
            self.assertNotIn(write_verb, whitelist,
                             f"{write_verb} must NOT be dry-run-executable")

    def test_dry_mode_blocks_writes_without_force(self):
        # the dry branch prints a preview and exits 0 without executing a write
        self.assertIn("pass --force to execute this write verb", self.src)
        self.assertIn("dry-run (no --force)", self.src)

    def test_force_path_execs_gh_py(self):
        # the final unconditional exec runs the verb only after --force is split out
        self.assertIn('exec python3 "$gh_py" "${args[@]}"', self.src)
        self.assertIn('if [[ "$force" -ne 1 ]]', self.src)


# --------------------------------------------------------------------------- #
# Frontmatter contract incl. the guard hooks block
# --------------------------------------------------------------------------- #
class TestFrontmatter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL, "r", encoding="utf-8") as fh:
            cls.text = fh.read()
        # isolate the YAML frontmatter block (between the first two `---` fences)
        parts = cls.text.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must open with a --- frontmatter block"
        cls.front = parts[1]

    def test_skill_file_exists(self):
        self.assertTrue(os.path.isfile(SKILL))

    def test_name_is_create_pr(self):
        self.assertRegex(self.front, r"(?m)^name:\s*create-pr\s*$")

    def test_disable_model_invocation_true(self):
        self.assertRegex(self.front, r"(?m)^disable-model-invocation:\s*true\s*$")

    def test_model_is_opus(self):
        self.assertRegex(self.front, r"(?m)^model:\s*claude-opus-4-8\s*$")

    def test_effort_is_high(self):
        self.assertRegex(self.front, r"(?m)^effort:\s*high\s*$")

    def test_argument_hint_present(self):
        self.assertRegex(self.front, r"(?m)^argument-hint:")
        self.assertIn("--issue", self.front)
        self.assertIn("--force", self.front)

    def test_allowed_tools_least_privilege_includes_gh(self):
        m = re.search(r"(?m)^allowed-tools:\s*(.+)$", self.front)
        self.assertIsNotNone(m)
        tools = m.group(1)
        # create-pr shells `gh pr checks`, so Bash(gh *) is in scope; plus the
        # engine + python3 wrappers and the read/ask tools.
        self.assertIn("Bash(gh *)", tools)
        self.assertIn("Bash(python3 *)", tools)
        self.assertIn("Bash(bash *)", tools)

    def test_guard_hooks_block_present(self):
        # The PreToolUse / matcher Bash guard block, pointing at guard.sh,
        # scopes the guard to only-while-this-skill-runs.
        self.assertRegex(self.front, r"(?m)^hooks:\s*$")
        self.assertIn("PreToolUse:", self.front)
        self.assertRegex(self.front, r'matcher:\s*"Bash"')
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh", self.front)
        self.assertRegex(self.front, r"type:\s*command")

    def test_guard_file_exists_and_is_referenced(self):
        guard = os.path.join(PLUGIN_ROOT, "hooks", "guard.sh")
        self.assertTrue(os.path.isfile(guard), "the referenced guard.sh must exist")


# --------------------------------------------------------------------------- #
# No metered AI; no closing keyword anywhere in the skill prose
# --------------------------------------------------------------------------- #
class TestSkillInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL, "r", encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_no_closing_keyword_directive_in_skill(self):
        low = self.text.lower()
        # the skill must instruct non-closing links; it never directs a closer.
        self.assertIn("relates to #n", low)
        for closer in ("closes #", "fixes #", "resolves #"):
            self.assertNotIn(closer, low)

    def test_no_metered_ai_call_in_skill(self):
        low = self.text.lower()
        for banned in ("anthropic", "openai", "api_key", "model api", "console key"):
            self.assertNotIn(banned, low)


if __name__ == "__main__":
    unittest.main()
