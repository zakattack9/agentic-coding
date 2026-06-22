# gh-projects

Run a small team's (≤4 engineers) **entire software lifecycle on GitHub Projects
v2** — deterministic, free, and GitHub-native. One org-owned board spans every
repo: AI-assisted intake into tiered issues with acceptance criteria, a structured
board, a light **branch → PR → staging → prod** flow tracked with zero
hand-maintenance, and always-live stakeholder surfaces (the project Status update,
Gantt-signal fields, the Roadmap view, Insights charts) — never a hand-kept Gantt
or a periodic digest. No metered AI: every moving part is plain Python + GraphQL.

## How it works (the mental model)

- **The GitHub issue is the canonical unit.** Issues carry typed fields and a
  grouped **Acceptance Criteria** table; the board is a live projection of
  issue / PR / deploy events, driven *into* the Project via GraphQL.
- **One org board, three field homes** — the work taxonomy is an **Issue Type**
  (`Feature/Bug/Chore/Infra/Epic`); org-wide attributes are **Issue Fields**
  (Priority, Start date, Target date); board-local state lives in **Project
  fields** (Size, Tier, Status, Blocked, and the auto Gantt signals).
- **The board stays current by itself** via three loosely-coupled layers (below);
  Status only ever advances `Backlog < Ready < In Progress < In Review < On Staging
  < Done`.
- **Signals are recomputed deterministically** (date math + the native blocked-by
  graph, no AI) so the Roadmap, Insights, and the project Status update are always
  live.

---

## Prerequisites (set these up before using the plugin)

### 1. Tooling

- **GitHub CLI (`gh`)** installed and authenticated (`gh auth login`). The plugin
  shells out to `gh` / `gh api`.
- **Python 3** (standard library only — nothing to `pip install`).
- **The `spec-ops` plugin installed.** `create-issues` delegates the issue body +
  acceptance-criteria authoring to `spec-ops`; without it, intake can't write issue
  bodies.

### 2. A GitHub App (one-time, org admin) — *required*

> **Step-by-step:** [`GOLDEN-TEMPLATE-SETUP.md`](GOLDEN-TEMPLATE-SETUP.md) §"Phase 0.0
> — Create the GitHub App" walks the full create → permissions → install → secrets flow.

`GITHUB_TOKEN` **cannot write Projects v2 fields** — a GitHub App installation
token is the only credential that can. Create an **org-owned GitHub App** with:

- **Projects:** read & write (org)
- **Repository:** Contents, Issues, Pull requests — read & write
- **Administration:** read & write (to toggle the repo no-squash merge setting)

Install it on the org (all or selected repos), then store its **App id** and
**private key** as org/repo Actions secrets so the installed workflows can mint an
installation token. (The token is never printed; the plugin scrubs secrets from all
output.)

### 3. A golden-template Project (one-time, by hand) — *required*

> **Full walkthrough:** [`GOLDEN-TEMPLATE-SETUP.md`](GOLDEN-TEMPLATE-SETUP.md) — the
> step-by-step build with API recipes and a clear map of what can vs. can't be
> automated. The summary below is the short version.

Build **one** org Project once (it must be an **org** — `Type`/`Priority`/dates are
org-only features — and **private**). A script does most of it:

1. `gh auth refresh -s project,admin:org`, then run
   [`lib/setup_board.py`](lib/setup_board.py) `--org <org> --title "…" --apply`. From
   `templates/project/*.json` it creates the private Project, the `Type` Issue Type,
   the Priority/Start/Target Issue Fields, **every project field including the `Sprint`
   iteration**, adds the org fields as columns, creates the **8 views with their visible
   columns**, and **marks it the org template** — dry-by-default, idempotent.
2. **Finish in the UI** (the script prints this list): edit the built-in **Status**
   options to the 6 stages · finish each view's grouping/slice/sort per
   [`views.md`](templates/project/views.md) · build the **3 Insights charts**
   ([`insights.md`](templates/project/insights.md)). These three have no API.

`scaffold-repo`'s `copyProjectV2` then carries the **fields and views** to every
scaffolded project — GitHub documents a project copy as preserving *"views and custom
fields."* **Insights charts are the exception:** they have no creation API *and*
GitHub does not document them as carried by a copy, so a scaffolded project may need
its charts rebuilt by hand from [`templates/project/insights.md`](templates/project/insights.md).
`scaffold-repo` verifies field/view *presence* after copying but cannot see charts
(Insights has no API) — confirm those by eye on each new project and recreate any that
didn't carry over.

### 4. The App token in your environment (for running the skills)

The skills write to the Project through the App token. Provide it one of two ways:

```bash
export GH_APP_TOKEN=<installation-token>        # if you already have one, or…
export APP_ID=<app-id>
export APP_PRIVATE_KEY="$(cat app-private-key.pem)"   # or: APP_PRIVATE_KEY_PATH=/path/to.pem
# optional, if the App has more than one installation:
export APP_INSTALLATION_ID=<installation-id>
```

`GITHUB_TOKEN` is explicitly rejected for Project writes.

---

## Setup: scaffold a repo onto the board

Run **`scaffold-repo`** once per org/repo to stand everything up — it copies the
golden template, re-resolves all IDs against the copy, ensures the org Issue Types
+ Issue Fields, sets the repo **no-squash** merge setting, links the repo (and
optionally a team) to the Project, and installs the per-repo automation (issue
forms, PR template, `board-sync.yml`, `signals-sync.yml`, the `add-to-project`
auto-add workflow, the `board-status` deploy action, `release.yml`, CODEOWNERS, the
board README).

```
scaffold-repo --org <login> --template "GitHub Projects Golden Template" \
              --title "<new project title>" [--repo owner/name] [--team <slug>]
```

Every mutating skill is **dry-by-default**: it prints the full change manifest and
writes nothing. Re-run with **`--force`** to apply. A second run is a clean no-op
(diff-before-mutate; iterations are never blind re-PUT).

> Note: the org **base role** for a linked team is UI-only (no API) — `scaffold-repo`
> emits it as a one-line manual step in the manifest.

---

## The skills

All skills are thin orchestrators over the deterministic engine (`lib/`), run on
`model: opus`. `create-issues` and the two read-only analysis skills
(`analyze-board`, `analyze-sprint`) are **Model-invocable**; the rest are
**Explicit** — user-invoked only.

| Skill | What it does | Invocation |
|---|---|---|
| `scaffold-repo` | Stand up the board + per-repo automation from the golden template (see Setup). Idempotent, dry-by-default. | Explicit |
| `create-issues` | Raw dump → tiered, field-complete issues. Delegates the body + acceptance criteria to `spec-ops`; sizes and Epic-splits from the AC-group count. Dry-runs before any `gh issue create`. | Model-invocable |
| `plan-sprint` | Assign issues to the current Iteration + Milestone, set Start/Target dates, show working-day capacity vs. assigned load (warns on over-allocation), and reorder the Ready queue. Dry-by-default. | Explicit |
| `start-issue` | Project one issue onto the board, populate its intake-time fields (Type/Size/Tier/PM-ID/Spec/Priority/Status), optionally self-assign, and cut its authoritative linked branch. Monotonic Status, dry-by-default, guard-scoped. | Explicit |
| `create-pr` | Open/update the issue-linked PR (non-closing `Relates to #N`), advance board Status across the PR lifecycle, surface the PR's check state, and offer a **non-squash** merge only when checks are green. Dry-by-default, guard-scoped. | Explicit |
| `sync-signals` | Recompute the auto Gantt signals (Schedule health, Slippage, Slippage days, Blast radius, Blast count, **Blocked**) from the blocked-by graph and post the project Status update. Also runs automatically via `signals-sync.yml` on events + cron. | Explicit |
| `analyze-board` | **Read-only** whole-program digest: rollup health, the critical chain (release-blockers that are themselves blocked), overdue × high-blast-radius items, intake-hygiene gaps, unassigned in-sprint work, stalled epics, and every `Decision needed ≠ No` — each line with its evidence and the one-command resolving skill. Never writes the board. | Model-invocable |
| `analyze-sprint` | **Read-only** current-iteration read: per-assignee working-day capacity vs load, over-allocation, what won't land this sprint, and a suggested rebalancing. Reuses the working-day capacity engine. Never writes the board. | Model-invocable |

---

## Everyday lifecycle

```
create-issues  →  plan-sprint  →  start-issue  →  (dev codes)  →  create-pr   →  deploy
     │               │               │              │                │             │
  tiered AC       Iteration +     board item +   board-sync.yml    PR + Status   board-status
  issues          dates + Ready   linked branch  moves Status      + green-gated  → On Staging
  on the board    order           (self-assign)  on push/PR        non-squash     / Done + Release
```

1. **Intake** — `create-issues "<dump or path>"` turns a brain-dump into tiered
   issues with acceptance criteria; prose-only / non-atomic items are refused
   `Ready` with a reason.
2. **Plan** — `plan-sprint --owner <org> --number <project#> …` schedules the
   current Iteration + Milestone + dates and orders the Ready queue by Priority
   then Target.
3. **Start work** — `start-issue --owner <org> --number <project#> --repo
   owner/name --issue <n> [--assignee <login>]` projects the issue, sets its fields,
   and creates the linked branch.
4. **Code** — push to the linked branch and open a PR; the board moves itself
   (`In Progress` on push, `In Review` on a ready PR).
5. **Promote** — `create-pr --owner <org> --number <project#> --repo owner/name
   --issue <n>` opens/updates the non-closing PR, holds the merge while checks are
   red/pending, and offers a non-squash merge when green.
6. **Deploy** — add the `board-status` action as one step in your deploy job to set
   `On Staging` on staging success and `Done` + close + cut the Release on prod
   success.
7. **Signals** — refresh on their own; run `sync-signals --owner <org> --number
   <project#>` to force a recompute + Status-update post.
8. **Analyze** (read-only) — `analyze-board --owner <org> --number <project#>` for
   the whole-program digest (what to decide / act on, each with a one-command
   resolving skill), and `analyze-sprint …` for the current-iteration capacity vs
   load. These only read and report — they never write the board.

Preview first, every time; add `--force` (or `--apply` for `sync-signals`) only
after reviewing the dry-run manifest. The `analyze-*` skills are read-only — no
`--force`.

---

## How the board stays live (three loosely-coupled layers)

1. **Native built-in workflows** (free, zero setup) — item added → `Backlog` · PR
   merged → `On Staging` · reopened → `In Progress`.
2. **`board-sync.yml`** (event-driven, App token) — push → `In Progress` · PR
   opened/ready → `In Review` (draft PRs hold `In Progress`). Resolves the PR↔issue
   link from the linked branch first, branch-name parse as fallback — never from
   `Closes #N`.
3. **`board-status` action** (opt-in, self-contained, one step in a deploy job) —
   deploy-accurate `On Staging` / `Done` + close + publish the tag's Release.

All three write the one Status field **idempotently and monotonically**: a stale or
replayed event is a no-op; only an explicit reopen moves Status back. Issues are
**never auto-closed by `Closes #N`** — closure happens at prod deploy.

---

## Guarantees (enforced, with tests)

- **No metered AI** anywhere — pure date math + the blocked-by graph.
- **Every Projects v2 write uses the GitHub App installation token**, never
  `GITHUB_TOKEN`; no token or secret is ever printed.
- **`hooks/guard.sh`** (a `PreToolUse` hook scoped to `start-issue` / `create-pr`)
  blocks `--squash` merges and prod actions without provably-green checks, and fails
  **open** on anything unrelated.
- **Dry-by-default + idempotent** — every skill and write verb previews first and
  re-runs as a clean no-op (an existing item/branch/PR/link/assignee/milestone is
  detected and skipped, never a 409/422).
- **Schema edits diff before mutate** — no blind re-PUT of a single-select option
  list or `iterationConfiguration`; option/iteration IDs stay stable.
- **Non-squash merges** via the free repo merge-method setting.

---

## Layout

- `skills/` — the eight skills above (`SKILL.md` each).
- `lib/` — Python **stdlib only**, exit codes `0` ok / `2` usage / `3` not-found /
  `1` unexpected:
  - `gh.py` — GraphQL/REST core: ID resolution + cache, two-phase field writes,
    monotonic `advance_status`, PR/merge/check/milestone/assignee/reorder/repo &
    team link verbs, diff-gated schema mutations, App-token minting.
  - `sprint.py` — working-day capacity + Ready-order recommendation.
  - `scaffold.py` — golden-template copy + idempotent file install.
  - `dag.py` — blocked-by graph → Blocked / Blast radius / Blast count.
  - `pm.py` — `PM-####` id allocator + flow-style front-matter I/O.
  - `analysis.py` — read-only ranked-findings engine over existing signals + the
    blocked-by DAG (the `analyze-*` skills' deterministic core).
  - `engine.sh` — the dry-by-default / `--force` rail the skills call.
- `templates/` — the golden-template `project/*` and the per-repo `github/*` files
  (issue forms, PR template, `board-sync.yml`, `signals-sync.yml`,
  `add-to-project.yml`, the self-contained `board-status` action, `release.yml`,
  CODEOWNERS).
- `hooks/guard.sh` — the skill-scoped PreToolUse guard.
- `rules/` — `github-fields.md`, `repo-conventions.md`, `ac-rubric.md`,
  `tier-rubric.md`.

The plugin manifest carries only `name` + `description`; the version lives in the
repo-root `.claude-plugin/marketplace.json`.

## Tests

Fully offline — no network, no live org (an injectable command runner stubs
`gh`/GraphQL):

```bash
cd claude-code/plugins/gh-projects
python3 -m unittest discover -s lib/tests -t lib
```
