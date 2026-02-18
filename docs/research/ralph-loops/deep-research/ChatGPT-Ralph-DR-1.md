# Deep research report on the Ralph Loop agentic coding method

## What the Ralph Loop is and why it exists

The “Ralph Loop” is best understood as an *outer orchestration loop* that repeatedly runs an agentic coding CLI (often in headless mode) against a stable, file-based specification of work—so the agent’s “memory” lives in the repo (PRDs, plans, progress logs, git history), not in an ever-growing chat transcript. This design is explicitly motivated by context accumulation (“context rot”) in standard agent loops, where repeated failures and noisy history degrade performance over time.

Across the ecosystem, a small set of invariants keeps showing up—even when the tooling differs:

- **Freshness by restart:** Many “classic” Ralph implementations restart the agent each iteration to guarantee a clean context window (and therefore a predictable “smart zone” for reasoning).
- **State on disk:** Work selection and continuity come from files (PRD/task list, implementation plan, progress log, guardrails), plus **git commits** as durable checkpoints.
- **One unit of work per iteration:** The loop converges when the agent is constrained to finish *one* well-scoped task/story, validate it, commit it, then exit; the next iteration picks the next item.
- **Backpressure over “good intentions”:** Tests, type checks, lint, build steps, and browser/e2e verification become objective gates that reject bad output and force iteration toward “works.”

The technique’s origin and framing are most closely associated with entity ["people","Geoffrey Huntley","software engineer"], who emphasizes “loop-thinking” and a *monolithic* approach (single repo, one task per loop), in contrast to complex multi-agent orchestration that can amplify nondeterminism.

The name references entity ["fictional_character","Ralph Wiggum","simpsons character"] from entity ["tv_show","The Simpsons","animated tv series"], a nod to persistence-through-iteration.

## Major families of Ralph Loop implementations

Because “Ralph Loop” is an unofficial primitive, the ecosystem has converged on several common *implementation families* rather than a single canonical workflow:

A “classic” bash outer loop is the foundational shape: a `while`/`for` loop feeds a stable prompt file into a CLI repeatedly (with a max-iterations safety cap), relying on disk state and commits to move forward. The minimal expression appears in the playbook documentation as essentially “cat prompt → run agent → repeat.”

A second family keeps the loop *inside* an existing agent session via a **stop hook**. In entity ["company","Anthropic","ai company"]’s Claude Code plugin implementation, a stop hook prevents the session from exiting while a Ralph state file exists, and re-feeds the same prompt back to the agent; completion is detected via a promise string embedded in `<promise>…</promise>`.

A third family layers *workflow infrastructure* around the loop: richer task formats, per-iteration logs, safety circuit breakers, rate limiting, scheduling, steering files, cross-model review, or even parallel execution. Representative examples include:

- Multi-model worker/reviewer loops in entity ["company","Block","fintech company"]’s “goose” Ralph Loop recipes, where each iteration runs a worker model and a reviewer model in separate steps and persists review feedback in files between fresh sessions.
- End-to-end “project enablement” and safety tooling (rate limiting, exit detection, allowed-tools control, tmux monitoring) in Frank Bria’s Ralph-for-Claude-Code scripts, centered on a `.ralph/` workspace and `.ralphrc` config.
- Token/health tracking, “gutter” (stuck) detection, context rotation thresholds, and parallel worktrees in entity ["company","Cursor","ai coding company"] CLI implementations (e.g., Agrim Singh’s repo), using `.ralph/` logs and task checkboxes as progress state.

These families are compatible: many teams start with a simple bash wrapper, then progressively add safeguards (iteration caps, PRD validation, scheduling), then add “operator levers” (steering files, richer task structures) once they see failure modes in the wild.

## Common Ralph Loop artifacts and directory layouts

Even though file names vary, most Ralph workflows revolve around three on-disk roles: **(a) what to build, (b) what happened, (c) how to run the loop.** The most common artifacts cluster into these buckets.

A PRD/task source file is the authority the agent uses to pick the next unit of work:

- JSON PRD with `passes: false/true` per story (popularized in repos like snarktank/ralph and ports), often with `branchName`, priority, and acceptance criteria.
- Markdown PRD with an embedded JSON task list or checklist-style tasks (e.g., `prd.md` produced by a `/create-prd` command in the “quickstart” approach).
- A plan file (`IMPLEMENTATION_PLAN.md`) derived from “gap analysis” between `specs/*` and the codebase, used heavily in the playbook-style, two-prompt planning/build workflow.
- A task table with per-task files (`tasks.json` + `tasks/TASK-{ID}.json`) for scaling to large backlogs (PageAI’s “.agent/” structure).

A progress/memory file captures what the last iteration learned so the next fresh context can avoid repeating mistakes:

- `progress.txt` / `progress.md` append-only learnings, often with a “Codebase Patterns” section near the top for reusable conventions and gotchas.
- `activity.md` as a human-readable iteration log (especially in UI-heavy loops with screenshots).
- “guardrails” or “Signs” files that explicitly accumulate lessons learned and constraints for future iterations (seen in multiple `.ralph/`-based frameworks).

A prompt file provides stable per-iteration instructions and invariants:

- `PROMPT.md` / `prompt.md` (or tool-specific equivalents like `CLAUDE.md`) that instruct: read PRD + progress, pick one task, implement, run checks, commit, update PRD/progress, and stop only when complete.
- Mode-split prompts (`PROMPT_plan.md` vs `PROMPT_build.md`) to separate planning/gap analysis from implementation.

Additional files frequently appear as “operator levers” and observability:

- A “steering” file you can edit *while the loop runs* to redirect behavior (e.g., `.agent/STEERING.md` that the agent checks each iteration).
- Logs/history folders (`history/`, `.ralph/logs`, `.ralph/errors.log`, `.ralph/activity.log`, per-iteration raw output dumps).
- Screenshot directories for visual verification in UI tasks (either via custom browser skills or Playwright flows).

Finally, some implementations add a *state file* to represent the loop itself:

- Claude Code’s stop-hook plugin stores state as `.claude/ralph-loop.local.md` with YAML frontmatter for `iteration`, `max_iterations`, and `completion_promise`, plus the prompt body after `---`.

## ralph.sh and loop runner variants found in the wild

Below are representative loop runners that illustrate how the ecosystem implements the “outer loop.” (These are *examples of patterns*, not endorsements; you’ll notice the “same prompt + file state + cap + completion signal” repeating.)

A minimal “outer loop” (playbook baseline) is literally “run agent with prompt; restart forever.”

A “simple-but-opinionated” bash wrapper (AIHero-style) adds: sandbox execution, print mode, max iterations, and promise detection:

```bash
for ((i=1; i<=$1; i++)); do
  result=$(docker sandbox run claude -p "@PRD.md @progress.txt ... If complete, output <promise>COMPLETE</promise>.")
  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then exit 0; fi
done
```

A “project quickstart” variant (coleam00) stresses **one task per iteration**, browser verification, logging, and commits—while the runner just repeats `claude -p "$(cat PROMPT.md)"` and checks for `COMPLETE`.

A PRD-JSON-driven runner (snarktank/ralph) supports multiple tools (Amp vs Claude Code), uses `prd.json` + `progress.txt`, archives prior runs when branch changes, and detects completion via output text.

A stricter Claude-only port (claude-ralph) hardens completion detection: it checks for a completion signal *and* verifies the PRD actually has zero remaining `passes: false` stories before exiting, reducing “false-complete” failures.

A scalable “task table + promise tags + exit codes” pattern (PageAI) formalizes statuses like `<promise>COMPLETE</promise>`, `<promise>BLOCKED:reason</promise>`, and `<promise>DECIDE:question</promise>` and documents explicit exit codes; its structure breaks tasks into `.agent/tasks.json` and per-task specs.

A usage-aware scheduler (ralph-installer) wraps the same loop call but monitors usage via an OAuth usage endpoint, can wait for a new usage block, and enforces max usage thresholds so AFK loops don’t unintentionally burn a full quota.

A “safety-first systems loop” (frankbria/ralph-claude-code) pushes this further: it centralizes state into `.ralph/`, applies `--allowed-tools` restrictions, rate limits calls/hour, supports session continuity/resume, and integrates tmux monitoring; the loop itself is a large script composed of library utilities and configuration loading from `.ralphrc`.

And a “context-health aware” runner (Cursor CLI ecosystem) treats context limits as first-class: it parses stream output, estimates token usage from read/write/tool activity, emits WARN/ROTATE signals at thresholds (e.g., 70k/80k), and detects “gutter” states like repeated failing commands or file thrashing—then rotates to fresh context.

## Hooks, skills, and mid-loop steering patterns

The most explicit “hook” pattern is Claude Code’s **stop hook implementation**, which turns “exit” into “continue.” The hook: (1) checks for `.claude/ralph-loop.local.md`, (2) reads the transcript to find the last assistant output, (3) detects a `<promise>` tag match to a configured completion phrase, (4) blocks exit and returns the same prompt as the reason if not complete, incrementing an iteration counter in the state file.

In bash-based ecosystems, “hooks” are usually implemented as *structured files the agent reads every iteration* (or as wrapper logic around the CLI). Common patterns include:

Skills directories. Several implementations treat “skills” as reusable, tool-agnostic instruction packs (PRD generation, browser testing, reviews, etc.), sometimes symlinked into multiple agent tool directories for compatibility.

Steering files. PageAI’s implementation documents `.agent/STEERING.md` as a live-edit lever: the agent checks it each iteration and prioritizes “critical work” before continuing normal tasks.

Cross-model review. Block/goose’s recipes implement an explicit worker/reviewer split, writing review feedback into `.goose/ralph/` state files that the next worker iteration must address first—an automated “LLM-as-judge” backpressure layer that complements tests.

Observability and stuck detection. Newer loop runners increasingly treat “being stuck” as detectable: repeated failing commands, repeated edits to the same files (“thrashing”), or repeated “done” signals without actual completion—triggering circuit breakers or rotation.

Usage/cost governors. Nearly every mature write-up warns about runaway usage and recommends hard caps (max iterations), while some tools implement rate limiting, usage polling, and wait-for-reset scheduling.

## Recommended implementation rules and a reference scaffold

This section consolidates recurring “rules and constraints” into a practical implementation specification, then provides a small reference scaffold you can adapt.

### Operational rules and constraints that consistently improve outcomes

A Ralph loop converges when its *unit of work* is right-sized, its *verification gates* are real, and its *memory artifacts* stay lean and reusable.

Right-size the work unit. Multiple sources converge on the same constraint: each PRD item must be small enough to complete within one context window; “build the whole dashboard” is too big, while “add a filter dropdown” is the right granularity.

Make backpressure non-negotiable. The Ralph Loop “without feedback loops” is repeatedly described as turning into a high-throughput broken-code generator; with type checks, tests, CI/build validation, and browser verification (for UI), it becomes an iterative gradient toward correctness.

Enforce “one task/story per iteration.” This shows up as an explicit prompt rule in multiple templates, and is treated as the key lever for keeping context lean and preventing half-done mega-commits.

Use file-based memory deliberately. Progress logs should capture *reusable* learnings (patterns, gotchas, commands, locations) rather than dumping every transient step; some templates explicitly promote a “Codebase Patterns” section near the top to prevent rediscovery churn.

Treat plans as disposable. In the playbook-style workflows, when the plan drifts, regenerating it in planning mode is cheaper than trying to salvage stale state; this is presented as a core philosophical guardrail, not an edge case.

Harden completion detection. A common failure mode is “false completion” (agent mentions COMPLETE, or outputs a promised string without truly meeting criteria). Stronger runners therefore (a) use scoped `<promise>` tags, (b) require explicit completion promises, and/or (c) verify completion by checking PRD/task state on disk before exiting.

Add cost governors early. At minimum: max iterations. More advanced setups add usage-aware scheduling, call/hour rate limits, circuit breakers, and “wait for reset” behavior—because real-world accounts hit usage blocks and long-running loops can burn through quotas quickly.

Prefer a monolithic loop unless you have a clear reason. While parallel and multi-model systems exist, the origin framing warns that multiplying nondeterministic agents can create “red hot mess” orchestration complexity; the safest baseline remains “one repo, one loop, one task at a time.”

### Reference scaffold you can copy and adapt

What follows is a compact “best-of” scaffold synthesized from the most repeated patterns (PRD/task file + progress log + prompt + loop runner with verified completion). The file naming below intentionally stays close to the most common conventions (`prd.json`, `progress.txt`, `prompt.md`, `ralph.sh`).

**Suggested directory layout**

```text
your-project/
├── ralph/
│   ├── prd.json
│   ├── progress.txt
│   ├── prompt.md
│   └── ralph.sh
└── (your actual source code)
```

**A minimal-but-hardened `prd.json` template (example)**

```json
{
  "project": "MyProject",
  "branchName": "ralph/my-feature",
  "description": "Short description",
  "userStories": [
    {
      "id": "US-001",
      "title": "Small, testable story",
      "description": "As a user, I want ... so that ...",
      "acceptanceCriteria": [
        "Specific criterion 1",
        "Specific criterion 2",
        "typecheck passes",
        "tests pass"
      ],
      "priority": 1,
      "passes": false,
      "notes": "",
      "dependsOn": []
    }
  ]
}
```

**A good `progress.txt` starting point**

```markdown
# Ralph Progress Log
Started: 2026-02-18

## Codebase Patterns
- (Add reusable patterns here as you discover them)

---

## 2026-02-18 - INIT
- Initialized PRD + prompt + loop runner
```

**A `prompt.md` that enforces the Ralph invariants**

```markdown
# Ralph Agent Instructions

You are an autonomous coding agent working in this repo.

Every iteration:
1) Read ralph/prd.json and find the highest-priority story where passes=false.
2) Read ralph/progress.txt (especially "Codebase Patterns").
3) Work on EXACTLY ONE story.
4) Run the project’s verification steps (tests/typecheck/lint/build as appropriate).
5) If verification passes, commit changes with:
   feat: [US-xxx] - [Story Title]
6) Update ralph/prd.json: set that story’s passes=true.
7) Append a progress entry to ralph/progress.txt:
   - what changed
   - commands run + results
   - learnings/gotchas/patterns

Hard rules:
- Do NOT do multiple stories in one iteration.
- Do NOT mark passes=true until acceptance criteria are met and verification passes.
- Prefer fixing the cause over weakening tests.
- Keep commits focused and minimal.

Stop condition:
- When ALL stories have passes=true, output ONLY:
  <promise>COMPLETE</promise>
```

**A bash runner (`ralph.sh`) that verifies completion by checking PRD state**

This runner implements the “classic” outer loop (fresh process each iteration), but avoids early exits by *also* checking the PRD JSON for remaining `passes: false`, similar in spirit to hardened Claude-only ports.

```bash
#!/usr/bin/env bash
set -euo pipefail

# Ralph Loop Runner (reference scaffold)
# Usage:
#   ./ralph/ralph.sh 20
# Environment:
#   RALPH_AGENT_CMD: command to run your agent in headless mode (reads prompt from stdin)
#     Examples:
#       export RALPH_AGENT_CMD='claude -p --dangerously-skip-permissions'
#       export RALPH_AGENT_CMD='docker sandbox run claude -p --permission-mode acceptEdits'
#
# Requirements:
#   jq, git, and your agent CLI.

MAX_ITERATIONS="${1:-10}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
PROMPT_FILE="$SCRIPT_DIR/prompt.md"

: "${RALPH_AGENT_CMD:=claude -p --dangerously-skip-permissions}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required."
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required."
  exit 1
fi

if [[ ! -f "$PRD_FILE" ]]; then
  echo "Error: missing $PRD_FILE"
  exit 1
fi

if [[ ! -f "$PROGRESS_FILE" ]]; then
  cat > "$PROGRESS_FILE" <<EOF
# Ralph Progress Log
Started: $(date '+%Y-%m-%d %H:%M:%S')

## Codebase Patterns
- (Add reusable patterns here)

---
EOF
fi

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Error: missing $PROMPT_FILE"
  exit 1
fi

all_stories_complete() {
  # returns 0 if complete, 1 otherwise
  local remaining
  remaining="$(jq '[.userStories[] | select(.passes == false)] | length' "$PRD_FILE" 2>/dev/null || echo "1")"
  [[ "$remaining" == "0" ]]
}

echo "Ralph starting: max iterations = $MAX_ITERATIONS"
echo "Agent command: $RALPH_AGENT_CMD"

for ((i=1; i<=MAX_ITERATIONS; i++)); do
  echo ""
  echo "=================================================="
  echo "Iteration $i / $MAX_ITERATIONS"
  echo "=================================================="

  # Short-circuit if PRD already complete
  if all_stories_complete; then
    echo "✅ PRD already complete."
    exit 0
  fi

  # Run agent with the stable prompt (agent reads PRD/progress itself)
  # Capture output for promise detection, but DO NOT trust it alone.
  set +e
  AGENT_OUTPUT="$(
    cat "$PROMPT_FILE" | bash -lc "$RALPH_AGENT_CMD" 2>&1
  )"
  AGENT_EXIT="$?"
  set -e

  echo "$AGENT_OUTPUT"

  # If agent claims COMPLETE, verify PRD state before exiting
  if grep -q "<promise>COMPLETE</promise>" <<<"$AGENT_OUTPUT"; then
    if all_stories_complete; then
      echo "✅ Verified: all stories passes=true. Exiting."
      exit 0
    else
      echo "⚠️ Agent output COMPLETE but PRD still has incomplete stories. Continuing."
    fi
  fi

  # Also allow PRD check to terminate even if promise tag is missing
  if all_stories_complete; then
    echo "✅ Verified: all stories passes=true (no promise tag needed). Exiting."
    exit 0
  fi

  if [[ "$AGENT_EXIT" -ne 0 ]]; then
    echo "⚠️ Agent exited non-zero ($AGENT_EXIT). Continuing (next iteration may recover)."
  fi

  sleep 2
done

echo ""
echo "⚠️ Max iterations reached without verified completion."
echo "Check: $PRD_FILE and $PROGRESS_FILE"
exit 1
```

### Where to extend this scaffold (based on proven patterns)

If you want to “industrialize” beyond the reference scaffold, the ecosystem’s most repeated upgrades are:

- Add **promise tags + exit codes** (`BLOCKED`, `DECIDE`) so the loop can stop safely when human input is needed, not just when it’s done.
- Add a **live steering file** (like `STEERING.md`) so you can redirect the agent mid-run without editing the primary prompt.
- Add **usage-aware scheduling** (stop at N% utilization, wait for next block) if you run AFK.
- Add **circuit breakers / stuck detection** (repeated failures, thrash detection) and **context rotation** thresholds when you can’t (or don’t want to) rely solely on “one task per iteration” to keep context clean.
- Add **cross-model review** for subjective quality gates (Ship/Revise), particularly on UI/UX-heavy tasks where tests won’t capture everything.

The throughline is consistent: start with the simplest loop that can *validate* and *checkpoint* work, then watch how it fails, then encode fixes as backpressure, guardrails, and observability—“programming the loop” rather than prompting harder.
