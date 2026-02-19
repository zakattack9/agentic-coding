# Plugin Setup Instructions

## What This Repo Is

This repo is a **single Git repository that acts as both the marketplace and the host for all plugins**. There is no separate marketplace repo. `.claude-plugin/marketplace.json` points to plugin subfolders via relative paths.

## What to Look Up

Use Context7 (`resolve-library-id` then `query-docs`) against the Claude Code docs site (`/websites/code_claude`). Query for:

1. **`plugin.json` manifest schema** — fields, required vs optional, where the file lives relative to the plugin root (it is NOT at the plugin folder root; look for `.claude-plugin/` directory convention).
2. **`marketplace.json` schema** — specifically the format for relative path sources pointing to subfolders within the same repo.
3. **Plugin components** — how to define commands, skills, agents, hooks, and MCP servers within a plugin. Each has its own directory convention and markdown/json format.
4. **`${CLAUDE_PLUGIN_ROOT}` variable** — how it resolves at runtime inside `plugin.json` hook commands and MCP server configs.
5. **Auto-update behavior** — how it works at startup, how users enable it per-marketplace.

## Non-Obvious Things You Won't Find in a Single Doc

- **Relative paths in `marketplace.json` only resolve when the marketplace is added via Git URL** (e.g., `/plugin marketplace add https://github.com/...git`). If someone adds it via a raw URL to the JSON file, the relative paths break. This is the only supported installation method for this repo.
- **The manifest location is `.claude-plugin/plugin.json`**, not `plugin.json` at the plugin folder root. The docs show this in a directory tree example but it's easy to miss since other sections casually reference "plugin.json" without the parent directory.
- **This repo doubles as its own marketplace.** Most docs describe the marketplace and plugins as separate repos. The pattern here — `.claude-plugin/marketplace.json` with `"source": "./claude-code/plugins/<name>"` entries — collapses them into one repo. This is valid but not the primary example in the docs, so you'll need to synthesize from the marketplace source format docs and the plugin structure docs independently.
