# worktree-ops

Git worktree workflow for running parallel Claude Code sessions — inspired by how [Conductor](https://conductor.build) maps each workspace to a git worktree, but built to **wrap Claude Code's native worktree support, not duplicate it**.

## Design principle

Claude Code already does the hard parts natively, in-session: the `EnterWorktree` / `ExitWorktree` tools create, enter, and remove worktrees (with a dirty/unmerged safety guard); `.worktreeinclude` copies gitignored env files; `worktree.baseRef` controls the base; clean worktrees auto-clean on exit. So these skills **call the native tools** and add only the lifecycle pieces native has no command for — and make the important, repeatable steps **deterministic and enforced** via helper scripts and a hook (not just model instructions).

## Skills

| Skill | Does |
|-------|------|
| `/worktree-ops:create-worktree` | Create a worktree via native `EnterWorktree` and **switch this session into it**. Fresh base, `.worktreeinclude` copy, optional GitHub issue/PR seed, ensures `.claude/worktrees/` is gitignored, runs `.claude/worktree-setup.sh` if present. |
| `/worktree-ops:list-worktrees` | Read-only dashboard of every worktree: branch, ahead/behind base, dirty count, PR status, current marked. `--fetch` for live numbers. |
| `/worktree-ops:pull-worktree` | Fetch and rebase (or `--merge`) the worktree's branch onto a base branch (`--from <branch>`, default `origin/HEAD`), guiding conflicts with an ask-first policy. |
| `/worktree-ops:merge-worktree` | Commit → push → open/update PR → merge into `--into <branch>` (never squashed) → run `.claude/worktree-archive.sh` → remove the worktree and return to main (native `ExitWorktree`). |

## Deterministic enforcement (hook + scripts)

The repeatable, high-stakes steps don't rely on the model remembering the rules:

- **`hooks/guard.sh`** is registered as a `PreToolUse` hook **in the `pull-worktree` and `merge-worktree` skills' frontmatter** — so it is active **only while those skills run** (scoped to the skill lifecycle, never global). While active it hard-blocks, regardless of what the model does:
  1. **squash merges** — any `gh pr merge --squash` is rejected (preserve commits with `--merge`/`--rebase`),
  2. **committing unresolved conflicts** — `git commit` / `git rebase|merge|cherry-pick|revert --continue` is blocked while unmerged paths or leftover conflict markers remain.
- **`scripts/wt-merge.sh`** merges without squashing and **confirms `state == MERGED`** before returning success, so teardown can be gated on a real merge (`wt-merge.sh && teardown`).
- **`scripts/wt-pull-preflight.sh`** deterministically reports pre-pull state (in-progress rebase/merge, dirty, resolved source, fetch, ahead/behind).
- **`scripts/wt-conflicts.sh`** lists the complete conflict set + hunks so resolution is never driven from a partial view.

## Opt-in project conventions

No-ops if the file is absent; run **only** for user-initiated skills (never for every subagent-isolation worktree):

- **`.claude/worktree-setup.sh`** — run by `create-worktree` (via `wt-run-optin.sh setup`) inside a new worktree.
- **`.claude/worktree-archive.sh`** — run by `merge-worktree` (via `wt-run-optin.sh archive`) before teardown.
- **`.worktreeinclude`** — native convention; gitignored files (e.g. `.env`) copied into each new worktree.

## Helper scripts (`scripts/`, via `${CLAUDE_PLUGIN_ROOT}`)

| Script | Role |
|--------|------|
| `wt-status.sh [--fetch] [base]` | Powers `list-worktrees` (offline TSV summary). |
| `wt-pull-preflight.sh [--from b]` | Deterministic pre-flight for `pull-worktree`. |
| `wt-conflicts.sh` | Complete conflict report (files + hunks). |
| `wt-merge.sh [--into b] [--rebase] [--keep-branch]` | Merge without squash + confirm `MERGED`. |
| `wt-run-optin.sh <setup\|archive>` | Run an opt-in `.claude/worktree-<name>.sh` if present. |
| `wt-create.sh <slug> [base]` | Raw-git creation fallback for non-interactive (`-p`) sessions. |
| `wt-ensure-gitignore.sh [root]` | Idempotently ensure `.claude/worktrees/` is gitignored in the main checkout (creates `.gitignore` if absent; derives the main root from git when no `root` is given). |
| `wt-teardown.sh <path\|slug> [--delete-branch] [--force]` | Guarded removal for worktrees `ExitWorktree` won't touch. |

## Roadmap

- **worktree-fanout** — decompose a task and dispatch N parallel agents, each in its own worktree (built on subagent `isolation: worktree`). Planned after the four skills above are validated in real use.
