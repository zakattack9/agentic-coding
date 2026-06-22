# Board vocabulary

Every term the board uses, in one place — what it means, what it is **not**, and
how the workflow acts on it. The field/option **names** here are the exact board
spellings; `templates/project/fields.json` owns those names (and the terse one-line
UI descriptions). This file owns the *fuller* meaning and the judgment a one-liner
can't carry. It does not restate the rules that already have a home — see
`${CLAUDE_PLUGIN_ROOT}/rules/github-fields.md` (field homes + platform discipline),
`${CLAUDE_PLUGIN_ROOT}/rules/tier-rubric.md` (Tier → rigor), and
`${CLAUDE_PLUGIN_ROOT}/rules/ac-rubric.md` (the acceptance-criteria bar).

For the cross-field judgment calls (when to split, Epic vs Milestone, reduce scope
vs move the date, picking a Decision needed option), see
`${CLAUDE_PLUGIN_ROOT}/rules/composition.md`.

---

## Work taxonomy — `Type`

The org-wide Issue Type. Exactly one per issue; it answers *what kind of work is
this*.

- **Feature** — a new user-facing capability. *Not* a fix to something that already
  works, and *not* invisible maintenance. Workflow: usually authored at standard or
  full rigor; ships value a user can see.
- **Bug** — a defect in existing behavior: the thing exists but does the wrong
  thing. *Not* a missing capability (that is a Feature) and *not* a deliberate
  change of intended behavior. Workflow: the AC describe the corrected end-state,
  not the repro.
- **Chore** — maintenance with no user-visible change (dependency bumps, refactors,
  cleanup). *Not* anything a user or stakeholder would notice in the product.
- **Infra** — an infrastructure or config-as-contract change (CI, deploy wiring,
  platform config whose values *are* the contract). *Not* product code. Workflow:
  treated as the full-rigor infra-spec class because the config is the contract.
- **Epic** — a parent that decomposes into per-AC-group sub-issues, with progress
  rolled up via Sub-issues progress. *Not* a date bucket (that is a Milestone) and
  *not* a single deliverable. Workflow: the parent of a split; its sub-issues carry
  the real work and the blocked-by edges.

## Triage / descriptive fields

These three are **orthogonal** appetites — see the disambiguation section below.

- **Size** — appetite, *not* story points. Options `S`, `M`, `L`. Suggested from
  the AC-group count (`1 → S`, `2-3 → M`, `4+ → L`) and human-confirmed. It answers
  *how much effort*. *Not* urgency, *not* risk. `L` is the cap — at `4+` groups,
  consider an Epic split. Workflow: set at intake from the group count.
- **Tier** — spec rigor / risk. Options `T1`, `T2`, `T3`. It is the single rigor
  knob: it picks the authoring rigor and decides whether a linked deep spec is
  required (see `tier-rubric.md`). It answers *how much spec*. *Not* effort, *not*
  urgency.
- **Priority** — urgency. Options `P0` (drop everything), `P1` (next up), `P2`
  (soon), `P3` (eventually). An org Issue Field that orders the Ready queue. It
  answers *how soon*. *Not* intrinsic importance-if-late (that is Impact level) and
  *not* effort. Workflow: set by the PM/lead; orders what gets picked up next.

## Lifecycle — `Status`

The single-select the board automation reads and writes. The lifecycle is
**monotonic**: `Backlog → Ready → In Progress → In Review → On Staging → Done`. A
stale or replayed event never drags an item backward; only an explicit reopen
regresses it.

- **Backlog** — captured, waiting to be organized into a sprint. *Not* committed
  work.
- **Ready** — acceptance-criteria-complete and gated; ready to begin. Set only when
  the AC pass the ready gate (`ac-rubric.md`) — prose-only or non-atomic AC are
  refused Ready.
- **In Progress** — currently in development (a linked branch was pushed).
- **In Review** — a non-draft pull request is open, before staging.
- **On Staging** — deployed to staging.
- **Done** — completed and deployed to production. Items are **never** auto-closed
  by a `Closes #N` PR link; closure happens at prod-deploy time.

## Auto Gantt-signals (deterministic, no AI)

These are recomputed deterministically on events plus a low-frequency cron — pure
date math and dependency-graph traversal, **never** a model call. They are *derived*,
not hand-set (except Impact level and Decision needed, which are deliberate human
calls). They power the live views and the project Status update.

- **Schedule health** — the rolled-up schedule status of one item. Options:
  `On track` (not past Target, not blocking a release), `At risk` (Target within the
  warning window, or a soft slip), `Blocked` (held by an open blocked-by
  dependency), `Overdue` (past Target date and still open), `Done` (shipped to
  prod). Derived; *not* hand-set.
- **Slippage** — bucketed lateness past the Target date. Options: `Not late`,
  `1-2d`, `3-5d`, `1+wk`, `2+wk`. *Not* an exact count — that is the next field.
- **Slippage days** — the exact whole number of days past Target (`0` when not
  late). The numeric companion to Slippage; unlocks sums/averages and numeric sort.
- **Blast radius** — how much *this* item blocks **downstream** work. Options:
  `Blocks release` (on the critical path to a release), `Blocks many` (two or more
  downstream items), `Blocks 1` (exactly one), `Blocks none`. Derived from the
  native blocked-by graph. *Not* a measure of whether *this* item is itself blocked
  (that is Blocked) and *not* a measure of intrinsic value (that is Impact level).
- **Blast count** — the exact number of distinct downstream items transitively
  blocked. The numeric companion to Blast radius.
- **Blocked** — does an open blocked-by dependency hold *this* item up? Options:
  `Unblocked`, `Blocked`. Derived from the native blocked-by edges. It is the
  **upstream** question (am I held up), the mirror of Blast radius's downstream
  question. *Not* hand-set.
- **Impact level** — a deliberate human call on the **intrinsic** consequence if
  this item is late, independent of what it blocks. Options: `Release blocker`
  (a release cannot ship without it), `High`, `Medium`, `Low`. *Not* derived, and
  *not* dependency fan-out (that is Blast radius).
- **Decision needed** — a single-select naming the **pending decision owed** on a
  stuck item — *what move the PM/CTO must make*. It is explicitly **not a boolean**:
  it names the decision, not merely that one exists. Options: `No decision` (none pending),
  `Move date`, `Reduce scope`, `Reassign`, `Split`, `Unblock`, `Defer`. A deliberate
  human call. *Not* a dependency flag (that is Blocked) and *not* an effort
  estimate (that is Size). See `composition.md` for picking the right option.

## Scheduling + linkage fields

- **Sprint** — the 2-week iteration an item is planned into; filter with
  `@current` / `@next` / `@previous`.
- **Start date** — the roadmap bar start (an org Issue Field).
- **Target date** — the deadline; feeds Schedule health and Slippage (an org Issue
  Field). *Not* a hard promise on its own — its weight depends on Blast radius and
  Impact level when a slip forces a Move-date-vs-reduce-scope call.
- **Milestone** — a time/release boundary that drives the Roadmap. A date bucket
  that holds many issues. Orthogonal to an Epic (a work structure) — see
  `composition.md`.
- **Parent issue** — the Epic-grouping link that feeds the Sub-issues progress
  rollup.
- **Sub-issues progress** — the native percent-complete rollup of an Epic's
  sub-issues.
- **PM-ID** — the stable `PM-####` identifier threading spec → issue → PR.
- **Spec** — the link to the full deep spec (present for the full-rigor tier; empty
  otherwise).
- **Assignees** — the people doing the work (the native field).

## Staging lifecycle terms (draft area, not board fields)

The local intake staging area holds **drafts** before they become canonical board
issues. These terms describe a draft's lifecycle in that staging area; they are
**not** `fields.json` fields and never describe a promoted (canonical) issue.

- **stub** — a freshly captured draft: an item exists in staging but has no authored
  body or acceptance criteria yet.
- **drafting** — a stub whose body and AC are being authored / refined.
- **ready** — a draft that has passed the AC bar locally and is cleared to promote.
  (Distinct from the board `Ready` Status — this is a *draft* being cleared to
  promote, not an issue's lifecycle stage.)
- **promoted** — the draft has been created as a real board issue. Promotion is
  one-way: once promoted, the draft is canonical and the staging area never mutates
  it.

---

## Orthogonal-axis disambiguation

The most-confused pairs. Each pair measures a **different axis** — they are
independent, and an item can sit anywhere on each.

### `Size` vs `Tier` vs `Priority` — three independent appetites

| Field | Axis | Question |
|---|---|---|
| **Size** (`S`/`M`/`L`) | appetite | *how much effort* |
| **Tier** (`T1`/`T2`/`T3`) | spec rigor / risk | *how much spec* |
| **Priority** (`P0`–`P3`) | urgency | *how soon* |

A one-line `S` change can still be `T3` (risky, needs grounding) and `P0` (drop
everything). A large `L` epic can be `T1`-ish per sub-issue and `P3` (eventually).
Never let one stand in for another.

### `Impact level` vs `Blast radius` — value vs fan-out

- **Impact level** is the **intrinsic** value-if-late: *does it hurt on its own*,
  regardless of what depends on it. A `Release blocker` hurts even if nothing else
  is waiting on it.
- **Blast radius** is **dependency fan-out**: *how many other items break* if this
  one slips. `Blocks many` says lots of downstream work stalls — but each of those
  could be low-impact.

An item can be high Impact level and `Blocks none` (it matters, but nothing waits
on it), or low Impact level and `Blocks many` (trivial in itself, but a chokepoint).

### `Blast radius` vs `Blocked` — downstream vs upstream

- **Blast radius** is what **I** block **downstream** — items waiting on me.
- **Blocked** is whether **I** am blocked **upstream** — items I am waiting on.

They are mirror directions on the same dependency graph. An item can be `Blocked`
(waiting on something) and simultaneously `Blocks many` (others wait on it) — a
blocked chokepoint, the most urgent thing to unblock.
