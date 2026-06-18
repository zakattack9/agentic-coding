---
name: route-issue
description: Route one GitHub issue onto the org board and create its authoritative linked branch — project the item, populate its intake-time fields, optionally self-assign, advance Status monotonically. Use when the user says "route this issue", "put #N on the board", "start work on issue N", "add issue N to the project + cut its branch", or "project this ticket". Dry-by-default — previews the full projection + branch plan and writes nothing until you re-run with --force. Does NOT intake/triage a backlog dump (intake-issues), assign sprints/dates/Milestone (plan-sprint), or open/merge the PR (promote-pr).
disable-model-invocation: true
model: claude-opus-4-8
effort: medium
allowed-tools: Bash(python3 *), Bash(bash *), Read, AskUserQuestion
argument-hint: "--owner <org> --number <project#> --repo owner/name --issue <n> [--assignee <login>] (add --force after the dry run)"
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh"
---

# route-issue

Project **one** issue onto the org board and create its **authoritative linked
branch**. This is a thin orchestrator over the deterministic engine — every
load-bearing operation is a checked-in `lib/gh.py` verb run behind
`${CLAUDE_PLUGIN_ROOT}/lib/engine.sh`'s **dry-by-default / `--force`** rail. Leave
no decision logic in this prose.

Let `ENGINE=${CLAUDE_PLUGIN_ROOT}/lib/engine.sh` and
`GH=${CLAUDE_PLUGIN_ROOT}/lib/gh.py`. Read verbs (`resolve`, `capabilities`) run
even in dry mode; write verbs mutate nothing without `--force`.

## Hard rails (the engine enforces these — never work around them)

- **Dry-by-default.** Without `--force`, the engine previews the projection +
  branch plan and mutates **nothing**. Only `--force` after the user
  confirms.
- **App installation token only.** Every Projects v2 write uses the GitHub App
  installation token (`GH_APP_TOKEN`, or `APP_ID`+`APP_PRIVATE_KEY`), **never**
  `GITHUB_TOKEN` — it cannot write org Projects v2. The token is never
  printed.
- **Field-home split.** route-issue sets **only** the intake-time fields —
  `Type / Size / Tier / PM-ID / Spec / Priority / Status`. It does **not** touch
  `Sprint / Milestone / Start / Target` (that is `plan-sprint`).
- **Monotonic Status.** Status advances only along
  `Backlog < Ready < In Progress < In Review < On Staging < Done`; a re-route
  never regresses an item already at/past the target.
- **Non-closing links only.** route-issue never writes `Closes/Fixes/Resolves`
  — closure stays the prod-time `board-status` job.
- **Idempotent.** A re-run is a clean no-op: the existing board item is reused
  (same item id), the existing linked branch is detected and skipped (exit 0),
  an already-set field/assignee is left alone — never a 409/422. The
  guard (`hooks/guard.sh`, scoped to this skill) hard-blocks a `--squash` merge
  and a prod deploy without provably-green checks.

## 1. Gather inputs

You need the **org `--owner`**, the **board `--number`**, the **`--repo
owner/name`**, and the **`--issue <n>`**; `--assignee <login>` is optional (the
actor's self-assign for the "Ready → In Progress = dev self-assign + status"
flow). If any required input is missing, ask with `AskUserQuestion`. Confirm the
App token is available (`GH_APP_TOKEN`, or `APP_ID`+`APP_PRIVATE_KEY`).

Resolve the board (read-only, runs in dry mode):

```bash
bash "$ENGINE" resolve --owner <org> --number <project#>
```

This caches the project + every field/option id route-issue will write to.

## 2. Dry run (always first)

Preview the **full projection + branch plan** without `--force`. Show the user:

- the **board item** the issue projects to (reusing the existing item if the
  issue is already on the board — same item id),
- the **intake-time field** values to set — `Type / Size / Tier / PM-ID / Spec /
  Priority / Status` — each read back identical by the engine,
- the **Status** transition, computed monotonically (no write if the item is
  already at/past the target),
- the **linked branch** plan — native `gh issue develop` when the installed `gh`
  supports it, else the `createLinkedBranch` GraphQL fallback (probed via
  `bash "$ENGINE" capabilities`); a re-run on an existing linked branch is a
  no-op,
- the optional **self-assign** when `--assignee` is given.

Every write verb run without `--force` prints its resolved command to stderr and
mutates nothing. Show the user this plan verbatim.

## 3. Confirm, then apply

Use `AskUserQuestion` to confirm (this mutates the board + repo). Every step
below is a concrete engine verb: run it **without `--force` first** (dry preview),
then re-run the **identical command with `--force` appended** to execute. A
re-run with the same inputs is a clean no-op.

**(a) Project the issue onto the board** (`add-item` — a re-add returns the same
item id):

```bash
bash "$ENGINE" add-item --owner <org> --number <project#> --repo owner/name --issue <n> --force
```

**(b) Write each intake-time field** (`write-field` — the engine reads each value
back identical; an unchanged value is a no-op). One command **per field** — set
only the fields you have values for:

```bash
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Type     --value <Feature|Bug|Chore|Infra> --force
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Size     --value <S|M|L>                 --force
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Tier     --value <T1|T2|T3>              --force
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field PM-ID    --value <PM-XXXX>               --force
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Spec     --value <specs/...md>           --force
bash "$ENGINE" write-field --owner <org> --number <project#> --repo owner/name --issue <n> --field Priority --value <P0|P1|P2|P3>           --force
```

(For single-select fields `--value` is the OPTION NAME; the engine resolves it.)

**(c) Advance Status monotonically** (`advance-status` — reads the current Status
and writes only a forward move; an item already at/past the target is a no-op, no
write):

```bash
bash "$ENGINE" advance-status --owner <org> --number <project#> --repo owner/name --issue <n> --to "<Status>" --force
```

**(d) Create the authoritative linked branch** (`create-linked-branch` — native
`gh issue develop` when supported, else GraphQL; an existing linked branch is
detected and is a no-op, exit 0). `--name` is optional:

```bash
bash "$ENGINE" create-linked-branch --repo owner/name --issue <n> [--name <branch>] --force
```

**(e) Self-assign the actor** (optional, only when `--assignee` was given —
`set-assignee`; adding an already-present assignee is a no-op):

```bash
bash "$ENGINE" set-assignee --repo owner/name --number <n> --login <login> --force
```

## 4. Report

State: the board item id (and whether it was **reused** vs newly added), the
intake-time fields set (with the read-back confirmation), the Status transition
(or "already at/past target — no write"), the linked branch name (created vs
already-linked no-op), and the self-assign if requested. If you re-ran on an
already-routed issue, confirm it was a clean no-op (same item id, branch
detected, no field/assignee/Status write).

## Guardrails
- Dry run first, every time; `--force` only after the user confirms.
- Never call `gh` to mutate the board directly — go through `engine.sh` (the
  `gh.py` verbs ride its `--force` rail).
- route-issue sets **only** intake-time fields — never `Sprint/Milestone/Start/
  Target` (that is `plan-sprint`), never the PR (that is `promote-pr`).
- Status is **monotonic** — never regress an item already past the target.
- **Non-closing links only** — never `Closes/Fixes/Resolves`; closure is
  the prod-time `board-status` job's responsibility.
- The skill-scoped guard (`hooks/guard.sh`) hard-blocks a `--squash` merge and a
  prod deploy without provably-green checks while this skill runs.
- Never print the App token; the engine scrubs secrets from all output.
- Exit codes: `0` ok · `2` usage / no App token · `3` project/field/issue not
  found · `1` unexpected.
