# Ralph Loop — Implementation Checklist

Derived from `ralph-loop-plan.md`. Each phase is scoped to fit within a single Claude Code session (~140k tokens). Phases are sequential — each builds on the prior.

Reference docs (read before starting relevant phase):
- `ralph/docker-sandbox-isolation.md` — Sandbox architecture, network policies, file sync caveats
- `ralph/sandbox-test-results.md` — Feasibility tests, create+exec+run pattern, auth DX (**read before Phase 1 task 1.5**)
- `ralph/pretooluse-hook-reference.md` — PreToolUse hook fallback patterns (**not implemented in MVP — documented for reference**)
- `ralph/context-monitor-hook.md` — Context monitor design notes (**read before Phase 3 task 3.1**)

Target directory: `claude-code/plugins/ralph/`

---

## Phase 1: Plugin Scaffold & Static Templates

**Goal:** Create the ralph plugin directory structure, manifest, marketplace registration, and all non-logic template files. After this phase, `ralph-init.sh` (Phase 5) will have all templates to copy.

### 1.1 — Create plugin directory structure

Create the full directory tree under `claude-code/plugins/ralph/`:

```
claude-code/plugins/ralph/
├── .claude-plugin/
├── hooks/
│   └── scripts/
├── sandbox/
├── scripts/
├── skills/
└── templates/
```

**Acceptance criteria:**
- [ ] All directories exist
- [ ] No files yet (directories only)

### 1.2 — Create plugin manifest

**File:** `claude-code/plugins/ralph/.claude-plugin/plugin.json`

**Acceptance criteria:**
- [ ] Valid JSON with `name`, `description`, `version`, `hooks` fields
- [ ] `hooks` field is `"./hooks/hooks.json"` — plain relative path starting with `./` (per manifest path rules; `${CLAUDE_PLUGIN_ROOT}` is NOT used here — it's used inside hooks.json for script command paths)
- [ ] Version is `0.1.0`

### 1.3 — Register plugin in marketplace

**File:** `marketplace.json` (repo root)

**Acceptance criteria:**
- [ ] New entry added to the `plugins` array
- [ ] `source` points to `./claude-code/plugins/ralph`
- [ ] Existing `zaksak` entry is unchanged
- [ ] File is valid JSON

### 1.4 — Create PRD template

**File:** `claude-code/plugins/ralph/templates/prd-template.md`

Per §7 of the plan. Sections 1–10 with HTML comment annotations explaining what to write. Complexity tier annotations (S-Patch to L-Epic) on each section header.

**Acceptance criteria:**
- [ ] All 10 sections present: Summary, Problem Statement, Goals, Non-Goals, Background & Context, Technical Design (with subsections 6a–6e), Constraints, Edge Cases & Error Handling, Risks & Mitigations, Open Questions
- [ ] Each section has an HTML comment explaining what to write and which complexity tiers it applies to
- [ ] Technical Design has subsections: Database Changes, API Contracts, Core Logic Changes, Frontend Changes, Infrastructure/Config Changes
- [ ] Template is ready for a human to fill in (placeholder text, not lorem ipsum)

### 1.5 — Create tasks template

**File:** `claude-code/plugins/ralph/templates/tasks-template.json`

Per §8 of the plan. The starter JSON structure that gets copied into target projects.

**Acceptance criteria:**
- [ ] Valid JSON matching the schema in §8 exactly
- [ ] Single example story with all required fields: `id`, `title`, `description`, `acceptanceCriteria` (array), `priority`, `passes` (false), `reviewStatus` (null), `reviewCount` (0), `reviewFeedback` (""), `notes`, `dependsOn` (array)
- [ ] Top-level fields: `project`, `branchName`, `description`, `verifyCommands` (array), `userStories` (array)
- [ ] Parseable by `jq`

### 1.6 — Create progress template

**File:** `claude-code/plugins/ralph/templates/progress-template.md`

Per §9 of the plan. Minimal scaffold with `{{DATE}}` and `{{PROJECT_NAME}}` placeholders for `ralph-init.sh` to substitute.

**Acceptance criteria:**
- [ ] Contains `{{DATE}}` and `{{PROJECT_NAME}}` substitution tokens
- [ ] Has "Codebase Patterns" section at top (empty, with placeholder bullet)
- [ ] Has `---` separator after the patterns section
- [ ] Matches the structure in §9

### 1.7 — Create sandbox setup script

**File:** `claude-code/plugins/ralph/sandbox/setup.sh`

Per §4 of the plan. Auth symlink setup + git config, run via `docker sandbox exec -u root`. Reference `sandbox-test-results.md` for the working pattern.

**Acceptance criteria:**
- [ ] Sets up symlinks from sandbox agent home to `$STATE_DIR/.claude` and `$STATE_DIR/.claude.json`
- [ ] Configures git user.email and user.name inside sandbox
- [ ] Uses correct paths (`/home/agent/` for sandbox agent user)
- [ ] Handles `chown -h agent:agent` for symlinks
- [ ] Removes existing `.claude` / `.claude.json` before symlinking (idempotent)
- [ ] Documents that `~/.dclaude_state/.claude.json` must contain valid JSON (`{}` minimum) — `touch` creates an empty file that causes JSON parse errors on sandbox startup (see plan §4)
- [ ] Script is executable (`chmod +x`)
- [ ] Comments explain what each section does

### 1.8 — Commit Phase 1

**Acceptance criteria:**
- [ ] All files from 1.1–1.7 committed on a feature branch
- [ ] Commit message: `feat(ralph): scaffold plugin structure and static templates`

---

## Phase 2: Prompt Template

**Goal:** Create the core iteration prompt — the document Claude receives every iteration. This is the most carefully-crafted artifact in the entire plan. It defines all three iteration modes and the full lifecycle.

### 2.1 — Create prompt template

**File:** `claude-code/plugins/ralph/templates/prompt.md`

Per §6 of the plan. Must include `{{RALPH_ITERATION}}` and `{{RALPH_MAX_ITERATIONS}}` substitution tokens for `ralph.sh` to inject via `sed`.

**Structure (all required):**

1. **Header** — Ralph Loop iteration identifier with substitution tokens
2. **Step 1: Orient** — Instructions to read progress.txt (especially Codebase Patterns), prd.md, tasks.json, git log/status
3. **Step 2: Select & Determine Mode** — Mode priority logic (Review-Fix > Review > Implement), story selection rules
4. **Step 3-implement** — Implementation workflow: read code first, follow patterns, implement, run verifyCommands, best-effort self-review (run `git diff`, check each AC, look for edge cases), commit
5. **Step 3-review** — Fresh-context review: increment `reviewCount`, read ACs, git log/diff for story changes, verify each AC individually, run verifyCommands, decision tree (approve / changes_requested / auto-approve at cap)
6. **Step 3-review-fix** — Address review feedback: read `reviewFeedback`, fix each issue, run verifyCommands, self-review, set `reviewStatus: "needs_review"`
7. **Step 4: Document Progress** — Append structured entry to progress.txt with iteration mode in header, curate Codebase Patterns
8. **Step 5: Consider Memory Updates** — CLAUDE.md / `.claude/rules/` for universal learnings only
9. **Step 6: Commit & Signal** — Mode-appropriate commit messages, completion check (`<promise>COMPLETE</promise>`)
10. **Hard Rules** — One story per iteration, implement never sets `passes: true`, don't weaken tests, document blockers, prd.md is read-only, review doesn't fix code, review-fix addresses ALL feedback
11. **Skip-review mode section** — Behavior when `.ralph-active` has `skipReview: true`

**Acceptance criteria:**
- [ ] All 11 structural sections present and complete
- [ ] `{{RALPH_ITERATION}}` and `{{RALPH_MAX_ITERATIONS}}` tokens present in header
- [ ] Three mode variants for Step 3 are clearly delineated
- [ ] Mode priority documented: Review-Fix > Review > Implement
- [ ] Review decision tree includes all three outcomes: approve, changes_requested, auto-approve at cap
- [ ] Commit message formats match §6: `feat:`, `review:`, `fix:` prefixes
- [ ] `<promise>COMPLETE</promise>` signal documented with dual condition (all `passes: true` AND all `reviewStatus: "approved"`)
- [ ] Prompt instructs Claude to read `.ralph-active` for runtime config: `skipReview` (determines mode availability) and `reviewCap` (determines auto-approve threshold in review mode)
- [ ] Hard rules section is explicit and unambiguous
- [ ] Skip-review mode behavior clearly documented as a separate section
- [ ] Self-review in implement/review-fix modes is described as advisory (not enforced)
- [ ] Context size awareness: mentions that stories too large for the context window should be split
- [ ] `dependsOn` ordering respected in story selection
- [ ] Task self-management rules: Claude may add/split/reorder stories, but prd.md is read-only

### 2.2 — Commit Phase 2

**Acceptance criteria:**
- [ ] prompt.md committed
- [ ] Commit message: `feat(ralph): add iteration prompt template with three-mode review lifecycle`

---

## Phase 3: Hook Scripts

**Goal:** Implement both hook scripts (context_monitor.py, stop_loop_reminder.py) and the hooks.json wiring. This phase contains the most complex logic in the plan — the stop hook's state machine validation.

Read `ralph/context-monitor-hook.md` before starting 3.1.

### 3.1 — Create context monitor hook

**File:** `claude-code/plugins/ralph/hooks/scripts/context_monitor.py`

Per §5a of the plan. PostToolUse hook that estimates context usage from transcript file size.

**Acceptance criteria:**
- [ ] Reads hook input from stdin as JSON (gets `session_id` and `transcript_path`)
- [ ] Estimates token usage: `FILE_SIZE / 4` chars-per-token against 200k window (or `CLAUDE_CONTEXT_WINDOW` env var)
- [ ] Fires graduated alerts at 5 thresholds: 50%, 60% (NOTICE), 70%, 80% (WARNING), 90% (CRITICAL)
- [ ] Each threshold fires only once per session via state file at `/tmp/claude-context-alerts-${SESSION_ID}`
- [ ] Alert messages match the three severity tiers from §5a (NOTICE/WARNING/CRITICAL wording)
- [ ] Returns valid hook JSON: `{"hookSpecificOutput": {"additionalContext": "<message>"}}`
- [ ] Returns empty/neutral JSON when no alert fires
- [ ] Handles missing transcript file gracefully (no crash, no alert)
- [ ] Script is executable

### 3.2 — Create stop loop reminder hook

**File:** `claude-code/plugins/ralph/hooks/scripts/stop_loop_reminder.py`

Per §5b of the plan. Stop hook with 4 checks. The most logic-dense file in the plugin.

**Check 1 — Task list schema validation:**
- [ ] Validates `ralph/tasks.json` exists and is valid JSON
- [ ] Validates required top-level fields: `project`, `branchName`, `description`, `userStories` (array)
- [ ] Validates every story has required fields: `id` (string), `title` (string), `passes` (boolean), `priority` (number), `acceptanceCriteria` (non-empty array), `reviewStatus` (null or one of `"needs_review"`, `"changes_requested"`, `"approved"`), `reviewCount` (non-negative integer), `reviewFeedback` (string)
- [ ] Validates `id` values are unique (no duplicates)
- [ ] Validates no story has `passes: true` with empty `notes`
- [ ] Blocks with specific error describing which field/story is malformed

**Check 2 — Review integrity enforcement (state invariants):**
- [ ] Skipped entirely when `.ralph-active` contains `"skipReview": true`
- [ ] Every story with `passes: true` must have `reviewStatus: "approved"` — blocks with specific message if not
- [ ] Every story with `reviewStatus: "approved"` must have `passes: true` — bidirectional sync
- [ ] `reviewStatus: "changes_requested"` requires non-empty `reviewFeedback`
- [ ] `reviewCount` must be non-negative and not exceed `reviewCap + 1`

**Check 2.5 — Transition validation (state transitions):**
- [ ] Skipped entirely when `.ralph-active` contains `"skipReview": true`
- [ ] Skipped with warning if `preIterationSnapshot` or `iterationMode` missing from `.ralph-active`
- [ ] Reads `iterationMode` and `preIterationSnapshot` from `.ralph-active`
- [ ] **Implement mode rules:** All existing stories' `passes`, `reviewStatus`, `reviewCount` must be unchanged EXCEPT at most one story may transition `reviewStatus: null → "needs_review"`. No story may have `passes` changed to `true`, `reviewStatus` changed to `"approved"`, or `reviewCount` changed at all. New stories allowed but must start at `passes: false, reviewStatus: null, reviewCount: 0`
- [ ] **Review mode rules:** Exactly one story's review fields may change. `reviewCount` must increment by exactly 1. Story transitions to either (approved + passes=true) or (changes_requested + non-empty reviewFeedback). No other story's review fields modified
- [ ] **Review-fix mode rules:** One story: `reviewStatus: "changes_requested" → "needs_review"`, `reviewFeedback` cleared, `passes` stays false, `reviewCount` unchanged. No other story's review fields modified
- [ ] Error messages include story ID and specific field/transition that violated rules

**Check 3 — Uncommitted changes:**
- [ ] Runs `git status --porcelain`
- [ ] If uncommitted changes exist → blocks with instructions to update progress.txt, consider CLAUDE.md, commit everything
- [ ] If clean → passes

**General:**
- [ ] Only activates when `.ralph-active` exists (early return otherwise)
- [ ] Reads `.ralph-active` as JSON for `skipReview`, `reviewCap`, `iterationMode`, `preIterationSnapshot`
- [ ] All checks must pass for stop to be approved
- [ ] Returns valid hook JSON: `{"decision": "block", "reason": "..."}` or `{"decision": "approve"}`
- [ ] Script is executable
- [ ] Handles edge cases: missing files, malformed JSON in `.ralph-active`, missing optional fields

### 3.3 — Create hooks.json

**File:** `claude-code/plugins/ralph/hooks/hooks.json`

Wires three hook entries across three events.

**Acceptance criteria:**
- [ ] `PostToolUse` entry: runs `context_monitor.py`, matcher `.*` (all tools)
- [ ] `Stop` entry: runs `stop_loop_reminder.py`
- [ ] `SessionStart` entry: inline command to clean up context monitor state file (`/tmp/claude-context-alerts-*`)
- [ ] Script paths use `${CLAUDE_PLUGIN_ROOT}` for portability (verify pattern against existing `zaksak` plugin)
- [ ] Valid JSON, parseable

### 3.4 — Commit Phase 3

**Acceptance criteria:**
- [ ] All hook files committed
- [ ] Commit message: `feat(ralph): add context monitor and stop loop reminder hooks`

---

## Phase 4: Main Loop Runner (ralph.sh)

**Goal:** Implement the main bash script that drives the ralph loop. Handles sandbox vs direct mode, pre-iteration snapshots, promise detection, and argument parsing.

Read `ralph/sandbox-test-results.md` before starting (specifically Steps 4 and 6).

### 4.1 — Create ralph.sh

**File:** `claude-code/plugins/ralph/scripts/ralph.sh`

Per §3 of the plan. This is the outer orchestrator.

**Argument parsing:**
- [ ] `-n, --max-iterations N` (default: 15)
- [ ] `--ralph-dir PATH` (default: `./ralph`)
- [ ] `-d, --project-dir PATH` (default: cwd)
- [ ] `-m, --model MODEL`
- [ ] `--sandbox` (force sandbox, error if unavailable)
- [ ] `--no-sandbox` (force direct mode)
- [ ] `--skip-review` (disable review cycle)
- [ ] `--review-cap N` (default: 5)
- [ ] `-h, --help` (usage text)

**Sandbox detection & setup:**
- [ ] Auto-detects Docker Sandbox availability at startup (`docker sandbox ls` check)
- [ ] Falls back to direct mode with warning if unavailable (unless `--sandbox` forced)
- [ ] Uses create + exec + run pattern from §3 (not custom Dockerfile)
- [ ] Sandbox name: `ralph-$(echo "$PROJECT_DIR" | sed 's#[^A-Za-z0-9._-]#_#g')`
- [ ] One-time sandbox creation with existence check (`docker sandbox ls | grep`)
- [ ] Auth symlink setup via `docker sandbox exec -u root` (runs `sandbox/setup.sh` or inline equivalent)
- [ ] Git config setup inside sandbox
- [ ] Ensures `~/.dclaude_state/.claude.json` contains valid JSON (`{}` minimum) before sandbox creation — empty file causes parse errors (plan §4)

**Loop iteration logic:**
- [ ] Iterates from 1 to `MAX_ITERATIONS`
- [ ] Reads `tasks.json` before each iteration
- [ ] Determines `iterationMode` using priority: any `reviewStatus: "changes_requested"` → `review-fix`, else any `reviewStatus: "needs_review"` → `review`, else → `implement`
- [ ] Writes pre-iteration snapshot to `.ralph-active` (JSON with `timestamp`, `pid`, `max_iterations`, `mode`, `skipReview`, `reviewCap`, `iterationMode`, `preIterationSnapshot` per story)
- [ ] Injects `$RALPH_ITERATION` and `$RALPH_MAX_ITERATIONS` into prompt via `sed`
- [ ] Sandbox mode: `docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"`
- [ ] Direct mode: `claude -p "$PROMPT" --dangerously-skip-permissions`
- [ ] Passes `--model` flag if specified
- [ ] Streams output to terminal via `tee /dev/stderr` while capturing for promise detection

**Resume-after-pause handling (sandbox mode only):**
- [ ] Detects if the loop was paused (developer edited files on host between iterations)
- [ ] Runs `docker sandbox stop` + restart before the next iteration to force Mutagen re-snapshot of host filesystem
- [ ] Overhead is ~10s (one-time per resume) — acceptable for multi-minute iterations
- [ ] See plan §3 file sync constraint #1 and `docker-sandbox-isolation.md` "File sync" caveat

**Completion detection:**
- [ ] Detects `<promise>COMPLETE</promise>` in captured output
- [ ] Falls back to tasks.json-only check: all stories have `passes: true` AND `reviewStatus: "approved"`
- [ ] Sandbox mode: 2-3 second sleep before reading tasks.json (file sync latency)
- [ ] Exits 0 on completion, 1 on max iterations reached

**Error handling & cleanup:**
- [ ] Creates `.ralph-active` marker on start
- [ ] `trap` cleans up `.ralph-active` on EXIT/INT/TERM
- [ ] Handles transient empty responses (exit 0, no output) with retry + cap
- [ ] Validates `jq` is available at startup
- [ ] Validates `ralph/` directory exists with required files (tasks.json, prompt.md, prd.md)

**General:**
- [ ] Script is executable
- [ ] Has usage/help text
- [ ] Uses `set -euo pipefail` (or equivalent safe defaults)
- [ ] Dependencies documented in comments: `jq`, `claude` CLI, optionally Docker Desktop 4.58+

### 4.2 — Commit Phase 4

**Acceptance criteria:**
- [ ] ralph.sh committed
- [ ] Commit message: `feat(ralph): add main loop runner with sandbox/direct mode support`

---

## Phase 5: Utility Scripts & Skill

**Goal:** Implement the initialization script, archive script, and interactive planning skill. These are the user-facing entry points.

### 5.1 — Create ralph-init.sh

**File:** `claude-code/plugins/ralph/scripts/ralph-init.sh`

Per §10 of the plan.

**Acceptance criteria:**
- [ ] Accepts `--project-dir PATH` (default: cwd) and `--name FEATURE_NAME`
- [ ] Creates `ralph/` directory in the target project
- [ ] Copies templates: `prompt.md`, `prd-template.md → prd.md`, `tasks-template.json → tasks.json`, `progress-template.md → progress.txt`
- [ ] Substitutes `{{DATE}}` (current date) and `{{PROJECT_NAME}}` (from `--name` or directory name) in progress.txt
- [ ] Sets `branchName` in tasks.json to `ralph/<name>` if `--name` provided
- [ ] Adds `.ralph-active` to `.gitignore` if not already present
- [ ] Prints next-steps instructions (edit prd.md, run `/ralph-plan` or fill tasks.json manually, run ralph.sh)
- [ ] Idempotent: warns but doesn't overwrite if `ralph/` already exists (unless `--force`)
- [ ] Script is executable
- [ ] Resolves template paths relative to the plugin's install location (not cwd)

### 5.2 — Create ralph-archive.sh

**File:** `claude-code/plugins/ralph/scripts/ralph-archive.sh`

Per §10 of the plan.

**Acceptance criteria:**
- [ ] Accepts `--project-dir PATH` (default: cwd) and `--label LABEL`
- [ ] Creates `ralph-archive/<date>-<branch-or-label>/` directory
- [ ] Moves `prd.md`, `tasks.json`, `progress.txt` to the archive directory
- [ ] Generates `summary.md` in the archive: stories completed vs total, date range, branch name
- [ ] Resets `ralph/` to clean state with fresh templates (same as init but preserves prompt.md customizations)
- [ ] Commits the archive with descriptive message
- [ ] Validates `ralph/` exists with completed tasks before archiving
- [ ] Script is executable

### 5.3 — Create ralph-plan skill

**File:** `claude-code/plugins/ralph/skills/ralph-plan.md`

Per §11 of the plan. User-invocable skill (`/ralph-plan`).

**Acceptance criteria:**
- [ ] Skill file follows the Claude Code skill format (check existing skills in `zaksak` plugin for pattern)
- [ ] **Mode 1 (full planning):** Triggers when `ralph/prd.md` is empty or template scaffold. Instructs Claude to ask clarifying questions (unlimited), generate prd.md, derive tasks.json, present for review
- [ ] **Mode 2 (task derivation):** Triggers when `ralph/prd.md` already has content. Read existing PRD, ask targeted questions only if ambiguous, derive tasks.json
- [ ] Task derivation rules encoded: one-story-per-iteration sizing, dependency ordering (schema → backend → API → frontend → integration), verifiable acceptance criteria, `dependsOn` set explicitly, `verifyCommands` populated
- [ ] All stories initialized with `passes: false`, `reviewStatus: null`, `reviewCount: 0`, empty `reviewFeedback`
- [ ] Prerequisite check: `ralph/` directory must exist (instructs user to run `ralph-init.sh` if not)
- [ ] Trigger phrases documented: `/ralph-plan`, "plan this feature for ralph", etc.

### 5.4 — Register skill in plugin manifest

Update `plugin.json` to register the ralph-plan skill (if the plugin manifest schema supports skill registration — verify against Claude Code docs/Context7).

**Acceptance criteria:**
- [ ] Skill is discoverable via `/ralph-plan` after plugin installation
- [ ] No changes to existing plugin fields

### 5.5 — Commit Phase 5

**Acceptance criteria:**
- [ ] All utility scripts and skill committed
- [ ] Commit message: `feat(ralph): add init, archive, and interactive planning utilities`

---

## Phase 6: Integration & Verification

**Goal:** Validate the complete plugin works end-to-end. Run through the verification plan from the spec. Fix any issues found.

### 6.1 — Structural validation

- [ ] Plugin installs correctly via marketplace (`marketplace.json` → plugin path → plugin.json → hooks.json chain resolves)
- [ ] All script files are executable (`chmod +x`)
- [ ] All JSON files are valid (`jq . < file`)
- [ ] All script shebangs are correct (`#!/usr/bin/env bash` for .sh, `#!/usr/bin/env python3` for .py)
- [ ] `${CLAUDE_PLUGIN_ROOT}` paths in hooks.json resolve correctly

### 6.2 — Hook script unit tests

Per verification plan §3.

**Context monitor:**
- [ ] Create fake transcript file → pass via JSON stdin → verify alerts fire at correct thresholds
- [ ] Verify each threshold fires only once per session
- [ ] Verify no crash on missing transcript file

**Stop loop reminder (schema validation — Check 1):**
- [ ] Valid tasks.json → passes Check 1
- [ ] Missing required field → blocks with specific error
- [ ] Duplicate story IDs → blocks
- [ ] `passes: true` with empty `notes` → blocks
- [ ] Invalid `reviewStatus` value → blocks
- [ ] `reviewCount: -1` → blocks (invalid negative value)

**Stop loop reminder (review integrity — Check 2):**
- [ ] `passes: true` + `reviewStatus: null` → blocks
- [ ] `passes: true` + `reviewStatus: "needs_review"` → blocks
- [ ] `passes: true` + `reviewStatus: "changes_requested"` → blocks
- [ ] `passes: true` + `reviewStatus: "approved"` → passes
- [ ] `reviewStatus: "changes_requested"` + empty `reviewFeedback` → blocks
- [ ] `reviewStatus: "approved"` + `passes: false` → blocks
- [ ] `.ralph-active` with `skipReview: true` → Check 2 skipped entirely

**Stop loop reminder (transition validation — Check 2.5):**
- [ ] `implement` mode + `passes` false→true → blocks
- [ ] `implement` mode + `reviewStatus` null→"approved" → blocks
- [ ] `implement` mode + `reviewCount` changed 0→1 → blocks
- [ ] `implement` mode + `reviewStatus` null→"needs_review" → passes (legal transition)
- [ ] `implement` mode + new story with valid initial state (`passes: false, reviewStatus: null, reviewCount: 0`) → passes
- [ ] `implement` mode + new story with `passes: true` → blocks
- [ ] `review` mode + legal approval (reviewCount+1, approved, passes=true) → passes
- [ ] `review` mode + legal rejection (reviewCount+1, changes_requested, non-empty feedback) → passes
- [ ] `review` mode + reviewCount unchanged → blocks
- [ ] `review` mode + two stories' review fields changed → blocks
- [ ] `review-fix` mode + legal resubmit (changes_requested→needs_review, feedback cleared) → passes
- [ ] `review-fix` mode + `passes` changed → blocks
- [ ] `review-fix` mode + `reviewCount` changed → blocks
- [ ] `review-fix` mode + `reviewStatus` → "approved" → blocks
- [ ] Missing `preIterationSnapshot` → Check 2.5 skipped with warning, Check 2 still runs

**Stop loop reminder (uncommitted changes — Check 3):**
- [ ] Uncommitted changes → blocks with commit instructions
- [ ] Clean working tree → passes

### 6.3 — ralph-init.sh validation

Per verification plan §4.
- [ ] Run in temp directory → all files created with correct content
- [ ] `{{DATE}}` and `{{PROJECT_NAME}}` substituted in progress.txt
- [ ] `.ralph-active` added to `.gitignore`
- [ ] Re-running warns about existing `ralph/` directory

### 6.4 — ralph.sh validation (direct mode)

Per verification plan §6.
- [ ] `--no-sandbox --max-iterations 1` with a single-story tasks.json
- [ ] Verify prompt injection (`{{RALPH_ITERATION}}` → `1`)
- [ ] Verify `.ralph-active` created with correct JSON payload
- [ ] Verify `.ralph-active` cleaned up on exit
- [ ] Verify iteration mode detection in `.ralph-active`

### 6.5 — ralph.sh validation (sandbox mode)

Per verification plan §§1, 5. **Requires Docker Desktop 4.58+.**
- [ ] `--sandbox --max-iterations 1` with a single-story tasks.json
- [ ] Verify sandbox creation (one-time) and reuse on subsequent runs
- [ ] Verify auth works (no login prompt)
- [ ] Verify auth persistence: destroy sandbox, recreate, re-run setup → still no login prompt (plan verification §1)
- [ ] Verify file sync latency handling (sleep before tasks.json read)

### 6.6 — Review lifecycle validation

Per verification plan §9. The critical behavioral test.
- [ ] Single-story task → implement iteration sets `reviewStatus: "needs_review"`, `passes` stays false
- [ ] Review iteration increments `reviewCount`, either approves or requests changes
- [ ] If changes requested: review-fix addresses feedback, sets `reviewStatus: "needs_review"`
- [ ] Re-review increments `reviewCount` again, approves
- [ ] Loop outputs `<promise>COMPLETE</promise>` only when all stories approved
- [ ] Implementation iteration attempting `passes: true` is blocked by stop hook
- [ ] `--review-cap 1` → auto-approves with `[AUTO-APPROVED AT CAP]` prefix
- [ ] `--skip-review` → implementation sets `passes: true` directly, no review cycle

### 6.7 — ralph-archive.sh validation

Per verification plan §7.
- [ ] Run after a completed loop → archive directory created with correct structure
- [ ] `ralph/` reset to clean templates
- [ ] Archive committed

### 6.8 — ralph-plan skill validation

Per verification plan §8.
- [ ] **Mode 1 (full planning):** Run `/ralph-plan` with empty/template prd.md → verify it asks clarifying questions, generates both prd.md and tasks.json, stories are right-sized and dependency-ordered
- [ ] **Mode 2 (task derivation):** Drop a pre-written prd.md into `ralph/`, run `/ralph-plan` → verify it reads existing PRD and derives tasks.json without regenerating the PRD
- [ ] Generated stories have correct initial state: `passes: false`, `reviewStatus: null`, `reviewCount: 0`, empty `reviewFeedback`
- [ ] `verifyCommands` populated, `dependsOn` set where applicable

### 6.9 — Network policy validation (sandbox mode)

Per verification plan §2. **Optional — tests infrastructure config, not plugin code.** Skip if network policy is not configured.
- [ ] `curl https://api.anthropic.com` from inside sandbox → succeeds (allowed)
- [ ] `curl https://evil.com` from inside sandbox → blocked
- [ ] Reverse shell attempt → blocked (non-HTTP blocked by default)

### 6.10 — Multi-story end-to-end test

Per verification plan §10.
- [ ] Run a 2–3 story task list through full ralph loop completion in sandbox mode
- [ ] Each story exercises the full review cycle (implement → review → approve, or implement → review → fix → re-review → approve)
- [ ] Loop terminates with `<promise>COMPLETE</promise>` only after all stories have `passes: true` AND `reviewStatus: "approved"`

### 6.11 — Post-completion analytics verification

Per verification plan §11.
- [ ] After end-to-end completion, verify `reviewCount` values in tasks.json are accurate
- [ ] `reviewCount` reflects the actual number of fresh-context review iterations each story went through (not review-fix iterations)

### 6.12 — Fix any issues found

- [ ] All issues from 6.1–6.11 resolved
- [ ] Final commit with all fixes

### 6.13 — Commit Phase 6

**Acceptance criteria:**
- [ ] All verification tests pass
- [ ] Commit message: `test(ralph): validate plugin integration and review lifecycle`

---

## Phase Summary

| Phase | Session | Key Deliverables | Estimated Complexity |
|-------|---------|-----------------|---------------------|
| 1 | 1 | Plugin scaffold, 4 templates, sandbox setup script | Low — mostly static files |
| 2 | 2 | prompt.md (3-mode iteration prompt) | Medium — careful writing, no logic |
| 3 | 3 | context_monitor.py, stop_loop_reminder.py, hooks.json | High — state machine validation logic |
| 4 | 4 | ralph.sh (main loop runner) | High — bash orchestration, sandbox management |
| 5 | 5 | ralph-init.sh, ralph-archive.sh, ralph-plan.md skill | Medium — utility scripts and skill |
| 6 | 6 | Integration testing, fixes | Medium — depends on issues found |

**Total: 6 sessions**

---

## Notes

- **Phase 3 is the riskiest.** The stop hook's transition validation (Check 2.5) is the most complex logic in the plan. Budget extra time and consider writing test cases alongside the implementation.
- **Phase 4 depends heavily on sandbox test results.** The create+exec+run pattern has been validated in `sandbox-test-results.md`, but ralph.sh integrates many moving parts. Test each section incrementally.
- **Phase 6 can be split** if testing reveals significant issues. Hook unit tests (6.2) could be a standalone sub-session if the test matrix is large.
- **PreToolUse hook blocklist is NOT in scope.** The plan documents it as a fallback reference (`pretooluse-hook-reference.md`) but the direct mode fallback in ralph.sh uses `--dangerously-skip-permissions` without a blocklist hook. Implementing the blocklist is a separate future effort if needed.
- **Checklist additions not in the original plan** (reasonable defensive measures, flagged for awareness):
  - Task 5.1 adds a `--force` flag to ralph-init.sh for overwriting existing `ralph/` directory
  - Task 5.2 adds pre-archive validation (ralph/ exists with completed tasks)
  - Task 5.2 includes branch name in summary.md (plan only specifies stories completed/total and date range)
