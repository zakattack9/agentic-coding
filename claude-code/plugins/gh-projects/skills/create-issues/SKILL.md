---
name: create-issues
description: >-
  Turn a raw dump of feature ideas / bugs / chores into board issues through a
  resumable decompose -> refine -> promote pipeline over a local, git-tracked
  staging area — not a one-shot dump. Each candidate becomes a local DRAFT
  (decompose), gets its body + grouped "## Acceptance Criteria" authored by
  spec-ops (refine), and is created as a tiered, field-complete issue only once
  it passes the readiness bar (promote). Use when the user pastes a backlog
  brain-dump, a PRD, a list of "things to build", or asks to "intake", "triage
  into issues", "break this into issues", "file these as tickets", or "turn this
  into a board" — including resuming an interrupted intake (unpromoted drafts
  persist). It REFUSES to promote a draft that is not ready, stating why. It
  DELEGATES all spec/AC authoring to spec-ops:write-spec at the tier's rigor (and
  refine-spec for T3) — it never writes an issue body itself. It does NOT scaffold
  the repo/project (scaffold-repo), assign sprints (plan-sprint), or move board
  status (board-sync). Dry-by-default: it previews every promote and creates
  nothing until you confirm.
model: claude-opus-4-8
effort: high
allowed-tools: Bash(python3 *), Bash(bash *), Bash(gh issue create *), Bash(gh issue view *), Read, Edit, AskUserQuestion, Skill
argument-hint: "[raw dump text or path to a file/PRD] (resumes unpromoted drafts; creates nothing until you confirm)"
references:
  - ${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md
  - ${CLAUDE_PLUGIN_ROOT}/rules/composition.md
---

# create-issues

Compile a raw dump into tiered, AC-bearing GitHub issues through a **resumable
three-stage pipeline** over a local staging area: **decompose → refine →
promote**. Three hard rails define this skill:

1. **Nothing reaches the board until it is ready.** Candidates live as local
   DRAFTS in a git-tracked staging area; only a `ready` draft is **promoted** to a
   real issue. Readiness — not batch size — decides what reaches the board. There
   is **no input-size threshold** that bypasses staging.
2. **You author NO issue body or AC list yourself.** All spec/AC authoring is
   DELEGATED to **spec-ops** at the tier's rigor, resolved against the **local
   draft file** (no GitHub issue exists yet).
3. **Every non-AI decision comes from the engine** — `lib/intake.py` (size,
   tier→rigor, Epic-split + blocked-by edges, AC ready-gate) and `lib/backlog.py`
   (the staging ledger + the deterministic promote). Never re-derive these in
   prose; the scripts are the source of truth (and the only thing tested).

Let `INTAKE=${CLAUDE_PLUGIN_ROOT}/lib/intake.py` and
`BACKLOG=${CLAUDE_PLUGIN_ROOT}/lib/backlog.py`. All GitHub writes go through
`lib/gh.py` with a **GitHub App installation token** (never `GITHUB_TOKEN`). **No
model/metered call happens in any workflow this skill installs** — the AI work is
your own reasoning here, at intake time only.

Read `${CLAUDE_PLUGIN_ROOT}/rules/composition.md` for the split / Epic-vs-Milestone
/ `Type`-boundary judgment calls, and `${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md`
for the field/option terms, the orthogonal-axis distinctions (Size vs Tier vs
Priority), and the staging lifecycle terms (stub / drafting / ready / promoted).

## The staging area is resumable

The pipeline shares **one persistent ledger** at the git root —
`<git-root>/.gh-projects/backlog/` (git-tracked, team-visible). An interrupted
intake leaves finished drafts on disk; **re-running create-issues resumes the
unpromoted ones** without redoing finished work. Start every run by listing what
already exists:

```bash
python3 "$BACKLOG" list      # the drafts + statuses (stub/drafting/ready/promoted)
```

Resume any draft that is not yet `promoted`; only add new drafts for genuinely new
candidates.

## Stage 1 — DECOMPOSE: dump → draft stubs + the tree

Read the dump (argument is raw text or a file path). Break it into the smallest
**independent** items — one deliverable per item. For each, decide its **Type**
(`Feature | Bug | Chore | Infra`) and **Tier** (`T1 trivial | T2 standard | T3
complex`) by surface area, risk, and unknowns, then capture it as a stub:

```bash
python3 "$BACKLOG" add --title "<title>" --type <Type> --tier <T1|T2|T3> [--repo owner/name] --force
```

Then propose an **epic / sub-issue / standalone tree** per
`${CLAUDE_PLUGIN_ROOT}/rules/composition.md` (Epic-vs-Milestone, when-to-split,
Type boundaries). **The split is not free-hand** — it is validated by the
deterministic AC-group-count heuristic once spec-ops has authored the AC groups
(`size_from_groups` / `should_epic_split` / `epic_split` in `lib/intake.py`).
Record the tree in the ledger:

```bash
python3 "$BACKLOG" link <child-slug> --parent <epic-slug> [--blocked-by <sibling-slug> ...] --force
```

Each draft starts at `stub`. Do **not** write AC or a body yet — that is Stage 2.

## Stage 2 — REFINE: author body + AC via spec-ops, against the local draft

Move each draft to `drafting`, then DELEGATE its body + AC to **spec-ops** via the
**Skill** tool — you author nothing inline. Confirm the tier→rigor mapping from the
script; never guess (the map is pinned — do not widen it):

```bash
python3 "$BACKLOG" set-status <slug> drafting --force
python3 "$INTAKE" rigor "<T1|T2|T3>"
# -> {"tier","rigor","refine","write_spec":"spec-ops:write-spec","refine_spec":...}
```

| Tier | Invoke | Rigor arg | Then |
|------|--------|-----------|------|
| T1 | `spec-ops:write-spec` | `light` | AC table only (≈ the issue body) |
| T2 | `spec-ops:write-spec` | `standard` | TL;DR + AC + Boundaries + lean body |
| T3 | `spec-ops:write-spec` | `full` | self-contained deep spec → then `spec-ops:refine-spec` to harden + commit the `needs §X` DAG |

Pass spec-ops the item's intent + the **shape** to fill —
`${CLAUDE_PLUGIN_ROOT}/templates/issue-body.md` (T1/T2) or
`${CLAUDE_PLUGIN_ROOT}/templates/deep-spec.md` (T3) — and resolve any clarifying
questions **against the local draft file** (no GitHub issue exists yet). Write
spec-ops's returned body into the draft file (`Edit`), and persist the proposed
triage fields:

```bash
python3 "$BACKLOG" set-fields <slug> --type <Type> --tier <T1|T2|T3> --priority <P0|P1|P2|P3> [--repo owner/name] --force
```

> Never substitute your own body for spec-ops's output. If spec-ops is
> unavailable, STOP and tell the user — do not hand-author AC.

### Validate size, split, and the ready-gate (deterministic)

Feed each draft's spec-ops AC groups to the core. It derives Size from the AC-group
count (`1→S · 2–3→M · 4+→L`), the Epic-split + blocked-by edges, AND the AC ready
decision:

```bash
echo '{"type":"Feature","tier":"T3","pm_id":"PM-0000","title":"…",
  "groups":[{"index":1,"name":"core","needs":[],"ac":["the core module is importable"]},
            {"index":2,"name":"api","needs":[1],"ac":["the API responds with JSON"]}]
}' | python3 "$INTAKE" plan
```

(The `pm_id` here is a placeholder for the plan preview — the real PM-#### is
allocated by promote. A group's `needs` lists the group indices it depends on.) If
the plan's `ready` is **false**, the AC are prose-only / not atomic: surface
`ready_reason` + each rejection to the user, ask spec-ops to rewrite the offending
AC as observable end-states, and re-plan — **do not** mark the draft `ready`. If
`epic_split` is true, the tree from Stage 1 must match (one sub-issue per group,
each `needs` edge projected onto a blocked-by relationship). Set the validated `--size` on the
draft, then clear the draft to promote:

```bash
python3 "$BACKLOG" set-fields <slug> --size <S|M|L> --force
python3 "$BACKLOG" set-status <slug> ready --force   # only when the plan's ready == true
```

## Stage 3 — PROMOTE: ready draft → board issue (DRY BY DEFAULT)

Promote is deterministic and **one-way** (`lib/backlog.py promote`). It readiness-
gates (a stub/drafting draft is refused with a reason), allocates the PM-####,
creates the issue, adds it to the board + sets `Type/Tier/Priority/Size/PM-ID/Spec`
via the **App installation token**, establishes the recorded parent/sub-issue +
blocked-by edges, lands the item at **Backlog**, and — once promoted — **removes
the staging file** so the issue is the only source of truth. For **T3** the deep
spec is published to a durable `specs/<slug>.md` and `Spec` links it; **T1/T2**
leave `Spec` empty.

**Preview first — every time.** A dry run previews the planned `gh issue create` +
field writes + links and mutates nothing:

```bash
python3 "$BACKLOG" promote <slug> --owner <org> --number <project#>            # dry preview
```

State plainly: **"Dry run — nothing created yet."** Promotion mutates the external
board, so confirm with **AskUserQuestion** before any write. Until the user
confirms, you have created **zero** issues. On confirm, re-run **identically with
`--force`** — promote a parent Epic before its sub-issues so the links resolve. A
re-run on an already-promoted draft is a clean no-op (it reuses the recorded issue
number — never a duplicate):

```bash
python3 "$BACKLOG" promote <slug> --owner <org> --number <project#> --force    # creates + lands at Backlog
```

## Report

For each promoted draft: issue number + URL, `Type/Size/Tier/PM-ID`, the AC-group
count and Size rationale, the `Spec` link (T3) or empty (T1/T2), and — for Epics —
the parent plus the sub-issue/blocked-by DAG. Name any draft still in
`stub`/`drafting`/`ready` (not yet promoted) and what it is waiting on, so the next
run resumes it.

## Guardrails

- **Resumable, readiness-gated.** Unpromoted drafts persist; re-running resumes
  them. Only a `ready` draft promotes — never a stub/drafting one. No batch-size
  threshold bypasses staging.
- **Dry-by-default.** Preview every promote first; `--force` only after the user
  confirms. Promotion is **one-way** — the staging file is removed on promote and
  the issue is canonical thereafter.
- **Never author a body/AC inline.** Delegate to `spec-ops:write-spec` at the
  tier's rigor (T3 also `spec-ops:refine-spec`), resolved against the local draft.
  The spec-ops interface is pinned in `lib/intake.py` — do not widen it.
- **Size/split are the script's, not yours.** Size = AC-group count; Epic-split +
  blocked-by edges come from `lib/intake.py plan`; the staging ledger + promote
  from `lib/backlog.py`.
- **App installation token for every Projects v2 write** — never `GITHUB_TOKEN`,
  never printed. Native sub-issue/blocked-by only; no label-based dependency
  fallback. Issues are never auto-closed by "Closes #N" (closed at prod by
  `board-status`).
- **No metered AI in any installed workflow.**
