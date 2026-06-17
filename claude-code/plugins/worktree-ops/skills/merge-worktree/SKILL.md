---
name: merge-worktree
description: Finish a worktree — commit any remaining work, push, open or update its pull request, optionally merge into a target branch once checks are green, run an optional teardown script, then remove the worktree and switch this session back to the main checkout. Use when the user says a task is "done", wants to "finish", "wrap up", "ship", "merge", "merge and clean up", or "tear down" a worktree, or to close out parallel work and reclaim the checkout. The merge target is configurable; pairs with create-worktree.
# model: claude-sonnet-4-6
# effort: medium
argument-hint: [--into <branch>] [--no-merge] [--keep-branch]
allowed-tools: Bash(git *), Bash(gh *), Bash(bash *), AskUserQuestion, ExitWorktree
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh"
---

# merge-worktree

Take a worktree from "work is done" to "merged, cleaned up, and back on main" — with as few manual steps as possible. Run it from inside the worktree.

## Inputs & confirmation

At any step, if a required input is missing or the safe path is ambiguous, **stop and use `AskUserQuestion`** before acting — don't assume a default that pushes, merges, or deletes. Confirm when unclear:

- **which** worktree/branch to finish;
- **merge now vs. `--no-merge`**;
- the **target** branch (`--into`), when not obvious;
- whether to **wait** on pending checks or stop;
- **keep vs. delete** the branch, and abandon vs. merged teardown (§6).

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

Check readiness first if needed (`gh pr view --json number,url,state,statusCheckRollup`; if checks are still running, ask whether to wait). Then use the deterministic merge helper — it **refuses to squash**, sets the target base, merges (merge commit by default; `--rebase` for linear history), and **confirms the PR actually reached `MERGED`**, exiting non-zero otherwise:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-merge.sh" [--into <branch>] [--rebase] [--keep-branch]
```

Act on the exit code:

- **0** = merged and confirmed → proceed to teardown.
- **3** = PR conflicts with its base → run `/worktree-ops:pull-worktree --from <into>` to integrate + resolve (it asks you about anything ambiguous), push, then retry.
- **any other non-zero** (checks red, branch protection, not approved, not merged) → **stop and report; do not tear down.**

(`--squash` is also blocked by this skill's `PreToolUse` guard, so it can't slip in by hand either.)

## 5. Teardown script (opt-in, deterministic)

Before removing the worktree, run the archive helper. It deterministically runs `.claude/worktree-archive.sh` if the project has one (tear down external resources: local DBs, Docker, caches) and is a no-op otherwise:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-run-optin.sh" archive
```

## 6. Remove and return to main — preferred (native, auto-flips back)

**Only run teardown if §4 confirmed the merge (`wt-merge.sh` exited 0), or the user is deliberately abandoning the worktree.** Never tear down after a failed/blocked merge.

If **this session created/entered the worktree via `EnterWorktree`**, finish with the **`ExitWorktree` tool**: it removes the worktree + branch *and switches the session back to the main checkout* in one step.

- After a confirmed merge (state `MERGED` from §4), pass `action: "remove"` with `discard_changes: true`. The merge happened on the remote, so the local branch can still look "unmerged" until you fetch — the guard would otherwise refuse, but the work is safely on the remote.
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
