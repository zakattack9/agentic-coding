# gh-projects

Runs a small team's whole software lifecycle on GitHub Projects v2 — deterministic,
free, no metered AI. Setup + usage: `README.md` (this directory). The offline test
suite (`lib/tests/`) is the source of truth for behavior.

## Test (do this after every change)

```
cd claude-code/plugins/gh-projects && python3 -m unittest discover -s lib/tests -t lib
```

`-t lib` is **required** — tests cross-import via `from tests.test_x import …`, which
needs `lib/` as the top-level dir. The suite is fully offline (no network, no GitHub
creds — every round-trip goes through the injectable `gh.RUN` seam). Keep it green.

## Structure

- `lib/` — the deterministic engine; **stdlib only**, exit codes `0/2/3/1`. `gh.py`
  (GraphQL/REST core + all write verbs), `sprint.py`, `scaffold.py`, `dag.py`,
  `pm.py`, `intake.py` (tier→rigor / size / Epic-split / ready-gate decisions),
  `backlog.py` (the git-tracked staging-ledger engine for the resumable `create-issues`
  decompose→refine→promote pipeline; promote sets the triage fields + lands at Backlog),
  `analysis.py` (READ-ONLY ranked-findings engine for the `analyze-*` skills),
  `setup_board.py` (one-shot golden-template builder, run by the user — not the App),
  `engine.sh` (the dry-by-default rail), `lib/tests/`.
- `skills/` — eight **thin** SKILL.md orchestrators over the engine. Put no decision
  logic in prose; every load-bearing step is a checked-in engine verb.
- `templates/` — golden-template `project/*` + per-repo `github/*`. `hooks/guard.sh`.
- `rules/` — `vocabulary.md` (canonical field/status/term glossary), `composition.md`
  (how the skills compose across the lifecycle), `github-fields.md`,
  `repo-conventions.md`, `ac-rubric.md`, `tier-rubric.md`.

## Invariants — preserve these on every change (tests enforce them)

- **No metered AI** anywhere — pure date math + GraphQL.
- **App installation token for all Projects v2 writes**, never `GITHUB_TOKEN`.
  `get_app_token()` resolves `GH_APP_TOKEN` or `APP_ID`+`APP_PRIVATE_KEY[_PATH]`
  (+ optional `APP_INSTALLATION_ID`). Never print a token (`gh._scrub`).
- **Dry-by-default / `--force`.** New write verbs go in `gh.py`'s `build_parser` and
  are reachable **only** through `engine.sh`'s `--force` rail — its `*)` branch gates
  everything not in the read whitelist (`resolve|capabilities|token`).
- **Idempotent.** Every write verb reads-then-skips (returns `changed: False`) so a
  re-run is a clean no-op, never a 409/422. Schema edits **diff before mutate** —
  never blind re-PUT a single-select option list or `iterationConfiguration` (option/
  iteration IDs must stay stable).
- **Reuse, don't duplicate** the core: `add_item` / `set_field` / `write_field` /
  `advance_status`+`STATUS_ORDER` / `create_linked_branch` / `Project.resolve` /
  `get_app_token`. PR links are **non-closing** (`Relates to #N`) — never
  `Closes/Fixes/Resolves` (closure is the prod-time `board-status` job).

## Skills

- All declare `model: claude-opus-4-8` + a deliberate `effort`. `create-issues` and
  the two **read-only** analysis skills (`analyze-board` + `analyze-sprint`) are
  model-invocable; the other five are Explicit (`disable-model-invocation: true`).
  The `analyze-*` skills only READ (deterministic findings via `lib/analysis.py`) —
  they never write a field, post a Status update, or emit a digest.
- `hooks/guard.sh` (PreToolUse) is wired **only** into `start-issue` + `create-pr`
  frontmatter — **not** `plan-sprint`.
- Field-home split: `create-issues` (promote) sets Type/Tier/Priority/Size/PM-ID/Spec
  (lands the item at Backlog); `start-issue` sets Status→In Progress + assignee +
  linked branch; `plan-sprint` owns scheduling (Sprint/Milestone/Start/Target) +
  Ready order; `create-pr` touches only Status, monotonically.
- `create-issues` delegates issue body + acceptance criteria to the **spec-ops**
  plugin (a dependency) — never author bodies inline. The interface is **narrow and
  pinned**: the two skill ids (`WRITE_SPEC_SKILL` / `REFINE_SPEC_SKILL`) and three
  rigor names (`TIER_RIGOR`: `light`/`standard`/`full`) in `lib/intake.py`, plus the
  **`--disable-questions`** flag `create-issues` always passes to `write-spec` (intake
  is a batch pipeline — spec-ops must elicit nothing interactively and leave
  `[NEEDS CLARIFICATION]` markers instead). spec-ops's
  own *spec format* may churn freely — `templates/{issue-body,deep-spec}.md` are
  gh-projects' target shape that spec-ops *fills*, not a mirror of its output. But a
  spec-ops **skill / rigor / flag rename** breaks delegation at runtime, and the offline
  suite **won't catch it** (spec-ops is stubbed) → if spec-ops renames a skill, rigor
  level, or the `--disable-questions` flag, update that map (and the `create-issues`
  delegation) here.

## Versioning

The repo rule (bump the plugin in root `marketplace.json` on any change) also requires
updating the **pinned version assertion** in `lib/tests/test_invariants.py` — bump
both together or the suite fails.

## Platform constraints (don't fight these)

- **Field creation is scriptable** via the REST Projects API (`X-GitHub-Api-Version:
  2026-03-10`): `setup_board.py` makes all project fields incl. the **iteration**
  field, the org issue type + issue fields, and **view shells** (name/layout/filter).
  Still **no API** (UI-only, done once on the template, carried by `copyProjectV2`): a
  view's **grouping/sort/slice/swimlane**, the built-in **Status** options, the
  **Insights charts**, and the **Make-template** flag. Copy is documented to carry
  fields + views; **charts may not survive it** → verify per board.
- A Project's org **base role is UI-only** (no API) → emit it as a manual step.
- There is **no built-in Auto-add API** → install `actions/add-to-project`, SHA-pinned.
- `projects_v2_item` has **no repo-workflow trigger** → drive Status from
  `issues`/`pull_request`/`push` events writing into the Project, never from column moves.
