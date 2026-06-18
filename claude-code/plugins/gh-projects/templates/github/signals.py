#!/usr/bin/env python3
"""VENDORED signals computer for `signals-sync.yml` (Phase 1 — deterministic, no AI).

This file is INSTALLED INTO A CONSUMING REPO by `scaffold-repo` (it lands at
`.github/signals.py`) and is run there by `signals-sync.yml`. That repo has NO
gh-projects plugin install, so this script is **fully self-contained**: it
vendors its own GraphQL paging + blocked-by DAG math and imports NOTHING from
the plugin's `lib/`. The DAG math here is a faithful re-implementation of
`lib/dag.py`; the plugin's `lib/tests/test_signals.py` cross-checks the two so
they can never drift.

Hard rules baked into this file (mirrors the workflow boundaries):
  * Deterministic & FREE — there is NO metered-LLM call anywhere in this file
    (no provider SDK, no inference endpoint). Every signal is pure arithmetic +
    graph traversal (AC-23 / AC-26). A test greps this file to prove it.
  * Every Projects v2 write uses the GitHub App INSTALLATION token passed in
    `GH_APP_TOKEN` — NEVER `GITHUB_TOKEN` (AC-27 / constraint #2). This script
    never reads `GITHUB_TOKEN`.
  * Status-update rollup is the documented one (AC-24): any Overdue or
    Blocked-blocking-release => OFF_TRACK; any At risk => AT_RISK; release
    milestone closed => COMPLETE; else ON_TRACK.
  * No blind re-PUT of any option list / iterationConfiguration (this script
    only reads schema + writes per-item field VALUES, never edits the schema).
  * Prints no token/secret, ever (AC-3). Exit codes: 0 ok · 2 usage · 3 not
    found · 1 unexpected.

Run modes:
  * `--plan`   : compute signals + the rollup and print the plan as JSON; write
                 NOTHING (dry-by-default; the workflow's cron/event run passes
                 `--apply`).
  * `--apply`  : additionally write each item's signal fields + post the project
                 `createProjectV2StatusUpdate`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

# --------------------------------------------------------------------------- #
# Schedule-health / Slippage enums (must match the §Data-model option names).
# --------------------------------------------------------------------------- #
HEALTH_ON_TRACK = "On track"
HEALTH_AT_RISK = "At risk"
HEALTH_BLOCKED = "Blocked"
HEALTH_OVERDUE = "Overdue"
HEALTH_DONE = "Done"

SLIP_NOT_LATE = "Not late"
SLIP_1_2 = "1–2d"
SLIP_3_5 = "3–5d"
SLIP_1WK = "1+wk"
SLIP_2WK = "2+wk"

BLAST_NONE = "None"
BLAST_ONE = "Blocks 1"
BLAST_MANY = "Blocks many"
BLAST_RELEASE = "Blocks release"

BLOCKED_YES = "yes"
BLOCKED_NO = "no"

# Rollup status enum values (the GraphQL ProjectV2StatusUpdateStatus enum).
ROLLUP_ON_TRACK = "ON_TRACK"
ROLLUP_AT_RISK = "AT_RISK"
ROLLUP_OFF_TRACK = "OFF_TRACK"
ROLLUP_COMPLETE = "COMPLETE"

# "At risk" window: an open, unblocked item whose Target is within this many
# days (and not yet past) is flagged At risk. Deterministic, configurable via
# env so the workflow can tune it without touching code.
AT_RISK_WINDOW_DAYS = int(os.environ.get("SIGNALS_AT_RISK_WINDOW_DAYS", "3"))


class SignalsError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Injectable command runner (the ONE seam tests override). Default shells to gh.
# --------------------------------------------------------------------------- #
def _default_run(args) -> str:
    proc = subprocess.run(["gh", *[str(a) for a in args]], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SignalsError(f"gh call failed: {_scrub(proc.stderr.strip())}", code=1)
    return proc.stdout


RUN = _default_run


_TOKENISH = ("ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_")


def _scrub(text) -> str:
    """Crude redaction so no token-shaped string is ever printed."""
    s = str(text)
    out = []
    for word in s.split(" "):
        if any(t in word for t in _TOKENISH) or "PRIVATE KEY" in word:
            out.append("[REDACTED]")
        else:
            out.append(word)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# GraphQL primitive (vendored — does not import the plugin).
# --------------------------------------------------------------------------- #
def graphql(query: str, variables: dict | None = None) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, val in (variables or {}).items():
        if isinstance(val, bool):
            args += ["-F", f"{key}={'true' if val else 'false'}"]
        elif isinstance(val, (int, float)):
            args += ["-F", f"{key}={val}"]
        else:
            args += ["-f", f"{key}={val}"]
    raw = RUN(args)
    payload = json.loads(raw) if raw.strip() else {}
    if isinstance(payload, dict) and payload.get("errors"):
        raise SignalsError(f"graphql errors: {_scrub(json.dumps(payload['errors']))}", code=1)
    return payload.get("data", payload) if isinstance(payload, dict) else {}


# --------------------------------------------------------------------------- #
# DAG math — a faithful re-implementation of lib/dag.py (cross-checked in tests).
#
# Edge convention (identical to lib/dag.py): items[A]["blocked_by"] == [B, C]
# means "A is blocked by B and C"; so the downstream of B (what B blocks) is
# everything reachable along reversed edges. A closed blocker no longer blocks.
# --------------------------------------------------------------------------- #
def _build_blocks(items: dict) -> dict:
    blocks: dict[str, set] = {k: set() for k in items}
    for item_id, meta in items.items():
        for blocker in (meta.get("blocked_by") or []):
            b = str(blocker)
            if b not in items:
                continue
            if items[b].get("state", "open") == "closed":
                continue
            blocks[b].add(str(item_id))
    return blocks


def _downstream(start: str, blocks: dict) -> set:
    seen: set = set()
    stack = list(blocks.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(blocks.get(node, ()))
    seen.discard(start)
    return seen


def _is_blocked(item_id: str, items: dict) -> bool:
    for blocker in (items.get(str(item_id), {}).get("blocked_by") or []):
        b = str(blocker)
        if b in items and items[b].get("state", "open") != "closed":
            return True
    return False


def dag_signals(items: dict) -> dict:
    """Per-item {blocked, blast_radius, blast_count} — matches lib/dag.compute."""
    blocks = _build_blocks(items)
    out: dict[str, dict] = {}
    for item_id in items:
        item_id = str(item_id)
        down = _downstream(item_id, blocks)
        count = len(down)
        blocks_release = any(items.get(d, {}).get("release_blocker") for d in down)
        if blocks_release:
            radius = BLAST_RELEASE
        elif count == 0:
            radius = BLAST_NONE
        elif count == 1:
            radius = BLAST_ONE
        else:
            radius = BLAST_MANY
        out[item_id] = {
            "blocked": _is_blocked(item_id, items),
            "blast_radius": radius,
            "blast_count": count,
        }
    return out


# --------------------------------------------------------------------------- #
# Schedule signals — pure date arithmetic (no AI).
# --------------------------------------------------------------------------- #
def _parse_date(value) -> date | None:
    if not value:
        return None
    s = str(value)
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def slippage_days(target, *, today: date) -> int:
    """Whole days past Target (0 if no target or not yet past)."""
    t = _parse_date(target)
    if t is None:
        return 0
    delta = (today - t).days
    return delta if delta > 0 else 0


def slippage_bucket(days: int) -> str:
    if days <= 0:
        return SLIP_NOT_LATE
    if days <= 2:
        return SLIP_1_2
    if days <= 5:
        return SLIP_3_5
    if days <= 13:
        return SLIP_1WK
    return SLIP_2WK


def schedule_health(item: dict, *, blocked: bool, today: date) -> str:
    """Derive Schedule health deterministically (precedence-ordered).

    Done (closed) > Overdue (open & past Target) > Blocked (DAG) > At risk
    (open, Target within the window) > On track. A closed item is Done even if
    it was once late.
    """
    if item.get("state", "open") == "closed":
        return HEALTH_DONE
    days_late = slippage_days(item.get("target"), today=today)
    if days_late > 0:
        return HEALTH_OVERDUE
    if blocked:
        return HEALTH_BLOCKED
    t = _parse_date(item.get("target"))
    if t is not None and 0 <= (t - today).days <= AT_RISK_WINDOW_DAYS:
        return HEALTH_AT_RISK
    return HEALTH_ON_TRACK


def compute_signals(items: dict, *, today: date | None = None) -> dict:
    """Full per-item signal set: the DAG signals + schedule signals.

    `items` is {id: {state, target, release_blocker, blocked_by[...]}}.
    Returns {id: {blocked, blast_radius, blast_count, schedule_health,
    slippage, slippage_days}}.
    """
    today = today or _utc_today()
    dag = dag_signals(items)
    out: dict[str, dict] = {}
    for item_id, meta in items.items():
        item_id = str(item_id)
        d = dag[item_id]
        days = slippage_days(meta.get("target"), today=today)
        health = schedule_health(meta, blocked=d["blocked"], today=today)
        out[item_id] = {
            "blocked": BLOCKED_YES if d["blocked"] else BLOCKED_NO,
            "blast_radius": d["blast_radius"],
            "blast_count": d["blast_count"],
            "schedule_health": health,
            "slippage": slippage_bucket(days),
            "slippage_days": days,
        }
    return out


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------- #
# Status-update rollup (AC-24) — the documented rules, exactly.
# --------------------------------------------------------------------------- #
def rollup_health(signals: dict, items: dict, *, release_milestone_closed: bool) -> str:
    """Roll per-item signals up to ONE project health enum (AC-24).

    Documented precedence:
      1. any Overdue OR any Blocked item that blocks the release => OFF_TRACK
      2. any At risk                                             => AT_RISK
      3. release milestone closed                                => COMPLETE
      4. else                                                    => ON_TRACK

    "Blocked-blocking-release": an item that is itself Blocked AND whose Blast
    radius is `Blocks release` (its downstream reaches a release blocker).
    """
    any_overdue = any(s["schedule_health"] == HEALTH_OVERDUE for s in signals.values())
    any_blocked_blocks_release = any(
        s["blocked"] == BLOCKED_YES and s["blast_radius"] == BLAST_RELEASE
        for s in signals.values()
    )
    if any_overdue or any_blocked_blocks_release:
        return ROLLUP_OFF_TRACK
    if any(s["schedule_health"] == HEALTH_AT_RISK for s in signals.values()):
        return ROLLUP_AT_RISK
    if release_milestone_closed:
        return ROLLUP_COMPLETE
    return ROLLUP_ON_TRACK


def rollup_body(health: str, signals: dict) -> str:
    """A deterministic one-line status-update body (no AI; AC-24)."""
    overdue = sum(1 for s in signals.values() if s["schedule_health"] == HEALTH_OVERDUE)
    at_risk = sum(1 for s in signals.values() if s["schedule_health"] == HEALTH_AT_RISK)
    blocked = sum(1 for s in signals.values() if s["blocked"] == BLOCKED_YES)
    return (
        f"{health}: {len(signals)} items · {overdue} overdue · "
        f"{at_risk} at risk · {blocked} blocked (auto, deterministic)."
    )


# --------------------------------------------------------------------------- #
# Board read — page the project's items into the `items` graph (vendored).
# --------------------------------------------------------------------------- #
_ITEMS_QUERY = """
query($owner:String!, $number:Int!, $after:String){
  organization(login:$owner){
    projectV2(number:$number){
      id
      items(first:100, after:$after){
        pageInfo { hasNextPage endCursor }
        nodes{
          id
          content{
            __typename
            ... on Issue {
              number
              state
              milestone { state }
              labels(first:20){ nodes { name } }
              blockedBy: issueDependenciesSummary { blockedBy }
            }
          }
          targetVal: fieldValueByName(name:"Target date"){
            ... on ProjectV2ItemFieldDateValue { date }
          }
          impact: fieldValueByName(name:"Impact level"){
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""


def load_board(owner: str, number: int) -> tuple[str, dict, dict]:
    """Page the project items into (project_id, items-graph, item->projectItemId).

    The items-graph is the {id: {state, target, release_blocker, blocked_by}}
    structure `compute_signals` consumes; the keys are issue NUMBERS (the same
    space `blocked_by` references). `item_ids` maps issue number -> project item
    node id so the writer can address each item.
    """
    project_id = None
    items: dict[str, dict] = {}
    item_ids: dict[str, str] = {}
    after = None
    while True:
        data = graphql(_ITEMS_QUERY, {"owner": owner, "number": int(number), "after": after})
        proj = (((data or {}).get("organization") or {}).get("projectV2")) or {}
        if not proj.get("id"):
            raise SignalsError(f"project {owner}#{number} not found", code=3)
        project_id = proj["id"]
        conn = proj.get("items") or {}
        for node in (conn.get("nodes") or []):
            content = node.get("content") or {}
            if content.get("__typename") != "Issue":
                continue  # draft issues / PRs carry no dependency graph
            num = str(content.get("number"))
            blocked_by = ((content.get("blockedBy") or {}).get("blockedBy")) or []
            impact = ((node.get("impact") or {}).get("name")) or ""
            milestone = (content.get("milestone") or {})
            release_blocker = (
                impact == "Release blocker"
                or _has_label(content, "release-blocker")
            )
            items[num] = {
                "state": content.get("state", "OPEN").lower(),
                "target": ((node.get("targetVal") or {}).get("date")),
                "release_blocker": release_blocker,
                "blocked_by": [str(b) for b in blocked_by],
                "milestone_state": (milestone.get("state") or "").lower(),
            }
            item_ids[num] = node["id"]
        page = conn.get("pageInfo") or {}
        if page.get("hasNextPage"):
            after = page.get("endCursor")
            continue
        break
    return project_id, items, item_ids


def _has_label(content: dict, name: str) -> bool:
    for lbl in ((content.get("labels") or {}).get("nodes") or []):
        if str(lbl.get("name", "")).lower() == name.lower():
            return True
    return False


def release_milestone_closed(items: dict) -> bool:
    """True if EVERY release-blocking item's milestone is closed and >=1 exists.

    Deterministic: with no release-blocking items, returns False (nothing to
    complete). With release-blocking items, COMPLETE only when all their
    milestones are closed.
    """
    rel = [m for m in items.values() if m.get("release_blocker")]
    if not rel:
        return False
    return all(m.get("milestone_state") == "closed" for m in rel)


# --------------------------------------------------------------------------- #
# Schema resolve + per-item writes (App token, two-phase value write).
# --------------------------------------------------------------------------- #
_SCHEMA_QUERY = """
query($owner:String!, $number:Int!){
  organization(login:$owner){
    projectV2(number:$number){
      id
      fields(first:100){
        nodes{
          __typename
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""


def resolve_fields(owner: str, number: int) -> dict:
    """Return {field_name: {id, options:{opt_name:opt_id}, dataType}} (cached once)."""
    data = graphql(_SCHEMA_QUERY, {"owner": owner, "number": int(number)})
    proj = (((data or {}).get("organization") or {}).get("projectV2")) or {}
    if not proj.get("id"):
        raise SignalsError(f"project {owner}#{number} not found", code=3)
    fields: dict[str, dict] = {}
    for node in ((proj.get("fields") or {}).get("nodes") or []):
        name = node.get("name")
        if not name:
            continue
        opts = {o["name"]: o["id"] for o in (node.get("options") or [])}
        fields[name] = {"id": node["id"], "options": opts,
                        "dataType": (node.get("dataType") or "").upper()}
    return fields


def _write_value(project_id: str, item_id: str, field: dict, value) -> None:
    """updateProjectV2ItemFieldValue with a typed literal (single-select/number)."""
    if field["options"]:
        opt_id = field["options"].get(value)
        if not opt_id:
            raise SignalsError(f"option '{value}' missing on field", code=3)
        lit = '{singleSelectOptionId:"%s"}' % opt_id
    elif "NUMBER" in field["dataType"]:
        lit = "{number:%s}" % float(value)
    else:
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lit = '{text:"%s"}' % text
    query = (
        "mutation($project:ID!,$item:ID!,$field:ID!){"
        "updateProjectV2ItemFieldValue(input:{"
        "projectId:$project,itemId:$item,fieldId:$field,value:%s}){"
        "projectV2Item{id}}}" % lit
    )
    graphql(query, {"project": project_id, "item": item_id, "field": field["id"]})


_FIELD_MAP = [
    ("Blocked", "blocked"),
    ("Blast radius", "blast_radius"),
    ("Blast-count", "blast_count"),
    ("Schedule health", "schedule_health"),
    ("Slippage", "slippage"),
    ("Slippage-days", "slippage_days"),
]


def write_signals(project_id: str, fields: dict, item_ids: dict, signals: dict) -> int:
    """Write each item's six signal fields. Returns the number of writes."""
    writes = 0
    for num, sig in signals.items():
        item_id = item_ids.get(num)
        if not item_id:
            continue
        for field_name, key in _FIELD_MAP:
            field = fields.get(field_name)
            if not field:
                continue  # field absent on this project — skip, don't crash
            _write_value(project_id, item_id, field, sig[key])
            writes += 1
    return writes


_STATUS_UPDATE = """
mutation($project:ID!, $body:String!, $status:ProjectV2StatusUpdateStatus, $start:Date, $target:Date){
  createProjectV2StatusUpdate(input:{
    projectId:$project, body:$body, status:$status, startDate:$start, targetDate:$target
  }){ statusUpdate { id } }
}
"""


def post_status_update(project_id: str, health: str, body: str,
                       *, start=None, target=None) -> dict:
    return graphql(_STATUS_UPDATE, {
        "project": project_id, "body": body, "status": health,
        "start": start, "target": target,
    })


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(owner: str, number: int, *, apply: bool, start=None, target=None,
        today: date | None = None) -> dict:
    """Compute (and optionally write) all signals + the rollup status update."""
    project_id, items, item_ids = load_board(owner, number)
    signals = compute_signals(items, today=today)
    rel_closed = release_milestone_closed(items)
    health = rollup_health(signals, items, release_milestone_closed=rel_closed)
    body = rollup_body(health, signals)
    plan = {
        "project": f"{owner}#{number}",
        "items": len(items),
        "signals": signals,
        "rollup": {"status": health, "body": body},
        "applied": False,
    }
    if not apply:
        return plan
    if _refuses_github_token():
        raise SignalsError(
            "GITHUB_TOKEN cannot write Projects v2 fields; set GH_APP_TOKEN "
            "(App installation token) (constraint #2).",
            code=2,
        )
    fields = resolve_fields(owner, number)
    writes = write_signals(project_id, fields, item_ids, signals)
    post_status_update(project_id, health, body, start=start, target=target)
    plan["applied"] = True
    plan["field_writes"] = writes
    return plan


def _refuses_github_token() -> bool:
    """True when no App token is configured (so we must refuse to write).

    A write requires `GH_APP_TOKEN` (the App installation token CI mints) — we
    NEVER fall back to `GITHUB_TOKEN` for a Projects write (constraint #2).
    """
    return not os.environ.get("GH_APP_TOKEN")


# --------------------------------------------------------------------------- #
# CLI — exit codes 0/2/3/1; prints no token/secret (AC-3).
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="signals.py",
                                description="gh-projects deterministic signals (no AI)")
    p.add_argument("--owner", required=True)
    p.add_argument("--number", type=int, required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write signal fields + post status update")
    g.add_argument("--plan", action="store_true", help="dry run: compute + print, write nothing (default)")
    p.add_argument("--start", help="status-update start date (YYYY-MM-DD)")
    p.add_argument("--target", help="status-update target date (YYYY-MM-DD)")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        plan = run(args.owner, args.number, apply=args.apply,
                   start=args.start, target=args.target)
        sys.stdout.write(_scrub(json.dumps(plan)) + "\n")
        return 0
    except SignalsError as e:
        sys.stderr.write("error: " + _scrub(str(e)) + "\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + _scrub(str(e)) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
