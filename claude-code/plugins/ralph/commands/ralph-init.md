---
description: Initialize a Ralph Loop in the current project
argument-hint: [--name FEATURE_NAME] [--force]
allowed-tools: Bash
---

Run the Ralph Loop initialization script to set up the `ralph/` directory with template files.

```
!`${CLAUDE_PLUGIN_ROOT}/scripts/ralph-init.sh --project-dir . $ARGUMENTS`
```

After initialization, edit `ralph/prd.md` with your requirements, then run `/ralph-plan` to generate tasks or fill in `ralph/tasks.json` manually.
