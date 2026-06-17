---
name: configure
description: Choose which centralized skill plugins the current project uses, written to the project's .claude/settings.local.json. Use when the user opens a repo and wants to wire up their skills, says "set up skills for this project", "which skills does this project use", "enable/disable a plugin here", or "configure plugins for this project".
# model: claude-sonnet-4-6
# effort: medium
model: claude-sonnet-4-6-20251114
effort: medium
disable-model-invocation: true
allowed-tools: Bash(python3 *) AskUserQuestion
argument-hint: "[plugins or 1 3 5]"
---

# Configure plugins for this project

Set which centralized plugins this project enables. The chosen set becomes the project's enabled set — the engine enables the picks and disables the rest — written to `.claude/settings.local.json` (personal, gitignored; merged, never clobbered). The engine resolves the selection and computes the change; **always preview the plan and confirm before applying.**

The engine is the source of truth at every step: it numbers the menu, resolves the reply, and diffs against current state. Don't enumerate, renumber, or map plugin names yourself — pass the user's raw reply through.

## Steps

1. **Show the numbered menu** (and what's already on):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" configure
   ```
   **Reproduce the menu in your reply inside a fenced ``` block** — copy it verbatim (numbers, `[on]`/`[  ]` markers, descriptions, skills) so the user can read it without expanding the raw tool output. Those values are ground truth; don't renumber or invent entries.

2. **Get the selection.** If the user already gave plugins or numbers (as args or in chat), use that. Otherwise ask in plain text to reply with the numbers to enable (e.g. `1 3 5`, a range `1-3`, `all`, or `none`) — this open-ended reply doesn't fit `AskUserQuestion`'s fixed options. Pass their reply through unchanged.

3. **Preview the plan** (writes nothing):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" configure --select "<user reply>"
   ```
   Add `--shared` only if the user wants the choice committed for the whole team (writes `.claude/settings.json`). The engine prints `enable` / `disable` / `keep on` / `result`, or "No changes" — relay those lines verbatim. It may also print a `stays on` line: a plugin enabled in the *other* scope that this scope can't turn off (re-run as the engine suggests, e.g. with/without `--shared`); surface it so the user isn't surprised it's still on. If it errors on a bad index/name, show the message and re-ask (back to step 2).

4. **Confirm before applying** with `AskUserQuestion`. Read the plan's `disable` line to choose the options:
   - **Apply** — set this exact selection (enable the picks, disable the rest).
   - **Enable these, keep current ones on** — include this option **only when the plan disables something**; it adds the picks without turning off what's already enabled (the guard against accidentally disabling everything).
   - **Cancel** — make no changes.

   If `enable` and `disable` are both empty ("No changes"), skip the confirmation — there's nothing to apply.

5. **Apply** the confirmed choice, reusing the exact `--select` string the plan echoed in its apply command:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" configure --select "<names>" --apply                 # Apply (exact set)
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" configure --select "<names>" --apply --keep-enabled   # keep current ones on
   ```
   Carry through `--shared` if it was used in step 3.

6. Tell the user to run `/reload-plugins` (or start a new session) to load them.

For a single quick toggle without the menu: `skillctl enable <plugin>` / `skillctl disable <plugin>`.

## Output

After applying, fill this skeleton from the engine's output, copying values verbatim and dropping lines that don't apply:

**Enabled:** `{newly enabled, or "—"}`
**Disabled:** `{newly disabled, or "—"}`
**Stays on (other scope):** `{plugins from a "stays on" line, if any}` — still enabled via the other scope; re-run as the engine suggested to turn them off there.
**Now on:** `{full enabled set}` → `{settings file}`
**Scope:** {this project only (`settings.local.json`) / shared with the team (`settings.json`)}
**Next:** run `/reload-plugins` — then this project can use those plugins' skills as `/{plugin}:<skill>`.

If the user cancelled, say so and report the unchanged enabled set instead.
