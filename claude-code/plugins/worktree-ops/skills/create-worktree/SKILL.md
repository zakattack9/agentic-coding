---
name: create-worktree
description: Create an isolated git worktree for a new task and switch this session straight into it — no restart, no manual cd. Branches fresh from the latest origin base, copies gitignored env files (.worktreeinclude), runs an optional per-project setup script, and can seed from a GitHub issue or PR. Use when the user wants to "create/start/spin up a worktree", "work on this in a separate branch/checkout", kick off isolated/parallel work for a feature or bugfix, or start a task from an issue or PR without disturbing the current checkout.
argument-hint: [task description | #issue | #PR | branch-name] [--base <ref>]
allowed-tools: Bash(git *), Bash(gh *), Bash(bash *), Read, AskUserQuestion, EnterWorktree
---

# create-worktree

Create a worktree and **flip this session into it in one step**, using Claude Code's native worktree support so you also get `.worktreeinclude` copying, `worktree.baseRef`, and native cleanup for free.

## 1. Decide the name and source

Derive a short, meaningful **kebab-case slug** from what the user is building (e.g. `fix-login-redirect`, `add-csv-export`). Never use generic names like `worktree-1`. Resolve the source:

- **Plain task / branch name** → use the slug directly.
- **GitHub issue** (`#123` / issue URL) → `gh issue view <n> --json number,title`, then slug = `issue-<n>-<short-title-slug>`. Remember the issue to reference in the PR later.
- **GitHub PR** (`#123` / PR URL) → this is the existing-worktree path (see 2b).
- **`--base <ref>`** → only meaningful via the fallback in 2c; native creation uses the `worktree.baseRef` setting.

If it's ambiguous (new vs. existing branch, which base), ask with `AskUserQuestion` first.

## 2. Create and enter

### 2a. New branch — preferred (native, auto-flips)

Call the **`EnterWorktree` tool with `name: <slug>`**. Native Claude Code then, in one atomic step: creates the worktree under `.claude/worktrees/<slug>/`, branches per the `worktree.baseRef` setting (default: fresh from `origin/<default>`), copies `.worktreeinclude` files, fires any `WorktreeCreate` hook, **and switches this session's working directory into the worktree**. The branch is typically named `worktree-<slug>`.

> `EnterWorktree` with `name` is rejected if the session is *already* inside a worktree. If so, either `ExitWorktree` (action `keep`) back to the main checkout first, or create the new branch with `git worktree add` and enter it via `path` (2b).

### 2b. From a PR, or entering an existing worktree

```bash
git fetch origin
git worktree add ".claude/worktrees/pr-<n>" -b "<headRefName>" --track "origin/<headRefName>"
```

Then call `EnterWorktree` with `path: .claude/worktrees/pr-<n>` to flip in. (Cross-fork PRs may need the fork added as a remote first — say so if the fetch fails.)

### 2c. Fallback when `EnterWorktree` is unavailable (e.g. `-p`/non-interactive)

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-create.sh" "<slug>" [base-ref]
```

It prints the worktree path on its last stdout line. The session can't auto-flip here — tell the user to `cd <path>` or run `claude --worktree <slug>`.

## 3. Per-project setup (opt-in, deterministic)

Once inside the worktree, run the setup helper. It deterministically runs `.claude/worktree-setup.sh` if the project has one (install deps, init a local DB, etc.) and is a safe no-op otherwise — so this step always behaves the same:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-run-optin.sh" setup
```

Don't hand-run an install instead. (Setup is scoped to user-initiated creation on purpose — it deliberately does *not* run for every subagent-isolation worktree.)

## 4. Report

Confirm: you're now working in the worktree, the branch, the base it was cut from, env files copied, and whether setup ran. When done, `/worktree-ops:merge-worktree` ships it and cleans up.
