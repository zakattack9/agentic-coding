---
name: launch-spec
description: Compile a finished, verified spec into the self-contained /goal driver prompt that implements it — then stop. Use this on a finished, refined spec to turn it into the one-shot execution prompt you'd otherwise hand-type: the goal, the spec + checklist references, the boundaries (what NOT to touch), and a verify-spec completion gate. It does NOT implement, run, or loop — it emits the driver and quits; you run it with /goal (the native implement step). For genuinely wide or repetitive work it can emit a dynamic-workflow or /batch brief instead.
argument-hint: [@path/to/spec.md] [focus areas]
model: opus
effort: high
allowed-tools: Read, Grep, Glob, Write, Bash
---

# Launch Spec

Fourth companion to `write-spec`, `refine-spec`, and `verify-spec`. It **compiles a ready spec into the driver `/goal` needs** — a goal, a checkable condition, explicit boundaries, and a `verify-spec` done-gate — then **quits**. `/goal` (native) does the implementing; you run the emitted prompt yourself.

**This skill is emit-only. It never implements, runs, polls, or re-launches.** It reads the spec and writes at most a `tasks.md`; nothing else.

Arguments: $ARGUMENTS

## Inputs

- **Spec** — the path / `@`-mention of the finished spec. If none is given, ask with `AskUserQuestion`.
- **Focus areas** — anything to scope (e.g. "just the backend tasks").

**Precondition (heuristic, not a gate).** This skill assumes the spec already passed `refine-spec`. Before compiling, scan it for readiness: does it have an id'd **Acceptance Criteria** table (the contract the done-gate enforces) and — unless the change is genuinely self-contained — an explicit **Boundaries** section (what NOT to touch)? A standard/full spec should also carry the human layer (a **`## Summary`** and a two-subsection **`## Checklist`**), but that is `refine-spec`'s gate, not a launch precondition. If the Acceptance Criteria table is missing (or Boundaries are absent for a change that clearly has out-of-bounds areas), say so and recommend running `refine-spec` first — don't silently emit a driver for an under-baked spec. (The real enforcement is `verify-spec` at the end, which catches a weak spec by contradiction.)

## Choosing the driver

Default to **`/goal`**. Step up only when a **structural** trigger below fires — evaluate them **top-down, first match wins**. The triggers are about *how the work is shaped*, never *how big it is*: a broad-but-shallow change (a mechanical tweak across many files, each edit self-contained) stays in `/goal` no matter how many files it spans, because nothing must be held across edits. Surface the result with `AskUserQuestion` (matched driver pre-selected) so the user can override.

**1. `/batch`** — the spec is the **same mechanical edit repeated across ≥5 files** with no per-file decision (rename a symbol, bump a version string everywhere). Emit a `/batch` brief: the one edit + the file list (isolated agent + worktree per file). A `/batch` can't self-gate per file, so the brief ends with an explicit completion step — **after the batch lands, run `verify-spec` on the spec once; zero contradicted = done.**

**2. `ultracode` (dynamic workflow)** — step up on any of these structural signals; each implies its shape:
  - **Independent workstreams** — the **AC groups** split into **≥2 streams** with **disjoint file sets** and **no ordering** between them → a **parallel fan-out** with per-leaf boundaries ("touch ONLY these files") so concurrent agents can't collide.
  - **Carried interdependence** — implementing the change means threading a **shared, evolving contract** (a data model, protocol, or invariant) through **dependent steps that must stay mutually consistent**, so a fresh-but-uninformed session would break later work → a **`pipeline()`** of fresh-context stages that carry that contract forward in dependency order.
  - **Unbounded scope** — the affected set can't be enumerated up front ("every / all callers of `X` / across the codebase"), forcing search-then-edit over an open-ended surface → `ultracode` (parallel if the discovered sites turn out independent, else a pipeline).

  Whatever its shape, the workflow's **final stage is `verify-spec`** (and, when phased, each phase's exit gate is `verify-spec` scoped to that phase) — it isn't done until verify returns zero contradicted, mirroring the `/goal` done-gate. A workflow `agent()` **cannot spawn a `Task`**, so the emitted verify stage must run its cross-model judge as **sibling stages** — the Codex bridge (`codex_bridge.py --kind judge-verify`, `Bash`, standalone) and `agent({ agentType: 'spec-ops:spec-verify-judge' })` auditing the ledger before the zero-contradicted gate — never a lone verify agent left to self-administer its own judge (see `references/cross-model-judge.md`, "Where `Task`-spawn is unavailable").

**3. `/goal`** (default) — none of the above: one coherent change that decomposes into bounded, mostly-independent or shallowly-coupled edits, **regardless of file count**. The rest of this skill compiles it.

## What it emits

A single **driver prompt** to paste into a fresh session. It is **command-prefixed so one paste runs it**: the emitted (and copied) text **begins with its command token**, byte-identical in chat and on the clipboard, prefix included:

| Driver | Emitted text begins with | One paste… |
| --- | --- | --- |
| **`/goal`** (default) | `/goal ` + the ≤4,000-char condition | invokes `/goal` with the driver as its condition — pair with auto mode |
| **`/batch`** | `/batch ` + the batch brief | invokes `/batch` |
| **dynamic workflow** | `ultracode` + the workflow brief (below) | opts into multi-agent orchestration; Claude authors + runs the workflow from the brief |

For **`/goal`**, the pasted text **is the `/goal` condition** — **≤4,000 chars with the `/goal ` prefix counted in** — checked each turn by a **tool-less evaluator** that only sees the transcript (it can't open files or run commands). If the composed `/goal ` driver would exceed that budget, that's the existing signal to **phase / escalate** (see *Context bounding*), **never** to truncate the condition. (The `ultracode` brief is not a `/goal` and is not bound by the 4,000-char cap.) Two consequences shape what you emit:

- **Point the worker at the spec / `tasks.md` with an explicit read directive** (e.g. *"read `@spec.md` and `@tasks.md`, then implement them"*) rather than inlining their bodies — so it works whether or not the mention pre-expands, and the worker (not the evaluator, which can't open files) does the reading. Inline only the **Boundaries** and **done-gate** the evaluator must enforce directly.
- **Make every end state demonstrable from the worker's own output** — a printed test result, a clean `verify-spec` run — never implicit, because that transcript is all the evaluator sees.

The parts:

| Part | Source | Why |
| --- | --- | --- |
| **Goal** | the spec's TL;DR + **Acceptance Criteria** | the **measurable end state** — the spec implemented so that **every acceptance criterion (`AC-1..N`) holds**; what must be *true* at the end, not a description of the change |
| **Spec + checklist** | `@`-reference the spec; derive a `tasks.md` work-breakdown **only if** the **AC groups** don't already partition the work in `needs §X` order — key decomposition off the **AC groups**, never off the `## Checklist` | the contract + tick-and-write-back continuity if the run compacts. The `## Checklist` is **verification, not a build plan**: `### For agents` feeds the `verify-spec` done-gate, `### For humans` is the human sign-off handoff |
| **Boundaries** | **change-specific** boundaries from the spec, **inlined**; promote **durable/cross-cutting** ones (conventions, architecture, "don't touch prod") to **CLAUDE.md** instead | the top anti-drift lever. Inline change-specific boundaries; durable ones live in CLAUDE.md, re-injected every turn |
| **Done-gate** | fixed | *"You are not done until **every acceptance criterion (`AC-1..N`) is satisfied** AND `verify-spec` returns zero contradicted claims."* — the worker **runs `verify-spec`**, which grounds **each `AC-id`** against HEAD/git/live state and surfaces the per-criterion verdict, so the evaluator confirms 'done' from a code-grounded check in the transcript, not the worker's say-so |
| **Commit cadence** | fixed | *"Commit after each phase's acceptance criteria verify clean — one commit per AC group (a single-context run: one commit once all criteria verify clean), scoped to the files that phase changed, with a conventional message citing its `AC-id`s. Don't push."* — so the implementation history maps to the spec's structure and a compaction / restart resumes from committed state. (Commit messages are git provenance, not the artifact — `AC-id`s belong here; the next row keeps them out of the *shipped files*.) |
| **Artifact hygiene** | fixed | *"The spec is build scaffolding, not part of the product — **write the artifact as if the spec never existed.** The delivered code, docs, comments, tests, and any generated output must read standalone: **(1)** leave **no** `AC-id`s, build-phase / §-section numbers, spec ids or filenames, or predecessor-component provenance in them; **(2) name** every function, variable, class, and test for **what it does**, never after the spec, a build phase, or a predecessor (no `AC34_*`, `spec07_*`, `phase1_*`, `legacy_*`); **(3)** carry **no background or historical context that doesn't help a future maintainer act** — cut what the code *used to be*, alternatives *considered and rejected*, and how the *build was sequenced*. **Keep load-bearing rationale** (why this design, what breaks if it changes), pattern callouts, and in-repo cross-refs that resolve in the shipped tree. The test for any word, name, or comment: would it make sense to someone who has never seen the spec and only needs to maintain the code? If not, it's scaffolding — cut it."* — a future reader of the product must never be pointed back at the spec, or made to carry build trivia; `verify-spec`'s hygiene sweep flags what slips through |
| **Durability note** | fixed | state lives in git + `tasks.md` + `CLAUDE.md`, not the conversation |

Write `tasks.md` beside the spec only when it adds decomposition the **AC groups** lacked. To bound a long run, the user can append a turn/time guard to the condition (e.g. `or stop after N turns`); by default it runs until the done-gate holds. Show the driver prompt in chat for the user to run; **do not run it**.

**The done-gate is the completion contract for *every* driver, not just `/goal`.** `verify-spec` grounds every `AC-id` and returns zero contradicted — wired as the `/goal` condition above, the final (and per-phase) stage of an `ultracode` workflow, or an explicit `verify-spec` run after a `/batch`. The mechanism differs by driver; the contract is identical, so "done" is always grounded against real code, never assumed.

### The `ultracode` brief — a runnable prompt, never a script

When the driver is the dynamic workflow, emit an **`ultracode`-led prompt** (leading token `ultracode`) — **never a literal `pipeline()` / `parallel()` workflow script**. A script would have to be written to a repo file, breaking emit-only; Claude authors the workflow internally from the prompt. The brief carries **every** part a `/goal` driver carries — not just the shape-specific ones:

- **Read directive** — *"read `@spec.md` (and `@tasks.md`) in full first."*
- **Measurable goal** — the spec implemented so **every acceptance criterion holds**, grounded by `verify-spec` (zero contradicted).
- **Workflow shape** — phased by **AC group** in `needs §X` order, with `verify-spec` as the **final gate and each phase's exit gate**; where a workflow `agent()` can't spawn a `Task`, the verify stage dispatches its cross-model judge as **sibling stages** (the Codex bridge standalone + `agent({ agentType: 'spec-ops:spec-verify-judge' })`).
- **Boundaries** — the spec's Boundaries, **inlined**.
- **Commit cadence** — one scoped commit per phase once its acceptance criteria verify clean (conventional message; don't push).
- **Artifact hygiene** — deliver code/docs/tests that read standalone: no spec ids, phase/§ numbers, spec-named identifiers, or build-increment framing; keep load-bearing rationale.

A single paste opts into orchestration and Claude **authors + runs** the workflow from the brief — `launch-spec` stays emit-only. When you preview the `ultracode` option with `AskUserQuestion` before compiling, keep that preview **natural-language too — never a script-shaped preview**, which primes the wrong mental model and risks the final compile copying its shape.

## Context bounding — phase by AC group only when escalated

**Default: one context holds every `AC-1..N` — no phasing.** This is the common case; emit a single driver gated on all acceptance criteria at once.

Step up to a **phased driver** only when the structural triggers above already escalate beyond one `/goal` context (the `ultracode` signals, or a genuinely large / hard-sequenced criteria set) — **never on an AC count alone** (no count threshold; inherit the same structural signals). The reason is real: the share of criteria a single context reliably honors decays as the number it must hold at once grows, with *omissions* dominating the failures. So when you escalate, **partition the AC-ids by the spec's named AC groups, in their `needs §X` order**, so no one context carries all N:

- Each phase is one fresh context that **front-loads only its own AC-ids** (re-applying the "criteria open the context" win per phase) and carries the inlined Boundaries.
- **Each phase's exit gate is "these AC-ids verify clean"** — the same `verify-spec` done-gate, scoped to the phase's subset; **on clean, that phase commits** (scoped, message citing its `AC-id`s). Reuse the machinery; never invent a new gate.
- **`needs §X` is the binding order.** A `needs §X` chain → a `pipeline()` of fresh-context stages carrying the shared contract forward; independent groups (no `needs`) → `parallel()` leaves with disjoint per-leaf boundaries. That is exactly the `ultracode` shape the trigger already selected — those groups simply supply the partition boundaries.
- **A group DAG (the common case) → a topologically-ordered `pipeline()` with a `parallel()` stage** wherever sibling groups depend only on already-built ones (e.g. three groups that each `needs §1` become one parallel phase after §1, then their dependents follow). Walk the partition in dependency order and front-load each phase's own AC-ids — it is neither a pure chain nor a pure fan-out but a mix of both.
- A spec with **one group (or a flat list) never phases** — it stays a single context, all `AC-1..N` in the one done-gate.

## Handoff

Emit the driver, tell the user how to run it (for `/goal`: paste into a fresh session — the paste is already prefixed with `/goal`; pair with **auto mode** so each goal turn runs unattended), and **stop**. Then the flow continues — the worker implements and **completion is confirmed by `verify-spec` grounding every claim against HEAD (zero contradicted = done)**, whether that's baked into the `/goal` condition, the final stage of the `ultracode` workflow, or an explicit `verify-spec` run after the `/batch`. Never treat the work as done without that grounded check.

**Copy the driver to the clipboard** so the handoff is a single ⌘V. After showing the prompt in chat, pipe the *exact same text* (**command prefix included** — the clipboard bytes are byte-identical to the chat bytes) to the system clipboard via a portable wrapper, then confirm. Copying is not running — it stays emit-only. Use a **single quoted heredoc** so the driver is never written to disk and no escaping is needed (`$`, backticks, and quotes pass through literally). Pick the **session-appropriate** tool present — gate the Wayland/X11 branches on the session's display env (`$WAYLAND_DISPLAY` / `$DISPLAY`) so a tool installed but wrong for the session can't win and swallow the copy — and fall back to chat-only if none land:

```bash
{ if   command -v pbcopy   >/dev/null 2>&1; then pbcopy                                                   # macOS
  elif [ -n "$WAYLAND_DISPLAY" ] && command -v wl-copy >/dev/null 2>&1; then wl-copy                       # Wayland
  elif [ -n "$DISPLAY" ]        && command -v xclip   >/dev/null 2>&1; then xclip -selection clipboard     # X11
  elif [ -n "$DISPLAY" ]        && command -v xsel    >/dev/null 2>&1; then xsel --clipboard --input       # X11 (Mint/XFCE)
  elif command -v clip.exe >/dev/null 2>&1; then clip.exe                                                  # WSL
  else cat >/dev/null; exit 3; fi; } <<'LAUNCH_SPEC_EOF'
…the driver prompt, verbatim (already command-prefixed — `/goal …`, `/batch …`, or `ultracode …`)…
LAUNCH_SPEC_EOF
```

A single-feed heredoc pipes to exactly one chosen tool and can't retry a second, so getting the **selection** right up front is the fix — a chosen tool that still exits non-zero just degrades to chat-only.

- **On success**, print the per-driver confirmation reflecting the single-paste UX — e.g. `📋 Copied — ⌘V into a fresh session (it's already prefixed with /goal)`; name the actual prefix per driver.
- **On `exit 3` (no tool) or any non-zero exit**, fall back to chat-only, never report a false success, never block the handoff (the driver is still shown in chat), **and name the remedy** — e.g. *"No clipboard tool found — copy the prompt above manually, or `sudo apt install xclip` (or `xsel`) to enable one-key copy."*

## Guardrails

- **Emit-only, forever.** Never run, poll, or re-launch the driver. If you're tempted to loop, stop and hand the prompt to the user.
- **`Bash` is for the clipboard copy only.** The single thing this skill may shell out for is piping the driver to a clipboard tool (see Handoff). Never use `Bash` to run the driver, invoke `/goal`, execute the spec, or touch git/the project — that would break emit-only.
- **Write only `tasks.md`.** The single file this skill may write is a `tasks.md` beside the spec (and only when the **AC groups** don't already partition the work). Show the driver prompt in chat — never write it to disk; never edit the spec or code.
- **Don't re-implement `/goal`.** This skill compiles the spec into `/goal`'s input; `/goal` does the work.
- **The done-condition is `verify-spec`, by composition — for *every* driver.** Wire it into whatever you emit: the `/goal` condition, the `ultracode` workflow's final / per-phase stage, or an explicit `verify-spec` follow-up in the `/batch` brief. Never restate or rebuild its logic here, and never emit a driver whose completion isn't grounded by `verify-spec`.
- **Boundaries are load-bearing.** If the spec lacks them, flag it — an unbounded `/goal` run is where drift happens.
- **The artifact stands alone.** Every emitted driver carries the fixed *Artifact hygiene* rule, so the worker keeps the delivered code/docs/tests free of spec-linkage (`AC-id`s, phase/§ numbers, spec ids, predecessor provenance, build-increment framing), free of **spec/history-named identifiers**, and free of **background context that doesn't help a maintainer act** — all while preserving the engineering *why*. This is durable and cross-cutting — also promote it to `CLAUDE.md` so it's re-injected every turn. The backstop is `verify-spec`, which runs a report-only spec-linkage hygiene sweep at the done-gate.
