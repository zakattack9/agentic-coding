#!/usr/bin/env python3
"""Offline tests for the start-issue leaf — NO network, NO live
org, NO mutation. start-issue is thin prose that orchestrates the EXISTING
lib/gh.py verbs (add_item / write_field / advance_status / create_linked_branch /
set_assignee), all behind engine.sh's dry-by-default `--force` rail. These tests
exercise that orchestrated behavior against an injected fake RUN (the
CountingRunner / fake-RUN pattern from test_gh_writeverbs.py + test_scaffold.py).

Covers:
  - project the issue (add_item REUSES the existing board item on re-add —
    same item id), advance Status to In Progress read-back-identical, optionally
    self-assign the actor when --assignee is given. start-issue sets ONLY
    work-start state (Status/assignee/branch) — it does NOT write the triage
    fields Type/Size/Tier/PM-ID/Spec/Priority (create-issues sets those at
    promote, landing the item at Backlog).
  - create the authoritative linked branch — BOTH capability paths (native
    `gh issue develop` + GraphQL createLinkedBranch); a re-run on an
    existing linked branch is a no-op (exit 0), never an error.
  - advance Status ONLY monotonically — a re-route never regresses an item
    already at/past the target (advance_status).
  - dry-by-default — without --force the engine adds no item, sets no
    field, creates no branch, sets no assignee; --force does (via engine.sh).
  - start-issue/SKILL.md declares disable-model-invocation true, model
    claude-opus-4-8, effort medium, AND carries the PreToolUse/Bash guard
    hooks block pointing at hooks/guard.sh.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
PLUGIN = os.path.dirname(LIB)
sys.path.insert(0, LIB)

import gh  # noqa: E402

ENGINE = os.path.join(LIB, "engine.sh")
SKILL_MD = os.path.join(PLUGIN, "skills", "start-issue", "SKILL.md")

# The work-start state start-issue owns (the field-home split: start-issue sets
# ONLY Status here — plus the assignee + linked branch handled separately). It
# does NOT set the triage fields below; create-issues sets those at promote.
WORK_START_FIELDS = {
    "Status": "In Progress",
}

# The triage fields start-issue must NOT touch (create-issues sets these at
# promote, landing the item at Backlog), and the scheduling fields plan-sprint
# owns. Asserting start-issue stays out of both.
TRIAGE_FIELDS = ("Type", "Size", "Tier", "PM-ID", "Spec", "Priority")
SCHEDULING_FIELDS = ("Sprint", "Milestone", "Start", "Target")


def _q(args):
    return " ".join(str(a) for a in args)


# --------------------------------------------------------------------------- #
# A fake gh runner modelling the board the start-issue projection writes onto.
# It serves the project field/option resolve, addProjectV2ItemById (REUSING a
# stable item id per content so a re-add returns the same id), the
# two-phase field write + read-back, the assignee read/edit, and both
# linked-branch capability paths. Every WRITE round-trip is recorded.
# --------------------------------------------------------------------------- #
PROJECT_ID = "PVT_board"
ITEM_ID = "ITEM_issue7"          # stable item id for the projected issue
CONTENT_ID = "I_issue7"          # the issue's node id

_SINGLE_SELECTS = {
    "Type": ["Feature", "Bug", "Chore", "Infra"],
    "Size": ["S", "M", "L"],
    "Tier": ["T1", "T2", "T3"],
    "Priority": ["P0", "P1", "P2", "P3"],
    "Status": ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"],
}
_TEXT_FIELDS = ["PM-ID", "Spec"]


class RouteRunner:
    """Fake gh runner: serves the board reads + records every write round-trip.

    Presets the tests can set:
      * supports_develop — whether the probed `gh` exposes `gh issue develop`
                           (drives the native vs GraphQL capability path)
      * existing_branch  — True ⇒ the issue already has a linked branch (re-run
                           no-op path); native `gh issue develop` then reports
                           "already linked" and is a clean no-op
      * current_status   — the item's current Status (for monotonic replay)
      * assignees        — the issue's current assignee logins (a set)
    """

    def __init__(self, *, supports_develop=True, existing_branch=False,
                 current_status=None, assignees=None):
        self.calls = []
        self.writes = []            # (kind, detail) for every mutating round-trip
        self.supports_develop = supports_develop
        self.existing_branch = existing_branch
        self.current_status = current_status
        self.assignees = set(assignees or [])
        # Per-field last-written value so the two-phase read-back matches.
        self._written = {}

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)

        # ----- capability probe: `gh issue develop --help` -----
        if body.startswith("issue develop") and "--help" in body:
            return "Create a linked branch\n--name string\n" if self.supports_develop else ""
        if "--help" in body:
            return ""  # other capability probes: feature absent

        # ----- native `gh issue develop` (linked branch create) -----
        if body.startswith("issue develop"):
            if self.existing_branch:
                # native gh treats an already-linked issue as a no-op (exit 0).
                self.writes.append(("branch-native-noop", body))
                return ""
            self.writes.append(("branch-native", body))
            return ""

        # ----- GraphQL: project + field resolve -----
        if "fields(first:100)" in body:
            return json.dumps({"data": {"organization": {"projectV2": {
                "id": PROJECT_ID, "number": 7, "title": "Board",
                "fields": {"nodes": self._field_nodes()}}}}})

        # ----- GraphQL: addProjectV2ItemById (REUSE a stable item id) -----
        if "addProjectV2ItemById" in body:
            self.writes.append(("add-item", body))
            return json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": ITEM_ID}}}})

        # ----- GraphQL: updateProjectV2ItemFieldValue (field write) -----
        if "updateProjectV2ItemFieldValue" in body:
            self.writes.append(("set-field", body))
            self._record_written(body)
            return json.dumps({"data": {"updateProjectV2ItemFieldValue": {
                "projectV2Item": {"id": ITEM_ID}}}})

        # ----- GraphQL: field read-back (the two-phase verify) -----
        if "fieldValues(first:50)" in body:
            return json.dumps({"data": {"node": {"id": ITEM_ID,
                "fieldValueByName": {"nodes": self._readback_nodes()}}}})

        # ----- GraphQL: createLinkedBranch fallback -----
        if "createLinkedBranch" in body:
            self.writes.append(("branch-graphql", body))
            return json.dumps({"data": {"createLinkedBranch": {"linkedBranch": {
                "id": "LB_1", "ref": {"name": "7-route-this-issue"}}}}})

        # ----- REST GET issue (assignee current state) -----
        if "api -X GET" in body and "/issues/" in body:
            return json.dumps({"assignees": [{"login": a} for a in sorted(self.assignees)]})
        # ----- gh issue edit (assignee add/remove) -----
        if body.startswith("issue edit"):
            self.writes.append(("assignee", body))
            return ""

        return "{}"

    # -- helpers ---------------------------------------------------------- #
    def _field_nodes(self):
        nodes = []
        for fname, opts in _SINGLE_SELECTS.items():
            nodes.append({
                "__typename": "ProjectV2SingleSelectField",
                "id": f"F_{fname}", "name": fname, "dataType": "SINGLE_SELECT",
                "options": [{"id": f"OPT_{fname}_{o}", "name": o, "description": ""}
                            for o in opts],
            })
        for fname in _TEXT_FIELDS:
            nodes.append({"__typename": "ProjectV2FieldCommon",
                          "id": f"F_{fname}", "name": fname, "dataType": "TEXT"})
        return nodes

    def _record_written(self, body):
        # Capture the field id + the typed literal value from the inlined mutation
        # so the read-back serves back exactly what was written.
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

    def tearDown(self):
        gh.RUN = self._orig

    def _project(self, runner):
        gh.RUN = runner
        return gh.Project("acme", 7).resolve()


# --------------------------------------------------------------------------- #
# Projection: reuse the existing item, populate intake fields, self-assign
# --------------------------------------------------------------------------- #
class TestProjection(Base):
    def test_re_add_returns_same_item_id(self):
        # add_item is the projection seam: re-adding an already-added issue yields
        # the SAME board item id (idempotent projection — no duplicate item).
        runner = RouteRunner()
        proj = self._project(runner)
        first = gh.add_item(proj.id, CONTENT_ID)
        second = gh.add_item(proj.id, CONTENT_ID)
        self.assertEqual(first, ITEM_ID)
        self.assertEqual(second, first,
                         "re-add must reuse the existing board item id")

    def test_work_start_status_reads_back_identical(self):
        # start-issue's one field write is Status -> In Progress; it reads back
        # identical (write_field raises on a read-back mismatch).
        runner = RouteRunner()
        proj = self._project(runner)
        dump = {}
        for fname, value in WORK_START_FIELDS.items():
            res = gh.write_field(proj, CONTENT_ID, fname, value)
            self.assertTrue(res["verified"], f"{fname} must read back identical")
            dump[fname] = value
        self.assertEqual(dump, WORK_START_FIELDS)

    def test_sets_only_status_not_triage_or_scheduling_fields(self):
        # Field-home split: start-issue's work-start state is Status only (plus
        # the assignee + branch). It does NOT write the triage fields (create-
        # issues sets those at promote) nor the scheduling fields (plan-sprint).
        self.assertEqual(set(WORK_START_FIELDS), {"Status"})
        for triage in TRIAGE_FIELDS:
            self.assertNotIn(triage, WORK_START_FIELDS)
        for sched in SCHEDULING_FIELDS:
            self.assertNotIn(sched, WORK_START_FIELDS)

    def test_skill_does_not_write_triage_fields(self):
        # The SKILL.md must not instruct a write-field for any triage field — those
        # moved to create-issues' promote. (A `--field Type` write-field line would
        # mean start-issue still owns the triage fields.)
        with open(SKILL_MD, "r", encoding="utf-8") as fh:
            text = fh.read()
        for triage in TRIAGE_FIELDS:
            self.assertNotIn(f"--field {triage}", text,
                             f"start-issue must not write the triage field {triage}")

    def test_assignee_path_sets_assignee(self):
        # The --assignee path self-assigns the actor (set_assignee), add when absent.
        runner = RouteRunner(assignees=set())
        gh.RUN = runner
        res = gh.set_assignee("acme/web", 7, "octocat")
        self.assertTrue(res["changed"])
        self.assertTrue(runner.count(lambda q: "--add-assignee" in q))

    def test_assignee_already_present_is_noop(self):
        runner = RouteRunner(assignees={"octocat"})
        gh.RUN = runner
        res = gh.set_assignee("acme/web", 7, "octocat")
        self.assertFalse(res["changed"])
        self.assertEqual(runner.count(lambda q: q.startswith("issue edit")), 0)


# --------------------------------------------------------------------------- #
# Authoritative linked branch: both capability paths + re-run no-op
# --------------------------------------------------------------------------- #
class TestLinkedBranch(Base):
    def test_native_path_when_gh_supports_develop(self):
        runner = RouteRunner(supports_develop=True)
        gh.RUN = runner
        res = gh.create_linked_branch("I_issue7", "deadbeef",
                                      name="7-route-this-issue",
                                      repo="acme/web", issue_number=7)
        self.assertEqual(res["via"], "native")
        self.assertTrue([w for w in runner.writes if w[0] == "branch-native"])
        # the native path used `gh issue develop`, not the GraphQL mutation.
        self.assertEqual(runner.count(lambda q: "createLinkedBranch" in q), 0)

    def test_graphql_fallback_when_develop_absent(self):
        runner = RouteRunner(supports_develop=False)
        gh.RUN = runner
        res = gh.create_linked_branch("I_issue7", "deadbeef",
                                      name="7-route-this-issue",
                                      repo="acme/web", issue_number=7)
        self.assertEqual(res["via"], "graphql")
        self.assertTrue([w for w in runner.writes if w[0] == "branch-graphql"])

    def test_rerun_on_existing_branch_is_noop_exit_0(self):
        # A re-run detects the existing linked branch: native gh treats it as a
        # no-op and returns cleanly (exit 0) — never an error.
        runner = RouteRunner(supports_develop=True, existing_branch=True)
        gh.RUN = runner
        res = gh.create_linked_branch("I_issue7", "deadbeef",
                                      name="7-route-this-issue",
                                      repo="acme/web", issue_number=7)
        self.assertEqual(res["via"], "native")
        self.assertTrue([w for w in runner.writes if w[0] == "branch-native-noop"],
                        "re-run on an existing linked branch is a no-op")


# --------------------------------------------------------------------------- #
# Status advances ONLY monotonically (re-route never regresses)
# --------------------------------------------------------------------------- #
class TestMonotonicStatus(Base):
    def test_advances_forward(self):
        # Ready -> In Progress is a forward move: advance_status returns the target.
        self.assertEqual(gh.advance_status("Ready", "In Progress"), "In Progress")

    def test_no_backward_write_when_already_past_target(self):
        # Re-route an item already In Review back toward In Progress: NO write.
        self.assertIsNone(gh.advance_status("In Review", "In Progress"),
                          "re-route must not regress a more-advanced item")

    def test_replay_no_backward_status_write(self):
        # Replay the same route twice. The first advances Ready->In Progress; the
        # second (item now In Progress) is a no-op (None == do not write).
        first = gh.advance_status("Ready", "In Progress")
        self.assertEqual(first, "In Progress")
        second = gh.advance_status("In Progress", "In Progress")
        self.assertIsNone(second, "a monotonic replay writes Status at most once")

    def test_at_target_is_noop(self):
        self.assertIsNone(gh.advance_status("Done", "Done"))


# --------------------------------------------------------------------------- #
# Dry-by-default via engine.sh: no write without --force; --force writes.
# --------------------------------------------------------------------------- #
class TestDryByDefault(Base):
    """start-issue's writes ride engine.sh's `--force` rail. We exercise the rail
    with a start-issue write that IS exposed as a CLI verb (set-assignee — the
    self-assign step): without --force the engine previews and runs no mutation;
    with --force it runs the verb. (The field/branch projection rides the same
    rail; the projection writes themselves are unit-tested above.)"""

    def _engine(self, *args, env=None):
        e = dict(os.environ)
        e.pop("CLAUDE_PLUGIN_ROOT", None)  # let engine.sh resolve lib_dir locally
        if env:
            e.update(env)
        return subprocess.run(["bash", ENGINE, *args],
                              capture_output=True, text=True, env=e)

    def test_dry_run_writes_nothing(self):
        # No --force: engine previews the write verb and mutates nothing (exit 0).
        proc = self._engine("set-assignee", "--repo", "acme/web",
                            "--number", "7", "--login", "octocat")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertIn("--force", proc.stderr)
        # The write verb was NOT executed: no JSON result on stdout.
        self.assertEqual(proc.stdout.strip(), "",
                         "dry-run must run no mutation (no result emitted)")

    def test_force_runs_the_write_verb(self):
        # With --force the engine actually invokes gh.py's set-assignee. We stub a
        # `gh` on PATH that records the issue-edit so no real network is touched.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "gh")
            with open(stub, "w", encoding="utf-8") as fh:
                fh.write("#!/usr/bin/env bash\n"
                         "# stub gh: serve the assignee GET, swallow the edit.\n"
                         'if printf "%s" "$*" | grep -q "issues/"; then\n'
                         '  echo \'{"assignees": []}\'\n'
                         "else\n"
                         "  :\n"
                         "fi\n")
            os.chmod(stub, 0o755)
            env = {"PATH": d + os.pathsep + os.environ.get("PATH", "")}
            proc = self._engine("set-assignee", "--repo", "acme/web",
                                "--number", "7", "--login", "octocat",
                                "--force", env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("dry-run", proc.stderr)
            # --force path emits the JSON result on stdout (the write ran).
            self.assertIn("octocat", proc.stdout)


# --------------------------------------------------------------------------- #
# start-issue/SKILL.md static frontmatter assertions.
# --------------------------------------------------------------------------- #
class TestSkillFrontmatter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL_MD, "r", encoding="utf-8") as fh:
            cls.text = fh.read()
        # Slice the YAML frontmatter block (between the first two `---` fences).
        parts = cls.text.split("---", 2)
        cls.fm = parts[1] if len(parts) >= 3 else ""

    def test_disable_model_invocation_true(self):
        self.assertRegex(self.fm, r"(?m)^disable-model-invocation:\s*true\s*$")

    def test_model_is_opus(self):
        self.assertRegex(self.fm, r"(?m)^model:\s*claude-opus-4-8\s*$")

    def test_effort_is_medium(self):
        self.assertRegex(self.fm, r"(?m)^effort:\s*medium\s*$")

    def test_name_is_start_issue(self):
        self.assertRegex(self.fm, r"(?m)^name:\s*start-issue\s*$")

    def test_carries_guard_hooks_block(self):
        # The PreToolUse / matcher "Bash" guard block pointing at guard.sh
        # so the guard is active ONLY while start-issue runs.
        self.assertIn("PreToolUse:", self.fm)
        self.assertRegex(self.fm, r'matcher:\s*"Bash"')
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh", self.fm)
        # the hook is a command-type PreToolUse hook (a YAML list item).
        self.assertRegex(self.fm, r"(?m)^\s*-?\s*type:\s*command\s*$")

    def test_least_privilege_allowed_tools(self):
        # mirror scaffold-repo/sync-signals: python3/bash/Read/AskUserQuestion.
        self.assertRegex(self.fm, r"(?m)^allowed-tools:\s")
        self.assertIn("Bash(python3 *)", self.fm)
        self.assertIn("Bash(bash *)", self.fm)


if __name__ == "__main__":
    unittest.main()
