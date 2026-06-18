# gh-projects

Runs a small team's whole software lifecycle on GitHub Projects v2 — deterministic,
free, no metered AI. Setup + usage: `README.md` (this directory). Historical build
contract + acceptance criteria: the PM-0001 / PM-0002 specs under
`research/pm-task-management/` (the offline test suite is the *live* source of truth;
the specs have drifted on some wording).

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
  `pm.py`, `engine.sh` (the dry-by-default rail), `lib/tests/`.
- `skills/` — six **thin** SKILL.md orchestrators over the engine. Put no decision
  logic in prose; every load-bearing step is a checked-in engine verb.
- `templates/` — golden-template `project/*` + per-repo `github/*`. `hooks/guard.sh`,
  `rules/`.

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

- All declare `model: claude-opus-4-8` + a deliberate `effort`. Only `intake-issues`
  is model-invocable; the other five are Explicit (`disable-model-invocation: true`).
- `hooks/guard.sh` (PreToolUse) is wired **only** into `route-issue` + `promote-pr`
  frontmatter — **not** `plan-sprint`.
- Field-home split: `route-issue` sets the intake fields (Type/Size/Tier/PM-ID/Spec/
  Priority/Status); `plan-sprint` owns scheduling (Sprint/Milestone/Start/Target) +
  Ready order; `promote-pr` touches only Status, monotonically.
- `intake-issues` delegates issue body + acceptance criteria to the **spec-ops**
  plugin (a dependency) — never author bodies inline.

## Versioning

The repo rule (bump the plugin in root `marketplace.json` on any change) also requires
updating the **pinned version assertion** in `lib/tests/test_invariants.py` — bump
both together or the suite fails.

## Platform constraints (don't fight these)

- Saved views + Insights charts are **not API-creatable** → golden template +
  `copyProjectV2`; scaffold verifies presence only.
- A Project's org **base role is UI-only** (no API) → emit it as a manual step.
- There is **no built-in Auto-add API** → install `actions/add-to-project`, SHA-pinned.
- `projects_v2_item` has **no repo-workflow trigger** → drive Status from
  `issues`/`pull_request`/`push` events writing into the Project, never from column moves.
