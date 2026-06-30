---
name: delegate-codex
description: Hand a write task to OpenAI Codex and let it edit the working tree — a cross-model "go implement this" to a different provider's model. User-invoked only. Use when you want Codex (not Claude) to make the change — "delegate this to Codex", "have Codex implement X", "let Codex fix this in the repo". With a task it runs immediately in a workspace-write sandbox; with no task it suggests 2–4 context-derived tasks to choose from. One foreground run — it surfaces Codex's output and the resulting git diff (attributing Codex's edits vs any pre-existing changes) and leaves the edits uncommitted and unstaged. It does NOT commit, stage, branch, retry, or auto-fix; it does NOT apply edits as Claude when Codex is unavailable (it reports and stops, fail-open); and it is NOT for read-only review/Q&A (use review-codex / ask-codex). Needs an OpenAI-authenticated Codex CLI.
argument-hint: "[task] [--model <m>] [--effort <e>]"
allowed-tools: Bash(python3 *), Bash(git diff*), Bash(git status*), Bash(git log*), Read, AskUserQuestion
model: opus
effort: medium
disable-model-invocation: true
---

# delegate-codex

Delegate a **write task** to OpenAI Codex: Codex (not Claude) edits the working tree in a
`workspace-write` sandbox, and you surface its output plus the resulting `git diff`, then
stop. **User-invoked only.** This skill **never runs without a task** and never makes the
edits itself as Claude.

Codex availability (probed at load):
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe`
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --resolve-defaults`

Arguments: $ARGUMENTS

**First, read `${CLAUDE_PLUGIN_ROOT}/references/shared-behavior.md`** — it governs untrusted-output
handling, prompt composition, the `--model`/`--effort` override picker, the exact bridge call,
exit-code branching, fail-open, verbatim+delimited output, and the session id. The rules below
are delegate-specific.

## If Codex is unavailable

Proceed only when the probe line **shows `CODEX: YES`**. If it shows anything else — a
`CODEX: NO …` line, a blank line, or an error / denied result — Codex is unavailable: tell the
user (quote the line) and **stop**. **No write is attempted** and you do not make the change as
Claude. A denied or failed probe is never a crash; it just means Codex couldn't be reached.

## Flow

1. **Parse arguments** (shared grammar): an optional task plus optional `--model`/`--effort`.
   Resolve overrides per the shared rules.
2. **Get the task:**
   - **With a task argument** → compose the task prompt and run **immediately**.
   - **With no argument** → open an `AskUserQuestion` offering **2–4 suggested tasks** derived
     from the conversation context (the built-in "Other" covers a freeform task — do **not** add
     a manual one). If context is **sparse**, ask the user to **type a task** rather than
     inventing one — especially important here, since this skill writes to the tree.
3. **Snapshot the tree before the run** — `git status --porcelain` — so you can attribute
   Codex's edits afterward (see `references/delegate.md`). If this is not a git repo, note that
   no diff/attribution will be possible and continue (the bridge still runs).
4. **Run the bridge in `--write` mode** (workspace-write) — see `references/delegate.md` for the
   task prompt template. Exactly **one foreground run**: no job store, no retries, no auto-fix
   loop, no post-processing beyond surfacing the output and the diff.
5. **Branch on the exit code** (shared) — see "After the run" below.

## After the run

- **Exit 0** → surface Codex's output **verbatim**, then the resulting **`git diff`**,
  attributing Codex's changes vs any pre-existing ones using your pre-run snapshot (or stating
  plainly that you cannot cleanly attribute them). If there is **no diff**, say no workspace
  change resulted — and still print the session id. If there is **no git repo**, report that no
  diff can be shown.
- **Exit 10** (skipped / unauthenticated / disabled) → **no write was attempted**; report the
  one diagnostic line and stop.
- **Exit 11** (error / timeout after the run began) → Codex may have made **partial edits**.
  Still show the resulting `git diff` so any partial changes are visible — **do not roll back**,
  and never finish the task yourself as Claude. Report the one diagnostic line.
- **Exit 12** → report the one diagnostic line and stop.

## Always

- **Leave the edits uncommitted and unstaged.** Never run `git add`, never commit, never branch.
- **Print the session id** (shared) so the user can resume the Codex thread.
