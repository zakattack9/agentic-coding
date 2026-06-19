#!/usr/bin/env python3
"""Offline tests for verify_views — NO network, NO live org, NO live
mutation. A fake gh runner returns the 8 copied views with their resolved
filter/group/slice (and lets each test corrupt that catalog) so we can assert:

  * verify_views PASSES when all 8 views are present AND each view's documented
    filter qualifiers, group field and slice field resolve against the COPY;
  * it FAILS LOUDLY when a view is missing;
  * it FAILS LOUDLY when a filter qualifier is unresolved (unknown keyword OR a
    keyword that maps to a field absent from the copy);
  * it FAILS LOUDLY when a documented group/slice is not reflected by the live
    view (the platform resolved no field — an empty groupBy/verticalGroupBy);
  * scaffold NEVER issues a view create/edit/delete mutation (views are not
    API-mutable; saved views / Insights charts are not API-creatable — see
    rules/github-fields.md Platform constraints) — it only READS the catalog.

The verify step ships in lib/scaffold.py (verify_views + raise_for_views) and
is wired into build_plan (`view_verify`) + apply_plan (fails loudly under
--force). Views are template-copied, never API-created — so a missing view or an
unresolved filter/group/slice is a TEMPLATE/COPY defect: fix on the golden
template and re-copy.
"""
from __future__ import annotations

import copy as _copy
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

ORG = "acme"
COPY_NUMBER = 42
COPY_PROJECT_ID = "PVT_copy"
ORG_NODE_ID = "ORG_node1"
TEMPLATE_PROJECT_ID = "PVT_template"
TEMPLATE_NUMBER = 1
TEMPLATE_TITLE = "gh-projects Golden Template"


# --------------------------------------------------------------------------- #
# The COPY's project fields (so group/slice field resolution sees real fields).
# Mirrors fields.json's project-home single-selects + number/text fields. The
# group/slice fields the views reference that are project-home (Status, Schedule
# health, Impact level) MUST appear here so _field_resolves finds them; Priority
# (issue_field), Type (issue_type) and Milestone (native) resolve via the schema
# / native sets, not this list.
# --------------------------------------------------------------------------- #
def _copy_field_nodes():
    schema = scaffold.load_fields_schema()
    nodes = []
    for f in schema.get("fields", []):
        if f.get("home") != "project":
            continue
        name = f["name"]
        dtype = (f.get("type") or "text").upper()
        node = {"id": f"F_{name.replace(' ', '_')}_copy", "name": name, "dataType": dtype}
        if f.get("type") == "single_select":
            node["__typename"] = "ProjectV2SingleSelectField"
            node["options"] = [{"id": f"OPT_{o['name']}_copy", "name": o["name"], "description": ""}
                               for o in f.get("options", [])]
        elif f.get("type") == "iteration":
            node["__typename"] = "ProjectV2IterationField"
            node["configuration"] = {"iterations": [], "completedIterations": []}
        else:
            node["__typename"] = "ProjectV2FieldCommon"
        nodes.append(node)
    return nodes


def _views_detail_nodes(views_schema: dict):
    """Build the live (resolved) views-detail nodes from a views.json-shaped
    schema: each declared group/slice becomes a NON-EMPTY live field (the
    platform resolved it), exactly what a faithful golden-template copy yields."""
    out = []
    for i, v in enumerate(views_schema["views"]):
        group = v.get("group", "")
        slc = v.get("slice", "")
        out.append({
            "number": i + 1,
            "name": v["name"],
            "layout": v.get("layout", "TABLE_LAYOUT"),
            "filter": v.get("filter", ""),
            "groupByFields": {"nodes": ([{"name": group}] if group else [])},
            "verticalGroupByFields": {"nodes": ([{"name": slc}] if slc else [])},
        })
    return out


class ViewsRunner:
    """Fake gh runner: serves the copy's field-resolve and a (mutable) views-detail
    catalog. Records every call so we can assert NO view mutation is ever issued.

    `views_override` lets a test substitute a corrupted live catalog (missing a
    view, or a group/slice the platform couldn't resolve)."""

    def __init__(self, *, views_override=None):
        self.calls = []
        self.views_override = views_override

    def __call__(self, args):
        self.calls.append(list(args))
        body = " ".join(str(a) for a in args)

        # org + named template resolve
        if "projectsV2(first:100" in body and "is:template" in body:
            return json.dumps({"data": {"organization": {
                "id": ORG_NODE_ID, "login": ORG,
                "projectsV2": {"nodes": [
                    {"id": TEMPLATE_PROJECT_ID, "number": TEMPLATE_NUMBER, "title": TEMPLATE_TITLE},
                ]}}}})

        # views-detail read — the verify_views query asks for groupByFields.
        if "views(first:100)" in body and "groupByFields" in body:
            if self.views_override is not None:
                nodes = self.views_override
            else:
                nodes = _views_detail_nodes(scaffold.load_views_schema())
            return json.dumps({"data": {"organization": {"projectV2": {
                "views": {"nodes": nodes}}}}})

        # views presence-only read
        if "views(first:100)" in body:
            schema = scaffold.load_views_schema()
            nodes = [{"number": i + 1, "name": v["name"], "layout": v.get("layout", "TABLE_LAYOUT")}
                     for i, v in enumerate(schema["views"])]
            return json.dumps({"data": {"organization": {"projectV2": {
                "views": {"nodes": nodes}}}}})

        # field resolve for the COPY
        if "fields(first:100)" in body:
            return json.dumps({"data": {"organization": {"projectV2": {
                "id": COPY_PROJECT_ID, "number": COPY_NUMBER, "title": "Acme Board",
                "fields": {"nodes": _copy_field_nodes()}}}}})

        return "{}"


class ViewsTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_run = gh.RUN
        self._orig_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(Path(LIB).parent)

    def tearDown(self):
        gh.RUN = self._orig_run
        if self._orig_env is None:
            os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        else:
            os.environ["CLAUDE_PLUGIN_ROOT"] = self._orig_env

    def _copy_proj(self, runner):
        gh.RUN = runner
        proj = gh.Project(ORG, COPY_NUMBER)
        proj.id = COPY_PROJECT_ID
        proj.resolve()
        return proj

    def _verify(self, runner):
        proj = self._copy_proj(runner)
        return scaffold.verify_views(
            ORG, COPY_NUMBER,
            views_schema=scaffold.load_views_schema(),
            fields_schema=scaffold.load_fields_schema(),
            copy_proj=proj,
        )


# --------------------------------------------------------------------------- #
# views.json catalog sanity — exactly 8 views, each with the keys verify needs.
# --------------------------------------------------------------------------- #
class TestViewsCatalog(ViewsTestBase):
    EXPECTED = [
        "Sprint", "My Tasks", "Ready Queue", "Triage",
        "Schedule Risk", "Epics", "Grooming",
        "Roadmap",
    ]

    def test_catalog_has_exactly_8_named_views(self):
        schema = scaffold.load_views_schema()
        self.assertEqual(scaffold.expected_view_names(schema), self.EXPECTED)
        self.assertEqual(len(schema["views"]), 8)

    def test_every_view_declares_filter_group_slice(self):
        for v in scaffold.view_specs(scaffold.load_views_schema()):
            self.assertIn("filter", v)
            self.assertIn("group", v)
            self.assertIn("slice", v)


# --------------------------------------------------------------------------- #
# verify_views PASSES when all 8 present + each resolves filter/group/slice.
# --------------------------------------------------------------------------- #
class TestVerifyViewsPasses(ViewsTestBase):
    def test_all_present_and_resolved_passes(self):
        runner = ViewsRunner()
        res = self._verify(runner)
        self.assertTrue(res["ok"], f"verify_views must pass; errors={res['errors']}")
        self.assertEqual(res["checked"], 8)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["errors"], [])

    def test_every_view_reports_present_and_each_axis_ok(self):
        runner = ViewsRunner()
        res = self._verify(runner)
        for name, vr in res["views"].items():
            self.assertTrue(vr["present"], f"{name} must be present")
            self.assertTrue(vr["filter_ok"], f"{name} filter must resolve")
            self.assertTrue(vr["group_ok"], f"{name} group must resolve")
            self.assertTrue(vr["slice_ok"], f"{name} slice must resolve")
            self.assertEqual(vr["errors"], [])

    def test_documented_group_and_slice_are_resolved_for_sliced_views(self):
        # Triage groups by Schedule health, slices by Decision needed;
        # Grooming groups by Status, slices by Type. Both must resolve.
        runner = ViewsRunner()
        res = self._verify(runner)
        cpb = res["views"]["Triage"]
        self.assertEqual(cpb["group"], "Schedule health")
        self.assertEqual(cpb["slice"], "Decision needed")
        self.assertTrue(cpb["group_ok"] and cpb["slice_ok"])
        intake = res["views"]["Grooming"]
        self.assertEqual(intake["slice"], "Type")
        self.assertTrue(intake["slice_ok"])

    def test_filter_qualifiers_resolve_against_real_fields(self):
        # status:Ready -> Status field on the copy; schedule-health: -> Schedule
        # health field; target-date: -> Target date issue field. All resolve.
        runner = ViewsRunner()
        res = self._verify(runner)
        self.assertTrue(res["views"]["Ready Queue"]["filter_ok"])
        self.assertTrue(res["views"]["Schedule Risk"]["filter_ok"])
        self.assertTrue(res["views"]["Roadmap"]["filter_ok"])

    def test_raise_for_views_is_noop_when_ok(self):
        runner = ViewsRunner()
        res = self._verify(runner)
        scaffold.raise_for_views(res)  # must NOT raise

    def test_reads_views_but_never_mutates_one(self):
        runner = ViewsRunner()
        self._verify(runner)
        self.assertTrue(runner.calls, "verify_views must read the catalog")
        for call in runner.calls:
            body = " ".join(str(a) for a in call)
            self.assertNotIn("createProjectV2View", body)
            self.assertNotIn("updateProjectV2View", body)
            self.assertNotIn("deleteProjectV2View", body)


# --------------------------------------------------------------------------- #
# verify_views FAILS LOUDLY when a view is missing / a filter, group or
# slice is unresolved.
# --------------------------------------------------------------------------- #
class TestVerifyViewsFailsLoudly(ViewsTestBase):
    def _detail_minus(self, drop_name):
        nodes = _views_detail_nodes(scaffold.load_views_schema())
        return [n for n in nodes if n["name"] != drop_name]

    def test_missing_view_fails_and_is_listed(self):
        override = self._detail_minus("Sprint")
        runner = ViewsRunner(views_override=override)
        res = self._verify(runner)
        self.assertFalse(res["ok"], "a missing view must FAIL verification")
        self.assertIn("Sprint", res["missing"])
        self.assertFalse(res["views"]["Sprint"]["present"])
        self.assertTrue(any("MISSING" in e for e in res["errors"]))

    def test_missing_view_raises_loudly_exit_3(self):
        override = self._detail_minus("Roadmap")
        runner = ViewsRunner(views_override=override)
        res = self._verify(runner)
        with self.assertRaises(scaffold.ScaffoldError) as ctx:
            scaffold.raise_for_views(res)
        self.assertEqual(ctx.exception.code, 3)
        self.assertIn("Roadmap", str(ctx.exception))
        self.assertIn("re-copy", str(ctx.exception))

    def test_unresolved_group_fails_when_live_view_groups_by_nothing(self):
        # A view documents a group but the live copy resolved no group field
        # (empty groupByFields) — an unresolved group, must FAIL loudly.
        nodes = _views_detail_nodes(scaffold.load_views_schema())
        for n in nodes:
            if n["name"] == "Sprint":
                n["groupByFields"] = {"nodes": []}  # platform resolved no column field
        runner = ViewsRunner(views_override=nodes)
        res = self._verify(runner)
        self.assertFalse(res["ok"])
        self.assertFalse(res["views"]["Sprint"]["group_ok"])
        self.assertTrue(any("group" in e and "Sprint" in e for e in res["errors"]))
        with self.assertRaises(scaffold.ScaffoldError):
            scaffold.raise_for_views(res)

    def test_unresolved_slice_fails_when_live_view_slices_by_nothing(self):
        nodes = _views_detail_nodes(scaffold.load_views_schema())
        for n in nodes:
            if n["name"] == "Triage":
                n["verticalGroupByFields"] = {"nodes": []}  # slice didn't resolve
        runner = ViewsRunner(views_override=nodes)
        res = self._verify(runner)
        self.assertFalse(res["ok"])
        self.assertFalse(res["views"]["Triage"]["slice_ok"])
        self.assertTrue(any("slice" in e and "Triage" in e for e in res["errors"]))

    def test_unknown_filter_qualifier_fails(self):
        # Corrupt one view's filter to carry an unknown qualifier keyword — the
        # mapping returns None -> unresolved -> FAIL.
        nodes = _views_detail_nodes(scaffold.load_views_schema())
        for n in nodes:
            if n["name"] == "Ready Queue":
                n["filter"] = "bogusqual:Whatever is:open"
        runner = ViewsRunner(views_override=nodes)
        res = self._verify(runner)
        self.assertFalse(res["ok"])
        self.assertFalse(res["views"]["Ready Queue"]["filter_ok"])
        self.assertIn("bogusqual", res["views"]["Ready Queue"]["unresolved_qualifiers"])

    def test_filter_qualifier_mapping_to_absent_field_fails(self):
        # A qualifier that maps to a field NOT present on the copy is unresolved.
        # Drop Status from the copy's field set, then a status:* filter can't
        # resolve. We patch the fields_schema used in verify so Status is gone.
        runner = ViewsRunner()
        proj = self._copy_proj(runner)
        fields_schema = _copy.deepcopy(scaffold.load_fields_schema())
        fields_schema["fields"] = [f for f in fields_schema["fields"] if f["name"] != "Status"]
        # Also remove Status from the live project so copy_proj.field('Status') fails.
        proj._fields_by_name.pop("Status", None)
        res = scaffold.verify_views(
            ORG, COPY_NUMBER, views_schema=scaffold.load_views_schema(),
            fields_schema=fields_schema, copy_proj=proj)
        self.assertFalse(res["ok"])
        # Ready Queue (status:Ready) and Sprint's group (Status) both break.
        self.assertFalse(res["views"]["Ready Queue"]["filter_ok"])
        self.assertIn("status", res["views"]["Ready Queue"]["unresolved_qualifiers"])
        self.assertFalse(res["views"]["Sprint"]["group_ok"])


# --------------------------------------------------------------------------- #
# Wired into build_plan + apply_plan: the plan carries `view_verify`,
# and --force FAILS LOUDLY before installing anything if a view is unresolved.
# --------------------------------------------------------------------------- #
class TestVerifyViewsInPlan(ViewsTestBase):
    def _plan_runner(self, *, views_override=None):
        """A runner rich enough for build_plan (adds copyProjectV2 + REST stubs)."""
        base = ViewsRunner(views_override=views_override)

        def run(args):
            body = " ".join(str(a) for a in args)
            if "copyProjectV2" in body:
                return json.dumps({"data": {"copyProjectV2": {"projectV2": {
                    "id": COPY_PROJECT_ID, "number": COPY_NUMBER, "title": "Acme Board"}}}})
            if "updateProjectV2(" in body and "fields(first:100)" not in body:
                return json.dumps({"data": {"updateProjectV2": {"projectV2": {"id": COPY_PROJECT_ID}}}})
            if "-X" in args:
                return "{}"
            if "issueFields" in body:
                return json.dumps({"data": {"organization": {"issueFields": {"nodes": []}}}})
            # field resolve must answer for the COPY number used by build_plan.
            if "fields(first:100)" in body:
                return json.dumps({"data": {"organization": {"projectV2": {
                    "id": COPY_PROJECT_ID, "number": COPY_NUMBER, "title": "Acme Board",
                    "fields": {"nodes": _copy_field_nodes()}}}}})
            return base(args)

        base._wrapped = run
        return base, run

    def test_plan_carries_view_verify_ok(self):
        base, run = self._plan_runner()
        gh.RUN = run
        with tempfile.TemporaryDirectory() as d:
            plan = scaffold.build_plan(org=ORG, template_title=TEMPLATE_TITLE,
                                       repo="acme/web", new_title="Acme Board",
                                       repo_dir=d, do_copy=True)
        self.assertIn("view_verify", plan)
        self.assertTrue(plan["view_verify"]["ok"])
        self.assertEqual(plan["view_verify"]["checked"], 8)

    def test_force_apply_raises_loudly_when_a_view_is_missing(self):
        override = [n for n in _views_detail_nodes(scaffold.load_views_schema())
                    if n["name"] != "My Tasks"]
        base, run = self._plan_runner(views_override=override)
        gh.RUN = run
        with tempfile.TemporaryDirectory() as d:
            plan = scaffold.build_plan(org=ORG, template_title=TEMPLATE_TITLE,
                                       repo="acme/web", new_title="Acme Board",
                                       repo_dir=d, do_copy=True)
            self.assertFalse(plan["view_verify"]["ok"])
            with self.assertRaises(scaffold.ScaffoldError) as ctx:
                scaffold.apply_plan(plan, repo_dir=d, force=True)
            self.assertEqual(ctx.exception.code, 3)
            # Fail loudly BEFORE installing any per-repo file.
            self.assertFalse((Path(d) / "project" / "README.md").exists(),
                             "must not install files when views are unresolved")

    def test_dry_run_does_not_raise_even_with_view_defect(self):
        # A dry run reports the defect but mutates nothing and does not raise
        # (the loud raise gates the --force apply, not the read-only preview).
        override = [n for n in _views_detail_nodes(scaffold.load_views_schema())
                    if n["name"] != "My Tasks"]
        base, run = self._plan_runner(views_override=override)
        gh.RUN = run
        with tempfile.TemporaryDirectory() as d:
            plan = scaffold.build_plan(org=ORG, template_title=TEMPLATE_TITLE,
                                       repo="acme/web", new_title="Acme Board",
                                       repo_dir=d, do_copy=True)
            actions = scaffold.apply_plan(plan, repo_dir=d, force=False)  # must NOT raise
        self.assertFalse(plan["view_verify"]["ok"])
        self.assertEqual(actions["files_written"], [])

    def test_render_manifest_surfaces_view_resolution(self):
        base, run = self._plan_runner()
        gh.RUN = run
        with tempfile.TemporaryDirectory() as d:
            plan = scaffold.build_plan(org=ORG, template_title=TEMPLATE_TITLE,
                                       repo="acme/web", new_title="Acme Board",
                                       repo_dir=d, do_copy=True)
        text = scaffold.render_manifest(plan)
        self.assertIn("View filter/group/slice resolution: ALL RESOLVE", text)
        self.assertIn("views checked", text)


if __name__ == "__main__":
    unittest.main()
