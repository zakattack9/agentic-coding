#!/usr/bin/env bash
# Deterministic pre-flight for pull-worktree. Read-only except an optional fetch.
# Usage: wt-pull-preflight.sh [--from <branch>] [--no-fetch]
# Prints key=value lines for the skill to act on.
# Exit 0 normally; 3 if a rebase/merge/cherry-pick is already in progress.
set -uo pipefail

from=""; do_fetch=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) from="${2:-}"; shift 2 ;;
    --no-fetch) do_fetch=0; shift ;;
    *) echo "warn: unknown arg $1" >&2; shift ;;
  esac
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "error: not a git repo" >&2; exit 2; }

echo "branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

gitdir=$(git rev-parse --git-dir 2>/dev/null)
inprogress=""
[ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ] && inprogress="rebase"
[ -f "$gitdir/MERGE_HEAD" ] && inprogress="${inprogress:+$inprogress+}merge"
[ -f "$gitdir/CHERRY_PICK_HEAD" ] && inprogress="${inprogress:+$inprogress+}cherry-pick"
if [[ -n "$inprogress" ]]; then
  echo "inprogress=$inprogress"
  echo "note=a $inprogress is already in progress; resolve or abort it before starting a new pull"
  exit 3
fi
echo "inprogress="

echo "dirty=$(git status --porcelain 2>/dev/null | grep -c . || true)"

src="$from"
if [[ -z "$src" ]]; then
  if oh=$(git symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null); then src="${oh#refs/remotes/}"
  elif git show-ref --verify --quiet refs/remotes/origin/main; then src="origin/main"
  elif git show-ref --verify --quiet refs/remotes/origin/master; then src="origin/master"
  elif git show-ref --verify --quiet refs/heads/main; then src="main"
  else src="origin/HEAD"; fi
fi
echo "source=$src"

if [[ "$do_fetch" -eq 1 ]] && git remote get-url origin >/dev/null 2>&1; then
  if git fetch --quiet origin; then echo "fetched=1"; else echo "fetched=0"; echo "note=git fetch failed; counts may be stale"; fi
else
  echo "fetched=0"
fi

if counts=$(git rev-list --left-right --count "$src"...HEAD 2>/dev/null); then
  echo "behind=$(printf '%s' "$counts" | awk '{print $1}')"
  echo "ahead=$(printf '%s' "$counts" | awk '{print $2}')"
else
  echo "behind=?"; echo "ahead=?"
  echo "note=could not resolve source ref '$src'"
fi
