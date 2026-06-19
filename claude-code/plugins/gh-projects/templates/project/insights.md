# Insights chart playbook

GitHub **Insights is free on all plans**. It is **read-only, UI-only, zero API** —
charts can be **neither created nor read** programmatically. So the charts are **built
by hand once** on the golden-template Project and **replicate via `copyProjectV2`** —
though GitHub documents only *fields + views* as carried by a copy, so **verify the
charts on each copy and rebuild any that didn't carry** (`scaffold-repo` can't see
them). **Chart history accrues per project from its own start, is never backfilled, and
is never copied** → define Status + Sprint day one and don't archive in-flight items.

**Just three charts.** Everything a snapshot chart would show — the spread of Status,
Schedule health, Blocked, or work mix — the **Views already convey at a glance**, so a
chart for it is redundant. These three earn their place by showing what a *view* can't:
a **trend**, a **rollup**, and a **quantified total**.

## What the chart UI can and can't do (the rules behind each chart)

A chart's **mode** + a **field's value type** decide what's allowed:

- **Current chart** (snapshot of the project now): set **X-axis** to a field,
  **optionally Group by** another field (stacking), and set **Y-axis** to a count of
  items *or* the **sum / average / min / max of a number field**.
- **Historical chart** (state over time): set **X-axis to "Time."** It tracks the
  built-in item states — Open / Completed / Closed-PR / Not-planned — over time.
  **There is NO custom Group-by on a historical chart.**
- **X-axis / Group-by need a *categorical* field:** single-select, iteration,
  milestone, assignees, labels. A **number** field isn't categorical → it belongs on
  the **Y-axis** (sum/avg/min/max). Text/date fields don't chart as categories.
- **Filters:** use `has:FIELD` for "has any value" — `FIELD:*` is rejected.

## The charts

All three are creatable as written (no special-field caveats).

| # | Chart | Mode · config | Filter | Audience — what it shows |
|---|---|---|---|---|
| 1 | **Throughput** | current column · X=Sprint · Y=count of items | `status:Done` | PM+founder — items shipped per sprint (the trend no view shows) |
| 2 | **Milestone progress** | current **stacked** column · X=Milestone · Group by=Status | `has:milestone` | stakeholders — each milestone's done/in-flight split |
| 3 | **Slippage days sum** | current column · X=Schedule health · **Y-axis = Sum of a field → `Slippage days`** | `is:open` | PM — total quantified lateness |

**Slippage days sum — exact Y-axis setup:** in the chart config, set the **Y-axis**
dropdown to **"Sum of a field,"** then set the **field** to **`Slippage days`** (the
auto number field). Leave **X = Schedule health** so the total lateness lands in the
At risk / Overdue buckets — or swap X to **Milestone** / **Sprint** if you'd rather see
*which release or sprint* is slipping most.

## Why only these three (the rest are covered by the Views)

- **Status / Schedule-health / Blocked / work-mix distributions** are already the daily
  **Sprint / Triage / Blockers / Grooming** views — a snapshot chart just duplicates them.
- **Throughput** stays: no view shows a per-sprint *shipped trend*.
- **Milestone progress** stays: no view rolls items up *by milestone* with a done split
  (Roadmap shows dates, not completion).
- **Slippage days sum** stays: a view shows *each* item's slippage bucket, but only a
  chart **sums the days into one "how late are we, total" number**.

## Post-scaffold human checklist

- [ ] **Confirm the 3 charts are present** on the copied Project (Insights has no API);
      rebuild any that didn't carry from this file.
