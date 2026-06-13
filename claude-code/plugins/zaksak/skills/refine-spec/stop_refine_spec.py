#!/usr/bin/env python3
"""stop_refine_spec.py — Stop hook for the refine-spec skill.

Deterministically enforces the refine-spec review loop: while a run is active,
Claude cannot end its turn until the spec is actually ready.

Activates ONLY when a session-scoped marker exists at
  /tmp/claude-refine-spec-<session_id>.json
so normal sessions (and other skills) are never affected. The marker is written
by the skill at the start of, and during, a refine-spec run, and removed here
once the readiness gate passes.

Readiness = ALL of:
  1. Every gate flag in the marker is true   (agent attestation per dimension)
  2. Every open question in the marker is resolved   (agent ledger)
  3. The spec file contains no leftover not-finalized markers   (mechanical scan)

Safety valves (so a run can never hard-trap a user who walked away):
  - Freshness: the marker's file mtime must be recent. If the agent stops
    refreshing it (stuck or abandoned), it goes stale and the loop releases.
  - Any read/parse error releases rather than blocks.
  - The block reason tells Claude how to bail out if the user has moved on.

Input:  JSON on stdin (hook payload; uses `session_id`).
Output: nothing / {"decision":"approve"} to allow stop;
        {"decision":"block","reason":...} to force another pass.
"""

import json
import os
import re
import sys
import time

# Marker is considered abandoned/stuck if not rewritten within this window.
# Long enough for a heavy pass (parallel verification subagents + user Q&A),
# short enough that a leaked marker frees the session on its own.
STALE_SECONDS = 45 * 60

# Heuristic "this spec is not finalized" markers. Case-insensitive.
# Deliberately excludes "- [ ]" — finalized specs legitimately end with an
# implementation Checklist of unchecked boxes (see the write-spec format).
NOT_DONE_PATTERNS = [
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\?\?\?",
    r"to be (?:determined|decided|defined)",
    r"\bdecide later\b",
    r"open question",
]
NOT_DONE_RE = re.compile("|".join(NOT_DONE_PATTERNS), re.IGNORECASE)


def allow():
    """Permit the stop (default behavior)."""
    sys.exit(0)


def block(reason: str):
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def main():
    # Read the hook payload; on any trouble, never block.
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

    # Fast path: no active refine-spec run → don't touch this stop.
    if not os.path.isfile(marker_path):
        allow()
        return

    # Stale marker (agent stopped refreshing it) → release and clean up.
    try:
        if time.time() - os.path.getmtime(marker_path) > STALE_SECONDS:
            remove(marker_path)
            allow()
            return
    except OSError:
        allow()
        return

    # Parse the ledger; corruption releases rather than traps.
    try:
        with open(marker_path, "r") as f:
            marker = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        remove(marker_path)
        allow()
        return

    spec_path = str(marker.get("spec", "")).strip()
    gate = marker.get("gate", {}) or {}
    open_questions = marker.get("openQuestions", []) or []

    failures = []

    # 1. Gate-flag attestations the agent must explicitly set true.
    unmet = [name for name, ok in gate.items() if ok is not True]
    if not gate:
        unmet = ["gate is empty — populate it"]
    if unmet:
        failures.append("Readiness gate flags still unmet: " + ", ".join(sorted(unmet)))

    # 2. Open-question ledger must be fully resolved.
    unresolved = [
        str(q.get("q", "?")) for q in open_questions
        if isinstance(q, dict) and q.get("resolved") is not True
    ]
    if unresolved:
        preview = "; ".join(unresolved[:5])
        more = f" (+{len(unresolved) - 5} more)" if len(unresolved) > 5 else ""
        failures.append(f"Unresolved open questions: {preview}{more}")

    # 3. Mechanical scan of the spec for not-finalized markers.
    if spec_path:
        try:
            with open(spec_path, "r", errors="replace") as f:
                hits = []
                for n, line in enumerate(f, 1):
                    if NOT_DONE_RE.search(line):
                        hits.append(f"L{n}: {line.strip()[:80]}")
                        if len(hits) >= 10:
                            break
            if hits:
                failures.append(
                    "Spec still contains not-finalized markers "
                    "(TODO/TBD/FIXME/???/'to be decided'/'open question'):\n  "
                    + "\n  ".join(hits)
                )
        except OSError:
            # Can't read the spec — don't trap the session over it.
            remove(marker_path)
            allow()
            return

    # Ready: tear down the marker and let Claude stop.
    if not failures:
        remove(marker_path)
        allow()
        return

    # Not ready: force another pass.
    reason = (
        "refine-spec loop is still active and the spec is not implementation-"
        "ready. Do NOT stop — run another refinement pass to clear these:\n\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\n\nAfter resolving them, update the ledger at "
        + marker_path
        + " (set the gate flags true / mark questions resolved) and try again.\n"
        + "If the user has redirected to unrelated work, delete that marker file "
        + "and stop instead of continuing to refine."
    )
    block(reason)


if __name__ == "__main__":
    main()
