---
name: pull-worktree
description: Pull the latest changes from a base branch into the current worktree — fetch, then rebase (or merge) this worktree's branch onto the newest origin/main (or any branch you name), guiding conflict resolution. Use when the user says a worktree/branch is "behind", wants to "pull in the latest", "catch up", "update", "sync", or "rebase onto main/develop" a worktree before continuing or opening a PR. The base to pull from is configurable, unlike anything native.
model: opus
effort: low
# model: claude-sonnet-4-6
# effort: medium
argument-hint: [--from <branch>] [--merge]
allowed-tools: Bash(git *), Bash(bash *), AskUserQuestion
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh"
---

# pull-worktree

Bring the current worktree's branch up to date with a base branch. "Pull" here means **integrate the base branch INTO this worktree** (not `git pull` of the branch's own upstream). Run it from inside the worktree.

## Inputs & confirmation

At any step, if a required input is missing or the safe path is ambiguous, **stop and use `AskUserQuestion`** before acting — don't assume a default that rewrites history. Confirm when unclear:

- the **source branch** to pull from — if `--from` is absent and the default base can't be resolved, ask;
- **rebase vs. merge** (§2);
- how to handle a **dirty tree** — stash / commit / abort (§1);
- any non-obvious **conflict** resolution (§3).

## 1. Pre-flight (deterministic)

Run the helper — it reports state and never changes history:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-pull-preflight.sh" [--from <branch>]
```

It prints `branch=`, `inprogress=`, `dirty=`, `source=`, `fetched=`, `ahead=`, `behind=` (plus any `note=`). Act on it:

- **`inprogress` set (exit code 3)** → a rebase/merge is already underway; don't start another. Help finish it (resolve per §3) or abort (`git rebase --abort` / `git merge --abort`), then stop.
- **`dirty` > 0** → don't integrate onto a dirty tree. Offer (via `AskUserQuestion`) to **stash → integrate → pop**, or commit/abort. If stashing, do all three; if the final `git stash pop` conflicts, resolve it under the §3 policy and don't drop the stash until clean.
- **`behind` = 0** → already up to date; report and stop.
- Otherwise state the ahead/behind and continue, using `source` as the base.

## 2. Integrate

Default to **rebase** (linear history on a feature branch):

```bash
git rebase <source>
```

Use **merge** instead (`git merge <source>`) when `--merge` is passed, or the branch is already pushed and shared. If unclear, ask with `AskUserQuestion`.

## 3. Conflicts — never guess

A rebase replays commits one at a time, so conflicts can recur. List them deterministically (complete set + hunks):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-conflicts.sh"
```

**Repeat** until the rebase finishes: review the reported conflicts, resolve, `git add` each, `git rebase --continue` (or commit, for a merge).

**Resolution policy — defer to the user unless it is obvious and safe.** Resolve a conflict yourself ONLY when the result is unambiguous and low-risk:

- non-overlapping additions on each side (keep both),
- pure import/whitespace/ordering differences,
- one side a strict superset of the other,
- a regenerated lockfile or build artifact (re-generate it).

For anything else — overlapping edits to the same logic, deletion vs. edit, or any unclear intent — **stop and ask with `AskUserQuestion`**, showing the file and the "ours" vs. "theirs" hunks and the choices (keep ours / keep theirs / combine / I'll describe). **Never assume which side is correct;** when in doubt, treat it as ambiguous and ask.

> **Enforced, not just requested:** while this skill is active, its `PreToolUse` guard **blocks any `git commit` / `--continue` while unresolved conflicts or leftover conflict markers remain**, so a partial or guessed resolution cannot be committed. `git rebase --abort` / `git merge --abort` is always the clean escape hatch.

## 4. Report and finish the loop

State the new ahead/behind. A rebase rewrites history, so if the branch was already pushed it needs `git push --force-with-lease` — **offer to do that push now** so it isn't a forgotten step. Mention `/worktree-ops:list-worktrees` to confirm.
