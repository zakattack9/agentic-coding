---
name: promote-pr
description: Open or update the issue-linked PR for the active branch, advance the board Status across the PR lifecycle, surface the PR's check state, and offer a guard-protected non-squash merge once checks are green. Use when the user says "promote the PR", "open the PR for this branch", "move to in review", or "merge when green". Dry-by-default — previews the PR + Status + merge intent and mutates nothing until you re-run with --force. Does NOT route issues or create linked branches (route-issue) and does NOT plan sprints / set dates (plan-sprint); does NOT author specs (spec-ops).
disable-model-invocation: true
model: claude-opus-4-8
effort: high
allowed-tools: Bash(python3 *), Bash(bash *), Bash(gh *), Read, AskUserQuestion
argument-hint: "--owner <org> --number <project#> --repo owner/name --issue <n> (add --force after the dry run)"
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh"
---

# promote-pr

Open/update the issue-linked PR for the active branch, advance the board
**Status** across the PR lifecycle, surface the PR's **check state**, and offer a
**guard-protected non-squash merge** once checks are green. This skill is a thin
orchestrator over the deterministic engine — every load-bearing operation is a
checked-in verb in `${CLAUDE_PLUGIN_ROOT}/lib/gh.py`, dispatched through
`${CLAUDE_PLUGIN_ROOT}/lib/engine.sh`'s **dry-by-default / `--force`** rail. Leave
no decision logic in this prose; orchestrate the verbs and render their output.

Let `ENGINE=${CLAUDE_PLUGIN_ROOT}/lib/engine.sh`. The `PreToolUse` guard above
(`hooks/guard.sh`) is active **only while this skill runs** (AC-25): it
hard-blocks any `--squash` and any prod deploy/release without provably-green
checks, and fails open on everything else. Never work around it.

## Hard rails (the engine + guard enforce these — never work around them)

- **Dry-by-default.** Without `--force`, the engine prints the intended write
  command and mutates **nothing** — PR, Status, and merge all stay previews
  (AC-20). Only `--force` after the user confirms.
- **Non-closing PR link only.** The PR body carries `Relates to #N` — **never**
  `Closes/Fixes/Resolves` (auto-close stays the prod-time `board-status` job's
  job, AC-30). The `open_or_update_pr` verb rejects a smuggled-in closer (exit 2).
- **Status is monotonic and Status-only.** This skill touches **only** the Status
  field and only forward along `Backlog < Ready < In Progress < In Review <
  On Staging < Done` (`advance_status`); it never sets intake fields (route-issue)
  or scheduling fields (plan-sprint), and never regresses Status (AC-17).
- **No merge while checks are red/pending.** The merge step is **withheld** until
  `pr_check_state` reads `green`, with the reason stated (AC-18).
- **Non-squash merge only.** Merge is `--merge` or `--rebase` (`merge_pr`), never
  `--squash` (AC-19) — and the guard hard-blocks `--squash` even if attempted.
- **App installation token only.** Every Projects v2 (Status) write uses the
  GitHub App installation token (`GH_APP_TOKEN`, or `APP_ID`+`APP_PRIVATE_KEY`),
  **never** `GITHUB_TOKEN` (AC-28). The token is never printed.
- **Idempotent.** A no-diff re-run is a clean no-op: an existing PR is edited in
  place (never a duplicate-PR 422), Status past the target is not rewritten, an
  already-merged PR is not re-merged (AC-33).

## 1. Gather inputs

You need the **org login** (`--owner`), the **project number** (`--number`), the
**`owner/name` repo** (`--repo`), and the **issue number** (`--issue`) whose
linked branch this PR promotes. The active **head** branch is the issue's
authoritative linked branch (created by `route-issue`); the **base** is the
repo's default branch unless the user names another. If any input is missing, ask
with `AskUserQuestion`. Confirm the App token is available (`GH_APP_TOKEN` or
`APP_ID`+`APP_PRIVATE_KEY`); the engine fails with a usage error (exit 2) if not.

## 2. Dry run (always first)

Preview the three intents — open/update PR, the Status target, the merge intent —
without mutating anything:

```bash
# (a) PR open/update preview (non-closing Relates to #N)
bash "$ENGINE" open-pr --repo <owner/name> --head <linked-branch> \
  --base <default-branch> --number <issue> [--draft]

# (b) PR check state (read-only — runs even in dry mode)
bash "$ENGINE" pr-checks --repo <owner/name> --pr <pr#>
```

Then determine the **Status target** from the PR's lifecycle and present it as a
preview:

| PR lifecycle state | Status target (monotonic) |
|---|---|
| draft PR | hold **In Progress** (do not advance) |
| ready (non-draft) PR | **In Review** |
| merged on green | **On Staging** is the consuming pipeline's job, not this skill |

Show the user the full preview verbatim: the PR action (`created`/`updated`) +
its `Relates to #N` body, the `green`/`red`/`pending` check verdict, the Status
target, and the merge intent. If checks are **not green**, state plainly that the
merge step is **withheld** and why (AC-18) — do not offer merge.

## 3. Confirm, then apply

Use `AskUserQuestion` to confirm (this mutates the repo + board). Run each verb
**without `--force` first** (dry preview), then re-run the **identical command with
`--force` appended** to execute. A no-diff re-run is a clean no-op (AC-33).

**(a) Open/update the non-closing PR** (`open-pr` — edits in place if a PR for the
branch already exists, never a duplicate-PR 422):

```bash
bash "$ENGINE" open-pr --repo <owner/name> --head <linked-branch> \
  --base <default-branch> --number <issue> [--draft] --force
```

**(b) Advance board Status monotonically** to the PR-lifecycle target
(`advance-status` — `advance_status` writes only a forward move; an item already
at/past the target is a no-op, no write — AC-17). Use the target from the §2
lifecycle table — `In Review` on a ready PR; hold `In Progress` while draft:

```bash
# ready (non-draft) PR -> In Review
bash "$ENGINE" advance-status --owner <org> --number <project#> --repo <owner/name> --issue <issue> --to "In Review" --force

# draft PR -> hold at In Progress (no advance past it)
bash "$ENGINE" advance-status --owner <org> --number <project#> --repo <owner/name> --issue <issue> --to "In Progress" --force
```

**(c) Merge only on green.** Offer the merge **only** when `pr-checks` reads
`green` (re-confirm with the read-only check verb, which runs even in dry mode):

```bash
bash "$ENGINE" pr-checks --repo <owner/name> --pr <pr#>   # must read "green"
```

On the user's explicit confirm and a green verdict, perform a **non-squash** merge:

```bash
# non-squash ONLY — --merge (or --rebase); the guard hard-blocks --squash
bash "$ENGINE" merge-pr --repo <owner/name> --pr <pr#> --method merge --force
```

Never pass `--squash` (the verb rejects it, exit 2; the guard blocks it too). If
checks are red/pending, **do not** run `merge-pr` — re-check after CI settles.

## 4. Report

State: the PR action (`created`/`updated`) + number/URL and its non-closing
`Relates to #N` link, the check verdict (`green`/`red`/`pending`), the Status
target written (or held, with the monotonic reason if no advance), and the merge
outcome (merged via `--merge`/`--rebase`, or **withheld** because checks were not
green). If you re-ran on an already-promoted PR, confirm it was a no-op (PR edited
in place, no Status rewrite, no re-merge).

## Guardrails
- Dry run first, every time; `--force` only after the user confirms.
- Never call `gh` to mutate the PR/board directly for a Project write — go through
  `engine.sh` so the `--force` rail and App-token path hold. (`gh pr checks` is a
  read; the engine runs it even in dry mode.)
- **Non-closing link only** — `Relates to #N`, never Closes/Fixes/Resolves
  (AC-30). Closure stays the prod-time `board-status` job.
- **Status only, monotonic** — never set intake/scheduling fields, never regress
  Status (AC-17). Intake fields are route-issue's; scheduling is plan-sprint's.
- **No merge unless green** (AC-18); **never `--squash`** (AC-19) — the guard
  enforces both.
- Never print the App token; the engine scrubs secrets from all output.
- Exit codes: `0` ok · `2` usage / no App token · `3` PR or project not found ·
  `1` unexpected.
