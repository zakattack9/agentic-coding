#!/usr/bin/env bash
# Safely remove a git worktree (and optionally delete its branch).
# Refuses on uncommitted changes or unpushed commits unless --force.
#
# Usage: wt-teardown.sh <path-or-slug> [--delete-branch] [--force]
set -euo pipefail

target=""; delete_branch=0; force=0
for arg in "$@"; do
  case "$arg" in
    --delete-branch) delete_branch=1 ;;
    --force) force=1 ;;
    -*) echo "error: unknown flag $arg" >&2; exit 2 ;;
    *) if [[ -z "$target" ]]; then target="$arg"; else echo "error: unexpected arg $arg" >&2; exit 2; fi ;;
  esac
done
[[ -z "$target" ]] && {
  echo "error: usage: wt-teardown.sh <path-or-slug> [--delete-branch] [--force]" >&2; exit 2; }

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "error: not inside a git repository" >&2; exit 2; }
git_common=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)
main_root=$(dirname "$git_common")

# Resolve target to an absolute, physical worktree path (match git's own output).
if [[ -d "$target" ]]; then
  wt_path=$(cd "$target" && pwd -P)
else
  cand="$main_root/.claude/worktrees/$target"
  [[ -d "$cand" ]] || { echo "error: no such worktree path: $cand" >&2; exit 2; }
  wt_path=$(cd "$cand" && pwd -P)
fi

if [[ "$wt_path" == "$main_root" ]]; then
  echo "error: refusing to remove the main worktree" >&2; exit 2
fi
if ! git worktree list --porcelain | grep -qxF "worktree $wt_path"; then
  echo "error: $wt_path is not a registered git worktree" >&2; exit 2
fi

branch=$(git -C "$wt_path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# Safety checks (skipped with --force).
if [[ "$force" -ne 1 ]]; then
  if [[ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null)" ]]; then
    echo "refuse: worktree has uncommitted changes or untracked files. Commit/stash, or re-run with --force." >&2
    exit 1
  fi
  if up=$(git -C "$wt_path" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null); then
    ahead=$(git -C "$wt_path" rev-list --count "@{u}"..HEAD 2>/dev/null || echo 0)
    if [[ "$ahead" -gt 0 ]]; then
      echo "refuse: branch '$branch' has $ahead commit(s) not pushed to $up. Push them, or re-run with --force." >&2
      exit 1
    fi
  else
    echo "warn: branch '$branch' has no upstream; cannot confirm its commits are pushed." >&2
    if [[ "$delete_branch" -eq 1 ]]; then
      echo "refuse: would delete unpushed branch '$branch'. Push it first, or re-run with --force." >&2
      exit 1
    fi
  fi
fi

# Run git from the main checkout so we never try to remove our own cwd.
cd "$main_root"

if [[ "$force" -eq 1 ]]; then
  git worktree remove --force "$wt_path"
else
  git worktree remove "$wt_path"
fi
echo "info: removed worktree $wt_path" >&2

if [[ "$delete_branch" -eq 1 && -n "$branch" && "$branch" != "HEAD" ]]; then
  if [[ "$force" -eq 1 ]]; then
    if git branch -D "$branch"; then echo "info: deleted branch $branch" >&2; else echo "warn: could not delete branch $branch" >&2; fi
  else
    if git branch -d "$branch" 2>/dev/null; then
      echo "info: deleted branch $branch" >&2
    else
      echo "warn: branch '$branch' not fully merged; left in place. Re-run with --force to delete it." >&2
    fi
  fi
fi

git worktree prune
echo "done"
