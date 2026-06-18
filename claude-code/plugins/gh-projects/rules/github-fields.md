# GitHub Projects v2 — field, ID, and schema discipline

These are the load-bearing platform constraints. Break one and the board silently
corrupts (orphaned assignments, lost history, a status that can't be written, a
trigger that never fires). They hold for every skill and every workflow.

## The four constraints (break the system if missed)

1. **`projects_v2_item` cannot trigger a repo workflow.** A board column move
   fires an **org-level** `projects_v2_item` webhook; there is no
   `on: projects_v2_item:` in a repo's Actions. Never react to a column move.
   Drive Status **the other way**: `issues` / `pull_request` / `push` events write
   Status **into** the Project via GraphQL (`board-sync.yml`), plus the native
   built-in workflows and the opt-in `board-status` deploy action.
2. **`GITHUB_TOKEN` cannot write Projects v2 fields.** Every Project write uses a
   **GitHub App installation token** (org-scoped, `project` scope) — the *only*
   token that can mutate Projects v2. Mint it in CI with
   `actions/create-github-app-token@v1`, pass it as `GH_APP_TOKEN`. Never read or
   wire `GITHUB_TOKEN` for a write. (Rate: ~5k GraphQL pts/hr + 2k/min on our
   plan — same baseline as a PAT; cache IDs and sync incrementally.)
3. **Field / option / iteration edits regenerate IDs and orphan assignments.**
   Editing a single-select option list regenerates option IDs;
   `updateProjectV2Field`'s `iterationConfiguration` is **replace-all** —
   re-PUTting it wipes completed iterations and orphans every issue↔iteration
   assignment and all chart history. Treat schema edits as **rare, idempotent,
   ID-stable**: resolve & cache IDs, **diff before mutate** (`lib/gh.py`
   `iterations_need_update` / `options_need_update`), **never blind re-PUT**.
4. **Metered Claude can silently stop.** Any future AI Action draws the separate
   Agent-SDK credit pool that drains first and stops without erroring. Phase 1 is
   **deterministic and free — no metered AI anywhere.** When AI ships (a later
   phase), every metered step uses a dedicated spend-capped Console key, fails
   loud, and is gated behind an explicit label.

## Field homes (three — pick the right one)

- **Issue Type** (org taxonomy, ≤25 types): `Feature / Bug / Chore / Infra / Epic`.
- **Org Issue Fields** (≤25/org, searchable, cross-repo, immune to project-copy /
  option-ID churn): org-wide typed attributes — **Priority, Start date, Target
  date**. Surface as Project columns on **private** projects only (ours are
  private).
- **Project single-selects** (live in the golden template, replicate via
  `copyProjectV2`): board-local plugin state — **Size, Tier, Blocked, the
  Gantt-signal fields**.

Rule: org-wide typed attribute → Issue Field · board-local / plugin state →
Project field · work taxonomy → Issue Type. Every signal single-select carries an
option `description` documenting its derivation (self-documenting board).

## ID-stability checklist (every schema touch)

- Resolve project / field / option / iteration IDs first; cache them.
- Diff the desired set against what's already there. **Skip** when unchanged.
- Add only genuinely-new options; never re-emit the existing list.
- Never call `updateProjectV2Field` with `iterationConfiguration` unless the diff
  guard says the set actually changed.
- Views and Insights charts are **not API-mutable** — they ship only via
  `copyProjectV2` from the golden template; `scaffold-repo` only *verifies
  presence*, it never creates them.
