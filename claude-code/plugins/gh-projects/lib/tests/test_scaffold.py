#!/usr/bin/env python3
"""Offline tests for lib/scaffold.py — NO network, NO live org, NO live mutation.

A fake gh runner stubs every GraphQL/REST round-trip (copyProjectV2, the org +
template resolve, the COPY's field resolve, org Issue Field list, REST settings).
Verifies that:

  * scaffold stands the project up via copyProjectV2 from the NAMED golden
    template; the copy carries every Data-model project field.
  * ids/options/iterations are re-resolved against the COPY, never the
    template — resolved ids != template ids in the fixture.
  * a second run is a no-op for fields and SKIPS existing iterations
    (iteration-mutation count == 0; re-run install manifest empty).
  * the install manifest lists ALL required destination paths (issue forms,
    PR template, board-sync.yml, signals-sync.yml, board-status action,
    release.yml, CODEOWNERS, project README); org Issue Fields + no-squash
    + App access are planned.
  * dry-run mutates nothing (no copy of files, no REST/GraphQL writes).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import gh  # noqa: E402
import scaffold  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixture: the TEMPLATE and the COPY have DISTINCT field/option/iteration ids so
# re-resolution ("resolved ids != template ids") is observable. The runner serves the
# template's fields when resolved by the template number, the copy's fields when
# resolved by the copy number.
# --------------------------------------------------------------------------- #
TEMPLATE_NUMBER = 1
COPY_NUMBER = 42
TEMPLATE_PROJECT_ID = "PVT_template"
COPY_PROJECT_ID = "PVT_copy"
ORG_NODE_ID = "ORG_node1"
TEMPLATE_TITLE = "gh-projects Golden Template"


def _project_fields_payload(id_suffix: str, *, with_iterations: bool):
    """Build a projectV2 fields payload whose ids carry `id_suffix` (so template
    ids and copy ids differ). Only the project-home fields appear (matching the
    real copy). Iterations present only when `with_iterations` is True."""
    single_selects = [
        ("Status", ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"]),
        ("Size", ["S", "M", "L"]),
        ("Tier", ["T1", "T2", "T3"]),
        ("Blocked", ["no", "yes"]),
        ("Schedule health", ["On track", "At risk", "Blocked", "Overdue", "Done"]),
        ("Slippage", ["Not late", "1-2d", "3-5d", "1+wk", "2+wk"]),
        ("Blast radius", ["None", "Blocks 1", "Blocks many", "Blocks release"]),
        ("Impact level", ["Low", "Medium", "High", "Release blocker"]),
        ("Decision needed", ["No", "Move date", "Reduce scope", "Reassign", "Split", "Unblock", "Defer"]),
    ]
    nodes = []
    for fname, opts in single_selects:
        nodes.append({
            "__typename": "ProjectV2SingleSelectField",
            "id": f"F_{fname.replace(' ', '_')}_{id_suffix}",
            "name": fname,
            "dataType": "SINGLE_SELECT",
            "options": [
                {"id": f"OPT_{fname.replace(' ', '_')}_{o.replace(' ', '_').replace('+', 'p')}_{id_suffix}",
                 "name": o, "description": ""}
                for o in opts
            ],
        })
    # Number + text + parent fields.
    for fname, dtype in [("Slippage-days", "NUMBER"), ("Blast-count", "NUMBER"),
                         ("PM-ID", "TEXT"), ("Spec", "TEXT"), ("Parent issue", "PARENT")]:
        nodes.append({"__typename": "ProjectV2FieldCommon",
                      "id": f"F_{fname.replace(' ', '_')}_{id_suffix}",
                      "name": fname, "dataType": dtype})
    # Iteration field.
    iter_cfg = {"iterations": [], "completedIterations": []}
    if with_iterations:
        # Match iterations.json's desired set exactly so the diff SKIPs.
        sched = json.loads((scaffold.templates_dir() / "project" / "iterations.json").read_text())
        iter_cfg["iterations"] = [
            {"id": f"IT_{i}_{id_suffix}", "title": it["title"],
             "startDate": it["startDate"], "duration": it["duration"]}
            for i, it in enumerate(sched["iterations"])
        ]
    nodes.append({"__typename": "ProjectV2IterationField",
                  "id": f"F_Sprint_{id_suffix}", "name": "Sprint",
                  "configuration": iter_cfg})
    return nodes


# The 8 saved views the golden template (and every copy) must carry. ProjectV2
# views are read-only via the API (projectV2.views) but never mutable — the
# fixture serves them so the view-catalog diff (views.json) is observable.
# When `detail` is set the payload also carries each view's resolved filter,
# groupByFields and verticalGroupByFields so verify_views sees a
# fully RESOLVED catalog (every documented group/slice maps to a non-empty live
# field). A faithful golden-template copy resolves all 8 — these match views.json.
def _project_views_payload(id_suffix: str, *, detail: bool = False):
    schema = json.loads((scaffold.templates_dir() / "project" / "views.json").read_text())
    nodes = []
    for i, v in enumerate(schema["views"]):
        node = {"number": i + 1, "name": v["name"],
                "layout": v.get("layout", "TABLE_LAYOUT")}
        if detail:
            node["filter"] = v.get("filter", "")
            group = v.get("group", "")
            slc = v.get("slice", "")
            node["groupByFields"] = {"nodes": ([{"name": group}] if group else [])}
            node["verticalGroupByFields"] = {"nodes": ([{"name": slc}] if slc else [])}
        nodes.append(node)
    return nodes


class ScaffoldRunner:
    """Fake gh runner: canned JSON per operation + a counter of WRITE round-trips.

    Reads are always served; writes (copyProjectV2, REST POST/PATCH, updateProject)
    are served too but RECORDED so a test can assert "no writes in dry-run". The
    COPY exists from the start (copyProjectV2 is what creates it) so resolving it
    yields the copy's ids."""

    def __init__(self, *, copy_has_iterations=True):
        self.calls = []
        self.writes = []  # mutation/REST-write round-trips
        self.copy_has_iterations = copy_has_iterations
        self.issue_fields_present = set()  # org has none initially

    def __call__(self, args):
        self.calls.append(list(args))
        body = " ".join(str(a) for a in args)

        # ----- REST writes (POST/PATCH) -----
        if "-X" in args:
            method = args[args.index("-X") + 1].upper() if args.index("-X") + 1 < len(args) else ""
            path = next((a for a in args if str(a).startswith("/")), "")
            if method in ("POST", "PATCH", "PUT", "DELETE"):
                self.writes.append(("rest", method, path))
                return "{}"
            # REST GET — issue-types / issue-fields listings.
            if "issue-fields" in path:
                return json.dumps([{"name": n} for n in sorted(self.issue_fields_present)])
            if "issue-types" in path:
                return json.dumps([])
            return "{}"

        # ----- GraphQL -----
        # org + named template resolve
        if "projectsV2(first:100" in body and "is:template" in body:
            return json.dumps({"data": {"organization": {
                "id": ORG_NODE_ID, "login": "acme",
                "projectsV2": {"nodes": [
                    {"id": TEMPLATE_PROJECT_ID, "number": TEMPLATE_NUMBER, "title": TEMPLATE_TITLE},
                ]},
            }}})
        # copyProjectV2 — the WRITE that creates the copy
        if "copyProjectV2" in body:
            self.writes.append(("graphql", "copyProjectV2"))
            return json.dumps({"data": {"copyProjectV2": {"projectV2": {
                "id": COPY_PROJECT_ID, "number": COPY_NUMBER, "title": "Acme Board"}}}})
        # updateProjectV2 (App-access grant) — a WRITE
        if "updateProjectV2(" in body and "fields(first:100)" not in body:
            self.writes.append(("graphql", "updateProjectV2"))
            return json.dumps({"data": {"updateProjectV2": {"projectV2": {"id": COPY_PROJECT_ID}}}})
        # view-catalog read — serve all 8 saved views, copy vs template by the
        # project number variable. Views are READ-ONLY here (no mutation). The
        # DETAIL query (verify_views) asks for groupByFields, so serve the
        # resolved filter/group/slice when present; the plain presence query
        # just needs number/name/layout.
        if "views(first:100)" in body:
            suffix = "copy" if f"number={COPY_NUMBER}" in body else "tmpl"
            detail = "groupByFields" in body
            return json.dumps({"data": {"organization": {"projectV2": {
                "views": {"nodes": _project_views_payload(suffix, detail=detail)}}}}})
        # field resolve — serve template OR copy ids by the project number variable
        if "fields(first:100)" in body:
            if f"number={COPY_NUMBER}" in body:
                nodes = _project_fields_payload("copy", with_iterations=self.copy_has_iterations)
                pid, num, title = COPY_PROJECT_ID, COPY_NUMBER, "Acme Board"
            else:
                nodes = _project_fields_payload("tmpl", with_iterations=True)
                pid, num, title = TEMPLATE_PROJECT_ID, TEMPLATE_NUMBER, TEMPLATE_TITLE
            return json.dumps({"data": {"organization": {"projectV2": {
                "id": pid, "number": num, "title": title,
                "fields": {"nodes": nodes}}}}})
        # org issue-fields GraphQL fallback
        if "issueFields" in body:
            return json.dumps({"data": {"organization": {"issueFields": {
                "nodes": [{"name": n} for n in sorted(self.issue_fields_present)]}}}})
        return "{}"


class ScaffoldTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_run = gh.RUN
        self._orig_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
        # Pin the plugin root to THIS plugin so templates_dir() resolves the
        # real bundled templates (never a hardcoded ~/.claude path).
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(Path(LIB).parent)

    def tearDown(self):
        gh.RUN = self._orig_run
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        else:
            os.environ["CLAUDE_PLUGIN_ROOT"] = self._orig_env

    def _plan(self, runner, repo_dir, *, repo="acme/web", title="Acme Board"):
        gh.RUN = runner
        return scaffold.build_plan(
            org="acme", template_title=TEMPLATE_TITLE, repo=repo,
            new_title=title, repo_dir=repo_dir,
        )


# --------------------------------------------------------------------------- #
# copyProjectV2 from the NAMED template; the copy carries every field.
# --------------------------------------------------------------------------- #
class TestCopyFromTemplate(ScaffoldTestBase):
    def test_copies_named_template_and_has_all_fields(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        # The copy was created from the named template id.
        self.assertEqual(plan["template_id"], TEMPLATE_PROJECT_ID)
        self.assertEqual(plan["copy"]["id"], COPY_PROJECT_ID)
        self.assertEqual(plan["copy"]["number"], COPY_NUMBER)
        # Every project-home field from fields.json is present in the COPY.
        schema = scaffold.load_fields_schema()
        expected = scaffold.project_field_names(schema)
        self.assertEqual(sorted(plan["fields"]["present"]), sorted(expected))
        self.assertEqual(plan["fields"]["missing"], [])

    def test_copy_uses_copyprojectv2_mutation(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            self._plan(runner, d)
        self.assertIn(("graphql", "copyProjectV2"), runner.writes)

    def test_copy_carries_all_8_views(self):
        # View-catalog half: the copy's saved-view catalog, read read-only
        # from projectV2.views, must contain all 8 views.json titles with none
        # missing.
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        schema = scaffold.load_views_schema()
        expected = scaffold.expected_view_names(schema)
        self.assertEqual(len(expected), 8, "the catalog must enumerate exactly 8 views")
        self.assertEqual(sorted(plan["views"]["present"]), sorted(expected))
        self.assertEqual(plan["views"]["missing"], [])
        self.assertTrue(plan["views"]["from_copy"],
                        "views must be verified against the COPY, not the template")

    def test_missing_template_view_is_reported(self):
        # If the template/copy is short a view, the diff must surface it as missing
        # (a template defect to fix + re-copy — scaffold never API-creates a view).
        runner = ScaffoldRunner()
        full = scaffold.expected_view_names(scaffold.load_views_schema())
        partial = full[:-1]  # copy is missing the last view
        check = scaffold.verify_copy_views(partial, scaffold.load_views_schema())
        self.assertEqual(check["missing"], [full[-1]])
        self.assertEqual(sorted(check["present"]), sorted(partial))

    def test_no_view_mutation_issued(self):
        # Scaffold reads the view catalog but must NEVER mutate a view (ProjectV2
        # views are not API-mutable; saved views / Insights charts are not
        # API-creatable — see rules/github-fields.md Platform constraints).
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            self._plan(runner, d)
        for call in runner.calls:
            body = " ".join(str(a) for a in call)
            self.assertNotIn("createProjectV2View", body)
            self.assertNotIn("updateProjectV2View", body)
            self.assertNotIn("deleteProjectV2View", body)


# --------------------------------------------------------------------------- #
# Ids re-resolved against the COPY, never the template.
# --------------------------------------------------------------------------- #
class TestReResolveAgainstCopy(ScaffoldTestBase):
    def test_field_ids_come_from_copy_not_template(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        # Resolve the template independently to get its ids.
        gh.RUN = runner
        tmpl = gh.Project("acme", TEMPLATE_NUMBER).resolve()
        for name, copy_id in plan["fields"]["field_ids"].items():
            self.assertTrue(copy_id.endswith("_copy"),
                            f"field '{name}' id must be from the COPY, got {copy_id!r}")
            tmpl_id = tmpl.field_id(name)
            self.assertNotEqual(copy_id, tmpl_id,
                                f"field '{name}': copy id must differ from template id")

    def test_option_ids_come_from_copy(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        # Every resolved option id is from the copy.
        for field_name, opts in plan["option_ids"].items():
            for opt_name, opt_id in opts.items():
                self.assertTrue(opt_id.endswith("_copy"),
                                f"{field_name}/{opt_name} option id must be from the COPY")

    def test_iteration_ids_come_from_copy(self):
        runner = ScaffoldRunner()
        gh.RUN = runner
        with tempfile.TemporaryDirectory() as d:
            self._plan(runner, d)
            copy_proj = gh.Project("acme", COPY_NUMBER)
            copy_proj.id = COPY_PROJECT_ID
            copy_proj.resolve()
            iters = scaffold.copy_iterations(copy_proj, scaffold.load_iterations_schema())
        self.assertTrue(iters, "copy must expose iterations to resolve from")
        for it in iters:
            self.assertTrue(str(it["id"]).endswith("_copy"))


# --------------------------------------------------------------------------- #
# Second run is a no-op for fields; iterations SKIP (zero mutations).
# --------------------------------------------------------------------------- #
class TestIdempotentSecondRun(ScaffoldTestBase):
    def test_iterations_skip_when_copy_matches_desired(self):
        runner = ScaffoldRunner(copy_has_iterations=True)
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        self.assertFalse(plan["iterations"]["mutate"],
                         "iterations already match -> must SKIP (no re-PUT)")
        self.assertEqual(plan["iterations"]["mutations"], 0, "zero iteration mutations")

    def test_second_run_install_manifest_empty(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            # First run with --force actually installs the on-disk template files.
            plan1 = self._plan(runner, d)
            written = scaffold.apply_plan(plan1, repo_dir=d, force=True)["files_written"]
            self.assertTrue(written, "first run must install the present template files")
            # Second run: every present source now matches the dest -> SKIP.
            plan2 = self._plan(runner, d)
            installs = [r for r in plan2["files"]
                        if r["action"] == "install" and (scaffold.templates_dir() / r["src"]).is_file()]
            self.assertEqual(installs, [],
                             "second run: every present file is already installed -> empty install manifest")

    def test_second_run_zero_iteration_mutations(self):
        runner = ScaffoldRunner(copy_has_iterations=True)
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
            actions = scaffold.apply_plan(plan, repo_dir=d, force=True)
        self.assertEqual(actions["iterations"]["mutations"], 0)
        self.assertNotIn("iterations_applied", actions)


# --------------------------------------------------------------------------- #
# Install manifest lists ALL required destination paths + org setup.
# --------------------------------------------------------------------------- #
class TestInstallManifest(ScaffoldTestBase):
    REQUIRED_DESTS = [
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/feature.yml",
        ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/ISSUE_TEMPLATE/chore.yml",
        ".github/ISSUE_TEMPLATE/infra.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/workflows/board-sync.yml",
        ".github/workflows/signals-sync.yml",
        ".github/actions/board-status/action.yml",
        ".github/release.yml",
        ".github/CODEOWNERS",
        "project/README.md",
    ]

    def test_manifest_lists_all_required_destinations(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        dests = {r["dest"] for r in plan["files"]}
        for required in self.REQUIRED_DESTS:
            self.assertIn(required, dests, f"manifest must list destination {required}")

    def test_manifest_enumerates_externally_sourced_files_even_without_source(self):
        # board-sync.yml / signals-sync.yml / board-status are authored
        # elsewhere; the manifest must still ENUMERATE their destinations.
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        dests = {r["dest"] for r in plan["files"]}
        for cross in (".github/workflows/board-sync.yml",
                      ".github/workflows/signals-sync.yml",
                      ".github/actions/board-status/action.yml"):
            self.assertIn(cross, dests)

    def test_org_issue_fields_and_types_planned(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        # Issue Fields: Priority/Start date/Target date ensured (org has none).
        names = {r["name"] for r in plan["issue_fields"]}
        self.assertEqual(names, {"Priority", "Start date", "Target date"})
        self.assertTrue(all(r["action"] == "ensure" for r in plan["issue_fields"]))
        # Issue Types from the taxonomy.
        self.assertEqual(set(plan["issue_types"]),
                         {"Feature", "Bug", "Chore", "Infra", "Epic"})

    def test_no_squash_and_app_access_planned(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
        self.assertEqual(plan["no_squash"], {"repo": "acme/web", "allow_squash_merge": False})
        self.assertTrue(plan["app_access"]["grant"])


# --------------------------------------------------------------------------- #
# Dry-run mutates nothing.
# --------------------------------------------------------------------------- #
class TestDryByDefault(ScaffoldTestBase):
    def test_dry_run_writes_no_files(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
            actions = scaffold.apply_plan(plan, repo_dir=d, force=False)
            self.assertEqual(actions["files_written"], [])
            # No template file landed in the repo dir.
            for r in plan["files"]:
                self.assertFalse((Path(d) / r["dest"]).exists(),
                                 f"dry-run must not write {r['dest']}")

    def test_dry_run_does_no_rest_or_field_writes(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
            # Snapshot writes after planning (copyProjectV2 is the one planning
            # mutation), then ensure apply(force=False) adds NO further writes.
            writes_after_plan = list(runner.writes)
            scaffold.apply_plan(plan, repo_dir=d, force=False)
        self.assertEqual(runner.writes, writes_after_plan,
                         "dry-run apply must add no REST/GraphQL writes")
        # And specifically: no REST POST/PATCH (issue-fields/types/repo settings).
        self.assertFalse([w for w in runner.writes if w[0] == "rest"],
                         "dry-run must not POST/PATCH any org/repo setting")

    def test_apply_force_writes_files_and_settings(self):
        runner = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d)
            actions = scaffold.apply_plan(plan, repo_dir=d, force=True)
            self.assertTrue(actions["files_written"])
            # no-squash PATCH + issue-field POSTs happened.
            self.assertTrue([w for w in runner.writes if w[0] == "rest" and w[1] == "PATCH"])
            self.assertTrue([w for w in runner.writes if w[0] == "rest" and w[1] == "POST"])
            self.assertEqual(actions["no_squash"], {"repo": "acme/web", "allow_squash_merge": False})


# --------------------------------------------------------------------------- #
# CLI exit codes + secret hygiene.
# --------------------------------------------------------------------------- #
class TestCli(ScaffoldTestBase):
    def _run_main(self, argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = scaffold.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_usage_error_exit_2(self):
        code, _, _ = self._run_main(["scaffold"])  # missing required args
        self.assertEqual(code, 2)

    def test_dry_run_exit_0(self):
        runner = ScaffoldRunner()
        gh.RUN = runner
        with tempfile.TemporaryDirectory() as d:
            code, out, err = self._run_main(
                ["scaffold", "--org", "acme", "--template", TEMPLATE_TITLE,
                 "--title", "Acme Board", "--repo", "acme/web", "--repo-dir", d])
            self.assertEqual(code, 0)
            self.assertIn("dry-run", err)
            result = json.loads(out.strip().splitlines()[-1])
            self.assertFalse(result["applied"])
            # A CLI dry-run makes NO copyProjectV2 and NO REST/field writes
            # (leaves the project + repo unchanged) — the project is only copied
            # under --force.
            self.assertEqual(runner.writes, [],
                             "CLI dry-run must make zero mutations (no copyProjectV2)")
            for r in result["files"]:
                self.assertFalse((Path(d) / r).exists())

    def test_template_not_found_exit_3(self):
        gh.RUN = ScaffoldRunner()
        with tempfile.TemporaryDirectory() as d:
            code, _, _ = self._run_main(
                ["scaffold", "--org", "acme", "--template", "Nonexistent Template",
                 "--title", "Acme Board", "--repo-dir", d])
        self.assertEqual(code, 3)

    def test_no_token_shaped_string_in_output(self):
        # Drive a run whose stderr would carry a token; assert it is scrubbed.
        def leaky(args):
            raise gh.GhError("upstream said ghs_leakyinstalltoken1234567890abcdef")
        gh.RUN = leaky
        code, out, err = self._run_main(
            ["scaffold", "--org", "acme", "--template", TEMPLATE_TITLE,
             "--title", "x"])
        self.assertNotIn("ghs_leakyinstalltoken1234567890abcdef", out + err)


if __name__ == "__main__":
    unittest.main()
