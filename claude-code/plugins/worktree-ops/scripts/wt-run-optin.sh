#!/usr/bin/env bash
# Deterministically run an opt-in per-worktree script if the project has one.
# Looks for .claude/worktree-<name>.sh in the current worktree, then the main
# checkout. No-op (exit 0) when absent, so the calling step always behaves the same.
#
# Usage: wt-run-optin.sh <setup|archive>
set -uo pipefail

name="${1:-}"
[[ -z "$name" ]] && { echo "error: usage: wt-run-optin.sh <name>" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "error: not a git repo" >&2; exit 2; }

top=$(git rev-parse --show-toplevel 2>/dev/null)
common=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)
main_root=$(dirname "$common")

script=""
for cand in "$top/.claude/worktree-$name.sh" "$main_root/.claude/worktree-$name.sh"; do
  if [[ -f "$cand" ]]; then script="$cand"; break; fi
done

if [[ -z "$script" ]]; then
  echo "no .claude/worktree-$name.sh; skipping $name" >&2
  exit 0
fi

echo "running $script ..." >&2
bash "$script"
echo "$name complete" >&2
