# skill-manager

Manage your Claude Code skills from inside any project. One GitHub repo is the single source
of truth for your skills; this plugin removes the manual round-trip of editing that repo,
switching back to a project, pulling, and reloading.

It works for **anyone**: install the plugin, point it at your own GitHub repo, and start
publishing skills that become available across all your projects.

## Install (anyone, once per machine)

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

3. **Point it at your own skills repo** — one time:
   ```
   /skill-manager:init
   ```
   The skill will gather what it needs and run the engine. Two cases:

   - **You already have a skills/marketplace repo** (including a monorepo): give it the path
     to your local checkout. The repo slug and the layout (root-level vs. nested plugins) are
     auto-detected.
   - **You're starting from scratch**: create an empty GitHub repo first
     (`gh repo create <you>/<repo> --private`), then run init with `--repo <you>/<repo>`.
     init clones it, turns it into a valid marketplace (writes + pushes `marketplace.json`),
     and registers it with Claude Code.

4. (Optional) Turn ON auto-update for your marketplace via `/plugin` → Marketplaces so new
   sessions pick up changes automatically; otherwise refresh on demand with `/reload-plugins`.

That's it — you can now manage skills from any project.

## Publish your first skill (the everyday loop)

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
4. **`/reload-plugins`** — now `/<plugin>:<skill>` works here, and in any project that
   enables that plugin.

Managing over time: `/skill-manager:status` (what exists + what's on + health; `--fix` to
auto-repair), `/skill-manager:push` (publish/update), `/skill-manager:remove` (delete a skill
or plugin). To iterate on a central skill locally, `skillctl pull <skill>`, edit, then push back.

## Skills

| Skill | What it does |
|---|---|
| `/skill-manager:init` | One-time setup against your local checkout (cold-start aware) |
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
- **Minimal refresh.** After a push it asks Claude Code to update the marketplace and tells you
  to `/reload-plugins`; no git force-fast-forward or cache surgery.

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
