# verify-spec internals — evidence standard & sweep mechanics

The detailed mechanics behind verify-spec's **step 2**. The skill body carries the summary plus the operative commands; this file holds the full "how", consulted while actually running the verification passes. Nothing here changes the gate — the Stop hook and the independent judge enforce the outcomes.

## Contents
- [Evidence standard — scale grounding to what the claim asserts](#evidence-standard--scale-grounding-to-what-the-claim-asserts)
- [Backward sweep — delivered code that owns no AC](#backward-sweep--delivered-code-that-owns-no-ac)
- [Spec-linkage hygiene sweep — artifact text that points back at the spec](#spec-linkage-hygiene-sweep--artifact-text-that-points-back-at-the-spec)

## Evidence standard — scale grounding to what the claim asserts

The strength of evidence a claim needs is a function of **what it asserts** — infer it from the claim's text, no type tags required. A bare code citation is **not** automatically sufficient:

- A **measurable threshold** ("p95 < 200ms", "≤ 5 retries", "bundle < 500 KB") demands an actual **measurement** — an observed number, a benchmark, a metric read. "The code sets a 200ms timeout" does *not* prove the bound holds → `method: measurement`.
- A **universal invariant** ("no asset is served from the ALB", "every endpoint authenticates", "nothing logs PII") demands an **exhaustive / static check** over the whole surface — a `grep`/AST sweep proving the absence — not one representative citation that happens to comply → `method: exhaustive-check`.
- A plain **behavior** ("clicking X does Y", "route returns Z") grounds against code/git or an exercise of the path → `method: static-read` / `test-run`.
- Keep **read-only CLI observation a first-class method** — an infra AC ("the bucket blocks public access") is verified by `aws … get-public-access-block`, never forced into a test suite → `method: cli-observation`.

This is the real value of "typing" without the formality: it closes the gap where a perf or security constraint gets **rubber-stamped by code-reading**. Record the technique in each claim's `method`; the judge (step 4) flags any whose method falls short of what the assertion demands.

## Backward sweep — delivered code that owns no AC

The claim grounding is the *forward* direction (every claim/`AC-id` has evidence). When the target is a spec with an `## Acceptance Criteria` section, **also run the backward direction**: every substantive change in the implementation diff should map to an owning `AC-id`. A hunk that maps to **none** is the finding this pass exists to surface — scope creep, silent reinterpretation, or a *derived requirement* (a real behavior built with no criterion). The forward judge can't see it, because it re-derives ACs forward and never looks at code with no AC.

- **Diff base.** Sweep the implementation diff. Resolve the base **in this order**: **(1)** an explicit PR / commit range or base sha **handed in** (user / caller) — *that* is the diff, it wins; **(2)** when the target is a **committed spec**, its **defining commit** — `git log -1 --format=%H -- <spec-path>` — which is the pre-implementation anchor (the spec is committed *ready* by `refine-spec` before implementation, and the implementation never touches the spec file), durable across compaction, a pushed trunk, and any number of commits, and computed by `verify-spec` itself from the spec path it already holds; **(3)** otherwise diff the working branch against its merge-base with the trunk — `git merge-base HEAD main` then `git diff <base>..HEAD`; when you are **on** the trunk, diff against the upstream instead (`git diff origin/main..HEAD` — the unpushed commits). Record the base used in `backwardSweep.base`. If none resolves (e.g. the spec is uncommitted *and* the heuristics come up empty): on **direct human invocation**, ask with `AskUserQuestion`; running **autonomously as the `/goal` done-gate**, set `backwardSweep.skippedReason` and proceed — **never block on it**. The spec-pin base (2) may **over-include** commits landed between spec-ready and implementation-start — that is **safe**: they surface as unmapped hunks and get triaged out-of-scope, never a wrong verdict (the sweep is report-only). The spec-pin anchor is why the autonomous done-gate's sweeps stay reliable even on an already-pushed trunk, where the heuristics yield an empty diff.
- **Substantive only — noise filter.** A finding must be a **behavior-bearing** hunk with no owning AC: new behavior, a branch, an endpoint, a handler, persisted state, an external call, or a user-observable change. **Allowlist — never a finding:** refactors, formatting, tests, CI, config churn, and docs. For a manifest, **split by field** — `description` / `version` edits are docs (allowlist); `dependency` / `entrypoint` / `script` / `permission` edits are substantive. Docs or config that an AC *explicitly governs* (e.g. an AC "the README documents X") are **not** a backward finding — that artifact's coverage is a *forward* concern, checked as its own claim.
- **Report, propose, triage — never act.** For each unmapped substantive hunk, add an entry to `backwardSweep.findings` with its `evidence`, propose candidate AC text (`proposedAC`), and triage `disposition`: `intended` (→ "add this AC and re-run `refine-spec`") vs `unintended` (→ "remove or justify") vs `unsure`. This is **always a non-blocking report** — it never holds the gate, you **edit nothing**, and you never auto-reopen `refine-spec`. On direct human invocation you *may* use `AskUserQuestion` to confirm an ambiguous intent, but **never as a gate dependency** (the autonomous done-gate has no human to ask).

## Spec-linkage hygiene sweep — artifact text that points back at the spec

The spec is **build scaffolding**, not part of the product: a future reader of the shipped artifact should never be pointed back at the spec that produced it. This sweep is the inverse of grounding — it flags delivered code, docs, comments, tests, and generated output that still **reference the build spec**: `AC-id`s, build-phase / §-section numbers, spec ids or filenames, predecessor-component provenance ("salvaged from X"), or "newly / now / previously" build-increment framing. It is the companion to the backward sweep and runs only for a spec implementation.

Run the **deterministic detector** over the implementation diff (the same base the backward sweep used) and record what it finds:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_linkage_scan.py" --json --diff <base>
```

It encodes the **keep-vs-strip guards** so genuine rationale survives — an artifact's *own* legitimate structure (a two-phase protocol's "Phase 1 / Phase 2", a runbook's section numbering), in-repo `constraint #N` cross-refs, a real in-tree dependency callout, and a template / issue file's `AC-1` / `AC-N` placeholders are **not** flagged. Each finding carries a `patternType`, the offending `snippet`, and a `suggested` rewrite that drops only the linkage. Write them into `specLinkageSweep.findings` (set `ran` true; an empty diff or a spec-clean artifact is `ran` true, `findings: []`).

**The detector is the deterministic *first* pass — it catches the greppable tokens, not everything.** Two leakage classes need *judgment*, so also read the diff for them: **(a) identifiers** — a function / variable / class / test named after the spec, a build phase, or a predecessor rather than after **what it does** (`AC34_Foo`, `spec07_fields`, `legacy_dispatch`, `phase1_handler`); and **(b) background** — a comment or docstring carrying context that doesn't help a future maintainer *act*: what the code *used to be*, alternatives *considered and rejected*, how the *build was phased*, where the code was *salvaged from*. The line to hold is the same one the artifact should: **keep load-bearing rationale** (why this design, what breaks if it changes) — that earns its place — and flag only the inert history. Record these in `specLinkageSweep.findings` too, with `patternType` `identifier` or `background`. The independent judge attests this **judgment pass** ran, not merely the detector.

This is **report-only**, exactly like the backward sweep: it never blocks the gate, you **edit nothing**, and you never auto-fix the artifact. Surface it in the handoff so the user — or the next `refine` / cleanup pass — can strip the leakage while preserving the *why*. (The detector is also a standalone linter: `spec_linkage_scan.py <path>` cleans an already-shipped artifact.)
