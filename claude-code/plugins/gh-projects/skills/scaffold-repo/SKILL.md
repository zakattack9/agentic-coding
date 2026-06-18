---
name: scaffold-repo
description: Stand up a new GitHub Project + repo templates for the gh-projects lifecycle by copying the org golden template and installing per-repo automation. Use when the user says "scaffold the board", "set up gh-projects for <repo>", "stand up the project", "copy the golden template", or "bootstrap a repo for the board". Dry-by-default — previews the full change manifest and mutates nothing until you re-run with --force. Does NOT do intake, routing, or signals (those are other gh-projects skills); does NOT author specs (that is spec-ops).
disable-model-invocation: true
model: claude-opus-4-8
effort: medium
allowed-tools: Bash(bash *), Bash(python3 *), Read, AskUserQuestion
argument-hint: "--org <login> --template \"<golden template title>\" --title \"<new project title>\" [--repo owner/name] [--team <slug>] (add --force only after reviewing the dry run)"
---

# scaffold-repo

Stand up one new org Project from the **named golden template** and install the
per-repo templates + deterministic automation. This skill is a thin orchestrator
over the deterministic engine — all load-bearing logic lives in
`${CLAUDE_PLUGIN_ROOT}/lib/scaffold.py`, which carries the same **dry-by-default /
`--force` rail** that `${CLAUDE_PLUGIN_ROOT}/lib/engine.sh` enforces for the core
`gh.py` read verbs (it mutates nothing without `--force`). Leave no decision logic
in this prose.

Let `SCAFFOLD=${CLAUDE_PLUGIN_ROOT}/lib/scaffold.py`. Read-only checks (e.g.
`bash ${CLAUDE_PLUGIN_ROOT}/lib/engine.sh resolve …`) still go through the engine.

## Hard rails (the engine enforces these — never work around them)

- **Dry-by-default.** Without `--force`, the engine prints the full change
  manifest and mutates **nothing** (AC-11). Only `--force` after the user
  confirms.
- **App installation token only.** Every Projects v2 write uses the GitHub App
  installation token (`GH_APP_TOKEN`, or `APP_ID`+`APP_PRIVATE_KEY`), **never**
  `GITHUB_TOKEN` (AC-27). The token is never printed.
- **`copyProjectV2` from the NAMED template, then re-resolve against the COPY.**
  Field/option/iteration ids are re-resolved from the copy, never the template
  (AC-7, AC-8). Views + Insights charts ride along in the copy — they are **not**
  API-creatable. The engine verifies **field presence** (by re-resolve), the
  **view-catalog presence** (a read-only `projectV2.views` diff against the 8 in
  `project/views.json`) — both halves of AC-7 — **and** that each of the 8 views
  **resolves its documented filter / group / slice** (`verify_views`, AC-25): a
  read-only pass that confirms every filter qualifier maps to a native qualifier
  or a field present on the copy and each documented group/slice is reflected by
  a non-empty live `groupByFields` / `verticalGroupByFields`. A missing view **or**
  an unresolved filter/group/slice **fails loudly (exit 3)** before any per-repo
  install under `--force` — the remedy is always *fix the golden template and
  re-copy* (views aren't API-mutable). Insights charts have **no API** at all, so
  they stay a human checklist item.
- **Never blind re-PUT** a single-select option list or `iterationConfiguration`
  — the engine diffs and SKIPs unchanged iterations (AC-9, AC-30).
- **Idempotent.** A second run is a no-op: empty file-install manifest + zero
  iteration mutations.

## 1. Gather inputs

You need the **org login**, the **golden-template Project title** (exact, marked
an org template in Phase 0), a **title for the new project**, optionally the
**`owner/name` repo** to install templates into + link to the Project, and
optionally an org **`--team` slug** to link the Project to. If any required input
is missing, ask with `AskUserQuestion`. Confirm the App token is available in the
environment (`GH_APP_TOKEN` or `APP_ID`+`APP_PRIVATE_KEY`); the engine fails with
a usage error (exit 2) if not.

## 2. Dry run (always first)

```bash
python3 "$SCAFFOLD" scaffold --org <login> --template "<golden template title>" \
  --title "<new project title>" [--repo owner/name] [--team <slug>]
```

The engine prints the full **change manifest** to stderr:
- the `copyProjectV2` source→destination and the new project number,
- fields **present vs missing** in the copy (missing ⇒ fix the *template* and
  re-copy; never hand-add to a scaffolded project — see `project/views.md`),
- **views present vs missing** — the 8-view catalog diff (read-only) against
  `project/views.json` (a missing view ⇒ same remedy: fix the template + re-copy),
- **view filter/group/slice resolution** — `ALL RESOLVE` or the per-view
  `UNRESOLVED:` lines (AC-25); any defect blocks the `--force` apply (exit 3),
- the iteration plan (**SKIP** when unchanged, with a mutation count),
- every **file to install** with `install`/`skip` per destination path,
- org **Issue Types** + **Issue Fields** to ensure,
- the repo **no-squash** setting and the **App access** confirmation touch
  (the App already has org Projects-write via its installation — this is a
  confirmation, **not** a base-role grant),
- the **repo→Project link** (`linkProjectV2ToRepository`, idempotent — `skip`
  when the repo is already linked) when `--repo` is given (AC-21), and the
  installed per-repo **`add-to-project.yml`** auto-add workflow (SHA-pinned
  `actions/add-to-project`, App-token auth, no metered AI — AC-22),
- the **Project→team link** (`linkProjectV2ToTeam`, write-to-team) when `--team`
  is given, plus the **base-role manual step** — setting the org base role to
  *Read* is **UI-only with no API** (AC-23), so the engine emits it as a manual
  checklist item rather than attempting a mutation,
- the human checklist (confirm the 9 Insights charts — Insights has no API; and
  the base-role manual step when `--team` was given).

Show the user this manifest verbatim. The machine-readable result JSON on stdout
carries `copy`, `fields_present/missing`, `views_present/missing`,
`views_resolve_ok`, `views_resolve_errors`, `iteration_mutations`, `files`,
`issue_types`, `issue_fields`. If `views_resolve_ok` is false, the `--force`
apply will fail (exit 3) — fix the golden template and re-copy first.

## 3. Confirm, then apply

Use `AskUserQuestion` to confirm (this mutates the org + repo). On confirmation,
re-run with `--force`:

```bash
python3 "$SCAFFOLD" scaffold --org <login> --template "<golden template title>" \
  --title "<new project title>" [--repo owner/name] [--team <slug>] --force
```

The result JSON's `files_written` lists exactly what changed; `applied:true`
confirms mutation.

## 4. Report

State: the new project number + title, fields present/missing, the 8-view
catalog present/missing AND whether all 8 views **resolved their filter/group/
slice** (and the remedy if any are missing/unresolved — fix the template,
re-copy), the iteration decision (skipped vs
diff-added), files installed (including `add-to-project.yml`), Issue Types/Fields
ensured, the no-squash setting, the **repo→Project link** (`link`/`skip`) and the
**Project→team link** when `--team` was given, and the **human checklist** items
(eyeball the 9 Insights charts — the engine cannot verify them, Insights has no
API; and set the org base role to *Read* in the UI when `--team` was given —
base role has no API, AC-23). If you re-ran on an already-scaffolded repo, confirm
it was a no-op (empty install manifest, zero iteration mutations, repo link
`skip`).

## Guardrails
- Dry run first, every time; `--force` only after the user confirms.
- Never call `gh` to mutate the board directly — go through `scaffold.py`
  (Projects/org/repo writes) or `engine.sh` (read verbs).
- A missing field/view — or a view whose filter/group/slice does not resolve — is
  a **template** defect: fix it on the golden template and re-copy. Never hand-add
  or hand-edit fields/views on a scaffolded project (it drifts).
- Never print the App token; the engine scrubs secrets from all output.
