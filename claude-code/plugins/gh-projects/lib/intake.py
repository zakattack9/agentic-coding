#!/usr/bin/env python3
"""gh-projects intake — the DETERMINISTIC core behind the `intake-issues` skill.

The skill (skills/intake-issues/SKILL.md) does the AI-shaped work: it splits a
raw dump into atomic items and DELEGATES every body+AC to `spec-ops:write-spec`
at the tier's rigor. It authors NO body itself. THIS file holds only the
non-AI decision logic the skill must not invent in prose:

  * size_from_groups        — AC-group count -> S/M/L
  * tier_rigor              — Tier -> spec-ops rigor + whether refine-spec runs
  * epic_split              — >~3-4 groups -> one sub-issue per group, with the
                              `needs §X` DAG projected onto blocked-by edges
  * ready_gate / classify_ac — atomic-observable vs prose AC; refuse `Ready`
                              for prose-only / non-atomic AC, with a reason
  * build_issue_fields      — Type/Size/Tier/PM-ID the issue must carry

Nothing here makes a model call or touches GitHub. The skill feeds it the
spec-ops AC groups + tier and renders/acts on the result; lib/gh.py performs the
actual `addSubIssue`/blocked-by writes, lib/pm.py allocates the PM-#### id.

Stdlib only. CLI exit codes: 0 ok · 2 usage/validation · 3 not found · 1 unexpected.
"""
from __future__ import annotations

import json
import re
import sys

# --------------------------------------------------------------------------- #
# Tier -> spec-ops rigor. The mapping is the pinned, stable interface
# between gh-projects and spec-ops; spec-ops internals may churn without
# breaking us. T3 additionally runs refine-spec to harden + commit the DAG.
# --------------------------------------------------------------------------- #
TIER_RIGOR = {
    "T1": {"rigor": "light", "refine": False},
    "T2": {"rigor": "standard", "refine": False},
    "T3": {"rigor": "full", "refine": True},
}

# The spec-ops skill each tier delegates to (write-spec always; T3 also
# refine-spec). These are skill ids the orchestrating SKILL.md invokes; they are
# named here so the call path is asserted in tests, never hand-typed in prose.
WRITE_SPEC_SKILL = "spec-ops:write-spec"
REFINE_SPEC_SKILL = "spec-ops:refine-spec"


class IntakeError(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Tier normalization
# --------------------------------------------------------------------------- #
def normalize_tier(tier) -> str:
    """Accept 'T1'/'1'/'tier 1'/'trivial' etc. -> canonical 'T1'|'T2'|'T3'."""
    s = str(tier).strip().lower()
    word = {"trivial": "T1", "standard": "T2", "complex": "T3"}
    if s in word:
        return word[s]
    m = re.search(r"([123])", s)
    if not m:
        raise IntakeError(f"unrecognized tier {tier!r} (want T1/T2/T3)")
    return f"T{m.group(1)}"


def tier_rigor(tier) -> dict:
    """Tier -> {'tier','rigor','refine','write_spec','refine_spec'}.

    T1->light · T2->standard · T3->full + refine-spec. `write_spec` /
    `refine_spec` name the exact spec-ops skill the SKILL.md must invoke; the
    SKILL authors NO body inline. `refine_spec` is None unless the tier refines.
    """
    t = normalize_tier(tier)
    spec = TIER_RIGOR[t]
    return {
        "tier": t,
        "rigor": spec["rigor"],
        "refine": spec["refine"],
        "write_spec": WRITE_SPEC_SKILL,
        "refine_spec": REFINE_SPEC_SKILL if spec["refine"] else None,
    }


# --------------------------------------------------------------------------- #
# Size from AC-group count: 1->S · 2-3->M · 4+->L
# --------------------------------------------------------------------------- #
def size_from_groups(group_count: int) -> str:
    n = int(group_count)
    if n < 1:
        raise IntakeError("an item needs at least one AC group")
    if n == 1:
        return "S"
    if n <= 3:
        return "M"
    return "L"


# Epic-split threshold: at >~3-4 groups, recommend splitting into one sub-issue
# per group. We split at 4+ (same boundary that makes size L).
EPIC_SPLIT_THRESHOLD = 4


def should_epic_split(group_count: int) -> bool:
    return int(group_count) >= EPIC_SPLIT_THRESHOLD


# --------------------------------------------------------------------------- #
# needs §X -> blocked-by edge projection
# --------------------------------------------------------------------------- #
_NEEDS_RE = re.compile(r"§\s*([0-9]+)")


def parse_needs(needs) -> list:
    """Extract group numbers a group depends on from its `needs §X` annotation.

    Accepts a list already (['1', 2]) or a free string ('needs §1, §2'). Returns
    a sorted, de-duplicated list of ints. An empty / absent value -> [].
    """
    if needs is None:
        return []
    nums = []
    if isinstance(needs, (list, tuple)):
        for n in needs:
            nums += [int(x) for x in _NEEDS_RE.findall(f"§{n}")] or (
                [int(n)] if str(n).strip().isdigit() else []
            )
    else:
        nums = [int(x) for x in _NEEDS_RE.findall(str(needs))]
    return sorted(set(nums))


def epic_split(groups: list) -> dict:
    """Project the AC-group DAG onto an Epic split.

    `groups` is the ordered list of spec-ops AC groups, each:
        {"index": 1, "name": "lib core", "needs": [...] | "needs §2", "ac": [...]}
    `index` is 1-based and the id used in `needs §X`. Returns:
        {
          "split": bool,                       # >~3-4 groups?
          "sub_issues": [                      # one per group, in order
             {"index","name","needs","blocked_by"}  # blocked_by = needs group indices
          ],
          "edges": [(child_index, blocker_index), ...]  # the blocked-by DAG
        }
    Independent groups (empty `needs`) get no blocked-by -> parallel work.
    Each `needs §X` becomes ONE native blocked-by edge for lib/gh.py.add_blocked_by.
    """
    ordered = sorted(groups, key=lambda g: int(g.get("index", 0)))
    indices = {int(g.get("index")) for g in ordered}
    sub_issues, edges = [], []
    for g in ordered:
        idx = int(g.get("index"))
        name = g.get("name") or f"group {idx}"
        needs = [n for n in parse_needs(g.get("needs")) if n != idx and n in indices]
        for blocker in needs:
            edges.append((idx, blocker))
        sub_issues.append({
            "index": idx,
            "name": name,
            "needs": needs,
            "blocked_by": needs,
        })
    return {
        "split": should_epic_split(len(ordered)),
        "sub_issues": sub_issues,
        "edges": edges,
    }


# --------------------------------------------------------------------------- #
# AC quality gate: atomic, observable end-states vs prose
# --------------------------------------------------------------------------- #
# A criterion enters `Ready` only if it reads as an observable END-STATE
# ("X is true / exists / returns / matches ...") — never a TASK ("add ...",
# "implement ...", "we should ..."). Prose-only / vague AC are refused, with a
# per-criterion reason so the model can self-correct.

_TASK_LEADS = (
    "add", "implement", "build", "create", "write", "make", "update", "refactor",
    "investigate", "explore", "consider", "improve", "handle", "support", "ensure that we",
    "we should", "we need to", "should be able to", "todo", "tbd",
)

# State verbs that signal an observable assertion ("X <verb> ..."). Covers both
# linking verbs ("is/has") and present-tense behavioral verbs that describe an
# observable outcome ("returns/renders/rejects/persists"). Anything not matched
# here ALSO passes the generic third-person-present heuristic below, so this is a
# fast-path allowlist, not the only signal.
_STATE_VERBS = (
    "is", "are", "was", "were", "has", "have", "returns", "return", "exists",
    "matches", "equals", "shows", "renders", "contains", "yields", "produces",
    "resolves", "persists", "passes", "fails", "blocks", "stays", "remains",
    "appears", "displays", "reflects", "reports", "round-trips", "round trips",
    "moves to", "set to", "is set", "becomes", "holds", "verifies", "rejects",
    "accepts", "warms", "records", "responds", "prints", "emits", "raises",
    "surfaces", "round-trip", "completes", "succeeds", "errors", "redirects",
)

# A clause has a present-tense observable verb when some token (not the first,
# task-lead position) is a third-person-singular present verb ("rejects",
# "renders", "warms"): ends in 's', not a plural-noun-ish 'ss'/'us'/'is'/'ous'.
_PRESENT_VERB_RE = re.compile(r"\b[a-z]{3,}s\b")
_NOT_VERB_SUFFIX = ("ss", "us", "ous", " news", "ies", "ics", "ms", "ds", "ns",
                    "rs", "ts", "ls", "gs", "ks", "ps", "ces", "ses")


def _has_present_verb(clause: str) -> bool:
    """Heuristic: a 3rd-person-singular present verb appears mid-clause."""
    toks = clause.split()
    for tok in toks[1:]:  # skip the lead token (task-verb check owns position 0)
        t = tok.strip(".,;:)»\"'")
        if _PRESENT_VERB_RE.fullmatch(t) and not t.endswith(_NOT_VERB_SUFFIX):
            return True
    return False

_VAGUE = ("etc", "and so on", "various", "as needed", "appropriately", "properly",
          "correctly", "etc.", "...")


def classify_ac(text: str) -> dict:
    """Classify one AC criterion. Returns {'atomic': bool, 'reason': str|None}.

    Atomic-observable: a single observable end-state. Rejected when it (a) leads
    with a task verb, (b) carries no state verb at all (prose / heading), (c) is
    multi-part ('X and Y and Z' joining independent assertions), or (d) is vague
    ('handle errors properly', 'etc'). `reason` is None iff atomic.
    """
    raw = str(text or "").strip()
    low = raw.lower().lstrip("-*0123456789. )").strip()
    if not low:
        return {"atomic": False, "reason": "empty criterion"}

    first = low.split()[0].rstrip(",:;")
    if first in _TASK_LEADS or low.startswith(("we should", "we need", "should be able")):
        return {"atomic": False,
                "reason": f"reads as a TASK ('{first} ...'), not an observable end-state"}

    if any(v in low for v in _VAGUE):
        bad = next(v for v in _VAGUE if v in low)
        return {"atomic": False,
                "reason": f"vague / non-verifiable ('{bad}') — state the exact observable outcome"}

    def _is_observable(clause: str) -> bool:
        return any(re.search(r"\b" + re.escape(v) + r"\b", clause) for v in _STATE_VERBS) \
            or _has_present_verb(clause)

    if not _is_observable(low):
        return {"atomic": False,
                "reason": "no observable assertion (prose-only; say what is TRUE, e.g. 'X is …')"}

    # Multi-part: independent assertions stapled with ' and '/' & '/';'. One
    # observable end-state per row — split these into separate AC.
    parts = re.split(r"\s+and\s+|\s*;\s*|\s+&\s+", low)
    independent = [p for p in parts if _is_observable(p)]
    if len(independent) > 1:
        return {"atomic": False,
                "reason": "multiple end-states in one row — split into one AC per observable outcome"}

    return {"atomic": True, "reason": None}


def ready_gate(ac_items) -> dict:
    """Decide whether the item may enter `Ready`.

    `ac_items` is the flat list of criterion strings (across all groups). Returns
        {"ready": bool, "rejections": [{"index","text","reason"}, ...],
         "reason": str|None}
    `ready` is False if ANY criterion is non-atomic / prose-only; `reason`
    summarizes why so the skill can state it and hold the item out of `Ready`.
    An empty AC list is NOT ready ("no acceptance criteria").
    """
    items = list(ac_items or [])
    if not items:
        return {"ready": False, "rejections": [],
                "reason": "no acceptance criteria — cannot enter Ready"}
    rejections = []
    for i, text in enumerate(items, start=1):
        res = classify_ac(text)
        if not res["atomic"]:
            rejections.append({"index": i, "text": str(text), "reason": res["reason"]})
    if rejections:
        return {
            "ready": False,
            "rejections": rejections,
            "reason": (f"{len(rejections)} of {len(items)} AC are prose-only / not atomic "
                       f"observable end-states — refused Ready until rewritten"),
        }
    return {"ready": True, "rejections": [], "reason": None}


# --------------------------------------------------------------------------- #
# Issue field block: every item carries Type/Size/Tier/PM-ID
# --------------------------------------------------------------------------- #
_VALID_TYPE = {"Feature", "Bug", "Chore", "Infra"}


def build_issue_fields(*, item_type: str, tier, pm_id: str, group_count: int) -> dict:
    """Assemble the required field block every intake issue must set.

    Size is DERIVED from the AC-group count (not free-chosen); Tier is
    normalized; Type is validated against the issue-form enum; PM-#### is the id
    lib/pm.py allocated. The skill copies these verbatim onto the issue + its
    Project item. Returns a dict with Type/Size/Tier/PM-ID + the rigor mapping.
    """
    itype = str(item_type).strip().capitalize()
    if itype not in _VALID_TYPE:
        raise IntakeError(f"invalid Type {item_type!r} (want one of {sorted(_VALID_TYPE)})")
    if not re.fullmatch(r"PM-\d{4,}", str(pm_id)):
        raise IntakeError(f"invalid PM-ID {pm_id!r} (want PM-#### from lib/pm.py)")
    rigor = tier_rigor(tier)
    return {
        "Type": itype,
        "Size": size_from_groups(group_count),
        "Tier": rigor["tier"],
        "PM-ID": str(pm_id),
        "rigor": rigor["rigor"],
        "refine": rigor["refine"],
        "write_spec": rigor["write_spec"],
        "refine_spec": rigor["refine_spec"],
    }


# --------------------------------------------------------------------------- #
# Plan one item end-to-end (deterministic) — the skill renders this preview
# --------------------------------------------------------------------------- #
def plan_item(item: dict) -> dict:
    """Compute the full deterministic plan for one intake item.

    `item` (the skill assembles this AFTER spec-ops authored the AC groups):
        {
          "type": "Feature",
          "tier": "T3",
          "pm_id": "PM-0007",
          "title": "...",
          "groups": [{"index","name","needs","ac":[...]}...],  # spec-ops output
        }
    Returns the merged plan: fields, the ready decision, the tier->rigor
    delegation, and the size + epic-split + blocked-by edges. Makes NO model
    call and NO GitHub write — pure function.
    """
    groups = list(item.get("groups") or [])
    group_count = len(groups)
    flat_ac = [c for g in groups for c in (g.get("ac") or [])]

    fields = build_issue_fields(
        item_type=item.get("type"),
        tier=item.get("tier"),
        pm_id=item.get("pm_id"),
        group_count=group_count,
    )
    gate = ready_gate(flat_ac)
    split = epic_split(groups)
    return {
        "title": item.get("title"),
        "fields": fields,
        "ready": gate["ready"],
        "ready_reason": gate["reason"],
        "rejections": gate["rejections"],
        "delegation": {
            "write_spec": fields["write_spec"],
            "rigor": fields["rigor"],
            "refine_spec": fields["refine_spec"],
        },
        "size": fields["Size"],
        "epic_split": split["split"],
        "sub_issues": split["sub_issues"],
        "blocked_by_edges": split["edges"],
    }


# --------------------------------------------------------------------------- #
# CLI — documented exit codes 0/2/3/1
# --------------------------------------------------------------------------- #
def _read_stdin_json() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        raise IntakeError("expected an item JSON on stdin")
    try:
        obj = json.loads(raw)
    except ValueError as e:
        raise IntakeError(f"stdin is not valid JSON: {e}")
    if not isinstance(obj, dict):
        raise IntakeError("stdin must be a JSON object")
    return obj


def _cmd_plan(_args) -> int:
    print(json.dumps(plan_item(_read_stdin_json()), indent=2))
    return 0


def _cmd_rigor(args) -> int:
    print(json.dumps(tier_rigor(args.tier)))
    return 0


def _cmd_size(args) -> int:
    print(json.dumps({"groups": args.groups, "size": size_from_groups(args.groups),
                      "epic_split": should_epic_split(args.groups)}))
    return 0


def _cmd_ready(_args) -> int:
    obj = _read_stdin_json()
    ac = obj.get("ac") if isinstance(obj, dict) else None
    if ac is None and isinstance(obj, dict):
        ac = [c for g in (obj.get("groups") or []) for c in (g.get("ac") or [])]
    res = ready_gate(ac or [])
    print(json.dumps(res, indent=2))
    return 0 if res["ready"] else 2


def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="intake.py", description="gh-projects deterministic intake core")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="full deterministic plan for one item (JSON on stdin)")
    sp.set_defaults(func=_cmd_plan)

    sp = sub.add_parser("rigor", help="tier -> spec-ops rigor + delegation")
    sp.add_argument("tier")
    sp.set_defaults(func=_cmd_rigor)

    sp = sub.add_parser("size", help="AC-group count -> size + epic-split flag")
    sp.add_argument("groups", type=int)
    sp.set_defaults(func=_cmd_size)

    sp = sub.add_parser("ready", help="AC ready-gate (exit 2 if refused) — JSON on stdin")
    sp.set_defaults(func=_cmd_ready)
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        return args.func(args)
    except IntakeError as e:
        sys.stderr.write(f"error: {e}\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"error: unexpected: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
