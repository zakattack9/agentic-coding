---
name: list-worktrees
description: Show a dashboard of every git worktree in this repo — branch, commits ahead/behind the base branch, uncommitted (dirty) file count, and open-PR status — with the current session's worktree marked, so all parallel sessions are visible at a glance. Use when the user asks to "list worktrees", "worktree status", "what worktrees do I have", "show my parallel sessions", "which branches am I working on", or wants an overview of in-flight worktree work before pulling, switching, or merging.
# model: claude-sonnet-4-6
# effort: medium
allowed-tools: Bash(git *), Bash(gh *), Bash(bash *)
---

# list-worktrees

This skill takes no required arguments (only optional `--fetch`), so there's nothing to confirm before it runs.

Run the helper and present a dashboard of all worktrees. By default it's **offline** (no fetch), so ahead/behind is measured against the last-known base — note that. Add `--fetch` when the user wants live numbers:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-status.sh"          # offline (fast)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wt-status.sh" --fetch   # fetch first (live ahead/behind)
```

It prints a `BASE<TAB><ref>` line, a header, then one tab-separated row per worktree: `cur`, `name`, `branch`, `ahead`, `behind`, `dirty`, `pr`, `path`. `cur` is `*` for the worktree this session is in. Treat the output as ground truth — don't infer any field. (`pr` is `-` when GitHub CLI is unavailable or there's no PR; ahead/behind are `?` if the base can't be resolved.)

Render a markdown table, naming the base in a lead-in and marking the current worktree (drop the full `path` unless asked):

**Base:** `{base}` · ahead/behind is from your last fetch (run with `--fetch` for live).

|            | Worktree | Branch     | Ahead   | Behind   | Dirty   | PR   |
| ---------- | -------- | ---------- | ------- | -------- | ------- | ---- |
| {▸ if cur} | `{name}` | `{branch}` | {ahead} | {behind} | {dirty} | {pr} |

Then a one-line takeaway plus the obvious next actions:

- **behind > 0** → `/worktree-ops:pull-worktree` in that worktree (it fetches fresh).
- **clean with PR merged/closed** → `/worktree-ops:merge-worktree` to tear it down.

If only the main worktree exists, say so plainly instead of a one-row table.
