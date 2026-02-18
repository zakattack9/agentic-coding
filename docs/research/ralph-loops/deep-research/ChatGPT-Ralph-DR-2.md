# Ralph Loop Agentic Coding Method Deep Research Aggregation

## [RAW] different ralph.sh scripts

Below are **raw, unmodified excerpts** (kept short) that illustrate *distinct* “loop runner” implementations seen in the wild.

**snarktank/ralph — Claude Code branch (YOLO + file-fed prompt)**
```bash
OUTPUT=$(claude --dangerously-skip-permissions --print < "$SCRIPT_DIR/CLAUDE.md" 2>&1) || true
```

**snarktank/ralph — Amp branch (stdin-fed prompt)**
```bash
OUTPUT=$(cat "$PROMPT_FILE" | amp --dangerously-allow-all 2>&1) || true
```

**coleam00/ralph-loop-quickstart — print-mode capture (explicit output-format, no YOLO flag shown)**
```bash
result=$(claude -p "$(cat PROMPT.md)" --output-format text 2>&1) || true
```

**RobinOppenstam/claude-ralph — tee-to-stderr pattern (preserve output + loop logic)**
```bash
OUTPUT=$(cat "$PROMPT_FILE" | claude -p --dangerously-skip-permissions --verbose 2>&1 | tee /dev/stderr) || true
```

**htlkg/super-ralph — Amp runner variant (tee-to-stderr)**
```bash
OUTPUT=$(cat "$SCRIPT_DIR/prompt.md" | amp --dangerously-allow-all 2>&1 | tee /dev/stderr) || true
```

**AIHero “afk-ralph.sh” — Docker Desktop sandbox wrapper (looped, print-mode)**
```bash
result=$(docker sandbox run claude --permission-mode acceptEdits -p "@PRD.md @progress.txt \
```

## [HIGH] different formats for the persistent memory across ralph loop iterations

This section **extracts the stable structural patterns** (headings/fields/layout), while ignoring “content inside” those structures.

### progress.txt or activity-style markdown logs

A common *append-only* memory artifact is a markdown log where the “top of file” is curated, and “bottom” grows per iteration.

**Observed structural pattern (derived from multiple prompts and templates):**
- **Curated “Codebase patterns / conventions” block** near the top (intended to stay short and high-signal)
- **Append-only iteration entries**, each typically keyed by a timestamp + task/story identifier, then a small fixed outline (“what changed”, “files changed”, “learnings”, etc.)
- Some implementations use an **“activity” header** (status + counters) plus a **session log** section underneath

### progress.json as structured short-term state

Two materially different “progress.json” styles show up:

**Structured session + tasks memory (AFK-style):**
- Top-level session metadata:
  - `started_at`
  - `iterations`
  - `last_branch`
  - `tasks` (map keyed by task-id)
- Per-task record (TaskProgress) core fields:
  - `id`, `source`, `status`
  - timestamps (`started_at`, `completed_at`)
  - `failure_count`
  - `commits` (list)
  - optional `message`
  - `learnings` (list; short-term, task-scoped)

**Execution telemetry for “currently running” display (Ralph monitor style):**
- `.ralph/progress.json` holds *ephemeral execution progress* fields such as:
  - `status` (e.g., executing/idle)
  - `indicator` (spinner glyph)
  - `elapsed_seconds`
  - `last_output` (truncated status text)

### progress.yaml as phase/roadmap state

A YAML “progress tracker” format appears in phase-driven Ralph variants:

- `current_phase` (nested: phase number, name, description, started, status, user_stories)
- `completed_phases` (list; each includes phase number/name/completed date, sometimes deliverables)
- `phases` (mapping keyed by phase number; each includes name/description/prerequisite/user_stories plus optional structures like deliverables and checkpoints)

## [SUM] different methods of updating memory files

This section provides a **high-level summary + outline** of the dominant “memory update” strategies used with Ralph loops, focusing on **CLAUDE.md** and **.claude/rules/*.md** patterns (plus the adjacent “Ralph memory” files they typically coordinate with).

### Memory update strategies seen in practice

Ralph workflows generally rely on **multiple “memory planes”**, updated in different ways:

**Instruction memory (human- or agent-maintained guidelines)**
- **Project memory in `CLAUDE.md` / `.claude/CLAUDE.md`**: teams store shared conventions, commands, architecture notes, and constraints. Claude Code loads these with clear precedence rules across directory hierarchies.
- **Modular rules in `.claude/rules/*.md`**: instead of one large instruction file, rules are split by topic (testing, code style, security), and can be **path-scoped** using YAML frontmatter (`paths:` globs).
- **Direct editing workflow**: Claude Code supports editing memory files via the in-session `/memory` command (opens the selected memory file in your editor).
- **Bootstrap workflow**: `/init` can generate an initial CLAUDE.md baseline for a project.

**Auto memory (agent-written, personal, per-repo notes)**
- Claude Code can maintain an **auto memory directory** under `~/.claude/projects/<project>/memory/`, with a concise `MEMORY.md` index and optional topic files; only the first ~200 lines of `MEMORY.md` are auto-loaded at session start.

**Loop memory (iteration persistence for “fresh-context” loops)**
- Many Ralph prompts explicitly require the agent to:
  - append a “what happened + learnings” entry each iteration in a progress log, and
  - move durable patterns into a short “patterns/conventions” section at the top of that file.
- Several Ralph variants also require updating **AGENTS.md** files near touched code to preserve directory-specific conventions (so future runs inherit local patterns).

**Human steering during an active loop**
- Some systems include a “live steering” file intended to be edited *while the loop is running*, checked every iteration, and allowed to override normal task selection (e.g., critical fixes, unblockers).

### Maintenance heuristics that recur across implementations

- Keep instruction memory concise; use modular rules instead of endlessly growing a single file.
- Prefer **topic- or path-scoped rules** (frontmatter) over global mandates when only certain folders need constraints.
- Treat “progress logs” as **append-only** (audit trail) and treat “patterns/guardrails” as **curated** (high-signal, low-noise).

## [HIGH] different formats for the task tracker

This section extracts **the stable shapes** used to represent “what’s left to do” and “what is done,” with emphasis on `prd.json`, `tasks.json`, and YAML-based trackers.

### prd.json with story objects and boolean completion

A widely used machine-readable task tracker model is:

- Root fields: `project`, `branchName`, `description`, `userStories`
- Each `userStories[]` item commonly includes:
  - identifiers (`id`, `title`)
  - narrative (`description`)
  - `acceptanceCriteria[]` (explicit verification hooks)
  - priority ordering (`priority`)
  - completion flag (`passes: false|true`)
  - optional `notes`

### tasks.json + per-task spec files

A second pattern is “lookup table + per-task expansion”:

- A `tasks.json` index contains the “task list / statuses.”
- Each task can have its own file like `tasks/TASK-{ID}.json` with step-by-step requirements, enabling deeper per-task context as the task count grows.

### Markdown checkbox plans (“fix_plan.md” / “TASKS.md”)

A common tracker alternative (especially for simpler loops) is a markdown checklist:

- Priority sections + checkboxes:
  - `- [ ]` incomplete
  - `- [x]` complete
- Some implementations also separate “active” vs “complete” as top-level headings (kanban-ish).

### tasks.yaml

YAML trackers appear in a “lightweight checklist” style:

- Top-level list of task objects
- Each task typically includes:
  - a human title/description
  - an `id` or name
  - a boolean completion field such as `completed: false|true`

### Status-field PRD JSON (open / in_progress / done)

Another prd.json variant uses explicit lifecycle states rather than a `passes` boolean:

- story state fields: `open`, `in_progress` (often with `startedAt`), `done` (often with `completedAt`)

## [HIGH] different formats for the core prompt/instructions fed each iteration

This section extracts the **prompt packaging formats** that repeatedly show up as the “core instruction payload” for each loop iteration.

### Single-file prompt template

A single markdown prompt file acts as the loop’s “constitution,” typically embedding:
- required read order (PRD first, then progress/memory)
- “one task per iteration”
- verification steps (tests/typecheck/browser)
- commit discipline
- task tracker update rule
- completion signal string

### Prompt as a file graph (explicit includes)

Some prompts are written as a *hub* that points to other state files via explicit references:
- e.g., `@prd.md @activity.md` at the top, then instructions describing how to use those files each run, including browser automation commands.

### Prompt with machine-parseable end-of-iteration status block

Some loops require a structured footer that the harness parses deterministically:
- fixed fields like `STATUS`, `TASKS_COMPLETED_THIS_LOOP`, `FILES_MODIFIED`, `TESTS_STATUS`, `WORK_TYPE`, `EXIT_SIGNAL`, etc.

### Prompt + guardrails + error memory triad

A notable format adds “don’t repeat this mistake” memory files and makes them first-class:
- a guardrails file (append-only “signs” / lessons)
- a progress file with “patterns”
- an errors log showing recent failures (tail)

### Prompt + live steering file

Some harnesses instruct the agent to read a “steering” file and treat it as higher priority than the normal tracker:
- steer file checked every iteration; if non-empty/critical, the agent resolves it before returning to the queue.

### Phase prompt decks

Phase-based Ralph variants use:
- a template `CLAUDE.md` describing the loop contract + what to read
- `prompts/phase-N.md` files as minimal per-phase iteration prompts
- an external phase tracker (often YAML) that gets updated on transitions

### Plugin-driven stop-hook state file

The official ralph-wiggum plugin pattern stores loop state and the re-injected prompt in a local markdown file with YAML frontmatter:
- fields like iteration/max-iterations + a completion promise
- the stop hook blocks exit and feeds the original prompt back into the session when incomplete

## [RAW] different ways to sandbox claude code's execution with --dangerously-skip-permissions

Below are **raw, unmodified** command/config fragments (kept short) that illustrate common “run YOLO-mode, but isolate it” approaches.

**Baseline: enable YOLO mode (CLI flag)**
```bash
claude --dangerously-skip-permissions
```

**Print-mode + file-driven prompt (common in loop runners / wrappers)**
```bash
AGENT_CMD="claude -p --dangerously-skip-permissions \"\$(cat {prompt})\""
```

**Devcontainer isolation (sandbox-by-container; recommended only for trusted repos)** — devcontainers are explicitly positioned as a way to run unattended with the flag, but still warn that exfiltration of anything inside the container remains possible.
```bash
claude --dangerously-skip-permissions
```

**Docker + git-worktree sandbox tool (one-shot sessions)** — VIWO describes a workflow that creates a worktree, runs Claude Code in a Docker container volume-mounted to that worktree, and runs print mode with `--dangerously-skip-permissions`.
```bash
viwo start
```

**Worktree isolation + YOLO mode (parallel instances without file conflicts)** — a common pattern is: create a worktree, then run Claude with the flag inside that worktree directory.
```bash
claude --dangerously-skip-permissions /todo
```

**Looping outside Claude to manage scale (still YOLO, but automation-level sandboxing)** — moving the repetition into bash can control concurrency/cost while keeping each command in “print mode.”
```bash
for i in $(seq 1 10); do claude --dangerously-skip-permissions --print /worktree; done
```
