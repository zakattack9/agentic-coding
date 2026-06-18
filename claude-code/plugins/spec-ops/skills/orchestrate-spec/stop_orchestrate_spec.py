#!/usr/bin/env python3
"""stop_orchestrate_spec.py — Stop hook for the orchestrate-spec skill.

Turns the orchestrate-spec pipeline (write → refine → launch → build → verify) into
a self-enforcing state machine: while a run is active, Claude cannot end its turn
until the next in-range stage's ARTIFACT actually exists. It re-injects which stage
to run next, so the orchestrator can't quietly stop mid-pipeline.

Activates ONLY when a session-keyed state file exists at
  /tmp/claude-orchestrate-spec-<session_id>.json
so normal sessions (and the other spec-ops skills) are never affected. That file is
written by ``spec_orchestrator.py`` — the deterministic state engine this hook shares
— at ``init`` and on every ``advance`` / ``abort`` / ``check``.

Completeness is judged from artifact GROUND TRUTH, never self-reported status
(``spec_orchestrator.stage_complete`` / ``gate``):
  - write / refine → the spec is committed (``spec_git.spec_needs_commit`` is False);
  - verify         → the drift baseline exists, its ``verifiedAtSHA`` equals the
    current HEAD, and NO criterion is ``contradicted`` — a bar stricter than
    verify-spec's own gate (located/read via ``drift_baseline``, never re-keyed);
  - launch / build → transient; the always-following verify artifact is the real gate.

FAIL-OPEN, deliberately (AC-27): unlike the model-authored-ledger hooks (refine /
verify), this state file is SCRIPT-written and trustworthy, and the load-bearing
gate (the verify artifact) is pure ground truth — so when the hook cannot tell a run
is active, or hits its own error, it RELEASES rather than risk wedging an unrelated
session. It never blocks on a malformed state; it blocks only on a clean,
artifact-incomplete, in-range pipeline.

Escape valves (so enforcement can never permanently trap someone):
  - Abort: when the orchestrator sets the abort flag (``spec_orchestrator.py abort``,
    on the user's explicit request), the hook allows the stop (AC-25).
  - Loud fallback: after FALLBACK_MAX consecutive blocks on the SAME stage with no
    artifact progress (default 3 — an independent counter from the build-loop cap),
    it stops blocking and surfaces the stall (AC-26).
  - Freshness: a state file older than STALE_SECONDS (an abandoned run) is removed
    and released.
  - The user can interrupt the turn at any time; the block reason says to abort if
    the user has redirected to unrelated work.

Input:  JSON on stdin (hook payload; uses ``session_id``).
Output: nothing to allow the stop; {"decision":"block","reason":...} to force the
        next stage.
"""

import json
import os
import sys
import time
from pathlib import Path

# The state engine is the single source of truth for the state file + stage gate.
# Guarded: a missing engine must FAIL OPEN (release), never wedge the session.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
try:
    import spec_orchestrator as engine
except Exception:  # noqa: BLE001
    engine = None

# An orchestrate run can sit idle through a long build⇄verify Workflow without the
# state file being rewritten; keep the abandoned-run window generous so a real run
# is never wrongly released, while a leaked state still frees the session eventually.
STALE_SECONDS = 2 * 60 * 60

# Consecutive no-progress blocks on one stage before the loud fallback releases.
# Independent of the build loop's max-iteration cap (AC-14); default 3 (AC-26).
FALLBACK_MAX = 3


def allow():
    """Permit the stop (default behavior). No output == allow."""
    sys.exit(0)


def block(reason: str):
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def release_with_notice(message: str):
    """Allow the stop (no `decision: block`) but SURFACE a message to the user — the
    loud-fallback path (AC-26): stop blocking, yet make the stall visible. Emits the
    documented `systemMessage` channel and also writes to stderr so the notice lands
    regardless of how the harness renders an allowed Stop hook."""
    sys.stderr.write(message + "\n")
    json.dump({"systemMessage": message}, sys.stdout)
    sys.exit(0)


def evaluate(state: dict):
    """Active, readable state: enforce the pipeline gate or release."""
    # Abort wins immediately (AC-25).
    if state.get("abort"):
        allow()
        return

    engine.recompute(state)

    # All in-range stages complete → the pipeline is done; let the turn end.
    if state.get("runState") == engine.COMPLETE or state.get("next") is None:
        engine.save_state(state)
        allow()
        return

    next_stage = state["next"]

    # Loud fallback: bound consecutive no-progress blocks on the same stage (AC-26).
    count = engine.bump_no_progress(state, next_stage)
    engine.save_state(state)
    if count > FALLBACK_MAX:
        release_with_notice(
            "orchestrate-spec STALL: stage '" + next_stage + "' has not progressed "
            "after " + str(FALLBACK_MAX) + " attempts — its artifact still does not "
            "exist (" + engine.artifact_hint(next_stage) + "). The Stop gate is "
            "releasing so you are not trapped. Surface this stall to the user and "
            "decide together: fix the blocker and re-run the stage, or abort the run "
            '(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_orchestrator.py" abort).'
        )
        # release_with_notice() exits; nothing below runs.
        return

    # Artifact-incomplete, in-range stage → re-inject the next action (AC-23).
    block(
        "orchestrate-spec pipeline is still active — do NOT stop. The next in-range "
        "stage's artifact does not yet exist.\n\n"
        "  Next stage: " + next_stage + "\n"
        "  Needed:     " + engine.artifact_hint(next_stage) + "\n\n"
        "Run that stage (delegating per the skill's lanes — but YOU own every user "
        "question in the main session), drive its side-effect from the main session, "
        "then mark it done:\n"
        '  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_orchestrator.py" advance '
        + next_stage
        + "\n\nIf the user has redirected to unrelated work, abort instead:\n"
        '  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_orchestrator.py" abort'
    )


def main():
    # FAIL OPEN throughout (AC-27): if we cannot positively confirm an active,
    # readable run with an incomplete in-range stage, we RELEASE.
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()
        return

    if engine is None:  # state engine unavailable → can't gate → release
        allow()
        return

    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        allow()
        return

    state_file = engine.state_path(session_id)

    # Fast path: no active orchestrate run → don't touch this stop.
    if not os.path.isfile(state_file):
        allow()
        return

    # Abandoned run (state not rewritten in a long time) → remove and release.
    try:
        if time.time() - os.path.getmtime(state_file) > STALE_SECONDS:
            try:
                os.remove(state_file)
            except OSError:
                pass
            allow()
            return
    except OSError:
        allow()
        return

    # State is SCRIPT-written, so a malformed/unreadable one is an anomaly, not an AI
    # gate-evasion — release rather than wedge (the opposite of the ledger hooks).
    state = engine.load_state(session_id)
    if not isinstance(state, dict) or not state.get("stages"):
        allow()
        return

    try:
        evaluate(state)
    except SystemExit:
        raise  # allow()/block() use sys.exit — let it through
    except Exception:  # noqa: BLE001 — own error → fail open, never wedge (AC-27)
        allow()


if __name__ == "__main__":
    main()
