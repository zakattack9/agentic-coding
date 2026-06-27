---
name: orchestrate-spec
description: Run the whole spec workflow — write → refine → launch → build → verify — end-to-end in ONE session, so you never hand-run each spec-ops skill yourself. Use when the user says "take this idea all the way to a verified implementation", "orchestrate the spec", "drive the whole spec pipeline", "go from spec to shipped", "do the full write/refine/launch/build/verify run", or hands over an idea / draft / ready spec and wants it carried to a code-grounded done. It COMPOSES the existing skills (it never reimplements them) and delegates the heavy autonomous stages to fresh-context subagents/workflows while keeping every user question in the main session. It is NOT for a single stage — to only draft use write-spec, only harden use refine-spec, only compile a driver use launch-spec, only check reality use verify-spec; this skill chains all of them.
argument-hint: [@path/to/spec.md or a bare idea] [from:<write|refine|launch|build|verify>] [to:<…>]
model: opus
effort: xhigh
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Bash, Task, Skill, Workflow, AskUserQuestion
hooks:
  Stop:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/skills/orchestrate-spec/stop_orchestrate_spec.py"
---

# Orchestrate Spec

Fifth spec-ops skill. The other four are run **by hand, one at a time**, each piling onto one growing context: `write-spec` → `refine-spec` → `launch-spec` → the emitted driver → `verify-spec`. This skill drives all five from **one main session**, delegating the heavy stages to fresh contexts and keeping only the **interaction + control flow** in the main session — so a bare idea reaches a **code-grounded, verified implementation in a single run**.

**It composes; it never reimplements.** Every stage calls the *real* spec-ops skill (`write-spec`, `refine-spec`, `launch-spec`, `verify-spec`); this skill only sequences them, owns the user conversation, and drives the deterministic side-effects. `launch-spec` stays **emit-only** — you run its emitted brief via the Workflow tool, never `launch-spec` itself.

Arguments: $ARGUMENTS

## Inputs

- **Spec or idea** — a `@`-path to an existing spec/draft, or a bare idea to start from. If a bare idea, the **write** stage (discovery + draft) produces and names the file.
- **from / to range** — optional `from:<stage>` / `to:<stage>` over `write · refine · launch · build · verify`. Default `from:write to:verify`. The user may **enter later** (e.g. `from:launch` against an already-ready spec) and/or **stop early** (e.g. `to:refine` to finish at a ready spec); only stages in range run. `from:verify to:verify` is a **verify-only** run against an existing implementation. If the range is ambiguous, ask with `AskUserQuestion`.

## The pipeline is a state machine — not prose

Control flow lives in the **state engine** (`scripts/spec_orchestrator.py`) and is enforced by a **skill-scoped `Stop` hook** (`stop_orchestrate_spec.py`), never in this document or the conversation. The engine owns a **session-keyed state file** at `/tmp/claude-orchestrate-spec-${CLAUDE_SESSION_ID}.json` recording the ordered stages, each stage's status, the spec path, the from/to range, the next action, and an abort flag. The hook re-reads it on every attempted turn-end and **blocks until the next in-range stage's artifact actually exists**, so you cannot stop mid-pipeline.

The stages run **in order, each beginning only after the previous stage's artifact exists** — order is enforced from artifacts, not assumed:

| Stage | Runs where | Invoked via | Completeness **artifact** | Side-effect **you** call from main |
|---|---|---|---|---|
| **write** (discovery + draft) | **Main** (preserves discovery context) | `write-spec` in-session | committed **draft** spec | `spec_git.py commit` (draft) |
| **refine** | **Subagent** (grounding) ⇄ **Main** (questions) | `Task` → `spec-ops:refine-spec` | committed **ready** spec | `spec_git.py commit` (ready) |
| **launch** | **Main** | `spec-ops:launch-spec` (emit-only) | emitted **driver brief** + driver-type | — |
| **build ⇄ verify** | **Workflow tool** (always) | shape by driver-type; verify is the loop's check | **drift baseline** at HEAD SHA, zero `contradicted` | `drift_baseline.py write` + `spec_amendments.py write` (from the returned ledger) |
| **outer loop** | **Main** | `AskUserQuestion` → back to refine | (human decision) | `spec_amendments.py` ingest on re-refine |

### Initialize the state, then resolve ONE canonical spec path

As soon as you know the spec's path (from args, or right after the **write** stage names the file), initialize the run. The engine canonicalizes the path (symlinks resolved once) and stores it as `state.spec` — **read that value back and pass it to every script** so the per-tool `/tmp` keys stay self-consistent:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_orchestrator.py" init <spec-path> <from> <to>   # writes the state file
CANON=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_orchestrator.py" status | python3 -c 'import json,sys;print(json.load(sys.stdin)["spec"])')
```

Use `$CANON` for **all** later calls (`spec_git.py`, `drift_baseline.py`, `spec_amendments.py`). The engine reads `${CLAUDE_SESSION_ID}` from the environment; pass it explicitly as the trailing arg if a call ever can't see it.

Drive the run with these verbs (the hook mirrors `check` against artifact ground truth):

| Verb | Use |
|---|---|
| `init <spec> <from> <to>` | start a run (or resume an active same-session one) |
| `check` | what's the next in-range stage? (`next:<stage>` exit 10 · `complete` 0 · `aborted` 11) |
| `advance <stage>` | mark a stage done **after** its side-effect landed |
| `abort` | the user explicitly stopped the run — releases the `Stop` gate |
| `status` | print the state JSON |

## Stage gates & the human-confirmed outer loop

**At every stage transition, surface the stage's result and a `proceed / adjust / abort` gate** before continuing — one `AskUserQuestion` round. `adjust` loops the current stage with the user's steer; `abort` ends the run (below).

After **build ⇄ verify**, surface the verify findings **and any proposed amendments**, and **ask before looping back to refine** — the outer verify→refine loop is **human-confirmed, never automatic**. On a confirmed loop: re-arm a fresh refine→verify pass by re-initializing the range (a *completed* run is replaced, per resume rules), then re-enter **refine ingesting the verify→refine amendments**, and re-run the downstream stages:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_orchestrator.py" init "$CANON" refine verify   # re-arm refine→verify
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_amendments.py" load "$CANON"                    # the backward-sweep proposed ACs
```

`refine-spec` already ingests that `/tmp` handoff at the start of its run and clears it once dispositioned — you do not re-key anything.

## Main-session vs delegation boundary

**Platform invariant this skill relies on: a subagent cannot call `AskUserQuestion`.** Therefore **all** user interaction — discovery, clarification, driver selection, every stage gate, surfacing findings — happens in the **main session; no subagent ever prompts the user**. The split:

- **Discovery + the initial draft run in the main session** (so discovery context is preserved), invoking `write-spec` in-session.
- **refine-grounding is delegated to a subagent** (`Task` → `spec-ops:refine-spec`) — the parallel, autonomous verification work that needs no live user.
- **build ⇄ verify runs as a Workflow** (below). The Workflow tool is **main-loop-only** — a subagent cannot call it — which is another reason this skill runs in main.

**Batched-question contract.** A delegated stage that hits a decision it cannot make returns a structured result — `{ "status": "blocked", "questions": [ { "q", "options", "recommended" } ] }` — else `{ "status": "ok", "result": … }`. Consume it as **structured data, schema-validated on the fields you depend on**; never treat a subagent's prose as ground truth. On `blocked`, render the questions in **one** `AskUserQuestion` round in the main session, then **re-dispatch the same stage** with the answers appended. Tell every delegated subagent: *return JSON in exactly this schema; do not ask the user; if you need a human decision, return `status:"blocked"` with the questions.*

**Delegated stages invoke the real skills** (`refine-spec`, `verify-spec`) rather than reimplementing their logic — the subagent's job is to *run the skill* and *return its structured result*, not to re-derive it.

**Cross-model judge (Codex) is inherited on the in-session stages, re-wired for the workflow stage.** Delegated **refine** runs as a plain `Task` subagent, so it spawns its own Claude judge + Codex bridge normally — orchestrate adds nothing, and a stubborn Claude/Codex split arrives as the normal `blocked` result above that you disposition in one `AskUserQuestion`, exactly like any other blocked stage. **Build ⇄ verify is different:** it runs as a **Workflow**, and a workflow `agent()` stage **cannot spawn a `Task`**, so a verify stage running there cannot self-dispatch its `spec-verify-judge` `Task` (left alone it silently self-administers the judge — a single-model pass wearing a cross-model badge). The build⇄verify workflow therefore runs the cross-model judge as **explicit sibling stages** (below) — the Codex bridge standalone (`Bash`) and the Claude judge as `agent({ agentType: 'spec-ops:spec-verify-judge' })`. The loop still gates on `contradicted == 0` (below), **not** on verify-spec's cross-model `complete`, so the two judges' `missed` / `weakEvidence` are folded into the ledger (and surfaced with the verify findings) before the count is read — strengthening the gate without letting a split deadlock the autonomous loop.

## Build ⇄ verify — always a Workflow

The build ⇄ verify stage **always executes via the Workflow tool** — the same dynamic-workflow mechanism (`pipeline()` / `parallel()` JS spawning subagents) that `launch-spec`'s `ultracode` driver emits — **never as a main-session `/goal` or `/batch` run**. This skill's own instruction to use it satisfies the Workflow tool's opt-in.

`launch-spec` is **emit-only and unchanged**: it still selects among its three drivers and emits a prompt/brief; you **consume that emitted brief as the workflow's build instruction**. The selected **driver-type maps to a workflow shape**:

| `launch-spec` driver | Workflow shape |
|---|---|
| **`/goal`** | a **build ⇄ verify loop**: the emitted build instructions become the loop's **build node**; the loop owns the **single** verify gate. Do **not** also fire the `/goal` driver's own embedded verify gate — that embedded gate is for standalone `/goal` use. |
| **`/batch`** | **`parallel` / `pipeline`** over the batch units, then a `verify-spec` stage as the gate. |
| **`ultracode`** (dynamic workflow) | run its emitted workflow brief **directly** (its final stage is already `verify-spec`). |

**The loop's verify stage invokes `verify-spec` and returns a structured `{ verdict, ledger }`.** The loop **exits when verify reports zero `contradicted` acceptance criteria** — a bar **deliberately stricter than verify-spec's own gate** (which lets `contradicted` findings pass), read from the verdict directly — bounded by a **max-iteration cap (default 3)**. Reaching the cap unconverged returns a structured **`blocked — unconverged`** result the main session surfaces.

**The verify stage runs the cross-model judge as sibling stages — never a nested `Task`.** Because a workflow `agent()` can't spawn a `Task`, shape the loop's verify stage as three steps: **(1)** the verify `agent()` (invoking `verify-spec` via `Skill`) produces the ledger; **(2)** a **Codex-bridge step** runs `codex_bridge.py --kind judge-verify` (`Bash`, standalone — no `Task`; fail-open to a no-op if Codex is absent); **(3)** an **`agent({ agentType: 'spec-ops:spec-verify-judge', schema: judge_verify })`** stage independently audits the ledger. Fold both judges' `missed` / `weakEvidence` into the ledger as additional unverified / `contradicted` entries **before** reading `contradictedCount`, so the cross-model judge strengthens the very count the loop exits on. This is the `references/cross-model-judge.md` "Where `Task`-spawn is unavailable" path — the verify stage never self-administers its own judge.

**The build workflow is autonomous**: it never attempts to ask the user; a genuine spec gap or blocker is returned as a structured **`blocked`** result that you surface in the main session (the loud, human-facing path — the workflow itself just reports).

**The verify stage returns its complete verify ledger** as part of its structured result. The session-keyed verify ledger is deleted on success and can't be read back from `/tmp`, so the workflow **returns the ledger** and you persist it yourself (next section) — materialization never depends on that ledger surviving.

A **verify-only range** (`from:verify`) skips the build loop: run verify as a **single delegated subagent** (`Task` → `spec-ops:verify-spec`) that returns its ledger — same materialize step, no loop.

## Deterministic side effects — driven from main

Drive **every** spec side-effect from the **main session**, so correctness never depends on a skill-scoped hook firing inside a subagent/workflow. A hook double-write is a harmless **idempotent overwrite**; a non-fire is covered by your own call.

- **Commits** — `spec_git.py commit "$CANON" "<msg>"` for the **draft** (after write) and the **ready** spec (after refine). Each commit is **scoped to the spec file only** — the helper does `git add -- <path>` then `git commit --only -- <path>`; **never `git add -A`/`.`, never a push**.
- **Materialize from the returned ledger** — write the workflow's returned verify ledger to a temp file, then emit the persistent artifacts with the additive `write` verbs (they reuse verify-spec's own module functions, so they emit the **identical** artifact the verify `Stop` hook would):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/verify-spec/drift_baseline.py" write "$CANON" <ledger-file>   # baseline: verifiedAtSHA + per-AC verdicts
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_amendments.py"          write "$CANON" <ledger-file>   # verify→refine handoff (backward-sweep findings; clears if none)
```

The drift baseline at the current HEAD with **zero `contradicted`** is exactly the artifact the `Stop` hook reads to confirm **verify** is complete — so once you've materialized it, the gate passes.

## The run, stage by stage

Front-load discovery and questions in main; delegate the heavy work; call the side-effect after each stage; `advance`; surface the gate. Only run stages in `[from, to]`.

1. **write** — Run discovery + draft by invoking `write-spec` (Skill, main session). When it names the spec file, `init` the state and capture `$CANON`. Commit the draft (`spec_git.py commit`), `advance write`, surface the **proceed/adjust/abort** gate.
2. **refine** — On a loop-back, first `spec_amendments.py load "$CANON"` and fold accepted amendments in. Delegate grounding: `Task` → a subagent that invokes `spec-ops:refine-spec` on `$CANON` and returns the schema'd result. Surface any `blocked` questions in one `AskUserQuestion` round and re-dispatch. When ready, commit the ready spec from main (`spec_git.py commit`), `advance refine`, gate.
3. **launch** — Invoke `spec-ops:launch-spec` (Skill, main, emit-only). Capture the emitted **driver brief + driver-type**. `advance launch`, gate.
4. **build ⇄ verify** — Run the **Workflow tool** with the shape mapped from the driver-type; loop build→verify to **zero contradicted** (cap 3). On the workflow's return, persist the ledger and run the two `write` verbs (above). `advance build`; the verify artifact now exists, so `advance verify`. Surface verify findings + amendments and **ask before any outer loop**.
5. **done / loop** — If `check` reports `complete`, hand off. If the user confirms an outer loop, re-arm `refine verify` and return to step 2.

## Resume & abort

- **Same-session resume.** Re-invoking `orchestrate-spec` in the same session **continues at the first incomplete in-range stage** — stages whose artifacts already exist are skipped (their status persists as done). A state file from a **completed or aborted** run — or for a different spec — is **not resumed; it is replaced** by a fresh run. `init` handles this; just call it.
- **Abort.** When the user explicitly stops the run, set the flag — `spec_orchestrator.py abort` — and the `Stop` hook then allows the turn to end. The hook also has a **loud fallback** (after a bounded number of no-progress blocks on one stage it surfaces the stall and releases) and **fails open** when it can't tell a run is active, so a run can never hard-trap the session. If the user redirects to unrelated work, `abort` and move on.

## Handoff

When `check` reports `complete`, give a short summary: the spec's journey (draft → ready → built → verified), the final per-AC verify verdict (zero `contradicted`), and any backward-sweep amendments carried for a future refine. State plainly that the implementation is **verified against the spec at HEAD**. The state file is left `complete` (a later same-session re-invocation starts fresh).

## Guardrails

- **Compose, never reimplement.** Always call the real `write-spec` / `refine-spec` / `launch-spec` / `verify-spec`. Never inline their logic, and never change their behavior — `launch-spec` stays emit-only.
- **You own every user question.** No subagent or workflow ever prompts the user; a delegated stage returns `blocked` + questions and you ask in main.
- **Build ⇄ verify is always a Workflow** — never a literal `/goal`/`/batch` in the main session — and exits only on **zero contradicted**.
- **Side-effects from main, scoped, never pushed.** Commit only the spec file via `spec_git.py`; materialize baseline + amendments via the `write` verbs from the returned ledger. Never `git add -A`, never push, never depend on a subagent's hook firing.
- **State lives in git + the spec + the state file — not the conversation.** If you compact or restart, re-read the spec and `git log`, then `init` to resume from committed state.
