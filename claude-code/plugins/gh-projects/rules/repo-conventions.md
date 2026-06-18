# Repo conventions — branch → PR → staging → prod

The lifecycle the board tracks. These are conventions enforced by the free repo
settings plus the skill-scoped `hooks/guard.sh`, not by paid rulesets.

## Flow

- **GitHub Flow.** Branch **from the issue** (`gh issue develop` or the dev panel)
  so the branch carries an authoritative linked-branch reference and a
  conventional name (`123-short-slug`). Short-lived branches; feature flags keep
  `main` shippable. WIP = 1 (2 max).
- **PR links the issue without `Closes #N`.** Use `Relates to #N`. A `Closes #N`
  would auto-close the issue on merge — we do **not** want that; the item is
  closed at **prod** by the `board-status` action, not at merge.
- **Draft PR = In Progress**, flips to **In Review** on `ready_for_review`.
- **Review = one human approval (any peer)** + green CI, by convention (rulesets
  are GHEC-only on our plan, so this is social + guard-enforced, not hard).

## Merge

- **no-squash.** Enforced by the **free repo merge-method setting** (squash
  disabled, merge-commit enabled), set by `scaffold-repo`. The
  `PreToolUse` guard additionally blocks a hand-typed `gh pr merge --squash`.
  Preserve individual commits — merge with `--merge` (or `--rebase`).
- A merged PR moves the item to **On Staging** (native built-in, reconfigured from
  the default Done) — the item stays **open**.

## Staging → prod

- Merge → **auto-deploy staging** (your existing `workflow_run`-after-CI). Exercise
  the change / verify AC in staging.
- **Prod is a manual, tagged `workflow_dispatch`** restricted to PM / senior lead:
  the **OIDC deploy-role actor-ID allowlist** (hard) + an in-workflow allowlist
  (soft) + **tag-must-point-at-`main`**. Environments' required-reviewers are
  GHEC-only for private repos, so they are *not* the gate.
- **Never dispatch prod ahead of green CI.** The guard blocks a prod deploy /
  release publish unless the same command provably gates on green checks (e.g.
  `gh pr checks <pr> --watch && …` or `gh run watch <id> && …`).
- Prod deploy success → the `board-status` step sets **Done**, **closes** the
  shipped issues, and **cuts the GitHub Release** (auto-notes from
  `.github/release.yml`). This is the only place issues are auto-closed.

## Board automation layers (loosely coupled, never rewrite a pipeline)

1. **Native built-ins** (free): item added → Backlog; PR merged → On Staging; item
   reopened → In Progress.
2. **`board-sync.yml`** (event-driven, App token): push → In Progress; PR opened /
   ready → In Review; resolves the PR↔issue link (linked-branch first, branch-name
   `123-foo` parse fallback).
3. **`board-status` action** (opt-in, self-contained, one step in a deploy job):
   deploy-accurate On Staging / Done + close + Release.

All three write the one Status field **idempotently and monotonically** — resolve
the current Status, only **advance** (Backlog < Ready < In Progress < In Review <
On Staging < Done). A stale or replayed event is a no-op; only an explicit reopen
regresses Status.

## Guard (skill-scoped)

`hooks/guard.sh` is wired into the `route-issue` / `promote-pr` skills' frontmatter
as a `PreToolUse` (matcher `Bash`) — active only while those skills run. It
fail-opens on unrelated input and **blocks** `--squash` and prod actions without
provably-green checks. It is a plugin-scoped fast-fail, not org enforcement.
