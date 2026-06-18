#!/usr/bin/env python3
"""Offline tests for the VENDORED board_sync.py — NO network, NO live org.

board-sync runs in a CONSUMING repo with no plugin installed, so the testable
status/link/monotonic logic lives in the vendored
`templates/github/workflows/board_sync.py`. These tests import THAT file (never
`lib/*`) and install a fake gh/GraphQL runner.

Coverage:
  push to an issue-linked branch -> In Progress via App-token GraphQL.
  ready PR -> In Review; draft PR holds In Progress until ready_for_review.
  link resolves LINKED-BRANCH-first AND via branch-name parse; grep that
  there is no `Closes #N` / closing-keyword dependence.
  Project writes use the App token, never GITHUB_TOKEN.
  A replayed/stale event does NOT regress Status (monotonic).
  The workflow's python is self-contained (no plugin import).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
BOARD_SYNC_PY = os.path.join(PLUGIN_ROOT, "templates", "github", "workflows", "board_sync.py")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bs = _load_module("board_sync_vendored", BOARD_SYNC_PY)


# --------------------------------------------------------------------------- #
# Fake gh/GraphQL runner.
# --------------------------------------------------------------------------- #
def _q(args):
    return " ".join(str(a) for a in args)


# Project Status field with its options.
_PROJECT = {
    "data": {"organization": {"projectV2": {
        "id": "PVT_1",
        "field": {"id": "F_status", "name": "Status", "options": [
            {"id": "OPT_ready", "name": "Ready"},
            {"id": "OPT_inprog", "name": "In Progress"},
            {"id": "OPT_inreview", "name": "In Review"},
            {"id": "OPT_staging", "name": "On Staging"},
            {"id": "OPT_done", "name": "Done"},
        ]},
    }}}
}


class FakeBoard:
    """Canned GitHub state + a counting runner.

    `linked_branches`: {branch_name: issue_number} — the authoritative link.
    `item_status`: {issue_number: current Status name on the project}.
    Records every updateProjectV2ItemFieldValue write so tests assert on it.
    """

    def __init__(self, *, linked_branches=None, item_status=None):
        self.linked_branches = linked_branches or {}
        self.item_status = item_status or {}
        self.calls = []
        self.writes = []  # (issue_number_guess, option_id)
        self.saw_github_token_env = False

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)

        # Token discipline: a Project write must carry the App token via
        # GH_TOKEN env, and GITHUB_TOKEN must NOT be what authorizes it.
        if "updateProjectV2ItemFieldValue" in body:
            if os.environ.get("GH_TOKEN") == "GITHUB_TOKEN_VALUE":
                self.saw_github_token_env = True
            opt = body.split("opt=")[1].split()[0] if "opt=" in body else \
                next((str(a).split("=", 1)[1] for a in args if str(a).startswith("opt=")), None)
            self.writes.append(opt)
            return json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_x"}}}})

        # --- linked-branch lookup (issue.linkedBranches) ---
        if "linkedBranches(first:10)" in body:
            name = self._fval(args, "name")
            nodes = []
            for branch, issue_num in self.linked_branches.items():
                nodes.append({
                    "number": issue_num, "id": f"I_{issue_num}",
                    "linkedBranches": {"nodes": [{"ref": {"name": branch}}]},
                })
            return json.dumps({"data": {"repository": {"issues": {"nodes": nodes}}}})

        # --- project + Status field resolve ---
        if 'field(name:"Status")' in body and "projectV2(number:" in body:
            return json.dumps(_PROJECT)

        # --- issue id by number ---
        if "issue(number:" in body:
            num = int(self._fval(args, "number"))
            return json.dumps({"data": {"repository": {"issue": {"id": f"I_{num}", "number": num}}}})

        # --- item for issue (current status) ---
        if "projectItems(first:20)" in body:
            iid = self._fval(args, "issue")  # e.g. I_5
            num = int(str(iid).split("_")[-1]) if "_" in str(iid) else None
            cur = self.item_status.get(num)
            return json.dumps({"data": {"node": {"number": num, "projectItems": {"nodes": [
                {"id": f"ITEM_{num}", "project": {"id": "PVT_1", "number": 7},
                 "fieldValueByName": ({"name": cur} if cur else None)},
            ]}}}})

        return "{}"

    @staticmethod
    def _fval(args, key):
        for a in args:
            s = str(a)
            if s.startswith(f"{key}="):
                return s.split("=", 1)[1]
        return None


class BoardSyncBase(unittest.TestCase):
    def setUp(self):
        self._orig = bs.RUN

    def tearDown(self):
        bs.RUN = self._orig
        os.environ.pop("GH_TOKEN", None)


# --------------------------------------------------------------------------- #
# link resolution: LINKED BRANCH first, branch-name parse fallback.
# --------------------------------------------------------------------------- #
class TestLinkResolution(BoardSyncBase):
    def test_linked_branch_first(self):
        board = FakeBoard(linked_branches={"feature/login": 42})
        bs.RUN = board
        link = bs.resolve_issue_for_branch("acme", "web", "refs/heads/feature/login")
        self.assertEqual(link["number"], 42)
        self.assertEqual(link["via"], "linked-branch")

    def test_branch_name_parse_fallback(self):
        # No linked branch recorded -> fall back to the `123-foo` prefix.
        board = FakeBoard(linked_branches={})
        bs.RUN = board
        link = bs.resolve_issue_for_branch("acme", "web", "refs/heads/123-add-search")
        self.assertEqual(link["number"], 123)
        self.assertEqual(link["via"], "branch-name")

    def test_branch_name_parse_only_function(self):
        self.assertEqual(bs.issue_from_branch_name("88-foo")["number"], 88)
        self.assertEqual(bs.issue_from_branch_name("refs/heads/9_bar")["number"], 9)
        self.assertIsNone(bs.issue_from_branch_name("no-number-here"))

    def test_no_link_returns_none(self):
        board = FakeBoard(linked_branches={})
        bs.RUN = board
        link = bs.resolve_issue_for_branch("acme", "web", "refs/heads/just-words")
        self.assertIsNone(link)


# --------------------------------------------------------------------------- #
# push to an issue-linked branch -> In Progress via App-token GraphQL.
# --------------------------------------------------------------------------- #
class TestPushInProgress(BoardSyncBase):
    def test_push_linked_branch_sets_in_progress(self):
        board = FakeBoard(linked_branches={"feature/login": 42}, item_status={42: "Ready"})
        bs.RUN = board
        os.environ["GH_TOKEN"] = "ghs_appinstallationtoken1234567890abcd"
        out = bs.apply_event("acme", "web", 7, event_name="push", action=None,
                             branch="refs/heads/feature/login", draft=False,
                             token="ghs_appinstallationtoken1234567890abcd")
        self.assertEqual(out["issue"], 42)
        self.assertEqual(out["to"], "In Progress")
        self.assertTrue(out["wrote"])
        # The write actually hit updateProjectV2ItemFieldValue with In Progress.
        self.assertIn("OPT_inprog", board.writes)

    def test_push_via_branch_name_fallback(self):
        board = FakeBoard(linked_branches={}, item_status={123: "Ready"})
        bs.RUN = board
        out = bs.apply_event("acme", "web", 7, event_name="push", action=None,
                             branch="refs/heads/123-foo", draft=False,
                             token="ghs_tok")
        self.assertEqual(out["issue"], 123)
        self.assertEqual(out["to"], "In Progress")
        self.assertEqual(out["via"], "branch-name")


# --------------------------------------------------------------------------- #
# ready PR -> In Review; draft PR holds In Progress until ready.
# --------------------------------------------------------------------------- #
class TestPullRequestStatus(BoardSyncBase):
    def test_ready_pr_in_review(self):
        board = FakeBoard(linked_branches={"feature/login": 42}, item_status={42: "In Progress"})
        bs.RUN = board
        out = bs.apply_event("acme", "web", 7, event_name="pull_request", action="ready_for_review",
                             branch="feature/login", draft=False, token="ghs_tok")
        self.assertEqual(out["to"], "In Review")
        self.assertIn("OPT_inreview", board.writes)

    def test_draft_pr_holds_in_progress(self):
        board = FakeBoard(linked_branches={"feature/login": 42}, item_status={42: "Ready"})
        bs.RUN = board
        out = bs.apply_event("acme", "web", 7, event_name="pull_request", action="opened",
                             branch="feature/login", draft=True, token="ghs_tok")
        self.assertEqual(out["to"], "In Progress")
        # A draft PR does NOT advance to In Review.
        self.assertNotIn("OPT_inreview", board.writes)

    def test_event_target_mapping(self):
        self.assertEqual(bs.target_for_event("push", None, draft=False), "In Progress")
        self.assertEqual(bs.target_for_event("pull_request", "opened", draft=True), "In Progress")
        self.assertEqual(bs.target_for_event("pull_request", "ready_for_review", draft=False), "In Review")
        self.assertIsNone(bs.target_for_event("issues", "labeled", draft=False))


# --------------------------------------------------------------------------- #
# a replayed/stale event does NOT regress Status (monotonic).
# --------------------------------------------------------------------------- #
class TestMonotonic(BoardSyncBase):
    def test_stale_push_does_not_regress_staged_item(self):
        # Item already On Staging; a replayed push (target In Progress) must no-op.
        board = FakeBoard(linked_branches={"feature/login": 42}, item_status={42: "On Staging"})
        bs.RUN = board
        out = bs.apply_event("acme", "web", 7, event_name="push", action=None,
                             branch="feature/login", draft=False, token="ghs_tok")
        self.assertFalse(out["wrote"])
        self.assertEqual(out["to"], "On Staging")
        self.assertEqual(board.writes, [], "no Status mutation may fire for a stale event")

    def test_replayed_ready_pr_is_noop_when_already_in_review(self):
        board = FakeBoard(linked_branches={"feature/login": 42}, item_status={42: "In Review"})
        bs.RUN = board
        out = bs.apply_event("acme", "web", 7, event_name="pull_request", action="ready_for_review",
                             branch="feature/login", draft=False, token="ghs_tok")
        self.assertFalse(out["wrote"])
        self.assertEqual(board.writes, [])

    def test_advance_status_unit(self):
        self.assertEqual(bs.advance_status("Ready", "In Progress"), "In Progress")
        self.assertIsNone(bs.advance_status("On Staging", "In Progress"))
        self.assertIsNone(bs.advance_status("In Review", "In Review"))
        self.assertEqual(bs.advance_status("Done", "In Progress", reopen=True), "In Progress")


# --------------------------------------------------------------------------- #
# boundary greps over the SOURCE — no `Closes #N` dependence.
# --------------------------------------------------------------------------- #
class TestSourceGreps(unittest.TestCase):
    def setUp(self):
        with open(BOARD_SYNC_PY, "r", encoding="utf-8") as fh:
            self.src = fh.read()
        self.lowered = self.src.lower()

    def test_no_closing_keyword_dependence(self):
        # The link must never be resolved from a closing keyword. The literal
        # `closingIssuesReferences` (GitHub's record of what a PR closes) must
        # NOT appear in board-sync's resolver, and no `closes #`/`fixes #`
        # parsing exists. (Mentions in a comment explaining the ban are allowed
        # only as the negated phrase; assert the API field itself is absent.)
        self.assertNotIn("closingissuesreferences", self.lowered,
                         "board-sync must not read closingIssuesReferences")
        # No regex/string that parses a closing keyword + issue number.
        for kw in ("closes #", "fixes #", "resolves #", "close #", "fix #"):
            # allow the word only inside a NEGATING explanation; assert it is not
            # used as an actual parse pattern (no `re.` near it / no split on it).
            self.assertNotIn(f'"{kw}"', self.lowered)
            self.assertNotIn(f"'{kw}'", self.lowered)

    def test_no_projects_v2_item_trigger_in_python(self):
        # The only mentions of `projects_v2_item` are in the module docstring /
        # comments explaining why we never trigger on it. Assert it never appears
        # as a quoted string or dict key in executable code (no event-dispatch).
        for needle in ('"projects_v2_item"', "'projects_v2_item'",
                       "projects_v2_item:", "== \"projects_v2_item\""):
            self.assertNotIn(needle, self.lowered,
                             f"projects_v2_item must not be reacted to in code ({needle!r})")
        # event-dispatch in this file is on event_name == "push"/"pull_request"
        # only — assert those are the sole dispatch comparisons.
        self.assertIn('event_name == "push"', self.src)
        self.assertIn('event_name == "pull_request"', self.src)

    def test_self_contained_no_plugin_import(self):
        # Must NOT import lib/* (gh, dag, pm) — it runs in a plugin-less repo.
        for bad in ("import gh", "from gh ", "import lib", "from lib", "import dag", "import pm"):
            self.assertNotIn(bad, self.src,
                             f"vendored board_sync.py must not import the plugin ({bad!r})")

    def test_never_uses_github_token_for_writes(self):
        self.assertNotIn('os.environ.get("GITHUB_TOKEN")', self.src)
        self.assertNotIn("os.environ['GITHUB_TOKEN']", self.src)


# --------------------------------------------------------------------------- #
# boundary greps over the WORKFLOW yaml — no projects_v2_item trigger,
# no Closes-driven close.
# --------------------------------------------------------------------------- #
class TestWorkflowYaml(unittest.TestCase):
    def setUp(self):
        path = os.path.join(PLUGIN_ROOT, "templates", "github", "workflows", "board-sync.yml")
        with open(path, "r", encoding="utf-8") as fh:
            self.yml = fh.read()

    def test_no_projects_v2_item_trigger(self):
        # constraint #1: there is NO `on: projects_v2_item:` repo trigger. The
        # phrase appears only in the inversion comment; assert every line that
        # names it is a YAML comment (starts with `#`), so it is never a trigger.
        for line in self.yml.splitlines():
            if "projects_v2_item" in line:
                self.assertTrue(line.lstrip().startswith("#"),
                                f"projects_v2_item may only appear in a comment, not: {line!r}")
        # And the literal trigger key never appears as a non-comment mapping key.
        self.assertNotIn("\n  projects_v2_item:", self.yml)
        self.assertNotIn("\nprojects_v2_item:", self.yml)

    def test_triggers_on_push_and_pull_request_types(self):
        self.assertIn("push:", self.yml)
        self.assertIn("pull_request:", self.yml)
        for t in ("opened", "ready_for_review", "converted_to_draft", "reopened"):
            self.assertIn(t, self.yml)

    def test_uses_app_token_not_github_token(self):
        self.assertIn("create-github-app-token", self.yml)
        self.assertIn("GH_APP_PRIVATE_KEY", self.yml)
        # GITHUB_TOKEN may appear ONLY in boundary prose; it must never be WIRED
        # as the token for the Project write step.
        low = self.yml.lower()
        self.assertNotIn("secrets.github_token", low)
        self.assertNotIn("gh_app_token: ${{ secrets.github_token", low)
        self.assertNotIn("${{ github.token", low)


if __name__ == "__main__":
    unittest.main()
