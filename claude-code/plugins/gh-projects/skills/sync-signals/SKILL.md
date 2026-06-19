---
name: sync-signals
description: On-demand recompute of the gh-projects board's deterministic Gantt-signals (Schedule health, Slippage, Slippage days, Blast radius, Blast count, Blocked) and post the project Status update — the same computation signals-sync.yml runs on events/cron, triggered by hand. Use when the user asks to "refresh the board signals", "recompute slippage/blast/blocked", "repost the project status update", or to force a signal refresh outside the cron. Dry-by-default — previews the exact plan, writes only on explicit --apply. NO AI/model call (pure date math + blocked-by DAG). Does NOT author specs (spec-ops) or move Status columns (board-sync/board-status).
disable-model-invocation: true
model: claude-opus-4-8
effort: low
allowed-tools: Bash(python3 *), Bash(gh *), Read, AskUserQuestion
argument-hint: "--owner <org> --number <project#> (add --apply only after reviewing the dry run)"
---

# sync-signals

Recompute the board's **auto** Gantt-signals and repost the project **Status
update** on demand. This is the manual twin of `signals-sync.yml`: it runs the
**same vendored, deterministic computer** — pure date arithmetic + blocked-by
DAG math, **no model/AI call ever**.

Let `SIGNALS=${CLAUDE_PLUGIN_ROOT}/templates/github/signals.py`. Project writes
need a GitHub **App installation token** in `GH_APP_TOKEN` — **never**
`GITHUB_TOKEN` (it cannot write Projects v2 fields). The plugin's `lib/gh.py`
`token` command mints one; export it before `--apply`.

## What it computes (all deterministic, no AI)

| Field | Derivation |
|---|---|
| **Blocked** | `yes` if the item has ≥1 OPEN blocker (native blocked-by DAG) |
| **Blast radius** | `None / Blocks 1 / Blocks many / Blocks release` — downstream reach |
| **Blast count** | # distinct downstream items transitively blocked |
| **Schedule health** | `Done`(closed) › `Overdue`(open, past Target) › `Blocked` › `At risk`(Target ≤ window) › `On track` |
| **Slippage** | bucketed days past Target — `Not late / 1–2d / 3–5d / 1+wk / 2+wk` |
| **Slippage days** | whole days past Target (0 if not late) |
| **Project Status update** | rolled-up health (`ON_TRACK/AT_RISK/OFF_TRACK/COMPLETE`) + a one-line body |

**Rollup:** any `Overdue` or any `Blocked`-item-that-blocks-release ⇒
`OFF_TRACK`; any `At risk` ⇒ `AT_RISK`; release milestone closed ⇒ `COMPLETE`;
else `ON_TRACK`.

## 1. Dry run (always first)

```bash
python3 "$SIGNALS" --owner <org> --number <project#> --plan
```

`--plan` (the default) writes **nothing**. It prints the full plan as JSON:
every item's computed signals, the rolled-up `status` + `body`, and
`"applied": false`. Show the user the rollup status, the body line, and any item
that flipped to `Overdue` / `Blocked` / `Blocks release`.

## 2. Confirm, then apply

Applying mutates the board (per-item field writes + a new Status update post).
Use `AskUserQuestion` to confirm, then export the App token and re-run with
`--apply`:

```bash
export GH_APP_TOKEN="$(python3 ${CLAUDE_PLUGIN_ROOT}/lib/gh.py token >/dev/null; echo "$GH_APP_TOKEN")"
# (in CI the token is already in GH_APP_TOKEN; locally, mint via the App creds —
#  set GH_APP_TOKEN, or APP_ID + APP_PRIVATE_KEY/APP_PRIVATE_KEY_PATH.)
python3 "$SIGNALS" --owner <org> --number <project#> --apply
```

If `GH_APP_TOKEN` is unset the script **refuses** (exit 2) rather than touching
the board with the wrong token — that refusal is intentional (constraint #2).
The result JSON carries `"applied": true` and a `field_writes` count.

## 3. Report

State the rolled-up status enum, the one-line body that was posted, the number
of items recomputed, and any item that is now `Overdue` / `Blocked` / blocking
the release. If anything was skipped (a signal field absent on the project), say
so plainly.

## Guardrails
- Dry run first, every time. Only `--apply` after the user confirms.
- **NO AI** — this skill never calls a model; the computation is pure
  arithmetic + DAG traversal.
- Every Project write uses the **App installation token** (`GH_APP_TOKEN`),
  never `GITHUB_TOKEN` (constraint #2). The script refuses to write without it.
- This skill only writes per-item **signal field values** + posts the Status
  update — it never edits an option list or iteration config, never
  moves the Status column (that's `board-sync` / `board-status`), and never
  authors a spec (that's spec-ops).
- Exit codes: `0` ok · `2` usage / no App token · `3` project or field not
  found · `1` unexpected.
