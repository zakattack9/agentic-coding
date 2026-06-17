---
name: push
description: Publish a skill from this project (its .claude/skills/, a plain folder, or ~/.claude/skills/) up into the central marketplace, or sync local edits of an already-central skill back up. Auto-detects new vs update. Use when the user says "push this skill", "publish this skill", "promote this to my marketplace", "make this skill available everywhere", "sync my skill changes up", or "save these skill edits upstream". Authoring a skill from scratch is the native skill-creator skill's job — use this to centralize one that already exists. Pushes to git; user-invoked only.
model: claude-sonnet-4-6
effort: medium
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *) AskUserQuestion
argument-hint: "[skill-name] [--from <dir>] [--md <file>] [--plugin <plugin>]"
---

# Push a skill to the central marketplace

Take a skill from this project's `.claude/skills/<name>/` and publish or update it in a central plugin, bump the plugin version (in `marketplace.json`), commit, and push — without leaving the project. The tool auto-detects whether the skill is new (publish) or already central (update, with a diff shown first).

## Steps

1. Identify the skill(s). If the user already named one (as an arg or in chat), use it and skip to step 2. Otherwise **show the engine's numbered menu of local skills** and let them pick by number — the engine does the discovery and resolves the index itself, so you never glob or map names:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push --list
   ```
   **Reproduce the menu in your reply inside a fenced ``` block** — copy it verbatim (numbers, paths, notes) so the user can read it without expanding the raw tool output. Then ask in plain text for the number(s) to push — one (`3`), several (`1 3 5`), or a range (`1-3`); this open-ended reply doesn't fit `AskUserQuestion`'s fixed options. Pass it through with `--select`:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push --select "<number(s)>" [--plugin <plugin>] [--md <file>]
   ```
   - **One number** → the single-skill flow below (steps 2–6): preview, then push.
   - **Several numbers or a range** → a batch; jump to **Pushing several at once** below.

   The menu covers `.claude/skills/*`, `~/.claude/skills/*`, `skills/*`, and plain folders in the cwd that have a `SKILL.md`. A skill is a folder with at least one root-level `.md` (its definition — usually `SKILL.md`, sometimes a differently-named `.md`, which is published **as `SKILL.md`** automatically; your local copy is unchanged). If the skill lives somewhere else, point at it with `--from <dir>` (works with both `--list` and a named skill). To create a skill first, use the native **skill-creator** skill — this plugin doesn't scaffold skills.
   In the commands below, **`<skill>` is whichever identifier you settled on** — the skill name, or `--select "<number>"` from the menu. Keep using the same one (plus `--from <dir>` if you used it) through every re-run.

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

## Pushing several at once

When the user picks more than one number (`1 3 5` or `1-3`), the engine runs a **batch**: it pushes every skill that's ready and **skips the rest, with a reason for each** — so nothing is guessed and one problem skill never blocks the others. Each pushed skill is its own commit.

1. **Preview** with `--dry-run` (writes nothing) and reproduce the result in your reply so the user sees what's ready vs skipped:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push --select "1 3 5" --dry-run
   ```
2. **Push** the ready ones (same `--select`, drop `--dry-run`):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push --select "1 3 5"
   ```
3. Report the engine's `pushed` / `skipped` lists verbatim with the **Batch output** skeleton. A batch never auto-creates a plugin or guesses an ambiguous target — it skips a skill when it needs a decision: **not central yet** (needs a target `--plugin`), **name in multiple plugins** (needs `--plugin`), **multiple root `.md` files** (needs `--md`), **already up to date**, or it **wouldn't pass validation**. Offer to reconcile each skipped skill by pushing it **on its own** — `push --select "<its number>"` or `push <name> --plugin <plugin>` — which runs the full single-skill flow (steps 2–6) with the disambiguation prompts.

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

**Batch output** (when several skills were selected) — copy the engine's two lists verbatim:

**Pushed ({n}):** {`/{plugin}:{skill}` (now v`{version}`) for each, or "none were ready"}
**Skipped ({n}):** {`{skill}` — {verbatim reason} for each} — reconcile each by pushing it on its own.
**⚠️ Push failed:** {verbatim WARNING, if any} — those changes are committed locally, not on the remote yet.
**Use them (required when anything was pushed):** `/plugin marketplace update {marketplace}` then `/reload-plugins`.
