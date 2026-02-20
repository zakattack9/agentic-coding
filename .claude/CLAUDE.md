# Agentic Coding Monorepo

This repository centralizes configuration, plugins, and tooling for AI-powered coding agents.

## Repo Structure

- `claude-code/` — Everything related to Claude Code: installable plugins, skills, hooks, commands, agents. See `claude-code/CLAUDE.md` for specifics.
- `codex-cli/` — Everything related to OpenAI Codex CLI (future).
- `docs/` — General documentation, guides, and notes not scoped to a specific tool.

## Plugin Marketplace

This repo doubles as a Claude Code plugin marketplace. `.claude-plugin/marketplace.json` points to plugins under `claude-code/plugins/` via relative paths. See `PLUGIN-SETUP.md` for the full mental model.

## Conventions

- Keep tool-specific content inside its tool directory. Do not put Claude Code files at the root or in `codex-cli/`.

## Versioning
**ALWAYS bump the plugin version in `.claude-plugin/marketplace.json` when changes are made to a plugin.** Versions are managed solely in `marketplace.json` — do not add a `version` field to individual `plugin.json` files.
