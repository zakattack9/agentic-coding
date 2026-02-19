#!/usr/bin/env python3
"""context_monitor.py — PostToolUse hook that estimates context usage from transcript size.

Fires graduated alerts at 5 thresholds (50%, 60%, 70%, 80%, 90%).
Each threshold fires only once per session via a state file.

Input: JSON on stdin with transcript_path, session_id, hook_event_name
Output: JSON with hookSpecificOutput.additionalContext (when alert fires)
"""

import json
import os
import sys

THRESHOLDS = [90, 80, 70, 60, 50]
CHARS_PER_TOKEN = 4
DEFAULT_CONTEXT_WINDOW = 200_000

MESSAGES = {
    "NOTICE": (
        "Be mindful of remaining space. Plan to finish your current task within this session. "
        "If you discover follow-up work, add new stories to tasks.json — the next iteration will pick them up."
    ),
    "WARNING": (
        "Finish your current task and commit soon. Do not start additional tasks. "
        "If work remains, create new stories in tasks.json for the next iteration and capture any "
        "implementation details or insights in progress.txt so the next iteration has full context."
    ),
    "CRITICAL": (
        "Wrap up immediately. Do NOT start new work. Instead: "
        "(1) create tasks in tasks.json for any remaining work, "
        "(2) write implementation details, insights, and handoff notes to progress.txt, "
        "(3) commit all changes, "
        "(4) stop. The next iteration will continue from where you left off."
    ),
}


def get_severity(threshold: int) -> str:
    if threshold >= 90:
        return "CRITICAL"
    if threshold >= 70:
        return "WARNING"
    return "NOTICE"


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    transcript_path = hook_input.get("transcript_path", "")
    session_id = hook_input.get("session_id", "unknown")

    if not transcript_path or not os.path.isfile(transcript_path):
        sys.exit(0)

    state_file = f"/tmp/claude-context-alerts-{session_id}"

    # Read which thresholds have already fired
    fired = set()
    if os.path.isfile(state_file):
        with open(state_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.isdigit():
                    fired.add(int(line))

    # Estimate context usage
    try:
        file_size = os.path.getsize(transcript_path)
    except OSError:
        sys.exit(0)

    context_window = int(os.environ.get("CLAUDE_CONTEXT_WINDOW", DEFAULT_CONTEXT_WINDOW))
    estimated_tokens = file_size // CHARS_PER_TOKEN
    pct = min(100, max(0, (estimated_tokens * 100) // context_window))

    # Check thresholds from highest to lowest, alert on the first new crossing
    for threshold in THRESHOLDS:
        if pct >= threshold and threshold not in fired:
            # Record this threshold as fired
            with open(state_file, "a") as f:
                f.write(f"{threshold}\n")

            severity = get_severity(threshold)
            msg = f"{severity}: Context window is at ~{pct}% usage (crossed {threshold}% threshold). {MESSAGES[severity]}"

            json.dump({
                "hookSpecificOutput": {
                    "additionalContext": msg
                }
            }, sys.stdout)
            sys.exit(0)

    # No alert needed
    sys.exit(0)


if __name__ == "__main__":
    main()
