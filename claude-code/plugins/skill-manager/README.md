# skill-manager

Manage your Claude Code skills from inside any project. One marketplace repo is the single
source of truth; this plugin removes the manual round-trip of editing the central repo,
switching back to a project, pulling, and reloading.

It rests on a few Claude Code facts:

- Skills are distributed through the **plugin** system; a GitHub repo registered as a plugin
  marketplace is the native way to share them.
- Per-project selection is opt-in via `enabledPlugins`; this plugin writes it to each
  project's `.claude/settings.local.json` (personal, gitignored) so your marketplace never
  leaks into a shared repo.
- A bundled stdlib-only Python CLI (`bin/skillctl`) does the git/file/marketplace work; the
  skills are thin wrappers that gather inputs and run it. Authoring a skill from scratch is
  delegated to the native **skill-creator** skill.

## Design choices

- **Any layout.** Works whether plugins live at the repo root (`source: ./<name>`) or nested
  in a monorepo (`source: ./path/to/plugins/<name>`); the plugins dir is auto-detected at init.
- **Your existing checkout.** Operates directly on the repo you already have cloned — no
  second authoring clone to keep in sync.
- **Versions in `marketplace.json` only.** The per-plugin `version` is bumped there; nothing
  is written to `plugin.json`.
- **No PATH install.** Skills invoke the engine via `${CLAUDE_PLUGIN_ROOT}/bin/skillctl`.
- **Minimal refresh.** After a push it asks Claude Code to update the marketplace and tells
  you to `/reload-plugins`; no git force-fast-forward or cache surgery.

## Setup (once)

Install the plugin from the marketplace, then:

```
/skill-manager:init
```

Point it at your local checkout of the marketplace repo (the slug is auto-detected from
`origin`). Or from a terminal:

```bash
skillctl init --path ~/path/to/your/skills-repo [--repo owner/name] [--user-plugins core]
```

Then turn ON auto-update for the marketplace (`/plugin` → Marketplaces) and `/reload-plugins`.

## Skills

| Skill | What it does |
|---|---|
| `/skill-manager:status` | Catalog + what's enabled in this project + a health check |
| `/skill-manager:configure` | Choose which plugins this project uses (`settings.local.json`) |
| `/skill-manager:push` | Publish a project skill central, or sync edits up (auto-detected) |
| `/skill-manager:remove` | Delete a skill or a whole plugin and push the removal |
| `/skill-manager:init` | One-time setup against your local checkout |

Authoring a new skill → use the native **skill-creator** skill, then `/skill-manager:push` it.

## CLI reference

The skills invoke the bundled engine at `${CLAUDE_PLUGIN_ROOT}/bin/skillctl`. For direct
terminal use, call that path or alias it (`alias skillctl='python3 .../bin/skillctl'`) — it is
deliberately not installed on your PATH.

```
skillctl init [--repo owner/name] [--path P] [--marketplace N] [--plugins-dir D] [--user-plugins a,b]
skillctl configure [--plugins a,b,c] [--shared]
skillctl enable <plugin>...        skillctl disable <plugin>...    [--shared]
skillctl push <skill> [--plugin P] [-m msg] [--dry-run] [--force] [--no-refresh]
skillctl pull <skill> [--plugin P] [--force]
skillctl new-plugin <name> [--description D]
skillctl remove-skill <skill> [--plugin P] --force
skillctl remove-plugin <plugin> --force
skillctl status        skillctl validate        skillctl refresh
skillctl version-bump <plugin>
```

`validate` runs without config (CI mode) against the repo's `marketplace.json`.
