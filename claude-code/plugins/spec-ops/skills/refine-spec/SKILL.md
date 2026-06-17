---
name: refine-spec
description: Review, verify, and tighten an existing feature spec until it is accurate, hallucination-free, not over-engineered, and ready to implement. Use immediately after write-spec, or whenever the user asks to review, fact-check, refine, simplify, de-risk, or finalize a spec / PRD / requirements doc before building. Runs a grounded multi-pass loop that verifies every claim against the codebase, asks the user to resolve open questions, cuts bloat and speculative scope, and stops only when the spec passes an implementation-readiness gate.
argument-hint: [@path/to/spec.md] [focus areas]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Edit, Write, Bash, Task
hooks:
  Stop:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/skills/refine-spec/stop_refine_spec.py"
---

# Refine Spec

Companion to `write-spec`. `write-spec` produces the foundational spec; this skill drives that spec — over **as many passes as it takes** — to a state that is **accurate, grounded, lean, and implementation-ready**, so the user can go straight from here into building. Loop until the readiness gate passes. Do not stop after one pass, and do not start implementing.

Arguments: $ARGUMENTS

## Inputs

- **Spec file** — the path or `@`-mention in the arguments above. If none is given, ask which file with `AskUserQuestion`.
- **Focus areas** — anything else in the arguments the user wants emphasized (e.g. "check the data model", "it feels over-engineered").

Read the spec in full before doing anything. Also read every doc, file, or sibling spec it links or refers to, so you review it in context.

## The loop

Run the five-step pass below repeatedly. Keep looping until a pass produces **no corrections, no open questions, and the readiness gate passes**. Then stop. Announce each pass (e.g. "Pass 2") so the user can follow the convergence.

```
Verify → Reconcile → Resolve → Refine → Re-check ↺
```

### Loop ledger — this loop is enforced, not optional

A **`Stop` hook blocks you from ending your turn** until the spec is genuinely ready, so you cannot quit a pass early. It reads a ledger you maintain at:

`/tmp/claude-refine-spec-${CLAUDE_SESSION_ID}.json`

**At the start of the run, and at the start of every pass,** write the ledger with the `Write` tool (overwrite it each time — that also keeps it fresh so the loop doesn't expire mid-run). **Write strict, valid JSON exactly matching the schema below** — `gate` flags and `resolved` must be JSON booleans (`true`/`false`, not strings), and `spec` must be the correct absolute path. The hook validates the ledger and will block you with a correction message if it is malformed, so a typo can't silently disable the gate:

```json
{
  "spec": "<absolute path to the spec file>",
  "gate": {
    "claims_verified": false,
    "no_open_questions": false,
    "no_overengineering": false,
    "no_bloat": false,
    "implementable_cold": false,
    "ac_complete": false
  },
  "openQuestions": [
    { "q": "short text of an open question you found", "resolved": false }
  ]
}
```

- Add **every** open question you find to `openQuestions`; set its `resolved` to `true` only once the user has given it a disposition — a concrete answer **or** an explicit "leave it / defer".
- Set each `gate` flag to `true` only when that dimension genuinely holds. The five flags map 1:1 to the **Readiness gate** below.
- The hook also scans the spec for leftover `TODO` / `TBD` / `FIXME` / `???` / "to be decided" / "open question" / `[NEEDS CLARIFICATION: …]` — those block the stop too, so don't leave them in the spec.

When every flag is `true`, every question is `resolved`, and the spec is clean, the hook removes the ledger and lets you stop. **If the user redirects to unrelated work, delete the ledger file and stop** instead of continuing to refine.

### 1. Verify — ground every claim against reality

List every **checkable claim** in the spec: file paths, function / class / method names, table / column names, routes, config or env keys, library or framework behavior, "the system currently does X" statements, data shapes, and counts.

Dispatch **parallel `Explore` subagents** (the `Task` tool, `subagent_type: Explore`) to check these claims against **ground truth, never against other docs** — they are read-only and fast. Ground truth, in order of authority: the **actual codebase at branch HEAD**; the **latest git commits** (`git log` / `git diff` on the working branch — specs drift after out-of-band commits and dev→infra merges, so re-ground against HEAD rather than trusting the spec's own history); and, for infra/ops specs, **live state via the named CLI** (e.g. `aws`, `gh`). Treat sibling or "completed" specs as **possibly stale — never as ground truth**. Split the claims by area (e.g. one agent per subsystem, model layer, or route group) and scale the agent count to the spec: a short spec may need a single verifier; a large one, several. Give each agent the relevant spec excerpt plus its claim list, and require a structured verdict per claim:

> For each claim return one of: `confirmed` / `wrong` (give the correct value and where you found it — `file:line`, a commit SHA, or CLI output) / `not found`. Quote the supporting evidence. Do not speculate — if you cannot verify it, say so.

Run one more agent (or do it yourself) as a **skeptic lens**: read the whole spec hunting for internal contradictions, over-engineering, speculative scope, anything an implementer could not actually act on, and **unstated non-functional constraints the change implies but never pins as an `AC` — performance, security, idempotency, limits, concurrency** (the requirements most often dropped).

### 2. Reconcile — sort what came back

Dedupe the findings and bucket each one:

| Bucket               | What it is                                                                                                                                                                                                                                                            | Action                    |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| **Inaccuracy**       | Contradicts the codebase                                                                                                                                                                                                                                              | Fix to the verified value |
| **Open question**    | Cannot be verified; needs a human decision                                                                                                                                                                                                                            | Queue for **Resolve**     |
| **Over-engineering** | Speculative, gold-plated, or beyond the stated goal                                                                                                                                                                                                                   | Propose cutting           |
| **Bloat**            | Text not needed to *build* it: historical/background prose, rationale or "why / previously / originally", problem statements, changelog, speculative out-of-scope narrative, restated field names, duplication. **Decision, config, and field tables — and the Acceptance Criteria list — are pertinent; keep them.** | Cut                       |

### 3. Resolve — ask the user

For **every** genuine ambiguity, unverifiable assumption, or open decision that changes *what gets built*, ask the user with `AskUserQuestion`. Batch related questions into one call; ask as many as you need across passes. **It is better to ask one too many questions than to let the spec ship an assumption.** Never guess to fill a gap.

You do **not** need to ask about facts you already verified and corrected against the codebase — fix those directly and note them in the final summary.

### 4. Refine — edit the spec

Apply, as one coherent edit per pass:

- **Corrections** — replace every inaccuracy with the verified value.
- **Resolutions** — fold in the user's answers.
- **Cuts** — remove over-engineering and bloat.
- **Simplification** — tighten so another dev can grasp the objective and the details fast, following the `write-spec` philosophy: say things once, in the right place; describe behavior, not implementation; show with tables / mermaid / examples instead of prose; bold the key terms; every sentence must earn its place.
- **Acceptance criteria** — ensure the spec opens with a flat, stable-id'd **Acceptance Criteria** list that captures *every* functional requirement and constraint as a discrete, atomic, testable assertion. Promote anything that exists only in prose into a criterion, split compound ones, and confirm each is an observable end-state (not a task). Cross-check coverage both ways: every criterion is addressed by the Checklist/plan, and every behavioral rule in the body maps back to an `AC-id`. This list is load-bearing — never cut it as bloat.
- **Acceptance-criteria ordering & grouping** — decide whether the AC list stays flat or becomes **ordered named groups**, and commit that decision *here* (it is grounded work the first-draft author can't do). Group only when it earns its keep: the ACs fall into **≥2 recognizable capability clusters**, *or* a **binding cross-group dependency** exists. Then name each group (`### 1. <capability> — start here`, `### 2. <capability> — needs §1`) and add a `needs §X` header edge **only for a real dependency you have grounded against the codebase** — never a guessed or scheduling order. `needs §X` is the only *binding* order; group sequence is otherwise a suggested reading order. Prefer **≥2 ACs per group** (a solo-AC group is allowed only for a genuine "start here" capability, e.g. a walking-skeleton AC). **No dates, time-boxes, or effort estimates** — order is dependency-derived only. If grouping would exceed **~5–6 groups**, surface that the spec may be too big rather than hard-blocking. AC-ids stay globally unique and stable; a one-group spec is just the flat list.
- **Unstated-constraint hunt & completeness probe** — actively look for **non-functional constraints the spec depends on but never states**: performance, security, idempotency, limits, concurrency. Promote each real one into its own `AC-id` — these are the most-dropped requirements, and a capable implementer will silently skip what isn't written. For every *behavioral* AC, run the **completeness probe** — *what initiates this, under what precondition, and what's the observable bound?* — and close any gap it exposes. This is a **prompt for finding holes, not a syntax to impose**: keep each AC a plain testable sentence (no EARS/Gherkin templates, no type tags), and **exempt** pure-math / decision-table criteria and the Boundaries section, which have no stimulus-response shape. Convey meaning over template.
- **Boundaries** — ensure the spec states explicit **Boundaries** (what the implementer must NOT touch) whenever the change has out-of-bounds areas; they are the top anti-drift lever for the implementation run. Add them, or ask, if missing. Keep them change-specific: if a boundary is really a standing project convention (architecture, "don't touch prod") rather than specific to this change, recommend it live in **CLAUDE.md** instead — re-injected every turn, durable across any driver.

**Preserve every detail an implementer needs.** Simplify *wording and structure*, never silently drop substance. If you are unsure whether a detail is load-bearing, ask before cutting it. Keep edits reviewable as a clean git diff.

**Prove no silent loss on a rewrite.** If the spec is already tracked in git and this pass rewrote or heavily condensed it, diff the result against the prior committed version (`git diff`, or `git show HEAD:<path>`) and surface a short **`removed:`** list of any non-bloat content you cut, so the user can veto a wrongful drop. Skip this for a brand-new, untracked spec.

### 5. Re-check — did the edit settle or stir?

Re-read the edited spec. Edits can introduce new claims, new ambiguities, or new contradictions. If the pass changed anything, **loop** and verify again. If a full pass produced no fixes and no questions, evaluate the readiness gate with the independent judge (below) — don't sign off on your own work. Before you try to stop, make the ledger reflect reality — unresolved questions marked, gate flags set only where they truly hold. The `Stop` hook bounces you back here if anything is still open.

## Readiness gate

Finish only when **all** of these hold. Report the gate's status at the end of each pass. Each maps to a ledger flag (in parentheses).

**The agent that did the refining does not get to declare it done.** Before setting any gate flag to `true`, dispatch a fresh **readiness judge** — an independent subagent (`Task`) with no memory of your edits — and hand it the current spec plus the criteria below. Instruct it to be adversarial: *read the spec and the codebase and hunt for any remaining inaccuracy, ambiguity, over-engineering, bloat, missing detail that would block implementation, any functional requirement or **unstated non-functional constraint** (performance, security, idempotency, limits, concurrency) not captured in the Acceptance Criteria list as a discrete, testable assertion; classify each finding as `[Gap]` (something required is missing), `[Ambiguity]` (more than one reasonable reading), or `[Conflict]` (two parts disagree), name the exact `AC-id` for every coverage finding ("AC-7 is not captured", never "some criteria missing" — precision drives recovery of dropped items), and return a per-criterion `PASS`/`FAIL` with specific reasons.* Set each `gate` flag `true` only for the criteria the judge passes; every `FAIL` becomes findings for another pass.

- [ ] Every factual claim is verified against the codebase or confirmed by the user — zero unverified "currently X" statements. (`claims_verified`)
- [ ] No open questions, TBDs, "decide later", `[NEEDS CLARIFICATION]` markers, or contradictions remain anywhere in the spec. (`no_open_questions`)
- [ ] No speculative scope or gold-plating — everything present serves the stated goal. (`no_overengineering`)
- [ ] No text that exists *only* for history, context, or rationale (the **Bloat** row above) — nothing a builder doesn't need. Decision/config/field **tables** stay. (`no_bloat`)
- [ ] A developer who has never seen this work could implement it end-to-end without asking a question. (`implementable_cold`)
- [ ] Every functional requirement and constraint is captured in the **Acceptance Criteria** list as a discrete, atomic, testable assertion — nothing load-bearing left only in prose, and every criterion is addressed by the plan. (`ac_complete`)

## Handoff

When the gate passes, give a short summary: what you corrected, what you cut, and which open questions you resolved (with the user's answers). State plainly that the spec is ready to implement. The `Stop` hook clears the ledger automatically once the gate passes. **Stop there — do not begin implementation.** To build it, hand the ready spec to **`launch-spec`**, which compiles it into a `/goal` driver; run that, then gate with **`verify-spec`**.

## Guardrails

- **Never invent facts** to fill a gap. Verify it, or ask.
- **Refine, don't redesign.** If you believe the design itself is wrong, raise it as a question — don't unilaterally rewrite the approach.
