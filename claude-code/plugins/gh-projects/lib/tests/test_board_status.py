#!/usr/bin/env python3
"""Offline tests for the VENDORED board-status action — NO network, NO live org.

The board-status action runs in a CONSUMING repo with NO plugin installed, so
its resolution/GraphQL logic is vendored in
`templates/github/actions/board-status/board_status.py`. These tests import THAT
file (never `lib/*`) and install a fake gh/GraphQL runner. This is the
"offline run of the vendored script" evidence.

Coverage:
  staging success -> On Staging (item stays open); prod success -> Done +
  close + publish the tag's Release, resolving shipped issues from the
  deployed SHA (SHA -> merged PRs -> issues).
  The action's python is self-contained (no plugin import) and runs green
  offline.
  Project writes use the App token, never GITHUB_TOKEN.
  A replayed/stale deploy event does NOT regress Status (monotonic).
  The action notes assert the native built-in target is On Staging / open.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
ACTION_DIR = os.path.join(PLUGIN_ROOT, "templates", "github", "actions", "board-status")
BOARD_STATUS_PY = os.path.join(ACTION_DIR, "board_status.py")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bsx = _load_module("board_status_vendored", BOARD_STATUS_PY)


def _q(args):
    return " ".join(str(a) for a in args)


_PROJECT = {
    "data": {"organization": {"projectV2": {
        "id": "PVT_1",
        "field": {"id": "F_status", "name": "Status", "options": [
            {"id": "OPT_inprog", "name": "In Progress"},
            {"id": "OPT_inreview", "name": "In Review"},
            {"id": "OPT_staging", "name": "On Staging"},
            {"id": "OPT_done", "name": "Done"},
        ]},
    }}}
}


class FakeDeploy:
    """Canned GitHub state + counting runner for the deploy-side resolver.

    `sha_issues`: {sha: [issue_number,...]} resolved via SHA -> merged PRs.
    `item_status`: {issue_number: current Status on the project}.
    Records writes, closes, and release-publish REST calls.
    """

    def __init__(self, *, sha_issues=None, item_status=None, existing_release=None):
        self.sha_issues = sha_issues or {}
        self.item_status = item_status or {}
        self.existing_release = existing_release  # None | {"id","draft"}
        self.calls = []
        self.writes = []     # option ids written
        self.closed = []     # issue ids closed
        self.released = []   # ("POST"|"PATCH", path)

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)

        # --- SHA -> merged PRs -> closing issues ---
        if "associatedPullRequests" in body and "closingIssuesReferences" in body:
            sha = self._fval(args, "sha")
            nums = self.sha_issues.get(sha, [])
            prs = [{"number": 900 + n, "merged": True,
                    "closingIssuesReferences": {"nodes": [{"number": n, "id": f"I_{n}"}]}}
                   for n in nums]
            return json.dumps({"data": {"repository": {"object": {
                "oid": sha, "associatedPullRequests": {"nodes": prs}}}}})

        # --- project Status resolve ---
        if 'field(name:"Status")' in body and "projectV2(number:" in body:
            return json.dumps(_PROJECT)

        # --- issue id by number ---
        if "issue(number:" in body:
            num = int(self._fval(args, "number"))
            return json.dumps({"data": {"repository": {"issue": {
                "id": f"I_{num}", "number": num, "state": "OPEN"}}}})

        # --- item for issue (current status) ---
        if "projectItems(first:20)" in body:
            iid = self._fval(args, "issue")
            num = int(str(iid).split("_")[-1])
            cur = self.item_status.get(num)
            return json.dumps({"data": {"node": {"number": num, "projectItems": {"nodes": [
                {"id": f"ITEM_{num}", "project": {"id": "PVT_1", "number": 7},
                 "fieldValueByName": ({"name": cur} if cur else None)},
            ]}}}})

        # --- Status write ---
        if "updateProjectV2ItemFieldValue" in body:
            opt = self._fval(args, "opt")
            self.writes.append(opt)
            return json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}})

        # --- close issue ---
        if "closeIssue" in body:
            iid = self._fval(args, "issue")
            self.closed.append(iid)
            return json.dumps({"data": {"closeIssue": {"issue": {"id": iid, "state": "CLOSED"}}}})

        # --- release: GET existing ---
        if any("releases/tags/" in str(a) for a in args):
            return json.dumps(self.existing_release or {})
        # --- release: POST create / PATCH publish ---
        if any(str(a) == "/repos/acme/web/releases" for a in args) or \
           any("releases/" in str(a) and "tags/" not in str(a) for a in args):
            method = "POST" if "POST" in body else ("PATCH" if "PATCH" in body else "?")
            self.released.append((method, "release"))
            return json.dumps({"id": 1, "draft": False})

        return "{}"

    @staticmethod
    def _fval(args, key):
        for a in args:
            s = str(a)
            if s.startswith(f"{key}="):
                return s.split("=", 1)[1]
        return None


class BoardStatusBase(unittest.TestCase):
    def setUp(self):
        self._orig = bsx.RUN

    def tearDown(self):
        bsx.RUN = self._orig
        os.environ.pop("GH_TOKEN", None)


# --------------------------------------------------------------------------- #
# staging success -> On Staging, item stays OPEN (not closed/Done).
# --------------------------------------------------------------------------- #
class TestStaging(BoardStatusBase):
    def test_staging_sets_on_staging_and_does_not_close(self):
        fake = FakeDeploy(sha_issues={"deadbeef": [5]}, item_status={5: "In Review"})
        bsx.RUN = fake
        out = bsx.run_staging("acme", "web", 7, "deadbeef", token="ghs_tok")
        self.assertEqual(out["target"], "On Staging")
        row = out["issues"][0]
        self.assertEqual(row["issue"], 5)
        self.assertEqual(row["to"], "On Staging")
        self.assertTrue(row["wrote"])
        self.assertFalse(row["closed"], "staging must NOT close the issue (stays open)")
        self.assertIn("OPT_staging", fake.writes)
        self.assertEqual(fake.closed, [], "no closeIssue may fire on staging")
        self.assertEqual(fake.released, [], "no Release published on staging")


# --------------------------------------------------------------------------- #
# prod success -> Done + close + publish the tag's Release.
# --------------------------------------------------------------------------- #
class TestProd(BoardStatusBase):
    def test_prod_sets_done_closes_and_publishes_release(self):
        fake = FakeDeploy(sha_issues={"cafef00d": [5, 6]},
                          item_status={5: "On Staging", 6: "On Staging"},
                          existing_release=None)
        bsx.RUN = fake
        out = bsx.run_prod("acme", "web", 7, "cafef00d", tag="v1.2.3", token="ghs_tok")
        self.assertEqual(out["target"], "Done")
        wrote_issues = {r["issue"]: r for r in out["issues"]}
        self.assertEqual(set(wrote_issues), {5, 6})
        for r in out["issues"]:
            self.assertEqual(r["to"], "Done")
            self.assertTrue(r["closed"])
        self.assertEqual(fake.writes.count("OPT_done"), 2)
        self.assertEqual(sorted(fake.closed), ["I_5", "I_6"])
        # Release for the tag was published.
        self.assertIn("release", out)
        self.assertTrue(fake.released, "prod must publish the tag's Release")

    def test_prod_resolves_shipped_issues_from_sha(self):
        # The shipped set comes from the DEPLOYED SHA -> merged PRs -> issues.
        fake = FakeDeploy(sha_issues={"sha123": [11]}, item_status={11: "On Staging"})
        bsx.RUN = fake
        issues = bsx.resolve_shipped_issues("acme", "web", "sha123", token="ghs_tok")
        self.assertEqual([i["number"] for i in issues], [11])

    def test_prod_publishes_existing_draft_release(self):
        fake = FakeDeploy(sha_issues={"s": [5]}, item_status={5: "On Staging"},
                          existing_release={"id": 99, "draft": True})
        bsx.RUN = fake
        out = bsx.run_prod("acme", "web", 7, "s", tag="v2.0.0", token="ghs_tok")
        self.assertEqual(out["release"]["action"], "published-existing-draft")
        self.assertIn(("PATCH", "release"), fake.released)


# --------------------------------------------------------------------------- #
# a replayed/stale deploy event does NOT regress Status.
# --------------------------------------------------------------------------- #
class TestMonotonic(BoardStatusBase):
    def test_replayed_staging_after_done_is_noop(self):
        # Item already Done; a replayed staging deploy (target On Staging) no-ops.
        fake = FakeDeploy(sha_issues={"s": [5]}, item_status={5: "Done"})
        bsx.RUN = fake
        out = bsx.run_staging("acme", "web", 7, "s", token="ghs_tok")
        row = out["issues"][0]
        self.assertFalse(row["wrote"])
        self.assertEqual(row["to"], "Done")
        self.assertEqual(fake.writes, [], "stale staging event must not regress a Done item")

    def test_replayed_prod_does_not_rewrite_but_close_is_idempotent(self):
        fake = FakeDeploy(sha_issues={"s": [5]}, item_status={5: "Done"})
        bsx.RUN = fake
        out = bsx.run_prod("acme", "web", 7, "s", tag="v1", token="ghs_tok")
        row = out["issues"][0]
        # Status is already Done -> no Status mutation; close stays idempotent.
        self.assertFalse(row["wrote"])
        self.assertEqual(fake.writes, [])

    def test_advance_status_unit(self):
        self.assertEqual(bsx.advance_status("In Review", "On Staging"), "On Staging")
        self.assertIsNone(bsx.advance_status("Done", "On Staging"))
        self.assertIsNone(bsx.advance_status("On Staging", "On Staging"))


# --------------------------------------------------------------------------- #
# self-contained: no plugin import; runs green offline via the CLI.
# --------------------------------------------------------------------------- #
class TestSelfContainedCli(BoardStatusBase):
    def _main(self, argv):
        with redirect_stdout(io.StringIO()):
            return bsx.main(argv)

    def test_cli_staging_runs_green(self):
        fake = FakeDeploy(sha_issues={"deadbeef": [5]}, item_status={5: "In Review"})
        bsx.RUN = fake
        code = self._main(["--repo", "acme/web", "--project", "7", "--status", "staging",
                           "--sha", "deadbeef", "--app-token", "ghs_tok"])
        self.assertEqual(code, 0)

    def test_cli_prod_requires_tag(self):
        fake = FakeDeploy(sha_issues={"s": [5]}, item_status={5: "On Staging"})
        bsx.RUN = fake
        code = self._main(["--repo", "acme/web", "--project", "7", "--status", "prod",
                         "--sha", "s", "--app-token", "ghs_tok"])
        self.assertEqual(code, 2, "prod without --tag is a usage error")

    def test_cli_needs_sha_or_issues(self):
        code = self._main(["--repo", "acme/web", "--project", "7", "--status", "staging",
                         "--app-token", "ghs_tok"])
        self.assertEqual(code, 2)

    def test_cli_bad_repo(self):
        code = self._main(["--repo", "noslash", "--project", "7", "--status", "staging",
                         "--sha", "x"])
        self.assertEqual(code, 2)

    def test_cli_explicit_issues_override_sha(self):
        fake = FakeDeploy(sha_issues={}, item_status={9: "In Review"})
        bsx.RUN = fake
        code = self._main(["--repo", "acme/web", "--project", "7", "--status", "staging",
                         "--issues", "9", "--app-token", "ghs_tok"])
        self.assertEqual(code, 0)
        self.assertIn("OPT_staging", fake.writes)


# --------------------------------------------------------------------------- #
# source greps: no plugin import, no GITHUB_TOKEN for writes.
# --------------------------------------------------------------------------- #
class TestSourceGreps(unittest.TestCase):
    def setUp(self):
        with open(BOARD_STATUS_PY, "r", encoding="utf-8") as fh:
            self.src = fh.read()

    def test_no_plugin_import(self):
        for bad in ("import gh", "from gh ", "import lib", "from lib", "import dag", "import pm"):
            self.assertNotIn(bad, self.src,
                             f"vendored board_status.py must not import the plugin ({bad!r})")

    def test_never_uses_github_token_for_writes(self):
        self.assertNotIn('os.environ.get("GITHUB_TOKEN")', self.src)
        self.assertNotIn("os.environ['GITHUB_TOKEN']", self.src)

    def test_no_metered_ai(self):
        low = self.src.lower()
        for bad in ("anthropic", "openai", "claude-", "gpt-", "completion(", "model="):
            self.assertNotIn(bad, low)


# --------------------------------------------------------------------------- #
# action.yml / README assert the native built-in target is On Staging,
# item stays OPEN after merge (greppable assertion).
# --------------------------------------------------------------------------- #
class TestActionNotesAndYaml(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ACTION_DIR, "action.yml"), "r", encoding="utf-8") as fh:
            self.action = fh.read()
        with open(os.path.join(ACTION_DIR, "README.md"), "r", encoding="utf-8") as fh:
            self.readme = fh.read()

    def test_action_documents_native_built_in_on_staging_open(self):
        # an explicit, greppable assertion that the native "PR merged ->
        # set Status" built-in target is On Staging (not Done) and stays open.
        text = (self.action + self.readme).lower()
        self.assertIn("pr merged", text)
        self.assertIn("on staging", text)
        self.assertIn("stays open", text)
        self.assertIn("not", text)  # "not Done"
        self.assertIn("done", text)

    def test_action_is_composite_and_self_contained(self):
        self.assertIn("using: composite", self.action)
        self.assertIn("board_status.py", self.action)
        # The action does not reference the plugin lib.
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", self.action)
        self.assertNotIn("/lib/", self.action)

    def test_action_uses_app_token_not_github_token(self):
        self.assertIn("create-github-app-token", self.action)
        self.assertIn("app-private-key", self.action)
        # GITHUB_TOKEN may appear ONLY in the "never use it" boundary prose; it
        # must never be WIRED as a value (no `${{ ... github_token ... }}` and no
        # `GH_TOKEN: ... GITHUB_TOKEN`).
        low = self.action.lower()
        self.assertNotIn("secrets.github_token", low)
        self.assertNotIn("${{ github.token", low)
        self.assertNotIn("gh_token: ${{ secrets.github_token", low)


if __name__ == "__main__":
    unittest.main()
