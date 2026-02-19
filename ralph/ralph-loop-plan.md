# Ralph Loop Development Workflow — Implementation Plan

## Context

The Ralph Loop is an outer orchestration pattern that repeatedly invokes Claude Code CLI against file-based specifications. Each iteration gets a fresh context window, avoiding context rot. State persists on disk between iterations via progress files, PRD task lists, and memory files. A bash script drives the loop.

This plan builds a **standalone `ralph` plugin** under `claude-code/plugins/ralph/`, separate from the `zaksak` plugin. This keeps the ralph workflow self-contained and independently installable via the marketplace. The design draws from the synthesized research in `research/ralph-loops/`. Key differentiators from reference implementations: hooks-based safety and behavior control, explicit separation of loop-scoped vs repo-scoped memory, context-aware wrap-up guidance, and self-managing task iteration.

---

## File Layout

New plugin at `claude-code/plugins/ralph/`:

```
claude-code/plugins/ralph/
├── .claude-plugin/
│   └── plugin.json                          # NEW: plugin manifest
├── hooks/
│   ├── hooks.json                           # NEW: plugin hook definitions
│   └── scripts/
│       ├── block_dangerous_commands.py      # NEW: PreToolUse safety guard
│       ├── context_monitor.py              # NEW: PostToolUse context usage alerts
│       └── stop_loop_reminder.py            # NEW: Stop hook — PRD validation + enforce commit
├── scripts/
│   ├── ralph.sh                             # NEW: main loop runner
│   ├── ralph-init.sh                        # NEW: initialize a ralph loop in a project
│   └── ralph-archive.sh                     # NEW: archive a completed loop
└── templates/
    ├── prompt.md                            # NEW: per-iteration prompt template
    ├── prd-template.json                    # NEW: task list starter
    └── progress-template.md                 # NEW: progress log starter
```

Also update the root `marketplace.json` to register the new plugin.

When a user runs `ralph-init.sh` in their target project, it creates:

```
target-project/
├── ralph/
│   ├── prd.json          # Task list (copied from template, user fills in)
│   ├── progress.txt      # Append-only iteration log (loop-scoped memory)
│   └── prompt.md         # Iteration prompt (copied, customizable per-project)
└── .ralph-active          # Runtime marker (created by ralph.sh, gitignored)
```

---

## Components

### 1. Plugin Manifest

**File:** `claude-code/plugins/ralph/.claude-plugin/plugin.json`

```json
{
  "name": "ralph",
  "description": "Ralph Loop — autonomous agentic coding workflow with hooks-based safety, scoped memory, and self-managing task iteration",
  "version": "0.1.0",
  "hooks": "./hooks/hooks.json"
}
```

### 2. Marketplace Registration

**File:** `marketplace.json` (root) — add entry:

```json
{
  "name": "ralph",
  "source": "./claude-code/plugins/ralph",
  "description": "Ralph Loop — autonomous agentic coding workflow with hooks-based safety, scoped memory, and self-managing task iteration",
  "version": "0.1.0"
}
```

### 3. ralph.sh — Main Loop Runner

**File:** `claude-code/plugins/ralph/scripts/ralph.sh`

Core behavior:
- Iterates from 1 to `MAX_ITERATIONS` (default: 10), invoking `claude -p --dangerously-skip-permissions` each time with the prompt template
- Each iteration is a fresh process = fresh context window
- Uses `sed` to inject `$RALPH_ITERATION` and `$RALPH_MAX_ITERATIONS` into the prompt before piping to Claude
- Creates `.ralph-active` marker file on start (JSON with timestamp, pid, max_iterations) — hooks check for this file to activate ralph-specific behavior
- Registers `trap` to clean up `.ralph-active` on EXIT/INT/TERM
- Detects completion via `<promise>COMPLETE</promise>` in output, then verifies with `jq` that all PRD stories have `passes: true`
- Falls back to PRD-only check (if agent completed everything but forgot the tag)
- Streams output to terminal via `tee /dev/stderr` while capturing for promise detection
- Exits 0 on completion, 1 on max iterations reached

Arguments:
```
ralph.sh [OPTIONS]
  -n, --max-iterations N    Max loop iterations (default: 10)
  --ralph-dir PATH           Path to ralph/ directory (default: ./ralph)
  -d, --project-dir PATH    Project root (default: cwd)
  -m, --model MODEL         Claude model to use (e.g., opus, sonnet)
  -h, --help                Show usage
```

Dependencies: `jq` (for PRD verification), `claude` CLI.

### 4. Hook Scripts

**File:** `claude-code/plugins/ralph/hooks/hooks.json`

Wires three hooks across three events (PreToolUse, PostToolUse, Stop), plus a SessionStart cleanup:

All hook scripts are written in Python for consistency, robust JSON handling (no `jq` dependency), and cleaner PRD validation logic.

#### 4a. Dangerous Command Blocker (Always-on)

**File:** `hooks/scripts/block_dangerous_commands.py`
**Event:** `PreToolUse`, matcher: `Bash`
**Always active** — general safety for any session with the ralph plugin enabled

Reads JSON from stdin, extracts `tool_input.command`, checks against blocked patterns:
- `rm -rf`, `rm -fr`, any recursive forced delete
- `sudo rm`
- `chmod 777`
- Disk-level commands (`mkfs`, `dd if=`, `fdisk`)
- Force push to main/master
- Writing to raw devices

Exit 2 to block (stderr message shown to Claude), exit 0 to allow. Standard `rm` of individual files is intentionally allowed.

#### 4b. Context Monitor (Always-on, graduated alerts)

**File:** `hooks/scripts/context_monitor.py`
**Event:** `PostToolUse`, matcher: `.*`
**Always active** — fires after every tool call

Estimates context usage by parsing the session transcript file (available via `transcript_path` in hook stdin JSON). Uses a `FILE_SIZE / 4` chars-per-token heuristic against a 200k token window (configurable via `CLAUDE_CONTEXT_WINDOW` env var).

Fires graduated alerts at 5 thresholds — each threshold triggers only once per session:

| Threshold | Severity | Message |
|-----------|----------|---------|
| 50%, 60% | NOTICE | "Be mindful of remaining space. Plan to finish your current task within this session." |
| 70%, 80% | WARNING | "Finish your current task and commit soon. Do not start additional tasks." |
| 90% | CRITICAL | "Wrap up immediately — commit progress, update progress.txt, and stop. Do NOT start new work." |

**State tracking:** Uses `/tmp/claude-context-alerts-${SESSION_ID}` to record which thresholds have already fired. Each threshold fires once, then is suppressed for the rest of the session.

**Session cleanup:** A `SessionStart` hook (inline command in hooks.json) removes the state file at the start of each new session so thresholds re-arm.

**Output:** Returns JSON with `hookSpecificOutput.additionalContext` containing the alert message, which gets injected into Claude's context.

**Tuning:** If alerts fire too early, increase the chars-per-token divisor to 5–6. If too late, decrease to 3. After compaction the transcript file is not truncated, so estimates may run high post-compaction — this is conservative (alerts earlier, not later).

#### 4c. End-of-Loop Stop Reminder (Ralph-only)

**File:** `hooks/scripts/stop_loop_reminder.py`
**Event:** `Stop`
**Conditionally active:** only when `.ralph-active` exists

Runs two checks before allowing Claude to stop. Both must pass or the stop is blocked:

**Check 1: PRD schema validation** — Validates `ralph/prd.json` structure with `jq`:
- File exists and is valid JSON
- Required top-level fields: `project`, `branchName`, `description`, `userStories` (array)
- Every story has required fields: `id` (string), `title` (string), `passes` (boolean), `priority` (number), `acceptanceCriteria` (non-empty array)
- `id` values are unique (no duplicates)
- No story has `passes: true` with an empty `notes` field (enforce documentation of what was done)
- If validation fails → block with specific error describing which field/story is malformed

**Check 2: Uncommitted changes** — Checks `git status --porcelain`:
- If uncommitted changes exist → block, telling Claude to:
  1. Update `ralph/progress.txt` with what was accomplished + learnings
  2. Consider if any lasting patterns belong in CLAUDE.md or `.claude/rules/`
  3. Commit ALL changes including progress.txt and prd.json updates
- Claude must address the feedback and try stopping again

If both checks pass (valid PRD + no uncommitted changes), approves the stop.

### 5. Prompt Template

**File:** `claude-code/plugins/ralph/templates/prompt.md`

The prompt Claude receives each iteration. Structure:

1. **Header** — Identifies this as Ralph Loop iteration N of M
2. **Step 1: Orient** — Read progress.txt (especially Codebase Patterns section at top), read prd.json, check `git log` and `git status`
3. **Step 2: Select & Right-Size** — Pick highest-priority story where `passes: false` (respecting `dependsOn`). If too large for the context window (~60% of context is usable working space), break it into sub-stories in prd.json and work on the first one. Claude can also add new tasks, reorder priorities, or restructure the task list as needed.
4. **Step 3: Implement** — Read existing code first, follow patterns, implement one story, run project verification commands (from `prd.json.verifyCommands`)
5. **Step 4: Document Progress** — Append structured entry to progress.txt (what was done, files changed, verification results, learnings). Curate the Codebase Patterns section at the top with reusable discoveries
6. **Step 5: Consider Memory Updates** — Update CLAUDE.md or `.claude/rules/` ONLY for rules that persist beyond this ralph loop (e.g., "this project uses bun not npm"). Skip this step if nothing universal was learned
7. **Step 6: Commit & Signal** — Set `passes: true` in prd.json, commit with `feat: [US-xxx] - [Title]`, check if ALL stories complete → output `<promise>COMPLETE</promise>`

Hard rules embedded in the prompt:
- One story per iteration, never start a second
- Don't mark `passes: true` until verification passes
- Don't weaken tests to make them pass
- If stuck, document the blocker in progress.txt for the next iteration
- Claude may add/split/reorder stories in prd.json as needed (self-management)

### 6. PRD Template

**File:** `claude-code/plugins/ralph/templates/prd-template.json`

```json
{
  "project": "",
  "branchName": "ralph/feature-name",
  "description": "",
  "verifyCommands": [],
  "userStories": [
    {
      "id": "US-001",
      "title": "",
      "description": "",
      "acceptanceCriteria": [],
      "priority": 1,
      "passes": false,
      "notes": "",
      "dependsOn": []
    }
  ]
}
```

Key fields:
- `verifyCommands`: project-specific checks Claude runs each iteration (tests, lint, typecheck)
- `dependsOn`: ordering constraints between stories
- `passes`: boolean, toggled by Claude when acceptance criteria + verification pass
- `notes`: Claude appends implementation context for future iterations

### 7. Progress Template

**File:** `claude-code/plugins/ralph/templates/progress-template.md`

```markdown
# Ralph Progress Log
Started: {{DATE}}
PRD: {{PROJECT_NAME}}

## Codebase Patterns
- (Reusable patterns discovered during this loop)

---
```

Append-only after the `---`. The Codebase Patterns section at the top is curated (edited, not just appended) as the loop progresses.

### 8. Utility Scripts

#### ralph-init.sh

**File:** `claude-code/plugins/ralph/scripts/ralph-init.sh`

Usage: `ralph-init.sh [--project-dir PATH] [--name FEATURE_NAME]`

What it does:
1. Creates `ralph/` directory in the target project
2. Copies template files (prompt.md, prd-template.json → prd.json, progress-template.md → progress.txt)
3. Substitutes `{{DATE}}` and `{{PROJECT_NAME}}` in progress.txt
4. Sets `branchName` in prd.json to `ralph/<name>` if `--name` provided
5. Adds `.ralph-active` to `.gitignore` if not already there
6. Prints next-steps instructions

#### ralph-archive.sh

**File:** `claude-code/plugins/ralph/scripts/ralph-archive.sh`

Usage: `ralph-archive.sh [--project-dir PATH] [--label LABEL]`

What it does:
1. Creates `ralph-archive/<date>-<branch-or-label>/`
2. Moves prd.json and progress.txt to archive
3. Generates a `summary.md` (stories completed vs total, date range)
4. Resets `ralph/` to clean state with fresh templates
5. Commits the archive

---

## Implementation Order

1. **Plugin scaffold** — `.claude-plugin/plugin.json` + `marketplace.json` update
2. **Templates** — `prd-template.json`, `progress-template.md`, `prompt.md` (static files, no deps)
3. **Hook scripts** — `block_dangerous_commands.py`, `context_monitor.py`, `stop_loop_reminder.py` (all Python, standalone, testable independently)
4. **hooks.json** — Wire hooks to events (depends on hook scripts)
5. **ralph.sh** — Main loop runner (depends on templates for file layout knowledge)
6. **ralph-init.sh** — Initializer (depends on templates existing)
7. **ralph-archive.sh** — Archiver (depends on file layout)

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Plugin structure | Standalone `ralph` plugin | Self-contained, independently installable, doesn't bloat `zaksak` |
| Dangerous command blocker scope | Always-on | General safety, not just ralph loops |
| Task list mutability | Claude can modify | Enables self-management: splitting, adding, reordering tasks |
| Permission mode | `--dangerously-skip-permissions` | Fully autonomous; PreToolUse hook provides safety net |
| Context reminders | PostToolUse transcript-size monitor | Graduated alerts at 50/60/70/80/90% via chars-per-token heuristic on transcript file |
| Progress.txt format | Append-only with curated top section | Loop-scoped memory; patterns section is edited, entries are append-only |
| Memory file separation | progress.txt (loop) vs CLAUDE.md (repo) | Clear boundary: task state vs lasting conventions |
| Completion detection | Promise tag + PRD verification | Dual check prevents false completion signals |
| Hook language | All Python | Consistent codebase, built-in JSON handling (no `jq` dep), cleaner PRD validation |
| Prompt variable injection | `sed` substitution | No external dependency (vs `envsubst` requiring `gettext`) |

---

## Verification Plan

1. **Hook scripts** — Test each independently:
   - `echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' | python3 block_dangerous_commands.py` → should exit 2
   - `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 block_dangerous_commands.py` → should exit 0
   - Create a fake transcript file, pass its path via JSON stdin to `context_monitor.py` → verify alerts fire at correct thresholds and each threshold fires only once
   - Create `.ralph-active` → run `stop_loop_reminder.py` with valid/invalid prd.json → verify schema validation blocks on malformed PRD, passes on valid
   - Create `.ralph-active` → run `stop_loop_reminder.py` with uncommitted changes → should return block decision
2. **ralph-init.sh** — Run in a temp directory, verify all files created correctly
3. **ralph.sh** — Run with `--max-iterations 1` against a simple single-story PRD in a test project to verify the full loop
4. **ralph-archive.sh** — Run after a completed loop, verify archive structure and clean reset
5. **End-to-end** — Run a 2-3 story PRD through full ralph loop completion
