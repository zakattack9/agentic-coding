---
name: pull-worktree
description: Pull the latest changes from a base branch into the current worktree — fetch, then rebase (or merge) this worktree's branch onto the newest origin/main (or any branch you name), guiding conflict resolution. Use when the user says a worktree/branch is "behind", wants to "pull in the latest", "catch up", "update", "sync", or "rebase onto main/develop" a worktree before continuing or opening a PR. The base to pull from is configurable, unlike anything native.
argument-hint: [--from <branch>] [--merge]
allowed-tools: Bash(git *), AskUserQuestion
---

# pull-worktree

Bring the current worktree's branch up to date with a base branch. "Pull" here means **integrate the base branch INTO this worktree** (not `git pull` of the branch's own upstream). Run it from inside the worktree.

## 1. Pre-flight

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
```

- **Already mid-rebase/merge?** If `git status` shows a rebase or merge already in progress, do **not** start a new one — surface it and ask whether to continue (resolve per §4) or abort (`git rebase --abort` / `git merge --abort`) first.
- **Dirty tree** → don't rebase/merge onto it. Offer (via `AskUserQuestion`) to **stash → integrate → pop** automatically, or to commit/abort. If they choose stash, do all three; if the final `git stash pop` itself conflicts, resolve it under the same §4 policy and don't drop the stash until the tree is clean.
- **Pick the source branch:** use `--from <branch>` if given (e.g. `--from develop`); otherwise default to `origin/HEAD` → `origin/main` / `origin/master`.

## 2. Fetch and assess

```bash
git fetch origin
git rev-list --left-right --count <source>...HEAD   # output: <behind>  <ahead>
```

If behind is `0`, report "already up to date" and stop. Otherwise state how far ahead/behind it is.

## 3. Integrate

Default to **rebase** (linear history on a feature branch):

```bash
git rebase <source>
```

Use **merge** instead (`git merge <source>`) when `--merge` is passed, or when the branch is already pushed and shared. If unclear, ask with `AskUserQuestion`.

## 4. Conflicts — never guess

A rebase replays commits one at a time, so conflicts can recur. **Repeat** this loop until the rebase finishes: show the conflicts (`git status`, then the conflicting hunks), resolve, `git add` each, `git rebase --continue` (or commit, for a merge).

**Resolution policy — defer to the user unless it is obvious and safe.** Resolve a conflict yourself ONLY when the correct result is unambiguous and low-risk, e.g.:

- non-overlapping additions on each side (keep both),
- pure import/whitespace/ordering differences,
- one side is a strict superset of the other,
- a regenerated lockfile or build artifact (re-generate it).

For anything else — overlapping edits to the same logic, deletion vs. edit, or any case where the intended behavior isn't clear — **stop and ask the user with `AskUserQuestion`**, showing the file, the conflicting "ours" vs. "theirs" hunks, and the choices (keep ours / keep theirs / combine / I'll describe how). **Never assume which side is correct.** When in doubt, treat it as ambiguous and ask.

Always offer the clean escape hatch — `git rebase --abort` (or `git merge --abort`) restores the pre-pull state.

## 5. Report and finish the loop

State the new ahead/behind. A rebase rewrites history, so if the branch was already pushed it needs `git push --force-with-lease` — **offer to do that push now** so it isn't a forgotten manual step. Mention `/worktree-ops:list-worktrees` to confirm.
