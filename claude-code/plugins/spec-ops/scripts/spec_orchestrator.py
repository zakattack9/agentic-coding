#!/usr/bin/env python3
"""spec_orchestrator.py — the state engine for the orchestrate-spec skill.

orchestrate-spec runs the whole spec workflow — write → refine → launch → build →
verify — in one main session. This module turns that pipeline into a deterministic,
resumable state machine so the skill's prose holds no control flow: the ordered
stages, each stage's status, the spec path, the from/to range, the next action, and
an abort flag all live in a session-keyed state file, NOT the conversation.

State file (session-keyed, the same /tmp + session-key convention the other
spec-ops hooks use):
  /tmp/claude-orchestrate-spec-<session_id>.json

This module is the single source of truth for that file and for stage completeness.
It is used by both:
  - the ``orchestrate-spec`` skill (the model in the MAIN session): drives the run
    via ``init`` / ``advance`` / ``abort`` / ``status`` / ``check``.
  - ``stop_orchestrate_spec.py`` (the Stop hook): imports this module and re-uses
    ``gate`` / ``recompute`` to block turn-end until the next in-range stage's
    ARTIFACT actually exists (never self-reported status).

Stage completeness is judged from artifact GROUND TRUTH, never trusted status:
  - ``write`` / ``refine`` → the spec is committed (``spec_git.spec_needs_commit`` is
    False); the orchestrator-recorded status only disambiguates *which* committed
    stage we are at (both end in a clean commit of the same file).
  - ``verify``            → the drift baseline exists, its ``verifiedAtSHA`` equals the
    current HEAD, and NO criterion's verdict is ``contradicted`` — a bar deliberately
    stricter than verify-spec's own gate (located/read via ``drift_baseline``, keyed
    on the spec's abspath, so it is resolved through the helper, never recomputed).
  - ``launch`` / ``build`` → transient (no standalone repo artifact); status-tracked,
    and the always-following ``verify`` artifact is the real downstream gate.

Same-session resume: re-invoking in the same session reloads the persisted
ACTIVE state and continues at the first incomplete in-range stage (artifact-present
stages are already ``done`` in the persisted status, so they are skipped). A state
file from a COMPLETED or ABORTED run — or for a different spec — is replaced by a
fresh run.

CLI (each verb prints a line and exits with a distinct code; session id from the
trailing arg or $CLAUDE_SESSION_ID):
  init <spec> [from] [to] [session]   → create/replace, or resume an active run
  status [session]                    → print the state JSON (exit 12 if no run)
  advance <stage> [session]           → mark a stage done, recompute next
  abort [session]                     → set the abort flag (Stop hook then releases)
  check [session]                     → evaluate the gate from artifact ground truth
                                        0 complete · 10 incomplete (next printed)
                                        11 aborted · 12 no active run · 2 usage
"""

import json
import os
import sys
from pathlib import Path

# Sibling helpers in this same scripts/ dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import spec_git
except Exception:  # noqa: BLE001 — a missing helper must degrade, never crash
    spec_git = None

# The drift baseline lives in the verify-spec skill dir; it is the artifact that
# proves the verify stage is complete. Guarded so a missing helper can't crash the
# engine (the hook fails open in that case).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "verify-spec"))
try:
    import drift_baseline
except Exception:  # noqa: BLE001
    drift_baseline = None

STATE_PREFIX = "/tmp/claude-orchestrate-spec-"

# The full pipeline, in order. from/to selects a contiguous slice.
STAGES = ["write", "refine", "launch", "build", "verify"]

# Stage statuses.
PENDING, DONE, SKIPPED = "pending", "done", "skipped"

# Run states.
ACTIVE, COMPLETE, ABORTED = "active", "complete", "aborted"


# ----------------------------------------------------------------------------- IO

def state_path(session_id: str) -> str:
    """The /tmp state file for a session. Deterministic, so the skill (writer) and
    the Stop hook (reader) always resolve the same file."""
    return f"{STATE_PREFIX}{session_id}.json"


def canonical_spec(spec_path: str) -> str:
    """The single canonical absolute spec path passed to every script:
    symlinks resolved once up front, so the per-script /tmp keys stay self-consistent
    (drift baseline keys on abspath, amendments on realpath — both agree on a
    realpath input). realpath also makes abspath a no-op fixpoint."""
    return os.path.realpath(spec_path)


def load_state(session_id: str):
    """The parsed state for a session, or None if absent/unreadable/malformed."""
    try:
        with open(state_path(session_id)) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_state(state: dict) -> str:
    """Write the state file for state['session']. Returns the path, or None on error."""
    path = state_path(state["session"])
    try:
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        return None
    return path


# ------------------------------------------------------------------- range / gate

def in_range(state: dict):
    """The ordered list of stages within [from, to] (inclusive)."""
    stages = state.get("stages", STAGES)
    try:
        lo = stages.index(state["from"])
        hi = stages.index(state["to"])
    except (ValueError, KeyError):
        return list(stages)
    return stages[lo : hi + 1]


def needs_commit(spec_path: str) -> bool:
    """True iff the spec has uncommitted changes in a git repo. Fail-OPEN (False)
    when the helper is missing or git errors, so an unenforceable commit never traps."""
    if spec_git is None:
        return False
    try:
        return bool(spec_git.spec_needs_commit(spec_path))
    except Exception:  # noqa: BLE001
        return False


def verify_artifact_ok(spec_path: str) -> bool:
    """The verify stage's ground-truth artifact: the drift baseline exists,
    its verifiedAtSHA equals the current HEAD, and NO criterion is ``contradicted``
    (stricter than verify-spec's own gate). Resolved through drift_baseline, never by
    recomputing the abspath key. False (incomplete) on any missing piece."""
    if drift_baseline is None:
        return False
    try:
        baseline = drift_baseline.load_baseline(spec_path)
        if not isinstance(baseline, dict):
            return False
        head = drift_baseline.current_head_sha()
        if not head or baseline.get("verifiedAtSHA") != head:
            return False
        for c in baseline.get("criteria", []) or []:
            if isinstance(c, dict) and c.get("verdict") == "contradicted":
                return False
        return True
    except Exception:  # noqa: BLE001
        return False


def stage_complete(stage: str, state: dict) -> bool:
    """Is one stage complete, judged from artifact ground truth?"""
    status = state.get("status", {})
    if status.get(stage) == SKIPPED:
        return True
    spec = state["spec"]
    if stage == "verify":
        return verify_artifact_ok(spec)  # pure ground truth — status irrelevant
    if stage in ("write", "refine"):
        # Both end in a clean commit of the same file; the recorded status says which
        # stage we are at, the commit (artifact) proves its side-effect landed.
        return status.get(stage) == DONE and not needs_commit(spec)
    # launch / build: transient, no repo artifact — verify is the downstream gate.
    return status.get(stage) == DONE


def gate(state: dict):
    """The first incomplete in-range stage (the next action), or None if every
    in-range stage is complete. Pure artifact evaluation — the engine's core."""
    for stage in in_range(state):
        if not stage_complete(stage, state):
            return stage
    return None


def artifact_hint(stage: str) -> str:
    """A one-line reminder of the artifact a stage must produce, for block messages."""
    return {
        "write": "commit the DRAFT spec (spec_git.py commit) so it has no uncommitted changes",
        "refine": "commit the READY spec (spec_git.py commit) so it has no uncommitted changes",
        "launch": "emit the launch-spec driver brief, then mark it done (advance launch)",
        "build": "run the build⇄verify Workflow, then mark it done (advance build)",
        "verify": "materialize the drift baseline at HEAD with zero contradicted "
        "(drift_baseline.py write), so verify is complete",
    }.get(stage, f"complete stage {stage}")


def recompute(state: dict) -> dict:
    """Refresh runState + next from the abort flag and the gate. Mutates in place."""
    if state.get("abort"):
        state["runState"] = ABORTED
        state["next"] = None
        return state
    nxt = gate(state)
    if nxt is None:
        state["runState"] = COMPLETE
        state["next"] = None
    else:
        state["runState"] = ACTIVE
        state["next"] = nxt
    return state


# ----------------------------------------------------- loud-fallback no-progress

def bump_no_progress(state: dict, stage) -> int:
    """Count CONSECUTIVE blocks on the same gating stage with no artifact progress.
    Resets when the gating stage changes (real progress). Returns the new count."""
    np = state.get("noProgress") or {}
    if np.get("stage") == stage:
        np = {"stage": stage, "count": int(np.get("count", 0)) + 1}
    else:
        np = {"stage": stage, "count": 1}
    state["noProgress"] = np
    return np["count"]


# ------------------------------------------------------------------- run lifecycle

def make_state(session_id: str, spec: str, frm: str, to: str) -> dict:
    """A fresh state: every in-range stage PENDING, out-of-range stages SKIPPED."""
    lo, hi = STAGES.index(frm), STAGES.index(to)
    status = {}
    for i, s in enumerate(STAGES):
        status[s] = PENDING if lo <= i <= hi else SKIPPED
    state = {
        "session": session_id,
        "spec": spec,
        "stages": list(STAGES),
        "from": frm,
        "to": to,
        "status": status,
        "next": None,
        "abort": False,
        "runState": ACTIVE,
        "noProgress": {"stage": None, "count": 0},
    }
    return recompute(state)


def init(session_id: str, spec_arg: str, frm: str, to: str):
    """Create/replace, or resume an active same-session run."""
    spec = canonical_spec(spec_arg)
    existing = load_state(session_id)
    # Resume ONLY an active run for the same spec; a completed/aborted/different-spec
    # state is replaced by a fresh run.
    if (
        isinstance(existing, dict)
        and existing.get("runState") == ACTIVE
        and not existing.get("abort")
        and canonical_spec(existing.get("spec", "")) == spec
    ):
        recompute(existing)  # continue at the first incomplete in-range stage
        path = save_state(existing)
        return existing, path, "resumed"
    state = make_state(session_id, spec, frm, to)
    path = save_state(state)
    return state, path, "fresh"


def advance(session_id: str, stage: str):
    """Mark a stage done and recompute. The orchestrator calls this AFTER a stage's
    side-effect landed (e.g. the commit, or the baseline write); the hook still
    re-checks the artifact, so a premature advance cannot fake a gate."""
    state = load_state(session_id)
    if state is None:
        return None, "no active run"
    if stage not in state.get("status", {}):
        return state, f"unknown stage {stage!r}"
    state["status"][stage] = DONE
    recompute(state)
    save_state(state)
    return state, "advanced"


def abort(session_id: str):
    """Set the abort flag. The Stop hook then allows the turn to end."""
    state = load_state(session_id)
    if state is None:
        return None, "no active run"
    state["abort"] = True
    recompute(state)
    save_state(state)
    return state, "aborted"


# --------------------------------------------------------------------------- CLI

def _session(argv, idx) -> str:
    """Session id from a trailing CLI arg, else $CLAUDE_SESSION_ID."""
    if len(argv) > idx and argv[idx].strip():
        return argv[idx].strip()
    return os.environ.get("CLAUDE_SESSION_ID", "").strip()


def main(argv):
    if len(argv) >= 3 and argv[1] == "init":
        spec = argv[2]
        frm = argv[3] if len(argv) > 3 and argv[3] in STAGES else "write"
        to = argv[4] if len(argv) > 4 and argv[4] in STAGES else "verify"
        if STAGES.index(frm) > STAGES.index(to):
            sys.stderr.write(f"from {frm!r} is after to {to!r}\n")
            return 2
        session = _session(argv, 5)
        if not session:
            sys.stderr.write("no session id (pass as last arg or set CLAUDE_SESSION_ID)\n")
            return 2
        state, path, how = init(session, spec, frm, to)
        print(f"{how}: {path}")
        print(json.dumps(state, indent=2))
        return 0

    if len(argv) >= 2 and argv[1] == "status":
        session = _session(argv, 2)
        state = load_state(session) if session else None
        if state is None:
            print("no-run")
            return 12
        print(json.dumps(state, indent=2))
        return 0

    if len(argv) >= 3 and argv[1] == "advance":
        session = _session(argv, 3)
        state, detail = advance(session, argv[2])
        print(detail)
        return 0 if state is not None else 12

    if len(argv) >= 2 and argv[1] == "abort":
        session = _session(argv, 2)
        state, detail = abort(session)
        print(detail)
        return 0 if state is not None else 12

    if len(argv) >= 2 and argv[1] == "check":
        session = _session(argv, 2)
        state = load_state(session) if session else None
        if state is None:
            print("no-run")
            return 12
        recompute(state)
        save_state(state)
        if state.get("abort"):
            print("aborted")
            return 11
        if state["runState"] == COMPLETE:
            print("complete")
            return 0
        nxt = state["next"]
        print(f"next:{nxt}")
        print(artifact_hint(nxt))
        return 10

    sys.stderr.write(
        "usage: spec_orchestrator.py "
        "{init <spec> [from] [to] [session] | status [session] | "
        "advance <stage> [session] | abort [session] | check [session]}\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
