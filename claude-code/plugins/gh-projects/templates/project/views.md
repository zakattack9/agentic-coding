# View catalog (8 saved views)

`lib/setup_board.py` creates these 8 views as **shells** via the REST Projects API
(`POST .../projectsV2/{n}/views` — `name` + `layout` + `filter` + `visible_fields`).
Their **grouping / slice / sort / swimlanes have no create parameter and there is no
view-update API**, so those are finished **by hand once** in the UI on the golden
template; the finished views then **replicate via `copyProjectV2`**. `scaffold-repo`
verifies the copy in two read-only passes — it never creates or edits a view:

1. **Presence** — diff the copy's view catalog against the expected 8 titles in `views.json`.
2. **Resolution (`verify_views`)** — for each of the 8 views confirm it **resolves its
   documented filter / group / slice** against the copy: every filter qualifier maps to
   a native GitHub qualifier or a field that exists on the copy, and each documented
   group/slice is reflected by a non-empty live `groupByFields` / `verticalGroupByFields`.
   A missing view **or** an unresolved filter/group/slice **fails loudly** (exit 3).

**Visible columns** come from each view's `fields` list in `views.json`: setup_board
resolves the names to field ids and sets `visible_fields` at create (table & board
only — roadmap takes none). The **org issue fields** `Priority` / `Start date` /
`Target date` don't auto-appear as project columns, so setup_board **adds them first**
via `POST .../fields {"issue_field_id": …}` and then resolves their columns like any
other field. The view API is **create-only** — no update *and* no delete (both `404`),
and no GraphQL view mutation exists — so changing a view (its columns, grouping,
filter…) means **deleting it in the UI and re-running** setup_board, which recreates it.
setup_board **flags** any existing view whose columns are out of date (it can't fix one
in place).

8 saved views over the **one issue set**. `is:open` defines "active"; raw `target-date`
math gives a live backstop if the `signals-sync` cron stalls. **`*` marks an org issue
field** (Priority/Start/Target) — setup_board adds these to the project automatically.

| # | View | Layout | Filter | Group / Slice | Sort | Visible columns (`fields`) | Audience — job |
|---|---|---|---|---|---|---|---|
| 1 | **Sprint board** | Board | `iteration:@current is:open` | cols = Status · **count ON** | manual rank | Assignees, Size, Priority\*, Blocked | Devs — pull from Ready, WIP=1 |
| 2 | **My work** | Table | `assignee:@me is:open` | group = Status | Priority↑ then Target↑ | Status, Priority\*, Sprint, Target date\*, Blocked | Devs — cross-sprint personal list |
| 3 | **Ready queue** | Table (manual rank) | `status:Ready is:open` | group = Priority | manual | Priority\*, Size, Target date\*, Blocked | Lead — owns the gate & ordering |
| 4 | **Critical Path Board** | Board | `is:open` | cols = Schedule health · swimlane = Impact · **slice = Decision needed** | manual | Target date\*, Assignees, Blast radius, Parent issue, Blocked | Standup — what's on fire now |
| 5 | **Schedule Risk Table** | Table | `is:open schedule-health:Overdue,Blocked,"At risk"` (backstop `target-date:<@today,@today..@today+14d`) | group = Milestone **count ON** · **slice = Impact** | Milestone↑ then Target↑ | Schedule health, Target date\*, Slippage, Impact level, Decision needed, Milestone | PM/founder — what to decide & what it breaks |
| 6 | **Epic Hierarchy** | Table **Show hierarchy ON** (preview; flat `type:Epic` fallback) | — | group = Milestone | manual | Sub-issues progress, Target date\*, Schedule health, Impact level | PM — epic rollup |
| 7 | **Intake & Hygiene** | Table | `is:open` | group = Status · **slice = Type** · ad-hoc hygiene filters (type into the bar — GitHub has no saved-search slot): `status:Backlog no:assignee` · `no:target-date` · `no:sprint` · `status:Blocked` | manual | Status, Assignees, Priority\*, Target date\*, Sprint (Type is the slice — issue_type can't be a column) | PM — intake + trustworthy data |
| 8 | **Release Train Roadmap** | Roadmap | `has:target-date` | date = Start→Target · group = Milestone · **markers = Milestone + Sprint** | zoom = Quarter | — *(roadmap: no `visible_fields`; date bars span Start date\* → Target date\*)* | Stakeholders — live timeline |

**Platform gaps (view playbook):**
- No `no:blocked-by` qualifier → the "blocked w/ no blocker" check stays a `lib/dag` scan.
- No `is:blocked` view-grouping → the derived **Blocked** single-select earns its place.
- **Views are create-only** (`POST` works; no update/delete API) → `visible_fields`,
  grouping and the rest are set at create or in the UI, and ship onward via `copyProjectV2`.
- **Org issue fields aren't auto-added to a project** → setup_board adds Priority/Start/
  Target via `POST .../fields {"issue_field_id": …}` so their columns (`*`) resolve.

**Fallback (template edit, never per-project):** if a view needs changing, change it on the
golden-template Project (delete + recreate, or edit in the UI) and re-copy so every project
stays in parity. Per-project view edits are forbidden — they drift from the template.
