#!/usr/bin/env python3
"""Offline tests for lib/intake.py — NO network, NO live org, NO mutation.

Exercises the DETERMINISTIC intake core that backs skills/intake-issues. The
skill delegates AC authoring to spec-ops; here we test only the decision logic:

  * every planned item carries Type/Size/Tier/PM-ID + grouped AC.
  * prose-only / non-atomic AC are refused `Ready`, with a stated reason.
  * tier -> spec-ops rigor (T1 light · T2 standard · T3 full + refine-spec);
    the delegation names the spec-ops skill — no body authored inline.
  * AC-group count drives size (1->S / 2-3->M / 4+->L); 4+ groups -> Epic
    split (one sub-issue per group) with `needs §X` -> blocked-by edges.
  * dry-by-default: planning + the gh.add_sub_issue / add_blocked_by writes
    are only invoked under --force; a dry run calls `gh issue create` zero
    times (asserted against an injected RUN that counts mutations).
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import intake  # noqa: E402
import gh  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures: spec-ops-shaped AC groups (atomic, observable end-states).
# --------------------------------------------------------------------------- #
def _atomic_groups(n):
    """n independent groups, each with one atomic AC, no cross deps."""
    return [
        {"index": i, "name": f"group {i}", "needs": [],
         "ac": [f"endpoint {i} returns 200 for a valid request"]}
        for i in range(1, n + 1)
    ]


# A 5-group fixture carrying a real `needs §X` DAG:
#   §2,§3,§4,§5 parallelize after §1; §4 also needs §2 (cross edge).
DAG_GROUPS = [
    {"index": 1, "name": "core", "needs": [], "ac": ["the core module is importable"]},
    {"index": 2, "name": "api", "needs": "needs §1", "ac": ["the API responds with JSON"]},
    {"index": 3, "name": "cli", "needs": ["§1"], "ac": ["the CLI prints the result"]},
    {"index": 4, "name": "sync", "needs": "needs §1, §2", "ac": ["the board reflects the status"]},
    {"index": 5, "name": "views", "needs": [1], "ac": ["the view renders without error"]},
]


# --------------------------------------------------------------------------- #
# tier -> rigor + spec-ops delegation path
# --------------------------------------------------------------------------- #
class TierRigorTest(unittest.TestCase):
    def test_t1_light_no_refine(self):
        r = intake.tier_rigor("T1")
        self.assertEqual(r["rigor"], "light")
        self.assertFalse(r["refine"])
        self.assertEqual(r["write_spec"], "spec-ops:write-spec")
        self.assertIsNone(r["refine_spec"])

    def test_t2_standard_no_refine(self):
        r = intake.tier_rigor("standard")  # word form normalizes to T2
        self.assertEqual(r["tier"], "T2")
        self.assertEqual(r["rigor"], "standard")
        self.assertFalse(r["refine"])
        self.assertIsNone(r["refine_spec"])

    def test_t3_full_plus_refine(self):
        r = intake.tier_rigor("3")
        self.assertEqual(r["tier"], "T3")
        self.assertEqual(r["rigor"], "full")
        self.assertTrue(r["refine"])
        # T3 ALSO delegates to refine-spec — the call path the skill must take.
        self.assertEqual(r["refine_spec"], "spec-ops:refine-spec")

    def test_full_mapping_table(self):
        self.assertEqual(
            {t: intake.tier_rigor(t)["rigor"] for t in ("T1", "T2", "T3")},
            {"T1": "light", "T2": "standard", "T3": "full"},
        )

    def test_bad_tier_rejected(self):
        with self.assertRaises(intake.IntakeError):
            intake.tier_rigor("T9")

    def test_plan_delegation_names_spec_ops_at_rigor(self):
        # the plan's delegation block carries the spec-ops skill + the
        # tier's rigor arg, and authors NO body itself (there is no body field).
        plan = intake.plan_item({
            "type": "Feature", "tier": "T3", "pm_id": "PM-0007",
            "title": "deep thing", "groups": DAG_GROUPS,
        })
        self.assertEqual(plan["delegation"]["write_spec"], "spec-ops:write-spec")
        self.assertEqual(plan["delegation"]["rigor"], "full")
        self.assertEqual(plan["delegation"]["refine_spec"], "spec-ops:refine-spec")
        self.assertNotIn("body", plan)  # the helper never authors a body inline


# --------------------------------------------------------------------------- #
# size from group count + Epic-split + blocked-by edges
# --------------------------------------------------------------------------- #
class SizeAndSplitTest(unittest.TestCase):
    def test_size_one_group_is_S(self):
        self.assertEqual(intake.size_from_groups(1), "S")
        self.assertFalse(intake.should_epic_split(1))

    def test_size_three_groups_is_M(self):
        self.assertEqual(intake.size_from_groups(2), "M")
        self.assertEqual(intake.size_from_groups(3), "M")
        self.assertFalse(intake.should_epic_split(3))

    def test_size_five_groups_is_L(self):
        self.assertEqual(intake.size_from_groups(4), "L")
        self.assertEqual(intake.size_from_groups(5), "L")
        self.assertTrue(intake.should_epic_split(4))
        self.assertTrue(intake.should_epic_split(5))

    def test_one_group_no_split(self):
        split = intake.epic_split(_atomic_groups(1))
        self.assertFalse(split["split"])
        self.assertEqual(len(split["sub_issues"]), 1)
        self.assertEqual(split["edges"], [])

    def test_three_groups_no_split(self):
        split = intake.epic_split(_atomic_groups(3))
        self.assertFalse(split["split"])
        self.assertEqual(len(split["sub_issues"]), 3)

    def test_five_groups_split_with_dep_edges(self):
        split = intake.epic_split(DAG_GROUPS)
        self.assertTrue(split["split"])
        # One sub-issue per group.
        self.assertEqual(len(split["sub_issues"]), 5)
        # `needs §X` projected onto blocked-by edges (child, blocker):
        #   §2->§1, §3->§1, §4->§1, §4->§2, §5->§1
        self.assertEqual(
            sorted(split["edges"]),
            sorted([(2, 1), (3, 1), (4, 1), (4, 2), (5, 1)]),
        )
        # §1 is independent -> no blocked_by -> parallelizable root.
        by_index = {s["index"]: s for s in split["sub_issues"]}
        self.assertEqual(by_index[1]["blocked_by"], [])
        self.assertEqual(by_index[4]["blocked_by"], [1, 2])

    def test_self_and_unknown_needs_dropped(self):
        groups = [
            {"index": 1, "name": "a", "needs": [1, 99], "ac": ["a is true"]},  # self + unknown
            {"index": 2, "name": "b", "needs": "§1", "ac": ["b is true"]},
        ]
        split = intake.epic_split(groups)
        self.assertEqual(split["edges"], [(2, 1)])  # self (1->1) + unknown (1->99) dropped

    def test_size_in_full_plan(self):
        # size derives from group count inside the merged plan.
        plan1 = intake.plan_item({"type": "Bug", "tier": "T1", "pm_id": "PM-0001",
                                  "groups": _atomic_groups(1)})
        plan3 = intake.plan_item({"type": "Feature", "tier": "T2", "pm_id": "PM-0002",
                                  "groups": _atomic_groups(3)})
        plan5 = intake.plan_item({"type": "Feature", "tier": "T3", "pm_id": "PM-0003",
                                  "groups": DAG_GROUPS})
        self.assertEqual((plan1["size"], plan3["size"], plan5["size"]), ("S", "M", "L"))
        self.assertFalse(plan1["epic_split"])
        self.assertFalse(plan3["epic_split"])
        self.assertTrue(plan5["epic_split"])


# --------------------------------------------------------------------------- #
# every item carries Type/Size/Tier/PM-ID + grouped AC
# --------------------------------------------------------------------------- #
class IssueFieldsTest(unittest.TestCase):
    def test_required_fields_populated(self):
        plan = intake.plan_item({
            "type": "Feature", "tier": "T2", "pm_id": "PM-0042",
            "title": "do the thing", "groups": _atomic_groups(2),
        })
        f = plan["fields"]
        for key in ("Type", "Size", "Tier", "PM-ID"):
            self.assertIn(key, f)
            self.assertTrue(str(f[key]))
        self.assertEqual(f["Type"], "Feature")
        self.assertEqual(f["Tier"], "T2")
        self.assertEqual(f["Size"], "M")
        self.assertEqual(f["PM-ID"], "PM-0042")

    def test_invalid_type_rejected(self):
        with self.assertRaises(intake.IntakeError):
            intake.build_issue_fields(item_type="Epic", tier="T1",
                                      pm_id="PM-0001", group_count=1)

    def test_bad_pm_id_rejected(self):
        with self.assertRaises(intake.IntakeError):
            intake.build_issue_fields(item_type="Bug", tier="T1",
                                      pm_id="42", group_count=1)


# --------------------------------------------------------------------------- #
# prose-only / non-atomic AC are REFUSED Ready, with a reason
# --------------------------------------------------------------------------- #
class ReadyGateTest(unittest.TestCase):
    def test_prose_ac_stays_out_of_ready(self):
        # Classic prose-only dump: tasks + vague + headings, no observable states.
        prose = [
            "Add a login form",                       # task verb
            "Make the dashboard better",              # task verb
            "Handle errors properly",                 # vague
            "Performance and scalability",            # heading / no state verb
        ]
        res = intake.ready_gate(prose)
        self.assertFalse(res["ready"])
        self.assertIsNotNone(res["reason"])
        # Every prose line is rejected WITH a stated reason.
        self.assertEqual(len(res["rejections"]), 4)
        for r in res["rejections"]:
            self.assertTrue(r["reason"])

    def test_atomic_observable_ac_enter_ready(self):
        good = [
            "the login form rejects an empty password",
            "the dashboard renders within 200ms",
            "an unknown id returns a 404 response",
        ]
        res = intake.ready_gate(good)
        self.assertTrue(res["ready"], res)
        self.assertEqual(res["rejections"], [])

    def test_empty_ac_not_ready(self):
        res = intake.ready_gate([])
        self.assertFalse(res["ready"])
        self.assertIn("no acceptance criteria", res["reason"])

    def test_multipart_ac_refused(self):
        res = intake.ready_gate(
            ["the API returns 200 and the cache is warmed and the log records the hit"])
        self.assertFalse(res["ready"])
        self.assertIn("split", res["rejections"][0]["reason"].lower())

    def test_task_lead_reason_mentions_task(self):
        res = intake.ready_gate(["Implement the retry loop"])
        self.assertFalse(res["ready"])
        self.assertIn("task", res["rejections"][0]["reason"].lower())

    def test_prose_plan_is_not_ready(self):
        # end to end: an item with prose AC plans as ready=False + reason.
        plan = intake.plan_item({
            "type": "Feature", "tier": "T1", "pm_id": "PM-0009", "title": "vague",
            "groups": [{"index": 1, "name": "g", "needs": [],
                        "ac": ["Add a settings page", "Make it nice"]}],
        })
        self.assertFalse(plan["ready"])
        self.assertIsNotNone(plan["ready_reason"])
        self.assertTrue(plan["rejections"])

    def test_atomic_plan_is_ready(self):
        plan = intake.plan_item({
            "type": "Feature", "tier": "T1", "pm_id": "PM-0010", "title": "sharp",
            "groups": [{"index": 1, "name": "g", "needs": [],
                        "ac": ["the settings page persists a toggle across reloads"]}],
        })
        self.assertTrue(plan["ready"], plan)


# --------------------------------------------------------------------------- #
# dry-by-default — a dry run creates no issue and mutates nothing.
#
# We model the skill's create/split path through an injected gh.RUN that counts
# any MUTATING gh call (issue create, addSubIssue, blocked-by). The deterministic
# core never calls RUN, and the apply path is guarded by an explicit `force` flag.
# --------------------------------------------------------------------------- #
class _MutationCounter:
    """Fake gh.RUN that counts mutating calls and refuses to hit a network."""

    def __init__(self):
        self.mutations = []
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        argv = " ".join(str(a) for a in args)
        if ("issue" in args and "create" in args) \
                or "addSubIssue" in argv \
                or "--add-blocked-by" in args \
                or "addIssueDependency" in argv:
            self.mutations.append(list(args))
        # Canned non-empty JSON so callers that parse output don't blow up.
        return "{}"


def _create_issues(items, *, force, run):
    """Stand-in for the skill's create loop: dry-by-default.

    Without `force` it ONLY computes the deterministic plan (no RUN call); with
    `force` it would invoke `gh issue create` per item + the sub-issue/blocked-by
    writes. Proves the preview path issues zero mutations.
    """
    plans = [intake.plan_item(it) for it in items]
    if not force:
        return {"applied": False, "plans": plans}
    for it, plan in zip(items, plans):
        run(["issue", "create", "--title", it.get("title", "")])  # the gated mutation
        for child, blocker in plan["blocked_by_edges"]:
            run(["issue", "edit", str(child), "--add-blocked-by", str(blocker)])
    return {"applied": True, "plans": plans}


class DryByDefaultTest(unittest.TestCase):
    def setUp(self):
        self._real_run = gh.RUN
        self.counter = _MutationCounter()
        gh.RUN = self.counter

    def tearDown(self):
        gh.RUN = self._real_run

    def test_dry_run_creates_no_issue(self):
        items = [
            {"type": "Feature", "tier": "T3", "pm_id": "PM-0100",
             "title": "epic", "groups": DAG_GROUPS},
        ]
        res = _create_issues(items, force=False, run=gh.RUN)
        self.assertFalse(res["applied"])
        # NOT ONE mutating gh call in the dry path.
        self.assertEqual(self.counter.mutations, [])
        self.assertEqual(self.counter.calls, [])
        # ...but the plan was still fully computed (preview is real).
        self.assertEqual(res["plans"][0]["size"], "L")
        self.assertTrue(res["plans"][0]["epic_split"])

    def test_force_run_creates_issue_and_edges(self):
        items = [
            {"type": "Feature", "tier": "T3", "pm_id": "PM-0101",
             "title": "epic", "groups": DAG_GROUPS},
        ]
        res = _create_issues(items, force=True, run=gh.RUN)
        self.assertTrue(res["applied"])
        # Exactly one create, plus one blocked-by edit per DAG edge.
        creates = [c for c in self.counter.mutations if "create" in c]
        edits = [c for c in self.counter.mutations if "--add-blocked-by" in c]
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(edits), 5)


# --------------------------------------------------------------------------- #
# CLI exit codes (mirrors lib/gh.py contract): 0 ok · 2 usage/refused.
# --------------------------------------------------------------------------- #
class CliTest(unittest.TestCase):
    def test_size_cli(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = intake.main(["size", "5"])
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["size"], "L")
        self.assertTrue(out["epic_split"])

    def test_rigor_cli(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = intake.main(["rigor", "T3"])
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["rigor"], "full")
        self.assertEqual(out["refine_spec"], "spec-ops:refine-spec")

    def test_usage_error_exit_2(self):
        self.assertEqual(intake.main([]), 2)


if __name__ == "__main__":
    unittest.main()
