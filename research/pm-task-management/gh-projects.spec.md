---
id: PM-0001
title: gh-projects — GitHub-native PM & software-lifecycle plugin
type: epic
tier: T3
rigor: full
size: L
status: draft
owner: PM
depends: [spec-ops]
spec_backing: ./research/synthesis-and-plan.md
views_concept: ./research/gh-projects-gantt-views.md
feature_audit: ./research/gh-projects-feature-audit.md
---

# gh-projects — Build Spec

> The build contract for a new Claude Code plugin that runs a ≤4-engineer startup's **entire software lifecycle on GitHub Projects v2** — AI-assisted intake, a structured board, a light branch→PR→staging→prod flow that is tightly tracked, and always-live native surfaces for stakeholders. Research backing: `research/synthesis-and-plan.md`. Views concept: `research/gh-projects-gantt-views.md`. Feature-utilization audit (verified June 2026): `research/gh-projects-feature-audit.md`.

## TL;DR

`gh-projects` turns unstructured work into **field-complete GitHub issues with machine-verifiable acceptance criteria**, projects them onto a Projects v2 board, and keeps that board a **live, automation-driven projection** of issue/PR/deploy events. The **GitHub issue is the canonical unit**; markdown deep-specs are linked reference detail for complex (T3) work only. Requirements are authored via **spec-ops** (the WHAT) but stay **implementation-agnostic** — any dev implements them however they like (`/goal`, Codex, hand-code). Board↔deploy wiring stays **loosely coupled**: native Project built-ins + a plugin `board-sync` workflow + an **opt-in composable `board-status` action** added as one step to existing deploy pipelines. Phase 1 is the **free, deterministic** loop; every **metered-AI** capability is deferred behind budget rails.

## Acceptance Criteria

> The Phase-1 build is done when every AC below holds — atomic, observable end-states (this spec dogfoods its own AC-first rule); the sections below realize each, and `verify:` names a concrete check.

- **AC-1** [lib] `lib/gh.py` resolves and caches a real org Project's field/option/iteration IDs via a GitHub App token; a repeat lookup in the same run hits cache (no second round-trip). `verify:` integration test asserts one resolve for two lookups.
- **AC-2** [lib] A field write goes through the two-phase `addProjectV2ItemById` → read item id → `updateProjectV2ItemFieldValue` sequence and reads back identical. `verify:` round-trip test on a single-select.
- **AC-3** [lib] Every `lib/*.py` entrypoint returns the documented exit codes (`0/2/3/1`) and prints no token/secret. `verify:` exit-code + secret-scan test.
- **AC-4** [lib] `lib/gh.py` prefers native `gh ≥ 2.94` flags, falls back to GraphQL, and contains **no** label-based dependency fallback. `verify:` grep + version-branch test.
- **AC-5** [lib] `lib/pm.py` allocates monotonic `PM-####` ids and round-trips flow-style front-matter without loss. `verify:` property test.
- **AC-6** [lib] `lib/dag.py` derives `Blocked`, `Blast radius`, and `Blast-count` from blocked-by edges matching a hand-checked fixture. `verify:` graph fixture test.
- **AC-7** [scaffold] `scaffold-repo` stands up the Project via `copyProjectV2` from the named golden template; the copy contains every §Data-model field and all 8 views. `verify:` post-scaffold GraphQL dump diffs `fields.json` + view catalog.
- **AC-8** [scaffold] `scaffold-repo` re-resolves all field/option/iteration IDs against the **copy** (never the template) before any write. `verify:` assert resolved IDs ≠ template IDs.
- **AC-9** [scaffold] A second run is a no-op for fields and **skips existing iterations** (no `iterationConfiguration` re-PUT). `verify:` re-run change-manifest empty; iteration-mutation count = 0.
- **AC-10** [scaffold] `scaffold-repo` ensures org Issue Types + Issue Fields exist, sets the repo `allow_squash_merge=false`, grants the App project access, and installs the issue forms, PR template, `board-sync.yml`, `signals-sync.yml`, `board-status` action, `release.yml`, CODEOWNERS, and project README. `verify:` post-scaffold file + setting assertions.
- **AC-11** [scaffold] `scaffold-repo` is dry-by-default — prints the full change manifest and mutates nothing without confirm/`--force`. `verify:` dry-run leaves project + repo unchanged.
- **AC-12** [intake] `intake-issues` turns a raw dump into individual tiered issues, each with `Type/Size/Tier/Rigor/PM-ID` set and a `## Acceptance Criteria` list. `verify:` sample dump → issues with required fields populated.
- **AC-13** [intake] `intake-issues` **refuses `Ready`** for any item whose AC are prose-only / not atomic observable end-states, stating the reason. `verify:` prose-AC fixture stays out of `Ready`.
- **AC-14** [intake] `intake-issues` delegates each body+AC to `spec-ops:write-spec` (+`refine-spec` when `rigor: full`) and authors no body inline. `verify:` call trace shows the delegation.
- **AC-15** [intake] Phase count drives the size suggestion (1→S/2–3→M/4+→L) and >~3–4 phases yields an Epic-split (sub-issue per phase via `addSubIssue`). `verify:` 1/3/5-phase fixtures → S/M/L + split.
- **AC-16** [intake] `intake-issues` is dry-by-default — previews drafts, calls `gh issue create` only on confirm. `verify:` dry-run creates no issue.
- **AC-17** [board] A push to an issue-linked branch moves the item to `In Progress` via an App-token GraphQL write. `verify:` event→status fixture.
- **AC-18** [board] A ready PR → `In Review`; a draft PR holds `In Progress` until `ready_for_review`. `verify:` draft vs ready fixtures.
- **AC-19** [board] `board-sync` resolves the PR↔issue link from the **linked branch first, branch-name parse fallback**, and never depends on `Closes #N`. `verify:` both paths + grep for no closing-keyword dependence.
- **AC-20** [board] The native "PR merged → set Status" built-in is set to `On Staging` (not `Done`) and the item stays **open** after merge. `verify:` post-merge item open + On Staging.
- **AC-21** [board] The `board-status` step sets `On Staging` on staging success and `Done` + closes + publishes the tag's Release on prod success, resolving shipped issues from the deployed SHA. `verify:` fixture-repo action run.
- **AC-22** [board] The `board-status` action is **self-contained** (vendors its GraphQL logic, no plugin import) and runs from `./.github/actions/board-status` in a repo without the plugin installed. `verify:` action runs green in a plugin-less repo.
- **AC-23** [signals] `signals-sync` recomputes Schedule health/Slippage/Slippage-days/Blast radius/Blast-count/Blocked deterministically (no model call) on events + cron. `verify:` fixture board → expected values; zero AI calls asserted.
- **AC-24** [signals] `signals-sync` posts a `createProjectV2StatusUpdate` whose health enum matches the documented rollup. `verify:` rollup fixtures → expected enum.
- **AC-25** [views] All 8 views exist and each resolves its documented filter/group/slice without error. `verify:` view-presence + query check.
- **AC-26** [invariant] No Phase-1 workflow or skill makes a metered AI/model call. `verify:` CI grep across templates + skills.
- **AC-27** [invariant] Every Projects field write uses the App installation token; none use `GITHUB_TOKEN`. `verify:` token-usage grep.
- **AC-28** [invariant] `hooks/guard.sh` blocks `--squash` and prod actions without green checks during route/promote, and fails open on unrelated input. `verify:` guard unit tests.
- **AC-29** [invariant] The plugin manifest carries only `name`+`description`; the version is in root `marketplace.json` at `0.1.0`; pm-ops is marked deprecated there. `verify:` manifest + marketplace assertions.
- **AC-30** [invariant] No schema mutation re-PUTs a single-select option list or `iterationConfiguration` without a prior diff. `verify:` ID-stability guard test.

## ⚠️ Load-bearing constraints (break the system if missed)

1. **`projects_v2_item` cannot trigger repo workflows.** A board column move fires an **org-level** `projects_v2_item` webhook — there is *no* `on: projects_v2_item:` in repo Actions. The board is driven **from** `issues` / `pull_request` / `push` events writing Status **into** the Project via GraphQL (we invert the trigger), plus native built-in workflows and the opt-in `board-status` action.
2. **`GITHUB_TOKEN` cannot write Projects v2 fields.** All Project writes use a **GitHub App installation token** (org-scoped, `project` scope, survives staff departure, 10k GraphQL pts/hr). PRs created by `GITHUB_TOKEN` also don't trigger downstream workflows.
3. **Field/option/iteration edits regenerate IDs and orphan assignments.** Editing a single-select option list regenerates option IDs; worse, `updateProjectV2Field`'s `iterationConfiguration` is **replace-all** — re-PUTting it wipes completed iterations and orphans every issue↔iteration assignment + chart history. Treat all schema edits as **rare, idempotent, ID-stable**: resolve & cache IDs, **diff before mutate**, never blind re-PUT.
4. **Metered Claude can silently stop.** Any future AI Action draws the separate Agent-SDK credit pool that drains first and stops without erroring. Every metered step uses a **dedicated spend-capped Console key**, **fails loud** (post "AI unavailable" + block), and is gated behind an explicit label.

## Goal & non-goals

**Goal:** A self-contained plugin that (a) scaffolds a GitHub Project + repo templates + deterministic automation across the org, (b) does AI-assisted intake into tiered, AC-bearing issues, (c) tracks the full branch→PR→staging→prod lifecycle on the board with zero hand-maintenance and **minimal coupling** to existing CI/CD, and (d) keeps stakeholders current via always-live native surfaces — the project **Status update**, the **Gantt-signal item fields**, the **Roadmap view**, and **Insights charts** — never a hand-kept Gantt or a periodic digest.

**Boundaries / non-goals (do NOT build in Phase 1):**
- **No implementation engine; depends on spec-ops only for the WHAT.** Delegates spec/AC **authoring + hardening + verification** to spec-ops (`write-spec`/`refine-spec`/`verify-spec`). Never dictates *how* to implement, and **does not depend on `launch-spec`** — implementation stays the dev's free choice.
- **No metered AI in core.** AC-review, auto-implement, and AI report narratives are **future phases** behind budget rails.
- **No digest/periodic report.** Stakeholder insight is **always-live native surfaces** (project Status update + signal fields + Roadmap + Insights), never a generated report.
- **No forced edits to existing CI/CD.** The board↔deploy bridge is an **opt-in composable action** a repo adds as one step; native built-ins cover the baseline with zero setup.
- **No multi-board abstraction.** GitHub only; one adapter (keep dry-by-default + degrade-don't-fail).
- **No markdown-canonical sync, no folder-as-stage, no central PM repo, no `index.md`.** Dropped from pm-ops (the Project replaces them).
- Do not modify spec-ops. Do not touch existing plugins beyond marking pm-ops deprecated in `marketplace.json`.

## Locked decisions

| Decision | Choice |
|---|---|
| Plugin name | **`gh-projects`** (new; pm-ops deprecated, mechanics salvaged) |
| Source of truth | **Hybrid** — issue/Project item canonical; markdown deep-spec linked for **T3 only** |
| spec-ops | **Delegate for the WHAT** — owns `write`/`refine`/`verify` + the spec/AC format; gh-projects depends on its authoring half, **not** `launch-spec` |
| Status options | `Backlog → Ready → In Progress → In Review → On Staging → Done` (+ `Blocked` flag-state) |
| Cadence | **2-week** iterations; Milestone = release; plan *direction* a quarter out, *detail* one cycle out |
| Sizing | `S/M/L` appetite, **no betting**; phases **suggest** size + drive an **Epic-split signal** |
| **Field homes** | **3 homes** — Issue **Type** (taxonomy) · org **Issue Fields** (Priority/Start/Target — org-wide, searchable) · **Project** single-selects (Size/Tier/Rigor/Blocked/signals — board-local) |
| **Board↔deploy** | Native built-ins + `board-sync.yml` (events) + an **opt-in composable `board-status` action** (one step in a deploy job for deploy-accurate On Staging/Done); no forced CI/CD edits |
| **Merge & close** | no-squash via **free repo setting**; review/checks = convention + `guard.sh` (rulesets need a paid plan we don't have); items are **never auto-closed by `Closes #N`** — closed at prod by `board-status` |
| **Releases** | real GitHub Release + auto-notes cut at prod deploy; **Milestone = planning %**, **Release = shipped artifact** |
| Prod gate | **PM or senior lead only** — actor-ID allowlist at the **OIDC deploy role** (`actor_id` condition, hard) + in-workflow allowlist (soft) + **tag-must-point-at-`main`** on a manual `workflow_dispatch`. Environments required-reviewers are GHEC-only for private repos, so *not* the gate. |
| Stakeholder surface | **Live native surfaces** — project Status update + Gantt-signal fields + Roadmap + Insights; **no digest** |
| Automation auth | **GitHub App** (Projects writes) now; **spend-capped Console `ANTHROPIC_API_KEY`** when metered AI ships |
| Phase 1 scope | Deterministic, free GitHub-native loop; metered AI deferred |

## Architecture overview

```mermaid
flowchart LR
  dump["unstructured dump"] -->|intake-issues| issue["GitHub Issue<br/>(canonical: AC, phases, boundaries, fields)"]
  issue -->|route-issue| board["Projects v2 board (org, cross-repo)"]
  issue -. T3 only .-> spec["linked deep spec"]
  dev["any dev / any impl"] -->|branch-from-issue → PR| pr["PR (linked, no auto-close)"]
  pr -->|push/PR events| sync["board-sync.yml"]
  sync -->|GraphQL (App token)| board
  deploy["existing deploy workflows"] -->|+ board-status step| board
  cron["signals-sync.yml"] -->|lib/dag + lib/gh| signals["signals + Blocked"]
  signals --> views["live views"]
  signals --> status["project Status update"]
  board --> views
```

The Project is **org-owned and spans all repos** (one board; the 50k-item cap binds, not a repo count). `scaffold-repo` replicates the whole board from a golden template via **`copyProjectV2`**.

## Data model — field schema

### Field homes (three)

- **Issue Type** (org, ≤25): the work taxonomy — `Feature/Bug/Chore/Infra/Epic`.
- **Org Issue Fields** (≤25/org, searchable, cross-repo, immune to project-copy/option-ID churn): org-wide typed attributes — **Priority, Start date, Target date**. Surfaced as Project columns (private projects — ours are private).
- **Project single-selects** (live in the golden template, replicate via `copyProjectV2`): board-local plugin state — **Size, Tier, Rigor, Blocked, the Gantt-signal fields**.

Rule: org-wide typed attr → Issue Field; board-local/plugin state → Project field; taxonomy → Issue Type. Every signal single-select carries an **option `description`** documenting its derivation (self-documenting).

### Org Issue Fields

| Field | Type | Set by | Purpose |
|---|---|---|---|
| **Priority** | Issue Field · single-select | PM/lead | `P0–P3`; orders `Ready` |
| **Start date** | Issue Field · date | plan-sprint | Roadmap bar start |
| **Target date** | Issue Field · date | plan-sprint/lead | Roadmap target / deadline; feeds Schedule health & Slippage |

### Project fields (core)

| Field | Type | Set by | Purpose |
|---|---|---|---|
| **Status** | Single-select (built-in) | automation + humans | Lifecycle column & automation key |
| **Type** | Issue Type (org) | intake | `Feature/Bug/Chore/Infra/Epic` |
| **Size** | Single-select | intake (suggest) + human | `S/M/L` appetite (not points) |
| **Tier** | Single-select | intake | `T1/T2/T3`; T3 requires a linked deep spec |
| **Rigor** | Single-select | intake | `light/full` (salvaged pm-ops rubric) |
| **Sprint** | Iteration | plan-sprint | 2-week cadence; filter `@current/@next/@previous` |
| **Parent issue** | Built-in (Parent) | intake (Epic-split) | Epic grouping; feeds the sub-issue % rollup |
| **PM-ID** | Text | intake | Stable `PM-####` threading spec→issue→PR |
| **Spec** | Text (URL) | intake | Link to T3 deep spec; empty for T1/T2 |
| **Blocked** | Single-select | **auto** (`signals-sync` from blocked-by DAG) | `yes/no` flag-state; **derived** from native dependencies, not hand-set |

Built-in metadata also relied on: **Assignees, Milestone, Linked PRs, Sub-issue progress (`subIssuesSummary.percentCompleted`), Blocked-by/Blocking.**

### Project fields (Gantt-signal — power the live views + the project status post)

| Field | Type | Maintained by | Derivation |
|---|---|---|---|
| **Schedule health** | Single-select | **auto** | `On track / At risk / Blocked / Overdue / Done` |
| **Slippage** | Single-select | **auto** | `Not late / 1–2d / 3–5d / 1+wk / 2+wk` |
| **Slippage-days** | **Number** | **auto** | days past Target (unlocks Insights sum/avg, numeric sort/range) |
| **Blast radius** | Single-select | **auto** (`lib/dag`) | `None / Blocks 1 / Blocks many / Blocks release` |
| **Blast-count** | **Number** | **auto** (`lib/dag`) | # downstream items blocked (Insights sum/sort) |
| **Impact level** | Single-select | **human** | `Low / Medium / High / Release blocker` |
| **Decision needed** | Single-select | **human** | `No / Move date / Reduce scope / Reassign / Split / Unblock / Defer` |
| **Project Status update** | Project status post (`createProjectV2StatusUpdate`) | **auto** | Rolled-up health (`ON_TRACK/AT_RISK/OFF_TRACK/COMPLETE`) + start/target/body |

> **Auto** signals (Schedule health, Slippage, Slippage-days, Blast radius, Blast-count, **Blocked**, project **Status update**) are recomputed deterministically (GraphQL + blocked-by DAG math, **no AI**) by `signals-sync.yml` on events + a low-frequency cron — every view and the status post stay live. The two **human** fields (Impact, Decision needed) are deliberate PM/lead calls. **Status-update rollup:** any `Overdue` or `Blocked`-blocking-release ⇒ `OFF_TRACK`; any `At risk` ⇒ `AT_RISK`; release milestone closed ⇒ `COMPLETE`; else `ON_TRACK` — start/target from the active Milestone/Iteration + a deterministic one-line body.

**Hard limits:** 50 fields/project · **50k items (active+archive — archiving does *not* free headroom)** · 25 issue types/org · **25 Issue Fields/org** · 100 sub-issues/parent · **8-level sub-issue depth** · **50 issues/dependency-relationship** · 100 items/page · **GraphQL 10k pts/hr + 2k/min (App token); mutation = 5 pts; content-creation 80/min·500/hr** · **replicate via `copyProjectV2` from a golden template** (carries fields/views/workflows-except-auto-add/Insights — *not* items/collaborators/repo-links) · **NO ProjectV2 view mutations** (views ship only by template-copy; scaffold verifies presence) · **Insights has zero API** (UI-only playbook). Issue Fields surface as Project columns on **private** projects only.

## Sprints / milestones / releases

| Mechanism | Used for | Notes |
|---|---|---|
| **Iteration = Sprint** | 2-week cycle | Filter `@current`; roadmap lanes; calendar-contiguous (compute working-day capacity in `plan-sprint`) |
| **Milestone = Release plan** | `v1.4`, "Q3 launch" | Native %-complete (closed/total); per-repo (cross-repo rollup is plugin-computed) |
| **Release = shipped artifact** | the tag cut at prod deploy | Real GitHub Release + auto-generated notes (`.github/release.yml` categories); the free stakeholder changelog |
| **Target-date field = Deadline** | hard dates | Roadmap markers + past-due; feeds Schedule health/Slippage |

Cadence: ~3 milestone buckets a quarter out; detailed breakdown only one cycle ahead.

## Views (curated, each with one job)

**8 saved views** over the **one issue set**. The **slice panel** and **column counts** are exploited. `is:open` defines "active"; raw date-math gives a live backstop if the `signals-sync` cron stalls.

| # | View | Layout · Filter · Group/Slice · Sort · Cards/Fields | Audience — job |
|---|---|---|---|
| 1 | **Sprint board** | Board · `iteration:@current is:open` · cols=Status · **count ON** · manual rank · cards: Assignees, Size, Priority, Blocked | Devs — pull from Ready, WIP=1 |
| 2 | **My work** | Table · `assignee:@me is:open` · group=Status · sort Priority↑ then Target↑ | Devs — cross-sprint personal list |
| 3 | **Ready queue** | Table (manual rank) · `status:Ready is:open` · group=Priority | Lead — owns the gate & ordering |
| 4 | **Critical Path Board** | Board · `is:open` · cols=Schedule health · swimlane=Impact · **slice=Decision needed** · cards: Target, Assignees, Blast radius, parent, Blocked-by | Standup — what's on fire now |
| 5 | **Schedule Risk Table** | Table · `is:open schedule-health:Overdue,Blocked,At-risk` (backstop `target-date:<@today,@today..@today+14d`) · group=Milestone **count ON** · **slice=Impact** · sort Release→Target↑ | PM/founder — what to decide & what it breaks |
| 6 | **Epic Hierarchy** | Table **Show hierarchy ON** (preview; flat `type:Epic` fallback) · group=Milestone · fields: Sub-issue progress, Target, Schedule health, Impact | PM — epic rollup |
| 7 | **Intake & Hygiene** | Table · `is:open` · group=Status · **slice=Type** · saved searches: `status:Backlog no:assignee`, `no:target-date`, `no:sprint`, `status:Blocked` | PM — intake + trustworthy data |
| 8 | **Release Train Roadmap** | Roadmap · `target-date:*` · bars Start→Target · group=Milestone · **markers=milestones+iterations** · zoom=Quarter | Stakeholders — live timeline |

**Platform gaps (view playbook):** no `no:blocked-by` qualifier → the "blocked w/ no blocker" check stays a `lib/dag` scan; no `is:blocked` view-grouping → the derived `Blocked` single-select earns its place; **views are not API-mutable** → ship via `copyProjectV2`; scaffold only verifies presence.

## Insights & charts (the live numeric trend)

GitHub **Insights is free on all plans** (since Feb 2025) — no paid gate. **Read-only, UI-only, zero API** → ships as a click-through playbook (`templates/project/insights.md`); `scaffold-repo`'s dry-run manifest lists chart creation as a **manual post-step**. The **Number fields** (Slippage-days, Blast-count) make charts quantitative (sum/avg), not just issue counts. **History accrues from project start, never backfilled** → define Status + Iteration day one, never archive in-flight items. (Historical group-by works only on **stacked** layouts.)

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

## Dev lifecycle & board automation

**Conventions:** GitHub Flow. Branch **from the issue** (`gh issue develop` / dev panel → authoritative link + conventional name), short-lived. PR links to the issue **without `Closes #N`** (so merge doesn't close it; draft PR = In Progress, flips to In Review on `ready_for_review`). PR → CI → **one human approval (any peer)** → merge → **auto-deploy staging** (your `workflow_run`-after-CI) → exercise / AC-in-staging → **prod = manual tagged `workflow_dispatch`**, restricted to PM/lead by the **OIDC-role actor-ID allowlist** (hard) + in-workflow allowlist (soft) + tag-on-`main`. Feature flags keep `main` shippable. WIP=1 (2 max). **no-squash** enforced via the free repo merge-method setting.

### Board automation — three layers (loosely coupled)

1. **Native Project built-in workflows** (free, zero Actions, zero coupling) — enabled/configured at scaffold: Item added→`Backlog`; **PR merged → `On Staging`** (reconfigured from the default `Done`); Item reopened→`In Progress`. Baseline that needs no deploy-pipeline changes.
2. **`board-sync.yml`** (plugin-owned, event-driven, App token, no AI): `push` → `In Progress`; `pull_request` → `In Review` (draft honesty) + resolve the PR↔issue link (**linked-branch first, branch-name `123-foo` parse fallback**).
3. **Composable `board-status` action** (`templates/github/actions/board-status/`, opt-in, reusable): **self-contained** — it vendors its own minimal GraphQL resolution logic and does **not** import the plugin (CI has no plugin install). `scaffold-repo` installs it per-repo at `./.github/actions/board-status`, referenced as `- uses: ./.github/actions/board-status`. A repo adds it as **one step** in its existing deploy job to report a **deploy-accurate** status for the issues tied to the deployed SHA — `On Staging` on staging success, **`Done` + close + cut the Release** on prod success. (Optional upgrade: centralize in an org ops repo as `org/actions/board-status@vN` for single-source updates.) Existing pipelines are extended, never rewritten.

| Transition | Layer | Trigger | Mechanism |
|---|---|---|---|
| Item added → `Backlog` | Built-in | item added | free |
| `Backlog → Ready` | Manual | lead | gate + manual order |
| `Ready → In Progress` | Manual | dev self-assign + status | inversion |
| Branch pushed → `In Progress` | `board-sync` | `push` | resolve issue via linked-branch, else branch name |
| PR opened → `In Review` | `board-sync` | `pull_request:[opened,ready_for_review]` | draft=In Progress; non-closing link |
| PR merged → `On Staging` | Built-in | PR merged | free; item stays **open** |
| Staging deploy success → `On Staging` | `board-status` (opt-in) | step in deploy-staging | deploy-accurate upgrade over the built-in |
| Prod deploy success → `Done` + close + Release | `board-status` (opt-in) | step in deploy-prod | resolves shipped issues (SHA→PRs→issues), sets Done, closes, publishes the tag's Release |
| Item reopened → `In Progress` | Built-in | reopened | free regression handling |
| Signals + project Status update refresh | `signals-sync` | `issues`/`pull_request` + cron | recompute signals incl. `Blocked` + post the project Status update |

All Project writes use the **GitHub App token** (constraint #2). **`projects_v2_item` gotcha:** never react to column moves (org-level, no repo trigger) — we drive from events + built-ins + the action. **Billing caution:** metered Claude is deferred; when added, dedicated spend-capped Console key + fail-loud.

## Requirement artifact — tiers, phases, sizing, AC

| Tier | Artifact | Deep spec? |
|---|---|---|
| **T1 trivial** | Issue body, **AC only**, 3–8 lines | No |
| **T2 standard** | Issue body **with phases + boundaries**, ~30–50 lines | No |
| **T3 complex** | Scannable issue body **+ linked `specs/<slug>.md`** | Yes |

**Issue body skeleton** (`templates/issue-body.md`): `Goal (1 line) → TL;DR → ## Acceptance Criteria → ⚠️ breaks-if-missed → Phases (each with an exit gate + its AC-ids) → Boundaries → Spec link (T3)` — AC directly after TL;DR (matches the spec-ops layout).

**Phases & sizing:** `intake-issues` enumerates phases (each a shippable gated increment), counts them, **suggests** `1→S / 2–3→M / 4+→L` (human-confirmed), and at >~3–4 phases **recommends an Epic split** (one sub-issue per phase, via `addSubIssue`). Deterministic `lib` helper; no spec-ops involvement.

**Acceptance Criteria (mandatory to enter `Ready`):** a flat list of **atomic, observable end-states** ("X is true", never a task), each with a **stable item-scoped id** (`AC-1…`; globally `PM-####/AC-N`). **Enumerated exhaustively, never condensed** — the "digestible" rule applies to *prose only* (mirrors spec-ops `AC-7`). Each AC may carry an **optional `verify:` handle** (a concrete observable) that augments — never replaces — the end-state. The `AC-id` set is the **co-owned contract** for the deep spec, `verify-spec` claims, and the future AI PR review. `intake-issues` **refuses `Ready`** for prose-only/unverifiable AC (the board-side `ac_complete`).

**Sync contract (one author, parity-enforced):** shared `AC-id` namespace across issue ↔ deep spec ↔ `verify-spec`. **T1/T2** — AC in the issue only. **T3** — AC authored once in the spec-ops spec (its `## Acceptance Criteria`) and **mirrored to the issue**; spec carries `issue: org/repo#NNN`, issue carries the `spec:` link; CI fails on **`AC-id` set divergence** or a 404 `spec:`. Anchor specs by **symbol name, not line number**.

## Plugin shape

**Versioning:** `plugin.json` = `name`+`description` only; bump `version` in root `marketplace.json` (start `0.1.0`). Reuses pm-ops's deterministic mechanics; delegates spec authoring to spec-ops.

### Skills (Phase 1)

| Skill | Purpose | Invocation |
|---|---|---|
| `scaffold-repo` | **`copyProjectV2` from the golden template**, then API-only setup: ensure org Issue **Types** + Issue **Fields** (Priority/Start/Target), link repos, **recreate per-repo Auto-add** (not copied), re-anchor iteration, **re-resolve IDs against the copy**, set base role=Read / Write-to-team, **grant App access**, **set repo no-squash merge setting**, write issue forms / PR template / `board-sync.yml` / `signals-sync.yml` / the `board-status` action / `release.yml` / CODEOWNERS, and the project **README** + Insights/view playbooks. Idempotent, dry-run manifest, `--force` | **Explicit** |
| `intake-issues` | Dump → tiered, field-complete issues; **delegates body + AC to `spec-ops:write-spec`** (+`refine-spec` if `rigor: full`); size suggestion + Epic-split (`addSubIssue`); dry-runs before any `gh issue create` | **Model-invocable** |
| `plan-sprint` | Assign issues to current Iteration + Milestone, working-day capacity, order `Ready`; dry-by-default | **Explicit** |
| `route-issue` | Project an issue + populate fields via the engine (GraphQL); create the linked branch; skill-scoped guard | **Explicit** |
| `promote-pr` | Track branch→PR on the board; open/update PR (linked, non-closing); guard blocks `--squash` & prod actions without green checks | **Explicit** |
| `sync-signals` | On-demand recompute of the auto signals (incl. `Blocked`, Number fields) **+ post the project Status update** | **Explicit** |

### lib/ (Python stdlib only; exit codes 0/2/3/1)

- `lib/gh.py` — GraphQL/REST core: resolve+cache project/field/option/iteration IDs; two-phase add→read-itemId→update; `addProjectV2ItemById`, `updateProjectV2ItemFieldValue`, `copyProjectV2`, `updateProjectV2` (readme/desc), iteration create/edit (⚠️ replace-all), `createProjectV2StatusUpdate`, `addSubIssue`, `createLinkedBranch`, org Issue Type/Field ensure, repo merge-method setting, `gh release create` + `release.yml`. Assignees/Labels/Milestone need their own mutations. **Degrade: native `gh ≥ 2.94` → GraphQL → (no label fallback).**
- `lib/pm.py` — `PM-####` allocator + registry; flow-style front-matter parse/serialize/normalize (T3 specs).
- `lib/scaffold.py` — template substitution + idempotent file install (manifest-first; iterations diff/skip, never blind re-PUT).
- `lib/dag.py` — native blocked-by → `Blocked` + Blast radius + Blast-count + ordering/critical path; feeds signals.
- `lib/engine.sh` — collapsed single GitHub adapter; dry-by-default rail.

### templates/

- `github/actions/board-status/` — the **self-contained composable action** (vendors its GraphQL/resolution logic, no plugin import; inputs: project, status, sha/issue refs, app token; resolves shipped issues, writes Status, optionally closes + publishes Release). Installed per-repo at `./.github/actions/board-status`.
- `github/workflows/`: `board-sync.yml`, `signals-sync.yml` (Phase 1). Disabled/labeled for later: `pr-ac-review.yml`, `auto-implement.yml`.
- `github/ISSUE_TEMPLATE/`: `feature/bug/chore/infra.yml` + `config.yml` (**`blank_issues_enabled: false`**) — issue forms with required Type/Size/Priority.
- `github/PULL_REQUEST_TEMPLATE.md` — non-closing `Relates to #N` (+ linked-branch), AC checklist ref, staging-URL.
- `github/release.yml` (note categories: Feature→Features, Bug→Fixes, Infra/Chore→Other) · `github/CODEOWNERS` (governance paths: `specs/**`, `.github/workflows/**`, `project/*.json`).
- `project/{fields,iterations}.json` (golden template) · `project/README.md` (board legend) · `project/insights.md` (chart playbook) · `project/views.md` (catalog + edit-the-template fallback) · `project/labels.json` (operational + release-category labels).
- `issue-body.md`, `deep-spec.md` — the tier skeletons.

### hooks/ & rules/

- `hooks/guard.sh` — skill-scoped **PreToolUse** (route-issue/promote-pr): fail-open on non-match, **block** `--squash`, prod actions without green checks, or raw `gh` board mutations. Plugin-scoped fast-fail (not org enforcement — rulesets unavailable on our plan).
- `rules/github-fields.md` (constraints #1–#4 + field/option-ID + field-homes discipline), `rules/repo-conventions.md`, `rules/ac-rubric.md`, `rules/tier-rubric.md`.

### Delegation to spec-ops (the WHAT)

The **`AC-id` contract + spec/AC format are the pinned, stable interface** — spec-ops internals may churn without breaking gh-projects.

| Need | Delegate to | Consumes |
|---|---|---|
| Author spec body + AC list | `spec-ops:write-spec` | Short spec → issue body (T1/T2); full → linked spec (T3) |
| Harden to zero-missed-detail | `spec-ops:refine-spec` (if `rigor: full`) | "ready"/`ac_complete` → flip `Ready` |
| Verify impl vs AC (future) | `spec-ops:verify-spec` | One claim per `AC-id`; zero `contradicted` = AC-clean |

**Not delegated:** `launch-spec` (HOW). gh-projects owns all GitHub writes; spec-ops never touches a branch/issue/board.

## Future phases (metered AI — deferred, behind budget rails)

| Capability | Approach | Guardrails |
|---|---|---|
| **AI PR review vs AC** | `pr-ac-review.yml`: extract closing issue's `AC-id` list → **composes `verify-spec`'s claim-per-`AC-id` grounding** (else grounds itself) → `pass/fail/uncertain` → label + sticky comment | Read-only tools; UNVERIFIED blocks as hard as FAIL; skip on `NO_AC`; capped Console key; block-merge fallback on credit exhaustion |
| **AI auto-implementation** | `auto-implement.yml` behind an `auto-implement` label → draft PR; compose with worktree-ops | Opt-in label; cap turns/model/timeout; small batches; human validates each slice |
| **AI report narrative** | Thin layer over the live views | Live views primary; narrative never canonical |

## Phase 0 — prerequisites (one-time, human/org; before P1.0)

External to the plugin; these must exist before scaffolding works. (Realizes the prereqs assumed by AC-1, AC-7, AC-10.)

- **0.1 — GitHub App.** Create an **org-owned GitHub App** with: Projects **read/write** (org), repo **Contents / Issues / Pull requests** read/write, and **Administration** read/write (to toggle the merge-method setting). Install it on the org (all or selected repos). Store the **App id + private key** as org/repo Actions secrets; workflows mint an **installation token** (constraint #2). *Exit:* a minted token writes a Project field.
- **0.2 — Golden-template Project.** Hand-build **one** org Project as the golden template: apply the §Data-model schema (`fields.json` fields/options/descriptions — these *can* be API-created via `lib/gh.py` to speed it) + the **Iteration** field, then **build the 8 views by hand** (views are *not* API-creatable — the one irreducibly manual step), and mark the Project an **org template**. `scaffold-repo`'s `copyProjectV2` copies this. *Exit:* template Project exists with all fields + 8 views, marked a template.
- **0.3 — (deferred) Console API key.** Only when metered AI (P2) ships: a dedicated **spend-capped Console `ANTHROPIC_API_KEY`**. Not needed for Phase 1.

*Exit gate (Phase 0 → P1):* App installed + token writes a field; golden-template Project built + marked a template.

## Phase plan (each phase ships behind an exit gate)

| Phase | Delivers | Exit gate |
|---|---|---|
| **P1.0 Core** | `lib/gh.py` + `lib/pm.py` port + `lib/engine.sh` | (needs Phase 0 App + a test project) Resolves & caches a real project's IDs; round-trips one field write; unit-tested helpers |
| **P1.1 Scaffold** | `scaffold-repo` (golden-template copy) + Issue Types/Fields + no-squash setting + issue forms + PR template + CODEOWNERS + README + `board-status` action + `release.yml` | Clean repo gets full schema + 8 views + iteration + org Issue Fields + the action/templates; re-run **diffs/skips** (iterations never blind re-PUT) and re-resolves IDs |
| **P1.2 Intake** | `intake-issues` (tiers, phases, size+split, machine-verifiable AC) | A dump → tiered issues; prose-only AC is **refused** `Ready`; phases drive size + Epic-split |
| **P1.3 Board sync** | `board-sync.yml` + native built-ins (PR-merged→On Staging) + the `board-status` action | Push/PR move Status; PR↔issue link resolves (linked-branch→branch-name); adding the action step yields deploy-accurate On Staging/Done+close+Release; zero AI |
| **P1.4 Route & promote** | `route-issue`, `promote-pr`, `guard.sh` | Issue projects with all fields; linked branch created; guard blocks `--squash`/unsafe prod |
| **P1.5 Signals, status & views** | `signals-sync.yml` + `sync-signals` + `lib/dag.py` + Number fields + 8 views + Insights playbook | Auto signals (incl. `Blocked`, Slippage-days, Blast-count) recompute; project **Status update** posts; 8 views live; Insights applied manually |

**Deferred:** `plan-sprint` capacity-math refinements · metered-AI workflows (P2) · org-webhook→`repository_dispatch` assign-on-drag bridge · optional spec-ops handoff · cross-repo milestone rollup · server-side ruleset (**N/A until a paid plan**) · migrating Tier/Rigor/PM-ID/Size to org Issue Fields once that fits.

## Risks

| Risk | Mitigation |
|---|---|
| `projects_v2_item` inversion mis-wired | Drive from events + built-ins + the action; document in `rules/github-fields.md` |
| `GITHUB_TOKEN` can't write Projects v2 | GitHub App installation token from day one |
| Option-ID regeneration / **iteration replace-all** orphans items | Schema edits rare/idempotent; diff before mutate; scaffold skips existing iterations |
| **No ProjectV2 view mutations / Insights zero API** | Views ship via `copyProjectV2`; charts via manual playbook; signals + Status update carry what automation needs |
| **No rulesets on our plan** (no enforced review/required-checks for private repos) | no-squash via free repo setting; review/checks = convention + `guard.sh`; revisit if we upgrade |
| **Issue Fields surface as columns on private projects only** + newer feature | Keep projects private; verify column surfacing at scaffold; Size/Tier/Rigor stay Project fields |
| Required-reviewers GHEC-only → prod gate | actor-ID allowlist at the OIDC deploy role (hard) + in-workflow (soft) + tag-on-`main` (cars.bdv model) |
| AI accelerates throughput, degrades stability (DORA) | Staging-exercise + AC-in-staging gate; small batches; feature flags; human validates each slice |
| Self-assignment degenerates | Lead orders `Ready`; WIP=1; pull top-down |
| T3 issue↔spec `AC-id` drift | CI parity check on `AC-id` sets; AC authored once, mirrored |
| GraphQL point budget | App = 10k/hr + 2k/min; cache IDs; incremental syncs; paginate ≤50; mind content-creation 80/min in intake |

## Open / parameterized (decide at build/scaffold time)

1. **First `scaffold-repo` target** — which repo(s) + the golden-template Project to stand up first. (`board-status` action home **resolved**: per-repo local install by default; org ops-repo centralization is an optional later upgrade.)
2. **Assign-on-drag** — keep the inverted assign-first model (default), or later add the org-webhook→`repository_dispatch` bridge.
3. **AC-review merge gate (P2)** — advisory-first (no rulesets to hard-block on our plan); hard-block only if we upgrade.
4. **Prod-gate enforcement (confirmed)** — actor-ID allowlist at the OIDC deploy role + in-workflow allowlist + tag-on-`main` (cars.bdv `deploy-prod.yml`); keep the allowlist in sync between workflow and OIDC role.
5. **Project visibility** — default **private** (a one-time human security decision, not automated). CSV export, merge queue, and MCP Projects tools are **deferred** (manual/lossy / overkill at WIP=1 / keep deterministic GraphQL).
