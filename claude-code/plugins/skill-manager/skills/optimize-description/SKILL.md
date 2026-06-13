---
name: optimize-description
description: Improve how reliably a skill triggers by optimizing its SKILL.md description, using the native skill-creator's description optimizer. Use when the user says a skill "isn't triggering", "doesn't activate when it should", "fires when it shouldn't", "tune the triggering", "improve the description", or "optimize when this skill runs". Works on a project-local skill or a central one. User-invoked.
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *)
argument-hint: "<skill-name>"
---

# Optimize a skill's description for reliable triggering

A skill's `description` is the only signal Claude uses to decide whether to invoke it, so a vague one makes even a good skill under-trigger (not firing when useful) or over-trigger (firing when it shouldn't). This skill improves that description with the native **skill-creator** skill's description optimizer — it generates realistic trigger/no-trigger queries, runs an eval loop, and picks the description that scores best on a held-out set — then publishes the result.

Requires the **skill-creator** plugin. If it isn't installed, tell the user: `/plugin install skill-creator@claude-plugins-official`.

## Steps

1. **Identify the target skill and get a writable copy in this project.**
   - If it already lives in `.claude/skills/<name>/`, use it.
   - If it's central, pull it down first so edits land somewhere writable:
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" pull <skill>
     ```
2. **Hand off to skill-creator's description optimizer.** Read the skill-creator skill and follow its **"Description Optimization"** section against this skill's directory: draft ~20 realistic should-trigger / should-not-trigger queries, get the user's sign-off on them, then run its optimizer loop using the model id powering this session. Let skill-creator apply the winning `best_description` to the skill's `SKILL.md` — don't hand-write a description yourself; the point is the measured result.
3. **Show the before/after description and the trigger scores** so the user can confirm it actually improved.
4. **Publish the improved skill** (it's a description-only edit, so this syncs the change up):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push <skill>
   ```
   Surface any push-failure WARNING, then tell the user to `/reload-plugins`.

Notes:
- The optimizer changes only the `description`, never the skill body.
- It runs eval loops and can take a few minutes; skill-creator runs it in the background and reports progress — let it finish before pushing.
- Only optimize a skill the user owns in their marketplace; don't run it against unrelated installed plugins.
