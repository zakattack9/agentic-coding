---
name: setup-project
description: Configure which centralized skill plugins this project uses and write them into the project's .claude/settings.json. Use this whenever the user opens a new repo and wants to wire up their skills, says "set up skills for this project", "which skills does this project use", "configure plugins here", or starts working somewhere that has no .claude/settings.json yet.
disable-model-invocation: true
allowed-tools: Bash(skillctl *) Bash(git *)
argument-hint: "[plugin,plugin,...]"
---

# Set up skills for this project

Wire the central marketplace into the current project and enable the plugins it needs. The selection is written into `.claude/settings.json` (merged, never clobbered), committed with the repo, and auto-applies to every future session here.

## Steps

1. Run `skillctl list` to show the catalog and what (if anything) is already enabled in this project.
2. If the user already named plugins (in arguments or the message), use those. Otherwise run `skillctl setup-project` with no `--plugins` flag first to see the auto-detected suggestions from the project's files, then present the suggestion and ask the user to confirm or adjust the set. Ask at most one question; offer the detected plugins plus the other catalog entries as options.
3. Write the config: `skillctl setup-project --plugins <comma,separated,list>`.
4. Tell the user to run `/reload-plugins` (or start a new session) so the plugins load now. New sessions will pick them up automatically.

If `skillctl` reports a plugin "not in catalog yet", surface that — the user may have mistyped, or may want to create it with the new-plugin skill.
