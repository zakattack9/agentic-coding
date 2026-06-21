---
name: plan-sprint
description: Schedule issues into the gh-projects board's current Iteration + Milestone, set Start/Target dates, show working-day capacity vs assigned load, and reorder the Ready queue to the deterministic recommendation. Use when the user asks to "plan the sprint", "assign these to the current iteration", "schedule the sprint", or "reorder the ready queue". Dry-by-default — previews every assignment, date set, and reorder; writes only on explicit --force. NO AI/model call (pure date math + field writes). Does NOT start/project new issues or self-assign the actor (start-issue), and does NOT open/merge PRs or move Status (create-pr).
disable-model-invocation: true
model: claude-opus-4-8
effort: high
allowed-tools: Bash(python3 *), Bash(bash *), Read, AskUserQuestion
argument-hint: "--owner <org> --number <project#> + the issue set + iteration/milestone (add --force after the dry run)"
---

# plan-sprint

Schedule a set of already-routed issues into the **current Iteration**, assign a
**Milestone**, set **Start/Target** dates, show **working-day capacity vs load**,
and **reorder the Ready queue** to the deterministic recommendation. This is a
thin orchestrator over the deterministic engine — all load-bearing logic lives
in `${CLAUDE_PLUGIN_ROOT}/lib/gh.py` + `${CLAUDE_PLUGIN_ROOT}/lib/sprint.py`,
ridden behind the **dry-by-default / `--force`** rail that
`${CLAUDE_PLUGIN_ROOT}/lib/engine.sh` enforces. Leave no decision logic in this
prose.

Let `ENGINE=${CLAUDE_PLUGIN_ROOT}/lib/engine.sh` and
`SPRINT=${CLAUDE_PLUGIN_ROOT}/lib/sprint.py`. Project writes need a GitHub **App
installation token** already in the environment (`GH_APP_TOKEN`, or
`APP_ID`+`APP_PRIVATE_KEY`) — **never** `GITHUB_TOKEN` (it cannot write Projects
v2 fields). The engine **never prints** the token: `bash $ENGINE token` only
**confirms** availability (returns a REDACTED `ok:true`); do not try to capture it.

**Field-home split.** `plan-sprint` OWNS the **scheduling** fields — **Sprint
(Iteration)**, **Milestone**, **Start**, **Target** — and the **Ready order**. It
does **not** set the intake-time fields (Type/Size/Tier/PM-ID/Spec/Priority — that
is `start-issue`) and does **not** move **Status** beyond what scheduling implies
(lifecycle Status is `create-pr`). `plan-sprint` does not deploy or merge, so it
does **not** wire the guard.

## What it does (all deterministic, no AI)

| Step | Mechanism |
|---|---|
| Pick the **active Iteration** | computed OFFLINE from the field config (see rule below) |
| Assign each issue to that Iteration (**Sprint** field) | `engine.sh resolve` ids → `gh.py` field write |
| Assign the **Milestone** | `gh.py set-milestone` (repo-scoped number, idempotent) |
| Set **Start/Target** dates | `gh.py` field write per item |
| Show **capacity vs load**, warn on over-allocation | `sprint.py capacity` vs assigned count |
| **Reorder** the Ready queue | `sprint.py ready-order` → `gh.py reorder-item` |

## Active-Iteration rule (deterministic, computed offline)

The "current" Iteration is **not** asked for and **not** guessed — it is computed
from the resolved Iteration field's `configuration` (the `iterations` list of
`{title, startDate, duration}` that `engine.sh resolve` already returns), against
**today**:

1. Each iteration spans the **half-open** window `[startDate, startDate + duration)`
   (the same half-open convention as `sprint.working_day_capacity`).
2. **Completed iterations are excluded** — only the live `iterations` list is
   considered, never `completedIterations`.
3. If **today falls inside** some iteration's window, that iteration is active.
4. If **today falls in a gap** (between iterations, or before the first), the
   **next upcoming** iteration (smallest `startDate` strictly after today) is used.
5. Ties/ordering break by `startDate` ascending; this is a pure, stable function
   of the config + today, so a re-run picks the identical iteration.

> Active-iteration selection is a pure computation over the resolved field
> config — there is no model call. The shared helper lives in `lib/sprint.py` as
> the `active_iteration(iterations, today)` pure function, and the rule above is
> covered offline by `test_plan_sprint.py`.

Resolve the field config (read-only, safe in dry mode):

```bash
bash "$ENGINE" resolve --owner <org> --number <project#>
```

## 1. Dry run (always first)

Without `--force` the engine **mutates nothing** — it prints the resolved
command(s) it *would* run and exits. Build and preview the full plan:

- the **active Iteration** title (per the rule above) every issue will be assigned
  to,
- the **Milestone** number and the **Start/Target** dates per issue,
- the **capacity line** — working-day capacity of the active iteration vs the
  number of issues being assigned (the **load**),
- the **Ready reorder** — the recommended order and the `reorder-item` calls.

Compute capacity and the recommended order with the read-only `sprint.py` (no
token, no network, no AI):

```bash
python3 "$SPRINT" capacity --start <iter-startDate> --duration <iter-duration>
python3 "$SPRINT" ready-order --items '<json array of {id,priority,target}>'
```

If the **load exceeds capacity**, emit an **over-allocation WARNING** and still
show the full plan — capacity is advisory, it **does not hard-block**.
Surface the warning to the user; do not silently drop issues.

## 2. Confirm, then apply

Use `AskUserQuestion` to confirm (this mutates the board). The App token must
**already be in the environment** — `GH_APP_TOKEN`, or `APP_ID`+`APP_PRIVATE_KEY`
(the engine never prints the token; `bash "$ENGINE" token` returns a REDACTED
confirmation only, so do **not** try to capture it). Confirm availability first
(`ok:true`); if it is unset the write verbs **refuse** (exit 2) — that refusal is
intentional:

```bash
bash "$ENGINE" token   # confirms availability only — prints {"app_token":"[REDACTED]","ok":true}
```

Then run each write verb **without `--force` first** (dry preview), and re-run the
**identical command with `--force` appended** to execute. Per issue in the set:

**(a) Assign the active Iteration** (`write-field` on the **Sprint** field —
`--value` is the iteration TITLE; the engine resolves it to the iteration id and
reads it back identical):

```bash
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Sprint --value "<iteration title>" --force
```

**(b) Set the Start / Target dates** (`write-field` on the date fields — `--value`
is an ISO `YYYY-MM-DD` date):

```bash
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Start  --value <YYYY-MM-DD> --force
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Target --value <YYYY-MM-DD> --force
```

**(c) Assign the Milestone** (`set-milestone` — repo-scoped number, idempotent):

```bash
bash "$ENGINE" set-milestone --repo owner/name --number <n> --milestone <m> --force
```

**(d) Reorder the Ready queue** (`reorder-item`) in the **recommended order**
returned by `ready-order`: move the first recommended item to the top (omit
`--after`), then each subsequent item `--after` the previous one:

```bash
bash "$ENGINE" reorder-item --project-id <projectId> --item <firstItemId> --force
bash "$ENGINE" reorder-item --project-id <projectId> --item <nextItemId> --after <prevItemId> --force
```

An already-assigned Iteration/date/Milestone, or an item already at its
recommended position, is detected and skipped — never a 409/422.

## 3. Report

State: the active Iteration chosen (and **why** — in-window vs next-upcoming vs
boundary), the Milestone, the Start/Target dates set, the **capacity vs load**
line and whether an over-allocation warning fired, and the **new Ready order**. If
you re-ran on an already-scheduled sprint, confirm it was a no-op (every
assignment / milestone / position already in place → no further write, exit 0).

## Guardrails
- Dry run first, every time; `--force` only after the user confirms.
- **NO AI** — this skill never calls a model; capacity, ordering, and
  active-iteration selection are pure arithmetic over the resolved config.
- Every Project write uses the **App installation token** (`GH_APP_TOKEN`), never
  `GITHUB_TOKEN`. The engine refuses to write without it and scrubs
  secrets from all output.
- **Idempotent**: an already-assigned Iteration/Milestone/date, or an item
  already at its recommended position, is detected and **skipped** — never a
  409/422. A second run is a clean no-op (exit 0).
- This skill owns **scheduling** fields + Ready order only. It does **not** project
  new issues or self-assign (`start-issue`), and does **not** open/merge PRs or
  advance lifecycle Status (`create-pr`).
- Capacity is **advisory** — over-allocation warns, it never hard-blocks.
- Exit codes: `0` ok · `2` usage / no App token · `3` project/field not found ·
  `1` unexpected.
