---
id: PM-0002
title: gh-projects — finish Phase 1 (workflow skills + guard activation + scaffold completion)
type: epic
tier: T3
size: M
status: ready
owner: PM
depends: [spec-ops, PM-0001]
parent_spec: ./gh-projects.spec.md
---

# gh-projects — Finish Phase 1 Spec

> Completes the Phase-1 surface of the `gh-projects` plugin. The AC-1..31 build (commit `3094da7`) shipped the deterministic core — `lib/` (`gh.py`/`pm.py`/`dag.py`/`scaffold.py`/`intake.py`/`engine.sh`), the `scaffold-repo` / `intake-issues` / `sync-signals` skills, the `board-sync` + `signals-sync` workflows, the self-contained `board-status` deploy action, the templates, and `hooks/guard.sh` — all behind 239 offline stdlib tests. This spec adds the **three remaining Phase-1 skills**, **activates the dormant guard**, and **completes three thin/missing `scaffold-repo` duties**. The original spec's **Future-phases (metered-AI)** section stays out of scope.

## TL;DR

- Add the three human-driven workflow skills — **`route-issue`** (project an issue + create its linked branch), **`plan-sprint`** (assign Iteration/Milestone/dates, capacity, reorder Ready), **`promote-pr`** (open/track the linked PR, advance Status, guard-protected non-squash merge) — as thin prose over a small set of new `lib` helpers.
- **`hooks/guard.sh` is built and unit-tested but never fires today** — it must be wired into `route-issue` + `promote-pr` frontmatter to activate (the guard guarantee breaks silently if missed → AC-25, AC-30).
- Every new Projects v2 write uses the **App installation token**, rides the **dry-by-default / `--force`** rail, and is **stdlib-only**; the existing 239 tests must stay green (→ AC-26, AC-28, AC-29, AC-31).
- Two scaffold "completions" are **smaller than they look** once grounded: the App already has org Projects-write **via its installation** (today's `grant_app_access` confirmation touch is *correct*), and a project's **org base-role is UI-only — no API** (AC-23).
- **Everything is idempotent** — re-running any skill or write verb with the same inputs is a clean no-op, never an error (AC-33). **All six skills run on `model: opus`** with per-skill `effort` (AC-34).

---

## Current state → Target

| Concern | Built today (commit `3094da7`) | This spec adds |
|---|---|---|
| Skills | `scaffold-repo`, `intake-issues`, `sync-signals` | `route-issue`, `plan-sprint`, `promote-pr` |
| `lib/gh.py` | `add_item`, `set_field`, `write_field`, `advance_status`+`STATUS_ORDER`, `create_linked_branch`, `add_blocked_by`, `add_sub_issue`, `create_status_update`, `set_repo_merge_method`, `copy_project`, `Project.resolve`, `get_app_token` | PR open/update (non-closing), PR check-state read, Milestone assign, board-item reorder, issue Assignee, repo→project link, project→team link |
| Deterministic planning math | `lib/dag.py` (Blocked / Blast radius / Blast-count) | `lib/sprint.py` (working-day capacity + Ready-order recommendation) |
| `hooks/guard.sh` | authored + unit-tested, **never fires** (no skill wires it) | activated via `route-issue` + `promote-pr` frontmatter |
| `scaffold-repo` duties | copy template, re-resolve IDs vs the copy, iterations diff/skip, ensure Issue Types/Fields, no-squash, install templates, `grant_app_access` (confirmation touch) | link repos to the Project · install `actions/add-to-project` for per-repo auto-add · link the Project to a team (write-to-team) · emit the org base-role as a manual step |
| `engine.sh` dispatch | `resolve · capabilities · token` | the new write verbs the skills call, all behind the same `--force` rail |

---

## Acceptance Criteria

> Atomic, observable end-states. The `AC` column is the bare number; cite ids elsewhere as `AC-1…`. **Verify** names a concrete, **offline** check (a stdlib-unittest fixture against an injected fake `gh`/GraphQL runner, or a grep) unless it explicitly needs a live org. The `needs §X` group edges are grounded: §2–§4 import the §1 lib; §5 is independent; §6 is cross-cutting. `launch-spec` phases the build by group.

### 1. lib extensions — start here
| AC | Criterion | Verify |
|----|-----------|--------|
| 1 | `lib/gh.py` opens an issue-linked PR with a **non-closing** reference (`Relates to #N`; never `Closes/Fixes/Resolves`), and **edits** the existing PR when one already exists for the branch (`gh pr create` / `gh pr edit`) | grep: no closing keyword in the PR path; fixture: create→edit round-trip on a fake runner |
| 2 | `lib/gh.py` reads a PR's aggregate check state (`gh pr checks --json` bucket, or GraphQL `statusCheckRollup.state`) and returns a `green / red / pending` verdict | green/red/pending rollup fixtures → expected verdict |
| 3 | `lib/gh.py` assigns a native **Milestone** to an issue via REST `PATCH /repos/{owner}/{repo}/issues/{n}` (repo-scoped milestone number), **idempotently** (a re-assign to the same milestone is a no-op) | assign + re-assign fixture → one effective write |
| 4 | `lib/gh.py` reorders a board item's manual rank via `updateProjectV2ItemPosition(projectId,itemId,afterId)` (omit `afterId` to move to top), an **App-token** write | reorder-sequence fixture → expected position mutation calls |
| 5 | `lib/gh.py` sets/removes an issue **Assignee** via its own mutation | add/remove-assignee fixture |
| 6 | `lib/sprint.py` computes a sprint's **working-day capacity** (working days in the Iteration window, weekends excluded) deterministically, no model call | date-window fixtures → expected working-day counts |
| 7 | `lib/sprint.py` returns a deterministic **Ready-order recommendation** — Priority↑ then Target↑, stable tiebreak — over a list of items | fixture list → expected order |

### 2. route-issue — needs §1
| AC | Criterion | Verify |
|----|-----------|--------|
| 8 | `route-issue` projects a given issue onto the org board (`add_item`, **reusing the existing board item if the issue is already added**), populates **Type/Size/Tier/PM-ID/Spec/Priority/Status** via the engine reading each back identical, and **optionally self-assigns the actor** (Assignee) — realizing the parent spec's "Ready → In Progress = dev self-assign + status" | fixture: field dump matches inputs; `--assignee` path sets the Assignee; re-add returns the same item id |
| 9 | `route-issue` creates the issue's **authoritative linked branch** (`create_linked_branch` — native `gh issue develop` when the installed `gh` supports it, GraphQL fallback) with a conventional name; a re-run **detects the existing linked branch and is a no-op** (never an error) | both capability paths → branch created/linked; re-run on an existing branch → no-op, exit 0 |
| 10 | `route-issue` advances Status only **monotonically** — a re-route never regresses an item already at/past the target (`advance_status`) | replay fixture → no backward Status write |
| 11 | `route-issue` is **dry-by-default** — previews the full projection + branch plan and writes nothing without confirm/`--force` | dry-run adds no item, sets no field, creates no branch |

### 3. plan-sprint — needs §1
| AC | Criterion | Verify |
|----|-----------|--------|
| 12 | `plan-sprint` assigns selected issues to the **current Iteration** (Sprint field; **active = the iteration whose `[startDate, startDate+duration)` window contains today**; if today falls in a gap, the **next upcoming** iteration; completed iterations excluded — all computable offline from the field config), assigns a **Milestone**, and sets **Start/Target dates** via the engine | iteration-window fixtures (in-window / gap / boundary) → expected active iteration; fields set match inputs |
| 13 | `plan-sprint` displays the sprint's **working-day capacity vs assigned load** and **warns on over-allocation** without hard-blocking | over-allocated fixture → warning emitted, plan still previewed |
| 14 | `plan-sprint` **reorders the Ready queue** to the §1 recommendation via `updateProjectV2ItemPosition` | fixture queue → expected reorder calls in recommended order |
| 15 | `plan-sprint` is **dry-by-default** — previews every assignment, date set, and reorder and writes nothing without `--force` | dry-run writes nothing |

### 4. promote-pr — needs §1
| AC | Criterion | Verify |
|----|-----------|--------|
| 16 | `promote-pr` opens/updates the issue-linked PR for the active branch with a **non-closing** link; when a PR already exists it **edits in place** and a no-diff re-run is a no-op (never a duplicate-PR error) | created/updated PR carries `Relates to #N`, no closing keyword; re-run with no change → no-op |
| 17 | `promote-pr` advances board Status across the PR lifecycle — `In Review` on a ready PR, holds `In Progress` while draft — **monotonically** | draft/ready fixtures → expected Status, no regression |
| 18 | `promote-pr` reads the PR's **check state** (AC-2) and **withholds** any merge/promote step while checks are red/pending, stating the reason | red-checks fixture → merge step withheld with reason |
| 19 | `promote-pr` performs a **non-squash merge** (`--merge`/`--rebase`) only on confirm/`--force` and only when checks are green; it never issues `--squash` (the guard, AC-25, hard-blocks `--squash`) | green fixture → merge offered (non-squash); squash attempt blocked by guard |
| 20 | `promote-pr` is **dry-by-default** — previews PR + Status + merge intent and mutates nothing without `--force` | dry-run mutates nothing |

### 5. scaffold completion — independent
| AC | Criterion | Verify |
|----|-----------|--------|
| 21 | `scaffold-repo` **links each target repo to the Project** via `linkProjectV2ToRepository(projectId,repositoryId)`, idempotently | post-scaffold: repo in the Project's linked repositories (live); offline: link mutation planned, no-op on re-run |
| 22 | `scaffold-repo` installs a per-repo **`actions/add-to-project`** workflow (a new `templates/github/workflows/add-to-project.yml`, pinned action SHA, App-token auth) so new issues/PRs in a linked repo auto-add to the board | post-scaffold: the workflow file is installed; a new issue auto-adds (live) |
| 23 | `scaffold-repo` **links the Project to the named team** via `linkProjectV2ToTeam` (write-to-team) when `--team` is given, and **emits the org base-role (Read) as a documented manual step** in the change manifest — because base-role is **UI-only, not API-settable**. The App's own project-write access is already provided by its org installation (confirmed by `grant_app_access`, not re-granted) | offline: team link planned when `--team` given + base-role manual step in the manifest; the App-access touch stays a confirmation, not a bare no-op masquerading as a grant |
| 24 | The scaffold completions are **dry-by-default**, **idempotent** (a second run is a no-op), and **diff-before-mutate** (no blind re-PUT) | re-run manifest empty for these duties |

### 6. guard activation & invariants — cross-cutting (hold across §1–§5)
| AC | Criterion | Verify |
|----|-----------|--------|
| 25 | `route-issue` and `promote-pr` frontmatter carry the **`hooks: PreToolUse` / matcher `Bash`** block pointing at `${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh` (the `worktree-ops` `pull-worktree`/`merge-worktree` pattern), so the guard is active **only while those skills run** — and it **blocks `--squash`**, **blocks a prod deploy/release without provably-green checks**, and **fails open** on unrelated input | frontmatter assertion + guard unit cases (squash blocked / prod-without-green blocked / unrelated allowed) |
| 26 | The **existing 239 offline tests stay green** and every new behavior above is covered by new offline tests (no regression) | full `python3 -m unittest discover` green |
| 27 | No new workflow or skill makes a **metered AI/model call** | grep across new skills + lib + the `add-to-project.yml` template |
| 28 | Every Projects v2 field/board write in the new code uses the **App installation token**; none use `GITHUB_TOKEN` (which cannot write org Projects v2) | token-usage grep |
| 29 | New Python is **stdlib-only**, returns exit codes `0/2/3/1`, and leaks no token/secret | exit-code + secret-scan tests |
| 30 | Items are **never auto-closed by `Closes #N`** in `route-issue`/`promote-pr` (closure stays the prod-time `board-status` job's responsibility) | grep: no closing keyword in the PR paths |
| 31 | New write verbs are reachable only through `lib/engine.sh`'s **`--force`** rail — nothing mutates GitHub without `--force` | dry-run invokes no mutation; `--force` does |
| 32 | The `gh-projects` version is **bumped** in root `marketplace.json` to ≥ `0.2.0` for this change | marketplace assertion |
| 33 | **Every skill and every lib write verb is idempotent** — re-running with the same inputs makes no further change and raises no error. A second `route-issue` / `plan-sprint` / `promote-pr` / `scaffold-repo` run is a clean **no-op**: an already-added item is reused, and an existing branch / PR / repo-link / team-link / assignee / milestone / board-position is **detected and skipped, never a 409/422**. (Realized by dry-by-default + monotonic Status + diff-before-mutate + existence checks in each new write verb.) | per-skill re-run fixture → empty change set, exit 0; each new write verb has a "second call is a no-op" test |
| 34 | **All six gh-projects skills declare `model: opus`** with a deliberate `effort:` — `route-issue` medium · `plan-sprint` high · `promote-pr` high · `scaffold-repo` medium · `intake-issues` high · `sync-signals` low. Only **two** existing skills change model (`scaffold-repo` sonnet→opus, `sync-signals` haiku→opus); `intake-issues` is **already** opus/high (assert, don't change) | frontmatter assertion across all six `SKILL.md` files |

---

## New lib surface

All new functions live in the existing `lib/` (stdlib only; the injectable `gh`/GraphQL runner used by the current tests stubs GitHub with no network; App token via `get_app_token()`; exit codes `0/2/3/1`). New write verbs are added to `gh.py`'s `build_parser` and dispatched through `lib/engine.sh` behind `--force`.

| Function (new) | Home | Mechanism (grounded) | AC |
|---|---|---|---|
| `open_or_update_pr(repo, head, base, issue_number, …)` | `gh.py` | `gh pr create`/`gh pr edit` with a **non-closing** `Relates to #N` body | AC-1, AC-16, AC-30 |
| `pr_check_state(repo, pr_number)` | `gh.py` | `gh pr checks --json` bucket (`pass/fail/pending`) → `green/red/pending` | AC-2, AC-18 |
| `merge_pr(repo, pr_number, method)` | `gh.py` | `gh pr merge --merge`/`--rebase` (never `--squash`); caller gates on green | AC-19 |
| `set_milestone(repo, issue_number, milestone)` | `gh.py` | REST `PATCH /repos/{o}/{r}/issues/{n}` `milestone` (repo-scoped number), idempotent | AC-3, AC-12 |
| `reorder_item(project_id, item_id, after_item_id=None)` | `gh.py` | `updateProjectV2ItemPosition` manual-rank reorder | AC-4, AC-14 |
| `set_assignee(repo, issue_number, login, remove=False)` | `gh.py` | issue Assignee add/remove | AC-5 |
| `link_repo(project_id, repo_id)` | `gh.py` | `linkProjectV2ToRepository` | AC-21 |
| `link_team(project_id, team_id)` | `gh.py` | `linkProjectV2ToTeam` (write-to-team) | AC-23 |
| `working_day_capacity(start, end)` | `sprint.py` | working days in the Iteration window (weekends excluded) | AC-6, AC-13 |
| `recommend_ready_order(items)` | `sprint.py` | deterministic Priority↑→Target↑ order | AC-7, AC-14 |

**Reuse, do not duplicate:** `add_item`, `set_field`, `write_field`, `advance_status`/`STATUS_ORDER`, `create_linked_branch`, `Project.resolve`, `get_app_token`, the `engine.sh` `--force` rail, and `hooks/guard.sh` already exist — the new skills call them. `grant_app_access` stays a **confirmation touch** (the App already has org Projects-write via its installation); it gains the `link_team` call but does **not** attempt a base-role mutation (none exists).

> **Do not mistake the existing stub for the team link.** `scaffold.py`'s current `_LINK_PROJECT_APP` GraphQL string is *aliased* `linkProjectV2ToTeam:` but its body is a bare `updateProjectV2(input:{projectId})` with **no team id** — it is the `grant_app_access` no-op confirmation, not a real link. `link_team` (AC-23) must be a **new** real `linkProjectV2ToTeam(projectId, teamId)` mutation; do not reuse `_LINK_PROJECT_APP`.

## New skills (all Explicit / `disable-model-invocation: true`)

| Skill | Model · Effort | Does | Reads |
|---|---|---|---|
| `route-issue` | opus · **medium** | Project one issue onto the board, populate its intake-time fields, optionally self-assign the actor, create the authoritative linked branch; dry-by-default; guard-scoped | `--owner --number --repo <issue> [--assignee]` (same flag convention as `scaffold-repo`/`gh.py`; no persisted config) |
| `plan-sprint` | opus · **high** | Assign issues to the current Iteration + Milestone, set Start/Target dates, show working-day capacity vs load, reorder Ready; dry-by-default | `--owner --number` + the issue set + iteration/milestone |
| `promote-pr` | opus · **high** | Open/update the linked (non-closing) PR, advance board Status across the PR lifecycle, surface check state, withhold + offer a guard-protected non-squash merge on green; dry-by-default; guard-scoped | `--owner --number --repo <issue/branch/pr>` |

All three set `disable-model-invocation: true` (Explicit, side-effecting). Effort is pinned to the skill's reasoning load: `route-issue` is a mostly-mechanical projection (medium); `plan-sprint` (capacity + ordering + bulk assignment) and `promote-pr` (merge-safety + check-gating + lifecycle) carry real judgment (high). Per AC-34 the existing skills are normalized to `model: opus` too — `scaffold-repo` (sonnet→opus, medium) and `sync-signals` (haiku→opus, low); `intake-issues` is **already** `model: claude-opus-4-8`/`effort: high`, so it is asserted, not changed.

**Field-home split (from the parent spec):** `route-issue` sets the **intake-time** fields (Type/Size/Tier/PM-ID/Spec/Priority/Status); `plan-sprint` owns the **scheduling** fields (Sprint/Milestone/Start/Target) and Ready order; `promote-pr` only touches **Status** (monotonic). Status order is `Backlog < Ready < In Progress < In Review < On Staging < Done`.

## Guard activation

`hooks/guard.sh` already enforces its two rules (no `--squash`; no prod deploy/release without provably-green checks), reads the attempted command from the PreToolUse event's `.tool_input.command`, and fails open on unrelated input. It is dormant because no skill registers it. Activate it by adding this block to **`route-issue`** and **`promote-pr`** `SKILL.md` frontmatter — the mechanism used by `worktree-ops`'s `pull-worktree`/`merge-worktree` (a `hooks:` block in SKILL.md frontmatter scopes the hook to only-while-this-skill-runs):

```yaml
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh"
```

`plan-sprint` does not deploy or merge, so it does **not** wire the guard.

---

## Boundaries

- **Do not touch spec-ops** or any other plugin. The only cross-plugin change is bumping `gh-projects` in root `marketplace.json` (AC-32).
- **Reuse the existing `lib`** — extend `gh.py`/`scaffold.py` and add `lib/sprint.py`; do not duplicate `add_item`/`set_field`/`advance_status`/`create_linked_branch`/`STATUS_ORDER` or re-implement the `engine.sh` `--force` rail or `hooks/guard.sh`. The new write verbs must match the existing lib's idempotency style (`advance_status` no-op past target, iterations diff/skip, `ensure_issue_type`/`set_repo_merge_method` idempotent) — AC-33.
- **Normalizing the two off-opus skills' `model` to opus is in scope** (a deliberate carve-in for AC-34): `scaffold-repo` (sonnet→opus) and `sync-signals` (haiku→opus); `intake-issues` is already opus/high. That frontmatter change is the only edit this spec makes to already-built skill behavior — do not otherwise change `scaffold-repo`/`intake-issues`/`sync-signals`.
- **Do not attempt an org base-role mutation** — it is UI-only (no GraphQL/REST surface); `updateProjectV2` has no base-role field. AC-23 emits a manual step instead. Likewise, **do not attempt to create the built-in Auto-add workflow via API** — there is none; AC-22 installs `actions/add-to-project` instead. **SHA-pin** that action — intentionally stricter than the existing first-party templates' tag pins (`actions/checkout@v4` etc.), since it is a longer-lived third-party supply-chain surface.
- **Out of scope (the original spec's Future phases — metered AI):** `pr-ac-review.yml`, `auto-implement.yml`, AI report narratives, and any model/Console-key wiring.
- **Out of scope (the original spec's own deferrals):** advanced `plan-sprint` capacity math beyond a working-day count; the org-webhook→`repository_dispatch` assign-on-drag bridge; cross-repo Milestone rollup; server-side rulesets.
- **The hard prod gate stays the consuming repo's deploy infrastructure** — the OIDC-role actor-ID allowlist and tag-must-point-at-`main` live in the repo's own deploy-prod workflow. This spec ships only the **soft, skill-scoped `guard.sh`** check; it does **not** add a `deploy-prod.yml` template (consistent with "extend existing pipelines, never rewrite").
- **Items are never auto-closed here.** Closure + Release stay the prod-time `board-status` action's job; `route-issue`/`promote-pr` use non-closing links only (AC-30).
- **No live-org mutations in tests.** Everything is verified offline against an injected fake runner + greps; the genuinely live-only checks (AC-21/22/23 post-scaffold state) are asserted by the planned-mutation/manifest offline and exercised at real scaffold time.

---

## Checklist

**`lib/gh.py` · `lib/sprint.py` (new helpers + verbs)**
- [ ] PR open/update (non-closing), check-state, non-squash merge, Milestone, item reorder, Assignee, repo-link, team-link — AC-1, AC-2, AC-3, AC-4, AC-5, AC-19, AC-21, AC-23
- [ ] `sprint.py` working-day capacity + Ready-order recommendation — AC-6, AC-7
- [ ] wire new write verbs into `build_parser` + `engine.sh` `--force` rail — AC-31
- [ ] App-token-only, stdlib-only, exit codes, no secret leak — AC-28, AC-29

**`skills/route-issue` · `skills/plan-sprint` · `skills/promote-pr`**
- [ ] `route-issue`: project + fields + linked branch, dry-by-default, monotonic — AC-8, AC-9, AC-10, AC-11
- [ ] `plan-sprint`: Iteration/Milestone/dates, capacity warn, Ready reorder, dry-by-default — AC-12, AC-13, AC-14, AC-15
- [ ] `promote-pr`: linked non-closing PR, Status lifecycle, check-gate, non-squash merge, dry-by-default — AC-16, AC-17, AC-18, AC-19, AC-20
- [ ] guard frontmatter block on `route-issue` + `promote-pr` — AC-25, AC-30

**`lib/scaffold.py` · `skills/scaffold-repo/SKILL.md` · `templates/github/workflows/add-to-project.yml` (completion)**
- [ ] link repos · install auto-add Action · link team + base-role manual step — AC-21, AC-22, AC-23
- [ ] dry-by-default + idempotent + diff-before-mutate — AC-24

**Cross-cutting (`lib/tests/` · all six `SKILL.md` · root `marketplace.json`)**
- [ ] new offline tests for every AC; existing 239 stay green — AC-26
- [ ] no metered AI anywhere new — AC-27
- [ ] per-skill + per-verb idempotency: re-run = no-op, no error — AC-33
- [ ] all six skills `model: opus` + per-skill `effort` (change only scaffold-repo + sync-signals; intake-issues already opus) — AC-34
- [ ] bump `gh-projects` to ≥ `0.2.0` — AC-32
