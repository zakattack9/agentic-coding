# The Acceptance Criteria contract

The conventions every spec-ops spec's **Acceptance Criteria** follow. `write-spec` drafts the table to these rules; `refine-spec` hardens it to them. This file is the single source for the *shared* conventions — each skill keeps only its own stage-specific application inline and points here for the rest.

## Contents
- [What the table is](#what-the-table-is)
- [The id convention](#the-id-convention)
- [Exhaustive enumeration](#exhaustive-enumeration)
- [Each criterion is one atomic, observable end-state](#each-criterion-is-one-atomic-observable-end-state)
- [Non-functional constraints](#non-functional-constraints)
- [Grouping & ordering](#grouping--ordering)
- [The Checklist — verification in two subsections](#the-checklist--verification-in-two-subsections)

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

## The Checklist — verification in two subsections

The AC table is the *assertion* view (what must be TRUE); the body is the *detail* view (how/where + the load-bearing why). The **`## Checklist`** is the *verification* view — how a reader confirms each criterion actually holds once the change is built. It is the **final section** of the spec and splits into exactly two subsections **by the kind of check**. There are no inline per-item `human` / `auto` tags and no second checklist section anywhere.

- **`### For agents`** — checks whose observation *and* pass / fail rule an agent or CI can both run: a command, a test, a static read. Each item is terse and runnable — name the exact command or test and its expected result.
- **`### For humans`** — checks that need human judgment: a UI clickthrough, a visual or UX read, a logic review. Each item is a scenario walkthrough in read-then-do form — a setup / precondition where needed, one observable action, and the expected observable result — phrased so a zero-context, non-native-English reader can perform it without reading code.

**Trace, don't re-describe.** Each *verification* item ends with a parenthetical `(AC-…)` citing only existing ids; the criterion text already lives in the AC table. The `**Setup:**`, "Explore on your own", and Sign-off lines are structural and carry no trace. A checklist item verifies an existing criterion — it never introduces a requirement, value, or success criterion absent from the table, and is never the sole home of a fact.

**Coverage is exhaustive** across the two subsections: every AC (at standard / full) is traced by ≥1 item, and every cited id references a real criterion (no orphans). One item may cover several closely-related ACs; one AC may need several items. A criterion that is part agent-checkable and part human-judgment appears in **both** subsections — the `### For humans` line marked `(partial)`. Label by the *kind of check*, not perfectly by the person; don't force a part-automatable criterion into exactly one subsection.

### The `### For humans` structure

`### For humans` groups its checks under user-facing capabilities or flows (about 5–9 checks per group), not one flat list. At **full** rigor it:

- **opens with the critical happy-path ("smoke") checks** — the "does it even work" path — and includes the empty / edge / error cases the spec calls for, not happy-path only;
- states any **setup** the checks need (role, state, test data, where to look) in plain placeholders, so performing the section never requires reading the codebase;
- **ends with an "Explore on your own" block** that sends the verifier *past* the scripted checks — a short list of open scenarios plus a short list of test ideas to vary (data values, boundaries, create / read / update / delete, interruptions, roles / devices) — and restates no scripted check;
- **closes with a sign-off checklist** of exit conditions (all checks pass, exploration done, no open critical defects).

The "Explore on your own" block **complements, never repeats**: it lists only what the scripted checks deliberately leave open — if an item would restate a scripted check, drop it. Push genuinely open-ended or subjective checks *into* Explore rather than bloating the scripted list.

### Rigor scaling

- **`light`** — no Checklist (the AC table alone).
- **`standard`** — a lean form: `### For agents` plus a lean `### For humans` of capability checks and a short explore prompt.
- **`full`** — the complete structure: smoke checks first, grouped capability checks with the required edge / error cases, the full explore block, and the sign-off.

The write-spec skeleton carries the fill-in template. This checklist is the single verification section — it replaces any older "code area → `AC-id`" index; a spec still carrying that flat legacy shape (no `### For agents` / `### For humans`) is a pre-format spec and is left as-is.
