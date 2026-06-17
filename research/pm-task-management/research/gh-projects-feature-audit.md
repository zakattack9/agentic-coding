---
title: gh-projects — GitHub Projects v2 & native feature-utilization audit
audited_spec: ../gh-projects.spec.md
backing: ./synthesis-and-plan.md
views_concept: ./gh-projects-gantt-views.md
verified: June 2026 (context7 /github/docs + GitHub changelogs + community discussions)
method: per-feature ADOPT / REFINE / EXCLUDE against current GitHub reality
---

# gh-projects feature-utilization audit

> Audit of the `gh-projects` build spec to confirm it **fully** exploits GitHub Projects v2 and GitHub-native features for a ≤4-engineer agentic startup migrating off Kanboard. Six cluster findings synthesized into one verdict + amendment list. Locked decisions are **respected, not relitigated**; corrections are feasibility/factual only.

---

## 1. Executive summary

The spec's architecture is sound and most load-bearing constraints (trigger inversion, App-token writes, option-ID instability, no-digest) are **accurate against June-2026 GitHub**. But the spec was drafted before several material shipped changes, leaving **four factual errors** and **two dominant capability gaps**.

**The two biggest gaps:**
1. **Native Project Status update (`createProjectV2StatusUpdate`)** — a free, API-driven, always-live project-level health primitive (enum `ON_TRACK/AT_RISK/OFF_TRACK/COMPLETE/INACTIVE` + start/target/body) that is the *exact* native fit for the "no-digest, always-live stakeholder surface" locked decision. The spec doesn't mention it. **Highest-value single addition.**
2. **`copyProjectV2` + org project templates exist** — the spec's entire `scaffold-repo` design is built around the now-false belief "no native Project-template" and "view creation via API is limited." Reality: copy a golden template project (carries fields, views, workflows-except-auto-add, Insights) in one mutation. This **simplifies the build** and removes its two biggest unknowns.

**The four factual errors to fix before build:** (a) "no native Project-template" — false, use `copyProjectV2`; (b) "view creation via API is limited" — it's *categorically impossible*, no view mutations exist at all; (c) "5k GraphQL pts/hr" — App installation token gets **10k/hr**; (d) the prod gate via **Environments required-reviewer is unavailable for private repos below GitHub Enterprise Cloud** — a silent no-op on Team/Free, twin of constraint #2.

**The highest-value additions beyond those:** an entire **§Insights & charts** section (free on all plans since Feb 2025; the live numeric digest); re-homing **Priority / Start date / Target date** to native org **Issue Fields**; deriving **Blocked** instead of hand-setting it; enabling free built-in workflows (**Item reopened, Auto-close issue**) while **disabling the default PR-merged→Done** that silently skips On Staging; scaffolding a **server-side ruleset** + a real **Release/`release.yml`**; and collapsing the 9 views to 8 with slice/sum/hierarchy exploited.

---

## 2. Master utilization matrix

Deduped across all six clusters. "In spec?" = present in `gh-projects.spec.md` today.

| Feature | Cluster | In spec today? | Verdict | Recommendation & where it plugs in |
|---|---|---|---|---|
| **Project Status update** (`createProjectV2StatusUpdate`, health enum + start/target/body, webhook `projects_v2_status_update`) | 4 | No | **ADOPT** | Project-level live "no-digest" surface; roll up Schedule-health → status enum in `signals-sync`. §Goal(d), §Gantt-signal fields, §Views, §lib/gh.py, §P1.5 gate. |
| **`copyProjectV2` + org project templates** (carries fields, views, workflows-except-auto-add, Insights; not items/collaborators) | 2, 6 | No (spec says "no template") | **ADOPT (replaces false claim)** | Golden-template-copy is the replication primitive. Rewrite §Hard-limits, §Risks, `scaffold-repo`, §lib/gh.py. |
| **No ProjectV2 *view* mutations** (create/sort/group/slice all impossible via API) | 2, 6 | Partial ("limited") | **REFINE → hard fact** | Views ship ONLY via template-copy; scaffold "verify presence" is read-only. §Risks, §Hard-limits, `scaffold-repo`. |
| **Issue Fields** (org-wide typed metadata, 25/org, searchable, REST+GraphQL; defaults Priority/Effort/Start/Target) | 1, 6 | No (predates it) | **ADOPT (Priority/Start/Target now); future-phase for Tier/Rigor/PM-ID/Size** | Re-home Priority, Start date, Target date to native Issue Fields (org-wide, cross-repo searchable); surface as Project columns (private-project only caveat). §Data model intro + fields. |
| **Native issue dependencies** (blocked-by/blocking, GA; native "Blocked" icon; `is:blocked`/`blocked-by:N`; `addBlockedBy`; 50/relationship cap) | 1, 5 | Partial (manual `Blocked` field; `lib/dag` reads deps) | **REFINE** | Derive `Blocked` in `signals-sync` (not human-set); add 50/relationship cap to Hard-limits; use `is:blocked` in Hygiene/Ready. Validates `lib/dag` design. §Data model, §Views, §lib/dag. |
| **`Parent issue` field + `subIssuesSummary.percentCompleted`** | 1, 5 | Partial (sub-issue progress named; parent not) | **ADOPT (`Parent issue` field) + REFINE (read summary)** | Add `Parent issue` as first-class field; feed `percentCompleted` into Epic signal. §Data model, Epic view, §lib/gh.py. |
| **Sub-issues 100/parent, 8 levels deep** | 1, 5, 6 | Partial (100 named) | **REFINE** | Add 8-level depth to Hard-limits (Epic→phase→sub-task ≤8). Epic-split must call `addSubIssue`/`gh --parent`. |
| **Hierarchy view ("Show hierarchy")** (table w/ inline parent→child tree, preserves group/slice/sort; public preview 2026-01-15) | 2 | No | **ADOPT** | Replace flat "Epic Health Rollup" with Hierarchy view (preview; flat fallback). §Views view 6. |
| **Built-in Number fields + group/column sums & counts** | 1, 2 | No (zero Number fields, zero sums) | **ADOPT (counts) + REFINE (Number fields)** | Add Number fields for Slippage-days & Blast-count (unlock Insights sums + sort + range filter); add item-count to Sprint board cols + Schedule-Risk Release groups. §Data model, §Views. |
| **Slice panel** (table/board/roadmap; composes with filter) | 2 | No (zero usage) | **ADOPT** | Biggest missed view capability. Slice: Critical Path=Decision needed, Intake&Hygiene=Type, Schedule Risk=Impact. §Views. |
| **Board column = non-Status single-select / iteration** | 2 | Partial (Critical Path uses Schedule health) | **REFINE (document as free choice)** | Already exploited once; document so future tabs can use it. §Views note. |
| **Native date-math filters** (`target-date:<@today`, `@today..@today+14d`, `is:open`) | 2 | No (uses `-status:Done`, derived field only) | **ADOPT** | Replace `-status:Done`→`is:open`; raw-date backstop on Hygiene/Schedule-Risk (live if cron stalls). §Views, all active-work filters. |
| **`parent-issue:` filter** | 1, 2 | No | **REFINE** | Use in Epic view + Epic-split signal. §Views. |
| **Roadmap milestone markers + default zoom** | 2 | Partial (iteration markers only) | **REFINE** | Add milestone markers + Quarter default to Release Train Roadmap. §Views. |
| **Secondary sort** | 2 | No | **REFINE** | Add to Ready queue (Priority then manual) + Schedule Risk (Release then Target date). §Views. |
| **Projects Insights / charts** (current + historical; FREE all plans since 2025-02; no API) | 3, 6 | No (zero coverage) | **ADOPT (new section)** | New §Insights & charts: 9-chart set (burn-up, cumulative-flow, throughput, work-mix, schedule-health, blocked-over-time, release progress). UI-only, ship as playbook. |
| **Built-in workflow: Item reopened** | 4 | No | **ADOPT** | Reopened regression → In Progress (free). `scaffold-repo`, §Dev lifecycle. |
| **Built-in workflow: Auto-close issue (Status→Done closes)** | 4 | No | **ADOPT** | Closes issue free when prod-deploy writes Done. `scaffold-repo`, §Dev lifecycle. |
| **Built-in workflow: PR merged → Done (default ON)** | 4 | No (collides) | **REFINE (must DISABLE)** | Default sets Done on merge → silently skips On Staging gate. Explicitly disable at scaffold. §Dev lifecycle, `scaffold-repo`. |
| **Built-in workflow: Item closed → Done (default ON)** | 4 | No | **REFINE (keep as fallback)** | Free Done-fallback so a closed issue never sits stale. §Dev lifecycle. |
| **Built-in workflow: Auto-add (plan-capped: Free 1 / Pro·Team 5 / EC 20)** | 4 | Implicit | **REFINE** | Make explicit; filter `is:issue,open`; not copied by `copyProjectV2` → recreate per linked repo. Add Auto-add cap to Hard-limits. |
| **Auto-archive workflow** | 4, 6 | No | **EXCLUDE (P1)** | No-op at ≤3k items/yr; archive shares the 50k cap (doesn't free headroom). Defer. |
| **Built-in workflow: Code review requested** | 4 | No | **EXCLUDE** | Redundant with PR-opened→In Review already wired. |
| **Project README + description** (`updateProjectV2(readme:,shortDescription:)`) | 4 | No | **ADOPT** | Generated board legend (Status/field/option meanings + view catalog + AC contract); home for the view playbook. `scaffold-repo`, §templates, §lib/gh.py. |
| **Project visibility (public/private)** | 4 | No | **EXCLUDE (automation)** | One-time human security decision (default private); document in §Open, don't automate. |
| **Project roles/permissions** (base Read for stakeholders, Write for team; App must be granted project access) | 6 | No | **ADOPT** | Set base role=Read (stakeholders see live views), Write to ≤4 eng + PM; explicitly grant App project access (footgun). `scaffold-repo`, §rules. |
| **CSV/TSV export** | 4 | No | **EXCLUDE** | Manual, view-scoped, scroll-lossy; superseded by GraphQL reads. §Open note only. |
| **`projects_v2` / `projects_v2_item` / `projects_v2_status_update` org webhooks** | 4 | Partial (names only `projects_v2_item`) | **REFINE** | List all three org-level events; inversion claim confirmed accurate. constraint #1, §rules. |
| **`gh` CLI 2.94.0 native type/parent/dependency flags** | 1, 5 | Inverted (treated as fallback threshold) | **REFINE (correctness fix)** | Native is the *happy path*: gh≥2.94 → GraphQL → DROP label fallback. §lib/gh.py, §constraints. |
| **Closing keywords + `closingIssuesReferences`** | 5 | Used (branch-parse + inject) | **REFINE** | Read `closingIssuesReferences` first (authoritative); document default-branch-only caveat (prod branch). §Dev lifecycle, §lib/gh.py. |
| **Development panel / `createLinkedBranch` / `gh issue develop`** | 5 | No | **ADOPT (optional)** | Authoritative issue↔branch link vs fragile branch-name regex. §route-issue, §lib/gh.py. |
| **Draft PRs** | 5 | Used (trigger list) | **REFINE** | Draft = In Progress, flip to In Review only on `ready_for_review` (board honesty; matters for future auto-implement). §Dev lifecycle. |
| **Rulesets / branch protection + required status checks** | 5 | Oblique (client-side `guard.sh`) | **ADOPT** | Scaffold ruleset on `main` (≥1 review, required checks, linear history, squash-off); reserve `ac-review` required-check slot for P2. `scaffold-repo`, §templates, §Open#3. |
| **Environments + required reviewers + deployment_status state mapping** | 5, 6 | Used (prod gate) but plan-blind | **ADOPT (plan prereq) + REFINE** | **GHEC-only for private repos** — add as load-bearing precondition + fallback gate; prevent-self-review; lock env to prod branch; map `deployment_status.state==success` per env. §constraints, §Dev lifecycle, `scaffold-repo`. |
| **Releases / tags / auto-notes (`release.yml`)** | 5 | No ("Milestone=release" only) | **ADOPT** | Cut real Release/tag + auto-notes at prod deploy (free stakeholder changelog); align labels to `release.yml` categories. §Sprints, §templates, §promote-pr. |
| **CODEOWNERS** | 5 | No | **EXCLUDE (routing) + ADOPT (narrow)** | No per-feature routing (4 eng, shared ownership). One-line CODEOWNERS for governance paths only (`specs/**`, `.github/workflows/**`, `project/*.json`). `scaffold-repo`. |
| **Operational labels** (`auto-implement`, `ac:passing/ac:failing`, release categories) | 5 | Mentioned in passing | **REFINE** | Scaffold them explicitly as an artifact (`labels.json` / REST). §templates. |
| **Label dependency fallback (`< gh 2.94`)** | 5 | Present | **EXCLUDE (drop)** | Lossy shadow; GraphQL covers all versions. §lib/gh.py. |
| **Issue forms + `config.yml`** | 5 | Used (strong) | **REFINE** | Set `blank_issues_enabled:false`; state forms enforce presence not AC quality (intake-issues owns AC). §templates. |
| **Markdown task lists** | 5 | PR template only | **EXCLUDE** | Don't surface in Projects fields; sub-issues + PR checklist supersede. |
| **Manual PR links (Development panel, 10/PR)** | 5 | No | **EXCLUDE (escape hatch only)** | Closing keywords are the automated primary; manual link is documented fallback. |
| **Merge queue** | 5 | No | **EXCLUDE** | Solves hot-branch contention; useless at WIP=1, ≤4 eng. §Risks/§Open note. |
| **Saved replies / team round-robin auto-assign** | 5 | No | **EXCLUDE** | Per-user / pushes work; contradicts self-assign-pull inversion. |
| **Bulk edit (table UI: copy-paste, drag-fill, Cmd+K add)** | 6 | No | **REFINE (document; no API)** | PMs bulk-set Sprint/Priority in table UI; no bulk-mutation API — don't build one. §Views note. |
| **Iteration fields editable via GraphQL** (2025-04) | 6 | Partial (resolve only) | **ADOPT** | After copy, re-anchor iteration start date via API; add iteration create/edit to lib. §lib/gh.py. ⚠️ replace-all hazard (below). |
| **Iteration replace-all / orphan hazard** | 1 | No (only single-select option-ID named) | **REFINE (correctness)** | `updateProjectV2Field` iterationConfiguration replaces whole list, wipes history. Extend constraint #3; correct `scaffold-repo` no-op gate (line 232). |
| **Single-select option `description`** | 1 | No | **REFINE** | Self-document signal fields' derivation rules in option descriptions. fields.json. |
| **Issue Types (25/org, label-independent, `gh --type`)** | 1, 6 | Used (correct) | **KEEP / REFINE** | Not copied by `copyProjectV2` (org-level; ensure exist once). Prefer `gh issue create --type`. |
| **Cross-repo single project (no repo cap; 50k items binds)** | 6 | Assumed (unstated) | **REFINE (state it)** | One org-owned board spans all repos; auto-add not copied → recreate per repo. §Architecture. |
| **Cross-repo Milestone rollup** | 6 | Deferred (plugin-computed) | **EXCLUDE (keep deferred)** | Milestones per-repo only; correct to defer. |
| **GraphQL rate envelope** (App=10k/hr, 2k/min, mutation=5pts, content-creation 80/min·500/hr) | 6 | Partial (wrong 5k figure) | **REFINE** | Fix 5k→10k; add 2k/min, mutation cost, content-creation (binds `intake-issues`). §Data model, §Risks. |
| **MCP Server Projects tools** (`projects_list/get/write`; fields+items only, no views) | 6 | No | **EXCLUDE (P1)** | Keep deterministic GraphQL + App token primary. |
| **Custom deployment protection rules (App-backed)** | 5 | No | **EXCLUDE** | Built-in required-reviewer + the `main` required-check cover the gate; P2 option only. |

---

## 3. Insights & custom charts

The spec has **zero** Insights coverage. Insights is a **free** (paid gate removed 2025-02-26), read-only, UI-only **historical/trend** surface the live views structurally cannot provide — and it is the **live numeric digest** that reinforces the locked "no digest" decision. **No API at all** (cannot be scaffolded, cannot feed `signals-sync`) → ship as a click-through playbook (`templates/project/insights.md`).

**Mechanics that decide what's buildable:**
- **Current** charts = snapshot now (X = any field, optional Group-by series, Y = item count OR sum/avg/min/max of a **Number** field). **Historical** = set **X-axis = Time** (tracks Open/Completed/Closed-PR/Not-planned).
- **Historical Y-axis = item count only** unless a **Number** field exists. Size is S/M/L (single-select, no points) → every historical chart here counts **issues, not effort**. (Adding the Number fields from §2 — Slippage-days, Blast-count — unlocks effort-like sums.)
- **Historical Group-by works only on Stacked layouts, NOT Burn-up.** Cumulative-flow = X=Time, Layout=**Stacked area**, Group by=**Status**.
- **History accrues from project start, never backfilled**; re-assigning iteration loses prior history → **define Status/Iteration day one; never archive in-flight items.**

**Tier caveat (paid gate flag):** Insights itself is **free on all plans, public and private** (since 2025-02-26) — Cluster 6 corrects Cluster 3's older "Team+" reading. The only residual nuance: historical charts need a project that has been collecting data, and the legacy "2 charts on Free private" limit was part of the pre-2025-02 regime now lifted. **Net: no paid-plan gate for charts.** (The one genuine paid-plan dependency in the whole spec is the **prod-gate Environment rule**, not Insights — see §6.)

**Proposed chart set** (Y = count unless a Number field is added; current unless marked historical):

| # | Chart | Purpose / audience | Config (Layout / X / Y / Group / Filter) | Replaces |
|---|---|---|---|---|
| 1 | **Sprint burn-up** (historical) | Sprint progress / devs+PM | Burn-up · X=Time · Y=count · Filter `sprint:@current` | Burndown a Gantt tool would show |
| 2 | **Cumulative flow / Status-over-time** (historical) | WIP build-up & bottlenecks / lead+PM | **Stacked area** · X=Time · **Group=Status** · Filter `-status:Done` | The static board's missing trend |
| 3 | **Throughput (Done per cycle)** | Delivery rate (DORA-adjacent) / PM+founder | Column · X=Sprint · Y=count · Filter `status:Done` | Digest "shipped N" |
| 4 | **Work mix by Type** | Feature vs Bug vs Infra balance / PM+founder | Column · X=Type · Y=count · Filter `-status:Done` | — |
| 5 | **Work mix by Size** | Appetite distribution / PM+lead | Stacked column · X=Size · Group=Type · Filter `status:Ready,Backlog` | — |
| 6 | **Schedule-health distribution** | Risk pulse now / standups+founder | Column · X=Schedule health · Y=count · Filter `-status:Done` (Group=Impact optional) | "Are we on schedule" |
| 7 | **Blocked count over time** (historical) | Blocking trend / lead+PM | Line/Stacked area · X=Time · Filter `blocked:yes -status:Done` (Group=Blast radius) | — |
| 8 | **Release / Milestone progress** | Release readiness / stakeholders | Stacked column · X=Milestone · **Group=Status** · Filter `milestone:*` | Per-repo %-complete crudeness |
| 9 | *(opt)* **Priority load in Ready** | Gate ordering / lead | Bar · X=Priority · Filter `status:Ready` | — |

**Charts that replace Gantt/digest needs:** burn-up (#1) = sprint progress; cumulative-flow (#2) + blocked-over-time (#7) = "where work is stuck"; schedule-health (#6) + release progress (#8) = "are we on schedule" — the Roadmap view stays the literal timeline, Insights adds the quantified trend. #3+#6+#7 are the live numeric digest.

---

## 4. View set refinement

**Are the views good?** Mostly — but **9 is one too many, with three genuine overlaps, and three layout capabilities (slice panel, group/column sums-counts, hierarchy view) are entirely unused.** Recommendation: **9 → 8 tabs**, every overlap resolved.

**Combine / split / refine moves vs the current 9:**

| Move | Views | Rationale |
|---|---|---|
| **MERGE** | Triage + Hygiene → **Intake & Hygiene** | Same PM audience, same "make data trustworthy" job. One `is:open` table, group=Status, **slice=Type**, hygiene variants documented as saved searches. Drops one tab. |
| **RE-SCOPE** | My work | Drop sprint constraint → `assignee:@me is:open` = the *cross-sprint* personal list, removing overlap with Sprint board. |
| **DIFFERENTIATE (keep both)** | Critical Path Board vs Schedule Risk Table | Biggest redundancy; keep but assign non-overlapping jobs: board = "what's on fire now" (slice=Decision needed), table = "what we decide & what it breaks" (Blast radius + Decision needed, grouped by Release w/ counts). |
| **ADOPT** | Epic Health Rollup → **Epic Hierarchy** | Replace flat `type:Epic` table with Hierarchy view (inline tree, preview; flat fallback). |
| **REFINE filters** | all active-work views | `-status:Done` → `is:open` (correct "active"); add raw date-math backstop. |
| **ADOPT slice** | Critical Path, Intake&Hygiene, Schedule Risk | Slice panel used in zero views today — the single biggest missed capability. |
| **ADOPT counts** | Sprint board, Schedule Risk | Item-count per column/group (free; surfaces WIP=1 breaches). |
| **REFINE** | Release Train Roadmap | Add milestone markers + Quarter default zoom. |

**Recommended final view set (8 tabs, exact config):**

| # | View | Layout · Filter · Group/Slice · Sort · Cards/Fields |
|---|---|---|
| 1 | **Sprint board** (devs) | Board · `iteration:@current is:open` · cols=Status · **count ON** · manual rank · cards: Assignees, Size, Priority, Blocked |
| 2 | **My work** (devs, cross-sprint) | Table · `assignee:@me is:open` · group=Status · sort Priority↑ then Target date↑ · fields: Title, Status, Sprint, Priority, Target date, Blocked |
| 3 | **Ready queue** (lead) | Table (manual rank) · `status:Ready is:open` · group=Priority · manual within group · fields: Title, Priority, Size, Sprint, Assignees, Blocked |
| 4 | **Critical Path Board** (standup) | Board · `is:open` · cols=Schedule health · swimlane=Impact level · **slice=Decision needed** · cards: Target date, Assignees, Blast radius, parent, Blocked-by |
| 5 | **Schedule Risk Table** (PM/founder) | Table · `is:open schedule-health:Overdue,Blocked,At-risk` OR backstop `is:open target-date:<@today,@today..@today+14d` · group=Milestone **count ON** · **slice=Impact** · sort Release then Target date↑ · fields: Title, Target date, Schedule health, Slippage, Blast radius, Decision needed, parent, Blocked-by |
| 6 | **Epic Hierarchy** (PM) | Table **Show hierarchy ON** (preview) · `type:Epic` · group=Milestone · slice=Schedule health (opt) · fields: Title, Sub-issue progress, Target date, Schedule health, Impact, Assignees |
| 7 | **Intake & Hygiene** (PM) | Table · `is:open` · group=Status · **slice=Type** · fields: Title, Type, Status, Assignees, Target date, Sprint, Blocked, Blocked-by · description documents `status:Backlog no:assignee`, `no:target-date`, `no:sprint`, `status:Blocked` |
| 8 | **Release Train Roadmap** (stakeholders) | Roadmap · `target-date:*` · bars Start→Target · group=Milestone · **markers=milestones+iterations** · slice=Schedule health (opt) · zoom=Quarter |

**Platform gaps to call out in the view playbook:** there is **no `no:blocked-by` qualifier** (the "blocked w/ no blocker" hygiene check stays a `lib/dag` scan, not a saved filter); **no `is:blocked` Projects-view grouping** (confirms the *derived* `Blocked` single-select earns its place to make blocked-ness filterable/groupable); **views are not API-mutable** (ship via `copyProjectV2` from the golden template; verify-presence only).

---

## 5. GitHub-native utilization

| Native feature | Verdict | Reason / how used |
|---|---|---|
| **Issue dependencies** (blocked-by/blocking) | **USE + REFINE** | `lib/dag` reads them → Blast radius (mandatory: deps aren't a groupable Project field). Add 50/relationship cap. Native "Blocked" icon derives free → make `Blocked` field auto-derived. `is:blocked`/`blocked-by:N` in Hygiene/Ready. |
| **Sub-issues + progress + Parent issue** | **USE + ADOPT** | Add `Parent issue` field (Epic grouping); read `subIssuesSummary.percentCompleted` into Epic signal; Epic-split calls `addSubIssue`. 100/parent, 8-deep caps. |
| **PR↔issue closing keywords + `closingIssuesReferences`** | **USE + REFINE** | Resolve issue via `closingIssuesReferences` first (authoritative), branch-parse fallback. Keywords fire only on **default-branch** PRs → prod-branch Done stays `deployment_status`-driven (already structurally correct; document it). |
| **Linked branches (`createLinkedBranch`/`gh issue develop`)** | **ADOPT (optional)** | Guaranteed issue↔branch link + conventional name vs fragile regex; caveat: `linkedBranches` empties at PR open → capture issue# at branch-create or fall back to closingIssuesReferences. |
| **Draft PRs** | **USE + REFINE** | Draft = In Progress; flip In Review only on `ready_for_review` (matters for future auto-implement draft PRs). |
| **Environments / deployments / `deployment_status`** | **USE + ADOPT prereq + REFINE** | Prod gate rides Environments. **Required-reviewer is GHEC-only for private repos** — add load-bearing precondition + deterministic fallback (workflow_dispatch restricted via env secrets, which DO work on Team-private). Prevent-self-review; lock env to prod branch; map `state==success` per env (failure → hold/Blocked). |
| **Rulesets / branch protection / required checks** | **ADOPT** | Move `--squash`/green-checks/review gates from bypassable `guard.sh` to server-side ruleset on `main`; reserve required-check slot named `ac-review` for P2 (labels don't gate merge; check runs do). |
| **Releases / tags / `release.yml` auto-notes** | **ADOPT** | "Milestone=release" yields no shipped artifact today. Cut a real Release + auto-generated notes at prod deploy (free changelog); align scaffolded labels to `release.yml` categories. |
| **Issue Types (org)** | **USE (correct)** | Right home for Type; not copied by `copyProjectV2` (org-level — ensure 5 exist once). Prefer `gh issue create --type`. |
| **Issue Fields (org)** | **ADOPT (Priority/Start/Target) + future-phase (Tier/Rigor/PM-ID/Size)** | Org-wide typed, cross-repo searchable, immune to per-project copy/re-ID; surface as Project columns (private-project integration caveat). |
| **Project Status update** | **ADOPT** | The project-level "no-digest" live health primitive; rolled up deterministically. |
| **Project README/description** | **ADOPT** | Generated board legend + view catalog + AC contract via `updateProjectV2`. |
| **Project roles/permissions** | **ADOPT** | Base Read (stakeholders), Write (team); explicitly grant App project access. |
| **Built-in workflows** | **ADOPT (Item reopened, Auto-close, keep Item-closed fallback) + REFINE (Auto-add) + DISABLE (PR-merged→Done) + EXCLUDE (Code review requested, Auto-archive)** | Free-first split: reserve `board-sync` GraphQL for In Progress/In Review/On Staging only. |
| **CODEOWNERS** | **EXCLUDE routing + ADOPT narrow** | No per-feature routing (shared ownership); one-line CODEOWNERS for governance paths (`specs/**`, workflows, schema JSON). |
| **Labels** | **REFINE + EXCLUDE fallback** | Scaffold operational labels explicitly; drop the label dependency-shadow fallback. |
| **Merge queue** | **EXCLUDE** | Overkill at WIP=1, ≤4 eng. |
| **Markdown task lists / saved replies / round-robin / CSV export / MCP tools / custom deploy-protection** | **EXCLUDE** | Each contradicts the model or is superseded (see §2). |

---

## 6. Corrections (spec is now wrong vs current GitHub)

| # | Spec claim (location) | Reality (June 2026) | Fix |
|---|---|---|---|
| C1 | **"no native Project-template (replicate via `createProjectV2*` mutations)"** — §Hard-limits L107, shapes `scaffold-repo` | **False.** `copyProjectV2` GraphQL mutation exists (`projectId`, `ownerId`, `title`, `includeDraftIssues`); UI "Make a copy" + org **project templates** (recommend up to 6). Copy carries views, fields, workflows-EXCEPT-auto-add, Insights — NOT items/collaborators/repo-links. | Rewrite to golden-template-copy architecture; `lib/scaffold.py` shrinks. |
| C2 | **"view creation via API is limited"** — §Hard-limits L107, §Risks L247 | **Categorically impossible.** Zero ProjectV2 view mutations (create/sort/group/slice/reorder). MCP Projects tools also cover fields+items only. | Views ship ONLY via template-copy; scaffold "verify presence" is read-only audit, not a create step. |
| C3 | **"5k GraphQL points/hr"** — §Hard-limits L107, §Risks L251 | That's the **user-PAT** number. The loop uses a **GitHub App installation token** → **10,000 pts/hr**. Also undocumented in spec: **2,000 pts/min** secondary, **mutation=5 pts**, **content-creation 80/min·500/hr**. | Fix 5k→10k; add the other three (content-creation binds `intake-issues`, not points). |
| C4 | **Prod gate = "Environments required-reviewer rule"** — §Locked decisions L52, §Dev lifecycle L147 (no plan caveat) | **Required reviewers (and wait timers) are NOT available for private repos below GitHub Enterprise Cloud.** On Free/Pro/Team private repos the rule silently no-ops; only public repos or GHEC enforce it. | Add as **load-bearing precondition** (twin of constraint #2) + deterministic fallback gate for Team-private (env secrets DO work). §Open#1 checked precondition. |
| C5 | **`Blocked` is human-set** (L91) but **also derived for Schedule health** (L99) and **signal count says 3 auto + 2 human** (L105) | Internally inconsistent; native "Blocked" icon now derives from blocked-by edges for free. | Move `Blocked` to **auto** (derived in `signals-sync` from the DAG); fix count to **4 auto + 2 human**; reconcile L99. |
| C6 | **Constraint #3 names only single-select option-ID instability** (L27) | **Iteration fields are worse**: `updateProjectV2Field` iterationConfiguration is **replace-all**, wiping completed iterations + orphaning issue↔iteration assignments. `scaffold-repo` "re-run is a no-op" exit gate (L232) is **false for iterations**. | Extend constraint #3 + Hard-limits to iteration replace-all; correct the no-op gate to diff/skip iterations. |
| C7 | **`lib/gh.py`: "label fallback < gh 2.94"** (L188) | **Inverted.** gh 2.94.0 (2026-06-10) *adds* native `--type/--parent/--blocked-by` — the rich happy path, not a fallback boundary. GraphQL (always available) is the real fallback; the label shadow is obsolete. | Rewrite degrade rail: gh≥2.94 native → GraphQL → **drop labels**. |
| C8 | **`updateProjectV2ItemFieldValue` writes all fields** (implied, L188) | Assignees/Labels/Milestone/Repository need **separate mutations**; iteration values use `iterationId`; `@current/@next` are filter sugar, not API values. | Note distinct mutations + iteration ID semantics in §lib/gh.py. |
| C9 | **"50,000 items (active+archive)"** (L107) — *correct* but missing consequence | Confirmed: 50k is the **combined** cap; archiving does **not** free headroom. | Keep figure; add "archive doesn't free the cap" + EXCLUDE auto-archive from P1 (no-op at scale). |
| C10 | **Cross-repo / org-ownership assumed, never stated** | One org-owned project spans unlimited repos (50k items binds); auto-add workflows **not copied** by `copyProjectV2`. | State org-owned + cross-repo in §Architecture; recreate auto-add per linked repo in `scaffold-repo`. |
| — | **`projects_v2_item` inversion** (constraint #1) | **Confirmed accurate** — no repo trigger; org-webhook→`repository_dispatch` is the only bridge. | No change; add `projects_v2` + `projects_v2_status_update` to the event list. |
| — | **50 fields/project, 50k items, 100 sub-issues/parent, 100 items/page** | **Confirmed accurate.** | No change; add 8-level sub-issue depth + 50/dependency-relationship cap. |

---

## 7. Prioritized spec amendments

Ordered, concrete edits to `gh-projects.spec.md`, tagged P1 (must-fix / highest value) / P2 / P3.

1. **[P1] Fix the four factual errors (§Hard-limits L107, §Risks L247/L251, §Locked-decisions L52, §lib/gh.py L188).** (a) Delete "no native Project-template" → state **`copyProjectV2` + org templates** as the replication primitive; (b) "view creation limited" → **"no view mutations exist; views ship only via template-copy, verify-presence is read-only"**; (c) **5k → 10k GraphQL pts/hr** (App token) and add **2k/min, mutation=5pts, content-creation 80/min·500/hr**; (d) invert the gh-2.94 degrade rail to **native → GraphQL → drop label fallback**.

2. **[P1] Add a new load-bearing precondition: the prod-gate Environment required-reviewer is GHEC-only for private repos.** Note it on §Locked-decisions "Prod gate" line and as a checked precondition in §Open #1; add a **deterministic fallback gate** (workflow_dispatch prod-deploy restricted to PM/lead via environment secrets — which DO work on Team-private) for teams not on GHEC. Add a matching §Risks row.

3. **[P1] Add §Project Status update as the project-level "no-digest" surface.** New row in §Gantt-signal fields ("**Project Status update** — rolled-up health, auto"); `signals-sync.yml`/`sync-signals` posts `createProjectV2StatusUpdate` (Overdue/Blocked blocking release ⇒ `OFF_TRACK`; At-risk ⇒ `AT_RISK`; else `ON_TRACK`; milestone closed ⇒ `COMPLETE`) with start/target from active Milestone/Iteration and a deterministic one-line body. Add the mutation to §lib/gh.py; restate §Goal(d) + the "no digest" non-goal as **Status update (project) + signal fields (items) + Roadmap view**; add to §P1.5 exit gate.

4. **[P1] Rewrite `scaffold-repo` + §org-replication around the golden-template-copy pattern.** One hand-built golden Project (full schema + all 8 views + iteration, marked org template) → `scaffold-repo` calls `copyProjectV2(includeDraftIssues:false)` per team → then does only what the API allows: link repos, **(re)create the per-repo auto-add workflow** (NOT copied), re-anchor the iteration start date (now API-editable), **re-resolve option/field/iteration IDs against the COPY** (mandatory, dovetails constraint #3), set base role=Read / Write-to-team, **explicitly grant the App project access** (footgun), install repo files. Downgrade the documented view playbook to "edit-the-golden-template fallback only." Update §lib/gh.py (`copyProjectV2`, `updateProjectV2`, iteration create/edit) and §templates.

5. **[P1] Correct the `Blocked` field + iteration hazard inconsistencies.** Move `Blocked` from human-set (L91) to **auto-derived** in `signals-sync` from the blocked-by DAG; fix the signal count to **4 auto + 2 human** (L105) and reconcile L99. Extend constraint #3 (L27) and Hard-limits to the **iteration replace-all/orphan hazard**; correct `scaffold-repo`'s "re-run is a no-op" exit gate (L232) to diff/skip iterations. Add the **50-per-dependency-relationship** cap and **8-level sub-issue depth** to Hard-limits.

6. **[P1] Add a new §Insights & charts section** (after §Views) — the 9-chart table from §3 (Name / current|historical / Layout / X / Y / Group / Filter / audience), prefaced with: read-only, UI-only, **no API** (cannot be scaffolded or feed automation), **free on all plans**, counts issues not effort, history accrues from project start (define Status/Iteration day one, never archive in-flight). Add `templates/project/insights.md` playbook; `scaffold-repo` dry-run manifest lists charts as a manual post-step. Add a §Risks row mirroring the view-API risk (Insights has *zero* API — worse than views).

7. **[P1] Replace the 9-view §Views table with the 8 refined views (§4).** Add **Slice** and **Sums/Count** columns; merge Triage+Hygiene → Intake & Hygiene; re-scope My work to cross-sprint; differentiate Critical Path vs Schedule Risk by job + slice; adopt the **Hierarchy view** for Epic Hierarchy (preview, flat fallback); change every `-status:Done` → `is:open`; add raw date-math backstops; add milestone markers + Quarter zoom to the Roadmap. Note the `no:blocked-by` / `is:blocked`-grouping platform gaps.

8. **[P2] Re-home Priority / Start date / Target date to native org Issue Fields**, surfaced as Project columns (note "private projects only" Projects-integration caveat as a parameterized item). Add Issue Fields as a third taxonomy home in §Data-model intro (rule: org-wide typed attrs → Issue Fields; board-local state → Project fields). Keep Size/Tier/Rigor as Project single-selects (deliberate, plugin-specific).

9. **[P2] Fix the free-first automation split (§Dev lifecycle + `scaffold-repo`).** Enable built-ins {Item added, Item reopened→In Progress, Item closed→Done (fallback), Auto-close issue}; **explicitly DISABLE the default "PR merged → Done"** (silently skips On Staging); reserve `board-sync.yml` GraphQL writes for In Progress / In Review / On Staging only. Add Auto-add (filter `is:issue,open`, plan-capped) to Hard-limits. List all three org webhooks (`projects_v2`, `projects_v2_item`, `projects_v2_status_update`) in constraint #1 + §rules.

10. **[P2] Scaffold a server-side ruleset on `main`** (≥1 approving review, required status checks, linear history, squash-merge OFF) via `scaffold-repo` + `templates/project/ruleset.json`; reserve a required-check slot named `ac-review` for the P2 AC gate (resolve §Open #3 toward server-side). Keep `guard.sh` as the client-side fast-fail, not the enforcement boundary.

11. **[P2] Add Number fields** for **Slippage-days** and **Blast-count** (companion to the categorical buckets) to unlock Insights sums/avg, numeric sort, and range filters; add **item-count** to Sprint board columns + Schedule-Risk Release groups. Add single-select **option `description`** config (self-documenting derivation rules) to `fields.json` for every signal field.

12. **[P2] Add Releases + `release.yml`** — ship `templates/github/release.yml` (categories mapping Feature→New Features, Bug→Fixes, Infra/Chore→Other); add a `cut-release` step (tag + auto-notes) to `promote-pr` at prod deploy; clarify in §Sprints that Milestone (planning %-complete) and Release (shipped artifact + notes) are **two mechanisms**. Scaffold the operational + release-category labels explicitly (`labels.json`).

13. **[P2] Generate a project README** (board legend: Status lifecycle, each field + option meanings, view catalog, AC/tier contract) + description via `updateProjectV2`; make it the home for the view-config playbook. Add `templates/project/README.md` and `updateProjectV2` to §lib/gh.py.

14. **[P3] PR↔issue + branch robustness.** Read `closingIssuesReferences` first in `board-sync` (branch-parse fallback); document the default-branch-only closing-keyword caveat (prod-branch Done stays `deployment_status`-driven). Optionally use `createLinkedBranch`/`gh issue develop` in `route-issue` for authoritative links (capture issue# at branch-create). Make draft PRs = In Progress, flip In Review only on `ready_for_review`. Pin `deployment_status.state==success` per env in §Dev lifecycle.

15. **[P3] Add `Parent issue` as a first-class §Data-model field** and read `subIssuesSummary.percentCompleted` into the Epic signal; ensure Epic-split calls `addSubIssue`. Note Assignees/Labels/Milestone/Repository need distinct mutations in §lib/gh.py.

16. **[P3] Hardening + housekeeping.** `blank_issues_enabled:false` in `config.yml`; state issue forms enforce field *presence* not AC quality (intake-issues owns AC); narrow CODEOWNERS for governance paths only; note bulk-edit is table-UI-only (no API). §Open notes: project visibility (default private, not automated), CSV/TSV export (manual/lossy — only if a stakeholder wants a spreadsheet), merge queue deferred (revisit only on merge contention), MCP Projects tools deferred (keep deterministic GraphQL). §Future-phases: migrate Tier/Rigor/PM-ID/Size to org Issue Fields once GA.
