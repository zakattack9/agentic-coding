# GitHub-Native PM & Lifecycle Plugin — Synthesis & Build Plan

> Lead-synthesizer document combining seven research findings (pm-ops audit, spec-ops audit, example-spec analysis, GitHub Projects v2 capabilities, GitHub Actions + claude-code-action, plugin authoring, startup agentic practices). It is the single guide for building the new plugin that runs a 4-engineer startup's entire software lifecycle on GitHub Projects.

---

## 1. Executive summary

The team is migrating off Kanboard to run its **entire lifecycle on GitHub Projects v2**, with the GitHub **issue as the atomic, canonical unit** and the board as a live, automation-driven projection of issue/PR/deploy events. The two existing plugins split cleanly: **pm-ops's architecture is the inverse of what this team needs** (markdown-canonical, board-as-projection-of-markdown, folder-as-stage, central-repo aggregation, one-way push, `gh`-CLI-only, no GraphQL/Actions/PR/deploy awareness) and should be **deprecated**, while its **mechanics are gold** (stable `PM-####` ids, rigor rubric, dry-by-default rail, deterministic stdlib scripts, typed flow-style front-matter, idempotent scaffolding, the engine/capability contract). **spec-ops is kept untouched and delegated to** for full-feature spec authoring/hardening/verification — it is the team's grounded-against-reality IP and must not be duplicated; the new plugin only needs a **short-form intake path** spec-ops lacks and a **machine-readable acceptance-criteria schema** that doubles as verify-spec's claim list.

The recommended source of truth is a **hybrid**: the **GitHub issue + Project item is canonical**; markdown specs are demoted to **linked reference detail** for complex (Tier-3) work only. Requirements layer by complexity tier — most work is a scannable, AC-first, phased **issue body**; only cross-cutting work gets a linked deep spec. The board is driven **from git events** (`issues`/`pull_request`/`push`) writing status *into* the Project via GraphQL — inverting `projects_v2_item` rather than reacting to it, because that event is **org-level and cannot trigger repo workflows**. Every metered Claude call is **budget-guarded with a deterministic fallback**, because the June 2026 Agent-SDK credit split (paused, not cancelled) can silently stop automation mid-sprint. Process stays light: one shared backlog, a lead-owned `Ready` gate, WIP=1 self-assignment, GitHub Flow → auto-staging → one-click prod, S/M/L appetite, 1–2 week cycles, and a generated stakeholder digest instead of a hand-kept Gantt.

---

## 2. Current-state assessment: pm-ops & spec-ops

Verdicts are per *component*, not per *plugin* — pm-ops is dropped as an architecture but mined for mechanics.

| Component | Plugin | Verdict | Rationale |
|---|---|---|---|
| Stable `PM-####` id allocator + registry counter | pm-ops | **KEEP** | A human id surviving issue renames/transfers threads spec→issue→PR; reuse the deterministic allocator, change only where canonical state lives. |
| Rigor rubric (`light` vs `full`) | pm-ops | **KEEP** | Pure decision logic, board-independent; maps 1:1 to a `Rigor` single-select field. |
| Engine/capabilities contract + dry-by-default rail | pm-ops | **KEEP (collapse runtime)** | Verb interface, degrade-don't-fail, paste-ready, dry-by-default are the right shape for a thin GitHub adapter; drop the multi-board dispatcher indirection. |
| Typed flow-style front-matter parse/serialize/normalize | pm-ops | **KEEP** | The field set *is* the Project custom-field schema; the YAML-subset parser is reusable for in-git specs. |
| Idempotent `cmd_init` scaffolder pattern | pm-ops | **KEEP (repurpose)** | Repurpose to scaffold a GitHub Project + issue/PR templates + Actions workflows across the org. |
| `candidate.md` / `spec.md` templates (TL;DR/AC/out-of-scope/checklist) | pm-ops | **KEEP** | Good "short, digestible" shape; reuse as issue-body template + issue form. |
| Markdown-canonical / "markdown wins" guardrail | pm-ops | **DROP** | Directly contradicts board-canonical; the issue is the atomic unit. |
| Folder-as-stage lifecycle (`STAGE_DIRS`, `git mv` between dirs) | pm-ops | **DROP** | Duplicates the Project `Status` field; also carries a latent `done`-stage gap. |
| `index.md` + `cmd_reindex` | pm-ops | **DROP** | Fully duplicated by a native Project table view. |
| Central PM repo as aggregation/board substitute | pm-ops | **DROP** | Projects v2 is org-level/cross-repo natively; the central repo re-implements it. |
| `repo_map`/`default_repo` engine-neutral routing + multi-engine dispatch | pm-ops | **DROP** | Over-generalized; GitHub is the only target (prior decision). Collapse to one adapter. |
| `gh`-CLI-only field resolution (N calls), no GraphQL/Actions/PR/deploy | pm-ops | **REFACTOR → GraphQL** | Needed for performance, `projects_v2_item` handling, PR/deploy tracking — all outside pm-ops's surface today. |
| `promote-spec` copy-and-stub across repos (three copies) | pm-ops | **REFACTOR** | Reduce to one canonical spec location linked from the issue's `Spec` field. |
| write/refine/launch/verify-spec + Stop-hook ledger + fresh-judge + grounding | spec-ops | **KEEP (delegate to, untouched)** | Core grounded-against-reality IP; the new plugin invokes it, never forks it. |
| launch-spec driver selection (`/goal`/`ultracode`/`/batch`, structural) | spec-ops | **KEEP (invoke)** | The right call for "how to implement"; invoke it rather than re-encoding. |
| spec-ops short-form / issue-body format | spec-ops | **GAP → BUILD NEW** | spec-ops only emits full multi-section specs; the new plugin owns intake → short issue body. |
| spec-ops machine-readable AC schema | spec-ops | **GAP → BUILD NEW** | No first-class AC field; build one that verify-spec can consume as its claim list. |
| spec-ops persistent structured hand-back | spec-ops | **GAP → SMALL EXTENSION** | "ready"/"verdict" live in a `/tmp` ledger deleted on success; capture from handoff or add a durable artifact to drive board automation. |

**Net:** Deprecate pm-ops as a *system of record*; lift its *mechanics* into the new plugin. Keep spec-ops as-is and delegate.

---

## 3. Central architectural decisions

Each decision states the recommended option, the runner-up, and the tradeoff.

### (a) Source of truth — GitHub Projects canonical vs markdown-canonical vs **HYBRID** ✅
**Recommend: Hybrid — the GitHub issue + Project item is canonical; markdown specs are linked reference detail for Tier-3 work only.**

| Option | Verdict | Tradeoff |
|---|---|---|
| Markdown-canonical (pm-ops today) | ✗ | Board edits by devs/PMs in the GitHub UI are lost on re-push; status drifts across three homes; no `projects_v2_item` representation. Inverse of what the team wants. |
| Projects-fully-canonical (everything in issues/fields) | ~ | Clean for short work, but Tier-3 architecture/migration/file-plan detail bloats an issue body; GitHub has no good home for a long spec except the issue body itself. |
| **Hybrid (issue canonical + linked deep spec)** | ✅ | One source of truth for **what done means** (issue: AC, Boundaries, sequencing); deep spec is demoted to *reference, pulled as needed*. Cost: a thin sync contract (CI check that spec↔issue links resolve and AC IDs exist) — cheap and worth it. The single-owner-plus-AI loop wants board, issue, branch, AC, and AI review in one GitHub-native loop, which argues decisively for issue-canonical. |

### (b) pm-ops — deprecate vs evolve → **DEPRECATE** ✅
**Recommend: Deprecate pm-ops; build a new plugin (`gh-lifecycle`) that lifts pm-ops's reusable mechanics.**

| Option | Verdict | Tradeoff |
|---|---|---|
| Evolve pm-ops in place | ✗ | Its load-bearing assumptions (markdown-canonical, folder-as-stage, central repo, one-way push, `gh`-only) are the *inverse* of the target; evolving means deleting most of its architecture while carrying its naming/docs baggage. |
| **Deprecate; new plugin lifts mechanics** | ✅ | Clean architecture, keeps the good scripts (id allocator, front-matter, rigor rubric, scaffolder, engine contract). Cost: a migration note + marking pm-ops deprecated in the marketplace; some one-time porting of `pm.py` helpers. |

### (c) spec-ops — integrate vs absorb → **INTEGRATE (delegate, untouched)** ✅
**Recommend: Integrate by delegation; do not absorb or fork spec-ops.**

| Option | Verdict | Tradeoff |
|---|---|---|
| Absorb spec-ops logic into the new plugin | ✗ | Duplicates the grounding engine, Stop-hook ledgers, fresh-judge — violates "define each shared skill in exactly one plugin." High maintenance, drift risk. |
| **Integrate via delegation** | ✅ | New plugin hands spec-ops a *spec body to author/harden/verify* and consumes back (ready spec, driver+driver-type, verify verdict). spec-ops never touches GitHub/branches/issues. Cost: one small extension — a durable, structured hand-back (ready/verdict) so board automation can poll it instead of scraping chat. |

### (d) Requirement layering — issue body vs linked deeper spec → **COMPLEXITY-TIERED LAYERING** ✅
**Recommend: Two layers gated by tier. Issue body is always the canonical "what done means"; a linked in-repo deep spec exists only for Tier-3.**

| Tier | Example | Artifact | Spec? |
|---|---|---|---|
| **T1 trivial** | "bump uploads dist to `PriceClass_All`" | Issue body, **AC only**, 3–8 lines | No |
| **T2 standard feature** | functional-requirements doc | Issue body **with phases + boundaries**, ~30–50 lines | No |
| **T3 complex/cross-cutting** | CDN fronting, shared-inbox PRD | Issue body (scannable top) **+ linked deep spec** + optional task ledger | Yes |

**Sync contract (prevents the triplication/drift seen in real docs):** ACs and Boundaries live in the **issue only**; the deep spec *references* them by ID (`see AC-3`), never restates. Sequencing lives in the **issue phase list only**. Deep spec carries front-matter `issue: org/repo#NNN`; issue carries `spec: specs/<slug>.md`. A cheap CI/GraphQL check fails the PR if a spec references a missing AC ID or the `spec:` link 404s. Anchor specs by **symbol name, not line number** (line numbers drift and lie).

---

## 4. Recommended GitHub Projects setup

### 4a. Custom-field schema

Use **Issue Type** (org-level, not labels) for the taxonomy so it is queryable; use single-selects for the rest. Design field/option edits as **rare, idempotent, ID-stable** operations — re-PUTting a single-select/iteration option list **regenerates option IDs and orphans existing assignments**.

| Field | Type | Purpose |
|---|---|---|
| **Status** | Single-select (built-in) | The lifecycle column; the workflow/automation key. Options kept short & consistent: `Backlog`, `Ready`, `In Progress`, `In Review`, `On Staging`, `Done` (+ `Blocked`). |
| **Type** | **Issue Type** (org, ≤25) | `Feature`, `Bug`, `Chore`, `Infra`, `Epic`. Native, filterable, independent of labels. |
| **Priority** | Single-select | `P0`–`P3`; drives manual ordering within `Ready`. |
| **Size / Appetite** | Single-select | `S` / `M` / `L` (appetite, **not** story points). |
| **Rigor** | Single-select | `light` / `full` — drives whether draft delegates to refine-spec (from pm-ops rubric). |
| **Tier** | Single-select | `T1` / `T2` / `T3` — drives whether a linked deep spec is required. |
| **Sprint** | **Iteration** | Recurring cadence (1–2 wk). Filter `@current`/`@previous`/`@next`. Note: iterations are calendar-contiguous (no weekend/holiday awareness) — compute working-day capacity in the plugin. |
| **Start date** | Date | Roadmap timeline start. |
| **Target date** | Date | Roadmap timeline target / hard deadline marker; past-due auto-flagged. |
| **PM-ID** | Text | Stable `PM-####` human id threading spec→issue→PR. |
| **Spec** | Text (URL) | Link to the Tier-3 deep spec (`specs/<slug>.md`); empty for T1/T2. |
| **breaks_prod** | Single-select | `yes` / `no` — scales AI-PR-review rigor (`yes` demands a run-it observable handle). |
| **AC status** | Single-select | `ac:passing` / `ac:failing` / `unverified` — written by the AC-review Action; merge gate. |

Also rely on built-in metadata fields (Assignees, Milestone, Linked PRs, Sub-issues progress, Blocked-by relationships). **Dependencies are metadata only** — they group nothing in views and drive nothing; the plugin must read the relationships and compute the DAG/critical-path itself.

**Hard limits to design around:** 50 fields/project; 50,000 items/project (active+archive); 25 issue types/org; 100 sub-issues/parent; 50 issues/dependency-relation; 100 items/page; 5,000 GraphQL points/hr. There is **no native Project-template for the field schema** — replicate org-wide by re-running `createProjectV2*` GraphQL mutations.

### 4b. Iteration / sprint + milestone model

Three independent mechanisms, each used for exactly one intent (don't overload one field):

| Mechanism | Used for | Why |
|---|---|---|
| **Iteration field = Sprint** | 1–2 week cadence/cycles | Recurring, filterable `@current`, renders as roadmap lanes. No native rollup. |
| **Milestone = Release** | `v1.4`, "Q3 launch" | The *only* native % complete (closed/total). Per-repo only; cross-repo rollup is plugin-computed. |
| **Target-date field = Deadline** | Hard dates / individual scheduling | Free roadmap markers + past-due flag. |

**Cadence:** one Milestone per cycle named by date; **S/M/L appetite, never velocity**; a rolling **quarter** = ~3 milestone buckets ahead populated loosely. Plan *direction* a quarter out, *detail* only one cycle out — detailed month-ahead breakdown is waste once AI-accelerated scope shifts.

### 4c. Views (devs / PMs / stakeholders)

| View | Layout | Filter | Group by | Audience & purpose |
|---|---|---|---|---|
| **Sprint board** | Board | `Sprint = @current` | `Status` (columns) | **Devs** — pull top of `Ready`, WIP=1; the daily work surface. |
| **My work** | Table | `assignee:@me AND Status != Done` | `Status` | **Devs** — personal in-flight list. |
| **Ready queue** | Table (manually ordered) | `Status = Ready` | `Priority` | **Senior lead** — owns the gate; orders what enters/leads `Ready`. |
| **Triage** | Table | `Status = Backlog AND no:assignee` | `Type` | **PM** — backlog grooming/intake landing zone. |
| **Sprint health** | Table | `Sprint = @current` | `Status` (with number sums) | **PM** — capacity, blocked items, time-in-status (derived). |
| **Roadmap** | Roadmap (Start/Target + Iteration markers) | `Target date` set | `Milestone` (group rows) | **Stakeholders** — the live "Gantt-substitute": draggable bars + iteration/milestone markers + past-due flags. *No dependency arrows / critical path / burndown natively* — those are plugin-rendered (e.g. Mermaid in the digest). |
| **Releases** | Table | grouped by `Milestone` | `Milestone` | **Stakeholders/PM** — % complete per release. |

---

## 5. Dev lifecycle: branch → PR → staging → prod

**Conventions (GitHub Flow, no GitFlow):** branch from `main` (`feat/…`, `fix/…`), short-lived (hours–2 days → small batches); PR → CI → **AI review against AC** → **one** human approval (any peer, *not* required to be the lead — that recreates a bottleneck); merge → **auto-deploy to staging** → e2e + AC-in-staging check; **prod = one manual approval click** via a GitHub Environments "required reviewers" rule. Feature flags keep `main` always shippable. WIP=1 (2 max). Status options stay short: `In Progress → In Review → On Staging → Done`.

### 5a. Board transitions — automated vs manual

The load-bearing rule: **`projects_v2_item` is an org-level event that CANNOT trigger repo workflows.** So the board is driven **from** events that *do* trigger repo workflows (`issues`/`pull_request`/`push`) writing status **into** the Project via GraphQL — we invert the trigger rather than reacting to board drags. Reserve the org-webhook → `repository_dispatch` bridge for the *one* case that genuinely needs the move event (auto-assign whoever dragged to In Progress) — and prefer the inversion even there (assign-first, let a workflow set the column).

| Transition | Mode | Trigger | Mechanism / note |
|---|---|---|---|
| Item added → `Backlog`/`Todo` | **Auto** | Project built-in workflow ("Item added") | Free, no Actions minutes. |
| `Backlog` → `Ready` | **Manual** | Senior lead decision | The lead owns the gate; ordering is manual within the column. |
| `Ready` → `In Progress` | **Manual (recommended)** | Dev self-assigns + sets status | Inversion: assignment is the source of truth. (Auto-on-drag possible only via the org-webhook bridge — `projects_v2_item edited`.) |
| Assign mover on drag → In Progress | **Auto (bridge only)** | org webhook `projects_v2_item edited` → `repository_dispatch` | Only path that needs the move event; `--add-assignee` is idempotent. |
| Branch pushed → `In Progress` | **Auto** | `push` (feature branch) | Workflow resolves linked issue, writes Status via GraphQL. |
| PR opened → `In Review` | **Auto** | `pull_request: [opened, ready_for_review]` | Also auto-links PR↔issue (parse branch `123-foo`, inject `Closes #123` if absent — idempotent grep guard). |
| AC review verdict | **Auto** | `pull_request: [opened, synchronize]` → claude-code-action | Posts per-AC PASS/FAIL/UNVERIFIED; sets `ac:passing`/`ac:failing` label (merge gate). UNVERIFIED blocks as hard as FAIL. |
| PR merged → (advance) | **Auto** | `pull_request: [closed]` + `merged==true` | Project built-in "PR merged → Done" handles trivial; richer flow writes `On Staging` via GraphQL. |
| Merge → staging deploy → `On Staging` | **Auto** | `push: branches: [main]` / `deployment_status` | One Status write per pipeline stage = "tightly tracked on the board." |
| Staging green → prod | **Manual** | GitHub Environments required-reviewer click | The *entire* release process: one button gated on green staging. |
| Prod deploy → `Done` | **Auto** | `push: branches: [prod]` / `deployment_status` | Final GraphQL Status write. |
| Issue/PR closed → `Done` | **Auto** | Project built-in "Item closed" / "PR merged" | Free native workflows. |

**`projects_v2_item` gotcha (call-out):** A Status/column change fires `projects_v2_item edited` (with embedded prev/current `changes.field_value` since June 2024) at the **org** level — *not* an `issues` event, and **no `on: projects_v2_item:` exists in repo workflows**. Any "react to a column move" automation must either (A) bridge org-webhook → `repository_dispatch`, or (B) be inverted to fire on `issues`/`pull_request`/`push`. Recommendation: (B)+(C native workflows); reserve (A) for the one assign-on-move case.

**Token gotcha:** `GITHUB_TOKEN` **cannot write Projects v2 fields** — use a **GitHub App installation token** (org-scoped, ~15k/hr, survives staff departure) with `project` scope, not a personal PAT. `GITHUB_TOKEN`-created PRs also don't trigger downstream workflows.

**Billing-credit caution (call-out):** The June 2026 Agent-SDK billing split is **paused, not cancelled** — architect as if it returns. Programmatic Claude (Agent SDK / `claude -p` / Claude Code GitHub Actions) would draw a **separate, non-rolling monthly credit pool (~$20/$100/$200)** at API list rates that **silently stops when drained**. Also, GitHub Copilot code review **consumes Actions minutes (and AI credits) as of June 1 2026**. Mitigations baked into every metered workflow: (1) use a **dedicated, spend-capped Console `ANTHROPIC_API_KEY`**, not a subscription token, so cost is explicit and capped; (2) keep cheap deterministic work (status moves, label sync, "Done on merge") as plain Actions/GraphQL, never Claude calls; (3) gate auto-implement behind an explicit label/assignment; cap `--max-turns`, `--model`, `timeout-minutes`; (4) **fail loud, not silent** — detect empty action output, post "Claude unavailable (credits may be exhausted)", and **block merge / require human review** rather than silently passing; (5) surface remaining credit/minutes in the weekly digest.

---

## 6. Proposed plugin shape

**Name:** `gh-lifecycle` (new plugin; pm-ops deprecated). Reuses pm-ops's deterministic core + engine contract; delegates spec bodies/verification to spec-ops. **Versioning:** `plugin.json` carries `name` + `description` only (no `version` field); bump `version` in root `marketplace.json` on every change; start at `0.1.0`.

### 6a. Skills

| Skill | Purpose (one line) | Invocation |
|---|---|---|
| `intake-issues` | Turn an unstructured dump into structured, field-complete GitHub issues with **testable AC**; triage tier/size; refuse `Ready` without testable AC. | **Model-invocable** (read/draft heavy; dry-runs drafts before any `gh issue create`). |
| `plan-sprint` | Organize the sprint: assign issues to the current Iteration + Milestone, balance appetite/capacity, order `Ready`. | **Explicit** (`disable-model-invocation: true`; mutates iterations/milestones; dry-by-default). |
| `route-issue` | Project an issue onto the board and populate custom fields via the GitHub engine (GraphQL). | **Explicit** (mutates board; all writes via engine, never raw `gh`; skill-scoped PreToolUse guard). |
| `promote-pr` | Track branch→PR→staging→prod on the board; open/update PR, advance Status per stage. | **Explicit** (git/PR writes; guard blocks `--squash` and merge-to-prod without green checks; branch first). |
| `scaffold-repo` | Write Actions workflows + issue/PR templates into a repo and apply the Project field/view/iteration schema via GraphQL — for org replication. | **Explicit** (writes files + opens PR + GraphQL; idempotent, dry-run manifest, `--force` to overwrite). |
| `sprint-report` | Generate the stakeholder digest from a GraphQL board scan (shipped / in staging / blocked / next bets); cheap deterministic by default, optional Claude narrative. | **Explicit** (read-only board scan; posts an issue/comment). |

### 6b. lib/ scripts (deterministic, stdlib-only, distinct exit codes `0/2/3/1`)

- `lib/gh.py` — GitHub **GraphQL/REST core**: resolve project/field/option/iteration IDs (cache them), two-phase item add→read-itemId→update, `addProjectV2ItemById`, `updateProjectV2ItemFieldValue`, `addSubIssue`, `updateIssueIssueType`, `addBlockedBy`. Degrades (paste-ready when `gh` absent; label fallback on `gh < 2.94`).
- `lib/pm.py` (ported from pm-ops) — `PM-####` id allocator + registry; flow-style front-matter parse/serialize/**normalize** (drops unfilled `{{…}}`); reused for in-git Tier-3 specs.
- `lib/scaffold.py` — template substitution (org/repo/project numbers) + idempotent file install (manifest-first, never overwrite without `--force`).
- `lib/dag.py` — read blocked-by relationships, compute DAG / ordering / critical path (Projects does none of this natively); emit Mermaid for the digest.
- `lib/engine-dispatch.sh` (collapsed) — direct call into the single GitHub engine; keep the dry-by-default rail, drop multi-board indirection.

### 6c. Templates

- `templates/github/workflows/` — `board-sync.yml` (issue/PR/push → GraphQL Status writes), `pr-ac-review.yml` (claude-code-action AC verdict → label, read-only tools), `scheduled-report.yml` (cron digest, `workflow_dispatch` escape hatch), `auto-implement.yml` (gated, future). Comments document the `projects_v2_item` inversion, the GitHub-App token requirement, and the credit-pool caution.
- `templates/github/ISSUE_TEMPLATE/` — `feature.yml`, `bug.yml`, `chore.yml`, `infra.yml` + `config.yml` as **issue forms** (required dropdowns Type/Size/Priority → structured, filterable from day one), each embedding the AC-first/breaks-if-missed/boundaries skeleton.
- `templates/github/PULL_REQUEST_TEMPLATE.md` — `Closes #N`, AC checklist reference, staging-URL field.
- `templates/project/{fields,views,statuses}.json` — the Project schema (§4) applied via GraphQL (Projects has no file form).
- `templates/issue-body.md` + `templates/deep-spec.md` — the Tier-tiered skeletons the model fills (§4d / Finding 3): goal → TL;DR → ⚠️ breaks-if-missed → AC (Given/When/Then + `verify:` handle) → phases-with-gates → boundaries → spec link.

### 6d. Hooks

- `hooks/guard.sh` — skill-scoped **PreToolUse** rail (in SKILL.md frontmatter, live only during `route-issue`/`promote-pr`): jq-parse `tool_input.command`, **fail-open** on non-matching input, **block (exit 2)** on `--squash`, merge-to-prod without green checks, or raw `gh` board mutation that should go through the engine.
- (Optional, future) a **Stop**-style budget/fallback gate pattern, modeled on spec-ops's fail-safe/fail-open ledger hooks, ensuring a metered Claude step that returns empty is treated as "unavailable → block," not "passed."

### 6e. What it delegates to spec-ops (never reimplements)

| Need | Delegate to | Hand-back consumed |
|---|---|---|
| Author a full feature spec body (Tier-3) | `spec-ops:write-spec @specs/<slug>.md` | Markdown spec on disk. |
| Harden a spec to implementation-ready | `spec-ops:refine-spec` (only if `rigor: full`) | "ready" signal (ledger cleared) → flip issue Status. |
| Decide how to implement (driver) | `spec-ops:launch-spec` | Emitted `/goal`/`ultracode`/`/batch` driver + driver name → feeds the branch/PR wrapper. |
| Verify implementation against claims | `spec-ops:verify-spec` | Per-claim verdict + `/tmp` ledger; **zero `contradicted` = the AC-clean gate** → advance Status. |

The new plugin owns **all** GitHub writes (issue creation, fields, status, milestones/sprints, PR/staging/prod tracking, Actions). spec-ops owns **all** spec quality; it never touches GitHub, a branch, or an issue. (Small extension needed: a durable, structured ready/verdict artifact so board automation can poll instead of scraping chat.)

---

## 7. Future-phase plan

| Capability | Approach | Guardrails (from billing/DORA findings) |
|---|---|---|
| **AI auto-implementation of tasks** | `claude-code-action` in **automation/prompt mode** (or issue-assignment mode) implements a labeled issue → opens a **draft** PR. The plugin supplies the branch/worktree wrapper (compose with worktree-ops); the emitted spec-ops driver already inlines a verify-spec done-gate. | **Opt-in only** behind an `auto-implement` label/assignment (never every issue); cap `--max-turns`/`--model`/`timeout-minutes`; behind a feature flag; small batches (DORA: large AI batches tank stability); a single human still **orchestrates and validates** (delegation gap is 0–20% full handoff). |
| **AI PR review vs acceptance criteria** | `pr-ac-review.yml`: resolve the PR's closing issue, extract its `## Acceptance Criteria` section, pass to claude-code-action requesting a **structured JSON verdict** (`pass`/`fail`/`uncertain` + `unmet[]`); set `ac:passing`/`ac:failing` label + sticky comment; **UNVERIFIED blocks merge as hard as FAIL**. The stable AC IDs *are* the claim list — compose verify-spec's grounding, don't fork it. | **Read-only tools** (`Read,Grep,Bash`) so review can't push commits (known action bug); scale rigor by `breaks_prod` (`yes` → run-it observable handle); skip-don't-fail-open if `NO_AC_FOUND`; capped Console API key. |
| **Scheduled reports** | `scheduled-report.yml` cron (UTC) GraphQL board scan → status breakdown + shipped/staging/blocked/next-bets digest as an issue/comment; the Roadmap view is the live timeline. Lead with the **cheap pure-GraphQL** summary; reserve Claude for narrative only. | Cron is UTC, may be delayed/dropped, **auto-disabled after 60 days inactivity** → keep `workflow_dispatch`; surface remaining credits/minutes in the digest so a silent stop isn't a surprise; paginate beyond 100 items. |

---

## 8. Phased build plan

**Phase 1 — the spec/MVP should cover (the GitHub-native loop, deterministic-first):**
1. `lib/gh.py` GraphQL core (ID resolution + two-phase writes) + `lib/pm.py` port (ids, front-matter) + the single GitHub engine with dry-by-default and degrade-don't-fail.
2. `scaffold-repo` + `templates/project/*` and `templates/github/ISSUE_TEMPLATE/*` (issue **forms** with required Type/Size/Priority) + `PULL_REQUEST_TEMPLATE.md` — stand up the Project field schema (§4) and templates, idempotently, across the org.
3. `intake-issues` — dump → tiered, field-complete issue with **machine-readable AC** (Given/When/Then + `verify:` handle); delegate Tier-3 bodies to `spec-ops:write-spec`.
4. `board-sync.yml` — the **deterministic, free** board automation: `issues`/`pull_request`/`push` → GraphQL Status writes (In Progress / In Review / On Staging / Done), PR↔issue auto-link, using a **GitHub App token**. Plus enable the native Project workflows.
5. `route-issue` + `promote-pr` with skill-scoped `guard.sh` — project issues, track branch→PR→staging→prod.
6. The seven Project **views** (§4c) and the Iteration/Milestone model (§4b).

**Deferred to later phases:**
- `plan-sprint` capacity/working-day math and `lib/dag.py` critical-path + Mermaid rendering.
- `pr-ac-review.yml` (metered AI review) — ship *after* the AC schema is proven and the credit-guard/fallback pattern is in place.
- `sprint-report` Claude narrative (cheap GraphQL digest can ship in Phase 1; narrative is later).
- `auto-implement.yml` — last; only after AC review + verify-spec gate + budget guards are trusted.
- The org-webhook → `repository_dispatch` **bridge** (auto-assign-on-drag) — only if the team insists on board-drag-driven assignment; otherwise rely on the inversion.
- Durable structured hand-back extension in spec-ops (small, do when board automation needs to poll readiness/verdict).

**Rationale:** front-load the **free, deterministic** GitHub-native loop (intake → structured issues → board auto-sync → light gated flow) that delivers the "tightly tracked, light process" goal immediately; defer every **metered Claude** automation until the budget-guard/fallback rails and the AC schema are proven, so the credit pool can never silently stop core lifecycle tracking.

---

## 9. Risks & open questions

### Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **June 2026 credit split returns and silently stops automation mid-sprint** | High | Dedicated spend-capped Console API key; deterministic-only for cheap work; fail-loud + block-merge fallback; surface credits in digest. |
| **`projects_v2_item` inversion gotcha mis-wired** → board automation silently never fires | High | Drive from `issues`/`pull_request`/`push` + native workflows; document in `rules/github-fields.md` and workflow comments; reserve the bridge for one case. |
| **`GITHUB_TOKEN` can't write Projects v2** / PAT tied to a person | Med | GitHub App installation token with `project` scope from day one. |
| **Field-schema edits regenerate option IDs and orphan assignments** | Med | Treat schema edits as rare, idempotent, ID-stable; never blindly re-PUT option lists. |
| **DORA: AI accelerates throughput but degrades stability** | High | Mandatory staging-exercise gate + AC-in-staging; small batches; feature flags; one human validates each slice. |
| **AC authored as prose** → AI can't verify, humans skip | Med | `intake-issues` refuses `Ready` without testable Given/When/Then + `verify:` handles. |
| **Spec↔issue drift / triplicated AC** | Med | AC/Boundaries/sequencing live in the issue only; CI checks links + AC IDs; anchor specs by symbol. |
| **Self-assignment degenerates** (cherry-picking, WIP sprawl) | Med | Lead orders `Ready`; WIP=1 board convention; pull top-down. |
| **GraphQL rate/point budget on full board reads** | Low–Med | Cache field/option IDs; incremental webhook-keyed syncs; paginate at 50. |
| **claude-code-action review pushed commits (known bug)** | Low | Constrain review to read-only `--allowedTools`. |

### Open questions for the PM's decision

1. **Source-of-truth confirmation:** Do you accept the **hybrid** model (GitHub issue/Project item canonical; markdown deep spec only for Tier-3), or do you want issue-fully-canonical with *no* linked specs even for complex work?
2. **pm-ops deprecation:** Approve formally **deprecating pm-ops** (marketplace note + migration) and building a new `gh-lifecycle` plugin — or do you prefer evolving pm-ops in place despite the architectural inversion?
3. **Plugin name & scope:** Is `gh-lifecycle` the right name, or fold this into a `pm-ops` v2? Should spec delegation stay external to `spec-ops`, confirmed?
4. **Auth for automation:** Will you provision a **GitHub App** (org-scoped, survives staff departure) for Projects writes, and a **dedicated spend-capped Console `ANTHROPIC_API_KEY`** for metered Claude Actions (vs. a subscription token)?
5. **Cycle length:** **1-week or 2-week** iterations? (Drives the Iteration field config and report cadence.)
6. **Sizing scheme:** Confirm **S/M/L appetite** (no story points/velocity), and whether to adopt Shape-Up-style betting at the `Ready` gate.
7. **Status taxonomy:** Confirm the option set `Backlog / Ready / In Progress / In Review / On Staging / Done (+ Blocked)` — add/remove any? (Schema edits are ID-stable-sensitive, so lock this early.)
8. **Prod gate owner:** Is the **one-click prod approval** any peer, or must it be the **senior lead**? (Lead-only risks a bottleneck.)
9. **Auto-assign-on-drag:** Do you want the org-webhook → `repository_dispatch` **bridge** for "assign whoever drags to In Progress", or is the inverted "assign-first" model acceptable (avoids standing up a webhook relay)?
10. **AI gates phasing:** Ship **AI PR review vs AC** and **scheduled reports** in an early phase, or defer both until the deterministic loop + budget guards are proven? Should the AC-review verdict **hard-block merge** via branch protection from day one?
11. **AC-review-without-credits fallback:** When the credit pool is exhausted, should the gate **block merge and require human review** (recommended), or fail-open to keep velocity?
12. **Stakeholder Gantt:** Is the native **Roadmap view + generated digest** sufficient, or do stakeholders require true **dependency arrows** (an optional external Gantt overlay like Ganttify)?
13. **Org replication target:** Which repos/projects should `scaffold-repo` target first, and is there an existing "ops" repo to host the (future) webhook relay and central workflows?
