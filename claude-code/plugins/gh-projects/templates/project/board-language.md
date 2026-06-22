# Board language — shared definitions

A one-page shared vocabulary for everyone on the board (devs and PMs alike): what
each field and option means, and the few distinctions worth getting right. The
Project's own field schema is the canonical source of these names; this card
summarizes them so we all speak the same language.

## Work taxonomy — `Type`

- **Feature** — a new user-facing capability.
- **Bug** — a defect in existing behavior.
- **Chore** — maintenance with no user-visible change.
- **Infra** — an infrastructure / config-as-contract change.
- **Epic** — a parent that splits into per-AC-group sub-issues (Sub-issues progress
  rolls them up).

## Triage — three independent axes

- **Size** (`S` / `M` / `L`) — *appetite*: how much effort. Suggested from the
  AC-group count, human-confirmed. `L` is the cap → consider an Epic split.
- **Tier** (`T1` / `T2` / `T3`) — *spec rigor / risk*: how much spec. `T3` needs a
  linked deep spec.
- **Priority** (`P0` / `P1` / `P2` / `P3`) — *urgency*: how soon. Orders the Ready
  queue.

## Lifecycle — `Status`

`Backlog → Ready → In Progress → In Review → On Staging → Done` (monotonic — only an
explicit reopen regresses it).

| Status | Meaning |
|---|---|
| **Backlog** | Captured, not yet organized into a sprint |
| **Ready** | AC-complete and gated; cleared to begin |
| **In Progress** | In development (linked branch pushed) |
| **In Review** | Non-draft PR open |
| **On Staging** | Deployed to staging |
| **Done** | On production |

## Auto Gantt-signals (deterministic, no AI)

| Field | Options | Read it as |
|---|---|---|
| **Schedule health** | On track · At risk · Blocked · Overdue · Done | rolled-up schedule status |
| **Slippage** + **Slippage days** | Not late · 1-2d · 3-5d · 1+wk · 2+wk (+ exact days) | how late past Target |
| **Blast radius** + **Blast count** | Blocks release · Blocks many · Blocks 1 · Blocks none (+ exact count) | how much *this* blocks downstream |
| **Blocked** | Unblocked · Blocked | is *this* held up upstream |
| **Impact level** | Release blocker · High · Medium · Low | intrinsic consequence if late (human call) |
| **Decision needed** | No decision · Move date · Reduce scope · Reassign · Split · Unblock · Defer | the pending PM/CTO move (names the decision owed — not a yes/no) |

## Scheduling + linkage

- **Sprint** — the 2-week iteration (`@current` / `@next`).
- **Start date** / **Target date** — roadmap bar start / deadline.
- **Milestone** — a time/release boundary driving the Roadmap.
- **Parent issue** / **Sub-issues progress** — Epic grouping + its rollup.
- **PM-ID** — the stable `PM-####` id (spec → issue → PR).
- **Spec** — link to the deep spec (full-rigor items).
- **Assignees** — who is doing the work.

## Distinctions worth getting right

- **Size vs Tier vs Priority** — effort vs spec-rigor vs urgency. A one-line change
  can still be high-rigor and top-priority; keep the three independent.
- **Impact level vs Blast radius** — *intrinsic value-if-late* (does it hurt on its
  own) vs *dependency fan-out* (how many other items break). High impact can block
  nothing; a trivial item can be a chokepoint.
- **Blast radius vs Blocked** — what **I** block downstream vs whether **I** am
  blocked upstream. Mirror directions on the same dependency graph; an item can be
  both.
