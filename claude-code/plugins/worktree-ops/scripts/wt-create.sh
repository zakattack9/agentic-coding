#!/usr/bin/env bash
# Create a git worktree under .claude/worktrees/<slug>, following Claude Code
# conventions:
#   - new branch <slug> based on a fresh remote base (origin/HEAD) by default
#   - ensures .claude/worktrees/ is gitignored in the main checkout
#   - copies gitignored files matching .worktreeinclude (default: .env*)
#
# Usage: wt-create.sh <slug> [base-ref]
# stdout: the created worktree path (single final line). Progress -> stderr.
set -euo pipefail

slug="${1:-}"
base_ref="${2:-}"

if [[ -z "$slug" ]]; then
  echo "error: usage: wt-create.sh <slug> [base-ref]" >&2
  exit 2
fi
if [[ ! "$slug" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "error: invalid slug '$slug' (allowed: letters, digits, and . _ / -)" >&2
  exit 2
fi

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "error: not inside a git repository" >&2; exit 2; }

git_common=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)
main_root=$(dirname "$git_common")
wt_dir="$main_root/.claude/worktrees/$slug"

if [[ -e "$wt_dir" ]]; then
  echo "error: worktree path already exists: $wt_dir" >&2; exit 2
fi
if git show-ref --verify --quiet "refs/heads/$slug"; then
  echo "error: branch '$slug' already exists; choose another name or check it out" >&2
  exit 2
fi

# Resolve the base ref (fresh remote default).
if [[ -z "$base_ref" ]]; then
  if git remote get-url origin >/dev/null 2>&1; then
    git fetch --quiet origin || echo "warn: 'git fetch origin' failed; using last-known refs" >&2
    if oh=$(git symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null); then
      base_ref="${oh#refs/remotes/}"
    elif git show-ref --verify --quiet refs/remotes/origin/main; then
      base_ref="origin/main"
    elif git show-ref --verify --quiet refs/remotes/origin/master; then
      base_ref="origin/master"
    fi
  fi
  if [[ -z "$base_ref" ]]; then
    base_ref="HEAD"
    echo "warn: no remote base found; branching from local HEAD" >&2
  fi
fi

mkdir -p "$main_root/.claude/worktrees"
git worktree add -b "$slug" "$wt_dir" "$base_ref" >&2

# Branching off a remote-tracking ref (e.g. origin/main) makes git set that as the
# new branch's upstream. A fresh feature branch should have none until its first
# push, so unset it — this keeps push -u and "is it pushed?" checks correct.
git -C "$wt_dir" branch --unset-upstream >/dev/null 2>&1 || true

# Ensure .claude/worktrees/ is gitignored in the main checkout (idempotent).
# A .gitignore hiccup must never abort an otherwise-successful creation.
bash "$(dirname "${BASH_SOURCE[0]}")/wt-ensure-gitignore.sh" "$main_root" || true

# Copy gitignored files matching .worktreeinclude (default .env*) into the worktree.
patterns=()
include_file="$main_root/.worktreeinclude"
if [[ -f "$include_file" ]]; then
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    pattern="${pattern%$'\r'}"
    [[ -z "${pattern// }" ]] && continue
    [[ "$pattern" =~ ^[[:space:]]*# ]] && continue
    patterns+=("$pattern")
  done < "$include_file"
else
  patterns=(".env*")
fi

copied=0
for pattern in "${patterns[@]}"; do
  while IFS= read -r -d '' rel; do
    src="$main_root/$rel"
    [[ -e "$src" ]] || continue
    dest="$wt_dir/$rel"
    mkdir -p "$(dirname "$dest")"
    cp -R "$src" "$dest"
    copied=$((copied + 1))
  done < <(git -C "$main_root" ls-files -z --others --ignored --exclude-standard -- "$pattern" 2>/dev/null || true)
done
echo "info: copied $copied gitignored file(s) into the worktree" >&2

# Machine-readable result: the worktree path.
echo "$wt_dir"
