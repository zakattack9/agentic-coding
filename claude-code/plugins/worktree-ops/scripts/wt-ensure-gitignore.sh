#!/usr/bin/env bash
# Ensure the main checkout's .gitignore ignores .claude/worktrees/.
#
# Idempotent and safe to run on every worktree creation:
#   - creates .gitignore if the repo doesn't have one
#   - no-ops if the rule is already present
#   - appends cleanly even when the file lacks a trailing newline
#
# The target is always the MAIN checkout's .gitignore, never a linked worktree's.
# Pass the main-checkout root explicitly, or omit it to derive it from git — this
# works even when called from inside a freshly entered worktree.
#
# Usage: wt-ensure-gitignore.sh [main-checkout-root]
# Progress -> stderr. No stdout. Exit 0 on success/no-op, 2 on usage/repo error.
set -euo pipefail

main_root="${1:-}"

# Derive the main checkout root from git when not given. A linked worktree shares
# the main repo's common git dir, so dirname(git-common-dir) is the main root.
if [[ -z "$main_root" ]]; then
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "error: not inside a git repository" >&2; exit 2; }
  git_common=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)
  main_root=$(dirname "$git_common")
fi

if [[ ! -d "$main_root" ]]; then
  echo "error: not a directory: $main_root" >&2; exit 2
fi

gitignore="$main_root/.gitignore"

# Already ignored? Match a line that is exactly .claude/worktrees or .claude/worktrees/.
if [[ -f "$gitignore" ]] && grep -qE '^\.claude/worktrees/?$' "$gitignore"; then
  exit 0
fi

# Append the rule. If the file exists and its last byte isn't a newline, add one
# first so the rule never lands on the end of an existing line.
if [[ -s "$gitignore" && -n "$(tail -c1 "$gitignore" 2>/dev/null)" ]]; then
  printf '\n' >> "$gitignore"
fi
printf '# Claude Code git worktrees\n.claude/worktrees/\n' >> "$gitignore"
echo "info: added .claude/worktrees/ to .gitignore" >&2
