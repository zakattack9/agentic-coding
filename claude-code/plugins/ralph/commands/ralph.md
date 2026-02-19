---
description: Start the Ralph Loop — iterates Claude against file-based specs
argument-hint: [--no-sandbox] [--skip-review] [--max-iterations N] [--model MODEL]
allowed-tools: Bash
---

Start the Ralph Loop runner. This invokes `ralph.sh` which iterates Claude Code CLI against the specifications in `ralph/`.

```
!`${CLAUDE_PLUGIN_ROOT}/scripts/ralph.sh --project-dir . $ARGUMENTS`
```

Common usage:
- `/ralph --no-sandbox --skip-review` — Direct mode, no review cycle (simplest)
- `/ralph --no-sandbox` — Direct mode with review cycle
- `/ralph --sandbox` — Docker Sandbox mode (requires Docker Desktop 4.58+)
- `/ralph --max-iterations 5` — Limit iterations
