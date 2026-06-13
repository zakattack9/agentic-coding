---
name: refine-spec
description: Review, verify, and tighten an existing feature spec until it is accurate, hallucination-free, not over-engineered, and ready to implement. Use immediately after write-spec, or whenever the user asks to review, fact-check, refine, simplify, de-risk, or finalize a spec / PRD / requirements doc before building. Runs a grounded multi-pass loop that verifies every claim against the codebase, asks the user to resolve open questions, cuts bloat and speculative scope, and stops only when the spec passes an implementation-readiness gate.
argument-hint: [@path/to/spec.md] [focus areas]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Edit, Write, Task
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

### 1. Verify — ground every claim against reality

List every **checkable claim** in the spec: file paths, function / class / method names, table / column names, routes, config or env keys, library or framework behavior, "the system currently does X" statements, data shapes, and counts.

Dispatch **parallel `Explore` subagents** (the `Task` tool, `subagent_type: Explore`) to check these claims against the actual codebase — they are read-only and fast. Split the claims by area (e.g. one agent per subsystem, model layer, or route group) and scale the agent count to the spec: a short spec may need a single verifier; a large one, several. Give each agent the relevant spec excerpt plus its claim list, and require a structured verdict per claim:

> For each claim return one of: `confirmed` / `wrong` (give the correct value and `file:line`) / `not found in codebase`. Quote the supporting evidence. Do not speculate — if you cannot verify it, say so.

Run one more agent (or do it yourself) as a **skeptic lens**: read the whole spec hunting for internal contradictions, over-engineering, speculative scope, and anything an implementer could not actually act on.

### 2. Reconcile — sort what came back

Dedupe the findings and bucket each one:

| Bucket | What it is | Action |
|---|---|---|
| **Inaccuracy** | Contradicts the codebase | Fix to the verified value |
| **Open question** | Cannot be verified; needs a human decision | Queue for **Resolve** |
| **Over-engineering** | Speculative, gold-plated, or beyond the stated goal | Propose cutting |
| **Bloat** | Historical prose, rationale, restated field names, duplication | Cut |

### 3. Resolve — ask the user

For **every** genuine ambiguity, unverifiable assumption, or open decision that changes *what gets built*, ask the user with `AskUserQuestion`. Batch related questions into one call; ask as many as you need across passes. **It is better to ask one too many questions than to let the spec ship an assumption.** Never guess to fill a gap.

You do **not** need to ask about facts you already verified and corrected against the codebase — fix those directly and note them in the final summary.

### 4. Refine — edit the spec

Apply, as one coherent edit per pass:

- **Corrections** — replace every inaccuracy with the verified value.
- **Resolutions** — fold in the user's answers.
- **Cuts** — remove over-engineering and bloat.
- **Simplification** — tighten so another dev can grasp the objective and the details fast, following the `write-spec` philosophy: say things once, in the right place; describe behavior, not implementation; show with tables / mermaid / examples instead of prose; bold the key terms; every sentence must earn its place.

**Preserve every detail an implementer needs.** Simplify *wording and structure*, never silently drop substance. If you are unsure whether a detail is load-bearing, ask before cutting it. Keep edits reviewable as a clean git diff.

### 5. Re-check — did the edit settle or stir?

Re-read the edited spec. Edits can introduce new claims, new ambiguities, or new contradictions. If the pass changed anything, **loop** and verify again. If a full pass produced no fixes and no questions, evaluate the readiness gate.

## Readiness gate

Finish only when **all** of these hold. Report the gate's status at the end of each pass.

- [ ] Every factual claim is verified against the codebase or confirmed by the user — zero unverified "currently X" statements.
- [ ] No open questions, TBDs, "decide later", or contradictions remain anywhere in the spec.
- [ ] No speculative scope or gold-plating — everything present serves the stated goal.
- [ ] No historical prose, rationale-for-its-own-sake, restated field names, or duplicated information.
- [ ] A developer who has never seen this work could implement it end-to-end without asking a question.

## Handoff

When the gate passes, give a short summary: what you corrected, what you cut, and which open questions you resolved (with the user's answers). State plainly that the spec is ready to implement. **Stop there — do not begin implementation** unless the user asks.

## Guardrails

- **Never invent facts** to fill a gap. Verify it, or ask.
- **Refine, don't redesign.** If you believe the design itself is wrong, raise it as a question — don't unilaterally rewrite the approach.
- Simplify presentation, **never** remove implementation-critical detail. When in doubt, ask.
- Respect `.gitignore` — never read or edit ignored files (secrets, env, build artifacts) while verifying claims.
