# The Ralph Loop: a comprehensive technical reference

The Ralph Loop is a deceptively simple technique for autonomous AI coding: **a bash while-loop that repeatedly feeds an LLM agent the same prompt, relying on externalized state in files and git history to drive progress**. Invented by Geoffrey Huntley in mid-2025 and named after Ralph Wiggum from *The Simpsons*, the technique has spawned a rich ecosystem of implementations, memory patterns, task formats, and sandboxing approaches. This report catalogs every major variant across all six requested categories, with raw code, schemas, and configurations gathered from over 30 distinct sources.

The core insight is that fresh context windows avoid degradation — each iteration reads the project's current state from disk rather than accumulating stale context. The loop itself is "deterministically bad in an undeterministic world" (Huntley), and its power comes entirely from how state files, prompts, and verification gates are structured around it.

---

## 1. Every distinct ralph.sh script implementation

### The original one-liner (ghuntley.com/ralph, July 2025)

```bash
while :; do cat PROMPT.md | claude-code ; done
```

This is the primordial form. Everything else elaborates on this pattern.

### ClaytonFarr/ralph-playbook loop.sh (= ghuntley/how-to-ralph-wiggum fork)

The canonical "playbook" version supports **three modes** — plan, build, and plan-work — and pushes after every iteration:

```bash
#!/bin/bash
# Usage: ./loop.sh [plan|plan-work] [max_iterations]
if [ "$1" = "plan" ]; then
    MODE="plan"; PROMPT_FILE="PROMPT_plan.md"; MAX_ITERATIONS=${2:-0}
elif [ "$1" = "plan-work" ]; then
    MODE="plan-work"; WORK_DESCRIPTION="$2"
    PROMPT_FILE="PROMPT_plan_work.md"; MAX_ITERATIONS=${3:-5}
elif [[ "$1" =~ ^[0-9]+$ ]]; then
    MODE="build"; PROMPT_FILE="PROMPT_build.md"; MAX_ITERATIONS=$1
else
    MODE="build"; PROMPT_FILE="PROMPT_build.md"; MAX_ITERATIONS=0
fi
ITERATION=0; CURRENT_BRANCH=$(git branch --show-current)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Mode: $MODE | Prompt: $PROMPT_FILE | Branch: $CURRENT_BRANCH"
[ $MAX_ITERATIONS -gt 0 ] && echo "Max: $MAX_ITERATIONS iterations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
[ ! -f "$PROMPT_FILE" ] && echo "Error: $PROMPT_FILE not found" && exit 1
while true; do
    [ "$MAX_ITERATIONS" -gt 0 ] && [ "$ITERATION" -ge "$MAX_ITERATIONS" ] && echo "Reached max iterations" && break
    if [ "$MODE" = "plan-work" ]; then
        envsubst < "$PROMPT_FILE" | claude -p --dangerously-skip-permissions \
            --output-format=stream-json --model opus --verbose
    else
        cat "$PROMPT_FILE" | claude -p --dangerously-skip-permissions \
            --output-format=stream-json --model opus --verbose
    fi
    git push origin "$CURRENT_BRANCH" || git push -u origin "$CURRENT_BRANCH"
    ITERATION=$((ITERATION + 1))
    echo -e "\n======================== LOOP $ITERATION ========================\n"
done
```

Key design choices: **Opus as default model**, `stream-json` output for monitoring, `git push` after every iteration, no completion detection (runs until max iterations or forever).

### snarktank/ralph ralph.sh (~9,200 stars)

Ryan Carson's implementation adds **dual-agent support** (Amp or Claude Code) and `<promise>COMPLETE</promise>` exit detection:

```bash
#!/bin/bash
set -e
TOOL="amp"; MAX_ITERATIONS=10
while [[ $# -gt 0 ]]; do
  case $1 in
    --tool) TOOL="$2"; shift 2;;
    --tool=*) TOOL="${1#*=}"; shift;;
    *) [[ "$1" =~ ^[0-9]+$ ]] && MAX_ITERATIONS="$1"; shift;;
  esac
done
[[ "$TOOL" != "amp" && "$TOOL" != "claude" ]] && echo "Error: Must be 'amp' or 'claude'." && exit 1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"; PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
for ((i=1; i<=MAX_ITERATIONS; i++)); do
  if [[ "$TOOL" == "amp" ]]; then
    OUTPUT=$(cat "$SCRIPT_DIR/prompt.md" | amp --dangerously-allow-all 2>&1 | tee /dev/stderr) || true
  else
    OUTPUT=$(claude --dangerously-skip-permissions --print < "$SCRIPT_DIR/CLAUDE.md" 2>&1 | tee /dev/stderr) || true
  fi
  if echo "$OUTPUT" | grep -q "<promise>COMPLETE</promise>"; then
    echo "Ralph completed all tasks!"; exit 0
  fi
  sleep 2
done
```

Notable: uses **separate prompt files per agent** (`prompt.md` for Amp, `CLAUDE.md` for Claude Code). Default **10 iterations**. The `<promise>COMPLETE</promise>` pattern originated here and became the ecosystem standard.

### coleam00/ralph-loop-quickstart ralph.sh

Cole Medin's intentionally minimal version — the "right way" per his guide:

```bash
#!/bin/bash
[ -z "$1" ] && echo "Usage: $0 <iterations>" && exit 1
for ((i=1; i<=$1; i++)); do
    echo "Iteration $i"
    result=$(claude -p "$(cat PROMPT.md)" --output-format text 2>&1) || true
    echo "$result"
    if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
        echo "All tasks complete after $i iterations."; exit 0
    fi
    echo "--- End of iteration $i ---"
done
echo "Reached max iterations ($1)"; exit 1
```

Philosophy: **fresh context per iteration** via `-p` flag (non-interactive mode). No streaming, no git push, no model specification — pure simplicity.

### fredflint's gist ralph.sh (TDD + code review variant)

Embeds a **full prompt inline** with TDD methodology, Linus Torvalds-style review criteria, and review task detection:

```bash
#!/bin/bash
set -e
MAX=${1:-10}; SLEEP=${2:-2}; MODEL=${3:-"sonnet"}
for ((i=1; i<=$MAX; i++)); do
  result=$(claude --model "$MODEL" --dangerously-skip-permissions -p "You are Ralph, an autonomous coding agent.
## Task Type Detection
First, read PRD.md and find the first incomplete task (marked [ ]).
Check the task header:
- **Regular task**: ### US-001: Create database [ ]
- **Review task**: ### US-REVIEW-XXX: Review tasks 1-3 [ ]
## Regular Task Process
1. Read PRD.md, find first incomplete [ ] task.
2. Read progress.txt - check Learnings section first.
3. Implement using TDD methodology.
4. Run tests/typecheck to verify.
## Critical: Only Complete If Tests Pass
- Mark acceptance criteria [x] as completed
- If ALL criteria [x]: Mark task header [x], commit, append to progress.txt
## Per-Task Linus Review: good taste, no special cases, minimal complexity
## End Condition
CRITICAL: Before outputting <promise>COMPLETE</promise>:
1. Read PRD.md top to bottom  2. Search for ANY remaining [ ]
3. Only output COMPLETE if EVERY task header is [x]")
  echo "$result" | grep -q "COMPLETE" && echo "Done after $i iterations." && exit 0
  sleep $SLEEP
done
echo "Max iterations hit."; exit 1
```

Unique features: **configurable model** (defaults to Sonnet for speed), **inline prompt** rather than external file, **review task** mode where the agent reviews its own prior work across multiple stories.

### prateek's gist ralph-loop.sh (Codex variant)

Uses OpenAI's Codex CLI with a **humorous file-touch completion signal**:

```bash
#!/bin/bash
set -e
[[ $# -lt 1 ]] && echo "Usage: $0 <iterations>" && exit 1
PROMISE_FILE="I_PROMISE_ALL_TASKS_IN_THE_PRD_ARE_DONE_I_AM_NOT_LYING_I_SWEAR"
mkdir -p .logs; rm -f "$PROMISE_FILE"
for ((i = 1; i <= $1; i++)); do
  codex --dangerously-bypass-approvals-and-sandbox exec <<'EOF' 2>&1 | tee -a ".logs/iterations.log"
1. Find the highest-priority task based on PRD.md and progress.txt, implement it.
2. Run tests and type checks.  3. Update the PRD.  4. Append to progress.txt.  5. Commit.
ONLY WORK ON A SINGLE TASK.
If the PRD is complete, touch I_PROMISE_ALL_TASKS_IN_THE_PRD_ARE_DONE_I_AM_NOT_LYING_I_SWEAR
EOF
  [[ -f "$PROMISE_FILE" ]] && echo "PRD complete after $i iterations." && exit 0
done
echo "PRD not complete after $1 iterations."; exit 1
```

Instead of parsing output for a completion string, this uses **file existence** as the signal — more reliable than grep-based detection since it avoids false positives from agent commentary.

### mwarger's gist ralph.sh (Codex with .ralphrc config)

A production-grade Codex implementation with **config file support**, security-conscious permission checks, and extensive customization:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Supports .ralphrc config file with: RALPH_PRD_PATH, RALPH_PROGRESS_PATH,
# RALPH_LOG_DIR, RALPH_CHECK_COMMANDS, RALPH_ADD_DIRS, RALPH_FULL_AUTO,
# RALPH_SANDBOX_MODE, RALPH_APPROVAL_POLICY, RALPH_PROFILE,
# RALPH_CODEX_MODEL, RALPH_CODEX_FLAGS, RALPH_REQUIRE_COMMIT, RALPH_VALIDATE_COMMIT
# Config permission checks (owner mismatch, group/world writable)
# Uses codex exec with sandbox mode, model selection, PRD-based prompts
# Supports --follow/-f flag and init subcommand
```

This is the most enterprise-ready gist variant, with **config file permission auditing** (rejects group/world-writable `.ralphrc` files) and configurable sandbox modes.

### shanselman's ralph-loop.ps1 (PowerShell for GitHub Copilot CLI)

Scott Hanselman's **PowerShell implementation** targeting Copilot CLI with a **job-based directory structure**:

```powershell
param([Parameter(Mandatory=$true, Position=0)] [string]$JobName)
$MaxIterations = if ($env:MAX_ITERATIONS) { [int]$env:MAX_ITERATIONS } else { 100 }
$ModelName = if ($env:MODEL_NAME) { $env:MODEL_NAME } else { "claude-opus-4.5" }
$CopilotArgs = if ($env:COPILOT_ARGS) { $env:COPILOT_ARGS } else { "--yolo" }
$JobDir = Join-Path "." "ralph-jobs" $JobName
# Creates: prompt.md, stop-hook.ps1, sessions/ directory
# If prompt.md doesn't exist, runs interactive setup via Copilot
# Main loop: invokes copilot with prompt, checks stop-hook exit code
# Sessions logged to iteration-001.md, iteration-002.md, etc.
while ($iteration -lt $maxIteration) {
    $iteration++
    $SessionFile = Join-Path $SessionDir ("iteration-{0:D3}.md" -f $iteration)
    $copilotCommand = "copilot -p `"$PromptContent`" $CopilotArgs --model `"$ModelName`" --share `"$SessionFile`""
    Invoke-Expression $copilotCommand
    if (Test-Path $StopHook) { & $StopHook; if ($LASTEXITCODE -eq 0) { exit 0 } }
    Start-Sleep -Seconds 2
}
```

Unique: **stop-hook.ps1** as a scriptable completion gate (exit code 0 = done), **session transcripts** saved per iteration, **automatic job scaffolding** on first run.

### soderlind's copilot-ralph.py (Python for GitHub Copilot)

A **Python wrapper** that manages structured prd.json with per-story test commands and a resume-capable `.ralph/state.json`:

```json
// prd.json schema
{
  "project": "Example",
  "final_tests": ["npm test"],
  "stories": [
    {"id": "S1", "priority": 1, "title": "...", "acceptance": ["..."],
     "tests": ["npm test"], "passes": false}
  ]
}
```

Adds `tests` array per story and `final_tests` at the project level — the loop only marks complete when both individual story tests AND final integration tests pass.

### syuya2036/ralph-loop ralph.sh (agent-agnostic)

Accepts **any CLI agent command** as its first argument:

```bash
./ralph-loop/ralph.sh "claude --dangerously-skip-permissions" 20
./ralph-loop/ralph.sh "codex exec --full-auto" 20
./ralph-loop/ralph.sh "gemini --yolo" 20
./ralph-loop/ralph.sh "qwen" 20
```

Pipes `prompt.md` content to the specified command via stdin. Default 10 iterations.

### Additional notable variants

- **Th0rgal/open-ralph-wiggum** (319 stars): TypeScript/Bun CLI supporting Claude, Codex, Copilot, OpenCode with `--rotation` for agent cycling
- **gemini-cli-extensions/ralph**: Uses Gemini's AfterAgent hooks to intercept completion and re-inject prompts — no bash loop needed
- **Goose ralph loop** (block.github.io/goose): Multi-model cross-review where one model works and a different model reviews
- **frankbria/ralph-claude-code** (463 stars): Circuit breaker, rate limiting, tmux dashboard, CI/CD mode
- **mikeyobrien/ralph-orchestrator** (253 stars): Rust-based orchestration with Telegram bot, web dashboard, and multi-agent coordination

---

## 2. Persistent memory file formats and schemas

Seven distinct persistence patterns exist across implementations, each solving the problem of maintaining state across fresh context windows.

### progress.txt — the append-only learning log

The most universal format. Every implementation uses some variant. The canonical structure from snarktank/ralph and the Geocodio blog:

```
## Codebase Patterns
(Maintained at top for quick reference)
- This project uses spatie/laravel-enum, not native PHP enums
- Form components live in resources/views/components/forms/

## Iteration 3 - 2026-01-23 14:32:15
### Task: US-003 - Add priority dropdown
**What I did:**
- Added PriorityEnum with values: low, medium, high, urgent
- Updated TaskRequest with priority validation
**Acceptance criteria results:**
- php artisan test - 47 passed
- ./vendor/bin/phpstan analyse - No errors
**Learnings for future iterations:**
- The tasks table has soft deletes - use withTrashed() when needed
**Status:** PASSED - Updated prd.json
```

**Key properties**: append-only (never overwritten), session-specific (deleted between sprints per aihero.dev), maintains a **Codebase Patterns** section at the top for quick reference. Each entry records: task attempted, actions taken, test results, learnings, pass/fail status.

### prd.json — the structured task state

The machine-readable completion tracker. Three major schema variants exist:

**Standard schema** (snarktank/ralph):
```
{ project, branchName, description, userStories: [{ id, title, acceptanceCriteria[], priority, passes: boolean, notes }] }
```

**Copilot-Ralph schema** (soderlind): adds `tests[]` per story and `final_tests[]` at root level

**Effort-aware schema** (Nagacevschi): adds `effort_label: "low"|"medium"|"high"` for model routing

The `passes: boolean` field is the **universal completion signal** — binary, no "in-progress" state in the standard variant. Chief's variant adds `inProgress: boolean` for three-state tracking.

### IMPLEMENTATION_PLAN.md — the Huntley/Farr markdown plan

```
# Implementation Plan
## High Priority
- [ ] Implement user authentication flow
  - Files: src/auth/, prisma/schema.prisma
  - Notes: Use existing middleware pattern
- [x] ~~Set up database schema~~ (completed iteration 3)
## Discovered Issues
- Soft deletes require withTrashed() queries
```

Uses **markdown checkboxes** (`- [ ]`/`- [x]`) with strikethrough for completed items. Considered **disposable** — regenerate rather than fight stale state. Huntley prefers this over JSON for "better token efficiency."

### .ralph/state.json — resume metadata

Lightweight file for pause/resume capability. Contains iteration count, last completed story ID, timestamps. Used by soderlind's copilot-ralph and frankbria's implementation.

### AGENTS.md — the long-term knowledge base

```
# Agents
## Build Commands       → npm run build, npm run test
## Testing             → Vitest with jsdom, tests co-located with source
## Conventions         → TypeScript strict mode, components in src/components/
## Learned Patterns    → (Updated by agent during iterations)
## Pitfalls            → Never import from solid-js, use @opentui/solid
```

Starts nearly empty. Agent and human add operational learnings over time. **Kept brief** (~60 lines max) because it's loaded every iteration and consumes context budget.

### .chief/prds/\<name\>/ — directory-scoped state (Chief TUI)

```
.chief/prds/my-feature/
├── prd.md          # Human-readable context (not parsed)
├── prd.json        # Machine-readable source of truth
├── progress.md     # Auto-generated progress log
└── claude.log      # Raw Claude output
```

### specs/*.md — requirement specifications (Huntley pattern)

One markdown file per "topic of concern" within a Job to Be Done. **Static during build loops** — only updated in planning phases. The agent reads these as reference but doesn't modify them during building.

---

## 3. How different implementations update memory files

The ecosystem uses **four distinct update strategies** applied across different file types, forming what Addy Osmani calls a "compound learning loop."

### Append-only for progress.txt

Every implementation instructs the agent to **append** a new section per iteration, never overwrite. The snarktank/ralph prompt says: "Append your progress to progress.txt." The aihero.dev guide recommends: "Sacrifice grammar for the sake of concision." When progress.txt grows too long, Osmani recommends having the agent summarize older content and truncate. The file is **session-specific** — deleted between sprints to avoid stale context accumulation.

### In-place field edit for prd.json

The agent sets `"passes": true` and optionally adds to `"notes"` — nothing else changes. The JSON structure is preserved. This is **the most constrained update pattern** by design: machine-readable, programmatic, minimal surface area for error.

### Append with occasional edit for AGENTS.md and CLAUDE.md

New learnings are appended as bullet points under the appropriate section. The building prompt instructs: "Update AGENTS.md if you learned new operational details." This happens **only when something NEW is discovered** — not every iteration. The Huntley playbook explicitly adds: "Keep AGENTS.md operational only — status updates and progress notes belong in IMPLEMENTATION_PLAN.md. A bloated AGENTS.md pollutes every future loop's context."

### In-place checkbox toggle for IMPLEMENTATION_PLAN.md

The agent changes `- [ ]` to `- [x]`, adds notes beside tasks, and may insert new discovered subtasks. The plan is treated as a **living document** that reflects ground truth about what's been implemented.

### The five tuning methods across implementations

1. **Reactive tuning by humans** (primary): "When Ralph fails a specific way, add a sign to help him next time" — human adds rule to AGENTS.md or PROMPT.md
2. **Agent self-update** (secondary): Building prompt instructs the agent to update AGENTS.md with discovered build commands, library quirks, file locations
3. **Real-time human correction** (interactive): Developer tells the agent mid-loop: "Use v2/users, not the old endpoint. Record this in AGENTS.md"
4. **Start empty, fill organically** (Huntley recommendation): Begin with an empty AGENTS.md; spot-test, observe loops, tune only as needed
5. **Code as implicit convention**: Well-structured utility code in `src/lib/` serves as discoverable patterns — Ralph reads and follows existing code style without explicit documentation

---

## 4. Task tracker format schemas

Ten distinct task tracking formats exist, spanning JSON and Markdown approaches.

### JSON formats

**Standard prd.json** (snarktank, most implementations):
```json
{
  "project": "string",
  "branchName": "string",
  "description": "string",
  "userStories": [{
    "id": "US-001",
    "title": "string",
    "acceptanceCriteria": ["string"],
    "priority": 1,         // lower = higher priority
    "passes": false,        // binary completion flag
    "notes": ""             // agent can append learnings
  }]
}
```

**Chief prd.json** (adds `inProgress` for 3-state tracking):
```json
{ "userStories": [{ "id": "US-012", "title": "...", "acceptanceCriteria": ["..."],
  "priority": 1, "passes": false, "inProgress": false }] }
```

**Copilot-Ralph prd.json** (adds per-story and project-level tests):
```json
{ "project": "...", "final_tests": ["npm test"],
  "stories": [{ "id": "S1", "priority": 1, "title": "...",
  "acceptance": ["..."], "tests": ["npm test"], "passes": false }] }
```

**Anthropic-style flat array** (from AI Hero):
```json
[{ "category": "string", "description": "string",
   "steps_to_verify": ["string"], "passes": false }]
```

**PageAI-Pro split format** — `tasks.json` as a lookup table plus individual `TASK-{ID}.json` files with step-by-step breakdowns. Scales better for hundreds of tasks.

### Markdown formats

**IMPLEMENTATION_PLAN.md** (Huntley/Farr playbook): Priority-sorted bullet list with `- [ ]`/`- [x]` checkboxes, category tags in brackets `[setup]`/`[feat]`/`[ui]`, notes inline.

**TODO.md** (Mburdo plugin workflow): Four priority tiers (Critical/High/Medium/Low) with `**HARD STOP**` markers for mandatory verification points. Tasks move to a "Completed" section when done.

**activity.md** (coleam00 quickstart): Current Status header with Last Updated, Tasks Completed, Current Task fields, plus a Session Log section for dated entries.

---

## 5. Core prompt and instruction format schemas

Eight distinct prompt architectures exist, from minimal single-file to elaborate multi-phase systems.

### Single PROMPT.md (snarktank/ralph, Geocodio — the most common)

```
# Ralph Agent Instructions
## Your Task
  1. Read the PRD at prd.json
  2. Read the progress log at progress.txt
  3. Check correct branch from PRD branchName
  4. Pick highest priority story where passes: false
  5. Implement that single user story
  6. Run quality checks (typecheck, lint, test)
  7. If checks pass, commit ALL changes
  8. Update PRD to set passes: true
  9. Append progress to progress.txt
## Stop Condition
  If ALL stories have passes: true → output <promise>COMPLETE</promise>
```

Universally follows the pattern: **read state → pick task → implement → verify → commit → update state → check completion**.

### Dual PROMPT_plan.md + PROMPT_build.md (Huntley/Farr playbook)

**PROMPT_plan.md sections**: `0a. Study specs/*` → `0b. Study IMPLEMENTATION_PLAN.md` → `0c. Study src/lib/*` → `0d. Study src/*` → `1. Gap analysis with Opus subagent, create/update plan`. Explicitly states: "**Plan only. Do NOT implement anything.**"

**PROMPT_build.md sections**: Same `0a-0c` orientation phase, then: `1. Choose most important item, search before implementing` → `2. Implement, run tests` → `3. Update plan with findings` → `4. Commit and push` → Numbered guidelines `99999-9999999999999` for documentation, single sources of truth, git tags, logging, AGENTS.md maintenance, bug documentation, and avoiding stubs/placeholders.

The build prompt's numbering scheme (`99999`, `999999`, etc.) is deliberate — it ensures these instructions appear **after** the main workflow steps but are still parsed as high-priority directives.

### Three-phase plugin commands (Mburdo gist)

**Phase 1 `/ralph-clarify`**: Discovery loop using AskUserQuestion tool. Seven question categories (Core Requirements, Users & Context, Integration Points, Edge Cases, Quality Attributes, Existing Patterns, Preferences). Outputs `<promise>CLARIFIED</promise>`.

**Phase 2 `/ralph-plan`**: Converts clarified requirements into PROMPT.md + TODO.md.

**Phase 3 `/ralph-loop`**: Autonomous execution with `--max-iterations` and `--completion-promise` flags.

### AGENTS.md as operational guide (loaded every iteration)

Typical sections: **Build Commands**, **Testing**, **Conventions**, **Learned Patterns**, **Pitfalls**. Kept to ~60 lines max. Distinct from PROMPT.md (task instructions) — AGENTS.md is **project memory** that accumulates over time.

### STEERING.md mid-loop override (PageAI-Pro)

A unique innovation: editable while the loop is running. The agent checks it each iteration for critical work to prioritize, enabling **human steering without stopping the loop**.

### Completion signals across implementations

- **`<promise>COMPLETE</promise>`** — the ecosystem standard (snarktank, coleam00, fredflint, Gemini extension, Goose)
- **`<chief-complete/>`** — Chief TUI variant
- **`STATUS: COMPLETE`** — Huntley playbook variant
- **File touch** (`I_PROMISE_ALL_TASKS_IN_THE_PRD_ARE_DONE_I_AM_NOT_LYING_I_SWEAR`) — prateek's Codex variant
- **Stop-hook exit code 0** — shanselman's PowerShell variant
- **Exit code 2 interception** — Anthropic's official plugin

---

## 6. Sandboxing --dangerously-skip-permissions execution

The most critical and varied category. Twelve distinct approaches exist, from application-level permission rules to OS-level namespace isolation.

### .claude/settings.json permission configurations

**Allowlist approach** (Kyle Redelinghuys, ksred.com):
```json
{
  "permissions": {
    "allow": [
      "Bash(mkdir:*)", "Bash(go:*)", "Write(*)", "Bash(ls:*)", "Bash(git:*)",
      "Bash(mv:*)", "Bash(echo:*)", "Bash(sed:*)", "Bash(npm:*)", "Bash(npx:*)",
      "Bash(grep:*)", "Bash(curl:*)", "Bash(rg:*)", "Bash(find:*)",
      "Bash(docker:*)", "Bash(python:*)", "Bash(python3:*)", "Update(*)"
    ],
    "deny": []
  }
}
```

Deliberately **omits `rm`** from the allow list. This is the lightest sandboxing — application-level only.

**Enterprise lockdown** (claudefa.st):
```json
{
  "permissions": {
    "deny": ["Bash(curl *)", "Bash(wget *)", "Read(./.env)", "Read(./.env.*)",
             "Read(./secrets/**)", "Read(./config/credentials.*)"],
    "disableBypassPermissionsMode": "disable"
  },
  "sandbox": {
    "enabled": true, "allowUnsandboxedCommands": false,
    "network": { "allowedDomains": ["github.com", "*.npmjs.org", "*.internal.acme.com"] }
  },
  "allowManagedHooksOnly": true, "allowManagedPermissionRulesOnly": true
}
```

Key: `"disableBypassPermissionsMode": "disable"` **prevents** `--dangerously-skip-permissions` from being used at all.

### Built-in /sandbox command (bubblewrap on Linux, Seatbelt on macOS)

Claude Code's native sandbox uses **bubblewrap** on Linux and Apple's **Seatbelt** framework on macOS. Enable with `/sandbox` in a Claude Code session. Reduces permission prompts by **84%** according to Anthropic's engineering blog.

For Docker-nested environments:
```json
{ "sandbox": { "enableWeakerNestedSandbox": true } }
```

### DIY bubblewrap wrapper (patrickmccanna.net)

The most granular control. Blocks .env files by overlaying with `/dev/null`:

```bash
bwrap \
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /bin /bin \
  --ro-bind /etc/resolv.conf /etc/resolv.conf \
  --ro-bind "$HOME/.nvm" "$HOME/.nvm" \
  --bind "$PROJECT_DIR" "$PROJECT_DIR" \
  --bind "$HOME/.claude" "$HOME/.claude" \
  --tmpfs /tmp --proc /proc --dev /dev \
  --share-net --unshare-pid --die-with-parent \
  --ro-bind /dev/null "$PROJECT_DIR/.env" \
  --ro-bind /dev/null "$PROJECT_DIR/.env.local" \
  "$(command -v claude)" --dangerously-skip-permissions "Your task"
```

`--share-net` allows network access (remove to block). `--unshare-pid` isolates the process namespace. The `/dev/null` overlay on `.env` files **prevents secret exfiltration** even if the agent tries to read them.

### Docker container approaches

**Anthropic's official devcontainer** includes a `init-firewall.sh` script that whitelists specific domains (registry.npmjs.org, api.anthropic.com, etc.) via iptables rules inside the container. The Dockerfile installs Claude Code globally and sets up sudoers for the firewall script.

**textcortex/claude-code-sandbox** provides a dedicated wrapper with `claude-sandbox.config.json`:
```json
{
  "dockerImage": "claude-code-sandbox:latest",
  "detached": false, "autoPush": true, "autoCreatePR": true,
  "network": "none",
  "allowedTools": ["*"], "maxThinkingTokens": 100000, "bashTimeout": 600000
}
```

**Minimal one-liner**: `docker run -it --rm -v $(pwd):/workspace -w /workspace --network none claude-code:latest --dangerously-skip-permissions "task"` — the `--network none` flag prevents all data exfiltration.

### Git worktree isolation

The standard pattern for **parallel agent sessions**:

```bash
git worktree add ../project-feature-a -b feature-a
cd ../project-feature-a && claude
```

**nwiizo/ccswarm** coordinates specialized agents (Frontend, Backend, DevOps, QA) in worktree-isolated environments using Rust-based orchestration. **agenttools/worktree** provides a CLI with `.worktree.yml` config for automated worktree management.

### macbox — macOS Seatbelt + worktrees (srdjan/macbox)

```bash
macbox --prompt "fix the build" --worktree my-feature --block-network
macbox --prompt "fix the build" --profile host-tools,host-ssh --trace
```

Uses macOS `sandbox-exec` (Seatbelt) with SBPL profiles. Auto-creates git worktrees. Restricts file writes to worktree + safe temp roots. Composable profile system.

### MCP-based permission control

A custom MCP server that intercepts permission requests and applies approval logic:

```javascript
server.tool("permission_prompt", "Handle permission requests",
  { tool_use_id: z.string(), tool_name: z.string(), input: z.any() },
  async ({ tool_use_id, tool_name, input }) => {
    const approved = true; // Your approval logic here
    return { content: [{ type: "text",
      text: JSON.stringify({ behavior: approved ? "allow" : "deny", updatedInput: input }) }] };
  });
```

Usage: `claude -p "task" --permission-prompt-tool mcp__permission-server__permission_prompt`

### CLI flags for additional safety

```bash
claude --dangerously-skip-permissions --disallowedTools "Bash(rm:*),Bash(sudo:*)" "task"
claude --dangerously-skip-permissions --max-budget-usd 5.00 "task"
```

**Important bug**: `--allowedTools` may be ignored with `bypassPermissions`. Use `--disallowedTools` instead, which works correctly in all modes.

### Destructive Command Guard (DCG)

An additional safety layer that intercepts destructive shell commands before execution:
```bash
curl -fsSL "https://raw.githubusercontent.com/Dicklesworthstone/destructive_command_guard/master/install.sh" | bash -s -- --easy-mode
```

Blocks `rm -rf`, direct pushes to main, and other dangerous operations regardless of Claude Code's permission settings.

---

## Conclusion: what the ecosystem reveals

The Ralph Loop ecosystem has converged on several strong patterns while maintaining healthy diversity in implementation details. **The `<promise>COMPLETE</promise>` completion signal, append-only progress.txt, and prd.json with `passes: boolean`** have become de facto standards across nearly all implementations.

Three architectural insights emerge that aren't obvious from any single source. First, the **separation of planning and building into distinct loop modes** (Huntley's dual-prompt approach) is the most reliable pattern for complex projects — mixing planning and implementation in a single prompt leads to the "oscillation" failure mode described by beuke.org. Second, the **"four channels of memory"** framework (git history + progress log + task state + agent knowledge) represents genuine distributed systems thinking applied to LLM orchestration — each channel serves a distinct purpose and degrades gracefully if any one fails. Third, the **most effective sandboxing combines multiple layers**: settings.json deny rules + bubblewrap/Seatbelt OS isolation + Docker network restrictions + git worktree code isolation. No single approach provides adequate safety for truly autonomous operation.

The technique's power remains rooted in Huntley's original insight: context windows are disposable buffers, but the filesystem accumulates truth. The bash loop is the simplest possible orchestrator — everything else is just better state management.