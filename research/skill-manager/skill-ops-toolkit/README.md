# skill-ops — centralized Claude Code skills, managed from anywhere

This repo is **both** a Claude Code plugin marketplace and the tooling to run it. One GitHub
repo is the single source of truth for every skill. A small CLI (`skillctl`) plus a set of
self-hosting meta-skills (`skill-ops`) remove the manual round-trip of editing the central
repo, switching back to a project, pulling, and restarting.

The design rests on three Claude Code facts:

- Skills are distributed through the **plugin** system; a GitHub repo registered as a plugin
  marketplace is the native way to share them.
- Per-project selection is opt-in via `enabledPlugins` in each project's `.claude/settings.json`;
  the user-wide layer is `~/.claude/settings.json`.
- There is a **headless CLI** (`claude plugin marketplace add/update`, `claude plugin install
  --scope project`), so the whole lifecycle can be scripted.

## Layout

```
.claude-plugin/marketplace.json   # the catalog (one entry per plugin)
bin/skillctl                      # the engine — every meta-skill wraps this; also a terminal CLI
core/                             # universal skills (enabled in every project)
skill-ops/                        # the meta-skills that manage this repo (this plugin)
  skills/{setup-project, promote-skill, sync-skill, new-skill, new-plugin, list-skills, skills-doctor}
templates/                        # SKILL.md and plugin.json starting points
.github/workflows/validate.yml    # CI: lints the catalog + every SKILL.md on push
```

Group skills coarsely: one `core` for universal skills, then a few **domain plugins**
(`aws-infra`, `web-frontend`, `mobile`, `rentals-ops`, …). You enable *plugins*, not
individual skills, so a small number of groups keeps per-project config trivial — and new
skills added to an already-enabled plugin flow into projects automatically on update.

## Install (once per machine)

1. Put the CLI on your PATH:
   ```bash
   cp bin/skillctl ~/.local/bin/skillctl && chmod +x ~/.local/bin/skillctl
   ```
2. Push this repo to GitHub (or use it as your existing marketplace repo). Make sure the
   `name` in `.claude-plugin/marketplace.json` matches the marketplace name you'll bootstrap with.
3. Bootstrap — clones an authoring copy to `~/.claude/skills-repo`, registers the marketplace,
   and enables `core` + `skill-ops` at user scope:
   ```bash
   skillctl bootstrap --repo <owner>/<name> --marketplace z-skills
   ```
4. Re-point the CLI at the canonical clone so `git pull` also updates `skillctl`:
   ```bash
   ln -sf ~/.claude/skills-repo/bin/skillctl ~/.local/bin/skillctl
   ```
5. In Claude Code: `/plugin` → Marketplaces → turn **auto-update on** (third-party
   marketplaces default off), then `/reload-plugins`.

After this, `/skill-ops:setup-project`, `/skill-ops:promote-skill`, etc. are available in
every project.

## The scenarios this automates

Everything below is a one-liner — run the `skillctl` command directly, or invoke the matching
`/skill-ops:*` skill and let Claude gather the inputs and run it for you.

### Per-project configuration
- **Onboard a new project** — auto-detect project type, pick plugins, write a merge-safe
  `.claude/settings.json`. `skillctl setup-project` / `/skill-ops:setup-project`.
- **Toggle a plugin** for the current project. `skillctl enable|disable <plugin>`.
- **See what's available vs. enabled** here. `skillctl list` / `/skill-ops:list-skills`.

### Authoring & the round-trip
- **Promote** a project-local skill up into a central plugin (copy → version bump → commit →
  push → marketplace update → fast-forward installed clone), all without leaving the project.
  `skillctl promote <skill> --plugin <plugin>` / `/skill-ops:promote-skill`.
- **Sync** edits to an already-central skill back upstream, with a diff shown first.
  `skillctl sync <skill>` / `/skill-ops:sync-skill`.
- **Pull** a central skill down into a project to iterate locally, then sync back.
  `skillctl pull <skill>`.
- **Scaffold** a new skill with correct frontmatter, in a project or a central plugin.
  `skillctl new-skill <name> [--project | --plugin <p>]` / `/skill-ops:new-skill`.

### Central-repo maintenance
- **New plugin** scaffolded and registered in the catalog in one step.
  `skillctl new-plugin <name>` / `/skill-ops:new-plugin`.
- **Validate** the catalog, every `plugin.json`, and every `SKILL.md` (also runs in CI).
  `skillctl validate`.
- **Version bump** a plugin (done automatically by promote/sync/new-skill).
  `skillctl version-bump <plugin>`.

### Keeping things fresh & healthy
- **Refresh** — pull the repo, update the marketplace, and force the installed clone to
  fast-forward (works around the bug where `claude plugin update` fetches but never merges).
  `skillctl refresh`, then `/reload-plugins`.
- **Doctor** — config, clones, marketplace registration, user-scope enablement, and drift
  between the installed clone and origin. `skillctl doctor` / `/skill-ops:skills-doctor`.

## How "auto-pull the latest" actually works

- **Edits to a skill's text** are picked up live — Claude Code watches skill directories, so
  changes take effect mid-session without a restart. New *top-level* skill directories need a
  restart.
- **New/changed skills inside an enabled plugin** arrive when the marketplace updates. With
  auto-update on, new sessions pick them up; for an immediate refresh run `skillctl refresh`
  then `/reload-plugins`.
- **A brand-new plugin** still has to be enabled where you want it (`skillctl enable`, or in
  `setup-project`). That's the one deliberate manual step — enabling is opt-in per project.

## Gotchas baked into the tooling

- **Auto-update defaults off** for third-party marketplaces — flip it on once (step 5 above).
- **Plugin skills are namespaced** — you invoke `/core:commit`, not `/commit`.
- **`claude plugin update` fetches without merging**, leaving the installed clone stale —
  `skillctl refresh` force-fast-forwards it as a workaround.
- **Project-scoped `/plugin install` doesn't always persist `enabledPlugins`** to project
  settings — so `skillctl` writes `.claude/settings.json` directly (merge-safe, with a `.bak`)
  as the reliable source of truth, rather than relying on the installer.

## Command reference

```
skillctl bootstrap --repo <owner/name> [--marketplace N] [--path P] [--user-plugins a,b]
skillctl setup-project [--plugins a,b,c] [--install]
skillctl enable <plugin>...            skillctl disable <plugin>...
skillctl promote <skill> [--plugin P] [-m msg] [--force] [--no-refresh]
skillctl sync <skill> [--plugin P] [--dry-run] [-m msg] [--no-refresh]
skillctl pull <skill> [--plugin P] [--force]
skillctl new-skill <name> [--project | --plugin P] [--description D]
skillctl new-plugin <name> [--description D]
skillctl list        skillctl validate        skillctl refresh        skillctl doctor
skillctl version-bump <plugin>
```
