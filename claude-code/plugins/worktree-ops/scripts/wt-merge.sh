#!/usr/bin/env bash
# Deterministically merge the current branch's PR WITHOUT squashing, then
# confirm it actually merged. Chain teardown only on success: wt-merge.sh && ...
#
# Usage: wt-merge.sh [--into <branch>] [--rebase] [--keep-branch]
# Exit: 0 merged & confirmed; 3 PR conflicts with base (resolve first);
#       2 usage/precondition error; 1 merge attempted but not confirmed.
set -uo pipefail

method="merge"   # never squash
into=""; keep_branch=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --into) into="${2:-}"; shift 2 ;;
    --rebase) method="rebase"; shift ;;
    --merge) method="merge"; shift ;;
    --squash) echo "error: squash is not allowed by policy; use --merge or --rebase" >&2; exit 2 ;;
    --keep-branch) keep_branch=1; shift ;;
    *) echo "warn: unknown arg $1" >&2; shift ;;
  esac
done

command -v gh >/dev/null 2>&1 || { echo "error: gh CLI not found" >&2; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "error: gh not authenticated" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "error: not a git repo" >&2; exit 2; }

pr=$(gh pr view --json number,state,mergeable 2>/dev/null) || {
  echo "error: no PR found for the current branch (open one first)" >&2; exit 2; }
num=$(printf '%s' "$pr" | jq -r '.number')
state=$(printf '%s' "$pr" | jq -r '.state')
mergeable=$(printf '%s' "$pr" | jq -r '.mergeable')

if [[ "$state" == "MERGED" ]]; then echo "already merged (PR #$num)"; exit 0; fi
if [[ "$state" != "OPEN" ]]; then echo "error: PR #$num is $state, not OPEN" >&2; exit 2; fi
if [[ "$mergeable" == "CONFLICTING" ]]; then
  echo "error: PR #$num conflicts with its base. Run pull-worktree --from <base>, resolve, push, then retry." >&2
  exit 3
fi

if [[ -n "$into" ]]; then
  gh pr edit "$num" --base "$into" >/dev/null 2>&1 || { echo "error: could not set PR base to '$into'" >&2; exit 2; }
fi

args="--$method"
[[ "$keep_branch" -eq 0 ]] && args="$args --delete-branch"

echo "merging PR #$num with --$method ..." >&2
# shellcheck disable=SC2086
if ! gh pr merge "$num" $args; then
  echo "error: 'gh pr merge' failed for PR #$num (checks, branch protection, approvals, or conflicts). Not merged — do not tear down." >&2
  exit 1
fi

final=$(gh pr view "$num" --json state -q '.state' 2>/dev/null || echo "")
if [[ "$final" == "MERGED" ]]; then
  echo "MERGED: PR #$num"
  exit 0
fi
echo "error: merge did not complete (state=$final). Do not tear down." >&2
exit 1
