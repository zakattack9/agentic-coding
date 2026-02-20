---
name: ralph-install
description: Install Ralph Loop scripts and templates into the current project's .ralph/ directory
---

# Ralph Install — Per-Project Setup

This skill sets up a project for Ralph Loop by downloading scripts and templates into a `.ralph/` directory.

## What to Do

Run the following command to install Ralph into the current project:

```bash
curl -fsSL https://raw.githubusercontent.com/zakattack9/agentic-coding/main/claude-code/plugins/ralph/scripts/ralph-install.sh | bash
```

### Version Pinning

To pin to a specific branch or tag, pass `--branch`:

```bash
curl -fsSL https://raw.githubusercontent.com/zakattack9/agentic-coding/main/claude-code/plugins/ralph/scripts/ralph-install.sh | bash -s -- --branch v1.0
```

## What It Creates

```
.ralph/
├── scripts/
│   ├── ralph.sh           # Main loop runner
│   ├── ralph-init.sh      # Initialize state files for a new feature
│   └── ralph-archive.sh   # Archive completed loop artifacts
├── templates/
│   ├── prompt.md           # Iteration prompt template
│   ├── prd-template.md     # PRD scaffold
│   ├── tasks-template.json # Task list scaffold
│   └── progress-template.md # Progress log scaffold
└── sandbox/
    └── setup.sh            # Docker sandbox auth setup
```

## Next Steps

After installation, tell the user:

1. **Initialize a feature:** `.ralph/scripts/ralph-init.sh --name my-feature`
2. **Plan the feature:** `/ralph-plan` to interactively generate PRD and task list
3. **Run the loop:** `.ralph/scripts/ralph.sh --no-sandbox` (or omit `--no-sandbox` if Docker is available)
