<!--
T3 deep-spec skeleton — the self-contained spec spec-ops authors at `full` rigor
(then hardens via spec-ops:refine-spec). Lives at `specs/<slug>.md` in the impl
repo and is LINKED from the tracker issue (T3 only; T1/T2 keep AC in the issue).

Sync contract (one author, parity-enforced):
  * `issue:` below names the tracker issue (org/repo#NNN); the issue carries this
    spec's path as `spec:`. CI fails on a 404 `spec:` or AC-id set divergence.
  * The `## Acceptance Criteria` AC-id set here is the SAME namespace as the
    issue's and is MIRRORED to it. AC are authored ONCE (here) for T3.
  * Anchor every code reference by SYMBOL NAME (function/class/file), NEVER a
    line number — line numbers rot.

Fill every {{...}}; drop lines that don't apply; never invent a value. Remove
this comment block when the spec is finalized.
-->

---
issue: {{org/repo#NNN}}
tier: T3
type: {{Feature|Bug|Chore|Infra}}
pm_id: {{PM-####}}
---

# {{Title}}

## Goal

{{one-line observable outcome}}

## Context

{{What exists today and why this change is needed. Anchor any existing code by
symbol name — e.g. "the `resolve()` method on `Project` in `lib/gh.py`" — never
"line 347". Keep it grounded: cite real symbols, not invented ones.}}

## Acceptance Criteria

<!--
The co-owned contract. One table per ordered named group; `AC` column = bare
number; cite as `AC-N`. Each row = one atomic, observable end-state with a
concrete `Verify` check. Numbered consecutively across groups; MIRRORED verbatim
to the issue (same id set). `verify-spec` consumes these: it scales evidence to
the assertion, records a `method` per AC, and runs a backward sweep for scope
creep. The groups carry the `needs §X` build DAG (below) — projected onto the
board's blocked-by edges when the Epic is split.
-->

### 1. {{group name}} — start here
| AC | Criterion | Verify |
|----|-----------|--------|
| 1 | {{atomic observable end-state}} | {{concrete check}} |

### 2. {{group name}} — needs §1
| AC | Criterion | Verify |
|----|-----------|--------|
| 2 | {{atomic observable end-state}} | {{concrete check}} |

## Build order (DAG)

{{The grounded `needs §X` dependency graph refine-spec commits — NOT a linear
list. Independent groups parallelize (no blocked-by). E.g.:
"§2–§4 parallelize after §1; §5 needs §2." Projected onto the board, this DAG IS
the Epic-split: one sub-issue per group, each `needs §X` -> a native blocked-by
edge.}}

## Boundaries / non-goals

- **Do NOT** {{out-of-scope work}}
- {{files/areas this spec must not touch}}

## Affected symbols

{{Bulleted list of the functions/classes/files this change touches, by SYMBOL
NAME. The anchor `verify-spec`'s backward sweep maps against — keep it accurate.}}
