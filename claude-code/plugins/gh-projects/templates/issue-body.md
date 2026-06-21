<!--
Issue body skeleton — this IS spec-ops:write-spec's output shape for an intake
issue (T1 `light` / T2 `standard`). The create-issues skill NEVER hand-authors
this body; it delegates authoring to spec-ops at the tier's rigor and pastes the
result here. Order is load-bearing:

  Goal (1 line) -> TL;DR (points at AC-ids) -> ## Acceptance Criteria (grouped
  tables) -> Boundaries -> Spec link (T3 only).

The named AC groups carry the structure — there is NO separate "phases" section;
each group's gate is "its AC-N verify clean". Fill every {{...}}; delete any line
that does not apply; never invent a value. Drop the comment block on create.
-->

## Goal

{{one-line statement of the observable outcome this issue delivers}}

## TL;DR

{{2-4 lines a reviewer must not miss. Each "breaks if missed" point cites the AC
it maps to, e.g. "Token never logged (AC-3)." Prose stays digestible — the AC
table below is the exhaustive contract, this is the summary.}}

## Acceptance Criteria

<!--
One markdown table PER ordered named group (capability cluster). The `AC` column
holds the BARE number; cite ids elsewhere as `AC-N`. Each row is ONE atomic,
observable end-state ("X is true / returns / renders ..."), NEVER a task.
Enumerate exhaustively — never condense AC. `create-issues` REFUSES `Ready` for
any prose-only / non-atomic row (lib/intake.py ready_gate). Number AC
consecutively ACROSS groups (do not restart per group). Group order + any
`needs §X` build dependency is recorded in the deep spec for T3 / projected onto
the board's blocked-by edges when an Epic is split.
-->

### Group 1 — {{group name, e.g. "core"}}

| AC | Criterion |
|----|-----------|
| 1 | {{atomic observable end-state}} |
| 2 | {{atomic observable end-state}} |

### Group 2 — {{group name}} <!-- repeat per group; delete if single-group -->

| AC | Criterion |
|----|-----------|
| 3 | {{atomic observable end-state}} |

## Boundaries

- **Do NOT** {{out-of-scope work this issue must not touch}}
- {{file/area ownership note, if any}}

## Spec

<!-- T3 ONLY: link the self-contained deep spec authored by spec-ops (full rigor
+ refine-spec). The spec carries `issue: org/repo#NNN`; this link + the AC-id set
are parity-checked. Delete this whole section for T1/T2 (AC live in the issue). -->

spec: {{repo-relative path, e.g. `specs/<slug>.md`}}
