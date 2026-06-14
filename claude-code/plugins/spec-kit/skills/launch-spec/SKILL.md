---
name: launch-spec
description: Compile a finished, verified spec into the self-contained /goal driver prompt that implements it — then stop. Use this on a finished, refined spec to turn it into the one-shot execution prompt you'd otherwise hand-type: the goal, the spec + checklist references, the boundaries (what NOT to touch), and a verify-spec completion gate. It does NOT implement, run, or loop — it emits the driver and quits; you run it with /goal (the native implement step). For genuinely wide or repetitive work it can emit a dynamic-workflow or /batch brief instead.
argument-hint: [@path/to/spec.md] [focus areas]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Write
---

# Launch Spec

Fourth companion to `write-spec`, `refine-spec`, and `verify-spec`. The implement step of `write → refine → implement → verify` is **already native**: for a validated spec, **`/goal`** grinds it to completion. `launch-spec` does **not** re-implement that loop — it **compiles a ready spec into the driver `/goal` needs** (a goal, a checkable condition, explicit boundaries) plus a `verify-spec` done-gate, then **quits**. You run the emitted prompt yourself.

**This skill is emit-only. It never implements, runs, polls, or re-launches.** Doing so would rebuild native plumbing (a "politer Ralph" — superseded; every problem it solved is now a native primitive). It reads the spec and writes at most a `tasks.md`; nothing else.

Arguments: $ARGUMENTS

## Inputs

- **Spec** — the path / `@`-mention of the finished spec. If none is given, ask with `AskUserQuestion`.
- **Focus areas** — anything to scope (e.g. "just the backend tasks").

**Precondition (heuristic, not a gate).** This skill assumes the spec already passed `refine-spec`. Before compiling, scan it for readiness: does it have a concrete **Checklist** of work items, and — unless the change is genuinely self-contained — an explicit **Boundaries** section (what NOT to touch)? If the Checklist is missing (or Boundaries are absent for a change that clearly has out-of-bounds areas), say so and recommend running `refine-spec` first — don't silently emit a driver for an under-baked spec. (The real enforcement is `verify-spec` at the end, which catches a weak spec by contradiction.)

## Choosing the driver — `/goal` by default

`/goal` is the answer for the overwhelming common case: one coherent change ground to completion. Only offer an alternative when the spec's shape genuinely calls for it — and surface the choice with `AskUserQuestion`, `/goal` pre-selected. Never present these as co-equal modes:

- **`/goal`** (default) — a single coherent task. Depth; guards drift; accumulating/compacting session with its own maker/checker.
- **Dynamic workflow (`ultracode`)** — *only* if the spec genuinely fans into **≥2 independent workstreams** that can run in parallel. Emit a fan-out brief with **per-leaf boundaries** ("touch ONLY these files") so parallel agents can't collide. Cost-warned — token-expensive; reserve for real width.
- **`/batch`** — *only* for an identical, repetitive change across many files.

## What it emits

A single self-contained **driver prompt** to paste into a fresh `/goal` session — everything inlined so the new session needs nothing but the `@`-referenced files:

| Part | Source | Why |
| --- | --- | --- |
| **Goal** | the spec's TL;DR | one line stating what "done" means |
| **Spec + checklist** | `@`-reference the spec; derive a `tasks.md` **only if** the Checklist lacks ordering/dependencies (else `@`-reference the Checklist directly) | the contract + tick-and-write-back continuity across `/goal`'s lossy compaction |
| **Boundaries** | the spec's Boundaries section, **inlined** | what the agent must NOT touch — the top anti-drift lever, restated where compaction can't drop it |
| **Done-gate** | fixed | *"You are not done until the spec is fully implemented AND `verify-spec` returns zero contradicted claims."* — reuses the independent checker, not `/goal`'s gameable in-session check |
| **Durability note** | fixed | state lives in git + `tasks.md` + `CLAUDE.md`, not the conversation — so a compaction or fresh session loses nothing that matters |

Write `tasks.md` beside the spec only when it adds decomposition the Checklist lacked. Show the driver prompt in chat for the user to run; **do not run it**.

## Handoff

Emit the driver, tell the user how to run it (paste into a fresh `/goal` session), and **stop**. Then the native flow continues: `/goal` implements → `verify-spec` grounds every claim against HEAD → zero contradicted claims = done.

## Guardrails

- **Emit-only, forever.** Never run, poll, or re-launch the driver. The instant this skill would "run it and watch," it has become Ralph. If you're tempted to loop, stop and hand the prompt to the user.
- **Write only `tasks.md`.** The single file this skill may write is a `tasks.md` beside the spec (and only when the Checklist lacks ordering). Show the driver prompt in chat — never write it to disk; never edit the spec or code.
- **Don't re-implement `/goal`.** This skill compiles the spec into `/goal`'s input; `/goal` does the work. For a refined spec, prefer `/goal` over the `ralph-*` suite — it is superseded for this.
- **The done-condition is `verify-spec`, by composition.** Wire it into the emitted prompt; never restate or rebuild its logic here.
- **Boundaries are load-bearing.** If the spec lacks them, flag it — an unbounded `/goal` run is where drift happens.
