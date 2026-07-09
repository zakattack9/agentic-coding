#!/usr/bin/env python3
"""stop_refine_spec.py — Stop hook for the refine-spec skill.

Deterministically enforces the refine-spec review loop: while a run is active,
Claude cannot end its turn until the spec is actually ready.

Activates ONLY when a session-scoped marker (the "ledger") exists at
  /tmp/claude-refine-spec-<session_id>.json
so normal sessions (and other skills) are never affected. The ledger is written
by the skill at the start of, and during, a run, and removed here once the
readiness gate passes.

The ledger is authored by the model, so it is treated as UNTRUSTED input and
validated strictly. The guardrail must never be silently disabled by an AI
mistake (malformed JSON, wrong types, bad path):

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

Readiness (all required) once the ledger is valid:
  1. Every gate flag is true        (agent attestation per dimension)
  2. Every open question is resolved (agent ledger)
  3. The spec file has no leftover not-finalized markers (mechanical scan)
  3b. The Acceptance Criteria have no duplicate ids and no leftover conflict
      markers (mechanical scan via spec_consistency.py; dangling `AC-N`
      references are reported as advisories and do not block)
  4. The ready spec is committed     (scoped to the spec file via spec_git.py;
                                      fail-OPEN if it isn't a git repo / git errors,
                                      so an unenforceable commit never traps a user)

Input:  JSON on stdin (hook payload; uses `session_id`).
Output: nothing to allow the stop; {"decision":"block","reason":...} to force
        another pass.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# The spec-commit helper lives in the plugin's shared scripts/ dir. The Stop hook
# enforces the READY spec is committed (scoped to the spec file) before releasing
# the stop; the import is guarded so a missing helper never disables the gate.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
try:
    import spec_git
except Exception:  # noqa: BLE001 — a missing helper must never disable the gate
    spec_git = None

# Deterministic AC-integrity check (duplicate ids / dangling refs / conflict markers).
# Guarded so a missing helper never disables the gate.
try:
    import spec_consistency
except Exception:  # noqa: BLE001 — a missing helper must never disable the gate
    spec_consistency = None

# Ledger is considered abandoned/stuck if not rewritten within this window.
# Long enough for a heavy pass (parallel verification subagents + user Q&A),
# short enough that a leaked ledger frees the session on its own.
STALE_SECONDS = 45 * 60

# Heuristic "this spec is not finalized" markers. Case-insensitive.
# Deliberately excludes "- [ ]" — finalized specs legitimately end with a
# verification Checklist of unchecked boxes (see the write-spec format).
NOT_DONE_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\?\?\?",
    r"to be (?:determined|decided|defined)",
    r"\bdecide later\b",
    r"open question",
    r"NEEDS CLARIFICATION",
]
NOT_DONE_RE = re.compile("|".join(NOT_DONE_PATTERNS), re.IGNORECASE)

# Canonical ledger shape, shown to the agent whenever its ledger is rejected.
SCHEMA_HINT = (
    '{\n'
    '  "spec": "<absolute path to the spec file>",\n'
    '  "gate": {\n'
    '    "claims_verified": false,\n'
    '    "no_open_questions": false,\n'
    '    "no_overengineering": false,\n'
    '    "no_bloat": false,\n'
    '    "implementable_cold": false,\n'
    '    "ac_complete": false\n'
    '  },\n'
    '  "openQuestions": [ { "q": "short text", "resolved": false } ]\n'
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
        "Your refine-spec ledger at "
        + marker_path
        + " is invalid, so the readiness gate cannot be evaluated. Do NOT stop. "
        "Rewrite it as STRICT, valid JSON exactly matching this schema "
        "(flags and `resolved` must be JSON booleans true/false, not strings):\n\n"
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

    # spec: required, non-empty string (existence is checked separately).
    spec = m.get("spec")
    if not isinstance(spec, str) or not spec.strip():
        problems.append("'spec' must be a non-empty string (absolute path to the spec file)")

    # gate: required, non-empty object whose values are all JSON booleans.
    gate = m.get("gate")
    if not isinstance(gate, dict) or not gate:
        problems.append("'gate' must be a non-empty JSON object of boolean flags")
    else:
        non_bool = [k for k, v in gate.items() if not isinstance(v, bool)]
        if non_bool:
            problems.append(
                "every 'gate' flag must be a JSON boolean (true/false); "
                "not boolean: " + ", ".join(sorted(non_bool))
            )

    # openQuestions: optional (defaults to []); if present must be a list of
    # {q: str, resolved: bool}.
    oq = m.get("openQuestions", [])
    if not isinstance(oq, list):
        problems.append("'openQuestions' must be a JSON array")
    else:
        for i, q in enumerate(oq):
            if not isinstance(q, dict):
                problems.append(f"openQuestions[{i}] must be an object with 'q' and 'resolved'")
                continue
            if not isinstance(q.get("q"), str) or not q.get("q").strip():
                problems.append(f"openQuestions[{i}].q must be a non-empty string")
            if not isinstance(q.get("resolved"), bool):
                problems.append(f"openQuestions[{i}].resolved must be a JSON boolean (true/false)")

    return problems


def commit_pending(spec_path: str) -> bool:
    """True if the ready spec still has uncommitted changes in a git repo.
    Fail-OPEN: a missing helper, a non-repo path, or any git error returns False,
    so an unenforceable commit never traps the user (unlike the readiness gate,
    which fails SAFE). The spec is committed via the visible helper in the skill's
    Handoff; this hook only *guarantees it happened*."""
    if spec_git is None:
        return False
    try:
        return bool(spec_git.spec_needs_commit(spec_path))
    except Exception:  # noqa: BLE001 — never trap a user over a git hiccup
        return False


def evaluate(marker_path: str, marker: dict):
    """Validated-ledger path: enforce readiness or block with specifics."""
    problems = validate_ledger(marker)
    if problems:
        reject_ledger(marker_path, problems)
        return

    spec_path = marker["spec"].strip()
    gate = marker["gate"]
    open_questions = marker.get("openQuestions", []) or []

    failures = []

    # 1. Gate-flag attestations (validated as booleans above).
    unmet = sorted(name for name, ok in gate.items() if ok is not True)
    if unmet:
        failures.append("Readiness gate flags still unmet: " + ", ".join(unmet))

    # 2. Open-question ledger fully resolved.
    unresolved = [q["q"] for q in open_questions if q.get("resolved") is not True]
    if unresolved:
        preview = "; ".join(unresolved[:5])
        more = f" (+{len(unresolved) - 5} more)" if len(unresolved) > 5 else ""
        failures.append(f"Unresolved open questions: {preview}{more}")

    # 3. Mechanical scan of the spec for not-finalized markers.
    #    An unreadable spec path is an AI mistake (wrong path) -> block, don't allow.
    try:
        with open(spec_path, "r", errors="replace") as f:
            hits = []
            for n, line in enumerate(f, 1):
                if NOT_DONE_RE.search(line):
                    hits.append(f"L{n}: {line.strip()[:80]}")
                    if len(hits) >= 10:
                        break
    except OSError:
        reject_ledger(
            marker_path,
            [f"'spec' path is not a readable file: {spec_path!r} — set it to the correct absolute path"],
        )
        return
    if hits:
        failures.append(
            "Spec still contains not-finalized markers "
            "(TODO/TBD/FIXME/???/'to be decided'/'open question'/'NEEDS CLARIFICATION'):\n  "
            + "\n  ".join(hits)
        )

    # 3b. Deterministic AC-integrity: no duplicate AC ids or leftover conflict markers.
    #     refine edits ACs heavily, so this is the highest-risk place for them. Only the
    #     *blocking* problems (conflict markers, duplicate AC numbers) hold the stop;
    #     dangling `AC-N` references are advisory (a bare AC-N may reference a sibling
    #     spec) and don't block here. Fail-SAFE — a real blocking defect blocks; fail-OPEN
    #     only when the check can't run (missing helper, unreadable, or no AC section to
    #     check → check() returns (None, None)), so it never traps a user.
    if spec_consistency is not None:
        try:
            blocking, _advisory = spec_consistency.check(
                open(spec_path, "r", errors="replace").read())
        except OSError:
            blocking = None
        if blocking:
            failures.append(
                "Acceptance-Criteria integrity problems — fix before finalizing:\n  "
                + "\n  ".join(blocking[:10])
            )

    # Ready on the verification gate — but also require the ready spec be
    # committed (scoped to the spec file) before releasing the stop. The model
    # commits via the helper in Handoff; here we only enforce it happened. Keep
    # the ledger if it hasn't, so the loop continues for one more (commit) step.
    if not failures:
        if commit_pending(spec_path):
            block(
                "refine-spec: the spec is implementation-ready but not yet committed. "
                "Commit it — scoped to the spec file only — then stop:\n\n"
                '  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_git.py" commit '
                + spec_path
                + ' "docs(spec): ready for implementation"\n\n'
                "This commits ONLY the spec file — never `git add -A`, never other staged "
                "changes, never a push. If the user redirected to unrelated work, delete the "
                "ledger and stop instead."
            )
            return
        remove(marker_path)
        allow()
        return

    # Not ready: force another pass.
    block(
        "refine-spec loop is still active and the spec is not implementation-"
        "ready. Do NOT stop — run another refinement pass to clear these:\n\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\n\nThen update the ledger at "
        + marker_path
        + " (set the gate flags true / mark questions resolved) and try again.\n"
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

    marker_path = f"/tmp/claude-refine-spec-{session_id}.json"

    # Fast path: no active refine-spec run -> don't touch this stop.
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
