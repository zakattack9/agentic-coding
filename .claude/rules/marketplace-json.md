---
paths:
  - ".claude-plugin/marketplace.json"
  - "**/.claude-plugin/marketplace.json"
---

# Editing the plugin marketplace (`marketplace.json`)

The repo-root `.claude-plugin/marketplace.json` lists every plugin under `claude-code/plugins/`. Keep all entries uniform.

## Entry shape

Each plugin is `{ name, source, description, version }`, in that order. `name` matches the plugin directory and its `plugin.json` `name`; `source` is `./claude-code/plugins/<name>`.

## `description` — a high-level overview, not a skill list

This is what a human reads in the `/plugin` browse view to decide whether to install. It is NOT a skill trigger (each skill carries its own `description`) and NOT the README. Give a concise pitch — **what the plugin is, its core capabilities, and the value it provides**:

- **Lead** with what the plugin is and for whom, in one clause.
- Summarize the **capabilities and value at a high level** — the arc of what it lets you do. Do **NOT** enumerate the individual skills/commands or walk a skill-by-skill feature list.
- **One differentiator** is welcome ("free, no metered AI"); a feature inventory is not.
- **Cut the detail** — skill-by-skill enumeration, hook names, token types, file formats, idempotency, SHA-pinning, flag-level mechanics. Those belong in the plugin README and the per-skill descriptions.
- Third person, present tense. **2–4 sentences**; if you are past **~500 characters** you are likely enumerating skills or mechanics rather than summarizing.
- Punctuation: literal Unicode (`—`, `→`), **never** `\uXXXX` escapes, and consistent across the file.

Match the style of the existing entries (`spec-ops`, `worktree-ops`, `gh-projects`, `ralph`). The old sprawling, skill-enumerating 1,000–2,200-character paragraphs were the anti-pattern.

## `version`

- Semver, and the **single source of truth** for the plugin version — never add a `version` to a plugin's `plugin.json`.
- Bump the plugin's `version` whenever that plugin's **content** changes (skills, scripts, hooks, agents): patch = fix/refine, minor = new capability, major = breaking. A `description`- or metadata-only edit to this file is **not** a plugin change and needs no bump.
- This file is shared, so plugins are often edited in parallel. Stage `marketplace.json` and commit **only your plugin's line** — never sweep another plugin's pending version bump.

## Before saving

Confirm it still parses: `python3 -m json.tool .claude-plugin/marketplace.json`.
