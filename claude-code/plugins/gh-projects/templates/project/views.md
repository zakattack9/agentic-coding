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
A view **never repeats its group field as a visible column** — the grouped section header
already shows it (so the Status-grouped and Priority-grouped tables omit Status/Priority
from `fields`). Sort keys need not be visible columns either; sort resolves on any field.

| #   | View         | Layout                                                                   | Filter                            | Group / Slice                                                                                                                                                                                                                                       | Sort                                | Visible columns (`fields`)                                                                                                                                                                                      | Audience — job                                                       |
| --- | ------------ | ------------------------------------------------------------------------ | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| 1   | **Sprint**   | Board                                                                    | `sprint:@current -status:Backlog` | cols = Status · **count ON**                                                                                                                                                                                                                        | Priority↑ then Size↓                | Priority\*, Size, Target date\*, Assignees, Blocked                                                                                                                                                             | Devs — pull from Ready, WIP=1                                        |
| 2   | **My Tasks** | Table                                                                    | `assignee:@me is:open`            | group = Status                                                                                                                                                                                                                                      | Priority↑ then Target↑              | Priority\*, Target date\*, Sprint, Size, Blocked                                                                                                                                                                | Devs — cross-sprint personal list                                    |
| 3   | **Ready**    | Table                                                                    | `status:Ready is:open`            | group = Priority                                                                                                                                                                                                                                    | Target↑ then Size↓                  | Target date\*, Size, Blocked, Tier                                                                                                                                                                              | Lead — owns the gate & ordering (Tier flags T3s needing a deep spec) |
| 4   | **Blockers** | Table                                                                    | `-blast-radius:"Blocks none" is:open` | group = Blast radius (option order Blocks release→Blocks 1; `Blocks none` filtered out)                                                                                                                                                                                                          | Blast count↓                        | Blast count, Blocked, Status, Assignees, Target date\*, Parent issue                                                                                                                                            | Lead — what to unblock first                                         |
| 5   | **Triage**   | Board                                                                    | `is:open -schedule-health:Done`   | cols = Schedule health (drag column order → Overdue→Blocked→At risk→On track; options unchanged — the `Done` column is filtered out since open items are never health:Done) · swimlane = Impact (Release blocker→Low) · **slice = Decision needed** | Priority↑ then Blast radius↑        | Priority\*, Status, Target date\*, Slippage, Milestone, Assignees, Blast radius, Blocked                                                                                                                        | Standup — what's on fire now                                         |
| 6   | **Epics**    | Table **Show hierarchy ON** (preview; flat `type:Epic is:open` fallback) | `type:Epic is:open`               | — *(no grouping — the epic→sub-issue tree is the structure)*                                                                                                                                                                                        | Schedule health↑ then Impact level↑ | Sub-issues progress, Status, Schedule health, Target date\*, Impact level                                                                                                                                       | PM — epic rollup                                                     |
| 7   | **Grooming** | Table **Show hierarchy ON**                                              | `is:open`                         | group = Status · **slice = Type** · ad-hoc hygiene filters (type into the bar — GitHub has no saved-search slot): `status:Backlog no:assignee` · `no:target-date` · `no:sprint` · `blocked:Blocked`                                                 | manual                              | Tier, Size, Priority\*, Assignees, Target date\*, Sprint, Milestone, **Type** (Type is the slice **and** a hand-added column — issue_type can't be in `visible_fields`, so toggle the Type column on in the UI) | PM — intake + trustworthy data                                       |
| 8   | **Roadmap**  | Roadmap **Truncate title ON**                                            | `has:target-date is:open`         | date = Start→Target · group = Milestone · **markers = Milestone + Sprint**                                                                                                                                                                          | Target↑ · zoom = Quarter            | — *(roadmap: no `visible_fields`; date bars span Start date\* → Target date\*)*                                                                                                                                 | Stakeholders — live timeline                                         |

**Platform gaps (view playbook):**
- No `no:blocked-by` qualifier → the "blocked w/ no blocker" check stays a `lib/dag` scan.
- No `is:blocked` view-grouping → the derived **Blocked** single-select earns its place.
- **Views are create-only** (`POST` works; no update/delete API) → `visible_fields`,
  grouping and the rest are set at create or in the UI, and ship onward via `copyProjectV2`.
- **Org issue fields aren't auto-added to a project** → setup_board adds Priority/Start/
  Target via `POST .../fields {"issue_field_id": …}` so their columns (`*`) resolve.
- **Board column order** follows the grouped field's *option* order; a per-view reorder
  (Triage's Schedule health → Overdue→Blocked→At risk→On track→Done) is a **UI drag** —
  no API, and it leaves the field's options untouched (`group_order` in views.json = the reminder).
- **`issue_type` can't be a `visible_fields` column** → show **Type** as a hand-toggled
  UI column (`ui_columns` in views.json); it carries via copy but scaffold can't verify it.
- **No field-position API** → the project's **global field order** (Settings → Fields,
  `field_display_order` in fields.json) is a one-time UI drag, carried by `copyProjectV2`.
- **View tab order = creation order** (the order in `views.json`); there's no view-reorder
  API, so changing the order on an existing board is a UI tab-drag (the template gets it
  right at create, and the order carries via copy).

**Fallback (template edit, never per-project):** if a view needs changing, change it on the
golden-template Project (delete + recreate, or edit in the UI) and re-copy so every project
stays in parity. Per-project view edits are forbidden — they drift from the template.
