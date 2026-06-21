# The Acceptance Criteria contract

The conventions every spec-ops spec's **Acceptance Criteria** follow. `write-spec` drafts the table to these rules; `refine-spec` hardens it to them. This file is the single source for the *shared* conventions — each skill keeps only its own stage-specific application inline and points here for the rest.

## Contents
- [What the table is](#what-the-table-is)
- [The id convention](#the-id-convention)
- [Exhaustive enumeration](#exhaustive-enumeration)
- [Each criterion is one atomic, observable end-state](#each-criterion-is-one-atomic-observable-end-state)
- [Non-functional constraints](#non-functional-constraints)
- [Grouping & ordering](#grouping--ordering)
- [The Checklist is an index, not a copy](#the-checklist-is-an-index-not-a-copy)

## What the table is

Lead the spec with a **markdown table** of acceptance criteria — every behavior and constraint that must hold once the change is done, each row a single testable assertion:

```markdown
| AC | Criterion |
|----|-----------|
| 1  | {single testable assertion about the end state} |
| 2  | {…} |
```

This table is the spec's **contract**: it is the reader's two-minute scan of *what must be true*, and it is what the implementation is later gated against, criterion by criterion (`launch-spec`'s done-gate and `verify-spec` check it 1:1). It is load-bearing — never cut it as bloat.

## The id convention

The `AC` column holds the **bare stable number** (`1`, `2`, …; the header already says "AC", so don't repeat the prefix). **Everywhere else** — the body, the Checklist, the gates — cite it as **`AC-1`, `AC-2`, …**. Ids are **globally unique and stable**, including across groups; they never get renumbered when the table is regrouped.

## Exhaustive enumeration

**Enumerate exhaustively — never condense.** Unlike prose, which you cut to the bone, the criteria are the one place you list *everything*. A requirement that lives only in a paragraph below is a requirement that gets missed at completion — brevity is for wording, not for coverage. A separate **Validation** or "how we'll test it" list is acceptance criteria wearing another hat: put those assertions here, not in a parallel section.

## Each criterion is one atomic, observable end-state

Phrase **what is true when done** (so it's checkable), not a task to do: "Unrouted mail is quarantined, never dropped" — not "build the quarantine system". Keep each criterion behavior-level and atomic (split compound ones); the detailed rule that *implements* it lives in the body and carries its `AC-id`, so each fact is stated once, at its altitude.

Where a **thin end-to-end path** ("walking skeleton") matters, encode it as a behavioral AC — *an end-to-end path from {X} to an observable {Y} runs* — not an instruction to "build the skeleton first". It stays checkable like any other criterion and naturally becomes a group's "start here" AC.

## Non-functional constraints

Don't silently drop them. Performance, security, idempotency, limits, concurrency — if the change implies one, make it its **own `AC`**. These are the requirements most often lost, and a capable implementer will silently skip what isn't written.

## Grouping & ordering

A **single flat table is the default**. Group only when it earns its keep — the ACs fall into **≥2 recognizable capability clusters** (a "what am I building" map), *or* a real cross-group dependency exists. When you group: one **`###` named header per group**, **one table per group**, ids still globally unique and stable.

Ordering is **dependency-derived only** — never a guessed or scheduling order, and **no dates, time-boxes, or effort estimates**. A `needs §X` header edge is the *only* binding order and may be added **only for a real dependency grounded against the codebase**; group sequence is otherwise just a suggested reading order. Prefer ≥2 ACs per group (a solo-AC group is allowed only for a genuine "start here" capability).

> Which stage commits what: **`write-spec`** may *loosely* group an obvious ≥2-cluster table as a reader's map, but does **not** assert a build order or any `needs §X` edge — that is a grounded fact. **`refine-spec`** commits the grounded group order and adds `needs §X` edges after checking them against the code. If grouping would exceed ~5–6 groups, distinguish the cause: a spec **bundling independent changes** → recommend splitting the spec; **one coherent change with real cross-group dependencies** → keep it whole and let `launch-spec` phase the build by group. The trigger to split is *independence*, not the count.

## The Checklist is an index, not a copy

The AC table is the *assertion* view (what must be TRUE); the body is the *detail* view (how/where + the load-bearing why); the **Checklist** is the *task* view, organized by the one axis neither gives — **code area**. Include it only when the work spans several code areas and a "by where in the code" map helps. Each item is **one line**: name the area's work in a few words and cite the `AC-id`(s) it lands — **never** re-describe what the criteria assert. A Checklist item must never be the sole home of a fact (exact config values, paths, resource names belong in the body or an AC; the item points at them). If a Checklist currently paraphrases the ACs, collapse each item to a one-line code-area pointer after moving any Checklist-only fact into the body.
