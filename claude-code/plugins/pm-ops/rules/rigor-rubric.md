# Rigor rubric

pm-ops uses **one format for every item** (`templates/spec.md`). What changes is
the *rigor* of the body — how much detail and process an item earns. Rigor is a
front-matter field (`rigor: light | full`) so it is queryable and drives routing,
but it is **invisible to developers**: every item they pick up is a complete spec.

This rubric is the single source of truth for choosing rigor. `consolidate-backlog`
suggests it; `draft-spec` confirms it and acts on it.

Both levels get their body from `spec-ops:write-spec` — spec-ops owns 100% of spec
content. Rigor decides only whether the heavy `refine-spec` grounding loop runs
afterward. `write-spec`'s conditional sections already make a trivial item's spec
short and a complex item's spec full, so the *format* is identical either way.

## The two levels

### `light` — write-spec only
A change small and self-evident enough that a single `write-spec` pass fully
captures it. `draft-spec` sets the front-matter and hands the body to
`spec-ops:write-spec`; no `refine-spec`.

Pick `light` when **all** hold:
- One repo, one surface, no schema/contract/API change.
- Approach is obvious; no meaningful design choice to make.
- Size S–M; reviewable in a single sitting.
- No data migration, no cross-team or cross-service coordination.
- Low blast radius if it's wrong (easily reverted).

Typical: copy tweaks, config flips, isolated bug fixes, small additive endpoints,
dependency bumps, well-trodden CRUD.

### `full` — write-spec + refine-spec
A change with enough surface area, ambiguity, or risk that it needs real design
work. `draft-spec` hands the body to `/spec-ops:write-spec` and then additionally
runs `/spec-ops:refine-spec` to ground and harden it.

Pick `full` when **any** hold:
- Schema / data migration, public API or contract change, auth/permissions/billing.
- A genuine design decision or trade-off (multiple viable approaches).
- Spans multiple repos, services, or teams.
- Size L–XL, or size is unknown because the problem isn't yet understood.
- High blast radius, security/privacy/compliance surface, or hard-to-reverse.
- Anyone has said "we should write this up properly."

When light vs. full is a close call, choose **full** — a too-detailed spec wastes
minutes; an under-specified one wastes the implementation.

## `epic` is a type, not a rigor
An umbrella that decomposes into child items is `type: epic`. The epic file itself
is usually `rigor: light` (it points at children); each child gets its own rigor.
Children carry `parent: <epic-id>`.

## Recording the decision
- Set `rigor:` in front-matter.
- For `full`, note the trigger in the item's Notes ("full: schema migration +
  cross-service"). This makes later audits of "why is this heavy?" trivial.
