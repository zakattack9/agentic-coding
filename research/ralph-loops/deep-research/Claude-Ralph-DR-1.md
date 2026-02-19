# The Ralph Loop: a complete guide to agentic coding's breakout primitive

**The Ralph Loop is a deceptively simple bash `while` loop that repeatedly runs an AI coding agent against a task file until verifiable completion criteria are met.** Created by Australian developer Geoffrey Huntley in early 2025 and named after the persistently optimistic Simpsons character Ralph Wiggum, it has become the dominant pattern for autonomous AI-assisted software development. The technique went viral in late 2025 after Anthropic shipped an official Claude Code plugin, Matt Pocock's explanatory thread reached millions, and developers reported delivering $50,000 contracts for under $300 in API costs. Its power lies not in complexity but in a counterintuitive insight: **spawning a fresh context window every iteration eliminates "context rot"** — the degradation of LLM reasoning as conversation history accumulates — while externalizing all state to the filesystem.

---

## How a goat farmer from Australia reinvented software development

Geoffrey Huntley discovered the underlying pattern in **February 2024** while doing spec-based development with LLMs. As he recounted on the Dev Interrupted podcast: *"When I discovered this, it literally made me want to Ralph. Ralph is a term for vomiting. I could actually see where we were going. I was building software in my sleep."* The technique remained unnamed until **June 19, 2025**, when Huntley demonstrated it at a San Francisco meetup of ~15 engineers. He livestreamed autonomous coding overnight from Australia while the audience watched. *"It needs a name,"* he decided. *"It's kind of dumb, it's kind of lovable and it never gives up. And it made me wanna Ralph, so I called it Ralph, as in Ralph Wiggum."*

The canonical blog post appeared on **July 14, 2025** at ghuntley.com/ralph/, introducing the purest form of the loop:

```bash
while :; do cat PROMPT.md | claude -p ; done
```

The name carries a **dual meaning**: Ralph Wiggum the character (simple-minded, persistent, never gives up despite frequent failures) and "ralph" as slang for vomiting (because discovering the technique's implications for the software industry made Huntley feel sick). His follow-up post in January 2026, "Everything is a Ralph Loop," expanded the philosophy: *"Ralph is an orchestrator pattern where you allocate the array with the required backing specifications and then give it a goal then looping the goal... Software is now clay on the pottery wheel."*

The timeline of adoption accelerated rapidly. In **September 2025**, Huntley launched Cursed Lang (a full programming language with an LLVM compiler built entirely by running Claude in a Ralph loop for 3 months). In **December 2025**, Anthropic released an official Ralph Wiggum plugin for Claude Code, causing the technique to go fully mainstream. By January 2026, VentureBeat, The Register, and dozens of developer publications were covering it, a $RALPH memecoin appeared on Solana, and a dedicated r/ralphcoding subreddit and Discord community had formed.

---

## Six principles that make the loop work

Every definition of the Ralph Loop converges on the same core mechanics, though different practitioners emphasize different aspects:

**Geoffrey Huntley's definition** is philosophical: *"That's the beauty of Ralph — the technique is deterministically bad in an undeterministic world."* Each iteration is individually unreliable, but the loop structure is deterministic. He uses the "playground" metaphor: *"Ralph is given instructions to construct a playground. Ralph comes home bruised because he fell off the slide, so you add a sign next to the slide saying 'SLIDE DOWN, DON'T JUMP, LOOK AROUND,' and Ralph is more likely to see the sign."*

**Dexter Horthy** (HumanLayer CEO, early adopter since June 2025) emphasizes the architectural insight: *"The key point of ralph is not 'run forever' but 'carve off small bits of work into independent context windows.'"* He calls it "naive persistence" — the LLM isn't protected from its own mess; it's forced to confront it.

**The DreamHost blog** articulates it structurally: *"The loop itself is almost irrelevant — what matters is the contract: State lives in the repo, completion lives outside the model, the agent is replaceable."*

**Beuke.org** provides an academic framing with four elements: Perception (read state), Orientation (assess progress), Decision (pick next task), Action (implement and verify).

**The Shipyard blog** focuses on the behavioral mechanism: *"A Ralph loop re-prompts your agent a set number of times with the same prompt. It refuses to let your agent say it is done with a task, and forces it to keep iterating until it hits a stop condition."*

These definitions converge on **six operating principles**: (1) fresh context every iteration (no context rot), (2) externalized state (progress tracked in files on disk, not model memory), (3) self-correcting behavior (each iteration can see and fix previous mistakes via git history and progress files), (4) one task per loop (single focused scope), (5) deterministic wrapper around non-deterministic models, and (6) verification-driven completion (tests passing, builds succeeding — not the model's self-assessment).

---

## The bash scripts: from five lines to full orchestrators

### The canonical minimal script

Huntley's original is deliberately primitive:

```bash
while :; do cat PROMPT.md | claude -p ; done
```

Or with Amp: `while :; do cat PROMPT.md | npx --yes @sourcegraph/amp ; done`

### snarktank/ralph (707 stars, 106 forks)

The most popular community implementation, supporting both Amp and Claude Code with argument parsing:

```bash
#!/bin/bash
set -e
TOOL="amp"
MAX_ITERATIONS=10
while [[ $# -gt 0 ]]; do
  case $1 in
    --tool) TOOL="$2"; shift 2 ;;
    --tool=*) TOOL="${1#*=}"; shift ;;
    *) if [[ "$1" =~ ^[0-9]+$ ]]; then MAX_ITERATIONS="$1"; fi; shift ;;
  esac
done
```

For Claude Code, it runs: `claude --dangerously-skip-permissions --print < "$SCRIPT_DIR/CLAUDE.md"`. The repo includes `prd.json` (task tracking), `progress.txt` (learning log), a skills system, interactive flowchart visualization, and archive management for previous runs.

### ghuntley/how-to-ralph-wiggum (602 stars, 58 forks)

Huntley's official playbook introduces a **two-mode system** — planning and building:

```bash
#!/bin/bash
if [ "$1" = "plan" ]; then
    MODE="plan"; PROMPT_FILE="PROMPT_plan.md"; MAX_ITERATIONS=${2:-0}
else
    MODE="build"; PROMPT_FILE="PROMPT_build.md"; MAX_ITERATIONS=${1:-0}
fi
ITERATION=0
while :; do
    ITERATION=$((ITERATION + 1))
    if [ "$MAX_ITERATIONS" -gt 0 ] && [ "$ITERATION" -gt "$MAX_ITERATIONS" ]; then break; fi
    cat "$PROMPT_FILE" | claude -p --dangerously-skip-permissions --output-format=stream-json --model opus --verbose
    git push
done
```

The building mode lifecycle runs through 10 stages: orient (subagents study specs), read plan, select task, investigate relevant source, implement with N subagents, validate with backpressure (build/tests), update plan, update AGENTS.md with learnings, commit, and loop restart with fresh context.

### fredflint's gist: TDD-focused with review integration

A sophisticated version adding per-task Linus-style code review:

```bash
#!/bin/bash
set -e
MAX=${1:-10}; SLEEP=${2:-2}; MODEL=${3:-"sonnet"}
for ((i=1; i<=$MAX; i++)); do
  result=$(claude --model "$MODEL" --dangerously-skip-permissions -p "You are Ralph...
    Read PRD.md, find first incomplete task. Implement using TDD.
    Run tests/typecheck. Mark completed ONLY if tests pass.
    After completing, review against linus-prompt-code-review.md.
    If issues found: insert fix tasks (US-XXXa, US-XXXb).
    CRITICAL: Only output <promise>COMPLETE</promise> if EVERY task header is [x]")
  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    incomplete=$(grep -c "^### US-.*\[ \]" PRD.md 2>/dev/null || true)
    if [[ "${incomplete:-0}" -gt 0 ]]; then
      echo "WARNING: COMPLETE signal rejected — $incomplete tasks remaining"
      continue
    fi
    echo "All tasks complete after $i iterations!"; exit 0
  fi
  sleep $SLEEP
done
```

This script **rejects false completion signals** by cross-checking the PRD file for unchecked tasks, even when the model claims to be done.

### prateek's gist: Codex version with comedic promise file

A delightful Codex implementation uses a promise **file** instead of output parsing:

```bash
PROMISE_FILE="I_PROMISE_ALL_TASKS_IN_THE_PRD_ARE_DONE_I_AM_NOT_LYING_I_SWEAR"
rm -f "$PROMISE_FILE"
for ((i = 1; i <= $1; i++)); do
  codex --dangerously-bypass-approvals-and-sandbox exec <<'EOF'
Find highest-priority task from PRD.md, implement it, run tests,
update PRD, commit. ONLY if ALL tasks done, touch file named
I_PROMISE_ALL_TASKS_IN_THE_PRD_ARE_DONE_I_AM_NOT_LYING_I_SWEAR
EOF
  if [[ -f "$PROMISE_FILE" ]]; then
    echo "PRD complete after $i iterations."; exit 0
  fi
done
```

### Other notable implementations

**Scott Hanselman's PowerShell version** (gist) ports Ralph to GitHub Copilot CLI on Windows. **mwarger's gist** adds `.ralphrc` config files, heartbeat monitoring, and profile support. **soderlind's gist** provides a Python wrapper for Copilot CLI. **AnandChowdhary/continuous-claude** adds budget limits (`--max-cost 10.00`) and duration limits (`--max-duration 2h`). The **syuya2036/ralph-loop** repo is agent-agnostic, supporting Claude, Codex, Gemini, and Ollama/Qwen through a unified interface.

---

## Files, structure, and the externalized memory contract

The Ralph Loop's power rests on **externalized state** — everything the agent needs to know lives in files, not in conversation history. The common file structure across implementations:

```
project/
├── ralph.sh / loop.sh          # Main loop runner
├── PROMPT.md                   # Instructions fed each iteration
│   (or PROMPT_plan.md + PROMPT_build.md for two-mode systems)
├── CLAUDE.md / AGENTS.md       # Accumulated knowledge, conventions, learnings
├── prd.json / PRD.md           # Product requirements with task tracking
├── progress.txt                # Persistent learning log across iterations
├── specs/                      # Individual spec files per feature/topic
├── IMPLEMENTATION_PLAN.md      # Prioritized task list (planning mode output)
├── .claude/
│   ├── settings.json           # Permissions and sandbox configuration
│   ├── commands/               # Custom slash commands (/create-prd, etc.)
│   ├── skills/                 # Claude Code skills (PRD generation, browser testing)
│   └── ralph-loop.local.md     # Loop state file (plugin variant)
└── .logs/                      # Iteration output logs
```

**The PRD** takes two forms. Markdown-based PRDs use checkbox syntax (`### US-001: Create database [ ]`), while JSON-based PRDs (popularized by snarktank/ralph) track stories with a `passes` field: `{"id": "US-001", "title": "...", "passes": false, "acceptanceCriteria": [...]}`. The JSON format enables programmatic verification — the loop checks if all stories have `passes: true`.

**progress.txt** serves as the agent's long-term memory. Each iteration appends what was accomplished, what failed, and what was learned. This file is read at the start of every iteration, giving the fresh context window access to accumulated institutional knowledge. Some implementations split this into `progress.txt` for task status and `AGENTS.md` for operational learnings (gotchas, patterns, conventions discovered during development).

**Four completion mechanisms** exist across implementations: (1) the `<promise>COMPLETE</promise>` output tag, (2) touching a sentinel file (like the comically named `I_PROMISE_ALL_TASKS_IN_THE_PRD_ARE_DONE_I_AM_NOT_LYING_I_SWEAR`), (3) all PRD task headers marked `[x]` or all JSON stories having `passes: true`, and (4) a stop hook returning exit code 0.

---

## Hooks: how the loop extends beyond bash

### Stop hooks (the official Anthropic mechanism)

The Anthropic plugin uses Claude Code's **Stop Hook** to intercept exit attempts rather than wrapping the agent in an external bash loop:

```
1. Claude works on the task
2. Claude tries to exit
3. Stop hook intercepts, checks for completion promise
4. If promise NOT found → blocks exit (exit code 2), re-feeds same prompt
5. If promise found → allows exit, loop ends
```

The state is tracked in `.claude/ralph-loop.local.md` with YAML frontmatter (`active: true`, `iteration: 0`, `max_iterations: 20`, `completion_promise: null`). A critical improvement by Jon Roosevelt added **session isolation** — scoping state files per `session_id` to prevent multi-session conflicts: `.claude/ralph-loop.${SESSION_ID}.local.md`.

Huntley has expressed reservations about the plugin approach. Because it runs within a single session, it doesn't get fresh context windows, defeating what many consider Ralph's core advantage. *"This isn't it,"* he said. Community sentiment largely agrees — practitioners who've tried both report the raw bash loop produces better results for long-running tasks.

### Session start hooks

For multi-session environments, a session start hook captures the session ID:

```bash
#!/bin/bash
HOOK_INPUT=$(cat)
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id // empty')
if [[ -n "$SESSION_ID" ]] && [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
    echo "export CLAUDE_SESSION_ID='$SESSION_ID'" >> "$CLAUDE_ENV_FILE"
fi
```

### Validation and testing hooks

Some implementations embed verification directly in the hook layer. Boris Cherny's approach uses a **background agent** after each iteration to review all changed files, run the full test suite, check for regressions, and report issues — separating the "worker" from the "reviewer." The Goose (Block) implementation formalizes this as a **cross-model review pattern**: a worker model (e.g., GPT-4o) implements changes while a different reviewer model (e.g., Claude Sonnet 4) evaluates them with SHIP/REVISE decisions.

### Gemini CLI extension

The Gemini CLI port uses an `AfterAgent` hook that clears the agent's memory between turns (enforcing fresh context without an external bash loop) and includes "Ghost Protection" — detecting prompt mismatches if a new task interrupts an active loop.

### Config-driven hooks (ralph-addons)

A Hacker News Show HN project (cvemprala/ralph-addons) adds YAML-configurable extensions: task routing (B* tasks to backend agents, F* tasks to frontend agents), auto-commits per task group, verification hooks (build/typecheck after each task), lint/test/notify hooks, and retry-on-failure logic. The creator's philosophy: *"Core is still a bash loop. State in files. Each iteration: read state, do one task, update state, stop. Repeat."*

---

## Rules, optimizations, and the art of tuning Ralph

### Context management: the "smart zone"

Huntley conceptualizes the context window as a malloc allocation. The **"smart zone"** is 30-60% utilization — beyond that, reasoning quality degrades. With a 200K token window (~176K usable), allocating the first ~5,000 tokens for specs and keeping to one task per loop maximizes time spent in the smart zone. **Subagents serve as memory extensions**: each gets ~156KB of its own context that is garbage-collected after use, allowing the main agent to fan out investigation without polluting its primary context.

### Model selection strategy

Huntley's playbook recommends mixing models: **Opus for the primary agent** (task selection, prioritization, coordination), **Sonnet subagents for efficiency** (searches, summaries, simple file operations), **Opus subagents for complex reasoning** (architectural decisions), and **Haiku subagents for trivial tasks** (status checks, simple reads).

### Prompt engineering patterns

A well-structured PROMPT.md follows this template (from snarktank/ralph):

```markdown
# Ralph Agent Instructions
You are an autonomous coding agent.
## Your Task
1. Read prd.json for requirements
2. Read progress.txt for accumulated learnings
3. Pick the highest priority story where passes: false
4. Implement that SINGLE user story
5. Run quality checks (typecheck, lint, test)
6. If checks pass, commit ALL changes and set passes: true
7. Append progress to progress.txt
## Stop Condition
If ALL stories have passes: true, output: <promise>COMPLETE</promise>
Otherwise, end normally (next iteration picks up the next story).
```

Matt Pocock's **11 Tips** distill practical wisdom: start with human-in-the-loop Ralph before going AFK, cap iterations (**5-10 for small tasks, 30-50 for large**), define "done" with binary success conditions, use JSON PRD items with a `passes` field, and recognize that vague tasks risk infinite loops or premature exits. His loops typically take **30-45 minutes**.

### The "guitar tuning" technique

Huntley's signature optimization method: start with minimal guardrails and let Ralph build. Observe failures. When Ralph fails a specific way, add a "sign" to the prompt — a targeted instruction addressing that exact failure mode. Iterate until failures are addressed. *"Eventually you get a new Ralph that doesn't feel defective."* This creates a **compound flywheel**: more iterations → more documented knowledge in AGENTS.md → faster/better future iterations.

### Backpressure through verification

Tests, typechecks, lints, and builds serve as "backpressure" — objective criteria that reject invalid work regardless of the model's confidence. For **UI work** that resists programmatic verification, a screenshot protocol forces at least two loop iterations: take screenshots, rename with "verified_" prefix after review, and only output the completion promise when all screenshots are verified.

For **subjective quality criteria** (aesthetics, UX), some practitioners use LLM-as-judge: a separate model evaluates quality with binary pass/fail. This aligns with Ralph's philosophy — the loop provides eventual consistency through iteration even with non-deterministic reviews.

---

## The ecosystem: 20+ implementations and counting

The Ralph Loop has spawned a remarkable ecosystem of tools, each optimizing for different workflows:

The **official Anthropic plugin** (`/plugin install ralph-wiggum@claude-plugins-official`) uses stop hooks within a single session. **snarktank/ralph** (707 stars) is the most popular community implementation with PRD-driven workflows and a skills system. **ghuntley/how-to-ralph-wiggum** (602 stars) is the official playbook with two-mode planning/building. **coleam00/ralph-loop-quickstart** (103 stars) explicitly rejects the Anthropic plugin in favor of the bash loop approach and adds browser verification via Vercel's agent-browser CLI.

**Th0rgal/open-ralph-wiggum** is a TypeScript CLI supporting multiple agents (Claude Code, Codex, Copilot, OpenCode) with a TUI status dashboard and struggle indicators. **hexsprite/cursor-ralph** ports Ralph to Cursor IDE using osascript workarounds for Cursor's 5-iteration followup limit. **AnandChowdhary/continuous-claude** adds budget and duration controls. **mj-meyer/choo-choo-ralph** replaces JSON task files with Beads, a git-native task tracker. **wiggumdev/ralph** provides a polished CLI with `ralph init`, `ralph run`, and `ralph check` commands and TOML configuration.

At the infrastructure level, **ohare93/juggle** offers a TUI for running parallel agents on git worktrees, and **mj1618/swarm-cli** manages Ralph loops in a DAG pipeline (planner → implementer → reviewer). The **gmickel/flow-next** plugin adds cross-model review gates with model escalation. **Block's Goose** framework implements Ralph with separate worker and reviewer models using YAML recipes.

---

## What the community says: praise, skepticism, and evolution

The Hacker News discussion on Huntley's original post (item 44565028) was the breakout moment. Subsequent HN threads have explored both enthusiasm and skepticism. Critics point to **"overcooking"** (leaving the loop too long causes the AI to add unwanted features and refactor working code) and **"undercooking"** (stopping too early leaves half-done features). One commenter on the "Ralph Wiggum Doesn't Work" thread argued: *"The fix isn't 'bigger context,' it's isolating steps and passing explicit state between them, with verification and guardrails"* — which, ironically, describes exactly what well-implemented Ralph loops do.

The economic claims have drawn both excitement and scrutiny. Huntley's headline stat — **a $50,000 contract delivered for $297 in API costs** — excludes human specification and review labor, a point critics emphasize. More measured assessments suggest **$10.42/hour in compute costs** with Sonnet, with typical session costs ranging from $5-15 for simple tasks to $30-75 for complex ones. A YC hackathon team shipped 1,100+ commits across 6 repos overnight for ~$800 total.

The technique has generated extensive media coverage: a **VentureBeat** feature ("How Ralph Wiggum went from 'The Simpsons' to the biggest name in AI"), a **Register** article, the **Dev Interrupted podcast** (58-minute interview with Huntley), the **Tool Use podcast** (with Amp founder Ryan Carson), and Matt Pocock's viral YouTube overview and X thread that reached millions. Multiple Substack newsletters (Dev Interrupted, SparkryAI, Bytes-Sized Brainwaves, Ken Huang's Agentic AI) provide ongoing analysis, and the **awesome-ralph** GitHub repo curates the full resource ecosystem.

The most forward-looking discussion — "Continuous agents and what happens after Ralph Wiggum?" on Hacker News — envisions evolution toward fully autonomous continuous development: `while true: if tickets exist → burn down the backlog; if not → figure out what feature would make sense to add next, create PRD, break down into tickets`. Huntley himself hints at this with his "Gas Town" concept and "The Weaving Loom" for evolutionary, self-healing software.

---

## Conclusion

The Ralph Loop's significance extends beyond its bash-script simplicity. It represents a paradigm shift in how developers think about AI agents: **not as conversation partners but as stateless workers orchestrated by external, deterministic processes**. The technique's rapid evolution — from a 5-line bash loop to an ecosystem of 20+ implementations with hooks, cross-model review gates, DAG pipelines, and budget controls — demonstrates both its fundamental soundness and the community's hunger for practical agentic coding patterns. The key insight remains what Huntley articulated from the start: fresh context windows, externalized state, and objective verification form a more reliable foundation than sophisticated multi-agent frameworks. The loop is dumb. The loop works. That's the point.