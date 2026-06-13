---
name: list-skills
description: Show the central skills catalog grouped by plugin, and which plugins are enabled in the current project. Use whenever the user asks "what skills do I have", "what's in my marketplace", "which plugins are on for this project", "list my skills", or wants an overview of available vs enabled skills.
allowed-tools: Bash(skillctl *)
---

# List the catalog and project enablement

Run `skillctl list` from the current project directory and present the result: each plugin, its skills (shown as `/<plugin>:<skill>`), and whether the plugin is enabled in this project (`[on]` vs `[ ]`).

If the user wants to turn something on or off, point them at the setup-project skill, or run `skillctl enable <plugin>` / `skillctl disable <plugin>` directly.
