#!/usr/bin/env python3
"""Seed a throwaway gh-projects test board with realistic mock data.

DEV-ONLY tool (gitignored, not part of the shipped plugin). It stands up a
disposable copy of the golden-template Project (#7) and fills it with a coherent
backlog of mock issues in `Zilarent/cars.bdv` so you can eyeball how every view /
field / chart looks with live-ish data — then `teardown_test_board.py` deletes it
all from a manifest.

WHAT IT DOES (all via the `gh` CLI, like the plugin itself):
  1. copyProjectV2  -> a fresh private test board off template #7
  2. updateProjectV2Field -> Sprint iterations anchored around TODAY
     (so @current / @previous / @next actually resolve in the views)
  3. gh issue create -> ~23 mock issues, then for each:
        updateIssueIssueType        (Type: Feature/Bug/Chore/Infra/Epic)
        addProjectV2ItemById        (put it on the board)
        updateProjectV2ItemFieldValue  (project fields: Status/Size/Tier/Sprint/
                                        Blocked/signals/PM-ID/Spec)
        updateIssueFieldValue       (org issue fields: Priority/Start/Target)
  4. addSubIssue   -> Epic -> child grouping (feeds the Sub-issues % rollup)
  5. addBlockedBy  -> a small blocked-by DAG (feeds Blocked / Blast radius /
                      Critical-Path views)

Everything created is recorded in `manifest.json` next to this file so teardown is
exact and safe. Re-running refuses if a manifest already records a board — tear it
down first. Idempotent only at that coarse grain; it is a disposable fixture.

Run as YOURSELF (gh auth with `project` + `admin:org`):
    python3 seed_test_board.py            # create + populate
    python3 seed_test_board.py --dry-run  # print the plan, mutate nothing
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Fixed environment (this org / repo / template). Edit here to retarget.
# --------------------------------------------------------------------------- #
ORG = "Zilarent"
ORG_ID = "O_kgDOCDFU6g"
REPO = "Zilarent/cars.bdv"
TEMPLATE_PROJECT_ID = "PVT_kwDOCDFU6s4BbEA1"   # #7 GitHub Projects Golden Template
BOARD_TITLE = "[TEST] cars.bdv Mock Board"
API_VERSION = "2026-03-10"
MANIFEST = Path(__file__).resolve().parent / "manifest.json"

# Sprint cadence anchored so Sprint 2 is the CURRENT iteration (today ~2026-06-18).
SPRINTS = [
    {"title": "Sprint 1", "startDate": "2026-05-25", "duration": 14},
    {"title": "Sprint 2", "startDate": "2026-06-08", "duration": 14},
    {"title": "Sprint 3", "startDate": "2026-06-22", "duration": 14},
    {"title": "Sprint 4", "startDate": "2026-07-06", "duration": 14},
    {"title": "Sprint 5", "startDate": "2026-07-20", "duration": 14},
    {"title": "Sprint 6", "startDate": "2026-08-03", "duration": 14},
]

# Org issue fields are written through updateIssueFieldValue, NOT the project item
# (the API rejects the project path for issue-field-backed columns).
ISSUE_FIELDS = {"Priority", "Start date", "Target date"}

# Assign active work to a real login so the assignee-filtered views ("My work" =
# assignee:@me, plus Sprint-board cards) populate. Backlog items are left
# unassigned on purpose (realistic, and exercises the unassigned-hygiene views).
ASSIGNEE = "zakattack9"
ASSIGN_WHEN_STATUS = {"Ready", "In Progress", "In Review", "On Staging", "Done"}

# --------------------------------------------------------------------------- #
# The mock backlog. `key` is internal (parent / blocked_by references only).
# Fields left unset are simply skipped. Dates are coherent with the sprint above.
# --------------------------------------------------------------------------- #
ISSUES = [
    # ---- Epics ----
    {"key": "EPIC-BOOK", "type": "Epic", "title": "Booking & reservation flow",
     "body": "Parent epic for the end-to-end rental booking experience.",
     "Status": "In Progress", "Size": "L", "Tier": "T3", "Priority": "P1",
     "Sprint": "Sprint 2", "Start date": "2026-06-08", "Target date": "2026-07-05",
     "Schedule health": "At risk", "Impact level": "High", "Decision needed": "No",
     "Blast radius": "Blocks release", "Blast-count": 4, "Spec": "https://specs.example/booking",
     "Blocked": "no"},
    {"key": "EPIC-FLEET", "type": "Epic", "title": "Fleet & inventory management",
     "body": "Parent epic for vehicle inventory, pricing and media.",
     "Status": "Backlog", "Size": "L", "Tier": "T3", "Priority": "P2",
     "Sprint": "Sprint 3", "Start date": "2026-06-22", "Target date": "2026-08-02",
     "Schedule health": "On track", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "Blocks many", "Blast-count": 3, "Spec": "https://specs.example/fleet",
     "Blocked": "no"},

    # ---- Booking children ----
    {"key": "BOOK-SEARCH", "parent": "EPIC-BOOK", "type": "Feature",
     "title": "Vehicle search & availability calendar",
     "body": "Search vehicles by date range with a live availability calendar.",
     "Status": "In Progress", "Size": "M", "Tier": "T2", "Priority": "P1",
     "Sprint": "Sprint 2", "Start date": "2026-06-08", "Target date": "2026-06-21",
     "Schedule health": "On track", "Impact level": "High", "Decision needed": "No",
     "Blast radius": "Blocks many", "Blast-count": 2, "Blocked": "no"},
    {"key": "BOOK-CHECKOUT", "parent": "EPIC-BOOK", "type": "Feature",
     "title": "Checkout & payment (Stripe)", "blocked_by": ["BOOK-SEARCH"],
     "body": "Stripe-backed checkout: hold, capture, and booking creation.",
     "Status": "In Review", "Size": "M", "Tier": "T3", "Priority": "P0",
     "Sprint": "Sprint 2", "Start date": "2026-06-10", "Target date": "2026-06-24",
     "Schedule health": "Blocked", "Impact level": "Release blocker",
     "Decision needed": "Unblock", "Blast radius": "Blocks many", "Blast-count": 3,
     "Spec": "https://specs.example/checkout", "Blocked": "yes"},
    {"key": "BOOK-CONFIRM", "parent": "EPIC-BOOK", "type": "Feature",
     "title": "Reservation confirmation email", "blocked_by": ["BOOK-CHECKOUT"],
     "body": "Transactional confirmation email with booking details + ICS.",
     "Status": "Ready", "Size": "S", "Tier": "T1", "Priority": "P2",
     "Sprint": "Sprint 3", "Start date": "2026-06-22", "Target date": "2026-07-01",
     "Schedule health": "Blocked", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "yes"},
    {"key": "BOOK-CANCEL", "parent": "EPIC-BOOK", "type": "Feature",
     "title": "Cancellation & refund flow", "blocked_by": ["BOOK-CHECKOUT"],
     "body": "Self-serve cancellation with policy-based refund calculation.",
     "Status": "Backlog", "Size": "M", "Tier": "T2", "Priority": "P2",
     "Sprint": "Sprint 3", "Start date": "2026-06-24", "Target date": "2026-07-05",
     "Schedule health": "Blocked", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "yes"},

    # ---- Fleet children ----
    {"key": "FLEET-CRUD", "parent": "EPIC-FLEET", "type": "Feature",
     "title": "Vehicle CRUD admin",
     "body": "Admin UI to create, edit and retire vehicles in the fleet.",
     "Status": "Backlog", "Size": "M", "Tier": "T2", "Priority": "P2",
     "Sprint": "Sprint 3", "Start date": "2026-06-22", "Target date": "2026-07-04",
     "Schedule health": "On track", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "Blocks many", "Blast-count": 2, "Blocked": "no"},
    {"key": "FLEET-PRICING", "parent": "EPIC-FLEET", "type": "Feature",
     "title": "Dynamic seasonal pricing rules", "blocked_by": ["FLEET-CRUD"],
     "body": "Rule engine for seasonal / demand-based daily rate adjustments.",
     "Status": "Backlog", "Size": "L", "Tier": "T3", "Priority": "P1",
     "Sprint": "Sprint 4", "Start date": "2026-07-06", "Target date": "2026-07-19",
     "Schedule health": "Blocked", "Impact level": "High", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Spec": "https://specs.example/pricing",
     "Blocked": "yes"},
    {"key": "FLEET-IMG", "parent": "EPIC-FLEET", "type": "Feature",
     "title": "Vehicle photo upload to S3", "blocked_by": ["FLEET-CRUD"],
     "body": "Multi-image upload with S3 storage and CDN delivery.",
     "Status": "Backlog", "Size": "S", "Tier": "T1", "Priority": "P3",
     "Sprint": "Sprint 4", "Start date": "2026-07-06", "Target date": "2026-07-15",
     "Schedule health": "Blocked", "Impact level": "Low", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "yes"},

    # ---- Standalone features ----
    {"key": "FEAT-AUTH", "type": "Feature", "title": "Guest account & login (OAuth)",
     "body": "Email + Google/Apple OAuth sign-in for returning guests.",
     "Status": "Done", "Size": "M", "Tier": "T2", "Priority": "P1",
     "Sprint": "Sprint 1", "Start date": "2026-05-25", "Target date": "2026-06-05",
     "Schedule health": "Done", "Impact level": "High", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},
    {"key": "FEAT-MAP", "type": "Feature", "title": "Pickup location map (Mapbox)",
     "body": "Interactive map of pickup/drop-off locations with hours.",
     "Status": "In Progress", "Size": "S", "Tier": "T2", "Priority": "P2",
     "Sprint": "Sprint 2", "Start date": "2026-06-09", "Target date": "2026-06-20",
     "Schedule health": "On track", "Impact level": "Low", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},
    {"key": "FEAT-REVIEWS", "type": "Feature", "title": "Customer reviews & ratings",
     "body": "Post-rental review prompts with star ratings on vehicle pages.",
     "Status": "Backlog", "Size": "S", "Tier": "T1", "Priority": "P3",
     "Sprint": "Sprint 5", "Start date": "2026-07-20", "Target date": "2026-07-29",
     "Schedule health": "On track", "Impact level": "Low", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},
    {"key": "FEAT-I18N", "type": "Feature", "title": "Multi-currency + i18n",
     "body": "Localized copy and multi-currency display/checkout.",
     "Status": "Backlog", "Size": "M", "Tier": "T2", "Priority": "P2",
     "Sprint": "Sprint 4", "Start date": "2026-07-06", "Target date": "2026-07-18",
     "Schedule health": "On track", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},

    # ---- Bugs ----
    {"key": "BUG-CALENDAR", "type": "Bug", "title": "Availability calendar off-by-one on DST",
     "body": "Calendar shows the wrong day across a DST boundary.", "blocked_by": ["BOOK-SEARCH"],
     "Status": "In Progress", "Size": "S", "Tier": "T1", "Priority": "P0",
     "Sprint": "Sprint 2", "Start date": "2026-06-12", "Target date": "2026-06-17",
     "Schedule health": "Overdue", "Slippage": "1-2d", "Slippage-days": 1,
     "Impact level": "High", "Decision needed": "Move date",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "yes"},
    {"key": "BUG-PAYMENT", "type": "Bug", "title": "Double-charge on payment retry",
     "body": "Retrying a failed payment occasionally charges the card twice.",
     "Status": "In Review", "Size": "S", "Tier": "T2", "Priority": "P0",
     "Sprint": "Sprint 2", "Start date": "2026-06-11", "Target date": "2026-06-14",
     "Schedule health": "Overdue", "Slippage": "3-5d", "Slippage-days": 4,
     "Impact level": "Release blocker", "Decision needed": "Reduce scope",
     "Blast radius": "Blocks 1", "Blast-count": 1, "Blocked": "no"},
    {"key": "BUG-MOBILE", "type": "Bug", "title": "Layout breaks on iOS Safari",
     "body": "Booking form overflows the viewport on iOS Safari.",
     "Status": "Ready", "Size": "S", "Tier": "T1", "Priority": "P2",
     "Sprint": "Sprint 2", "Start date": "2026-06-13", "Target date": "2026-06-21",
     "Schedule health": "On track", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},
    {"key": "BUG-EMAIL", "type": "Bug", "title": "Confirmation email lands in spam",
     "body": "SPF/DKIM misconfiguration sends confirmations to spam.",
     "Status": "Backlog", "Size": "S", "Tier": "T1", "Priority": "P3",
     "Schedule health": "On track", "Impact level": "Low", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},

    # ---- Chores ----
    {"key": "CHORE-DEPS", "type": "Chore", "title": "Upgrade to React 19",
     "body": "Bump React + types and fix breaking changes.",
     "Status": "Backlog", "Size": "S", "Tier": "T1", "Priority": "P3",
     "Sprint": "Sprint 3", "Start date": "2026-06-23", "Target date": "2026-07-02",
     "Schedule health": "On track", "Impact level": "Low", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},
    {"key": "CHORE-TESTS", "type": "Chore", "title": "Add E2E coverage for checkout",
     "body": "Playwright E2E covering the full booking + payment path.", "blocked_by": ["BOOK-CHECKOUT"],
     "Status": "Backlog", "Size": "M", "Tier": "T2", "Priority": "P2",
     "Sprint": "Sprint 3", "Start date": "2026-06-25", "Target date": "2026-07-05",
     "Schedule health": "Blocked", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "yes"},
    {"key": "CHORE-A11Y", "type": "Chore", "title": "Accessibility audit fixes",
     "body": "Resolve WCAG AA findings from the accessibility audit.",
     "Status": "Backlog", "Size": "S", "Tier": "T1", "Priority": "P2",
     "Sprint": "Sprint 5", "Start date": "2026-07-21", "Target date": "2026-07-30",
     "Schedule health": "On track", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},

    # ---- Infra ----
    {"key": "INFRA-CI", "type": "Infra", "title": "Set up CI/CD pipeline (GH Actions)",
     "body": "Build/test/deploy pipeline with staging + prod environments.",
     "Status": "Done", "Size": "M", "Tier": "T2", "Priority": "P1",
     "Sprint": "Sprint 1", "Start date": "2026-05-25", "Target date": "2026-06-04",
     "Schedule health": "Done", "Impact level": "High", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Spec": "https://specs.example/cicd",
     "Blocked": "no"},
    {"key": "INFRA-CDN", "type": "Infra", "title": "CloudFront CDN + caching",
     "body": "Front the app with CloudFront and tune cache behaviors.",
     "Status": "On Staging", "Size": "M", "Tier": "T3", "Priority": "P1",
     "Sprint": "Sprint 2", "Start date": "2026-06-08", "Target date": "2026-06-19",
     "Schedule health": "At risk", "Impact level": "High", "Decision needed": "No",
     "Blast radius": "Blocks 1", "Blast-count": 1, "Spec": "https://specs.example/cdn",
     "Blocked": "no"},
    {"key": "INFRA-DB", "type": "Infra", "title": "Postgres connection pooling (PgBouncer)",
     "body": "Introduce PgBouncer to cap DB connections under load.",
     "Status": "In Progress", "Size": "S", "Tier": "T2", "Priority": "P1",
     "Sprint": "Sprint 2", "Start date": "2026-06-10", "Target date": "2026-06-21",
     "Schedule health": "On track", "Impact level": "Medium", "Decision needed": "No",
     "Blast radius": "None", "Blast-count": 0, "Blocked": "no"},
]


# --------------------------------------------------------------------------- #
# gh plumbing
# --------------------------------------------------------------------------- #
def run(args, stdin=None):
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout


def gql(query, **variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        # `-F` lets gh coerce numbers (Int!); strings go through `-f`.
        flag = "-F" if isinstance(v, int) and not isinstance(v, bool) else "-f"
        args += [flag, f"{k}={v}"]
    out = run(args)
    data = json.loads(out) if out.strip() else {}
    if data.get("errors"):
        raise RuntimeError(f"graphql errors: {json.dumps(data['errors'])}")
    return data.get("data", {})


def esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def resolve_project_fields(number: int) -> dict:
    """{field_name: {kind, id, options:{name:optid}, iterations:{title:itid}}} for
    PROJECT-home fields (single_select / number / text / iteration)."""
    data = gql(
        "query($o:String!,$n:Int!){organization(login:$o){projectV2(number:$n){"
        "fields(first:100){nodes{__typename "
        "... on ProjectV2FieldCommon{id name dataType} "
        "... on ProjectV2SingleSelectField{id name options{id name}} "
        "... on ProjectV2IterationField{id name configuration{"
        "iterations{id title} completedIterations{id title}}}}}}}}",
        o=ORG, n=int(number))
    out = {}
    for f in data["organization"]["projectV2"]["fields"]["nodes"]:
        name = f.get("name")
        if not name:
            continue
        node = {"kind": (f.get("dataType") or "").upper(), "id": f.get("id")}
        if f.get("options"):
            node["options"] = {o["name"]: o["id"] for o in f["options"]}
        cfg = f.get("configuration")
        if cfg:
            its = (cfg.get("iterations") or []) + (cfg.get("completedIterations") or [])
            node["iterations"] = {i["title"]: i["id"] for i in its}
        out[name] = node
    return out


def resolve_issue_fields() -> dict:
    """{field_name: {node_id, data_type, options:{name:optnode}}} for the org
    issue fields (Priority / Start date / Target date)."""
    # `id` lives on the concrete types, not the IssueFieldCommon interface.
    data = gql(
        "query($o:String!){organization(login:$o){issueFields(first:30){nodes{"
        "__typename "
        "... on IssueFieldSingleSelect{id name options{id name}} "
        "... on IssueFieldDate{id name} "
        "... on IssueFieldText{id name} "
        "... on IssueFieldNumber{id name}}}}}", o=ORG)
    out = {}
    for f in data["organization"]["issueFields"]["nodes"]:
        name = f.get("name")
        if name in ISSUE_FIELDS:
            node = {"node_id": f["id"], "data_type": f.get("__typename")}
            if f.get("options"):
                node["options"] = {o["name"]: o["id"] for o in f["options"]}
            out[name] = node
    return out


def resolve_issue_types() -> dict:
    """{type_name: node_id} for the org issue types."""
    data = gql("query($o:String!){organization(login:$o){issueTypes(first:30){nodes{id name}}}}", o=ORG)
    return {t["name"]: t["id"] for t in data["organization"]["issueTypes"]["nodes"]}


# --------------------------------------------------------------------------- #
# Board create + sprints
# --------------------------------------------------------------------------- #
def create_board() -> dict:
    data = gql(
        "mutation($o:ID!,$s:ID!,$t:String!){copyProjectV2(input:{ownerId:$o,projectId:$s,"
        "title:$t,includeDraftIssues:false}){projectV2{id number url title}}}",
        o=ORG_ID, s=TEMPLATE_PROJECT_ID, t=BOARD_TITLE)
    return data["copyProjectV2"]["projectV2"]


def set_sprints(project_number: int):
    fields = resolve_project_fields(project_number)
    fid = fields["Sprint"]["id"]
    its = ",".join(
        '{title:"%s",startDate:"%s",duration:%d}' % (s["title"], s["startDate"], s["duration"])
        for s in SPRINTS)
    first = SPRINTS[0]
    q = ('mutation($f:ID!){updateProjectV2Field(input:{fieldId:$f,iterationConfiguration:'
         '{startDate:"%s",duration:%d,iterations:[%s]}}){projectV2Field{__typename}}}'
         % (first["startDate"], first["duration"], its))
    gql(q, f=fid)


# --------------------------------------------------------------------------- #
# Per-issue writes
# --------------------------------------------------------------------------- #
def create_issue(spec: dict) -> dict:
    out = run(["issue", "create", "--repo", REPO,
               "--title", spec["title"], "--body", spec.get("body", "")])
    url = out.strip().splitlines()[-1]
    number = int(url.rstrip("/").split("/")[-1])
    node = gql("query($o:String!,$n:String!,$i:Int!){repository(owner:$o,name:$n){"
               "issue(number:$i){id}}}",
               o=REPO.split("/")[0], n=REPO.split("/")[1], i=int(number))
    return {"number": number, "url": url, "node_id": node["repository"]["issue"]["id"]}


def set_issue_type(issue_node: str, type_node: str):
    gql("mutation($i:ID!,$t:ID!){updateIssueIssueType(input:{issueId:$i,issueTypeId:$t}){issue{id}}}",
        i=issue_node, t=type_node)


def add_to_board(project_id: str, content_id: str) -> str:
    data = gql("mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}",
               p=project_id, c=content_id)
    return data["addProjectV2ItemById"]["item"]["id"]


def set_project_field(project_id: str, item_id: str, fnode: dict, value):
    kind, fid = fnode["kind"], fnode["id"]
    if "options" in fnode:
        opt = fnode["options"][value]
        lit = '{singleSelectOptionId:"%s"}' % opt
    elif "iterations" in fnode:
        it = fnode["iterations"][value]
        lit = '{iterationId:"%s"}' % it
    elif "NUMBER" in kind:
        lit = "{number:%s}" % value
    elif "TEXT" in kind:
        lit = '{text:"%s"}' % esc(value)
    else:
        lit = '{text:"%s"}' % esc(value)
    gql("mutation($p:ID!,$i:ID!,$f:ID!){updateProjectV2ItemFieldValue(input:{"
        "projectId:$p,itemId:$i,fieldId:$f,value:%s}){projectV2Item{id}}}" % lit,
        p=project_id, i=item_id, f=fid)


def set_issue_field(issue_node: str, fnode: dict, value):
    fid = fnode["node_id"]
    if "options" in fnode:
        opt = fnode["options"][value]
        sub = '{fieldId:"%s",singleSelectOptionId:"%s"}' % (fid, opt)
    else:  # date
        sub = '{fieldId:"%s",dateValue:"%s"}' % (fid, value)
    gql("mutation($i:ID!){updateIssueFieldValue(input:{issueId:$i,issueField:%s}){issue{id}}}" % sub,
        i=issue_node)


def set_assignee(number: int, login: str):
    run(["issue", "edit", str(number), "--repo", REPO, "--add-assignee", login])


def add_sub_issue(parent_node: str, child_node: str):
    gql("mutation($p:ID!,$c:ID!){addSubIssue(input:{issueId:$p,subIssueId:$c}){issue{id}}}",
        p=parent_node, c=child_node)


def add_blocked_by(issue_node: str, blocker_node: str):
    gql("mutation($i:ID!,$b:ID!){addBlockedBy(input:{issueId:$i,blockingIssueId:$b}){issue{id}}}",
        i=issue_node, b=blocker_node)


# Field-name -> handled-by classifier for the per-issue loop.
_PROJECT_FIELDS = ["Status", "Size", "Tier", "Sprint", "Blocked", "Schedule health",
                   "Slippage", "Slippage-days", "Blast radius", "Blast-count",
                   "Impact level", "Decision needed", "PM-ID", "Spec"]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def seed(dry_run: bool):
    if MANIFEST.exists():
        m = json.loads(MANIFEST.read_text())
        if m.get("project", {}).get("number"):
            sys.exit(f"manifest already records board #{m['project']['number']} — run "
                     "teardown_test_board.py first (a board is a disposable fixture).")

    print(f"Template     : {ORG} #7 ({TEMPLATE_PROJECT_ID})")
    print(f"Repo         : {REPO}")
    print(f"Mock issues  : {len(ISSUES)}  "
          f"({sum(1 for i in ISSUES if i.get('parent'))} sub-issues, "
          f"{sum(len(i.get('blocked_by', [])) for i in ISSUES)} blocked-by edges)")
    if dry_run:
        from collections import Counter
        print("\n--dry-run: nothing mutated. Distribution:")
        for dim in ("type", "Status", "Priority", "Tier", "Sprint"):
            c = Counter(i.get(dim, "—") for i in ISSUES)
            print(f"  {dim:9}: " + ", ".join(f"{k}={v}" for k, v in sorted(c.items())))
        return

    board = create_board()
    print(f"\n[board] created #{board['number']}  {board['url']}")
    set_sprints(board["number"])
    print(f"[board] set {len(SPRINTS)} Sprint iterations (Sprint 2 = current)")

    pfields = resolve_project_fields(board["number"])
    ifields = resolve_issue_fields()
    itypes = resolve_issue_types()

    manifest = {"project": board, "org": ORG, "repo": REPO, "issues": []}
    by_key = {}

    for spec in ISSUES:
        issue = create_issue(spec)
        by_key[spec["key"]] = issue
        manifest["issues"].append({"key": spec["key"], **issue, "title": spec["title"]})
        # persist incrementally so a mid-run failure is still fully cleanable
        MANIFEST.write_text(json.dumps(manifest, indent=2))

        set_issue_type(issue["node_id"], itypes[spec["type"]])
        item_id = add_to_board(board["id"], issue["node_id"])

        for fname in _PROJECT_FIELDS:
            if fname in spec:
                set_project_field(board["id"], item_id, pfields[fname], spec[fname])
        for fname in ISSUE_FIELDS:
            if fname in spec:
                set_issue_field(issue["node_id"], ifields[fname], spec[fname])
        if spec.get("Status") in ASSIGN_WHEN_STATUS:
            set_assignee(issue["number"], ASSIGNEE)
        print(f"  #{issue['number']:>4}  {spec['type']:7} {spec['Status']:11} {spec['title']}")

    # Relationships (after every issue exists)
    for spec in ISSUES:
        if spec.get("parent"):
            add_sub_issue(by_key[spec["parent"]]["node_id"], by_key[spec["key"]]["node_id"])
        for b in spec.get("blocked_by", []):
            add_blocked_by(by_key[spec["key"]]["node_id"], by_key[b]["node_id"])

    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"\nDone. Board: {board['url']}")
    print(f"Manifest: {MANIFEST}")
    print("Tear down with:  python3 teardown_test_board.py")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, mutate nothing")
    args = ap.parse_args(argv)
    seed(args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)
