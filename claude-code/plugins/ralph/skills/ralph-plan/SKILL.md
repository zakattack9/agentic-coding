---
name: ralph-plan
description: Interactively generate a PRD and task list for a Ralph Loop — invoke to plan a feature before running ralph.sh
allowed-tools: Bash(*), Read, Write, Glob, Grep, Task, AskUserQuestion
---

# Ralph Plan — Interactive PRD & Task List Generator

You are helping the user plan a feature for execution by the Ralph Loop. Your goal is to produce two artifacts:

1. **`.ralph/prd.md`** — A concise requirements specification that serves as the **base context** read at the start of every ralph iteration. Written and structured for optimal Claude comprehension in fresh context windows.
2. **`.ralph/tasks.json`** — A task list with stories sized for the Ralph Loop's fresh-context execution model. Each story is a self-contained implementation instruction that Claude can act on with only the PRD as additional context.

These two files have **complementary roles** — the PRD provides stable context (what, why, who, constraints, technical design), while tasks.json provides execution state (individual stories, acceptance criteria, progress). They must not duplicate each other. Both should be formatted for **Claude's consumption** — structured, explicit, and unambiguous. The primary reader is Claude in a fresh context window, not a human skimming a document.

---

## Prerequisite Check

!`bash -c 'test -d .ralph && echo "RALPH_DIR: installed" || echo "RALPH_DIR: MISSING"'`
!`bash -c 'test -f .ralph/templates/prd-template.md && echo "TEMPLATES: installed" || echo "TEMPLATES: MISSING"'`
!`bash -c 'test -f .ralph/prd.md && echo "PRD: exists" || echo "PRD: MISSING"'`
!`bash -c 'test -f .ralph/tasks.json && echo "TASKS: exists" || echo "TASKS: MISSING"'`

Evaluate the status outputs above:

- If **RALPH_DIR is MISSING**: Tell the user to run `/ralph-install` first, then `/ralph-init --name my-feature`, then `/ralph-plan` again. **Stop here.**
- If **TEMPLATES is MISSING**: Tell the user to run `/ralph-install` to restore templates. **Stop here.**
- If **PRD is MISSING** or **TASKS is MISSING**: Tell the user to run `/ralph-init --name my-feature` to initialize state files, then `/ralph-plan` again. **Stop here.**
- If all checks pass: proceed to Phase 1.

---

## Phase 1: Research & Discovery

Before asking the user ANY questions, perform targeted research to build your own understanding of the project and the proposed feature. Research findings persist in `.ralph/planning/` so they can be referenced throughout planning and by future subagents.

### Setup

Create the planning directory if it doesn't exist:

!`bash -c 'mkdir -p .ralph/planning'`

### Assess what research is needed

Based on the user's initial description of the feature, determine which research subagents to launch. **Not every task needs all types** — use judgment. In rare cases where the feature is simple and well-described, you may skip research entirely.

| Research type | When to use | Subagent |
|---|---|---|
| **Codebase exploration** | When you need to understand existing code structure, patterns, tech stack, or find relevant files | Launch `Task` with `subagent_type: "ralph-explore"`. Pass the feature description and specific questions about the codebase. Writes detailed findings to `.ralph/planning/ralph-explore.md`. |
| **Documentation lookup** | When the feature involves specific libraries, frameworks, or tools where API details or configuration matter | Launch `Task` with `subagent_type: "ralph-docs"`. Specify which libraries to research and what questions to answer. Writes findings to `.ralph/planning/ralph-docs.md`. |
| **Web search** | When the feature involves external services, third-party APIs, or technology decisions where current information matters | Launch `Task` with `subagent_type: "ralph-web"`. Specify the research questions. Writes findings to `.ralph/planning/ralph-web.md`. |

**Launch research subagents in parallel** whenever multiple types are needed. Each subagent writes detailed findings to `.ralph/planning/` and returns a concise summary to you.

### Subagent handoff contract

When spawning research subagents, your `Task` prompt must include:
1. **Feature description** — what is being built (from the user's initial request)
2. **Specific questions** — what you need the subagent to answer (targeted, not open-ended)
3. **Scope boundaries** — what's NOT relevant (prevents subagents from going too broad)

Each subagent will:
- Write comprehensive findings to `.ralph/planning/{agent-name}.md`
- Return a concise summary (10-20 bullet points) of key findings to you

### After research completes

Synthesize the returned summaries. If any summary lacks critical detail, read the full findings file from `.ralph/planning/` directly. Reference specific discoveries when asking the user questions in Phase 2 (e.g., "I see the project uses Next.js with the app router — should this feature follow the same pattern as the existing `/dashboard` routes?").

---

## Phase 2: Determine Mode & Plan

!`bash -c 'cat .ralph/prd.md 2>/dev/null || echo "NO_PRD_CONTENT"'`

Read the prd.md content above to determine which mode to use:

### Mode 1: Full Planning (prd.md is empty or template scaffold)

If prd.md contains only the template scaffold (section headers with HTML comments, no real content), use full planning mode:

1. **Gather requirements via AskUserQuestion** — Use your research findings to ask informed, specific questions. Your questions should demonstrate understanding of the codebase and narrow in on decisions the user needs to make — NOT ask about things you already discovered through research. Focus on:
   - What problem are we solving? Who is the user?
   - What is the core functionality? (reference existing patterns you found)
   - What are the explicit scope boundaries (non-goals)?
   - What constraints must be respected? (mention any you discovered)
   - What does success look like? What verification is appropriate?
   - Ask follow-up rounds until every ambiguity is resolved. There is no question limit. Do NOT proceed until you are confident the specification is complete enough that another developer could implement it without further questions.

2. **Generate `.ralph/prd.md`** — Write the PRD following the guidelines in the "PRD Guidelines" section below. Fill in all relevant sections. Delete sections that don't apply rather than leaving them empty.

3. **Architect task breakdown** — Launch the `ralph-plan-tasks` subagent via `Task` with `subagent_type: "ralph-plan-tasks"`. In your prompt, include:
   - The PRD content you just generated (or instruct it to read `.ralph/prd.md`)
   - Paths to research findings in `.ralph/planning/` (so it can read them)
   - Any user requirements or constraints from the Q&A that aren't in the PRD

   The subagent writes a detailed task architecture to `.ralph/planning/ralph-plan-tasks.md` and returns a summary. Read the full `.ralph/planning/ralph-plan-tasks.md` file to review the proposed breakdown.

4. **Derive `.ralph/tasks.json`** — Using the task architecture from `ralph-plan-tasks`, generate the final tasks.json. Apply all field requirements (initial state, story IDs, structure) from the "Task Derivation Rules" section below. You may adjust the subagent's recommendations — it provides the architecture, you produce the final artifact.

5. **Present both files for review** — Use `AskUserQuestion` to present your draft of prd.md and tasks.json and ask the user to approve, request changes, or add missing requirements. Iterate until the user confirms both artifacts are ready.

### Mode 2: Task Derivation (prd.md already has content)

If prd.md already contains real requirements content:

1. **Read existing `.ralph/prd.md`** thoroughly (already loaded above)
2. **Clarify gaps via AskUserQuestion** — If requirements are ambiguous, incomplete, or could be interpreted multiple ways, use research findings to ask targeted questions. Do not guess.
3. **Architect task breakdown** — Launch `ralph-plan-tasks` subagent (same as Mode 1 step 3). Pass the existing PRD content, research findings paths, and any clarifications from the user. Read the full `.ralph/planning/ralph-plan-tasks.md` output.
4. **Derive `.ralph/tasks.json`** — Convert the task architecture output into final tasks.json, applying all field requirements from the "Task Derivation Rules" section below.
5. **Present tasks for review** — Use `AskUserQuestion` to present the task list and ask the user to approve or request changes. Iterate until confirmed.

---

## PRD Guidelines: Base Context for Every Iteration

The PRD is read at the start of **every ralph iteration** in a fresh context window. It serves as the stable "base context" that orients each session. Every word in the PRD costs context budget across every iteration.

### Token budget

**Target: 2,000-3,000 words maximum** (~2,500-4,000 tokens).

Rationale — measured per-iteration overhead for the ralph loop artifacts:

| Artifact | Size | Tokens (approx) | Notes |
|---|---|---|---|
| Claude Code system prompt + tools | — | ~5,000-15,000 | Fixed overhead, not controllable |
| prompt.md (iteration template) | ~1,400 words / ~10K chars | ~2,000-2,500 | Fixed per iteration |
| **prd.md** | **2,000-3,000 words** | **~2,500-4,000** | **Your target — read every iteration** |
| tasks.json (5 stories, populated) | ~5-6K chars | ~1,500-2,000 | Grows with stories |
| progress.txt (mid-loop, ~5 iterations) | ~1,000-1,200 words | ~1,000-1,500 | Grows each iteration |
| Orientation (git log, git status, .ralph-active) | — | ~250-500 | Fixed per iteration |
| **Total fixed overhead** | | **~12,000-25,000** | Before any implementation work |

Claude's context window is ~200K tokens (~185-195K usable after system prompt). The **"smart zone"** — where reasoning quality is highest — is **30-60% utilization** (~60K-120K total tokens used). Beyond 60%, reasoning quality degrades progressively ("context rot"). This means:

- After ~20K tokens of overhead, the smart zone gives **~40-100K tokens for actual implementation work**
- A lean PRD at ~3K tokens vs a bloated PRD at ~8K tokens saves 5K tokens **every iteration** — that's the equivalent of reading 2-3 extra source files in the smart zone

**Formatting rules for PRD:**
- Use bullet points, tables, and structured sections — Claude parses these more efficiently than prose paragraphs
- Frontload key information within each section — the most important details go first
- Use concrete references (file paths, function names, table names) over abstract descriptions
- Every sentence should earn its place — if it doesn't help Claude understand what to build and what constraints to follow, cut it

### What belongs in the PRD vs tasks.json

The PRD provides **umbrella context**. tasks.json provides **per-story execution state**. They are complementary, not overlapping.

| Belongs in PRD | Belongs in tasks.json |
|---|---|
| High-level summary (what, why, who) | Individual story titles and descriptions |
| Problem statement and goals | Per-story acceptance criteria |
| Architecture overview and technical design | Story dependencies and ordering |
| Cross-cutting constraints (rules that apply to ALL stories) | Story-specific implementation notes |
| Key file paths and existing patterns to follow | Verification status (passes, reviewStatus) |
| Non-goals and scope boundaries | Story-specific edge cases |
| Global edge cases and error handling strategy | Per-story notes and review feedback |

**The PRD should never re-state what's in individual story descriptions.** Instead, it provides the context that makes each story's description and acceptance criteria self-sufficient. A fresh Claude session reads the PRD to understand the "world," then reads a specific story to know what to implement in that iteration.

### PRD section guidance

Follow the template structure in `.ralph/templates/prd-template.md`. Key principles:

- **Summary** — 2-4 sentences. Must orient a fresh Claude context window immediately. Write this as a briefing, not an abstract.
- **Non-Goals** — The most critical section for constraining Claude's behavior. Be explicit and specific about what is out of scope (e.g., "Do NOT add pagination to the list view" rather than "Keep it simple"). This prevents over-engineering across every iteration.
- **Background & Context** — Include key file paths, architecture patterns, naming conventions, and relevant existing code. This section prevents Claude from "rediscovering" the codebase structure each iteration. Use a file/directory listing format where possible.
- **Technical Design** — Only include subsections relevant to this feature. Delete the rest. Write in a format Claude can act on: pseudocode, explicit API signatures, schema definitions — not narrative descriptions.
- **Constraints** — Cross-cutting rules Claude must follow in ALL stories. Write these as imperative instructions: "Use date-fns for all date formatting" not "We prefer date-fns".
- **Delete unused sections** — Empty sections waste context budget. Remove any section that doesn't apply.

---

## Task Derivation Rules

Apply these rules when creating the task list in both modes.

### Smart Window Sizing

Each Ralph Loop iteration runs in a **fresh context window**. Claude's context window is ~200K tokens (~185-195K usable after system prompt and tool definitions). The **"smart zone"** — where Claude reasons best — is **30-60% utilization** (~60K-120K total tokens). Beyond ~60%, reasoning quality degrades progressively. A story must be completable well within this zone.

**How to think about story size in tokens:**

A typical source file (100-500 lines) consumes ~1,500-5,000 tokens when read. Each tool call round-trip (read, edit, bash) adds ~500-2,000 tokens. Verification commands add ~500-1,500 tokens each. So a story's implementation work breaks down as:

| Activity | Token cost | Notes |
|---|---|---|
| Reading source files to understand context | ~1,500-5,000 per file | 200-line file ≈ ~2,500 tokens |
| Code edits (read + write per file) | ~1,000-3,000 per modified file | Includes tool call overhead |
| Running verification commands | ~500-1,500 per command | Test output varies |
| Self-review (git diff + analysis) | ~2,000-5,000 | Depends on change size |
| Commit + tasks.json/progress.txt updates | ~1,000-2,000 | Fixed overhead |

With ~40-100K tokens of smart-zone budget for implementation (after the ~20K overhead from ralph artifacts), a story can afford:

- Reading ~8-15 source files for understanding (~15-40K tokens)
- Modifying ~3-8 files with edits (~5-20K tokens)
- Running 2-5 verification commands (~2-5K tokens)
- Self-review and commit (~3-7K tokens)

**Concrete sizing heuristics:**
- A story should require reading **no more than ~15 source files** and modifying **no more than ~8 files**
- If you can't describe the implementation approach in 2-3 sentences, the story is too big — split it
- If a story touches more than 2 system boundaries (e.g., database + API + frontend), split along the boundary
- Prefer more small stories over fewer large ones — each gets a fresh context window, which is the loop's key advantage
- When in doubt, split smaller — the cost of an extra iteration (fresh context + orientation) is much lower than the cost of degraded reasoning in an overloaded context

**When to split stories:**
- Story requires understanding a large existing module AND building something new → split into "scaffold/setup" and "implement core logic"
- Story has both data model changes and UI changes → split along the boundary
- Story has more than 3-4 acceptance criteria testing different behaviors → each behavior could be its own story
- Story requires integrating with multiple external services → one story per integration
- Story involves reading more than ~15 files or modifying more than ~8 files → too large for the smart zone

### Story Ordering
- Order by dependency: schema/database → backend logic → API routes → frontend components → integration/summary views
- Set `dependsOn` explicitly when story order matters beyond priority number
- Lower priority numbers execute first

### Acceptance Criteria
- Write criteria as **assertions Claude can objectively verify** — either by reading code, running a command, or checking output
- Be specific: `GET /api/users returns JSON array with id, name, email fields` not "API works correctly"
- Include both positive cases and relevant error/edge cases
- Criteria should be verifiable within the story's context — don't write criteria that require reading the entire codebase
- Each criterion should map to something Claude can check: a file exists, a test passes, a function returns expected output, an error is handled

### Story Descriptions
- Write descriptions as **implementation instructions for Claude**, not as user stories for a human product team. "Create a new file `src/routes/users.ts` exporting a GET handler that queries the `users` table and returns JSON matching the schema in the PRD §6b" is better than "As a user, I want to see a list of users"
- Each description should be **self-contained when combined with the PRD context** — a fresh Claude session reading the PRD + this one story should know exactly what to implement
- Reference specific file paths, function names, or components when possible
- Include the "how" at a high level (e.g., "Add a new API route at `/api/v1/users` following the pattern in `routes/products.ts`") — don't just say "add user endpoint"
- Do NOT duplicate PRD content — reference it (e.g., "following the constraints in the PRD" rather than restating them)

### Verify Commands
- Populate `verifyCommands` from the project's existing test/lint/typecheck commands
- If you discovered these during research, include them directly
- Use `AskUserQuestion` if you're unsure which commands to include

### Initial State
All stories must start with:
```json
{
  "passes": false,
  "reviewStatus": null,
  "reviewCount": 0,
  "reviewFeedback": ""
}
```

### tasks.json Structure
```json
{
  "project": "<project name>",
  "description": "<brief description of the overall feature>",
  "verifyCommands": ["<test command>", "<lint command>"],
  "userStories": [
    {
      "id": "US-001",
      "title": "<short imperative title — e.g., 'Create users API route'>",
      "description": "<implementation instruction for Claude — what to build, which files to create/modify, which patterns to follow, referencing PRD sections for context>",
      "acceptanceCriteria": ["<assertion Claude can objectively verify>"],
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

---

## Important Notes

- **Do not write files until the user approves** — Always use `AskUserQuestion` to get explicit confirmation before writing prd.md and tasks.json
- **Research first, ask second** — Use subagents to discover what you can before asking the user. Your questions should demonstrate that you've done your homework.
- **Subagent findings persist** — All research and planning subagents write detailed findings to `.ralph/planning/`. Read these files when you need more detail than the returned summaries provide. The planning folder is archived with the loop and cleaned on init.
- **Use AskUserQuestion liberally** — It is better to ask one too many questions than to produce an incomplete spec. The ralph loop cannot ask for clarification mid-execution, so the plan must be airtight before it starts.
- **Respect the PRD token budget** — The PRD is read every iteration. Verbose PRDs steal context from implementation work. Target 2,000-3,000 words. Use structured formats.
- **Write for Claude, not humans** — Both prd.md and tasks.json are primarily consumed by Claude in fresh context windows. Use structured formats (bullet points, tables, explicit file paths, imperative instructions) that Claude parses efficiently. Avoid narrative prose, vague language, and implicit expectations.
- **tasks.json must be valid JSON** — Ensure all required fields are present and correctly typed
- **Story IDs** use the format `US-001`, `US-002`, etc.
- **No branch creation needed** — Assume the current branch is correct. Do not include `branchName` or instruct the user to create a new branch.
- **Delete empty PRD sections** — When writing prd.md, remove any template section that doesn't apply. Empty sections waste tokens every iteration.
