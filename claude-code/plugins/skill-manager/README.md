# skill-manager

Manage your Claude Code skills from inside any project. One GitHub repo is the single source of
truth for your skills, and this plugin removes the manual round-trip of editing that repo,
switching back to a project, pulling, and reloading — install it, point it at your own repo, and
publish skills that become available across all your projects.

## Install

1. **Add the marketplace that hosts this plugin** and accept the trust prompt
   (third-party marketplaces must be trusted before they can be used):
   ```
   /plugin marketplace add zakattack9/agentic-coding
   ```

2. **Install the plugin, then reload to activate it:**
   ```
   /plugin install skill-manager@zaksak
   /reload-plugins
   ```
   Installing enables it for you, so `/skill-manager:*` becomes available in your projects.

3. **Point it at your skills repo** — once:
   ```
   /skill-manager:init
   ```
   It finds the skills repos already on your machine and asks which one to use — or, if you
   don't have one, **creates a fresh repo for you** (you give it a name and where to put it).
   Either way it bootstraps and registers the marketplace, adapting to any layout (root-level
   or nested in a monorepo). Creating a new repo uses the GitHub CLI `gh`; without it, create
   an empty repo on GitHub first and init points at that.

4. **Heads up — you'll refresh manually.** Custom marketplaces don't reliably auto-update
   (not even in new sessions), so after every change you publish you'll update the marketplace
   and reload (see *Publish your first skill*, step 4). You can flip on auto-update in
   `/plugin` → Marketplaces, but don't rely on it.

That's it — you can now manage skills from any project.

## Publish your first skill

1. **Author** a skill in your current project using the native **skill-creator** skill
   (this plugin intentionally doesn't scaffold skills — skill-creator does it better).
2. **Publish** it to your marketplace:
   ```
   /skill-manager:push
   ```
   Name the target plugin (a grouping) for a brand-new skill; it's created automatically if
   it doesn't exist. Editing a skill that's already central? `push` detects that and syncs
   your changes up (showing a diff first).
3. **Enable** the plugin for this project:
   ```
   /skill-manager:configure
   ```
4. **Refresh & use it — required after every push.** Custom marketplaces don't reliably
   auto-update, so each time you publish run these two commands (using your real marketplace
   name): `/plugin marketplace update <marketplace>` then `/reload-plugins`. Now
   `/<plugin>:<skill>` works here (and in any project that enables the plugin).

Managing over time: `/skill-manager:status` (what exists + what's on + health; `--fix` to
auto-repair), `/skill-manager:push` (publish/update), `/skill-manager:remove` (delete a skill
or plugin). To iterate on a central skill locally, `skillctl pull <skill>`, edit, then push back.

## Skills

| Skill | What it does |
|---|---|
| `/skill-manager:init` | One-time setup: pick an existing skills repo, or have it create a new one |
| `/skill-manager:status` | Catalog + what's enabled here + a health check; `--fix` auto-repairs |
| `/skill-manager:configure` | Choose which plugins this project uses (`settings.local.json`) |
| `/skill-manager:push` | Publish a project skill central, or sync edits up (auto-detected) |
| `/skill-manager:remove` | Delete a skill or a whole plugin and push the removal |

Authoring a new skill → use the native **skill-creator** skill, then `/skill-manager:push` it.

## Design choices

- **Any layout.** Works whether plugins live at the repo root (`source: ./<name>`) or nested
  in a monorepo (`source: ./path/to/plugins/<name>`); the plugins dir is auto-detected at init.
- **Your existing checkout.** Operates directly on the repo you already have cloned — no
  second authoring clone to keep in sync.
- **Versions in `marketplace.json` only.** The per-plugin `version` is bumped there; nothing
  is written to `plugin.json`.
- **No PATH install.** The skills invoke the bundled engine via
  `${CLAUDE_PLUGIN_ROOT}/bin/skillctl` (no setup, works cross-checkout).
- **Personal by default.** Per-project enablement is written to `.claude/settings.local.json`
  (gitignored) so your marketplace never leaks into a shared repo. Use `--shared` to commit it
  for a whole team.
- **Manual refresh.** Custom marketplaces don't reliably auto-update (not even new sessions),
  so after every change you update the marketplace in `/plugin` and `/reload-plugins`; the
  engine does no git force-fast-forward or cache surgery.

## CLI reference

The skills invoke the bundled engine at `${CLAUDE_PLUGIN_ROOT}/bin/skillctl`. For direct
terminal use, call that path or alias it (`alias skillctl='python3 .../bin/skillctl'`) — it is
deliberately not installed on your PATH. Requires `python3` (macOS/Linux).

```
skillctl init [--repo owner/name] [--path P] [--marketplace N] [--plugins-dir D] [--user-plugins a,b]
skillctl configure [--plugins a,b,c] [--shared]
skillctl enable <plugin>...        skillctl disable <plugin>...    [--shared]
skillctl push <skill> [--plugin P] [-m msg] [--dry-run] [--force] [--no-refresh]
skillctl pull <skill> [--plugin P] [--force]
skillctl new-plugin <name> [--description D]
skillctl remove-skill <skill> [--plugin P] --force
skillctl remove-plugin <plugin> --force
skillctl status [--fix]   skillctl validate        skillctl refresh
skillctl version-bump <plugin>
```

`validate` runs without config (CI mode) against the repo's `marketplace.json`.
