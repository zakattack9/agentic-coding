#!/usr/bin/env bash
# Summary of all git worktrees in the repo.
# Offline by default (no fetch): ahead/behind is vs the last-known base ref.
# Pass --fetch to fetch origin first for live ahead/behind.
#
# Usage: wt-status.sh [--fetch] [base-ref]
# stdout: a BASE line, a header, then one TSV row per worktree:
#         cur  name  branch  ahead  behind  dirty  pr  path
# (cur = "*" for the worktree this session is currently in)
set -uo pipefail

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "error: not inside a git repository" >&2; exit 2; }

do_fetch=0
base_ref=""
for arg in "$@"; do
  case "$arg" in
    --fetch) do_fetch=1 ;;
    -*) echo "warn: unknown flag $arg" >&2 ;;
    *) base_ref="$arg" ;;
  esac
done

if [[ "$do_fetch" -eq 1 ]] && git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin || echo "warn: 'git fetch origin' failed; showing last-known refs" >&2
fi

if [[ -z "$base_ref" ]]; then
  if oh=$(git symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null); then base_ref="${oh#refs/remotes/}"
  elif git show-ref --verify --quiet refs/remotes/origin/main; then base_ref="origin/main"
  elif git show-ref --verify --quiet refs/remotes/origin/master; then base_ref="origin/master"
  elif git show-ref --verify --quiet refs/heads/main; then base_ref="main"
  elif git show-ref --verify --quiet refs/heads/master; then base_ref="master"
  else base_ref="$(git rev-parse --abbrev-ref HEAD)"; fi
fi

# Physical path of the worktree this session is in, to mark the current row.
cur_root=""
if top=$(git rev-parse --show-toplevel 2>/dev/null); then cur_root=$(cd "$top" && pwd -P); fi

have_gh=0
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then have_gh=1; fi

printf 'BASE\t%s\n' "$base_ref"
printf '#cur\tname\tbranch\tahead\tbehind\tdirty\tpr\tpath\n'

emit() {
  local path="$1" branch="$2"
  local cur name ahead behind dirty pr counts
  cur=" "; [[ -n "$cur_root" && "$path" == "$cur_root" ]] && cur="*"
  name="$(basename "$path")"
  ahead="?"; behind="?"
  if counts=$(git -C "$path" rev-list --left-right --count "$base_ref"...HEAD 2>/dev/null); then
    behind="$(printf '%s' "$counts" | awk '{print $1}')"
    ahead="$(printf '%s' "$counts" | awk '{print $2}')"
  fi
  dirty="$(git -C "$path" status --porcelain 2>/dev/null | grep -c . || true)"
  pr="-"
  if [[ "$have_gh" -eq 1 ]]; then
    pr="$( (cd "$path" && gh pr view --json number,state -q '"#\(.number) \(.state|ascii_downcase)"') 2>/dev/null || echo "-")"
    [[ -z "$pr" ]] && pr="-"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$cur" "$name" "$branch" "$ahead" "$behind" "$dirty" "$pr" "$path"
}

path=""; branch=""
while IFS= read -r line; do
  if [[ "$line" == worktree\ * ]]; then
    path="${line#worktree }"
  elif [[ "$line" == branch\ * ]]; then
    branch="${line#branch }"; branch="${branch#refs/heads/}"
  elif [[ "$line" == "detached" ]]; then
    branch="(detached)"
  elif [[ -z "$line" ]]; then
    [[ -n "$path" ]] && emit "$path" "$branch"
    path=""; branch=""
  fi
done < <(git worktree list --porcelain; printf '\n')
