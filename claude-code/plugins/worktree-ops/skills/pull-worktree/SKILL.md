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

- **Dirty tree** → don't rebase/merge onto it. Offer (via `AskUserQuestion`) to **stash → integrate → pop** automatically, or to commit/abort. If they choose stash, do all three steps so they don't have to.
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

## 4. Conflicts

If it stops on conflicts: show them (`git status`), resolve in the worktree, `git add` each, then `git rebase --continue` (or commit the merge). Always offer the clean escape hatch — `git rebase --abort` (or `git merge --abort`) restores the pre-pull state.

## 5. Report and finish the loop

State the new ahead/behind. A rebase rewrites history, so if the branch was already pushed it needs `git push --force-with-lease` — **offer to do that push now** so it isn't a forgotten manual step. Mention `/worktree-ops:list-worktrees` to confirm.
