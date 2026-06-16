---
name: push
description: Publish a skill from this project (its .claude/skills/, a plain folder, or ~/.claude/skills/) up into the central marketplace, or sync local edits of an already-central skill back up. Auto-detects new vs update. Use when the user says "push this skill", "publish this skill", "promote this to my marketplace", "make this skill available everywhere", "sync my skill changes up", or "save these skill edits upstream". Authoring a skill from scratch is the native skill-creator skill's job — use this to centralize one that already exists. Pushes to git; user-invoked only.
model: claude-sonnet-4-6
effort: medium
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *) Bash(ls *) Read Glob AskUserQuestion
argument-hint: "<skill-name> [--from <dir>] [--md <file>] [--plugin <plugin>]"
---

# Push a skill to the central marketplace

Take a skill from this project's `.claude/skills/<name>/` and publish or update it in a central plugin, bump the plugin version (in `marketplace.json`), commit, and push — without leaving the project. The tool auto-detects whether the skill is new (publish) or already central (update, with a diff shown first).

## Steps

1. Identify the skill. A skill is a folder with **at least one root-level `.md` file** — its definition, usually `SKILL.md` but sometimes a differently-named `.md`. A folder with no root `.md` is just code, so skip it (this scoping is what keeps auto-detect from matching random source folders). Discover candidates the way the engine resolves them, **preferring `SKILL.md`**: the canonical `.claude/skills/*/`, any folder with a `SKILL.md` (Glob `*/SKILL.md`), then plain folders in the current directory that hold a root `.md` (Glob `*/*.md`) — excluding obvious non-skill dirs like `node_modules`, `.git`, `dist`, `build` — plus `~/.claude/skills/*/` and `skills/*/`. If the user didn't name one, list the candidates and ask which with `AskUserQuestion`. If it lives somewhere non-standard, add `--from <dir>`. A non-`SKILL.md` definition file is published **as `SKILL.md`** automatically (your local copy is left unchanged), since Claude Code only loads skills from `SKILL.md`. **Respect the 4-option cap:** `AskUserQuestion` shows at most 4 options, so if there are more than 4 candidate skills, **page through them** rather than dropping any — offer 3 plus a `Show more (N left)…` option and re-ask with the next batch when picked (the auto-added "Other" lets them type the exact name/path to skip paging). (To create a skill first, use the native **skill-creator** skill — this plugin doesn't scaffold skills.)
2. When the skill may already be central, preview with a dry run, then show the diff and confirm:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push <skill> [--from <dir>] --dry-run
   ```
3. For a brand-new skill, decide the destination plugin (run `/skill-manager:status` to see options). The plugin is created and registered automatically if it doesn't exist.
4. Push:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push <skill> [--from <dir>] [--md <file>] [--plugin <plugin>]
   ```
   **If the engine prints `AMBIGUOUS-MD: ... multiple root .md files and no SKILL.md: a.md, b.md`,** the folder has several root markdown files and the engine won't guess which is the skill. Use `AskUserQuestion` to ask which one is the skill definition, then re-run with `--md <their choice>` (it'll be published as `SKILL.md`).
   **If the engine prints `AMBIGUOUS: '<skill>' exists in multiple plugins: X, Y`,** the same skill name is already central in more than one plugin and the engine won't guess. Use `AskUserQuestion` to ask which plugin to target (one option per listed plugin), then re-run the push with `--plugin <their choice>`.
5. Report the result using the **Output** skeleton: the skill is invoked as `/<plugin>:<skill>`. **If the tool prints a push-failure WARNING, surface it prominently** — the change is committed locally but not on the remote until the push succeeds. Be sure the user sees the two-command marketplace-update + reload steps the engine prints (`/plugin marketplace update <marketplace>` then `/reload-plugins`): custom marketplaces don't auto-refresh, so `/reload-plugins` alone won't pick up the new version.
6. If this project doesn't enable that plugin yet, offer `/skill-manager:configure` (or `skillctl enable <plugin>`).

## Stay grounded — this writes to git

The engine does all the file/version/git work deterministically; your job is to feed it
correct inputs and report its results honestly. Two things prevent mistakes:

- **Get names from real data, never guess.** The project skill comes from a real folder with
  a `SKILL.md` (see step 1); the target plugin comes from `/skill-manager:status`. A mistyped
  `--plugin` silently creates a brand-new plugin, so confirm the name against the catalog
  before a new push.
- **Relay what the tool actually printed.** Only report a publish/sync as done if the tool
  printed its success line. If it printed a `WARNING` (e.g. the push failed) or an error,
  surface that verbatim — the change may be committed locally but not on the remote.

Notes:
- Keep the original skill name (the folder name); don't rename it on push. The *definition markdown*, however, is always published as `SKILL.md` — if the source file is named differently, the central copy is renamed (source untouched).
- `--plugin` is only needed for a brand-new skill; for updates the owning plugin is auto-detected.
- To iterate on a central skill locally first, `skillctl pull <skill>` copies it down; edit, then push back.

## Output

Fill this skeleton from the engine's output, copying values verbatim. Drop any line whose condition doesn't apply:

**Result:** {Published / Updated / No change} — `/{plugin}:{skill}` (now v`{version}`)
**⚠️ Push failed:** {verbatim WARNING} — committed locally, not on the remote yet.
**Available:** in every project that enables `{plugin}`, once that project refreshes the marketplace.
**Enable here:** {only if this project doesn't enable `{plugin}`} → run `/skill-manager:configure` first.
**Use it (required after every push):** custom marketplaces don't reliably auto-update — not even new sessions — so run these two commands each time to pick up the change (substitute the real marketplace name for `{marketplace}`): `/plugin marketplace update {marketplace}` then `/reload-plugins`.
