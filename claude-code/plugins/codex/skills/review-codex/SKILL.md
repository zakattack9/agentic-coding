---
name: review-codex
description: Hand the current diff or a named target to OpenAI Codex for a read-only, cross-model code review — a second opinion from a different provider's model. Use when the user wants Codex to review their work — "have Codex review this", "get Codex's take on the diff", "cross-model review of my changes", "what does Codex think of this code". With no argument it reviews the uncommitted working tree; with a target it reviews that file/range/intent. Surfaces Codex's review verbatim in Codex's own severity order, then stops. It does NOT modify, fix, or format anything (read-only — it may offer a fix as a follow-up); it does NOT review as Claude when Codex is unavailable (it reports and stops, fail-open); and it is NOT a replacement for Claude's own review. Needs an OpenAI-authenticated Codex CLI.
argument-hint: "[review target | branch/commit] [--model <m>] [--effort <e>]"
allowed-tools: Bash(python3 *), Bash(git diff*), Bash(git status*), Bash(git log*), Read, Grep, Glob, AskUserQuestion
model: opus
effort: medium
---

# review-codex

Get a **cross-model code review** from OpenAI Codex. You compose grounded review
instructions and route them through the bridge; Codex reviews read-only and you surface its
findings **exactly as returned**, then stop. You never review as Claude and never apply fixes.

Codex availability (probed at load):
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe`
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --resolve-defaults`

Arguments: $ARGUMENTS

**First, read `${CLAUDE_PLUGIN_ROOT}/references/shared-behavior.md`** — it governs untrusted-output
handling, prompt composition, the `--model`/`--effort` override picker, the exact bridge call,
exit-code branching, fail-open, verbatim+delimited output, and the session id. The rules below
are review-specific.

## If Codex is unavailable

If the probe line above is anything other than an explicit `CODEX: YES …` — a `CODEX: NO …`
line, an empty line, or an error / permission-denied message (e.g. this freshly-installed
plugin's script blocked in auto mode) — Codex is unavailable: tell the user (quote the line) and
**stop** — do not compose a prompt, do not call the bridge, do not review as Claude. A denied or
failed probe is never a crash; it just means Codex couldn't be reached.

## Flow

1. **Parse arguments** (shared grammar): an optional single review target plus optional
   `--model`/`--effort`. Resolve overrides per the shared rules.
2. **Pick the review shape** (full detail + prompt template in
   `references/review.md`):
   - **No target** → ground the working tree (`git status --porcelain`, `git diff`,
     recently-touched files) and the conversation for focus, then run the bridge in
     **`--review`** mode (its default scope is the uncommitted working tree).
   - **No target and nothing to review** (clean tree, ambiguous context) → say there is
     nothing obvious to review and **ask the user for a target**. Do not invent a review and
     do not open a suggestion picker.
   - **A target naming a specific branch / commit / range** → Codex's `review` scope flags
     cannot be combined with a prompt, so run a **plain read-only** bridge call (no `--review`)
     whose composed instructions tell Codex to inspect that range via read-only `git`.
   - **A target that is a focus** (a module, a concern like "security") → run **`--review`**
     with the target as the review focus over the working tree.
   - **Never** combine a `review` scope flag with a prompt (the bridge's `--review` mode never
     passes one; you only choose `--review` vs a plain call).
3. **Compose** grounded review instructions from `references/review.md`, including the
   explicit defense-in-depth line telling Codex **not to modify files, run formatters, or
   install dependencies** even if the target implies a fix.
4. **Call the bridge** and **branch on the exit code** (shared). On a skipped/errored/
   unrecoverable result, report the one diagnostic line and stop — never review as Claude.

## Surfacing the review (exit 0)

- Show Codex's review **verbatim and in full, in Codex's own severity ordering**. Add only
  minimal section framing — **do not** parse, re-sort, re-rank, or transform the findings.
- Print the session id (shared).
- **Then stop.** Never auto-apply fixes. You may offer, as a follow-up, to fix specific
  findings if the user wants — but only on their say-so, and that is Claude's own work, not
  this skill's.
