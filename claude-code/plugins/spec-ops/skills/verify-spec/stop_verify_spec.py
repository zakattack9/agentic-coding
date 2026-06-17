#!/usr/bin/env python3
"""stop_verify_spec.py — Stop hook for the verify-spec skill.

Deterministically enforces the verify-spec verification loop: while a run is
active, Claude cannot end its turn until the ledger shows a structurally complete,
judge-signed verification — every checkable claim driven to a definitive verdict
with cited evidence (or a user disposition), and a fresh independent judge having
run and attested the verification is complete.

Activates ONLY when a session-scoped marker (the "ledger") exists at
  /tmp/claude-verify-spec-<session_id>.json
so normal sessions (and other skills, including refine-spec) are never affected.
The ledger is written by the skill at the start of, and during, a run, and
removed here once the verification gate passes.

The ledger is authored by the model, so it is treated as UNTRUSTED input and
validated strictly. The guardrail must never be silently disabled by an AI
mistake (malformed JSON, wrong types):

  fail-SAFE  — while a run is active, a malformed/invalid/unreadable ledger
               BLOCKS with an exact correction message (it does not allow the
               stop and does not crash). An AI mistake forces a fix, not a pass.
  fail-OPEN  — only the "can't even tell a run is active" cases release:
               unreadable stdin, no session id, or no ledger file. Plus the
               mtime escape below, so a run can never hard-trap a user.

Escape valves (so enforcement can never permanently trap someone):
  - Freshness: if the ledger's mtime is older than STALE_SECONDS (the agent
    stopped refreshing it — stuck or abandoned), it is removed and released.
  - The user can interrupt the turn at any time.
  - The block reason tells Claude to delete the ledger and stop if the user
    has redirected to unrelated work.

What this hook CAN enforce is structure + that the judge ran and signed off; it
canNOT see whether enumeration was complete or whether a citation is genuine —
that is the judge's job, which is why the judge's sign-off is itself gated.

Readiness (all required) once the ledger is valid:
  1. No claim is still `unchecked`.
  2. Every `confirmed` / `contradicted` claim cites non-empty `evidence`.
  3. Every `unverifiable` claim carries a non-empty `disposition`.
  4. The independent judge ran (`judge.ran`), returned `verdict: "complete"`, and
     reported no `missed` claims and no `weakEvidence`.
  `contradicted` claims are findings, not blockers — they do NOT hold the stop.
  `backwardSweep` (R1 backward-coverage pass) is OPTIONAL and shape-validated when
  present, but NEVER gates the stop — its `findings` are reports like `contradicted`
  claims, and the judge (not this hook) attests the sweep actually ran.

Input:  JSON on stdin (hook payload; uses `session_id`).
Output: nothing to allow the stop; {"decision":"block","reason":...} to force
        another pass.
"""

import json
import os
import sys
import time

# Ledger is considered abandoned/stuck if not rewritten within this window.
# Long enough for a heavy pass (parallel grounding subagents + user Q&A),
# short enough that a leaked ledger frees the session on its own.
STALE_SECONDS = 45 * 60

# Allowed verdict values for a claim.
VERDICTS = {"unchecked", "confirmed", "contradicted", "unverifiable"}

# Canonical ledger shape, shown to the agent whenever its ledger is rejected.
SCHEMA_HINT = (
    '{\n'
    '  "target": "<what you are verifying — a path, feature, or commit range>",\n'
    '  "claims": [\n'
    '    {\n'
    '      "claim": "short text of one checkable claim",\n'
    '      "verdict": "unchecked | confirmed | contradicted | unverifiable",\n'
    '      "evidence": "file:line / git sha / read-only CLI output (required once verdict is confirmed/contradicted)",\n'
    '      "disposition": "the user\'s call (required once verdict is unverifiable)"\n'
    '    }\n'
    '  ],\n'
    '  "judge": {\n'
    '    "ran": false,\n'
    '    "verdict": "pending | gaps | complete",\n'
    '    "missed": ["claims the judge found absent from the ledger"],\n'
    '    "weakEvidence": ["claims whose evidence the judge found hollow/stale/doc-based"]\n'
    '  },\n'
    '  "backwardSweep": {\n'
    '    "ran": false,\n'
    '    "base": "diff base swept (commit range), or empty if none",\n'
    '    "skippedReason": "why the sweep was skipped, if it was (else empty)",\n'
    '    "findings": [\n'
    '      {\n'
    '        "hunk": "file:line / path of a substantive change mapping to NO acceptance criterion",\n'
    '        "evidence": "git sha / file:line",\n'
    '        "disposition": "intended | unintended | unsure",\n'
    '        "proposedAC": "candidate AC text"\n'
    '      }\n'
    '    ]\n'
    '  }\n'
    '}'
)


def allow():
    """Permit the stop (default behavior). No output == allow."""
    sys.exit(0)


def block(reason: str):
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def reject_ledger(marker_path: str, problems: list):
    """Block because the model-authored ledger is invalid. Keep the ledger so
    the block persists until the agent rewrites it correctly."""
    block(
        "Your verify-spec ledger at "
        + marker_path
        + " is invalid, so the verification gate cannot be evaluated. Do NOT stop. "
        "Rewrite it as STRICT, valid JSON exactly matching this schema "
        "(`verdict` must be one of unchecked/confirmed/contradicted/unverifiable; "
        "`backwardSweep` is OPTIONAL and report-only — include it for a spec "
        "implementation, omit it otherwise):\n\n"
        + SCHEMA_HINT
        + "\n\nProblems found:\n"
        + "\n".join(f"- {p}" for p in problems)
        + "\n\nIf the user has redirected to unrelated work, delete that file and stop instead."
    )


def validate_ledger(m):
    """Return a list of structural problems with the parsed ledger (empty == ok).
    Strict: the ledger is untrusted, model-authored input."""
    if not isinstance(m, dict):
        return ["the ledger must be a JSON object"]

    problems = []

    # target: required, non-empty string.
    target = m.get("target")
    if not isinstance(target, str) or not target.strip():
        problems.append("'target' must be a non-empty string (what is being verified)")

    # claims: required, non-empty list of {claim, verdict, evidence?, disposition?}.
    claims = m.get("claims")
    if not isinstance(claims, list) or not claims:
        problems.append("'claims' must be a non-empty JSON array of claim objects")
    else:
        for i, c in enumerate(claims):
            if not isinstance(c, dict):
                problems.append(f"claims[{i}] must be an object with 'claim' and 'verdict'")
                continue
            if not isinstance(c.get("claim"), str) or not c.get("claim").strip():
                problems.append(f"claims[{i}].claim must be a non-empty string")
            v = c.get("verdict")
            if v not in VERDICTS:
                problems.append(
                    f"claims[{i}].verdict must be one of "
                    + "/".join(sorted(VERDICTS))
                    + f" (got {v!r})"
                )
            if "evidence" in c and not isinstance(c.get("evidence"), str):
                problems.append(f"claims[{i}].evidence must be a string")
            if "disposition" in c and not isinstance(c.get("disposition"), str):
                problems.append(f"claims[{i}].disposition must be a string")

    # judge: required object recording the independent judge's result.
    judge = m.get("judge")
    if not isinstance(judge, dict):
        problems.append(
            "'judge' must be a JSON object {ran, verdict, missed, weakEvidence} "
            "recording the independent judge's result"
        )
    else:
        if not isinstance(judge.get("ran"), bool):
            problems.append("'judge.ran' must be a JSON boolean (true/false)")
        if not isinstance(judge.get("verdict"), str) or not judge.get("verdict", "").strip():
            problems.append("'judge.verdict' must be a non-empty string (pending/gaps/complete)")
        for key in ("missed", "weakEvidence"):
            if key in judge and not isinstance(judge.get(key), list):
                problems.append(f"'judge.{key}' must be a JSON array")

    # backwardSweep: OPTIONAL, report-only (R1 backward-coverage pass). It is
    # shape-validated when present so a malformed sweep self-corrects, but it
    # NEVER gates the stop — its findings are reports, exactly like
    # `contradicted` claims. Omitted entirely for non-spec targets.
    sweep = m.get("backwardSweep")
    if sweep is not None:
        if not isinstance(sweep, dict):
            problems.append(
                "'backwardSweep' must be a JSON object {ran, base, skippedReason, findings} when present"
            )
        else:
            if not isinstance(sweep.get("ran"), bool):
                problems.append("'backwardSweep.ran' must be a JSON boolean (true/false)")
            for key in ("base", "skippedReason"):
                if key in sweep and not isinstance(sweep.get(key), str):
                    problems.append(f"'backwardSweep.{key}' must be a string")
            findings = sweep.get("findings")
            if findings is not None and not isinstance(findings, list):
                problems.append("'backwardSweep.findings' must be a JSON array")
            elif isinstance(findings, list):
                for i, f in enumerate(findings):
                    if not isinstance(f, dict):
                        problems.append(f"backwardSweep.findings[{i}] must be an object")
                        continue
                    if not isinstance(f.get("hunk"), str) or not f.get("hunk").strip():
                        problems.append(f"backwardSweep.findings[{i}].hunk must be a non-empty string")
                    for key in ("evidence", "disposition", "proposedAC"):
                        if key in f and not isinstance(f.get(key), str):
                            problems.append(f"backwardSweep.findings[{i}].{key} must be a string")

    return problems


def evaluate(marker_path: str, marker: dict):
    """Validated-ledger path: enforce the verification gate or block with specifics."""
    problems = validate_ledger(marker)
    if problems:
        reject_ledger(marker_path, problems)
        return

    claims = marker["claims"]
    judge = marker["judge"]
    failures = []

    # 1. No claim may still be unchecked.
    unchecked = [c["claim"] for c in claims if c.get("verdict") == "unchecked"]
    if unchecked:
        preview = "; ".join(unchecked[:5])
        more = f" (+{len(unchecked) - 5} more)" if len(unchecked) > 5 else ""
        failures.append(f"{len(unchecked)} claim(s) still unchecked: {preview}{more}")

    # 2. Every confirmed/contradicted claim must cite evidence (real source).
    uncited = [
        c["claim"]
        for c in claims
        if c.get("verdict") in ("confirmed", "contradicted")
        and not str(c.get("evidence", "")).strip()
    ]
    if uncited:
        preview = "; ".join(uncited[:5])
        more = f" (+{len(uncited) - 5} more)" if len(uncited) > 5 else ""
        failures.append(
            "These claims have a verdict but cite no evidence "
            f"(add a file:line / git sha / read-only CLI output): {preview}{more}"
        )

    # 3. Every unverifiable claim must carry an explicit user disposition.
    undispositioned = [
        c["claim"]
        for c in claims
        if c.get("verdict") == "unverifiable" and not str(c.get("disposition", "")).strip()
    ]
    if undispositioned:
        preview = "; ".join(undispositioned[:5])
        more = f" (+{len(undispositioned) - 5} more)" if len(undispositioned) > 5 else ""
        failures.append(
            "These claims are 'unverifiable' but have no user disposition "
            f"(dig further, or ask the user and record their call): {preview}{more}"
        )

    # 4. The independent judge must have run and signed off clean.
    if judge.get("ran") is not True:
        failures.append(
            "The independent verification judge has not run (judge.ran is not true). "
            "Dispatch a fresh judge subagent with no memory of your passes and record its result."
        )
    else:
        if judge.get("verdict") != "complete":
            failures.append(
                f"The judge returned verdict {judge.get('verdict')!r}, not 'complete' — "
                "resolve its findings and re-run it."
            )
        missed = judge.get("missed") or []
        if missed:
            preview = "; ".join(str(x) for x in missed[:5])
            more = f" (+{len(missed) - 5} more)" if len(missed) > 5 else ""
            failures.append(
                f"The judge found {len(missed)} claim(s) missing from the ledger — "
                f"enumerate and verify them: {preview}{more}"
            )
        weak = judge.get("weakEvidence") or []
        if weak:
            preview = "; ".join(str(x) for x in weak[:5])
            more = f" (+{len(weak) - 5} more)" if len(weak) > 5 else ""
            failures.append(
                f"The judge flagged {len(weak)} claim(s) with hollow / stale / doc-based "
                f"evidence — re-ground them against real source: {preview}{more}"
            )

    # Ready: tear down the ledger and let Claude stop.
    if not failures:
        remove(marker_path)
        allow()
        return

    # Not ready: force another pass.
    block(
        "verify-spec loop is still active and verification is not complete. "
        "Do NOT stop — keep grounding claims against real source (code at HEAD, "
        "git history, read-only CLI) and re-run the judge to clear these:\n\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\n\nThen update the ledger at "
        + marker_path
        + " and try again. Remember: evidence must be real source, never the spec or a doc.\n"
        + "If the user has redirected to unrelated work, delete that file and stop instead."
    )


def main():
    # Read the hook payload. If we can't even parse it, we cannot determine
    # whether a run is active -> allow (never break unrelated sessions).
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()
        return

    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        allow()
        return

    marker_path = f"/tmp/claude-verify-spec-{session_id}.json"

    # Fast path: no active verify-spec run -> don't touch this stop.
    if not os.path.isfile(marker_path):
        allow()
        return

    # Stale ledger (agent stopped refreshing it) -> release. This runs BEFORE
    # parsing so an abandoned, even-malformed ledger always frees the session.
    try:
        if time.time() - os.path.getmtime(marker_path) > STALE_SECONDS:
            remove(marker_path)
            allow()
            return
    except OSError:
        allow()
        return

    # Active run. From here on, fail SAFE: any problem blocks with a fix
    # message rather than allowing a premature stop or crashing the hook.
    try:
        with open(marker_path, "r") as f:
            marker = json.load(f)
    except (json.JSONDecodeError, ValueError):
        reject_ledger(marker_path, ["the file is not valid JSON"])
        return
    except OSError:
        # Can't read a ledger we just confirmed exists — transient; don't trap.
        allow()
        return

    try:
        evaluate(marker_path, marker)
    except SystemExit:
        raise  # allow()/block() use sys.exit — let it through
    except Exception as e:  # noqa: BLE001 — never crash into a fail-open
        reject_ledger(marker_path, [f"unexpected ledger processing error: {e}"])


if __name__ == "__main__":
    main()
