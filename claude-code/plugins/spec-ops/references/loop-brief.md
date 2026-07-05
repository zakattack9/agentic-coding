# The loop-spec brief — fill-in skeleton

`loop-spec` emits this brief, filled from the target spec, as the driver a fresh session runs
to converge the spec. Copy it verbatim, replacing every `«…»` placeholder with spec-derived
content; **drop** a placeholder's line entirely if it doesn't apply (never emit a literal
`«…»`). Everything not in `«…»` is fixed — keep it as-is so the materiality bar, the loop, the
Codex-concurrency rule, and the convergence rule stay intact.

Placeholders you fill (all derived by the skill before emitting — see `SKILL.md`):
- `«SPEC_PATH»`, `«BRANCH»` — the target spec and its branch.
- `«CONVERGENCE_GOAL»` — the end state in one clause (e.g. "implementation-ready and, once built
  and tested in staging, safe to promote to prod"; for a pure app/library spec, just
  "implementation-ready — unambiguous and complete enough to build without guessing").
- `«GROUNDING»` — the lean context block: what the spec covers + the key repo files reviewers
  must check spec claims against.
- `«LENSES»` — the 3–5 tailored review lenses (one per risk surface of THIS spec), each a
  `Lens X — <focus>` line; always include an implementability / spec-doc-quality lens.
- `«CONSISTENCY_CHECK»` — the shell check matched to the spec's AC format.
- `«ROUNDS»` — the hard-cap round count (default 6).

**Emit only the brief below the `---` rule.** This header block is guidance for `loop-spec`; it is
NOT part of the driver — the pasted/copied prompt starts at `# TASK:`.

---

# TASK: Drive «SPEC_PATH» to «CONVERGENCE_GOAL»

You are the ORCHESTRATOR. Run a review→fix loop that converges the spec `«SPEC_PATH»` (branch
`«BRANCH»`) to «CONVERGENCE_GOAL». When you finish, an independent fresh review must find nothing
material.

You DISCOVER issues only through FRESH reviewers each round (unbiased, no prior-round context).
You ADJUDICATE, EDIT the spec directly, and DECIDE convergence yourself.

## Hard constraints
- Do NOT run any spec-ops skill (no refine-spec / verify-spec / write-spec / launch-spec). Use
  the Agent tool for reviewers and the `codex:codex-review` agent for the cross-model reviewer.
- Do NOT implement code. The ONLY file you edit is `«SPEC_PATH»`.
- Reviewers get a FRESH read each round: give them only the CURRENT spec + repo, never your
  running notes or prior findings (so they can't anchor). You dedupe on the receiving side.
- Keep your own context lean: reviewers do the heavy reading; you keep only tight finding
  summaries, a FIX-log, and a DECLINE-log.

## Grounding context (put this in EVERY reviewer prompt)
«GROUNDING»
- Reviewers MUST verify spec claims against the ACTUAL repo (code, config, migrations,
  workflows, infra) — the real defects are spec-vs-code mismatches and ambiguities, not prose.

## MATERIALITY BAR (this is what prevents diminishing-return churn — apply it strictly)
A finding is MATERIAL (worth a spec edit) ONLY if it would plausibly cause one of:
- a failed/broken build, deploy, or provision;
- data loss/corruption, or a security/privacy leak;
- an outage / unsafe blast radius / irreversibility with no fail-closed path;
- a genuine AMBIGUITY where two competent engineers would build materially different things;
- an internal CONTRADICTION, a stale claim the code refutes, or a REQUIRED behavior with no
  acceptance criterion (so it can't be implemented or verified).
NOT material (DECLINE, log one line, never edit): wording/style, redundant emphasis, "could add
detail" that doesn't change what gets built, speculative/future scope, defense-in-depth beyond
the stated threat model, or re-litigating an explicitly-accepted trade-off. When unsure whether
a finding changes the implementation or adds risk, it is NOT material — DECLINE it.

## THE LOOP
Repeat rounds until the convergence rule fires:

1. DISPATCH a full parallel sweep — in ONE message, issue ALL of these tool calls together so
   they run concurrently, and wait for all to return before adjudicating:
   - One `Agent` (general-purpose, `run_in_background: false`) per lens below, each told to check
     spec claims against the repo and return ONLY material findings per the bar above.
   - ONE `Agent` of type `codex:codex-review` (also `run_in_background: false`) — the cross-model
     reviewer. Dispatch it IN THE SAME MESSAGE as the Claude lenses so Codex runs concurrently,
     not after them. Hand it a self-contained brief: the target `«SPEC_PATH»`, the Grounding
     block above, "review the whole spec for material issues vs. the repo," the Materiality Bar,
     and the Finding shape below. It returns `{ codexAvailable, findings }`. (Codex runs only when
     this session has the `codex` plugin installed + OpenAI-authenticated and
     `Bash(python3 *codex_bridge.py*)` allowed — in auto mode the bridge is blocked otherwise, so
     Codex reports unavailable every round and the loop is Claude-only until you grant that.)

   Lenses:
   «LENSES»

   Each reviewer prompt must demand, for every finding: **severity**, the **exact AC/section**,
   the concrete **"implementer builds the wrong thing" or "risk"** scenario, **file:line
   evidence** from the repo, and the **precise spec edit** needed. Shared finding shape:
   `{ severity, location (AC-id/§), scenario, evidence (file:line), edit }`. Return channels
   differ by reviewer: a **Claude lens** replies with its findings, or exactly `NO MATERIAL
   FINDINGS` if none; the **`codex:codex-review` agent** instead ALWAYS returns its JSON envelope
   `{ codexAvailable, findings }` (with `findings: []` when nothing material) — never the
   `NO MATERIAL FINDINGS` sentinel.

   Codex is best-effort — NEVER block the loop on it. Treat **any** of these as "Codex unavailable
   this round" and proceed on the Claude lens results alone: `codex:codex-review` returns
   `codexAvailable: false`, **or** the `Agent` call errors / the agent type isn't installed (an
   unknown agent type raises a tool error, not a JSON envelope — count that error as a *completed*
   unavailable Codex result, not something to retry or wait on). Never fabricate a Codex review,
   and never hold the round open for Codex beyond the one concurrent dispatch.

2. ADJUDICATE every returned finding yourself (read the spec + cited code to confirm):
   - FIX: real + material + not already covered → edit the spec now.
   - ALREADY-OK: verify it's genuinely addressed → note, no edit.
   - DECLINE: fails the materiality bar → add to DECLINE-log with a one-line rationale.
   Dedupe across reviewers and against your DECLINE-log (don't re-fix a declined item).

3. EDIT the spec directly for each FIX: add/correct the AC (continue the AC-NN numbering), and
   CORRECT IN PLACE any older claim the fix contradicts (so the doc never self-contradicts).
   After each edit batch, run the consistency check and resolve any failure:
   «CONSISTENCY_CHECK»

4. Record the round: material-fixes count. A round is CLEAN when zero material findings survive
   adjudication (all reviewers effectively NO-MATERIAL after dedupe/decline). **A Codex-unavailable
   round is judged on the Claude lenses alone** — Codex-unavailable is *neutral*: it never fails a
   round and never resets the streak; note the unavailability for the final report.

## CONVERGENCE / TERMINATION
- STOP when TWO CONSECUTIVE rounds are CLEAN — two full fresh sweeps in a row where every
  **available** reviewer produced nothing material. Codex participates when available; when it is
  fail-open unavailable the round is still valid and judged on the Claude lenses, so **Codex never
  blocks convergence** (the final report notes it didn't run). Any material fix resets the streak.
- Hard cap: «ROUNDS» rounds. If you hit it without two clean rounds, STOP and report the residual
  open items rather than looping further.
- The goal is CONVERGENCE to a «CONVERGENCE_GOAL» spec — NOT maximal edits. Bias toward DECLINE
  over speculative additions.

## FINAL REPORT (when you stop)
Output: rounds run + material-fixes per round (should trend to 0,0); the full FIX-log (each edit
+ which AC); the DECLINE-log (consciously-skipped diminishing-return items + rationale); the
final consistency-check result; and an explicit verdict on whether the spec now meets
«CONVERGENCE_GOAL». Do NOT commit — leave the spec edited in the working tree for me to review.
