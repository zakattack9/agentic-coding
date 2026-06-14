---
name: status
description: Show the central skills catalog grouped by plugin, which plugins are enabled in the current project, and a health check of the skill-manager setup — and optionally auto-repair it. Use when the user asks "what skills do I have", "what's in my marketplace", "which plugins are on for this project", "list my skills", "is my skill setup healthy", "why isn't my skill loading", "fix my skill setup", or wants an overview of available vs enabled skills.
model: sonnet
effort: high
allowed-tools: Bash(python3 *) AskUserQuestion
---

# Skill-manager status

Run the engine and present the result: each plugin with its version and skills (shown as `/<plugin>:<skill>`), whether it's enabled in this project (`[on]` vs `[  ]`), and a health check.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" status
```

If it reports "not configured", point the user at `/skill-manager:init`.

To turn plugins on/off for this project, use `/skill-manager:configure`.

If health checks fail, offer to auto-repair the fixable ones:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" status --fix
```

`--fix` safely repairs the two common drift cases — re-registering the marketplace and re-enabling your user-scope plugins — and reports what it changed. It deliberately does **not** touch failures that need a decision (missing checkout, no `origin` remote, `claude` CLI not installed, unpushed commits); relay the printed `->` hint for those.

Present what the tool prints — the catalog, the `[on]`/`[  ]` markers, and the health lines are the ground truth. Don't infer enablement, versions, or health beyond its output.

## Output

Present it the same way every call, so it reads consistently:

1. Show the engine's output verbatim in a fenced block — the catalog (`[on]`/`[  ]` markers, versions, `/<plugin>:<skill>` lines) and the Health block are already structured, so don't paraphrase or reformat them away.
2. Then one takeaway line: plugin count, how many are enabled in this project, and overall health — e.g. `3 plugins, 1 enabled here — health OK`, or `health: 1 fixable issue (run status --fix)`.

Add nothing else unless the user asks a follow-up.
