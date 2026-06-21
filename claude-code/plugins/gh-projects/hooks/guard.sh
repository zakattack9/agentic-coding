#!/usr/bin/env bash
# PreToolUse guard for gh-projects — deterministic, skill-scoped enforcement.
#
# Wired into the start-issue / create-pr skills' frontmatter (PreToolUse,
# matcher: "Bash"), so it is active ONLY while those skills run — never global.
# It hard-blocks, regardless of what the model attempts on a Bash call:
#   1) a squash merge of a PR (no-squash is policy; commits are preserved)
#   2) a PROD deploy / publish action when checks are not provably green
#      (a prod tag/deploy must follow a green CI run, not race ahead of it)
#
# Reads the PreToolUse event JSON on stdin. FAIL-OPEN by design: unexpected
# input, missing jq, or a command that doesn't match a guarded pattern -> ALLOW
# (exit 0), so an unrelated session is never bricked. Only an explicit violation
# BLOCKS (exit 2, message on stderr shown to the model). It prints no token or
# secret. It uses only POSIX/GNU-portable constructs (no BSD-only flags).
set -euo pipefail

# --- read the event; fail-open on anything unreadable ---
input=$(cat 2>/dev/null || true)
[ -z "$input" ] && exit 0

# Extract the Bash command. Prefer jq; fall back to a tolerant grep/sed parse so
# the guard still functions where jq is absent (then fail-open if we can't read).
cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
fi
if [ -z "$cmd" ]; then
  # Best-effort extraction of "command":"..." without jq. If this fails to find a
  # command, we fail-open below.
  cmd=$(printf '%s' "$input" \
    | grep -oE '"command"[[:space:]]*:[[:space:]]*"([^"\\]|\\.)*"' 2>/dev/null \
    | head -n1 \
    | sed -E 's/^"command"[[:space:]]*:[[:space:]]*"//; s/"$//' \
    | sed -E 's/\\"/"/g; s/\\\\/\\/g' \
    || true)
fi
[ -z "$cmd" ] && exit 0

# --- Rule 1: no squash merges (no-squash is enforced by the free repo setting; the
#     guard stops a hand-typed --squash from slipping past it) ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+merge' \
   && printf '%s' "$cmd" | grep -Eq -- '(^|[[:space:]])--squash([[:space:]=]|$)'; then
  echo "gh-projects policy: '--squash' is not allowed — preserve commits with 'gh pr merge --merge' (or --rebase). no-squash is the configured repo merge method." >&2
  exit 2
fi

# --- Rule 2: no PROD deploy / publish action without provably-green checks ---
# A "prod action" is a manual prod-deploy dispatch or a release publish that
# fronts a prod cut. We only consider a command a prod action when it BOTH
# targets a deploy/release surface AND carries a prod signal — keeping the guard
# narrow so unrelated `gh` calls fall through (fail-open).
is_prod_action=0
# gh workflow run / gh api ...dispatches that name a prod/production/deploy workflow
if printf '%s' "$cmd" | grep -Eiq 'gh[[:space:]]+workflow[[:space:]]+run' \
   && printf '%s' "$cmd" | grep -Eiq '(deploy[-_]?prod|prod[-_]?deploy|production|release)'; then
  is_prod_action=1
fi
# gh api workflow dispatch hitting a prod/deploy workflow
if printf '%s' "$cmd" | grep -Eiq 'gh[[:space:]]+api' \
   && printf '%s' "$cmd" | grep -Eiq 'workflows?/[^[:space:]]*(deploy|prod|release)[^[:space:]]*/dispatches'; then
  is_prod_action=1
fi
# publishing a GitHub Release that fronts a prod cut (board-status normally does
# this; a hand-run `gh release create --target ... ` prod publish is guarded)
if printf '%s' "$cmd" | grep -Eiq 'gh[[:space:]]+release[[:space:]]+(create|edit)' \
   && printf '%s' "$cmd" | grep -Eiq '(deploy[-_]?prod|prod[-_]?deploy|production)'; then
  is_prod_action=1
fi

if [ "$is_prod_action" -eq 1 ]; then
  # Allow ONLY when the same command provably gates on green checks. Accept an
  # explicit green-gate signal anywhere in the command (e.g. a preceding
  # `gh pr checks --watch && ...`, a `--checks green`/`CHECKS_GREEN=1` marker, or
  # `gh run watch ... && ...` chained ahead of the prod step). Absent any such
  # proof, BLOCK.
  green_gated=0
  if printf '%s' "$cmd" | grep -Eiq 'gh[[:space:]]+pr[[:space:]]+checks'; then
    green_gated=1
  fi
  if printf '%s' "$cmd" | grep -Eiq 'gh[[:space:]]+run[[:space:]]+watch'; then
    green_gated=1
  fi
  if printf '%s' "$cmd" | grep -Eiq '(^|[[:space:]])CHECKS_GREEN=(1|true)([[:space:]]|$)'; then
    green_gated=1
  fi
  if printf '%s' "$cmd" | grep -Eiq -- '--checks[[:space:]=]+green'; then
    green_gated=1
  fi

  if [ "$green_gated" -eq 0 ]; then
    {
      echo "gh-projects policy: blocked — a PROD deploy/release action must follow provably-green checks."
      echo "Confirm CI is green first (e.g. 'gh pr checks <pr> --watch && ...' or 'gh run watch <id> && ...'),"
      echo "then re-issue the prod step chained after that gate. Do not dispatch prod ahead of a green CI run."
    } >&2
    exit 2
  fi
fi

# Nothing matched a guarded pattern (or a guarded action was green-gated) -> ALLOW.
exit 0
