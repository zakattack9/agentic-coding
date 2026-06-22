#!/usr/bin/env python3
"""gh-projects ranked-findings engine (deterministic, free, no AI).

A READ-ONLY machine-lens over the board's EXISTING signals. It reads what is
already on the board — the written Schedule health / Slippage / Blast radius /
Blast count / Blocked / Impact level / Decision needed field values, the native
blocked-by dependency graph, and issue content (Status, Size, Target date,
assignees, the "## Acceptance Criteria" table, Sub-issues progress) — and emits a
RANKED list of findings. It introduces NO new persisted data and NEVER writes a
field, posts a Status update, or mutates anything.

Two layers, split for offline testability and a clean read-only seam:

  * `compute_findings(items, *, today)` — the PURE, testable core. Pure dict/date
    math over a normalized board snapshot; no I/O, no network, no model call.
    The same snapshot always yields the identical ranked list (stable order).
  * `load_board(owner, number)` / `run(...)` — page the live board into that
    snapshot through the injectable `RUN`/`graphql` seam, then call
    `compute_findings`. Only READS go over the seam (GraphQL queries); the engine
    issues no mutation. Tests override `RUN` (offline) or call `compute_findings`
    directly on fixtures.

Each finding carries:
  * `kind`     — a stable machine identifier for the finding category.
  * `evidence` — the triggering issue number(s) + the field value(s) that fired
                 the finding (machine-checkable).
  * `title` / `summary` — human-readable narration slots.
  * `severity` — an integer rank (lower = more urgent) for stable ordering.
  * `action`   — the resolving skill to run + suggested args, so each digest line
                 is a one-command fix. A finding the PM must DECIDE (no skill can
                 resolve it) records the named decision instead.

The findings MATH is here and deterministic (cron-safe, no metered AI). The
interactive `analyze-*` skills only narrate and prioritize on the model; they add
no math and write nothing.

Exit codes (the CLI entrypoint): 0 ok · 2 usage/validation · 3 not found ·
1 unexpected — mirrors gh.py / sprint.py.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys

# --------------------------------------------------------------------------- #
# Field/option names + the resolving-skill identifiers (the EXACT board
# spellings; the skills render against these).
# --------------------------------------------------------------------------- #
HEALTH_ON_TRACK = "On track"
HEALTH_AT_RISK = "At risk"
HEALTH_BLOCKED = "Blocked"
HEALTH_OVERDUE = "Overdue"
HEALTH_DONE = "Done"

BLAST_NONE = "Blocks none"
BLAST_ONE = "Blocks 1"
BLAST_MANY = "Blocks many"
BLAST_RELEASE = "Blocks release"

BLOCKED_YES = "Blocked"
BLOCKED_NO = "Unblocked"

IMPACT_RELEASE = "Release blocker"
IMPACT_HIGH = "High"

STATUS_READY = "Ready"
IN_SPRINT_STATUSES = ("Ready", "In Progress", "In Review", "On Staging")

DECISION_NONE = "No"

# Resolving skills (the action each finding routes to).
SKILL_CREATE_ISSUES = "create-issues"
SKILL_START_ISSUE = "start-issue"
SKILL_PLAN_SPRINT = "plan-sprint"

# Finding kinds (stable machine identifiers).
KIND_CRITICAL_CHAIN = "critical_chain"          # release-blocker that is itself blocked
KIND_OVERDUE_HIGH_BLAST = "overdue_high_blast"   # overdue x high blast radius
KIND_STALLED_EPIC = "stalled_epic"               # At risk/Overdue epic, incomplete sub-issues
KIND_INTAKE_HYGIENE = "intake_hygiene"           # Ready item missing AC table / Size / Target
KIND_UNASSIGNED_IN_SPRINT = "unassigned_in_sprint"
KIND_DECISION_NEEDED = "decision_needed"         # Decision needed != No

# Severity ranks (lower = more urgent). Stable, fully deterministic.
SEV_CRITICAL_CHAIN = 0
SEV_OVERDUE_HIGH_BLAST = 1
SEV_STALLED_EPIC = 2
SEV_DECISION_NEEDED = 3
SEV_INTAKE_HYGIENE = 4
SEV_UNASSIGNED_IN_SPRINT = 5


class AnalysisError(Exception):
    """An analysis computation failed. Carries a code for the CLI exit map."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Injectable command runner (the ONE seam tests override) — READ-ONLY use only.
# --------------------------------------------------------------------------- #
def _default_run(args) -> str:
    proc = subprocess.run(["gh", *[str(a) for a in args]], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AnalysisError(f"gh call failed: {_scrub(proc.stderr.strip())}", code=1)
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
# Date helper — pure.
# --------------------------------------------------------------------------- #
def _parse_date(value):
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _utc_today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


# --------------------------------------------------------------------------- #
# The board snapshot schema `compute_findings` consumes (a list of dicts):
#
#   {"number": <issue number, int|str>,    # stable id + tiebreak key
#    "status": <"Backlog"|"Ready"|... >,    # board Status (lifecycle stage)
#    "type": <"Feature"|"Epic"|... >,       # Issue Type
#    "size": <"S"|"M"|"L"|None>,            # appetite
#    "target": <"YYYY-MM-DD"|None>,         # Target date
#    "assignees": [<login>, ...],           # native assignees
#    "has_ac_table": <bool>,                # body has a "## Acceptance Criteria" table
#    "sub_issues_total": <int>,             # Epic sub-issue count (0 if not an epic)
#    "sub_issues_done": <int>,              # completed sub-issues
#    "schedule_health": <"On track"|... >,  # the WRITTEN Schedule health value
#    "blast_radius": <"Blocks none"|... >,  # the WRITTEN Blast radius value
#    "blocked": <"Blocked"|"Unblocked">,    # the WRITTEN Blocked value
#    "impact": <"Release blocker"|... >,    # Impact level (human-set)
#    "decision_needed": <"No"|"Move date"|...>,  # Decision needed (human-set)
#    "blocked_by": [<number>, ...]}         # the native blocked-by edges
#
# Missing keys degrade to safe defaults — a snapshot from `load_board` always
# fills them; a fixture may omit the ones a given finding does not read.
# --------------------------------------------------------------------------- #
def _norm(item: dict) -> dict:
    """Normalize one snapshot item to the full key set with safe defaults."""
    it = item or {}
    return {
        "number": str(it.get("number", "")),
        "status": it.get("status") or "",
        "type": it.get("type") or "",
        "size": it.get("size"),
        "target": it.get("target"),
        "assignees": list(it.get("assignees") or []),
        "has_ac_table": bool(it.get("has_ac_table")),
        "sub_issues_total": int(it.get("sub_issues_total") or 0),
        "sub_issues_done": int(it.get("sub_issues_done") or 0),
        "schedule_health": it.get("schedule_health") or "",
        "blast_radius": it.get("blast_radius") or "",
        "blocked": it.get("blocked") or "",
        "impact": it.get("impact") or "",
        "decision_needed": it.get("decision_needed") or DECISION_NONE,
        "blocked_by": [str(b) for b in (it.get("blocked_by") or [])],
    }


def _finding(kind, severity, number, *, title, summary, evidence, action):
    """Build one structured finding record."""
    return {
        "kind": kind,
        "severity": severity,
        "number": str(number),
        "title": title,
        "summary": summary,
        "evidence": evidence,
        "action": action,
    }


def _action(skill, args, *, note=None):
    """An action record: the resolving skill + suggested args (a one-command fix).

    `skill` is None for a finding the PM must DECIDE — no skill resolves it; the
    `note` then names the move owed.
    """
    return {"skill": skill, "args": args, "note": note}


# --------------------------------------------------------------------------- #
# The PURE findings core — deterministic, no I/O.
# --------------------------------------------------------------------------- #
def compute_findings(items, *, today=None):
    """Return the ranked findings list for a board snapshot. Pure function.

    `items` is the snapshot (see the schema note above). `today` defaults to the
    UTC date; pass it explicitly for reproducible tests. Reads only what is on
    the board; computes no new persisted data. Findings are sorted by a fully
    deterministic key — (severity, issue number, kind) — so the SAME snapshot
    always yields the IDENTICAL order regardless of input ordering.
    """
    today = today or _utc_today()
    norm = [_norm(it) for it in (items or [])]
    findings = []

    for it in norm:
        num = it["number"]

        # --- critical chain: a release-blocker that is itself blocked --------
        is_release_blocker = (
            it["impact"] == IMPACT_RELEASE or it["blast_radius"] == BLAST_RELEASE
        )
        if is_release_blocker and it["blocked"] == BLOCKED_YES:
            blockers = it["blocked_by"]
            findings.append(_finding(
                KIND_CRITICAL_CHAIN, SEV_CRITICAL_CHAIN, num,
                title=f"Release-blocker #{num} is itself blocked",
                summary=(f"#{num} is on the critical path (Impact "
                         f"{it['impact'] or '—'} / Blast {it['blast_radius'] or '—'}) "
                         f"but held by an open dependency."),
                evidence={"number": num, "impact": it["impact"],
                          "blast_radius": it["blast_radius"],
                          "blocked": it["blocked"], "blocked_by": blockers},
                action=_action(
                    SKILL_START_ISSUE,
                    f"#{blockers[0]}" if blockers else f"#{num}",
                    note=("clear the upstream blocker to free the critical chain"
                          if blockers else None)),
            ))

        # --- overdue x high blast radius ------------------------------------
        high_blast = it["blast_radius"] in (BLAST_RELEASE, BLAST_MANY)
        if it["schedule_health"] == HEALTH_OVERDUE and high_blast:
            findings.append(_finding(
                KIND_OVERDUE_HIGH_BLAST, SEV_OVERDUE_HIGH_BLAST, num,
                title=f"#{num} is overdue and high blast-radius",
                summary=(f"#{num} is Overdue with Blast radius "
                         f"{it['blast_radius']} — its slip stalls downstream work."),
                evidence={"number": num, "schedule_health": it["schedule_health"],
                          "blast_radius": it["blast_radius"], "target": it["target"]},
                action=_action(SKILL_PLAN_SPRINT, f"reschedule #{num}",
                               note="move the date or cut scope, then re-plan"),
            ))

        # --- stalled epic: At risk/Overdue epic with incomplete sub-issues --
        if (it["type"] == "Epic"
                and it["schedule_health"] in (HEALTH_AT_RISK, HEALTH_OVERDUE)
                and it["sub_issues_total"] > 0
                and it["sub_issues_done"] < it["sub_issues_total"]):
            findings.append(_finding(
                KIND_STALLED_EPIC, SEV_STALLED_EPIC, num,
                title=f"Epic #{num} is stalling",
                summary=(f"Epic #{num} is {it['schedule_health']} with "
                         f"{it['sub_issues_done']}/{it['sub_issues_total']} "
                         f"sub-issues done."),
                evidence={"number": num, "schedule_health": it["schedule_health"],
                          "sub_issues_done": it["sub_issues_done"],
                          "sub_issues_total": it["sub_issues_total"]},
                action=_action(SKILL_PLAN_SPRINT, f"re-plan epic #{num}",
                               note="re-plan or start the next sub-issue"),
            ))

        # --- intake-hygiene gaps: Ready item missing AC table/Size/Target ----
        if it["status"] == STATUS_READY:
            gaps = []
            if not it["has_ac_table"]:
                gaps.append("AC table")
            if not it["size"]:
                gaps.append("Size")
            if not it["target"]:
                gaps.append("Target date")
            if gaps:
                findings.append(_finding(
                    KIND_INTAKE_HYGIENE, SEV_INTAKE_HYGIENE, num,
                    title=f"Ready #{num} has intake gaps",
                    summary=(f"#{num} is Ready but missing: "
                             f"{', '.join(gaps)}."),
                    evidence={"number": num, "status": it["status"],
                              "missing": gaps, "size": it["size"],
                              "target": it["target"],
                              "has_ac_table": it["has_ac_table"]},
                    action=_action(SKILL_CREATE_ISSUES, f"#{num}",
                                   note="complete intake fields before it is worked"),
                ))

        # --- unassigned in-sprint work --------------------------------------
        if it["status"] in IN_SPRINT_STATUSES and not it["assignees"]:
            findings.append(_finding(
                KIND_UNASSIGNED_IN_SPRINT, SEV_UNASSIGNED_IN_SPRINT, num,
                title=f"In-sprint #{num} is unassigned",
                summary=f"#{num} is {it['status']} with no assignee.",
                evidence={"number": num, "status": it["status"], "assignees": []},
                action=_action(SKILL_PLAN_SPRINT, f"assign #{num}",
                               note="assign an owner during planning"),
            ))

        # --- Decision needed != No (the PM owns the named decision) ----------
        if it["decision_needed"] and it["decision_needed"] != DECISION_NONE:
            findings.append(_finding(
                KIND_DECISION_NEEDED, SEV_DECISION_NEEDED, num,
                title=f"#{num} needs a decision: {it['decision_needed']}",
                summary=(f"#{num} has Decision needed = "
                         f"{it['decision_needed']} — a PM/CTO call is owed."),
                evidence={"number": num, "decision_needed": it["decision_needed"]},
                # No skill resolves a product/architecture call — the option
                # names the move the PM must make.
                action=_action(None, None, note=it["decision_needed"]),
            ))

    findings.sort(key=lambda f: (f["severity"], _num_key(f["number"]), f["kind"]))
    return findings


def _num_key(number):
    """Sort issue numbers numerically when possible, else lexically (stable)."""
    s = str(number)
    try:
        return (0, int(s))
    except (ValueError, TypeError):
        return (1, s)


# --------------------------------------------------------------------------- #
# Rollup counts the skills surface alongside the findings (pure).
# --------------------------------------------------------------------------- #
def rollup_counts(items):
    """Deterministic top-line counts over the snapshot (no AI)."""
    norm = [_norm(it) for it in (items or [])]
    return {
        "items": len(norm),
        "overdue": sum(1 for it in norm if it["schedule_health"] == HEALTH_OVERDUE),
        "at_risk": sum(1 for it in norm if it["schedule_health"] == HEALTH_AT_RISK),
        "blocked": sum(1 for it in norm if it["blocked"] == BLOCKED_YES),
        "decisions_owed": sum(1 for it in norm
                              if it["decision_needed"] not in ("", DECISION_NONE)),
    }


# --------------------------------------------------------------------------- #
# Board read — page the project into the snapshot (READ-ONLY, through the seam).
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
        raise AnalysisError(f"graphql errors: {_scrub(json.dumps(payload['errors']))}", code=1)
    return payload.get("data", payload) if isinstance(payload, dict) else {}


# A single read-only query: the item content + the WRITTEN signal/decision field
# values the findings read. No mutation is ever issued by this engine.
_ITEMS_QUERY = """
query($owner:String!, $number:Int!, $after:String){
  organization(login:$owner){
    projectV2(number:$number){
      id
      items(first:100, after:$after){
        pageInfo { hasNextPage endCursor }
        nodes{
          content{
            __typename
            ... on Issue {
              number
              body
              issueType { name }
              assignees(first:20){ nodes { login } }
              subIssuesSummary { total completed }
              blockedBy: issueDependenciesSummary { blockedBy }
            }
          }
          status:        fieldValueByName(name:"Status"){          ... on ProjectV2ItemFieldSingleSelectValue { name } }
          size:          fieldValueByName(name:"Size"){            ... on ProjectV2ItemFieldSingleSelectValue { name } }
          target:        fieldValueByName(name:"Target date"){     ... on ProjectV2ItemFieldDateValue { date } }
          health:        fieldValueByName(name:"Schedule health"){ ... on ProjectV2ItemFieldSingleSelectValue { name } }
          blast:         fieldValueByName(name:"Blast radius"){    ... on ProjectV2ItemFieldSingleSelectValue { name } }
          blockedField:  fieldValueByName(name:"Blocked"){         ... on ProjectV2ItemFieldSingleSelectValue { name } }
          impact:        fieldValueByName(name:"Impact level"){    ... on ProjectV2ItemFieldSingleSelectValue { name } }
          decision:      fieldValueByName(name:"Decision needed"){ ... on ProjectV2ItemFieldSingleSelectValue { name } }
        }
      }
    }
  }
}
"""

_AC_HEADING = "## acceptance criteria"


def _has_ac_table(body) -> bool:
    """True if the issue body has a "## Acceptance Criteria" table (a `|` row
    under the heading). A prose-only AC section does not count."""
    if not body:
        return False
    lines = str(body).splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(_AC_HEADING):
            for follow in lines[i + 1:]:
                stripped = follow.strip()
                if stripped.startswith("|"):
                    return True
                if stripped.startswith("#"):  # next section — no table found
                    break
            break
    return False


def _opt(node, key) -> str:
    return ((node.get(key) or {}).get("name")) or ""


def load_board(owner: str, number: int):
    """Page the project items into the analysis snapshot (READ-ONLY).

    Returns the list of snapshot dicts `compute_findings` consumes. Only GraphQL
    READ queries go over the seam — the engine issues no mutation.
    """
    snapshot = []
    after = None
    seen_project = False
    while True:
        data = graphql(_ITEMS_QUERY, {"owner": owner, "number": int(number), "after": after})
        proj = (((data or {}).get("organization") or {}).get("projectV2")) or {}
        if not proj.get("id"):
            raise AnalysisError(f"project {owner}#{number} not found", code=3)
        seen_project = True
        conn = proj.get("items") or {}
        for node in (conn.get("nodes") or []):
            content = node.get("content") or {}
            if content.get("__typename") != "Issue":
                continue  # draft issues / PRs carry no analysis content
            sub = content.get("subIssuesSummary") or {}
            blocked_by = ((content.get("blockedBy") or {}).get("blockedBy")) or []
            assignees = [a.get("login") for a in
                         ((content.get("assignees") or {}).get("nodes") or [])
                         if a.get("login")]
            snapshot.append({
                "number": str(content.get("number")),
                "status": _opt(node, "status"),
                "type": ((content.get("issueType") or {}).get("name")) or "",
                "size": _opt(node, "size") or None,
                "target": ((node.get("target") or {}).get("date")),
                "assignees": assignees,
                "has_ac_table": _has_ac_table(content.get("body")),
                "sub_issues_total": int(sub.get("total") or 0),
                "sub_issues_done": int(sub.get("completed") or 0),
                "schedule_health": _opt(node, "health"),
                "blast_radius": _opt(node, "blast"),
                "blocked": _opt(node, "blockedField"),
                "impact": _opt(node, "impact"),
                "decision_needed": _opt(node, "decision") or DECISION_NONE,
                "blocked_by": [str(b) for b in blocked_by],
            })
        page = conn.get("pageInfo") or {}
        if page.get("hasNextPage"):
            after = page.get("endCursor")
            continue
        break
    if not seen_project:
        raise AnalysisError(f"project {owner}#{number} not found", code=3)
    return snapshot


def run(owner: str, number: int, *, today=None) -> dict:
    """Fetch the live board (read-only) and emit the ranked findings + counts.

    The whole result is computed by `compute_findings` over the snapshot — this
    function only does the read seam + assembly. It NEVER writes.
    """
    snapshot = load_board(owner, number)
    findings = compute_findings(snapshot, today=today)
    return {
        "project": f"{owner}#{number}",
        "counts": rollup_counts(snapshot),
        "findings": findings,
    }


# --------------------------------------------------------------------------- #
# CLI — documented exit codes 0/2/3/1; prints no token/secret; never writes.
# --------------------------------------------------------------------------- #
def build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="analysis.py",
        description="gh-projects ranked-findings engine (read-only, no AI)")
    p.add_argument("--owner", help="org login (live board read)")
    p.add_argument("--number", type=int, help="project number (live board read)")
    p.add_argument("--snapshot", default=None,
                   help="path to a board-snapshot JSON array, or - for stdin "
                        "(offline; skips the live read)")
    p.add_argument("--today", default=None, help="reference date YYYY-MM-DD (default: UTC today)")
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    today = _parse_date(args.today) if args.today else None
    if args.today and today is None:
        sys.stderr.write(f"error: invalid --today {args.today!r}\n")
        return 2
    try:
        if args.snapshot is not None:
            raw = sys.stdin.read() if args.snapshot == "-" else _read_file(args.snapshot)
            items = json.loads(raw) if raw and raw.strip() else []
            if not isinstance(items, list):
                raise AnalysisError("snapshot must be a JSON array", code=2)
            result = {
                "project": "(snapshot)",
                "counts": rollup_counts(items),
                "findings": compute_findings(items, today=today),
            }
        else:
            if not args.owner or args.number is None:
                raise AnalysisError("need --owner and --number (or --snapshot)", code=2)
            result = run(args.owner, args.number, today=today)
        sys.stdout.write(_scrub(json.dumps(result)) + "\n")
        return 0
    except AnalysisError as e:
        sys.stderr.write("error: " + _scrub(str(e)) + "\n")
        return e.code
    except json.JSONDecodeError as e:
        sys.stderr.write("error: invalid snapshot JSON: " + _scrub(str(e)) + "\n")
        return 2
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + _scrub(str(e)) + "\n")
        return 1


def _read_file(path) -> str:
    if not os.path.isfile(path):
        raise AnalysisError(f"no such file: {path}", code=3)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


if __name__ == "__main__":
    sys.exit(main())
