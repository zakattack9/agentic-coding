---
name: launch-spec
description: Compile a finished, verified spec into the self-contained /goal driver prompt that implements it — then stop. Use this on a finished, refined spec to turn it into the one-shot execution prompt you'd otherwise hand-type: the goal, the spec + checklist references, the boundaries (what NOT to touch), and a verify-spec completion gate. It does NOT implement, run, or loop — it emits the driver and quits; you run it with /goal (the native implement step). For genuinely wide or repetitive work it can emit a dynamic-workflow or /batch brief instead.
argument-hint: [@path/to/spec.md] [focus areas]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Write, Bash
---

# Launch Spec

Fourth companion to `write-spec`, `refine-spec`, and `verify-spec`. It **compiles a ready spec into the driver `/goal` needs** — a goal, a checkable condition, explicit boundaries, and a `verify-spec` done-gate — then **quits**. `/goal` (native) does the implementing; you run the emitted prompt yourself.

**This skill is emit-only. It never implements, runs, polls, or re-launches.** It reads the spec and writes at most a `tasks.md`; nothing else.

Arguments: $ARGUMENTS

## Inputs

- **Spec** — the path / `@`-mention of the finished spec. If none is given, ask with `AskUserQuestion`.
- **Focus areas** — anything to scope (e.g. "just the backend tasks").

**Precondition (heuristic, not a gate).** This skill assumes the spec already passed `refine-spec`. Before compiling, scan it for readiness: does it have a concrete **Checklist** of work items, and — unless the change is genuinely self-contained — an explicit **Boundaries** section (what NOT to touch)? If the Checklist is missing (or Boundaries are absent for a change that clearly has out-of-bounds areas), say so and recommend running `refine-spec` first — don't silently emit a driver for an under-baked spec. (The real enforcement is `verify-spec` at the end, which catches a weak spec by contradiction.)

## Choosing the driver — `/goal` by default

`/goal` is the answer for the overwhelming common case: one coherent change ground to completion, including most multi-item checklists. A merely **long** checklist is not, by itself, a reason to step up. Only offer an alternative when the spec's shape genuinely calls for it — surface the choice with `AskUserQuestion`, `/goal` pre-selected. Never present these as co-equal modes:

- **`/goal`** (default) — a single coherent task that fits in one session. Depth; guards drift.
- **Dynamic workflow (`ultracode`)** — step up when **either**: the spec fans into **≥2 independent workstreams** that can run in parallel, **or** the checklist is large enough (a very large PRD) that one `/goal` session would accumulate too much context to stay reliable — each item then gets its own fresh context. Match the emitted brief to the reason:
  - *Independent workstreams* → a **parallel fan-out** with **per-leaf boundaries** ("touch ONLY these files") so concurrent agents can't collide.
  - *Large sequential PRD* → a **pipeline of fresh-context stages** (`pipeline()`), where **dependency ordering** — not file-disjointness — prevents collisions.

  Cost-warned — token-expensive; reserve for real width or real context pressure.
- **`/batch`** — *only* for an identical, repetitive change across many files (isolated agent + worktree per item).

## What it emits

A single **driver prompt** to paste into a fresh `/goal` session. The pasted text **is the `/goal` condition** (≤4,000 chars), checked each turn by a **tool-less evaluator** that only sees the transcript — it can't open files or run commands. Two consequences shape what you emit:

- **Point the worker at the spec / `tasks.md` with an explicit read directive** (e.g. *"read `@spec.md` and `@tasks.md`, then implement them"*) rather than inlining their bodies — so it works whether or not the mention pre-expands, and the worker (not the evaluator, which can't open files) does the reading. Inline only the **Boundaries** and **done-gate** the evaluator must enforce directly.
- **Make every end state demonstrable from the worker's own output** — a printed test result, a clean `verify-spec` run — never implicit, because that transcript is all the evaluator sees.

The parts:

| Part | Source | Why |
| --- | --- | --- |
| **Goal** | the spec's TL;DR | the **measurable end state** in one line — the spec implemented per its Checklist; what must be *true* at the end, not a description of the change |
| **Spec + checklist** | `@`-reference the spec; derive a `tasks.md` **only if** the Checklist lacks ordering/dependencies (else `@`-reference the Checklist directly) | the contract + tick-and-write-back continuity if the run compacts |
| **Boundaries** | **change-specific** boundaries from the spec, **inlined**; promote **durable/cross-cutting** ones (conventions, architecture, "don't touch prod") to **CLAUDE.md** instead | the top anti-drift lever. Inline change-specific boundaries; durable ones live in CLAUDE.md, re-injected every turn |
| **Done-gate** | fixed | *"You are not done until the spec is fully implemented AND `verify-spec` returns zero contradicted claims."* — the worker **runs `verify-spec`** (which grounds against HEAD/git/live state) and surfaces its verdict, so the evaluator confirms 'done' from a code-grounded check in the transcript, not the worker's say-so |
| **Durability note** | fixed | state lives in git + `tasks.md` + `CLAUDE.md`, not the conversation |

Write `tasks.md` beside the spec only when it adds decomposition the Checklist lacked. To bound a long run, the user can append a turn/time guard to the condition (e.g. `or stop after N turns`); by default it runs until the done-gate holds. Show the driver prompt in chat for the user to run; **do not run it**.

## Handoff

Emit the driver, tell the user how to run it (paste into a fresh `/goal` session — pair with **auto mode** so each goal turn runs unattended), and **stop**. Then the native flow continues: `/goal` implements → `verify-spec` grounds every claim against HEAD → zero contradicted claims = done.

**Copy the driver to the clipboard** so the handoff is a single ⌘V. After showing the prompt in chat, pipe the *exact same text* to the system clipboard via a portable wrapper, then confirm. Copying is not running — it stays emit-only. Use a quoted heredoc so the driver is never written to disk and no escaping is needed (`$`, backticks, and quotes pass through literally). Pick the first clipboard tool that exists and fall back to chat-only if none do:

```bash
{ if command -v pbcopy   >/dev/null 2>&1; then pbcopy                       # macOS
  elif command -v wl-copy >/dev/null 2>&1; then wl-copy                     # Wayland
  elif command -v xclip   >/dev/null 2>&1; then xclip -selection clipboard  # X11
  elif command -v clip.exe >/dev/null 2>&1; then clip.exe                   # WSL
  else cat >/dev/null; exit 3; fi; } <<'LAUNCH_SPEC_EOF'
…the driver prompt, verbatim…
LAUNCH_SPEC_EOF
```

If the copy succeeds, print `📋 Copied to clipboard — open a fresh session and ⌘V into /goal`. If it exits non-zero (no clipboard tool, or a headless/remote shell where there's no local pasteboard), say so plainly and fall back to "copy the prompt above manually" — never let a missing clipboard block the handoff.

## Guardrails

- **Emit-only, forever.** Never run, poll, or re-launch the driver. If you're tempted to loop, stop and hand the prompt to the user.
- **`Bash` is for the clipboard copy only.** The single thing this skill may shell out for is piping the driver to a clipboard tool (see Handoff). Never use `Bash` to run the driver, invoke `/goal`, execute the spec, or touch git/the project — that would break emit-only.
- **Write only `tasks.md`.** The single file this skill may write is a `tasks.md` beside the spec (and only when the Checklist lacks ordering). Show the driver prompt in chat — never write it to disk; never edit the spec or code.
- **Don't re-implement `/goal`.** This skill compiles the spec into `/goal`'s input; `/goal` does the work.
- **The done-condition is `verify-spec`, by composition.** Wire it into the emitted prompt; never restate or rebuild its logic here.
- **Boundaries are load-bearing.** If the spec lacks them, flag it — an unbounded `/goal` run is where drift happens.
