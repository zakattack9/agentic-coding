# Engineering-quality bar + leave-it-better principle

The spec pipeline defaults to a **minimal footprint** and actively **cuts over-engineering**
(`no_overengineering` / `no_bloat`, `write-spec`'s "nothing more", `launch-spec`'s Boundaries).
That guards against *too much*. This reference adds the **symmetric** half — the engineering-quality
dimension and the **leave-it-better** principle — so a change also isn't allowed to ship *too little
quality*: new and updated code should leave the touched codebase in a **better state**, not pile a
new pattern onto a poor existing one until debt compounds.

It is **single-sourced here** and pointed at by `write-spec`, `refine-spec` (+ `spec-refine-judge`),
`launch-spec` / `orchestrate-spec`, `verify-spec` (+ `spec-verify-judge`), and `loop-spec`. It is a
**bar, never a construction plan** — the implementer still owns the HOW.

## The verticals — a change-scaled checklist

For the surface **this change touches**, consider each vertical; promote it to a discrete,
testable **AC only where the change *materially implies* it**. Do **not** invent requirements the
change doesn't need — that is the over-engineering the pipeline already cuts. Depth scales to the
change: a one-line fix needs no perf AC; a new endpoint touching auth and a hot query needs both.

- **Architecture / fit** — the change belongs where it's going and fits existing module boundaries
  and conventions, rather than bolting on a parallel structure.
- **Code design** — naming, cohesion, DRY, clear interfaces, readability (the bar the implementer
  builds to — not a symbol-by-symbol plan).
- **Security** — authz, input validation, secrets, injection, least-privilege on the touched paths.
- **Performance** — the hot paths the change adds or touches; a measurable bound where one matters.
- **Scalability** — behavior as data / load grows (N+1s, unbounded growth, pagination).
- **Maintainability / testability** — tests for the new behavior; docs where the intent is non-obvious.
- **Error handling / resilience** — the failure modes the change introduces; fail-closed where it matters.
- **Observability** — logging / metrics where operating the change requires them.
- **Backward-compat / migration** — data and API compatibility; migration safety and ordering.

A materially-implied vertical with **no AC** is a coverage gap (this is the existing "unstated
non-functional constraint" rule — performance / security / idempotency / limits / concurrency —
**broadened** to the full list).

## The leave-it-better principle

New or updated code should leave the touched surface **no worse, and ideally better**. Concretely:
when the change would otherwise **extend, copy, or build on top of an existing poor pattern**, prefer
a **bounded refactor** of that pattern over piling a new one on top of it. A change that only ever
adds atop known-bad code is how a codebase compounds into an unmaintainable state.

## The warranted-refactor test (the guardrail)

A surrounding refactor is **in-scope for the spec ONLY when ALL three hold** — this is what keeps
leave-it-better from becoming a scope-creep / gold-plating license:

- **(a) Within the original objective** — it serves the spec's stated goal; it is not a new goal
  wearing a refactor's clothes.
- **(b) Entrenchment-avoiding** — the change would otherwise build on / extend a concrete existing
  poor pattern, and doing so would compound a **real, nameable** debt (not "could be cleaner").
- **(c) Bounded & proportionate** — a contained, reviewable change whose blast radius fits the
  spec's footprint; **not** a redesign or rewrite.

**When any of (a)(b)(c) is in doubt, it is NOT warranted — leave it** (mirror the materiality bar's
"when unsure, cut"). An unwarranted expansion is still over-engineering and is still cut. The point
is a *disciplined* better-state, not maximal edits.

## Rigor — an observable quality AC fits any tier; a refactor AC is full-rigor only

The pipeline keeps **light / standard** specs **code-free** — the implementer owns the HOW; only
**full** rigor (and config-as-contract specs) may pin internal code, the same invariant
`write-spec` / `refine-spec` already enforce. The quality dimension respects that split:

- A vertical stated as an **observable outcome** — a perf bound ("p95 < 200 ms"), "input is
  validated", "the operation is idempotent", "it fails closed" — is **behavior**, and is a fine AC
  at **any** rigor.
- A **bounded-refactor** AC — "consolidate helper X", "replace pattern Y with Z" — is
  **code-structural HOW**. It belongs only to **full-rigor / code-naming** specs. At **light /
  standard**, do **not** promote a refactor AC: capture the leave-it-better intent as the
  **observable outcome** it protects, or note it as an appetite for a full pass — never as a
  code-structural instruction the tier forbids.

So the debt-perpetuation check and the leave-it-better AC apply **fully at full rigor**; at
light / standard they **narrow to the observable-outcome form**. This mirrors the infra-at-light guard.

## Reconciliation with the existing gates (so they don't fight)

- **vs `no_overengineering` / `no_bloat`** — those cut **unwarranted** scope. A refactor that passes
  the warranted test is **not** gold-plating and must **not** be reflexively cut. Complementary: cut
  what fails the test, keep (and capture) what passes.
- **vs Boundaries** — Boundaries fence the **outer** limit (what the change must not touch).
  Leave-it-better operates **inside** the allowed surface and never crosses a boundary on its own. A
  warranted refactor that *would* cross a boundary is a **spec-scope question for the author**, not a
  silent expansion.
- **vs "Refine, don't redesign"** — a warranted refactor is **bounded and captured as an AC**, never
  a unilateral rearchitecture. A change that genuinely needs a redesign is **raised as a question**,
  not performed.

## Where it is captured and checked (the flow)

- **`write-spec`** — elicits the change's quality / NFR intent and the **leave-it-better appetite**
  (code-blind: the *desired* end state, not a survey of current code — that grounding is refine's job).
- **`refine-spec` + `spec-refine-judge`** — grounds it against the codebase: promotes each
  materially-implied vertical to an AC, and when the change would entrench a poor pattern, proposes a
  **bounded refactor AC**. The judge flags a missing materially-implied vertical or an un-scoped
  warranted refactor as a `Gap` (severity-tiered — `CRITICAL` only when it ships materially worse code
  *within the objective*; sub-blocking → `WARNING`), reusing the existing `ac_complete` gate.
- **`launch-spec` / `orchestrate-spec`** — the emitted implement driver carries an *Engineering
  quality + leave-it-better* instruction (inside Boundaries): build to the bar; refactor a poor
  pattern rather than pile on; leave the touched surface no worse.
- **`verify-spec` + `spec-verify-judge`** — **report-only**: a refactor / quality AC is verified as a
  forward claim; code that entrenched a poor pattern or left the surface worse is surfaced, never
  hard-gated (verify is read-only).
- **`loop-spec`** — a code-quality / architecture-fit lens, and the loop's materiality bar counts a
  warranted-refactor omission as material.
