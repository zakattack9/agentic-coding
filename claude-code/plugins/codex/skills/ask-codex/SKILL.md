---
name: ask-codex
description: Ask OpenAI Codex a free-form question for a cross-model second opinion — an explanation, a plan/approach review, a repo question, or a take on a diff, answered by a different provider's model. Use when the user wants Codex's view — "ask Codex how X works", "what would Codex do here", "get Codex's opinion on this approach", "ask Codex about this repo". With a question it runs immediately; with no question it suggests 2–4 context-derived questions to choose from. Read-only — Codex inspects the repo but changes nothing. Surfaces Codex's answer verbatim, then stops. It does NOT edit files or run a write task (that is delegate-codex), and it does NOT answer as Claude when Codex is unavailable (it reports and stops, fail-open). Needs an OpenAI-authenticated Codex CLI.
argument-hint: "[question] [--model <m>] [--effort <e>]"
allowed-tools: Bash(python3 *), Read, AskUserQuestion
---

# ask-codex

Get a **cross-model answer** from OpenAI Codex to a free-form question — explain / review a
plan / repo Q&A / opinion on a diff. You compose a grounded prompt and route it through the
bridge; the run is read-only and you surface Codex's answer **verbatim**, then stop. This
skill **never runs without a question** and never answers as Claude in Codex's place.

Codex availability (probed at load):
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe`
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --resolve-defaults`

Arguments: $ARGUMENTS

**First, read `${CLAUDE_PLUGIN_ROOT}/references/shared-behavior.md`** — it governs untrusted-output
handling, prompt composition, the `--model`/`--effort` override picker, the exact bridge call,
exit-code branching, fail-open, verbatim+delimited output, and the session id. The rules below
are ask-specific.

## If Codex is unavailable

If the probe line reads `CODEX: NO …`, tell the user (quote that line) and **stop** — do not
compose a prompt, do not call the bridge, do not answer as Claude.

## Flow

1. **Parse arguments** (shared grammar): an optional question plus optional `--model`/`--effort`.
   Resolve overrides per the shared rules.
2. **Get the question:**
   - **With a question argument** → compose a grounded prompt around it and run **immediately**.
     No picker.
   - **With no argument** → open an `AskUserQuestion` offering **2–4 suggested questions**
     derived from the conversation context (the built-in "Other" covers a freeform question —
     do **not** add a manual freeform option). If the conversation is **sparse** (no basis for
     repo-specific suggestions), ask the user to **type a question** rather than inventing
     misleading suggestions.
3. **Compose** a grounded prompt (template in `references/ask.md`), including the explicit
   "do not modify any files" line (defense-in-depth atop the read-only sandbox). Let Codex
   ground itself in the repo — don't paste large context blobs.
4. **Call the bridge** (a plain read-only call — no `--review`, no `--write`) and **branch on
   the exit code** (shared). On a skipped/errored/unrecoverable result, report the one
   diagnostic line and stop — never answer as Claude.

## Surfacing the answer (exit 0)

Show Codex's answer **verbatim and in full**, append the session-id metadata block (shared),
and stop.
