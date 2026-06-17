# spec-ops

A four-skill spec workflow — **write → refine → launch → verify** — that carries a change from idea to a verified implementation. Every step that checks a fact does so against **reality** (the codebase at HEAD, git history, live read-only state), never against another doc.

```mermaid
flowchart LR
    W["write-spec<br/>draft"] --> R["refine-spec<br/>harden + ground"]
    R --> L["launch-spec<br/>compile /goal driver"]
    L -->|emits driver| G(["/goal<br/>native implement"])
    G --> V["verify-spec<br/>ground claims vs reality"]
    V -. discrepancies → fix .-> G
```

`launch-spec` is **emit-only**: it compiles the driver and stops; the native `/goal` does the implementing, and the driver's done-gate runs `verify-spec` so completion is confirmed against real code, not the worker's say-so.

## Skills

| Skill | Does |
|-------|------|
| `/spec-ops:write-spec` | Draft a concise, scannable spec — **behavior, not implementation**; tables / mermaid / mockups over prose; say things once; opens with a flat, id'd **Acceptance Criteria** list (the testable contract; optionally organized into ordered named groups); an explicit **Boundaries** section (what NOT to touch). Asks before guessing via `AskUserQuestion`. |
| `/spec-ops:refine-spec` | Harden a draft into an implementation-ready spec. A grounded multi-pass loop: dispatch parallel `Explore` agents to **verify every claim against the codebase**, resolve open questions with you, cut bloat and over-engineering, and loop until an **independent judge** passes a five-point readiness gate. |
| `/spec-ops:launch-spec` | Compile a verified spec into the self-contained **`/goal` driver** that implements it — goal, spec/checklist references, inlined boundaries, and a `verify-spec` done-gate. Picks the driver (see below), copies it to your clipboard, and **stops** (never runs it). |
| `/spec-ops:verify-spec` | Check that what was actually built matches the claims — every "we did X" / "the system does Y" grounded in **real source, git, or live read-only CLI**, never the spec. Enumerates claims, verifies each with cited evidence, runs a **backward sweep** (flags delivered code that maps to *no* acceptance criterion — scope creep / silent reinterpretation), has a fresh judge confirm completeness, and reports discrepancies. **Edits nothing.** |

## Design principles

- **Enumerated, gated acceptance criteria.** Every spec opens with a flat, stable-id'd **Acceptance Criteria** list — the reader's scannable contract of *what must be true*, and the machine's checklist. The detailed body says *how/where* and cites each `AC-id`; the criteria say *what*, enumerated exhaustively and never condensed. `launch-spec`'s done-gate and `verify-spec` both check the implementation against **every `AC-id`**, so a requirement can't silently fall off between spec and "done". When it aids the reader, `refine-spec` organizes the criteria into **ordered named groups** — a capability map plus a dependency-derived build order (`needs §X`), never dates.
- **Coverage runs both directions.** `verify-spec` defends *forward* coverage (every `AC-id` has cited evidence) and also runs a **backward sweep**: it flags delivered code that maps to **no** criterion — scope creep, silent reinterpretation, or a derived requirement built with no AC. Backward findings are *reported* (with a proposed AC and a triage), never auto-changed — `verify-spec` still edits nothing.
- **Grounded against reality, never docs.** `refine-spec` and `verify-spec` check claims against the codebase at branch HEAD, the git history, and (for infra/ops) live read-only CLI state. Sibling or "completed" specs are treated as *possibly stale* — the thing under review is the hypothesis, not the evidence.
- **Enforced loops, not one-shot passes.** `refine-spec` and `verify-spec` run multi-pass loops gated by a `Stop` hook plus a `/tmp` ledger, so neither can sign off after a shallow pass.
- **A fresh judge decides "done."** The agent that did the work never declares it complete — an independent subagent with no memory of the work attests readiness (refine) or completeness (verify), mirroring how `/goal` uses a separate evaluator.
- **Ask, don't guess.** Genuine ambiguities go to you via `AskUserQuestion`; a gap is never filled with an assumption.
- **Emit-only handoff.** `launch-spec` compiles the `/goal` driver and quits — it writes at most a `tasks.md`, never code, never the spec, and never runs the driver itself.

## Choosing the implementation driver (`launch-spec`)

`launch-spec` defaults to **`/goal`** and steps up only on **structural** signals — *how the work is shaped, never how big it is*. A broad-but-shallow change (one mechanical edit across many files) stays in `/goal` regardless of file count.

| Driver | Step up when |
|--------|--------------|
| **`/goal`** (default) | One coherent change that decomposes into bounded, mostly-independent or shallowly-coupled edits. |
| **`ultracode`** (dynamic workflow) | **≥2 independent workstreams** (disjoint files, no ordering) → parallel fan-out; a **shared contract carried through dependent steps** that must stay consistent → `pipeline()`; **unbounded scope** ("every / all / across the codebase") → discovery. |
| **`/batch`** | The **same mechanical edit repeated across ≥5 files** with no per-file decision. |

## Stop-hook enforcement

The two looping skills carry their gate as a skill-scoped `Stop` hook (active only while the skill runs), each backed by a `/tmp` ledger keyed on the session id:

| Skill | Hook | Blocks the stop until… |
|-------|------|------------------------|
| `refine-spec` | `skills/refine-spec/stop_refine_spec.py` | all five readiness-gate flags are `true`, every open question resolved, and no `TODO` / `TBD` / `FIXME` markers remain in the spec. (The flags are set only after an independent readiness judge passes.) |
| `verify-spec` | `skills/verify-spec/stop_verify_spec.py` | every claim has a cited verdict, every unverifiable claim is dispositioned, and an independent judge returns `complete`. |

## Quickstart

```text
/spec-ops:write-spec  add per-rule long-term discount  @docs/specs/discount.md
/spec-ops:refine-spec @docs/specs/discount.md
/spec-ops:launch-spec @docs/specs/discount.md     # → driver copied to clipboard
#   ⌘V into a fresh /goal session (pair with auto mode) to implement
/spec-ops:verify-spec @docs/specs/discount.md     # after implementation
```

You don't have to type these commands — all four skills are model-invocable and trigger automatically from a matching request ("write a spec for…", "review / finalize this spec", "turn this spec into a `/goal` driver", "is this actually done?"). Name them explicitly when you want to force the choice.
