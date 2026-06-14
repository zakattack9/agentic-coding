---
name: push
description: Publish a skill that lives in this project's .claude/skills/ up into the central marketplace, or sync local edits of an already-central skill back up. Auto-detects new vs update. Use when the user says "push this skill", "publish this skill", "promote this to my marketplace", "make this skill available everywhere", "sync my skill changes up", or "save these skill edits upstream". Authoring a skill from scratch is the native skill-creator skill's job — use this to centralize one that already exists. Pushes to git; user-invoked only.
disable-model-invocation: true
model: sonnet
effort: high
allowed-tools: Bash(python3 *) Bash(git *) Bash(ls *) Read Glob AskUserQuestion
argument-hint: "<skill-name> [--plugin <plugin>]"
---

# Push a skill to the central marketplace

Take a skill from this project's `.claude/skills/<name>/` and publish or update it in a central plugin, bump the plugin version (in `marketplace.json`), commit, and push — without leaving the project. The tool auto-detects whether the skill is new (publish) or already central (update, with a diff shown first).

## Steps

1. Identify the skill. If the user didn't name it, list `.claude/skills/*/` and ask which one. It must have a `SKILL.md`. (To create a skill first, use the native **skill-creator** skill — this plugin doesn't scaffold skills.)
2. When the skill may already be central, preview with a dry run, then show the diff and confirm:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push <skill> --dry-run
   ```
3. For a brand-new skill, decide the destination plugin (run `/skill-manager:status` to see options). The plugin is created and registered automatically if it doesn't exist.
4. Push:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" push <skill> [--plugin <plugin>]
   ```
5. Report the result: the skill is invoked as `/<plugin>:<skill>`; tell the user to `/reload-plugins`. **If the tool prints a push-failure WARNING, surface it prominently** — the change is committed locally but not on the remote until the push succeeds.
6. If this project doesn't enable that plugin yet, offer `/skill-manager:configure` (or `skillctl enable <plugin>`).

## Stay grounded — this writes to git

The engine does all the file/version/git work deterministically; your job is to feed it
correct inputs and report its results honestly. Two things prevent mistakes:

- **Get names from real data, never guess.** The project skill comes from `.claude/skills/`;
  the target plugin comes from `/skill-manager:status`. A mistyped `--plugin` silently
  creates a brand-new plugin, so confirm the name against the catalog before a new push.
- **Relay what the tool actually printed.** Only report a publish/sync as done if the tool
  printed its success line. If it printed a `WARNING` (e.g. the push failed) or an error,
  surface that verbatim — the change may be committed locally but not on the remote.

Notes:
- Keep the original skill name; don't rename on push.
- `--plugin` is only needed for a brand-new skill; for updates the owning plugin is auto-detected.
- To iterate on a central skill locally first, `skillctl pull <skill>` copies it down; edit, then push back.

## Output

Fill this skeleton from the engine's output, copying values verbatim. Drop any line whose condition doesn't apply:

**Result:** {Published / Updated / No change} — `/{plugin}:{skill}` (now v`{version}`)
**⚠️ Push failed:** {verbatim WARNING} — committed locally, not on the remote yet.
**Available:** in every project that enables `{plugin}` — new sessions pick it up; current ones after `/reload-plugins`.
**Next:** run `/reload-plugins` to use it here now.
**Enable here:** {only if this project doesn't enable `{plugin}`} → run `/skill-manager:configure`.
