# Insights chart playbook

GitHub **Insights is free on all plans**. It is **read-only, UI-only, zero API** —
charts can be **neither created nor read** programmatically. So the charts are **built
by hand once** on the golden-template Project and **replicate via `copyProjectV2`** —
though GitHub documents only *fields + views* as carried by a copy, so **verify the
charts on each copy and rebuild any that didn't carry** (`scaffold-repo` can't see
them). **Chart history accrues per project from its own start, is never backfilled, and
is never copied** → define Status + Sprint day one and don't archive in-flight items.

## What the chart UI can and can't do (the rules that decide each chart)

A chart's **mode** + a **field's value type** decide what's allowed:

- **Current chart** (snapshot of the project now): set **X-axis** to a field,
  **optionally Group by** another field (stacking), and set **Y-axis** to a count of
  items *or* the **sum / average / min / max of a number field**.
- **Historical chart** (state over time): set **X-axis to "Time."** It tracks the
  built-in item states — Open / Completed / Closed-PR / Not-planned — over time.
  **There is NO custom Group-by on a historical chart** (Group-by is a *current*-chart
  option), so you **cannot** stack a time series by Status, Blast radius, etc.
- **X-axis / Group-by need a *categorical* field:** single-select, iteration,
  milestone, assignees, labels. A **number** field isn't categorical → it belongs on
  the **Y-axis** (sum/avg/min/max). Text/date fields don't chart as categories.
- **`Type` (issue type)** as an X-axis / Group-by is **unverified** — issue-type is a
  special field (it can't be a view column, for instance). Confirm it in the UI; if a
  chart rejects it, swap to a single-select.
- **Filters:** use `has:FIELD` for "has any value" — `FIELD:*` is rejected (same as in
  view filters).

## The charts

`✓` = creatable as written · `⚠️` = verify the flagged field in the UI once.

| # | Chart | Mode · config | Filter | | Audience |
|---|---|---|---|---|---|
| 1 | **Sprint burn-up** | historical · X=Time · Y=count | `sprint:@current` | ✓ | devs+PM |
| 2 | **Throughput** | current column · X=Sprint · Y=count | `status:Done` | ✓ | PM+founder |
| 3 | **Status distribution** | current column · X=Status · Y=count | `is:open` | ✓ | standups |
| 4 | **Work mix by Size × Tier** | current stacked column · X=Size · Group=Tier | `is:open` | ✓ | PM+lead |
| 5 | **Schedule-health distribution** | current column · X=Schedule health · Y=count | `is:open` | ✓ | standups+founder |
| 6 | **Blocked trend** | historical · X=Time · Y=count | `blocked:yes is:open` | ✓ | lead+PM |
| 7 | **Release / Milestone progress** | current stacked column · X=Milestone · Group=Status | `has:milestone` | ✓ | stakeholders |
| 8 | **Slippage-days sum** | current column · X=Schedule health · Y=**sum(Slippage-days)** | `is:open` | ✓ | PM — quantified lateness |
| 9 | **Work mix by Type** | current column · X=Type · Y=count | `is:open` | ⚠️ X=Type | PM+founder |

## What changed from the first draft (and why)

- **Cut "Cumulative flow"** (X=Time, Group=Status) and **"Blocked over time"** (X=Time,
  Group=Blast radius): a historical chart has **no custom group-by**, so neither
  stack-over-time can be built. Replaced by **Status distribution** (#3 — a current
  snapshot by Status) and **Blocked trend** (#6 — a historical *count* of blocked items,
  no group).
- **Work mix by Size** now groups by **Tier** (both single-select) instead of `Type`,
  to avoid the issue-type group-by risk.
- **Release / Milestone progress** filter fixed: `milestone:*` → **`has:milestone`**.
- **Work mix by Type** (#9) is kept but **flagged**: confirm `Type` is accepted as an
  X-axis. If it's rejected, **cut it** — Size × Tier (#4) already covers the work-mix
  need. (If `Type` *is* accepted, it's a nice one-glance feature/bug/chore split.)

## Post-scaffold human checklist

- [ ] **Confirm the charts are present** on the copied Project (Insights has no API).
- [ ] **Verify chart #9** (X=`Type`) builds in the UI; cut it if `Type` is rejected.
