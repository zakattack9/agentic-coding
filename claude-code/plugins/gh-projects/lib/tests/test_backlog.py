#!/usr/bin/env python3
"""Offline tests for lib/backlog.py — the staging-ledger engine behind the
resumable create-issues intake pipeline. NO network, NO live org, NO creds.

Every test runs in a throwaway temp git repo (so `git rev-parse --show-toplevel`
resolves locally) and overrides the lib/gh.py RUN seam with a fake recorder, so
the `gh issue create` + the Projects v2 writes (add_item / write_field /
add_sub_issue / add_blocked_by) are exercised without a network. Follows the
fake-RUN / CountingRunner idiom from test_gh_writeverbs.py + test_intake.py.

Covers:
  - staging dir resolves at the git toplevel from a SUBDIRECTORY
  - a ledger entry records the decompose-tree + proposed triage fields
  - target repo defaults/overridable AND is required to promote
  - lifecycle stub -> drafting -> ready -> promoted
  - promote is readiness-gated (stub/drafting refused WITH A REASON)
  - promote is idempotent (re-promote = no-op, NO duplicate issue create)
  - promote is one-way (staging file removed, ledger marked promoted)
  - add/list/show/link/promote subcommands + the documented `list` columns
  - dry-by-default (no mutation without --force)
  - Projects v2 writes ride the App-token path (no GITHUB_TOKEN, no token print)
  - T3 publishes specs/<slug>.md + sets Spec; T1/T2 leave Spec empty
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import backlog  # noqa: E402
import gh  # noqa: E402


def _q(args):
    return " ".join(str(a) for a in args)


def _init_repo(path):
    subprocess.run(["git", "init", "-q", path], check=True,
                   capture_output=True, text=True)


# --------------------------------------------------------------------------- #
# A fake gh runner: serves the board resolve + the issue-create + every Projects
# v2 write the promote path drives, recording each call so writes/round-trips are
# testable. NEVER touches a network; NEVER returns or carries a token.
# --------------------------------------------------------------------------- #
PROJECT_ID = "PVT_board"

_SINGLE_SELECTS = {
    "Type": ["Feature", "Bug", "Chore", "Infra"],
    "Size": ["S", "M", "L"],
    "Tier": ["T1", "T2", "T3"],
    "Priority": ["P0", "P1", "P2", "P3"],
    "Status": ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"],
}
_TEXT_FIELDS = ["PM-ID", "Spec"]


class BoardRunner:
    """Fake gh runner for the promote path. Each `gh issue create` returns the
    next issue url/number; field writes read back identical via a per-item map."""

    def __init__(self, *, next_issue=101):
        self.calls = []
        self.writes = []
        self.issue_creates = []
        self._next_issue = next_issue
        self._written = {}  # field id -> (kind, value) for the two-phase read-back
        self._node_ids = {}  # issue number -> node id

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)

        if "--help" in body:
            return ""  # capability probes: feature absent -> GraphQL fallback

        # ----- gh issue create -> emit a url carrying the issue number -----
        if body.startswith("issue create"):
            num = self._next_issue
            self._next_issue += 1
            self.issue_creates.append(list(args))
            url = f"https://github.com/acme/web/issues/{num}"
            return url + "\n"

        # ----- project + field resolve -----
        if "fields(first:100)" in body:
            return json.dumps({"data": {"organization": {"projectV2": {
                "id": PROJECT_ID, "number": 7, "title": "Board",
                "fields": {"nodes": self._field_nodes()}}}}})

        # ----- REST GET issue (node id resolution) -----
        if "api -X GET" in body and "/issues/" in body:
            import re
            m = re.search(r"/issues/(\d+)", body)
            num = int(m.group(1)) if m else 0
            return json.dumps({"node_id": f"I_{num}", "assignees": []})

        # ----- addProjectV2ItemById -----
        if "addProjectV2ItemById" in body:
            self.writes.append(("add-item", body))
            return json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": "ITEM_x"}}}})

        # ----- updateProjectV2ItemFieldValue (field write) -----
        if "updateProjectV2ItemFieldValue" in body:
            self.writes.append(("set-field", body))
            self._record_written(body)
            return json.dumps({"data": {"updateProjectV2ItemFieldValue": {
                "projectV2Item": {"id": "ITEM_x"}}}})

        # ----- field read-back -----
        if "fieldValues(first:50)" in body:
            return json.dumps({"data": {"node": {"id": "ITEM_x",
                "fieldValueByName": {"nodes": self._readback_nodes()}}}})

        # ----- addSubIssue -----
        if "addSubIssue" in body:
            self.writes.append(("add-sub-issue", body))
            return json.dumps({"data": {"addSubIssue": {"issue": {"id": "I_parent"}}}})

        # ----- blocked-by (GraphQL fallback, since develop probe = absent) -----
        if "addIssueDependency" in body:
            self.writes.append(("blocked-by", body))
            return json.dumps({"data": {"addIssueDependency": {"issue": {"id": "x"}}}})
        if body.startswith("issue edit") and "--add-blocked-by" in body:
            self.writes.append(("blocked-by", body))
            return ""

        return "{}"

    def _field_nodes(self):
        nodes = []
        for fname, opts in _SINGLE_SELECTS.items():
            nodes.append({"__typename": "ProjectV2SingleSelectField",
                          "id": f"F_{fname}", "name": fname, "dataType": "SINGLE_SELECT",
                          "options": [{"id": f"OPT_{fname}_{o}", "name": o, "description": ""}
                                      for o in opts]})
        for fname in _TEXT_FIELDS:
            nodes.append({"__typename": "ProjectV2FieldCommon",
                          "id": f"F_{fname}", "name": fname, "dataType": "TEXT"})
        return nodes

    def _record_written(self, body):
        fid = None
        for c in self.calls[-1]:
            c = str(c)
            if c.startswith("field=F_"):
                fid = c.split("=", 1)[1]
        if not fid:
            return
        if "singleSelectOptionId:" in body:
            val = body.split('singleSelectOptionId:"', 1)[1].split('"', 1)[0]
            self._written[fid] = ("optionId", val)
        elif "text:" in body:
            val = body.split('text:"', 1)[1].split('"', 1)[0]
            self._written[fid] = ("text", val)

    def _readback_nodes(self):
        nodes = []
        for fid, (kind, val) in self._written.items():
            if kind == "optionId":
                nodes.append({"optionId": val, "field": {"id": fid}})
            else:
                nodes.append({"text": val, "field": {"id": fid}})
        return nodes

    def count(self, predicate):
        return sum(1 for c in self.calls if predicate(_q(c)))


class Base(unittest.TestCase):
    def setUp(self):
        self._orig = gh.RUN
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _init_repo(self.root)
        self.staging = backlog.Staging(self.root)

    def tearDown(self):
        gh.RUN = self._orig
        self._tmp.cleanup()


# --------------------------------------------------------------------------- #
# Staging-area resolution at the git toplevel from a subdirectory.
# --------------------------------------------------------------------------- #
class TestStagingResolution(Base):
    def test_resolves_root_from_subdirectory(self):
        sub = os.path.join(self.root, "a", "b", "c")
        os.makedirs(sub)
        st = backlog.Staging.resolve(start=sub)
        # The resolved root is the git toplevel, not the subdirectory.
        self.assertEqual(os.path.realpath(st.root), os.path.realpath(self.root))
        self.assertTrue(st.dir.endswith(os.path.join(".gh-projects", "backlog")))

    def test_explicit_root_overrides(self):
        st = backlog.Staging.resolve(root=self.root)
        self.assertEqual(st.root, self.root)

    def test_outside_git_tree_is_error_code_3(self):
        with tempfile.TemporaryDirectory() as nogit:
            with self.assertRaises(backlog.BacklogError) as ctx:
                backlog.git_root(nogit)
            self.assertEqual(ctx.exception.code, 3)


# --------------------------------------------------------------------------- #
# Ledger entry records the decompose tree + proposed triage fields.
# --------------------------------------------------------------------------- #
class TestLedgerEntry(Base):
    def test_entry_records_all_fields(self):
        backlog.add_draft(self.staging, title="Add login", type_="Feature",
                          tier="T2", size="M", priority="P1",
                          target_repo="acme/web", force=True)
        entry = backlog.show_draft(self.staging, "add-login")["entry"]
        self.assertEqual(entry["title"], "Add login")
        self.assertEqual(entry["type"], "Feature")
        self.assertEqual(entry["tier"], "T2")
        self.assertEqual(entry["size"], "M")
        self.assertEqual(entry["priority"], "P1")
        self.assertEqual(entry["target_repo"], "acme/web")
        self.assertEqual(entry["status"], "stub")
        self.assertTrue(entry["file"].endswith("add-login.md"))
        # promote-only fields start empty
        for k in ("pm_id", "issue", "spec"):
            self.assertIsNone(entry[k])

    def test_draft_file_written_with_front_matter(self):
        backlog.add_draft(self.staging, title="Add login", type_="Feature",
                          tier="T2", body="body text", force=True)
        path = self.staging.draft_file("add-login")
        self.assertTrue(os.path.isfile(path))
        fm, body = backlog._read_draft_body(self.staging, "add-login")
        self.assertEqual(fm.get("title"), "Add login")
        self.assertIn("body text", body)

    def test_decompose_tree_recorded_via_link(self):
        backlog.add_draft(self.staging, title="Epic root", force=True)
        backlog.add_draft(self.staging, title="Child one", force=True)
        backlog.add_draft(self.staging, title="Child two", force=True)
        backlog.link_draft(self.staging, "child-one", parent="epic-root", force=True)
        backlog.link_draft(self.staging, "child-two", parent="epic-root",
                           blocked_by=["child-one"], force=True)
        c2 = backlog.show_draft(self.staging, "child-two")["entry"]
        self.assertEqual(c2["parent"], "epic-root")
        self.assertEqual(c2["blocked_by"], ["child-one"])

    def test_link_unknown_slug_is_error_code_3(self):
        backlog.add_draft(self.staging, title="Child", force=True)
        with self.assertRaises(backlog.BacklogError) as ctx:
            backlog.link_draft(self.staging, "child", parent="nope", force=True)
        self.assertEqual(ctx.exception.code, 3)


# --------------------------------------------------------------------------- #
# Target repo defaults/overridable + required to promote.
# --------------------------------------------------------------------------- #
class TestTargetRepo(Base):
    def test_target_repo_may_be_unset_in_stub(self):
        backlog.add_draft(self.staging, title="No repo yet", force=True)
        entry = backlog.show_draft(self.staging, "no-repo-yet")["entry"]
        self.assertIsNone(entry["target_repo"])

    def test_target_repo_overridable_via_set_fields(self):
        backlog.add_draft(self.staging, title="Item", force=True)
        backlog.set_fields(self.staging, "item", target_repo="acme/api", force=True)
        self.assertEqual(backlog.show_draft(self.staging, "item")["entry"]["target_repo"],
                         "acme/api")

    def test_promote_without_target_repo_refused_with_reason(self):
        backlog.add_draft(self.staging, title="Item", type_="Feature", tier="T1", force=True)
        backlog.set_status(self.staging, "item", "drafting", force=True)
        backlog.set_status(self.staging, "item", "ready", force=True)
        gh.RUN = BoardRunner()
        res = backlog.promote_draft(self.staging, "item", owner="acme",
                                    project_number=7, force=True)
        self.assertFalse(res["ready"])
        self.assertIn("target repo", res["reason"].lower())
        self.assertFalse(res["applied"])


# --------------------------------------------------------------------------- #
# Lifecycle stub -> drafting -> ready -> promoted.
# --------------------------------------------------------------------------- #
class TestLifecycle(Base):
    def test_advances_through_states(self):
        backlog.add_draft(self.staging, title="Item", type_="Feature", tier="T1",
                          target_repo="acme/web", force=True)
        self.assertEqual(backlog.show_draft(self.staging, "item")["entry"]["status"], "stub")
        backlog.set_status(self.staging, "item", "drafting", force=True)
        self.assertEqual(backlog.show_draft(self.staging, "item")["entry"]["status"], "drafting")
        backlog.set_status(self.staging, "item", "ready", force=True)
        self.assertEqual(backlog.show_draft(self.staging, "item")["entry"]["status"], "ready")
        gh.RUN = BoardRunner()
        backlog.promote_draft(self.staging, "item", owner="acme", project_number=7, force=True)
        self.assertEqual(backlog.show_draft(self.staging, "item")["entry"]["status"], "promoted")

    def test_set_status_promoted_rejected(self):
        backlog.add_draft(self.staging, title="Item", force=True)
        with self.assertRaises(backlog.BacklogError) as ctx:
            backlog.set_status(self.staging, "item", "promoted", force=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_set_status_idempotent(self):
        backlog.add_draft(self.staging, title="Item", force=True)
        res = backlog.set_status(self.staging, "item", "stub", force=True)
        self.assertFalse(res["changed"])


# --------------------------------------------------------------------------- #
# Promote: readiness-gated (stub/drafting refused WITH A REASON).
# --------------------------------------------------------------------------- #
class TestPromoteReadinessGate(Base):
    def _ready_repo(self, title, tier="T1"):
        backlog.add_draft(self.staging, title=title, type_="Feature", tier=tier,
                          size="S", priority="P1", target_repo="acme/web", force=True)

    def test_stub_refused_with_reason(self):
        self._ready_repo("Stub item")
        gh.RUN = BoardRunner()
        res = backlog.promote_draft(self.staging, "stub-item", owner="acme",
                                    project_number=7, force=True)
        self.assertFalse(res["ready"])
        self.assertIn("not 'ready'", res["reason"])
        self.assertFalse(res["applied"])

    def test_drafting_refused_with_reason(self):
        self._ready_repo("Drafting item")
        backlog.set_status(self.staging, "drafting-item", "drafting", force=True)
        gh.RUN = BoardRunner()
        res = backlog.promote_draft(self.staging, "drafting-item", owner="acme",
                                    project_number=7, force=True)
        self.assertFalse(res["ready"])
        self.assertFalse(res["applied"])

    def test_refused_promote_creates_no_issue(self):
        self._ready_repo("Stub item")
        runner = BoardRunner()
        gh.RUN = runner
        backlog.promote_draft(self.staging, "stub-item", owner="acme",
                              project_number=7, force=True)
        self.assertEqual(len(runner.issue_creates), 0)


# --------------------------------------------------------------------------- #
# Promote: idempotent (re-promote = no-op, NO duplicate issue create).
# --------------------------------------------------------------------------- #
class TestPromoteIsIdempotent(Base):
    def _make_ready(self, title, tier="T1"):
        backlog.add_draft(self.staging, title=title, type_="Feature", tier=tier,
                          size="S", priority="P1", target_repo="acme/web", force=True)
        slug = backlog.slugify(title)
        backlog.set_status(self.staging, slug, "drafting", force=True)
        backlog.set_status(self.staging, slug, "ready", force=True)
        return slug

    def test_repromote_is_clean_noop_no_duplicate(self):
        slug = self._make_ready("Add login")
        runner = BoardRunner()
        gh.RUN = runner
        first = backlog.promote_draft(self.staging, slug, owner="acme",
                                      project_number=7, force=True)
        self.assertTrue(first["applied"])
        self.assertEqual(first["issue"], 101)
        # second promote: reads the recorded issue, creates NO duplicate.
        second = backlog.promote_draft(self.staging, slug, owner="acme",
                                       project_number=7, force=True)
        self.assertTrue(second["noop"])
        self.assertEqual(second["issue"], 101)
        self.assertEqual(len(runner.issue_creates), 1,
                         "re-promote must not create a duplicate issue")


# --------------------------------------------------------------------------- #
# Promote: one-way (staging file removed, ledger marked promoted).
# --------------------------------------------------------------------------- #
class TestPromoteIsOneWay(Base):
    def test_staging_file_removed_and_marked_promoted(self):
        backlog.add_draft(self.staging, title="Add login", type_="Feature", tier="T1",
                          size="S", priority="P1", target_repo="acme/web",
                          body="b", force=True)
        backlog.set_status(self.staging, "add-login", "drafting", force=True)
        backlog.set_status(self.staging, "add-login", "ready", force=True)
        path = self.staging.draft_file("add-login")
        self.assertTrue(os.path.isfile(path))
        gh.RUN = BoardRunner()
        res = backlog.promote_draft(self.staging, "add-login", owner="acme",
                                    project_number=7, force=True)
        self.assertTrue(res["applied"])
        self.assertTrue(res["staging_file_removed"])
        self.assertFalse(os.path.isfile(path), "promote must remove the staging file")
        entry = backlog.show_draft(self.staging, "add-login")["entry"]
        self.assertEqual(entry["status"], "promoted")
        self.assertEqual(entry["issue"], 101)
        self.assertTrue(entry["pm_id"].startswith("PM-"))

    def test_promoted_draft_cannot_be_re_edited(self):
        slug = "add-login"
        backlog.add_draft(self.staging, title="Add login", type_="Feature", tier="T1",
                          size="S", priority="P1", target_repo="acme/web", force=True)
        backlog.set_status(self.staging, slug, "drafting", force=True)
        backlog.set_status(self.staging, slug, "ready", force=True)
        gh.RUN = BoardRunner()
        backlog.promote_draft(self.staging, slug, owner="acme", project_number=7, force=True)
        for call in (lambda: backlog.set_fields(self.staging, slug, size="L", force=True),
                     lambda: backlog.link_draft(self.staging, slug, parent=None,
                                                blocked_by=[], force=True)):
            with self.assertRaises(backlog.BacklogError):
                call()


# --------------------------------------------------------------------------- #
# Dry-by-default: no mutation without force.
# --------------------------------------------------------------------------- #
class TestDryByDefault(Base):
    def test_add_dry_writes_no_file_or_ledger(self):
        res = backlog.add_draft(self.staging, title="Item", force=False)
        self.assertFalse(res["applied"])
        self.assertFalse(os.path.isfile(self.staging.draft_file("item")))
        self.assertFalse(os.path.isfile(self.staging.ledger_path))

    def test_promote_dry_creates_no_issue_and_previews(self):
        backlog.add_draft(self.staging, title="Add login", type_="Feature", tier="T3",
                          size="M", priority="P1", target_repo="acme/web", body="b",
                          force=True)
        backlog.set_status(self.staging, "add-login", "drafting", force=True)
        backlog.set_status(self.staging, "add-login", "ready", force=True)
        runner = BoardRunner()
        gh.RUN = runner
        res = backlog.promote_draft(self.staging, "add-login", owner="acme",
                                    project_number=7, force=False)
        self.assertTrue(res["ready"])
        self.assertFalse(res["applied"])
        # The preview shows the planned spec publish + fields, but mutates nothing.
        self.assertEqual(res["spec_publish"], "specs/add-login.md")
        self.assertEqual(len(runner.issue_creates), 0)
        self.assertEqual(runner.writes, [])
        self.assertEqual(backlog.show_draft(self.staging, "add-login")["entry"]["status"],
                         "ready")


# --------------------------------------------------------------------------- #
# Projects v2 writes ride the App-token path (no GITHUB_TOKEN, no token print).
# --------------------------------------------------------------------------- #
class TestAppTokenOnly(Base):
    def _promote(self, tier="T2"):
        backlog.add_draft(self.staging, title="Add login", type_="Feature", tier=tier,
                          size="M", priority="P1", target_repo="acme/web", body="b",
                          force=True)
        backlog.set_status(self.staging, "add-login", "drafting", force=True)
        backlog.set_status(self.staging, "add-login", "ready", force=True)
        runner = BoardRunner()
        gh.RUN = runner
        res = backlog.promote_draft(self.staging, "add-login", owner="acme",
                                    project_number=7, force=True)
        return runner, res

    def test_projects_v2_writes_go_through_graphql_no_github_token(self):
        runner, res = self._promote()
        self.assertTrue(res["applied"])
        # Every field write + add-item rode `gh api graphql` (the App-token rail).
        v2 = [c for c in runner.calls
              if "updateProjectV2ItemFieldValue" in _q(c) or "addProjectV2ItemById" in _q(c)]
        self.assertTrue(v2)
        for c in v2:
            self.assertEqual(c[0], "api")
            self.assertEqual(c[1], "graphql")
            self.assertNotIn("GITHUB_TOKEN", _q(c))

    def test_no_token_printed_in_cli_output(self):
        # A leaky error must be scrubbed before backlog.py prints it.
        def leaky(args):
            raise gh.GhError("boom ghp_leakytoken1234567890abcdefghijklmnop")
        # ready draft so we reach the gh path.
        backlog.add_draft(self.staging, title="Add login", type_="Feature", tier="T1",
                          size="S", priority="P1", target_repo="acme/web", force=True)
        backlog.set_status(self.staging, "add-login", "drafting", force=True)
        backlog.set_status(self.staging, "add-login", "ready", force=True)
        gh.RUN = leaky
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = backlog.main(["--root", self.root, "promote", "add-login",
                                 "--owner", "acme", "--number", "7", "--force"])
        self.assertEqual(code, 1)
        blob = out.getvalue() + err.getvalue()
        self.assertNotIn("ghp_leakytoken1234567890abcdefghijklmnop", blob)
        self.assertIn("[REDACTED]", err.getvalue())


# --------------------------------------------------------------------------- #
# T3 publishes specs/<slug>.md + sets Spec; T1/T2 leave Spec empty.
# --------------------------------------------------------------------------- #
class TestSpecPublish(Base):
    def _promote(self, tier, body="deep spec body"):
        slug = "add-login"
        backlog.add_draft(self.staging, title="Add login", type_="Feature", tier=tier,
                          size="M", priority="P1", target_repo="acme/web", body=body,
                          force=True)
        backlog.set_status(self.staging, slug, "drafting", force=True)
        backlog.set_status(self.staging, slug, "ready", force=True)
        runner = BoardRunner()
        gh.RUN = runner
        res = backlog.promote_draft(self.staging, slug, owner="acme",
                                    project_number=7, force=True)
        return runner, res

    def test_t3_publishes_spec_and_sets_spec_field(self):
        runner, res = self._promote("T3")
        self.assertEqual(res["spec_published"], "specs/add-login.md")
        published = os.path.join(self.root, "specs", "add-login.md")
        self.assertTrue(os.path.isfile(published), "T3 must publish a durable spec")
        # the Spec field was written with the published path.
        spec_writes = [c for c in runner.calls
                       if "updateProjectV2ItemFieldValue" in _q(c) and "F_Spec" in _q(c)]
        self.assertTrue(spec_writes, "T3 must set the Spec field")
        entry = backlog.show_draft(self.staging, "add-login")["entry"]
        self.assertEqual(entry["spec"], "specs/add-login.md")

    def test_t1_leaves_spec_empty(self):
        self._assert_spec_empty("T1")

    def test_t2_leaves_spec_empty(self):
        self._assert_spec_empty("T2")

    def _assert_spec_empty(self, tier):
        runner, res = self._promote(tier)
        self.assertIsNone(res["spec_published"])
        self.assertFalse(os.path.isfile(os.path.join(self.root, "specs", "add-login.md")))
        spec_writes = [c for c in runner.calls
                       if "updateProjectV2ItemFieldValue" in _q(c) and "F_Spec" in _q(c)]
        self.assertEqual(spec_writes, [], f"{tier} must NOT set the Spec field")


# --------------------------------------------------------------------------- #
# Sub-issue + blocked-by edges re-established on promote (the decompose DAG).
# --------------------------------------------------------------------------- #
class TestPromoteEstablishesDag(Base):
    def test_parent_and_blocked_by_edges_written(self):
        # epic (promote first) -> child blocked by a sibling (promote last).
        for title, tier in (("Epic root", "T1"), ("Sib", "T1"), ("Child", "T1")):
            backlog.add_draft(self.staging, title=title, type_="Feature", tier=tier,
                              size="S", priority="P1", target_repo="acme/web", force=True)
        backlog.link_draft(self.staging, "child", parent="epic-root",
                           blocked_by=["sib"], force=True)
        for slug in ("epic-root", "sib", "child"):
            backlog.set_status(self.staging, slug, "drafting", force=True)
            backlog.set_status(self.staging, slug, "ready", force=True)
        runner = BoardRunner()
        gh.RUN = runner
        backlog.promote_draft(self.staging, "epic-root", owner="acme", project_number=7, force=True)
        backlog.promote_draft(self.staging, "sib", owner="acme", project_number=7, force=True)
        backlog.promote_draft(self.staging, "child", owner="acme", project_number=7, force=True)
        # the child's promote established a sub-issue link + a blocked-by edge.
        self.assertTrue([w for w in runner.writes if w[0] == "add-sub-issue"])
        self.assertTrue([w for w in runner.writes if w[0] == "blocked-by"])


# --------------------------------------------------------------------------- #
# Subcommands + the documented `list` columns + CLI exit codes.
# --------------------------------------------------------------------------- #
class TestCli(Base):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = backlog.main(["--root", self.root, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_add_list_show_subcommands(self):
        code, _, _ = self._run(["add", "--title", "Item one", "--type", "Feature",
                                "--tier", "T1", "--force"])
        self.assertEqual(code, 0)
        code, out, _ = self._run(["list"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["columns"], list(backlog.LIST_COLUMNS))
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["slug"], "item-one")
        code, out, _ = self._run(["show", "item-one"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["entry"]["title"], "Item one")

    def test_list_documented_columns(self):
        # The list columns are an explicit documented set.
        for col in ("slug", "title", "status", "type", "tier", "size",
                    "priority", "parent", "target_repo", "pm_id", "issue", "file"):
            self.assertIn(col, backlog.LIST_COLUMNS)

    def test_link_subcommand(self):
        self._run(["add", "--title", "P", "--force"])
        self._run(["add", "--title", "C", "--force"])
        code, out, _ = self._run(["link", "c", "--parent", "p", "--force"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["parent"], "p")

    def test_promote_refused_exit_2(self):
        self._run(["add", "--title", "Item", "--type", "Feature", "--tier", "T1",
                   "--repo", "acme/web", "--force"])
        gh.RUN = BoardRunner()
        code, out, _ = self._run(["promote", "item", "--owner", "acme",
                                  "--number", "7", "--force"])
        # not ready -> refusal -> exit 2
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ready"])

    def test_show_missing_exit_3(self):
        code, _, _ = self._run(["show", "nope"])
        self.assertEqual(code, 3)

    def test_usage_error_exit_2(self):
        code, _, _ = self._run(["promote", "x"])  # missing --owner/--number
        self.assertEqual(code, 2)

    def test_add_dry_by_default_no_force(self):
        code, out, err = self._run(["add", "--title", "Item"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["applied"])
        self.assertFalse(os.path.isfile(self.staging.ledger_path))


# --------------------------------------------------------------------------- #
# Resumability: unpromoted drafts persist; a re-run resumes them.
# --------------------------------------------------------------------------- #
class TestResumable(Base):
    def test_unpromoted_drafts_persist_across_fresh_staging_objects(self):
        backlog.add_draft(self.staging, title="One", force=True)
        backlog.add_draft(self.staging, title="Two", force=True)
        backlog.set_status(self.staging, "one", "drafting", force=True)
        # a brand-new Staging over the same root sees the persisted ledger.
        fresh = backlog.Staging(self.root)
        rows = {r["slug"]: r["status"] for r in backlog.list_drafts(fresh)["rows"]}
        self.assertEqual(rows, {"one": "drafting", "two": "stub"})


if __name__ == "__main__":
    unittest.main()
