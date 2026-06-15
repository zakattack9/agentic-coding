---
name: merge-worktree
description: Finish a worktree — commit any remaining work, push, open or update its pull request, optionally merge into a target branch once checks are green, run an optional teardown script, then remove the worktree and switch this session back to the main checkout. Use when the user says a task is "done", wants to "finish", "wrap up", "ship", "merge", "merge and clean up", or "tear down" a worktree, or to close out parallel work and reclaim the checkout. The merge target is configurable; pairs with create-worktree.
argument-hint: [--into <branch>] [--no-merge] [--keep-branch]
allowed-tools: Bash(git *), Bash(gh *), Bash(bash *), AskUserQuestion, ExitWorktree
---

# merge-worktree

Take a worktree from "work is done" to "merged, cleaned up, and back on main" — with as few manual steps as possible. Run it from inside the worktree.

## 1. Confirm scope

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
```

Confirm this is the worktree/branch to finish, and whether to **merge now** or only open/update the PR and stop (`--no-merge`). The merge **target** is `--into <branch>` if given, else the PR's base (default `main`). Ask with `AskUserQuestion` if anything is unclear.

## 2. Commit & push

- If dirty, review and commit per the repo's conventions. If the user has a preferred commit flow (e.g. `/commit-commands:commit-push-pr`), defer to it for steps 2–3.
- Push, setting upstream: `git push -u origin HEAD`.

## 3. Pull request

- No PR yet → `gh pr create --fill --base <into>` (or draft a title/body from the commits and any seeding issue).
- PR exists → the push updated it; show URL + status: `gh pr view --json number,url,state,statusCheckRollup`.

## 4. Merge (unless `--no-merge`)

- Verify mergeable — approved, checks green, no conflicts. If checks are still running, report and ask whether to wait or stop here.
- Merge into the target: `gh pr merge --squash --delete-branch` (it merges into the PR's base; set `--base`/the PR base to `<into>` earlier). `--delete-branch` removes the remote branch.

## 5. Teardown script (opt-in)

Before removing the worktree, if a **`.claude/worktree-archive.sh`** exists at the repo root, run it to clean up resources that live *outside* the worktree (local DBs, Docker, caches):

```bash
bash .claude/worktree-archive.sh
```

## 6. Remove and return to main — preferred (native, auto-flips back)

If **this session created/entered the worktree via `EnterWorktree`**, finish with the **`ExitWorktree` tool**: it removes the worktree + branch *and switches the session back to the main checkout* in one step.

- After a confirmed merge, pass `action: "remove"` with `discard_changes: true` (a squash-merge leaves the local branch looking "unmerged," so the guard would otherwise refuse — but the work is safely on the remote).
- Abandoning instead → `action: "remove"` without `discard_changes`; if it lists uncommitted/unmerged work, relay that and confirm before retrying with `discard_changes: true`. Never discard silently.
- `--keep-branch` or "I might come back" → `action: "keep"` (returns to main, leaves the worktree on disk).

### Fallback — worktree from a prior session or created via raw git

`ExitWorktree` only touches worktrees this session entered. Otherwise use the helper (it refuses on dirty/unpushed work unless `--force`); run it from the main checkout:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-teardown.sh" "<path-or-slug>" --delete-branch        # unmerged: guards apply
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-teardown.sh" "<path-or-slug>" --force --delete-branch  # after a confirmed merge
```

## 7. Report

Summarize: commits pushed, PR URL + state, whether it merged into `<into>`, whether the teardown script ran, and that the worktree + branch were removed and the session is back on the main checkout (or why anything was kept).
