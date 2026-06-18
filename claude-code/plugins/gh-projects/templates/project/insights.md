# Insights chart playbook (9 charts)

GitHub **Insights is free on all plans** (since Feb 2025). It is **read-only, UI-only,
zero API**: charts can be **neither created nor read** programmatically. So the 9 charts
are **built by hand once** on the golden-template Project (Phase 0, exactly like the 8
views) and then **replicate via `copyProjectV2`** (which carries Insights config).

Because Insights has **no API**, `scaffold-repo` can neither create *nor* verify charts —
it trusts the copy and emits a one-line **"confirm charts present"** human checklist item.
**Chart history accrues per project from its own start, is never backfilled, and is never
copied** → define Status + Iteration day one and don't archive in-flight items. Historical
group-by works only on **stacked** layouts.

The **Number fields** (Slippage-days, Blast-count) make charts quantitative (sum/avg), not
just issue counts.

| # | Chart | Layout · X · Y · Group · Filter | Audience |
|---|---|---|---|
| 1 | **Sprint burn-up** (hist.) | Burn-up · X=Time · Y=count · `sprint:@current` | devs+PM |
| 2 | **Cumulative flow** (hist.) | Stacked area · X=Time · Group=Status · `-status:Done` | lead+PM |
| 3 | **Throughput** | Column · X=Sprint · Y=count · `status:Done` | PM+founder |
| 4 | **Work mix by Type** | Column · X=Type · `is:open` | PM+founder |
| 5 | **Work mix by Size** | Stacked column · X=Size · Group=Type · `status:Ready,Backlog` | PM+lead |
| 6 | **Schedule-health dist.** | Column · X=Schedule health · `is:open` | standups+founder |
| 7 | **Blocked over time** (hist.) | Stacked area · X=Time · Group=Blast radius · `blocked:yes is:open` | lead+PM |
| 8 | **Release/Milestone progress** | Stacked column · X=Milestone · Group=Status · `milestone:*` | stakeholders |
| 9 | *(opt)* **Slippage-days sum** | Column · X=Schedule health · Y=**sum(Slippage-days)** · `is:open` | PM — quantified lateness |

## Post-scaffold human checklist (one line)

- [ ] **Confirm all 9 Insights charts are present** on the copied Project (Insights has
      no API; `scaffold-repo` cannot verify this — eyeball it once).
