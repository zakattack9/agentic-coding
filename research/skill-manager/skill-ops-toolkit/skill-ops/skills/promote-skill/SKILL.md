---
name: promote-skill
description: Push a skill that was created locally inside this project up into the centralized skills repo so every project can use it. Use whenever the user builds or drafts a skill in a project and says "promote this", "push this skill to the central repo", "add this to my marketplace", "make this skill available everywhere", or otherwise wants a project-local skill centralized. Do not auto-run; this pushes to git.
disable-model-invocation: true
allowed-tools: Bash(skillctl *) Bash(git *)
argument-hint: "<skill-name> [--plugin <plugin>]"
---

# Promote a project skill to the central repo

Take a skill from this project's `.claude/skills/<name>/` and publish it into a plugin in the central marketplace repo, then refresh so it's available immediately. This replaces the manual round-trip of switching repos, copying, committing, and pulling.

## Steps

1. Identify the skill. If the user didn't name it, list `.claude/skills/*/` and ask which one. Confirm the skill directory has a `SKILL.md`.
2. Pick the destination plugin. Run `skillctl list` to show existing plugins. Ask which plugin it belongs in (default `core` for universal skills). If the right plugin doesn't exist yet, use the new-plugin skill first.
3. Run `skillctl promote <skill> --plugin <plugin>`. This copies the skill up, patch-bumps the plugin version, commits, pushes, updates the marketplace, and fast-forwards the installed clone.
4. If this project isn't already enabling that plugin, offer to run `skillctl enable <plugin>`.
5. Tell the user the skill is now invoked as `/<plugin>:<skill>` and to run `/reload-plugins` to use it in the current session.

Notes:
- If the skill already exists centrally, `skillctl promote` will stop and point you at the sync-skill instead. Don't pass `--force` unless the user explicitly wants to overwrite.
- Keep the original skill name; don't rename on promotion.
