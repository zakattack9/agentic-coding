---
name: ralph-init
description: Initialize a new Ralph Loop in the current project with state files from templates
argument-hint: [--name feature-name] [--force]
---

# Ralph Init — Initialize Loop State

!`.ralph/scripts/ralph-init.sh $ARGUMENTS`

## Result

The init script above has been executed. Report the output to the user.

If the init succeeded, tell the user their next steps:

1. **Plan the feature (Claude Code):** Run `/ralph-plan` to interactively generate a PRD and task list
2. **Run the loop (terminal):** `.ralph/scripts/ralph.sh` (use `--no-sandbox` if Docker is unavailable)

If the init failed because `.ralph/templates/` was not found, tell the user to run `/ralph-install` first.

If the init failed because state files already exist, tell the user they can pass `--force` to overwrite (e.g., `/ralph-init --force`).
