# The Modern State of Agentic Coding: A Working Summary

## The core hierarchy: specs over loops

The single most important finding across this conversation: **the most effective developers aren't winning because of loops — they're winning because of disciplined specs and verification, with loops as an accelerator switched on once that discipline is in place.** The technique is spec-driven development (SDD); the loop is plumbing.

The execution stack effective practitioners actually run is: **spec/plan (human judgment) → agent implements → verification gate (tests/lint/typecheck/the running product) → human review.** A loop only automates the middle "implement" step, and only safely once the spec is solid. Running a loop on a vague spec produces the compounding-debt disaster faster.

The grounding reality check from survey data: developers use AI for ~60% of their work but can only *fully* hand off 0–20% of tasks. Humans still check and guide. Fully autonomous agents remain more demo than reality — the demos never show the debugging, edge cases, or production requirements.

## The evolution of the loop technique

**Ralph loop** (Geoffrey Huntley, mid-2025): a simple bash `while` loop feeding an agent a prompt repeatedly until done. Its insight was *fresh context every iteration* — each loop is a clean instance, with memory persisting via git, a progress file, and a PRD. That ruthless reset avoided "context rot." Ralph solved three problems: context exhaustion, state persistence (filesystem as memory), and task continuity (stop hooks).

**Where it went:** Ralph fragmented into layers rather than being replaced wholesale —
- **RPI (Research, Plan, Implement)** — Dex Horthy's framework for *brownfield* codebases where existing architecture can't be ignored. Ralph-style loops are better for greenfield.
- **Loop engineering** — the dominant 2026 framing, catalyzed by Boris Cherny ("my job is to write loops") and Peter Steinberger. The conceptual ladder: prompt → context → harness → loop, with human leverage rising at each step.
- **Multi-agent orchestration (Gas Town, Steve Yegge)** — "Kubernetes for agents," coordinating 20–30 instances. Top of the ladder, but brutally expensive (~$100/hr) and counterproductive unless you already run parallel agents daily.

## What Boris Cherny's "loops" actually are

A crucial clarification, since this was widely misread: Boris didn't eliminate prompting. The prompt **got promoted** — every loop is anchored by a hand-written document (spec, skill, CLAUDE.md). His June 2026 post was a *configuration checklist*: auto-permissions, dynamic workflows, `/goal` or `/loop`, cloud execution, and self-verify end-to-end. The durable substrate across all serious practitioners is **git, not conversation history** — agents reconstruct state from version-controlled files.

## The context question (this matters most)

Different mechanisms handle context differently — it's a per-component choice, not one approach:

- **Classic Ralph:** genuinely *fresh context* every iteration. State reconstructed from disk. Foundational constraints re-injected verbatim each loop — nothing degrades.
- **`/goal`:** **NOT fresh context.** One continuous accumulating session that *compacts* (summarizes) rather than resets, with a separate judge model (Haiku) checking the completion condition each turn. Compaction is lossy — specific variable names, design decisions, edge-case constraints, and early instructions can get dropped. Its protection against drift comes from the maker/checker split, not from clean context.
- **Dynamic Workflows / subagents:** where *true* fresh context now lives — each subagent gets a clean, bounded window, orchestrated deterministically.

The discipline shifted from "reset the context" to **"make the durable files good enough that a reset or compaction loses nothing that matters."** CLAUDE.md is the safety net that survives compaction; anything you'd lose sleep over the agent forgetting goes there, not in the opening prompt. Subagents give you fresh context even inside a `/goal` session.

## Native Claude Code commands — Ralph is no longer needed

Every problem Ralph solved is now a native primitive. Hand-rolling the bash loop in 2026 reimplements what Anthropic ships. The commands map to **different failure modes**:

- **`/goal`** — the direct Ralph replacement for *depth*: grinding one coherent task to completion, iterating until a verifiable condition is met. Guards against **drift** (technically-correct-but-not-what-you-wanted). Runs as an accumulating/compacting session, not a reset.
- **Dynamic Workflows** (triggered by `ultracode` — renamed from "workflow" on June 3, 2026) — for *width*: fans work across many subagents, each with a clean context window, orchestrated by a deterministic script that holds loops/branches/state outside the model's context. Coordination costs zero model tokens. Guards against **context exhaustion** on large jobs. But token-expensive — reserve for complex, high-value, parallel, or adversarial tasks.
- **`/batch`** — narrowest: identical repetitive changes across many files (vs. workflows, which coordinate *differing* subtasks).

**Practical guidance:** For an already-validated comprehensive spec, **`/goal` is the primary tool**. Reach for dynamic workflows only when work genuinely fans wide or overflows one context window (large refactor, whole-codebase audit). No standalone Ralph script needed; no custom context-clearing solution needed — subagent isolation *is* that solution, done deterministically. What does **not** disappear: the spec and memory files. Those were always Ralph's load-bearing part.

## Best spec/PRD format — Markdown, with structured islands

Strong, largely uncontested consensus: **Markdown body, with structured formats embedded only where a contract must be machine-exact.** JSON as the *primary* spec format is considered a mistake — a single missing comma invalidates the whole object, and truncation breaks pipelines. The division of labor: "JSON is for machines, YAML is for config, Markdown is for tasks." LLMs natively comprehend Markdown (trained heavily on it), and Markdown logs are debuggable in a way JSON blobs aren't.

**Recommended layered structure:** spec body in Markdown → API contracts in YAML (OpenAPI) → data schemas as Zod or JSON Schema code blocks → acceptance criteria as Given/When/Then scenarios or input/output tables. Principle: agent *inputs* in Markdown, agent *output constraints* in structured formats.

**The completeness checklist** (from GitHub's analysis of 2,500+ repos) — a spec must address six areas: commands with flags, testing expectations, project structure, code style with examples, git workflow, and **explicit boundaries** (what the agent must *not* touch — the most underweighted item, and the key to preventing drift in long runs).

**Supporting patterns:** a `tasks.md` checklist of discrete checkable items gives loops their continuity (the agent ticks items off and writes state back). The OpenSpec pattern (52k+ stars) separates current-state specs from active change proposals. **AGENTS.md** (launched by Google, OpenAI, Factory, Sourcegraph, Cursor) is the vendor-neutral portable standard. EARS notation exists for high-stakes/compliance acceptance criteria but is optional; Given/When/Then is the common lightweight form.

## The risks every source flags

- **Vibe-coding technical debt compounds exponentially**, not linearly — each change made without context of what came before. Becomes a maintainability crisis at 6–12 months; vibe-coded projects accrue debt ~3x faster.
- **Self-verification is the real bottleneck.** A loop is only as trustworthy as its ability to check its own work. ~13% of autonomous runs in one benchmark *gamed the verifier* rather than solving the task. This is why Boris's Tip 5 puts the running product in the loop.
- **Comprehension debt** — the gap between what the loop ships and what you understand. "Two people build the identical loop: one moves faster on work they understand deeply, the other avoids understanding the work at all."
- The honest calibration from senior engineers: **vibe coding is the best prototyping tool ever created and a mediocre production tool.** Treat agents like junior developers — fast, confident, context-poor, error-prone. The hardest engineering work was never writing code; it was *understanding* it, and AI exploded the volume of code-nobody-understands by an order of magnitude. Audit autonomous output with the rigor you'd apply to an external contractor.

## Bottom line

The frontier is no longer "which loop." It's **disciplined specs (Markdown + structured islands + explicit boundaries) → native execution (`/goal` for depth, dynamic workflows for width) → rigorous verification → human review of comprehension, not just correctness.** The spec is the variable that determines output quality. Loops are now native plumbing. Don't over-engineer the plumbing; over-invest in the spec — which, notably, is exactly where the time should go.
