---
name: ralph-install
description: Install Ralph Loop scripts and templates into the current project's .ralph/ directory
allowed-tools: Bash(curl:*), Bash(chmod:*)
---

# Ralph Install — Per-Project Setup

!`curl -fsSL https://raw.githubusercontent.com/zakattack9/agentic-coding/main/claude-code/plugins/ralph/scripts/ralph-install.sh | bash`

## Result

The install script above has been executed. Report the output to the user.

If the install succeeded, tell the user their next steps:

1. **Plan the feature (Claude Code):** Run `/ralph-plan` to interactively generate a PRD and task list
2. **Initialize a loop (terminal):** `.ralph/scripts/ralph-init.sh --name my-feature`
3. **Run the loop (terminal):** `.ralph/scripts/ralph.sh` (use `--no-sandbox` if Docker is unavailable)

Note: Only `/ralph-plan` runs inside Claude Code. Initialization and running the loop must be done from the terminal.
