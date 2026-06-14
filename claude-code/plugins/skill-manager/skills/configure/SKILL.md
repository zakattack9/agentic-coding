---
name: configure
description: Choose which centralized skill plugins the current project uses, written to the project's .claude/settings.local.json. Use when the user opens a repo and wants to wire up their skills, says "set up skills for this project", "which skills does this project use", "enable/disable a plugin here", or "configure plugins for this project".
disable-model-invocation: true
model: sonnet
effort: high
allowed-tools: Bash(python3 *) AskUserQuestion
argument-hint: "[plugin,plugin,...]"
---

# Configure plugins for this project

Enable the plugins this project needs. The selection is written to `.claude/settings.local.json` (personal and gitignored, so it won't leak your marketplace to collaborators) and merged, never clobbered.

## Steps

1. Show the catalog and what's already enabled:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" configure
   ```
2. If the user named plugins, use those. Otherwise present the catalog and ask which to enable (one question). Use the exact plugin names from the catalog output — don't invent names; the tool will warn on any it doesn't recognize.
3. Write the selection:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" configure --plugins <comma,separated,list>
   ```
   - Pass `--shared` only if the user explicitly wants the choice committed for the whole team (writes `.claude/settings.json` instead).
4. Tell the user to run `/reload-plugins` (or start a new session) to load them.

To toggle a single plugin without re-listing: `skillctl enable <plugin>` / `skillctl disable <plugin>`.

## Output

Fill this skeleton from the engine's output, copying values verbatim:

**{Enabled / Disabled}:** `{plugins}` → `{settings file}`
**Scope:** {this project only (`settings.local.json`) / shared with the team (`settings.json`)}
**Next:** run `/reload-plugins` — then this project can use the plugin's skills as `/{plugin}:<skill>`.
