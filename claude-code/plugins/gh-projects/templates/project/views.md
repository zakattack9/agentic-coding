# View catalog (8 saved views)

**ProjectV2 views are NOT API-mutable** (no create/edit/delete), but they **are
API-readable** (the `projectV2.views` connection: `name`, `layout`, `filter`,
`groupByFields`, `verticalGroupByFields`). All 8 views are built by hand **once**
on the golden-template Project (Phase 0) and **replicate via `copyProjectV2`**.
`scaffold-repo` verifies the copy in two read-only passes — it never creates or
edits a view:

1. **Presence (AC-7)** — diff the copy's view catalog against the expected 8
   titles in `views.json`.
2. **Resolution (AC-25, §6 `verify_views`)** — for each of the 8 views confirm it
   **resolves its documented filter / group / slice** against the copy: every
   filter qualifier maps to a native GitHub qualifier or a field that exists on
   the copy, and each documented group/slice is reflected by a non-empty live
   `groupByFields` / `verticalGroupByFields`. A missing view **or** an unresolved
   filter/group/slice **fails loudly** (exit 3) before any per-repo install under
   `--force`.

If a view is missing or unresolved after a copy, fix it on the **template** and
re-copy — do not hand-add to a scaffolded project (it would drift from the
template). The machine-checkable filter/group/slice catalog those checks read
lives in `views.json` (`filter`, `group`, `slice` per view + `_field_qualifiers`
mapping each filter keyword to its field).

8 saved views over the **one issue set**. `is:open` defines "active"; raw `target-date`
math gives a live backstop if the `signals-sync` cron stalls.

| # | View | Layout | Filter | Group / Slice | Sort | Card / Field surface | Audience — job |
|---|---|---|---|---|---|---|---|
| 1 | **Sprint board** | Board | `iteration:@current is:open` | cols = Status · **count ON** | manual rank | Assignees, Size, Priority, Blocked | Devs — pull from Ready, WIP=1 |
| 2 | **My work** | Table | `assignee:@me is:open` | group = Status | Priority↑ then Target↑ | — | Devs — cross-sprint personal list |
| 3 | **Ready queue** | Table (manual rank) | `status:Ready is:open` | group = Priority | manual | — | Lead — owns the gate & ordering |
| 4 | **Critical Path Board** | Board | `is:open` | cols = Schedule health · swimlane = Impact · **slice = Decision needed** | — | Target, Assignees, Blast radius, parent, Blocked-by | Standup — what's on fire now |
| 5 | **Schedule Risk Table** | Table | `is:open schedule-health:Overdue,Blocked,At-risk` (backstop `target-date:<@today,@today..@today+14d`) | group = Milestone **count ON** · **slice = Impact** | Release→Target↑ | — | PM/founder — what to decide & what it breaks |
| 6 | **Epic Hierarchy** | Table **Show hierarchy ON** (preview; flat `type:Epic` fallback) | — | group = Milestone | — | Sub-issue progress, Target, Schedule health, Impact | PM — epic rollup |
| 7 | **Intake & Hygiene** | Table | `is:open` | group = Status · **slice = Type** · saved searches: `status:Backlog no:assignee`, `no:target-date`, `no:sprint`, `status:Blocked` | — | — | PM — intake + trustworthy data |
| 8 | **Release Train Roadmap** | Roadmap | `target-date:*` | bars Start→Target · group = Milestone · **markers = milestones+iterations** | zoom = Quarter | — | Stakeholders — live timeline |

**Platform gaps (view playbook):**
- No `no:blocked-by` qualifier → the "blocked w/ no blocker" check stays a `lib/dag` scan.
- No `is:blocked` view-grouping → the derived **Blocked** single-select earns its place.
- **Views are not API-mutable** → ship via `copyProjectV2`; scaffold only verifies presence.

**Fallback (template edit, never per-project):** if a view needs changing, edit it on the
golden-template Project and re-run `scaffold-repo` (or re-copy) so every project stays in
parity. Per-project view edits are forbidden — they drift from the template.
