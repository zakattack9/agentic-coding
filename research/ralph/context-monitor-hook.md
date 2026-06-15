# Context Monitor Hook — PostToolUse Implementation

## Problem

Claude Code hooks do not receive `context_window.used_percentage` or any token/context data in their stdin JSON. Only the statusline script gets this data. We need a way to notify Claude during a session when context usage crosses specific thresholds (50%, 60%, 70%, 80%, 90%).

## Approach

Use a **PostToolUse hook** that estimates context usage by parsing the session transcript file. Every hook receives `transcript_path` in its stdin JSON — this is a JSONL file containing the full conversation. By measuring its size and applying a chars-per-token heuristic, we can estimate context usage without any external dependencies.

### Why PostToolUse

- Fires frequently (after every tool call), giving fine-grained monitoring
- Has `additionalContext` support in `hookSpecificOutput`, which injects messages visible to Claude
- Self-contained — no statusline bridge, no temp files, no race conditions
- Inherently parallel-session safe (each session has its own transcript)

### Why not the statusline bridge

The statusline script receives exact `context_window.used_percentage`, so an alternative is to have it write to a temp file that hooks read. This gives precise numbers but:

- Requires two coordinated scripts (statusline writer + hook reader)
- Needs session_id namespacing for parallel Claude sessions (`/tmp/claude-context-${SESSION_ID}.json`)
- Data is one turn stale (statusline updates after assistant messages)
- Orphan temp files accumulate from crashed sessions
- More moving parts = more failure modes

The transcript approach trades precision for simplicity. For threshold-based alerts, the estimate is close enough.

### Why not PreCompact alone

The ralph-loop-plan.md already specifies a `PreCompact` hook for context reminders. PreCompact is valuable but limited:

- Only fires when compaction is about to happen (very late — typically 90%+ usage)
- No earlier warnings at 50%, 60%, 70%, 80%
- The PostToolUse monitor provides graduated alerts across the full range

**Recommendation:** Use both. The PostToolUse monitor for early/mid warnings, PreCompact for the "last chance" reminder.

---

## Implementation

### Hook Script

**File:** `context-monitor.sh`

```bash
#!/bin/bash
# context-monitor.sh — Estimate context usage from transcript size
# PostToolUse hook that alerts Claude at configurable thresholds

INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
EVENT_NAME=$(echo "$INPUT" | jq -r '.hook_event_name')
STATE_FILE="/tmp/claude-context-alerts-${SESSION_ID}"

# Exit early if transcript doesn't exist yet
if [ ! -f "$TRANSCRIPT" ]; then
  exit 0
fi

# --- Estimation ---
# ~4 chars per token is a rough heuristic for mixed code/prose
# Context window is 200k tokens by default, 1M for extended
FILE_SIZE=$(wc -c < "$TRANSCRIPT" | tr -d ' ')
ESTIMATED_TOKENS=$((FILE_SIZE / 4))
CONTEXT_WINDOW=${CLAUDE_CONTEXT_WINDOW:-200000}

PCT=$((ESTIMATED_TOKENS * 100 / CONTEXT_WINDOW))

# Clamp to 0-100
[ "$PCT" -gt 100 ] && PCT=100
[ "$PCT" -lt 0 ] && PCT=0

# --- Threshold alerts ---
# Check thresholds from highest to lowest, alert on the first new crossing
THRESHOLDS="90 80 70 60 50"

for THRESHOLD in $THRESHOLDS; do
  if [ "$PCT" -ge "$THRESHOLD" ]; then
    if ! grep -q "^${THRESHOLD}$" "$STATE_FILE" 2>/dev/null; then
      echo "$THRESHOLD" >> "$STATE_FILE"

      # Build warning message based on severity
      if [ "$THRESHOLD" -ge 90 ]; then
        MSG="CRITICAL: Context window is at ~${PCT}% usage (crossed ${THRESHOLD}% threshold). You are running out of space. Wrap up your current task immediately — commit progress, update progress.txt, and stop. Do NOT start new work."
      elif [ "$THRESHOLD" -ge 70 ]; then
        MSG="WARNING: Context window is at ~${PCT}% usage (crossed ${THRESHOLD}% threshold). Finish your current task and commit soon. Do not start additional tasks."
      else
        MSG="NOTICE: Context window is at ~${PCT}% usage (crossed ${THRESHOLD}% threshold). Be mindful of remaining space. Plan to finish your current task within this session."
      fi

      jq -n --arg msg "$MSG" --arg event "$EVENT_NAME" '{
        "hookSpecificOutput": {
          "hookEventName": $event,
          "additionalContext": $msg
        }
      }'
      exit 0
    fi
  fi
done

exit 0
```

### Hook Configuration

Add to `hooks.json` (or `.claude/settings.json`):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/context-monitor.sh",
            "statusMessage": "Checking context usage..."
          }
        ]
      }
    ]
  }
}
```

### Session Cleanup

Add a `SessionStart` hook to reset the alert state file so thresholds re-arm on each new session:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "rm -f /tmp/claude-context-alerts-$(jq -r '.session_id')"
          }
        ]
      }
    ]
  }
}
```

---

## Accuracy & Tuning

### The 4 chars/token heuristic

The `FILE_SIZE / 4` estimate is intentionally conservative. Real-world ratios vary:

| Content type | Approx chars/token |
|---|---|
| English prose | 4–5 |
| Code (Python, JS) | 3–4 |
| JSON/structured data | 2–3 |
| Mixed (typical session) | ~3.5–4 |

The transcript JSONL includes JSON framing (role, type fields, etc.) which inflates the file size beyond just the message content. This partly offsets the variance — the framing overhead roughly compensates for code's lower chars/token ratio.

**If alerts fire too early:** increase the divisor to 5 or 6.
**If alerts fire too late:** decrease the divisor to 3.

### Extended context window

For models with 1M token context windows, set the environment variable:

```bash
export CLAUDE_CONTEXT_WINDOW=1000000
```

Or detect it from the model name in the hook (the model info is not in hook stdin, but could be persisted by a SessionStart hook).

### What the transcript file contains

The transcript is JSONL — one JSON object per line. It includes:
- System messages, user prompts, assistant responses
- Tool calls and their results
- Cache and compaction markers

After compaction, the transcript file is **not truncated** — old content remains. This means the file size grows monotonically, which can cause over-estimation after compaction. A more sophisticated version could detect compaction markers and reset the baseline.

---

## Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| Estimate, not exact | Alerts may fire 5–15% early or late | Acceptable for threshold-based warnings; tune the divisor |
| Transcript grows after compaction | Over-estimates after `/compact` | Could detect compaction markers; or accept that post-compaction alerts are conservative |
| No model-aware window size | Defaults to 200k | Set `CLAUDE_CONTEXT_WINDOW` env var for extended context |
| Runs on every tool call | Slight overhead per tool invocation | `wc -c` is fast; jq parsing is the bottleneck (~10ms) |
| Temp state file in /tmp | Orphans from killed sessions | Files are tiny; `/tmp` is cleaned on reboot; could add periodic cleanup |

---

## Integration with Ralph Loop

In the ralph plugin's `hooks.json`, wire this alongside the existing hooks:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/block-dangerous-commands.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/context-monitor.sh"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/context-compaction-reminder.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/stop-loop-reminder.sh"
          }
        ]
      }
    ]
  }
}
```

The context monitor complements the existing plan:
- **50–70%**: Gentle notices (from context-monitor.sh)
- **70–90%**: Warnings to wrap up (from context-monitor.sh)
- **~90%+ / compaction**: Last-chance reminder (from context-compaction-reminder.sh)
- **Stop**: Enforce commit + progress update (from stop-loop-reminder.sh)

---

## Open Questions

1. **Should the hook also fire on `UserPromptSubmit`?** This would catch context growth from large user prompts, but adds overhead to every prompt submission.
2. **Should we persist the model's context window size from a SessionStart hook?** The statusline script receives `context_window.context_window_size` — a SessionStart hook could write this to `$CLAUDE_ENV_FILE` so the PostToolUse hook uses the real value instead of a hardcoded default.
3. **Post-compaction reset:** Should the hook detect compaction (via a PreCompact hook writing a marker) and reset its baseline estimate?
