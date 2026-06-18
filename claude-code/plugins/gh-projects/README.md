# gh-projects

Run a small team's (≤4 engineers) **entire software lifecycle on GitHub Projects
v2** — deterministic, free, and GitHub-native. One org-owned board spans every
repo: AI-assisted intake into tiered, AC-bearing issues; a structured board; a
light branch → PR → staging → prod flow tracked with zero hand-maintenance; and
always-live native stakeholder surfaces (the project Status update, Gantt-signal
fields, the Roadmap view, Insights charts) — never a hand-kept Gantt or a periodic
digest.

Spec (the build contract):
[`research/pm-task-management/gh-projects.spec.md`](../../../research/pm-task-management/gh-projects.spec.md).

## Phase 1 skills (deterministic, free, no metered AI)

| Skill | What it does | Invocation |
|---|---|---|
| `scaffold-repo` | `copyProjectV2` from the golden template, then API-only setup: ensure org Issue Types + Issue Fields, link repos, recreate per-repo Auto-add, re-anchor the iteration, re-resolve IDs against the copy, set base roles, grant App access, set the repo **no-squash** merge setting, and install the issue forms / PR template / `board-sync.yml` / `signals-sync.yml` / the `board-status` action / `release.yml` / CODEOWNERS + the board README and Insights/view playbooks. Idempotent, dry-run manifest, `--force`. | Explicit |
| `intake-issues` | Raw dump → tiered, field-complete issues. Delegates the body + Acceptance Criteria to **spec-ops** (`write-spec` at the tier's rigor; `refine-spec` for T3); sizes + Epic-splits from the AC-group count. Dry-runs before any `gh issue create`. | Model-invocable |
| `sync-signals` | On-demand recompute of the auto Gantt-signal fields (Schedule health, Slippage, Slippage-days, Blast radius, Blast-count, **Blocked**) from the native blocked-by DAG **+ post the project Status update**. | Explicit |

> The spec's Phase-1 list also names `plan-sprint`, `route-issue`, and
> `promote-pr`. Those are **out of scope for the current build** (AC-1..31) and not
> shipped here. `hooks/guard.sh` is authored to wire into `route-issue` /
> `promote-pr` when they land.

## How the board stays live (three loosely-coupled layers)

1. **Native built-in workflows** — item added → Backlog · PR merged → On Staging ·
   reopened → In Progress.
2. **`board-sync.yml`** (event-driven, App token) — push → In Progress · PR opened
   / ready → In Review.
3. **`board-status` action** (opt-in, self-contained, one step in a deploy job) —
   deploy-accurate On Staging / Done + close + cut the Release.

All three write the one Status field **idempotently and monotonically** (Backlog <
Ready < In Progress < In Review < On Staging < Done): a stale or replayed event is
a no-op; only an explicit reopen moves Status back.

## Invariants (enforced, with tests)

- **No metered AI** anywhere in Phase 1 (AC-26).
- **Every Projects v2 field write uses a GitHub App installation token**, never
  `GITHUB_TOKEN` (AC-27).
- **`hooks/guard.sh`** (skill-scoped `PreToolUse`) blocks `--squash` and prod
  actions without provably-green checks; fails **open** on unrelated input
  (AC-28). Wired in the route-issue / promote-pr skill frontmatter.
- **Schema edits diff before mutate** — no blind re-PUT of a single-select option
  list or `iterationConfiguration`; option/iteration IDs stay stable (AC-30).
- The plugin manifest carries only `name` + `description`; the **version lives in
  the root `marketplace.json`** (`0.1.0`) (AC-29).

## Layout

- `skills/` — the Phase-1 skills above.
- `lib/` — Python **stdlib only**, exit codes `0` ok / `2` usage / `3` not-found /
  `1` unexpected. `gh.py` (GraphQL/REST core, ID resolution, monotonic
  `advance_status`, diff-gated schema mutations), `pm.py` (`PM-####` allocator +
  front-matter I/O), `scaffold.py`, `dag.py`, `engine.sh` (dry-by-default rail).
- `templates/` — the golden-template `project/*`, the `github/` repo files
  (issue forms, PR template, workflows, the self-contained `board-status` action,
  `release.yml`, CODEOWNERS), and the issue/spec skeletons.
- `hooks/guard.sh` — the skill-scoped PreToolUse guard.
- `rules/` — `github-fields.md`, `repo-conventions.md`, `ac-rubric.md`,
  `tier-rubric.md`.

## Tests

Offline, no network, no live org (an injectable command runner stubs gh/GraphQL):

```
cd claude-code/plugins/gh-projects
python3 -m unittest discover -s lib/tests -p "test_*.py"
```

## Phase 0 (external prerequisite)

A human/org one-time step assumed to exist: a GitHub **App** (Projects write) and
the **golden-template Project** with the field schema, the 8 saved views, and the
9 Insights charts built by hand, marked an org template. `scaffold-repo` replicates
it via `copyProjectV2`. Views and Insights are not API-creatable — the plugin only
verifies their presence.

## Delegation to spec-ops (the WHAT, not the HOW)

Spec/AC **authoring + hardening + verification** is delegated to spec-ops
(`write-spec` / `refine-spec` / `verify-spec`). gh-projects does **not** depend on
`launch-spec` — implementation stays the dev's free choice. The `AC-id` contract
and spec/AC format are the pinned, stable interface.
