---
name: sync-skill
description: Push local edits to a skill that already lives in the central repo back up to it, without leaving the project. Use whenever the user has iterated on a centralized skill inside a project (often after pulling it down) and says "sync this skill", "push my changes back", "update the central version", or "save these skill edits upstream". Shows a diff before writing. Do not auto-run; this pushes to git.
disable-model-invocation: true
allowed-tools: Bash(skillctl *) Bash(git *)
argument-hint: "<skill-name>"
---

# Sync local skill edits back to the central repo

For a skill that exists both in this project and in a central plugin, push the project's edits upstream. The tool auto-detects which plugin owns the skill and shows a diff before committing.

## Steps

1. Identify the skill name (ask if not given).
2. Run `skillctl sync <skill> --dry-run` to show the diff of what would change upstream. Show it to the user and confirm.
3. On confirmation, run `skillctl sync <skill>`. It copies the edits up, patch-bumps the plugin, commits, pushes, and refreshes the installed clone.
4. Tell the user to run `/reload-plugins` to pick up the change in the current session.

If the tool reports the skill isn't in any central plugin yet, use the promote-skill skill instead.

Related: the `skillctl pull <skill>` command copies a central skill *down* into the current project for local iteration — use that first if the user wants to hack on a central skill before syncing changes back.
