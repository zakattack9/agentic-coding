---
id: {{ID}}
title: {{TITLE}}
type: {{feature|bug|chore|epic}}
status: {{draft|active}}
size: {{S|M|L|XL}}
priority: {{P0|P1|P2|P3}}
rigor: {{light|full}}
parent: {{PM-#### if part of an epic, else omit}}
depends_on: []
spec: {{specs/<stage>/<this-file> — set once placed, else omit}}
impl_repo: {{owner/name — target implementation repo, else omit}}
labels: []
assignees: []
created: {{YYYY-MM-DD}}
---

<!--
ONE format for every item — spec-ops owns 100% of the body; rigor only decides
whether refine-spec runs. The skeleton below is a SEED for spec-ops:write-spec
(so it inherits the pm-ops shape), not something to fill in by hand:

• rigor: light  → /spec-ops:write-spec authors the body (short, via its
                  conditional sections). No refine-spec.
• rigor: full   → /spec-ops:write-spec then /spec-ops:refine-spec.

Keep this front-matter block as the pm-ops wrapper; spec-ops rewrites everything
under it. The front-matter is the engine-neutral contract pm.py reads. Never
hand-edit `id`; never change it as the file moves between folders. See
rules/repo-conventions.md.
-->

## TL;DR
{{One paragraph: what changes and why, in plain language.}}

## Acceptance criteria
- [ ] {{Observable, testable outcome.}}
- [ ] {{Another outcome.}}

## Out of scope
- {{What this explicitly does NOT cover, to bound the work.}}

## Implementation checklist
- [ ] {{Concrete step.}}
- [ ] {{Concrete step.}}

## Notes
- {{Links, prior art, open questions. Delete if none.}}
