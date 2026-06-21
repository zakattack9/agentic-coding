#!/usr/bin/env python3
"""validate_return.py — deterministic shape-check for spec-ops subagent returns.

The grounder and judge subagents that refine-spec and verify-spec dispatch return
their verdicts as JSON. That JSON is model-authored, so the parent skill must treat
it as UNTRUSTED and validate the fields it depends on before folding them into a
ledger or a gate decision — never trust a subagent's prose. This script is that
validation step (the plan-validate-execute pattern): pipe a subagent's return
through it and branch on the exit code.

Four contracts (`--kind`):

  grounder-verify : verify-spec step 2 — a JSON ARRAY, one object per claim:
        [{ "claim", "verdict": confirmed|contradicted|unverifiable,
           "evidence", "method": <one of the five> }]
        evidence + method are required once verdict is confirmed/contradicted.

  grounder-refine : refine-spec step 1 — a JSON ARRAY, one object per claim:
        [{ "claim", "verdict": confirmed|wrong|not-found, "evidence" }]
        evidence is required once verdict is confirmed/wrong.

  judge-verify    : verify-spec step 4 — a JSON OBJECT:
        { "verdict": complete|gaps, "missed": [...], "weakEvidence": [...],
          "backwardSweepAttested"?: bool, "specLinkageSweepAttested"?: bool }

  judge-refine    : refine-spec readiness gate — a JSON OBJECT:
        { "perCriterion": [{ "criterion": <one of the six gate flags>,
            "verdict": PASS|FAIL, "reason" }], "findings": [...],
          "overall": PASS|FAIL }

Input: the JSON on stdin, or a file path argument. Usage:
    python3 validate_return.py --kind <kind> [file.json]
    cat return.json | python3 validate_return.py --kind judge-verify

Exit codes (so a caller branches on the code alone):
    0  valid — the return matches the contract
    2  invalid — prints the problems AND the canonical schema, so the parent can
       hand the subagent a precise correction and re-dispatch
    3  usage error (bad --kind, unreadable input, not JSON)

This validates SHAPE only — it never judges whether the evidence is genuine or the
verdict is correct (that is the judge's job, and the verify/refine Stop hooks gate
the rest). It mirrors the strictness the Stop hooks already apply to the ledger.
"""

import json
import sys

# Method techniques and the six refine gate criteria are mirrored from the skills /
# the verify Stop hook (METHODS) — kept here so the validator is self-contained; the
# hook's SCHEMA_HINT remains the model-facing source of truth for the ledger itself.
METHODS = ("static-read", "measurement", "exhaustive-check", "cli-observation", "test-run")
GROUNDER_VERIFY_VERDICTS = ("confirmed", "contradicted", "unverifiable")
GROUNDER_REFINE_VERDICTS = ("confirmed", "wrong", "not-found")
JUDGE_VERIFY_VERDICTS = ("complete", "gaps")
PASS_FAIL = ("PASS", "FAIL")
REFINE_CRITERIA = (
    "claims_verified", "no_open_questions", "no_overengineering",
    "no_bloat", "implementable_cold", "ac_complete",
)

SCHEMAS = {
    "grounder-verify": (
        '[\n'
        '  { "claim": "one checkable claim",\n'
        '    "verdict": "confirmed | contradicted | unverifiable",\n'
        '    "evidence": "file:line / git sha / read-only CLI output '
        '(required once confirmed/contradicted; state the ACTUAL value when contradicted)",\n'
        '    "method": "' + " | ".join(METHODS) + ' (required once confirmed/contradicted)" }\n'
        ']'
    ),
    "grounder-refine": (
        '[\n'
        '  { "claim": "one checkable spec claim",\n'
        '    "verdict": "confirmed | wrong | not-found",\n'
        '    "evidence": "file:line / commit SHA / CLI output, with the correct value when wrong '
        '(required once confirmed/wrong)" }\n'
        ']'
    ),
    "judge-verify": (
        '{\n'
        '  "verdict": "complete | gaps",\n'
        '  "missed": ["checkable claim / AC-id absent from the ledger"],\n'
        '  "weakEvidence": ["claim whose evidence is hollow / stale / doc-based / below standard"],\n'
        '  "backwardSweepAttested": true,\n'
        '  "specLinkageSweepAttested": true\n'
        '}'
    ),
    "judge-refine": (
        '{\n'
        '  "perCriterion": [\n'
        '    { "criterion": "' + " | ".join(REFINE_CRITERIA) + '",\n'
        '      "verdict": "PASS | FAIL", "reason": "specific reason" }\n'
        '  ],\n'
        '  "findings": [{ "type": "Gap | Ambiguity | Conflict", "acId": "AC-7 or empty", "detail": "..." }],\n'
        '  "overall": "PASS | FAIL"\n'
        '}'
    ),
}


def _is_str(v):
    return isinstance(v, str)


def _nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def validate_grounder_verify(data):
    problems = []
    if not isinstance(data, list) or not data:
        return ["the return must be a non-empty JSON array of claim objects"]
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            problems.append(f"[{i}] must be an object with 'claim' and 'verdict'")
            continue
        if not _nonempty_str(item.get("claim")):
            problems.append(f"[{i}].claim must be a non-empty string")
        v = item.get("verdict")
        if v not in GROUNDER_VERIFY_VERDICTS:
            problems.append(f"[{i}].verdict must be one of {'/'.join(GROUNDER_VERIFY_VERDICTS)} (got {v!r})")
        if v in ("confirmed", "contradicted"):
            if not _nonempty_str(item.get("evidence")):
                problems.append(f"[{i}].evidence must be non-empty real-source evidence once verdict is {v}")
            if not _nonempty_str(item.get("method")):
                problems.append(f"[{i}].method must be recorded once verdict is {v}")
            elif item.get("method") not in METHODS:
                # Reject a method value outside the five techniques here, at dispatch —
                # cheaper than letting a junk/hallucinated method into the ledger for the
                # judge to catch. (The verify Stop hook checks method *presence* only,
                # since by then a compliant grounder has already emitted one of the five;
                # whether the method *fits* the claim stays the judge's call either way.)
                problems.append(
                    f"[{i}].method {item.get('method')!r} is not one of {'/'.join(METHODS)}"
                )
        if "evidence" in item and not _is_str(item.get("evidence")):
            problems.append(f"[{i}].evidence must be a string")
    return problems


def validate_grounder_refine(data):
    problems = []
    if not isinstance(data, list) or not data:
        return ["the return must be a non-empty JSON array of claim objects"]
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            problems.append(f"[{i}] must be an object with 'claim' and 'verdict'")
            continue
        if not _nonempty_str(item.get("claim")):
            problems.append(f"[{i}].claim must be a non-empty string")
        v = item.get("verdict")
        if v not in GROUNDER_REFINE_VERDICTS:
            problems.append(f"[{i}].verdict must be one of {'/'.join(GROUNDER_REFINE_VERDICTS)} (got {v!r})")
        if v in ("confirmed", "wrong") and not _nonempty_str(item.get("evidence")):
            problems.append(f"[{i}].evidence must be non-empty once verdict is {v} (cite where, and the correct value when wrong)")
        if "evidence" in item and not _is_str(item.get("evidence")):
            problems.append(f"[{i}].evidence must be a string")
    return problems


def validate_judge_verify(data):
    problems = []
    if not isinstance(data, dict):
        return ["the return must be a JSON object {verdict, missed, weakEvidence}"]
    if data.get("verdict") not in JUDGE_VERIFY_VERDICTS:
        problems.append(f"verdict must be one of {'/'.join(JUDGE_VERIFY_VERDICTS)} (got {data.get('verdict')!r})")
    for key in ("missed", "weakEvidence"):
        if not isinstance(data.get(key), list):
            problems.append(f"'{key}' must be a JSON array (empty when none)")
    for key in ("backwardSweepAttested", "specLinkageSweepAttested"):
        if key in data and not isinstance(data.get(key), bool):
            problems.append(f"'{key}' must be a JSON boolean when present")
    return problems


def validate_judge_refine(data):
    problems = []
    if not isinstance(data, dict):
        return ["the return must be a JSON object {perCriterion, findings, overall}"]
    if data.get("overall") not in PASS_FAIL:
        problems.append(f"overall must be PASS or FAIL (got {data.get('overall')!r})")
    pc = data.get("perCriterion")
    if not isinstance(pc, list) or not pc:
        problems.append("'perCriterion' must be a non-empty JSON array")
    else:
        seen = set()
        for i, item in enumerate(pc):
            if not isinstance(item, dict):
                problems.append(f"perCriterion[{i}] must be an object")
                continue
            crit = item.get("criterion")
            if crit not in REFINE_CRITERIA:
                problems.append(f"perCriterion[{i}].criterion must be one of {'/'.join(REFINE_CRITERIA)} (got {crit!r})")
            else:
                seen.add(crit)
            if item.get("verdict") not in PASS_FAIL:
                problems.append(f"perCriterion[{i}].verdict must be PASS or FAIL (got {item.get('verdict')!r})")
        missing = [c for c in REFINE_CRITERIA if c not in seen]
        if missing:
            problems.append("perCriterion is missing a verdict for: " + ", ".join(missing))
    if "findings" in data and not isinstance(data.get("findings"), list):
        problems.append("'findings' must be a JSON array when present")
    return problems


VALIDATORS = {
    "grounder-verify": validate_grounder_verify,
    "grounder-refine": validate_grounder_refine,
    "judge-verify": validate_judge_verify,
    "judge-refine": validate_judge_refine,
}


def validate(kind, data):
    """Return a list of shape problems (empty == valid). Raises KeyError on bad kind."""
    return VALIDATORS[kind](data)


def main(argv):
    kind = None
    path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--kind":
            i += 1
            if i >= len(argv):
                sys.stderr.write("validate_return: --kind needs a value\n")
                return 3
            kind = argv[i]
        elif a in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return 0
        elif a.startswith("-"):
            sys.stderr.write(f"validate_return: unknown flag {a!r}\n")
            return 3
        else:
            path = a
        i += 1

    if kind not in VALIDATORS:
        sys.stderr.write(
            "validate_return: --kind must be one of "
            + ", ".join(sorted(VALIDATORS)) + "\n"
        )
        return 3

    try:
        raw = open(path, "r", encoding="utf-8").read() if path else sys.stdin.read()
    except OSError as e:
        sys.stderr.write(f"validate_return: cannot read input: {e}\n")
        return 3

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        sys.stderr.write(
            f"validate_return: the return is not valid JSON ({e}).\n"
            "Re-dispatch the subagent and require STRICT JSON exactly matching:\n\n"
            + SCHEMAS[kind] + "\n"
        )
        return 3

    problems = validate(kind, data)
    if problems:
        sys.stderr.write(
            f"validate_return: the {kind} return is invalid — do NOT trust it. "
            "Re-dispatch the subagent (or fix the parse) to match this schema:\n\n"
            + SCHEMAS[kind]
            + "\n\nProblems:\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n"
        )
        return 2

    sys.stdout.write(f"valid — {kind} return matches the contract\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
