# Acceptance Criteria rubric

The `AC-id` set is the **co-owned contract** across the issue, the deep spec (T3),
and `verify-spec`. spec-ops authors it; gh-projects mirrors and gates on it. These
rules decide whether an issue may enter `Ready`.

## Shape

- **A markdown table:** `| AC | Criterion |`. The `AC` column holds the **bare
  number**; `AC-N` is the id used everywhere else (TL;DR, spec, verify, PR review).
- Each row is **one atomic, observable end-state** — "X is true", never a task.
  "The token is minted from the App secrets" ✓ · "Mint the token" ✗.
- Optionally split into **ordered named groups**, one table per group. The named
  groups carry the structure — there is **no separate "phases" section**; each
  group's gate is *its `AC-N`s verify clean*.
- **Enumerated exhaustively, never condensed.** The "keep it digestible" rule
  applies to prose only — never collapse two criteria into one row.

## Ready gate (`ac_complete`)

`intake-issues` **refuses `Ready`** when AC are:

- prose-only (no table), or
- unverifiable / not an observable end-state (a task, an aspiration, a "should").

Each AC must be checkable offline or against real code / git / live read-only
state — that is what `verify-spec` later confirms (evidence **scaled to the
assertion**, a verification **method** recorded per AC, plus a **backward sweep**
for code that maps to no AC).

## AC-group count → size + Epic-split

`intake-issues` reads the **group count**:

- `1 → S`, `2–3 → M`, `4+ → L` (human-confirmed).
- At **>~3–4 groups**, recommend an **Epic split**: one **sub-issue per group**
  (`addSubIssue`), with each group's `needs §X` edge projected onto the board's
  native **blocked-by** relationship. The spec's dependency DAG *becomes* the
  board's (feeding Blast radius / Critical Path). Independent groups → no
  blocked-by → parallel work.

## Sync contract (one author, parity-enforced)

Shared `AC-id` namespace across **issue ↔ deep spec ↔ verify-spec**.

- **T1 / T2** — AC live in the **issue only**.
- **T3** — AC authored **once** in the spec-ops spec's `## Acceptance Criteria` and
  **mirrored to the issue**. The spec carries `issue: org/repo#NNN`; the issue
  carries the `spec:` link. CI fails on an **`AC-id` set divergence** or a 404
  `spec:` link. Anchor specs by **symbol name, not line number**.
