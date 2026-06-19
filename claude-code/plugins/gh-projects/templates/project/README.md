# Project board — legend

This Project is the **canonical board** for the org's whole software lifecycle. It is
**org-owned and spans every repo** (the 50k-item cap binds, not a repo count). It was
stood up by `gh-projects:scaffold-repo` via `copyProjectV2` from the org **golden
template** — fields, the 8 views, and the 3 Insights charts all came from that copy
(chart *history* accrues per project from day one and is never backfilled).

## Status lifecycle (the automation key)

`Backlog → Ready → In Progress → In Review → On Staging → Done`

| Status | Meaning | Who/what sets it |
|---|---|---|
| **Backlog** | Captured, not committed | Built-in "item added" |
| **Ready** | AC-complete, gated | Lead (manual) |
| **In Progress** | Linked branch pushed | `board-sync` (push) / built-in reopen |
| **In Review** | Non-draft PR open | `board-sync` (pull_request) |
| **On Staging** | Merged + on staging | Built-in (PR merged) / `board-status` (staging deploy) |
| **Done** | On prod, closed, Release cut | `board-status` (prod deploy) |

Status is **monotonic**: a stale or replayed event never drags an item backward
(`In Progress` < `In Review` < `On Staging` < `Done`); only an explicit **reopen**
regresses it. Items are **never auto-closed by `Closes #N`** — `board-status` closes
them at prod.

## Fields

- **Type** (Issue Type): `Feature / Bug / Chore / Infra / Epic`.
- **Size**: `S / M / L` appetite — suggested from the AC-group count, human-confirmed.
- **Tier**: `T1 / T2 / T3` — drives `write-spec` rigor; T3 needs a linked deep spec.
- **Sprint**: 2-week iteration; filter `@current`.
- **Parent issue / PM-ID / Spec**: epic grouping, stable `PM-####` id, deep-spec URL.
- **Blocked** *(auto)*: `Blocked/Unblocked`, derived from native blocked-by edges by `lib/dag`.
- **Priority / Start date / Target date** (org Issue Fields): ordering + roadmap dates.

### Gantt-signal fields (power the live views + the Status update)

| Field | Maintained by | Read it as |
|---|---|---|
| **Schedule health** | auto | On track / At risk / Blocked / Overdue / Done |
| **Slippage** + **Slippage days** | auto | bucket + exact days past Target |
| **Blast radius** + **Blast count** | auto (`lib/dag`) | how much / how many it blocks |
| **Impact level** | human | Low / Medium / High / Release blocker |
| **Decision needed** | human | the PM/lead's next move |

All **auto** signals are recomputed **deterministically (no AI)** by `signals-sync` on
events + a low-frequency cron, which also posts the project **Status update**.

## Surfaces

- **8 saved views** — see `views.md` (devs / lead / standup / PM / stakeholders).
- **3 Insights charts** — see `insights.md` (live numeric trends; UI-only, no API).

> Insights has **no API**: `scaffold-repo` can neither create nor verify charts —
> after scaffolding, **confirm the 3 charts are present** on this board by hand.
