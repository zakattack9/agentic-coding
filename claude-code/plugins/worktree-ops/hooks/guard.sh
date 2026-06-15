#!/usr/bin/env bash
# PreToolUse guard for worktree-ops — deterministic enforcement, regardless of
# what the model attempts on a Bash call:
#   1) never squash-merge a PR
#   2) never commit / continue a rebase|merge while conflicts are unresolved
#
# Reads the PreToolUse event JSON on stdin. Fail-open: unexpected input or
# non-matching commands -> allow (exit 0). Only explicit violations block
# (exit 2, message on stderr shown to the model).
set -uo pipefail

input=$(cat 2>/dev/null || true)
[[ -z "$input" ]] && exit 0

cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
fi
[[ -z "$cmd" ]] && exit 0

# --- Rule 1: no squash merges ---
if printf '%s' "$cmd" | grep -Eq 'gh[[:space:]]+pr[[:space:]]+merge' \
   && printf '%s' "$cmd" | grep -Eq -- '(^|[[:space:]])--squash([[:space:]=]|$)'; then
  echo "worktree-ops policy: '--squash' is not allowed — preserve commits with 'gh pr merge --merge' (or --rebase)." >&2
  exit 2
fi

# --- Rule 2: no committing/continuing with unresolved conflicts ---
is_finalize=0
printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+commit([[:space:]]|$)' && is_finalize=1
printf '%s' "$cmd" | grep -Eq 'git[[:space:]]+(rebase|merge|cherry-pick|revert)[[:space:]]+--continue' && is_finalize=1

if [[ "$is_finalize" -eq 1 ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  unmerged=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
  markers=$( { git diff --cached --check 2>/dev/null; git diff --check 2>/dev/null; } | grep 'conflict marker' || true )
  if [[ -n "$unmerged" || -n "$markers" ]]; then
    {
      echo "worktree-ops policy: blocked — unresolved merge conflicts present."
      if [[ -n "$unmerged" ]]; then
        echo "Unmerged files:"
        printf '%s\n' "$unmerged" | sed 's/^/  - /'
      fi
      [[ -n "$markers" ]] && echo "Leftover conflict markers detected in the diff."
      echo "Resolve every conflict (ask the user when ambiguous), 'git add' them, then retry. Do not commit a partial or guessed resolution."
    } >&2
    exit 2
  fi
fi

exit 0
