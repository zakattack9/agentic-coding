---
name: new-plugin
description: Create a new plugin in the central skills repo and register it in the marketplace catalog. Use whenever the user wants a new grouping of skills, says "create a plugin", "add a new plugin", "I need a category for <domain> skills", or tries to promote a skill into a plugin that doesn't exist yet. Do not auto-run; this pushes to git.
disable-model-invocation: true
allowed-tools: Bash(skillctl *) Bash(git *)
argument-hint: "<plugin-name>"
---

# Create and register a new plugin

Plugins are how skills are grouped and enabled per project. Keep the count small and scope-based: one `core` for universal skills, then a handful of domain plugins (e.g. `aws-infra`, `web-frontend`, `mobile`, `rentals-ops`). Users enable plugins, not individual skills, so coarse grouping keeps per-project config trivial and lets new skills flow in automatically when added to an already-enabled plugin.

## Steps

1. Get a lowercase-hyphenated plugin name and a one-line description.
2. Run `skillctl new-plugin <name> --description "<desc>"`. This scaffolds `<name>/.claude-plugin/plugin.json` and `<name>/skills/`, registers it in `.claude-plugin/marketplace.json`, commits, pushes, and refreshes.
3. Suggest next steps: add skills with the new-skill skill (`--plugin <name>`), and enable it in projects that need it with the setup-project skill or `skillctl enable <name>`.

Before creating, run `skillctl list` to make sure a suitable plugin doesn't already exist — prefer adding to an existing plugin over proliferating new ones.
