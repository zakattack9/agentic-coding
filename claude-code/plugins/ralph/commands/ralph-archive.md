---
description: Archive a completed Ralph Loop and reset for the next feature
argument-hint: [--label LABEL]
allowed-tools: Bash
---

Archive the completed Ralph Loop artifacts to `ralph-archive/` and reset `ralph/` with fresh templates.

```
!`${CLAUDE_PLUGIN_ROOT}/scripts/ralph-archive.sh --project-dir . $ARGUMENTS`
```

The archive includes tasks.json, progress.txt, prd.md, and a generated summary. The `ralph/` directory is reset for the next loop (prompt.md is preserved).
