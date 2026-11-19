---
name: review-codex
description: Hand the current diff or a named target to OpenAI Codex for one read-only, cross-model code review that reports only blocking (P0) and must-fix (P1) findings, each with evidence or marked unproven. Use when the user wants Codex to review their work — "have Codex review this", "get Codex's take on the diff", "cross-model review of my changes", "what does Codex think of this code" — or to recheck fixed findings ("recheck these with Codex", `--recheck <findings file>`), which runs in a fresh Codex session that sees the evidence, not the author's argument. With no argument it reviews the uncommitted working tree. Surfaces the findings verbatim, then stops. It does NOT fix anything, does NOT loop review rounds, and does NOT run Claude and Codex side by side. When Codex is unavailable it runs the same review once in a fresh read-only Claude subagent and labels it as the fallback.
argument-hint: "[review target | branch/commit] [--recheck <findings file>] [--model <m>] [--effort <e>]"
allowed-tools: Bash(python3 *), Bash(git diff*), Bash(git status*), Bash(git log*), Read, Grep, Glob, Agent, AskUserQuestion
model: opus
effort: medium
---

# review-codex

One **cross-model code review** by OpenAI Codex: a single pass that reports only P0 and P1
findings, each backed by evidence or marked unproven. You compose grounded instructions,
route them through the bridge, surface the findings **exactly as returned**, then stop. You
never fix anything. Review is a sensor, not a verdict: the author proves each finding with a
failing test (or dismisses it with evidence) before acting on it.

Codex availability (probed at load):
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe`
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --resolve-defaults`

Arguments: $ARGUMENTS

**First, read `${CLAUDE_PLUGIN_ROOT}/references/shared-behavior.md`** (untrusted-output
handling, prompt composition, overrides, the bridge call, exit codes, verbatim output, session
id) and **`${CLAUDE_PLUGIN_ROOT}/references/review.md`** (the review and recheck prompt
templates). The rules below are review-specific and win over shared-behavior where they differ.

## Codex availability and the Claude fallback

Proceed with the bridge only when the probe above **shows `CODEX: YES`** (only that verdict
matters; text after it is informational). Any other line, or a bridge exit of 10, 11 or 12,
means Codex is unavailable. Then, unlike ask-codex and delegate-codex:

1. Tell the user Codex is unavailable and quote the one diagnostic line.
2. Dispatch **one fresh `Explore` subagent** (read-only) with the same composed instructions
   from `references/review.md`. It has no context from this session, so the brief must be
   self-contained (target, diff command, focus, the P0/P1 bar and the finding shape).
3. Surface its findings verbatim under the heading
   `Claude fallback review (Codex unavailable: <reason>)`, then stop.

Never run both models on the same target, and never add a third model to judge between them.

## Flow

1. **Parse arguments**: an optional single review target, an optional `--recheck <file>`, and
   optional `--model`/`--effort` (shared rules).
2. **Recheck mode** (`--recheck <file>`): read the findings file. For each finding id it names,
   collect the evidence the author recorded: the failing-then-passing test command and its
   output, or the dismissal evidence (file:line, a test that cannot be made to fail). Compose
   the **recheck template** from `references/review.md` and run a **new** plain read-only
   bridge call. Never resume the original review session, and never include the author's
   argument for a dismissal, only its evidence. Codex answers per finding RESOLVED, STILL OPEN
   or NOT REPRODUCED with evidence, and may raise only new P0 findings. Skip steps 3 to 5.
3. **Pick the review shape**:
   - **No target**: ground the working tree (`git status --porcelain`, `git diff`, recently
     touched files) and the conversation for focus, then run the bridge in **`--review`** mode
     (its default scope is the uncommitted working tree).
   - **No target and nothing to review** (clean tree): say so and ask the user for a target.
   - **A target naming a branch, commit or range**: run a **plain read-only** bridge call (no
     `--review`) whose instructions tell Codex to inspect that range via read-only `git`.
     `--review` scope flags cannot be combined with a prompt.
   - **A target that is a focus** (a module, "security"): run **`--review`** with the target
     as the focus over the working tree.
4. **Compose** the review template from `references/review.md`, including the line telling
   Codex **not to modify files, run formatters, or install dependencies**.
5. **Call the bridge** and branch on the exit code. Exit 0: surface. Any other exit: the
   Claude fallback above.

## Surfacing the findings

- Show the findings **verbatim and in full**, in the reviewer's own order. Add only minimal
  framing; do not re-rank, merge or drop findings.
- Print the session id (shared). For a recheck, say it ran in a fresh session.
- **Then stop.** Do not start another review round. The author's next step is a failing test
  per finding (or a recorded dismissal), then one `--recheck` of exactly those findings.
  Anything still disputed after that recheck goes to the user as one question.
