#!/usr/bin/env python3
"""subagent_validate.py — SubagentStop hook that deterministically validates a
spec-ops subagent's structured return.

Declared in verify-spec / refine-spec frontmatter as a `SubagentStop` hook with one
argument — the skill name (`verify` or `refine`). When a subagent dispatched during
that skill finishes, this fires, figures out which return contract applies from the
`agent_type`, validates the subagent's final message against it (reusing
validate_return.py's logic — single source of the contract), and on a definite shape
violation BLOCKS (exit 2) so the subagent is forced to re-emit valid JSON. The parent
then never ingests a malformed return.

Routing (skill + agent_type → contract):
  verify + spec-verify-judge  → judge-verify        verify + Explore → grounder-verify
  refine + spec-refine-judge  → judge-refine        refine + Explore → grounder-refine
  anything else               → allow (not ours to validate)

FAIL-OPEN by design — this is a best-effort backstop layered on top of the skill's own
validate_return.py step, NOT the primary gate. It must never trap a subagent or break a
run on anything but a confidently-detected contract violation. It allows (exit 0) when:
  - stdin isn't valid JSON, or has no recognized fields;
  - `stop_hook_active` is true (a prior block already fired — give exactly one re-emit);
  - the payload carries no subagent return text (`last_assistant_message`) — the runtime
    may not expose it; without the content there is nothing to check;
  - the agent_type doesn't map to one of our contracts;
  - no JSON value can be confidently extracted from the return;
  - any unexpected error.
It BLOCKS (exit 2) ONLY when it parsed a JSON value from the return AND that value
definitively violates the contract — echoing the canonical schema + the problems so the
subagent self-corrects.

Input:  JSON on stdin (SubagentStop payload; uses `agent_type`, `last_assistant_message`,
        `stop_hook_active`).
Output: exit 0 (allow the subagent to stop) or exit 2 with a stderr correction (re-emit).
"""

import json
import sys
from pathlib import Path

# Reuse the contract definitions — single source of truth (also the manual CLI).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import validate_return
except Exception:  # noqa: BLE001 — without it we cannot validate; fail-open below
    validate_return = None


# (skill, agent_type-predicate) → contract kind. Judge agent_type may arrive namespaced
# (`spec-ops:spec-verify-judge`) or bare, so match by suffix.
def route(skill, agent_type):
    at = (agent_type or "").strip()
    if skill == "verify":
        if at.endswith("spec-verify-judge"):
            return "judge-verify"
        if at == "Explore":
            return "grounder-verify"
    elif skill == "refine":
        if at.endswith("spec-refine-judge"):
            return "judge-refine"
        if at == "Explore":
            return "grounder-refine"
    return None


def extract_json(text):
    """Best-effort: pull the JSON value out of a subagent's final message. Returns the
    parsed value, or None if nothing parses (in which case the caller fails open — it
    never blocks on a parse failure, only on a parsed-but-invalid value)."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    # Strip a ```json … ``` (or bare ```) fence if present.
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    # Direct parse first.
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to the outermost {...} or [...] span.
    starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    end = max(s.rfind("}"), s.rfind("]"))
    if end <= start:
        return None
    try:
        return json.loads(s[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def allow():
    sys.exit(0)


def block(kind, problems):
    schema = validate_return.SCHEMAS.get(kind, "") if validate_return else ""
    sys.stderr.write(
        f"Your {kind} return is not valid JSON for the contract, so it cannot be trusted. "
        "Do NOT stop yet — re-emit your final message as STRICT JSON (and ONLY that JSON) "
        "exactly matching this schema:\n\n"
        + schema
        + "\n\nProblems:\n"
        + "\n".join(f"- {p}" for p in problems)
        + "\n"
    )
    sys.exit(2)


def main(argv):
    skill = argv[0] if argv else ""
    if skill not in ("verify", "refine") or validate_return is None:
        allow()

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()
        return
    if not isinstance(payload, dict):
        allow()

    # Loop guard: if a prior block already fired this turn, allow (one re-emit only).
    if payload.get("stop_hook_active") is True:
        allow()

    kind = route(skill, payload.get("agent_type"))
    if kind is None:
        allow()  # not a subagent we own a contract for

    # The runtime may not expose the subagent's return text; without it, nothing to check.
    text = payload.get("last_assistant_message")
    data = extract_json(text)
    if data is None:
        allow()  # no confidently-parseable JSON → fail open, never block on a parse miss

    try:
        problems = validate_return.validate(kind, data)
    except Exception:  # noqa: BLE001 — never break a run on a validation bug
        allow()
        return

    if problems:
        block(kind, problems)
    allow()


if __name__ == "__main__":
    main(sys.argv[1:])
