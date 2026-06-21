---
name: create-issues
description: >-
  Turn a raw dump of feature ideas / bugs / chores into individual, tiered,
  field-complete GitHub issues on the board — each with Type/Size/Tier/PM-ID and
  a grouped "## Acceptance Criteria" table of atomic observable end-states. Use
  when the user pastes a backlog brain-dump, a PRD, a list of "things to build",
  or asks to "intake", "triage into issues", "break this into issues", "file
  these as tickets", or "turn this into a board". It REFUSES to mark prose-only /
  non-atomic items `Ready`, stating why. It DELEGATES all spec/AC authoring to
  spec-ops:write-spec at the tier's rigor (and refine-spec for T3) — it never
  writes an issue body itself. It does NOT scaffold the repo/project (scaffold-repo),
  assign sprints (plan-sprint), or move board status (board-sync). Dry-by-default:
  it previews every draft and creates nothing until you confirm.
model: claude-opus-4-8
effort: high
allowed-tools: Bash(python3 *), Bash(bash *), Bash(gh issue create *), Bash(gh issue view *), Read, Edit, AskUserQuestion, Skill
argument-hint: "[raw dump text or path to a file/PRD] (creates nothing until you confirm)"
---

# create-issues

Compile a raw dump into tiered, AC-bearing GitHub issues on the board. Two hard
rails define this skill:

1. **You author NO issue body or AC list yourself.** All spec/AC authoring is
   DELEGATED to **spec-ops** at the tier's rigor. You only split the dump
   into atomic items, run the deterministic core for every non-AI decision, and
   create issues on confirm.
2. **Every non-AI decision comes from `lib/intake.py`** — size, tier→rigor, the
   Epic-split + blocked-by edges, and the AC ready-gate. Never re-derive these in
   prose; the script is the source of truth (and the only thing tested).

Let `INTAKE=${CLAUDE_PLUGIN_ROOT}/lib/intake.py`,
`PM=${CLAUDE_PLUGIN_ROOT}/lib/pm.py`, and
`GH=${CLAUDE_PLUGIN_ROOT}/lib/gh.py`. All GitHub writes go through `gh` / `lib/gh.py`
with a **GitHub App installation token** (never `GITHUB_TOKEN`). **No model/metered
call happens in any workflow this skill installs** — the AI work is your own
reasoning here, at intake time only.

## 1. Split the dump into atomic items

Read the dump (argument is raw text or a file path). Break it into the smallest
**independent** items — one deliverable per item. For each, decide:

- **Type** ∈ `Feature | Bug | Chore | Infra` (matches the issue-form enum).
- **Tier** ∈ `T1 trivial | T2 standard | T3 complex` — judge by surface area,
  risk, and unknowns. (See `${CLAUDE_PLUGIN_ROOT}/rules/tier-rubric.md` if present.)

Do **not** write AC or a body yet — that is spec-ops's job (step 3).

## 2. Allocate a PM-#### per item (deterministic)

```bash
python3 "$PM" new-id --repo "<pm-repo-or-.>"     # prints e.g. PM-0042, monotonic
```

One id per item. These become the issue's `PM-ID` field.

## 3. Delegate body + AC to spec-ops AT THE TIER'S RIGOR

For each item, invoke spec-ops via the **Skill** tool — you author nothing inline.
The tier→rigor mapping is deterministic; confirm it from the script, never guess:

```bash
python3 "$INTAKE" rigor "<T1|T2|T3>"
# -> {"tier","rigor","refine","write_spec":"spec-ops:write-spec","refine_spec":...}
```

| Tier | Invoke | Rigor arg | Then |
|------|--------|-----------|------|
| T1 | `spec-ops:write-spec` | `light` | AC table only (≈ the issue body) |
| T2 | `spec-ops:write-spec` | `standard` | TL;DR + AC + Boundaries + lean body |
| T3 | `spec-ops:write-spec` | `full` | self-contained deep spec → then `spec-ops:refine-spec` to harden + commit the `needs §X` DAG |

Pass the item's intent + the **shape** to fill:
`${CLAUDE_PLUGIN_ROOT}/templates/issue-body.md` (T1/T2) or
`${CLAUDE_PLUGIN_ROOT}/templates/deep-spec.md` (T3). spec-ops returns the body and
the **ordered named AC groups** (each row an atomic observable end-state). For
**T3**, run `spec-ops:refine-spec` next; it commits the grounded `needs §X` build
DAG you'll project onto blocked-by edges in step 5.

> Never substitute your own body for spec-ops's output. If spec-ops is
> unavailable, STOP and tell the user — do not hand-author AC.

## 4. Run the deterministic plan + ready-gate

Feed each item (with spec-ops's AC groups) to the core. It computes the issue
fields, the size + Epic-split, the blocked-by edges, AND the AC ready decision:

```bash
echo '{
  "type":"Feature","tier":"T3","pm_id":"PM-0042","title":"…",
  "groups":[
    {"index":1,"name":"core","needs":[],        "ac":["the core module is importable"]},
    {"index":2,"name":"api", "needs":"needs §1", "ac":["the API responds with JSON"]}
  ]
}' | python3 "$INTAKE" plan
```

The result carries:

- `fields` — **Type / Size / Tier / PM-ID** the issue must set. Size is
  **derived from the AC-group count** (`1→S · 2–3→M · 4+→L`) — not free-chosen.
- `ready` + `ready_reason` + `rejections` — the **`Ready` gate**. If
  `ready` is **false**, the AC are prose-only / not atomic; **do NOT set Status
  `Ready`** and surface `ready_reason` + each rejection's reason to the user. Ask
  spec-ops to rewrite the offending AC as observable end-states, then re-plan.
- `epic_split` + `sub_issues` + `blocked_by_edges` — the Epic decision.

The body itself stays spec-ops's; this script only decides fields/size/split/ready.

## 5. Preview every draft — DRY BY DEFAULT

Build the full preview WITHOUT touching GitHub. For each item show: title, the
`fields` block, the grouped AC table (from spec-ops), the `Ready` verdict (+
reason if refused), and — when `epic_split` is true — the parent Epic plus **one
sub-issue per group**, with each sub-issue's `blocked_by` (the `needs §X` edges).

State plainly: **"Dry run — nothing created yet."** Creating issues mutates the
external board, so confirm with **AskUserQuestion** before any write. Until the
user confirms, you have called `gh issue create` **zero** times.

## 6. On confirm — create issues, fields, and the Epic DAG

Only after explicit confirmation:

1. `gh issue create` each issue (parent Epic first, then its sub-issues), with
   `--type <Type>`. Capture each issue's node id / number.
2. Add each to the Project and set **Type/Size/Tier/PM-ID** via `lib/gh.py`
   (`write_field`) using the **App installation token** (never `GITHUB_TOKEN`).
3. Set Status `Ready` **only** for items whose plan returned `ready: true`.
   Refused items stay in `Backlog` with the reason recorded.
4. For an Epic: link each group's sub-issue under the parent with
   `lib/gh.py add_sub_issue`, then project every `blocked_by_edges` pair onto a
   native **blocked-by** relationship with `lib/gh.py add_blocked_by` (no
   label-based dependency — native only). Independent groups get **no** edge → they
   parallelize.
5. **T3**: write the spec to `specs/<slug>.md`, set the issue's `spec:` link, and
   ensure the spec's `issue:` + AC-id set match the issue (parity).

## 7. Report

For each item: issue number + URL, `Type/Size/Tier/PM-ID`, the AC-group count and
Size rationale, `Ready` vs refused (with the reason), and — for Epics — the parent
plus the sub-issue/blocked-by DAG. Name anything left in `Backlog` and why.

## Guardrails

- **Dry-by-default.** Preview first, every time; `gh issue create` only after the
  user confirms.
- **Never author a body/AC inline.** Delegate to `spec-ops:write-spec` at the
  tier's rigor; T3 also runs `spec-ops:refine-spec`.
- **Never mark prose-only/non-atomic AC `Ready`** — honor `lib/intake.py`'s
  `ready_gate`; state the refusal reason.
- **Size/split are the script's, not yours.** Size = AC-group count; Epic-split +
  blocked-by edges come from `lib/intake.py plan`.
- **App installation token for every Projects write** — never `GITHUB_TOKEN`.
  Native sub-issue/blocked-by only; no label-based dependency fallback.
- **No metered AI in any installed workflow.** Issues are never
  auto-closed by "Closes #N" (closed at prod by `board-status`).
