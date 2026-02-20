# Ralph Loop Plugin

Autonomous agentic coding workflow for Claude Code. Ralph repeatedly invokes `claude -p` against file-based specifications, giving each iteration a fresh context window. State persists on disk between iterations via a task list, progress log, and PRD.

Key features:
- **Fresh-context review cycle** — every task must pass a review from a separate iteration before completion, preventing anchoring bias
- **Docker Sandbox isolation** (optional) — runs Claude inside a microVM for OS-level safety
- **Self-managing task iteration** — Claude can add, split, and reorder stories as it works
- **Graduated context alerts** — warns Claude as the context window fills up
- **Stop hook enforcement** — validates task list schema, review integrity, and legal state transitions before allowing Claude to stop

## Prerequisites

- **Claude Code CLI** installed on host
- **jq** — `brew install jq`
- **Docker Desktop 4.58+** with Sandboxes enabled (recommended, optional)
- macOS with Apple Silicon (primary target)

## Install

Add the marketplace, then install the ralph plugin:

```bash
/plugin marketplace add https://github.com/zakattack9/agentic-coding.git
/plugin install ralph
```

Or, if developing locally, add the plugin directly:

```bash
/plugin add ./claude-code/plugins/ralph
```

## Quick Start

### 1. Initialize a ralph loop in your project

```bash
cd /path/to/your/project
/path/to/ralph-init.sh --name my-feature
```

This creates a `ralph/` directory with:
- `prd.md` — fill in your requirements (what to build, constraints, technical design)
- `tasks.json` — user stories that Claude works through one per iteration
- `progress.txt` — append-only iteration log (loop-scoped memory)
- `prompt.md` — the prompt Claude receives each iteration (customizable)

### 2. Plan your feature

Either fill in `ralph/prd.md` and `ralph/tasks.json` manually, or use the interactive planner:

```
/ralph-plan
```

The skill asks clarifying questions until the spec is clear, then generates both the PRD and a right-sized task list.

### 3. Run the loop

```bash
# Recommended: sandbox mode (auto-detected if Docker is available)
ralph.sh

# Direct mode (no Docker, uses --dangerously-skip-permissions)
ralph.sh --no-sandbox

# Skip the review cycle for low-stakes tasks
ralph.sh --skip-review

# Limit iterations
ralph.sh --max-iterations 10
```

### 4. Archive when done

```bash
ralph-archive.sh --label v1
```

Moves completed artifacts to `ralph-archive/`, generates a summary, and resets `ralph/` for the next feature.

## How It Works

Each iteration, `ralph.sh`:
1. Reads `tasks.json` and determines the **iteration mode** based on story state
2. Writes a pre-iteration snapshot to `.ralph-active` (used by the stop hook for transition validation)
3. Injects the iteration number into the prompt template
4. Invokes `claude -p` with the prompt (fresh context every time)
5. Checks for completion (`<promise>COMPLETE</promise>` tag or tasks.json verification)

### Iteration Modes

| Mode           | Trigger                                         | What happens                                                     |
| -------------- | ----------------------------------------------- | ---------------------------------------------------------------- |
| **Implement**  | Story has `passes: false`, `reviewStatus: null` | Claude implements the story, sets `reviewStatus: "needs_review"` |
| **Review**     | Story has `reviewStatus: "needs_review"`        | Fresh-context review: approve or request changes                 |
| **Review-Fix** | Story has `reviewStatus: "changes_requested"`   | Address review feedback, resubmit for review                     |

Priority: Review-Fix > Review > Implement. This ensures feedback is addressed before new work begins.

### Review Lifecycle

```
null/false ──implement──> needs_review/false ──review──> approved/true  (done)
                                                    └──> changes_requested/false
                                                              │
                                                         review-fix
                                                              │
                                                              └──> needs_review/false (re-review)
```

The stop hook enforces that only review iterations can approve stories. Implementation iterations cannot set `passes: true` — this is validated against a pre-iteration snapshot, not just prompt instructions.

## Options Reference

```
ralph.sh [OPTIONS]
  -n, --max-iterations N    Max loop iterations (default: 15)
  --ralph-dir PATH          Path to ralph/ directory (default: ./ralph)
  -d, --project-dir PATH    Project root (default: cwd)
  -m, --model MODEL         Claude model to use (e.g., opus, sonnet)
  --sandbox                 Force Docker Sandbox mode (error if unavailable)
  --no-sandbox              Force direct mode
  --skip-review             Disable fresh-context review cycle
  --review-cap N            Max reviews per story before auto-approve (default: 5)
  -h, --help                Show usage

ralph-init.sh [OPTIONS]
  --project-dir PATH        Project root (default: cwd)
  --name FEATURE_NAME       Feature name (sets branch name and progress log header)
  --force                   Overwrite existing ralph/ directory
  -h, --help                Show usage

ralph-archive.sh [OPTIONS]
  --project-dir PATH        Project root (default: cwd)
  --label LABEL             Archive label (default: git branch name)
  -h, --help                Show usage
```

## Hooks

The plugin registers three hooks that activate automatically:

| Event            | Script                  | Behavior                                                                                                                                                       |
| ---------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PostToolUse**  | `context_monitor.py`    | Graduated context usage alerts at 50/60/70/80/90%                                                                                                              |
| **Stop**         | `stop_loop_reminder.py` | Validates tasks.json schema, review integrity, legal transitions, and uncommitted changes. Only active when `.ralph-active` exists (i.e., during a ralph loop) |
| **SessionStart** | inline                  | Cleans up context monitor state files                                                                                                                          |

## File Layout

After initialization, your project will have:

```
your-project/
├── ralph/
│   ├── prd.md            # Requirements (you write this, Claude reads it)
│   ├── tasks.json        # Execution state (Claude modifies this)
│   ├── progress.txt      # Iteration log (Claude appends to this)
│   └── prompt.md         # Iteration prompt (customizable)
└── .ralph-active          # Runtime marker (auto-created, gitignored)
```

## tasks.json Schema

```json
{
  "project": "my-project",
  "branchName": "ralph/my-feature",
  "description": "Feature description",
  "verifyCommands": ["npm test", "npm run lint"],
  "userStories": [
    {
      "id": "US-001",
      "title": "Story title",
      "description": "What to build",
      "acceptanceCriteria": ["Specific, verifiable criterion"],
      "priority": 1,
      "passes": false,
      "reviewStatus": null,
      "reviewCount": 0,
      "reviewFeedback": "",
      "notes": "",
      "dependsOn": []
    }
  ]
}
```

Key fields:
- **passes** — only set to `true` by review iterations after approval
- **reviewStatus** — `null` | `"needs_review"` | `"changes_requested"` | `"approved"`
- **reviewCount** — incremented each review; auto-approves at the review cap
- **verifyCommands** — run by Claude each iteration to validate changes
- **dependsOn** — story IDs that must complete before this story starts
