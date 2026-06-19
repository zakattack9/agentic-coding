#!/usr/bin/env python3
"""Offline tests for setup_board.py — NO network, NO live org.

setup_board builds the golden template's API request bodies from the template JSON
and applies them through an injectable RUN seam. These tests exercise the pure body
builders against the REAL templates/project/*.json (so schema drift is caught) and
the idempotent apply path with a fake gh runner.
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
MODULE_PATH = os.path.join(PLUGIN_ROOT, "lib", "setup_board.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sb = _load("setup_board", MODULE_PATH)


class TestIssueTypes(unittest.TestCase):
    def setUp(self):
        self.types = sb.issue_type_payloads(sb.load_fields())

    def test_five_issue_types_from_type_options(self):
        names = [t["name"] for t in self.types]
        self.assertEqual(names, ["Feature", "Bug", "Chore", "Infra", "Epic"])

    def test_each_has_required_fields_and_lowercase_color(self):
        for t in self.types:
            self.assertTrue(t["name"] and t["description"])
            self.assertIs(t["is_enabled"], True)
            self.assertEqual(t["color"], "gray")  # issue-types enum is lowercase


class TestIssueFields(unittest.TestCase):
    def setUp(self):
        self.fields = sb.issue_field_payloads(sb.load_fields())

    def test_three_org_issue_fields(self):
        self.assertEqual([f["name"] for f in self.fields], ["Priority", "Start date", "Target date"])

    def test_priority_is_single_select_with_options_and_no_color(self):
        prio = next(f for f in self.fields if f["name"] == "Priority")
        self.assertEqual(prio["data_type"], "single_select")
        self.assertEqual([o["name"] for o in prio["single_select_options"]], ["P0", "P1", "P2", "P3"])
        # issue-field options carry no color (REST issue-fields API doesn't take one)
        self.assertNotIn("color", prio["single_select_options"][0])

    def test_dates_are_date_type(self):
        for name in ("Start date", "Target date"):
            f = next(f for f in self.fields if f["name"] == name)
            self.assertEqual(f["data_type"], "date")


class TestProjectFields(unittest.TestCase):
    def setUp(self):
        self.pf = sb.project_field_payloads(sb.load_fields(), sb.load_iterations())
        self.names = [f["name"] for f in self.pf]

    def test_excludes_builtins(self):
        self.assertNotIn("Status", self.names)        # built-in single-select
        self.assertNotIn("Parent issue", self.names)  # built-in parent

    def test_includes_expected_thirteen(self):
        self.assertEqual(len(self.pf), 13)
        for n in ("Size", "Tier", "Blocked", "Schedule health", "Slippage", "Slippage-days",
                  "Blast radius", "Blast-count", "Impact level", "Decision needed",
                  "PM-ID", "Spec", "Sprint"):
            self.assertIn(n, self.names)

    def test_single_select_options_carry_color(self):
        size = next(f for f in self.pf if f["name"] == "Size")
        self.assertEqual(size["data_type"], "single_select")
        colors = {o["name"]: o["color"] for o in size["single_select_options"]}
        self.assertEqual(colors["S"], "BLUE")  # from the fields.json color scheme
        # projectsV2 option color must be the UPPERCASE enum
        self.assertTrue(all(o["color"].isupper() for o in size["single_select_options"]))
        self.assertTrue(size["single_select_options"][0]["description"])

    def test_health_field_colors_from_scheme(self):
        sh = next(f for f in self.pf if f["name"] == "Schedule health")
        colors = {o["name"]: o["color"] for o in sh["single_select_options"]}
        self.assertEqual(colors["On track"], "GREEN")
        self.assertEqual(colors["Overdue"], "RED")

    def test_sprint_iteration_carries_configuration(self):
        sprint = next(f for f in self.pf if f["name"] == "Sprint")
        self.assertEqual(sprint["data_type"], "iteration")
        # GitHub's REST iteration field takes a start anchor + duration and generates
        # the iterations itself. An explicit `iterations` array 500s (verified live).
        self.assertEqual(sprint["iteration_configuration"], {"start_date": "2026-01-05", "duration": 14})


class TestViews(unittest.TestCase):
    def setUp(self):
        self.views = sb.view_payloads(sb.load_views())

    def test_eight_views_layouts_lowercased(self):
        self.assertEqual(len(self.views), 8)
        layouts = {v["name"]: v["layout"] for v in self.views}
        self.assertEqual(layouts["Sprint"], "board")
        self.assertEqual(layouts["My Tasks"], "table")
        self.assertEqual(layouts["Roadmap"], "roadmap")

    def test_filter_present_only_when_nonempty(self):
        sprint = next(v for v in self.views if v["name"] == "Sprint")
        self.assertEqual(sprint["filter"], "sprint:@current -status:Backlog")
        # an empty filter is omitted from the POST body (every shipped view now carries
        # one, so assert the rule on a synthetic view)
        empty = sb.view_payloads({"views": [{"name": "X", "layout": "TABLE_LAYOUT", "filter": ""}]})[0]
        self.assertNotIn("filter", empty)


class TestVisibleFields(unittest.TestCase):
    def setUp(self):
        self.views = sb.load_views()
        # a realistic name->id map; org `Start date` intentionally absent
        self.ids = {"Assignees": 1, "Size": 2, "Priority": 3, "Blocked": 4, "Status": 5,
                    "Sprint": 6, "Target date": 7, "Type": 8, "Milestone": 9,
                    "Schedule health": 10, "Slippage": 11, "Impact level": 12,
                    "Decision needed": 13, "Blast radius": 14, "Parent issue": 15,
                    "Sub-issues progress": 16}

    def _by_name(self, field_ids=None):
        return {v["name"]: v for v in sb.view_payloads(self.views, field_ids=field_ids)}

    def test_visible_fields_resolved_in_order(self):
        sprint = self._by_name(self.ids)["Sprint"]
        self.assertEqual(sprint["visible_fields"], [1, 2, 3, 4])  # Assignees, Size, Priority, Blocked

    def test_roadmap_gets_no_visible_fields(self):
        self.assertNotIn("visible_fields", self._by_name(self.ids)["Roadmap"])

    def test_absent_field_is_skipped_keeping_order(self):
        ids = dict(self.ids); del ids["Priority"]
        self.assertEqual(self._by_name(ids)["Sprint"]["visible_fields"], [1, 2, 4])

    def test_no_field_ids_means_no_visible_fields(self):
        self.assertTrue(all("visible_fields" not in p for p in sb.view_payloads(self.views)))

    def test_unresolved_view_fields_reports_missing(self):
        ids = dict(self.ids); del ids["Target date"]
        miss = sb.unresolved_view_fields(self.views, ids)
        self.assertIn("Target date", miss.get("My Tasks", []))
        self.assertNotIn("Roadmap", miss)  # roadmap excluded

    def test_resolve_field_ids_parses_rest_list(self):
        rows = [{"id": 360, "name": "Status"}, {"id": 361, "name": "Size"}]
        run = lambda args, stdin=None: json.dumps(rows)
        self.assertEqual(sb.resolve_field_ids("o", 7, run=run), {"Status": 360, "Size": 361})

    def test_stale_view_flagged_when_missing_a_column(self):
        # Sprint wants Assignees/Size/Priority/Blocked; current lacks Priority+Blocked
        current = {"Sprint": ["Title", "Assignees", "Size"]}
        self.assertIn("Sprint", sb.stale_views(self.views, self.ids, current))

    def test_view_not_stale_when_all_columns_present(self):
        current = {"Sprint": ["Title", "Assignees", "Size", "Priority", "Blocked"]}
        self.assertNotIn("Sprint", sb.stale_views(self.views, self.ids, current))

    def test_absent_view_is_not_stale(self):
        # a view not yet on the project will be created fresh — not "stale"
        self.assertEqual(sb.stale_views(self.views, self.ids, {}), [])


class TestPunchList(unittest.TestCase):
    def test_lists_status_options_grouping_charts_template(self):
        text = "\n".join(sb.punch_list(sb.load_fields(), sb.load_views()))
        self.assertIn("Backlog", text)            # the Status 6-stage options
        self.assertIn("On Staging", text)
        self.assertIn("group by Status", text)    # a view grouping to finish
        self.assertIn("Insights charts", text)
        self.assertNotIn("Make template", text)   # now automated via markProjectV2AsTemplate


class _FakeRun:
    """Records POSTs; answers a GET list with `existing`."""
    def __init__(self, existing=None):
        self.existing = existing or []
        self.posts = []

    def __call__(self, args, stdin=None):
        if "--input" in args:           # a POST carrying a body
            self.posts.append(json.loads(stdin))
            return "{}"
        return json.dumps(self.existing)  # a GET list


class TestApplyIdempotent(unittest.TestCase):
    def test_ensure_skips_present_creates_missing(self):
        fr = _FakeRun(existing=[{"name": "Size"}])
        rows = sb.ensure("/orgs/o/projectsV2/7/fields",
                         [{"name": "Size", "data_type": "single_select"},
                          {"name": "Tier", "data_type": "single_select"}], run=fr)
        actions = {r["name"]: r["action"] for r in rows}
        self.assertEqual(actions, {"Size": "skip", "Tier": "create"})
        self.assertEqual([p["name"] for p in fr.posts], ["Tier"])

    def test_ensure_rerun_is_full_noop(self):
        fr = _FakeRun(existing=[{"name": "Size"}, {"name": "Tier"}])
        rows = sb.ensure("/orgs/o/projectsV2/7/fields",
                         [{"name": "Size"}, {"name": "Tier"}], run=fr)
        self.assertTrue(all(r["action"] == "skip" for r in rows))
        self.assertEqual(fr.posts, [])

    def test_ensure_accepts_precomputed_present(self):
        fr = _FakeRun()  # views have no REST list — present is passed in, no GET
        rows = sb.ensure("/orgs/o/projectsV2/7/views",
                         [{"name": "Sprint"}, {"name": "My Tasks"}],
                         run=fr, present={"Sprint"})
        self.assertEqual({r["name"]: r["action"] for r in rows},
                         {"Sprint": "skip", "My Tasks": "create"})
        self.assertEqual([p["name"] for p in fr.posts], ["My Tasks"])

    def test_existing_view_names_reads_graphql(self):
        payload = {"data": {"organization": {"projectV2": {"views": {"nodes": [
            {"name": "Sprint"}, {"name": "My Tasks"},
        ]}}}}}
        run = lambda args, stdin=None: json.dumps(payload)
        self.assertEqual(sb.existing_view_names("o", 7, run=run), {"Sprint", "My Tasks"})

    def test_project_meta_parses(self):
        run = lambda a, stdin=None: json.dumps({"node_id": "PVT_x", "is_template": True})
        self.assertEqual(sb.project_meta("o", 7, run=run), {"id": "PVT_x", "is_template": True})

    def test_find_project_by_title(self):
        nodes = {"data": {"organization": {"projectsV2": {"nodes": [
            {"id": "PVT_1", "number": 7, "title": "Golden Template"},
        ]}}}}
        run = lambda args, stdin=None: json.dumps(nodes)
        self.assertEqual(sb.find_project_by_title("o", "Golden Template", run=run),
                         {"id": "PVT_1", "number": 7})
        self.assertIsNone(sb.find_project_by_title("o", "Nope", run=run))


class _FakeOrgAdd:
    """Answers project-fields GET, org issue-fields GET, and records POSTs."""
    def __init__(self, project_field_names, org_field_ids):
        self.pf = project_field_names
        self.org = org_field_ids
        self.posts = []

    def __call__(self, args, stdin=None):
        if "--input" in args:
            self.posts.append(json.loads(stdin))
            return "{}"
        path = next(a for a in args if a.startswith("/orgs/"))
        if path.endswith("/issue-fields"):
            return json.dumps([{"id": v, "name": k} for k, v in self.org.items()])
        if path.endswith("/fields"):  # project fields list
            return json.dumps([{"id": 100 + i, "name": n} for i, n in enumerate(self.pf)])
        return "[]"


class TestOrgFieldsToProject(unittest.TestCase):
    def setUp(self):
        self.fields = sb.load_fields()

    def test_issue_field_names(self):
        self.assertEqual(sb.issue_field_names(self.fields), ["Priority", "Start date", "Target date"])

    def test_org_issue_field_ids_parses(self):
        run = lambda a, stdin=None: json.dumps([{"id": 5, "name": "Priority"}, {"id": 6, "name": "Start date"}])
        self.assertEqual(sb.org_issue_field_ids("o", run=run), {"Priority": 5, "Start date": 6})

    def test_adds_missing_org_fields_via_issue_field_id(self):
        fr = _FakeOrgAdd(["Status", "Size"], {"Priority": 5, "Start date": 6, "Target date": 7})
        rows, missing = sb.add_org_fields_to_project("o", 7, self.fields, run=fr)
        self.assertEqual({r["name"]: r["action"] for r in rows},
                         {"Priority": "create", "Start date": "create", "Target date": "create"})
        self.assertEqual(missing, [])
        self.assertEqual(sorted(p["issue_field_id"] for p in fr.posts), [5, 6, 7])

    def test_skips_org_fields_already_on_project(self):
        fr = _FakeOrgAdd(["Priority", "Start date", "Target date"],
                         {"Priority": 5, "Start date": 6, "Target date": 7})
        rows, missing = sb.add_org_fields_to_project("o", 7, self.fields, run=fr)
        self.assertTrue(all(r["action"] == "skip" for r in rows))
        self.assertEqual(fr.posts, [])
        self.assertEqual(missing, [])

    def test_reports_org_field_absent_at_org_level(self):
        fr = _FakeOrgAdd(["Status"], {"Priority": 5})  # Start/Target missing org-side
        rows, missing = sb.add_org_fields_to_project("o", 7, self.fields, run=fr)
        self.assertEqual(missing, ["Start date", "Target date"])
        self.assertEqual([p["issue_field_id"] for p in fr.posts], [5])


class TestSelfContained(unittest.TestCase):
    def test_imports_nothing_from_plugin(self):
        with open(MODULE_PATH, encoding="utf-8") as fh:
            src = fh.read()
        for bad in ("import gh", "from gh", "import scaffold", "from scaffold", "import intake"):
            self.assertNotIn(bad, src, f"setup_board must be self-contained; found `{bad}`")


if __name__ == "__main__":
    unittest.main()
