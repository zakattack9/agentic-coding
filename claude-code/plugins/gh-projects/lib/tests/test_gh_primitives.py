#!/usr/bin/env python3
"""Offline tests for the FOUR start-issue / plan-sprint projection verbs on
lib/gh.py's CLI — add-item, write-field, advance-status,
create-linked-branch — NO network, NO live org, NO mutation. Every test installs
a fake RUN that returns canned JSON and counts round-trips.

These verbs reuse the core lib functions (add_item / write_field /
advance_status / create_linked_branch) — they add no new mutation primitive; they
only resolve-then-dispatch. They ride engine.sh's dry-by-default `--force` rail
(nothing mutates without --force).

Covers:
  add-item — a re-add returns the SAME board item id (idempotent projection)
  write-field — single-select / iteration (Sprint) / date read-back-identical
  advance-status — monotonic; an at/past-target re-run is a no-op (no write)
  create-linked-branch — an existing linked branch is a no-op (exit 0)
  dry-by-default — engine.sh runs NO mutation without --force; --force does
  App-token path (gh api graphql) — never GITHUB_TOKEN
  exit codes 0/2/3/1 + no secret leak
  the projection verbs emit no closing keyword
  "second call is a no-op" on replay for add-item / advance-status
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
PLUGIN = os.path.dirname(LIB)
sys.path.insert(0, LIB)

import gh  # noqa: E402

ENGINE = os.path.join(LIB, "engine.sh")

PROJECT_ID = "PVT_board"
ITEM_ID = "ITEM_issue7"   # stable board item id (re-add returns this)
NODE_ID = "I_issue7"      # the issue's GraphQL node id (from REST GET)

_SINGLE_SELECTS = {
    "Type": ["Feature", "Bug", "Chore", "Infra"],
    "Size": ["S", "M", "L"],
    "Tier": ["T1", "T2", "T3"],
    "Priority": ["P0", "P1", "P2", "P3"],
    "Status": ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"],
}
_TEXT_FIELDS = ["PM-ID", "Spec"]
_DATE_FIELDS = ["Start", "Target"]
_ITERATIONS = [
    {"id": "IT_s1", "title": "Sprint 1", "startDate": "2026-06-01", "duration": 14},
    {"id": "IT_s2", "title": "Sprint 2", "startDate": "2026-06-15", "duration": 14},
]


def _q(args):
    return " ".join(str(a) for a in args)


class PrimitiveRunner:
    """Fake gh runner: serves the board reads (project resolve incl. an iteration
    + date field, REST issue node-id, item Status, linked-branch state) and
    records every write round-trip.

    Presets the tests can set:
      * current_status   — the item's current board Status (advance-status replay)
      * existing_branch  — True ⇒ the issue already has a linked branch (no-op)
      * supports_develop — native `gh issue develop` available (cap path)
    """

    def __init__(self, *, current_status=None, existing_branch=False,
                 supports_develop=False, node_id=NODE_ID):
        self.calls = []
        self.writes = []
        self.current_status = current_status
        self.existing_branch = existing_branch
        self.supports_develop = supports_develop
        self.node_id = node_id
        self._written = {}   # field id -> (kind, value) for the two-phase read-back

    def __call__(self, args):
        self.calls.append(list(args))
        body = _q(args)

        # ----- capability probe: `gh issue develop --help` -----
        if body.startswith("issue develop") and "--help" in body:
            return "Create a linked branch\n--name string\n" if self.supports_develop else ""
        if "--help" in body:
            return ""

        # ----- native `gh issue develop` (linked branch create) -----
        if body.startswith("issue develop"):
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

        # ----- GraphQL: current item Status (advance-status read) -----
        if "projectItems(first:50)" in body:
            sv = {"name": self.current_status} if self.current_status else {}
            return json.dumps({"data": {"node": {"projectItems": {"nodes": [{
                "id": ITEM_ID,
                "project": {"number": 7, "owner": {"login": "acme"}},
                "fieldValueByName": sv,
            }]}}}})

        # ----- GraphQL: issue linked-branch state (create-linked-branch read) -----
        if "linkedBranches(first:10)" in body:
            branches = [{"ref": {"name": "7-existing"}}] if self.existing_branch else []
            return json.dumps({"data": {"repository": {
                "defaultBranchRef": {"target": {"oid": "deadbeef"}},
                "issue": {"id": self.node_id,
                          "linkedBranches": {"nodes": branches}}}}})

        # ----- GraphQL: createLinkedBranch fallback -----
        if "createLinkedBranch" in body:
            self.writes.append(("branch-graphql", body))
            return json.dumps({"data": {"createLinkedBranch": {"linkedBranch": {
                "id": "LB_1", "ref": {"name": "7-route-this-issue"}}}}})

        # ----- REST GET issue (node_id resolution) -----
        if "api -X GET" in body and "/issues/" in body:
            return json.dumps({"node_id": self.node_id})

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
        for fname in _DATE_FIELDS:
            nodes.append({"__typename": "ProjectV2FieldCommon",
                          "id": f"F_{fname}", "name": fname, "dataType": "DATE"})
        # the Sprint iteration field (configuration, not options)
        nodes.append({
            "__typename": "ProjectV2IterationField",
            "id": "F_Sprint", "name": "Sprint", "dataType": "ITERATION",
            "configuration": {"iterations": _ITERATIONS, "completedIterations": []},
        })
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
            self._written[fid] = ("optionId", body.split('singleSelectOptionId:"', 1)[1].split('"', 1)[0])
        elif "iterationId:" in body:
            self._written[fid] = ("iterationId", body.split('iterationId:"', 1)[1].split('"', 1)[0])
        elif "date:" in body:
            self._written[fid] = ("date", body.split('date:"', 1)[1].split('"', 1)[0])
        elif "text:" in body:
            self._written[fid] = ("text", body.split('text:"', 1)[1].split('"', 1)[0])

    def _readback_nodes(self):
        nodes = []
        for fid, (kind, val) in self._written.items():
            if kind == "optionId":
                nodes.append({"optionId": val, "field": {"id": fid}})
            elif kind == "iterationId":
                nodes.append({"iterationId": val, "field": {"id": fid}})
            elif kind == "date":
                nodes.append({"date": val, "field": {"id": fid}})
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

    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gh.main(argv)
        return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
# add-item: re-add returns the SAME item id (idempotent projection)
# --------------------------------------------------------------------------- #
class TestAddItem(Base):
    def test_dispatch_returns_item_id(self):
        gh.RUN = PrimitiveRunner()
        code, out, _ = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "acme/web", "--issue", "7"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["item"], ITEM_ID)

    def test_re_add_returns_same_item_id(self):
        runner = PrimitiveRunner()
        gh.RUN = runner
        c1, o1, _ = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "acme/web", "--issue", "7"])
        c2, o2, _ = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "acme/web", "--issue", "7"])
        self.assertEqual(c1, 0)
        self.assertEqual(c2, 0)
        self.assertEqual(json.loads(o1)["item"], json.loads(o2)["item"],
                         "a re-add must yield the same board item id")

    def test_uses_app_token_graphql_path(self):
        # add_item rides `gh api graphql` (the App-token write path), never GITHUB_TOKEN.
        runner = PrimitiveRunner()
        gh.RUN = runner
        self._main(["add-item", "--owner", "acme", "--number", "7",
                    "--repo", "acme/web", "--issue", "7"])
        add = next(c for c in runner.calls if "addProjectV2ItemById" in _q(c))
        self.assertEqual(add[0], "api")
        self.assertEqual(add[1], "graphql")
        self.assertNotIn("GITHUB_TOKEN", _q(add))


# --------------------------------------------------------------------------- #
# write-field: single-select / iteration (Sprint) / date read-back-identical
# --------------------------------------------------------------------------- #
class TestWriteField(Base):
    def test_single_select_read_back(self):
        gh.RUN = PrimitiveRunner()
        code, out, _ = self._main(
            ["write-field", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--field", "Type", "--value", "Feature"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertTrue(res["verified"])
        # the resolved option id (not the raw name) was written + read back
        self.assertEqual(res["value"], "OPT_Type_Feature")

    def test_iteration_sprint_resolves_title_to_id(self):
        runner = PrimitiveRunner()
        gh.RUN = runner
        code, out, _ = self._main(
            ["write-field", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--field", "Sprint", "--value", "Sprint 2"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertTrue(res["verified"])
        self.assertEqual(res["value"], "IT_s2", "Sprint title must resolve to its iteration id")
        # the mutation carried an iterationId literal (not a singleSelectOptionId)
        setf = next(c for c in runner.calls if "updateProjectV2ItemFieldValue" in _q(c))
        self.assertIn('iterationId:"IT_s2"', _q(setf))

    def test_date_field_read_back(self):
        runner = PrimitiveRunner()
        gh.RUN = runner
        code, out, _ = self._main(
            ["write-field", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--field", "Start", "--value", "2026-06-15"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertTrue(res["verified"])
        self.assertEqual(res["value"], "2026-06-15")
        setf = next(c for c in runner.calls if "updateProjectV2ItemFieldValue" in _q(c))
        self.assertIn('date:"2026-06-15"', _q(setf))

    def test_bad_option_is_not_found_exit_3(self):
        gh.RUN = PrimitiveRunner()
        code, _, err = self._main(
            ["write-field", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--field", "Type", "--value", "Nonexistent"])
        self.assertEqual(code, 3)


# --------------------------------------------------------------------------- #
# advance-status: monotonic; an at/past-target re-run is a no-op
# --------------------------------------------------------------------------- #
class TestAdvanceStatus(Base):
    def test_advances_forward_writes_status(self):
        runner = PrimitiveRunner(current_status="Ready")
        gh.RUN = runner
        code, out, _ = self._main(
            ["advance-status", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--to", "In Progress"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["decision"], "advanced")
        self.assertEqual(res["to"], "In Progress")
        self.assertTrue([w for w in runner.writes if w[0] == "set-field"],
                        "a forward advance must write the Status field")

    def test_at_or_past_target_is_noop_no_write(self):
        # item already In Review; advancing to In Progress is a backward move = no-op
        runner = PrimitiveRunner(current_status="In Review")
        gh.RUN = runner
        code, out, _ = self._main(
            ["advance-status", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--to", "In Progress"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "no-op")
        self.assertFalse([w for w in runner.writes if w[0] == "set-field"],
                         "a re-route past the target writes no Status")

    def test_replay_writes_status_at_most_once(self):
        # call 1: Ready -> In Progress writes; call 2: now In Progress -> no-op
        r1 = PrimitiveRunner(current_status="Ready")
        gh.RUN = r1
        self._main(["advance-status", "--owner", "acme", "--number", "7",
                    "--repo", "acme/web", "--issue", "7", "--to", "In Progress"])
        self.assertEqual(len([w for w in r1.writes if w[0] == "set-field"]), 1)
        r2 = PrimitiveRunner(current_status="In Progress")
        gh.RUN = r2
        c2, o2, _ = self._main(["advance-status", "--owner", "acme", "--number", "7",
                                "--repo", "acme/web", "--issue", "7", "--to", "In Progress"])
        self.assertEqual(c2, 0)
        self.assertEqual(json.loads(o2)["decision"], "no-op")
        self.assertEqual(len([w for w in r2.writes if w[0] == "set-field"]), 0)

    def test_fresh_item_no_current_status_advances(self):
        runner = PrimitiveRunner(current_status=None)
        gh.RUN = runner
        code, out, _ = self._main(
            ["advance-status", "--owner", "acme", "--number", "7", "--repo", "acme/web",
             "--issue", "7", "--to", "Ready"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "advanced")


# --------------------------------------------------------------------------- #
# create-linked-branch: existing branch = no-op (exit 0)
# --------------------------------------------------------------------------- #
class TestCreateLinkedBranch(Base):
    def test_existing_branch_is_noop_exit_0(self):
        runner = PrimitiveRunner(existing_branch=True)
        gh.RUN = runner
        code, out, _ = self._main(
            ["create-linked-branch", "--repo", "acme/web", "--issue", "7"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "already-linked")
        # no branch was created (neither native nor GraphQL)
        self.assertFalse(runner.writes, "an existing linked branch creates nothing")

    def test_creates_via_graphql_when_absent(self):
        runner = PrimitiveRunner(existing_branch=False, supports_develop=False)
        gh.RUN = runner
        code, out, _ = self._main(
            ["create-linked-branch", "--repo", "acme/web", "--issue", "7",
             "--name", "7-route-this-issue"])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual(res["action"], "created")
        self.assertEqual(res["via"], "graphql")
        self.assertTrue([w for w in runner.writes if w[0] == "branch-graphql"])

    def test_creates_via_native_when_supported(self):
        runner = PrimitiveRunner(existing_branch=False, supports_develop=True)
        gh.RUN = runner
        code, out, _ = self._main(
            ["create-linked-branch", "--repo", "acme/web", "--issue", "7",
             "--name", "7-route-this-issue"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["via"], "native")
        self.assertTrue([w for w in runner.writes if w[0] == "branch-native"])
        self.assertEqual(runner.count(lambda q: "createLinkedBranch" in q), 0)

    def test_replay_after_link_is_noop(self):
        # first run creates; a replay (now existing_branch=True) is a clean no-op
        runner = PrimitiveRunner(existing_branch=False)
        gh.RUN = runner
        self._main(["create-linked-branch", "--repo", "acme/web", "--issue", "7"])
        runner.existing_branch = True
        runner.writes.clear()
        code, out, _ = self._main(["create-linked-branch", "--repo", "acme/web", "--issue", "7"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["action"], "already-linked")
        self.assertFalse(runner.writes)


# --------------------------------------------------------------------------- #
# exit codes + no secret leak across the CLI surface
# --------------------------------------------------------------------------- #
class TestCliExitAndSecret(Base):
    def test_add_item_usage_error_exit_2(self):
        code, _, _ = self._main(["add-item", "--owner", "acme"])
        self.assertEqual(code, 2)

    def test_write_field_usage_error_exit_2(self):
        code, _, _ = self._main(
            ["write-field", "--owner", "acme", "--number", "7", "--repo", "acme/web"])
        self.assertEqual(code, 2)

    def test_malformed_repo_exit_2(self):
        gh.RUN = PrimitiveRunner()
        code, _, _ = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "noslash", "--issue", "7"])
        self.assertEqual(code, 2)

    def test_missing_issue_exit_3(self):
        runner = PrimitiveRunner(node_id=None)  # REST GET returns no node_id
        gh.RUN = runner
        code, _, _ = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "acme/web", "--issue", "999"])
        self.assertEqual(code, 3)

    def test_unexpected_exit_1(self):
        def boom(args):
            raise RuntimeError("kaboom")

        gh.RUN = boom
        code, _, _ = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "acme/web", "--issue", "7"])
        self.assertEqual(code, 1)

    def test_no_secret_in_output(self):
        def leaky(args):
            raise gh.GhError("boom ghp_leakytoken1234567890abcdefghijklmnop")

        gh.RUN = leaky
        code, out, err = self._main(
            ["add-item", "--owner", "acme", "--number", "7", "--repo", "acme/web", "--issue", "7"])
        self.assertNotIn("ghp_leakytoken1234567890abcdefghijklmnop", out + err)
        self.assertIn("[REDACTED]", err)


# --------------------------------------------------------------------------- #
# the projection verbs emit NO closing keyword (source scan)
# --------------------------------------------------------------------------- #
class TestNoClosingKeyword(Base):
    def test_projection_cmd_source_has_no_closer(self):
        with open(os.path.join(LIB, "gh.py"), "r", encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _cmd_add_item")
        end = src.index("def build_parser")
        block = src[start:end].lower()
        for kw in ("closes #", "fixes #", "resolves #", 'f"closes', "closeissue"):
            self.assertNotIn(kw, block)


# --------------------------------------------------------------------------- #
# dry-by-default via engine.sh: no mutation without --force; --force does
# --------------------------------------------------------------------------- #
class TestDryByDefaultRail(unittest.TestCase):
    """The four write verbs fall through engine.sh's `*)` branch (not in the
    {resolve|capabilities|token} read-whitelist), so they are auto-gated by
    --force: a dry run previews and mutates NOTHING."""

    def _engine(self, *args, env=None):
        e = dict(os.environ)
        e.pop("CLAUDE_PLUGIN_ROOT", None)
        if env:
            e.update(env)
        return subprocess.run(["bash", ENGINE, *args],
                              capture_output=True, text=True, env=e)

    def test_add_item_dry_run_mutates_nothing(self):
        proc = self._engine("add-item", "--owner", "o", "--number", "1",
                            "--repo", "o/r", "--issue", "1")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertIn("--force", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "",
                         "dry-run must run no mutation (no result emitted)")

    def test_write_field_dry_run_mutates_nothing(self):
        proc = self._engine("write-field", "--owner", "o", "--number", "1",
                            "--repo", "o/r", "--issue", "1", "--field", "Type", "--value", "Feature")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_advance_status_dry_run_mutates_nothing(self):
        proc = self._engine("advance-status", "--owner", "o", "--number", "1",
                            "--repo", "o/r", "--issue", "1", "--to", "In Progress")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_create_linked_branch_dry_run_mutates_nothing(self):
        proc = self._engine("create-linked-branch", "--repo", "o/r", "--issue", "1")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("dry-run", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_force_runs_add_item(self):
        # With --force the engine actually invokes gh.py add-item. A stub `gh` on
        # PATH serves the REST node-id GET + the addProjectV2ItemById mutation, so
        # no real network is touched and we prove --force executes the write verb.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "gh")
            with open(stub, "w", encoding="utf-8") as fh:
                fh.write(
                    "#!/usr/bin/env bash\n"
                    "all=\"$*\"\n"
                    "case \"$all\" in\n"
                    "  *fields\\(first:100\\)*) "
                    "echo '{\"data\":{\"organization\":{\"projectV2\":{\"id\":\"P\",\"title\":\"B\","
                    "\"fields\":{\"nodes\":[]}}}}}' ;;\n"
                    "  *addProjectV2ItemById*) "
                    "echo '{\"data\":{\"addProjectV2ItemById\":{\"item\":{\"id\":\"ITEM_x\"}}}}' ;;\n"
                    "  *issues/*) echo '{\"node_id\":\"I_x\"}' ;;\n"
                    "  *) echo '{}' ;;\n"
                    "esac\n")
            os.chmod(stub, 0o755)
            env = {"PATH": d + os.pathsep + os.environ.get("PATH", "")}
            proc = self._engine("add-item", "--owner", "acme", "--number", "7",
                                "--repo", "acme/web", "--issue", "7", "--force", env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("dry-run", proc.stderr)
            self.assertIn("ITEM_x", proc.stdout)


if __name__ == "__main__":
    unittest.main()
