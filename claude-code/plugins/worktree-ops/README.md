# worktree-ops

Git worktree workflow for running parallel Claude Code sessions — inspired by how [Conductor](https://conductor.build) maps each workspace to a git worktree, but built to **wrap Claude Code's native worktree support, not duplicate it**.

## Design principle

Claude Code already does the hard parts natively, in-session: the `EnterWorktree` / `ExitWorktree` tools create, enter, and remove worktrees (with a dirty/unmerged safety guard); `.worktreeinclude` copies gitignored env files; `worktree.baseRef` controls the base; clean worktrees auto-clean on exit. So these skills **call the native tools** and add only the lifecycle pieces native has no command for:

- intent-triggered, one-step **create + auto-flip** into a worktree (with naming + issue/PR seeding + an opt-in setup script),
- a **cross-worktree dashboard** (no native equivalent),
- **pull/merge onto a chosen base/target branch** (no native equivalent),
- a **finish flow** that merges, runs an opt-in teardown script, removes the worktree, and returns you to main.

## Skills

| Skill | Does |
|-------|------|
| `/worktree-ops:create-worktree` | Create a worktree via native `EnterWorktree` and **switch this session into it**. Fresh base, `.worktreeinclude` copy, optional GitHub issue/PR seed, runs `.claude/worktree-setup.sh` if present. |
| `/worktree-ops:list-worktrees` | Read-only dashboard of every worktree: branch, ahead/behind base, dirty count, PR status, with the current worktree marked. `--fetch` for live numbers. |
| `/worktree-ops:pull-worktree` | Fetch and rebase (or `--merge`) the worktree's branch onto a base branch (`--from <branch>`, default `origin/HEAD`), guiding conflicts. |
| `/worktree-ops:merge-worktree` | Commit → push → open/update PR → merge into `--into <branch>` → run `.claude/worktree-archive.sh` → remove the worktree and return to main (via native `ExitWorktree`). |

## Opt-in project conventions

Both are no-ops if the file is absent, and run **only** for user-initiated skills (never for every subagent-isolation worktree):

- **`.claude/worktree-setup.sh`** — run by `create-worktree` inside a new worktree (install deps, init a local DB, generate files).
- **`.claude/worktree-archive.sh`** — run by `merge-worktree` before teardown (tear down external resources: local DBs, Docker, caches).
- **`.worktreeinclude`** — native convention; gitignored files (e.g. `.env`, `.env.local`) to copy into each new worktree.

## Helper scripts (`scripts/`, via `${CLAUDE_PLUGIN_ROOT}`)

The skills prefer native tools; these back the fallback / read-only paths:

- `wt-status.sh [--fetch] [base-ref]` — offline TSV summary of all worktrees (powers `list-worktrees`).
- `wt-create.sh <slug> [base-ref]` — raw-git worktree creation for non-interactive (`-p`) sessions where `EnterWorktree` isn't available.
- `wt-teardown.sh <path-or-slug> [--delete-branch] [--force]` — guarded removal (refuses on dirty/unpushed unless `--force`) for worktrees from a prior session that `ExitWorktree` won't touch.

## Roadmap

- **worktree-fanout** — decompose a task and dispatch N parallel agents, each in its own worktree (built on subagent `isolation: worktree`). Planned after the four skills above are validated in real use.
