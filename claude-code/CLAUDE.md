# Claude Code

All Claude Code plugins, skills, hooks, commands, and agents live here.

## Plugins

Plugins are under `plugins/`. Each plugin is a self-contained directory with its own `.claude-plugin/plugin.json` manifest. The root `marketplace.json` references each plugin via relative path (e.g., `./claude-code/plugins/<name>`).

To add a new plugin:

1. Create `plugins/<name>/`
2. Create `plugins/<name>/.claude-plugin/plugin.json` with the required manifest fields
3. Add component directories (`commands/`, `skills/`, `agents/`, `hooks/`) as needed inside the plugin
4. Add an entry to the root `marketplace.json`

Use `${CLAUDE_PLUGIN_ROOT}` inside `plugin.json` to reference scripts and files relative to the plugin's installed location at runtime.

Refer to `PLUGIN-SETUP.md` at the repo root for context on the marketplace architecture and non-obvious gotchas. Use Context7 against the Claude Code docs for the full `plugin.json` and `marketplace.json` schemas when building out a plugin.
