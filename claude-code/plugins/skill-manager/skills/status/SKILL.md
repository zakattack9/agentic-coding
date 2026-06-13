---
name: status
description: Show the central skills catalog grouped by plugin, which plugins are enabled in the current project, and a health check of the skill-manager setup. Use when the user asks "what skills do I have", "what's in my marketplace", "which plugins are on for this project", "list my skills", "is my skill setup healthy", "why isn't my skill loading", or wants an overview of available vs enabled skills.
allowed-tools: Bash(python3 *)
---

# Skill-manager status

Run the engine and present the result: each plugin with its version and skills (shown as `/<plugin>:<skill>`), whether it's enabled in this project (`[on]` vs `[  ]`), and a health check.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" status
```

If it reports "not configured", point the user at `/skill-manager:init`.

To turn plugins on/off for this project, use `/skill-manager:configure`. If a health check line fails, walk the user through the fix — the tool prints a `->` hint under each failure.

Present what the tool prints — the catalog, the `[on]`/`[  ]` markers, and the health lines are the ground truth. Don't infer enablement, versions, or health beyond its output.
