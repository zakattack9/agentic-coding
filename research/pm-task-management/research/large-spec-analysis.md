Let me look at both specs in parallel.

Now let me fetch both spec files in parallel.

Let me get the Turo README and specs directory contents in parallel.

Let me get the functional requirements spec to complete the picture.

I've now read both specs in full. Here's my analysis and recommendation.

---

## What these two specs reveal about the trade-off

**CDN spec** — technical detail is *the* spec. Infrastructure has essentially one correct configuration, so "what it does" and "how to do it" are inseparable. The TL;DR at the top is genuinely excellent — it names the 4 things that break the site, which is what any implementer needs to read first. But then the spec front-loads 11 sections of dense mixed prose before the checklist, and there's no explicit phase ordering — the checklist is by component (Terraform, WAF, nginx, deploy) not by deployment sequence. An implementer has to mentally reconstruct "do X before Y or it doesn't work" from cues buried in prose.

**Turo spec** — the functional requirements doc is clean, portable, and has exactly the right structure: purpose → constraints → numbered FRs → numbered ACs. The 18 ACs are specific and testable. The problem is the inverse: the functional requirements *alone* leave too much ambiguous for an implementer. The 4 supplementary docs (pipeline-architecture, email-processing, booking-synchronization, error-handling) exist precisely because FR-3.4.5 ("create the booking in CANCELLED state") doesn't tell you about idempotency key strategy, DLQ topology, or AI prompt design. A dev has to read all 5 documents to build the thing confidently.

---

## Direct answers to your questions

**Functional only vs. with technical details?**

It depends on the domain:

- **App features** → functional-first is correct. The *what* is genuinely separable from the *how*, and an AI agent can derive implementation from good FRs + knowledge of the codebase. The Turo FR doc is the right artifact to write; the architecture docs are optional reference.
- **Infra/systems work** → the technical spec IS the spec, because there's no meaningful "how would you implement this?" ambiguity — there's just the right Terraform resource with the right arguments. The CDN spec's technical depth is appropriate. You can't reduce it to FRs without losing the actual spec.

**One developer vs. multiple developers?**

Stick to one developer + AI for each spec. The value of one person holding the full context is higher now, not lower — because AI handles the mechanical implementation, the bottleneck has shifted to architectural coherence, not typing speed. The CDN spec has natural seams that *could* be parallelized (Terraform, app code, nginx, deploy pipeline), but those seams also have dependencies that create integration bugs when worked in parallel. The person who lands the `?v=` filter needs to know the cache policy key configuration; the person doing the nginx `Cache-Control` header needs to know that `immutable` is only safe *after* the filter is in place. These are coordination costs that eat the parallel-dev gain.

**How to make large specs more quickly digestible?**

The biggest problem in both specs is that they're written for reading *from the top*, but implementers (and agents) need to know *where to start and in what order*. Here's what I'd change:

**Add explicit phases with scoped acceptance criteria.** The checklist at the bottom of the CDN spec is excellent — but it's in the wrong place and in the wrong structure. It should be at the top as a phased delivery plan, not a flat checkbox list at the end. Something like:

```
## Phase 1 — Foundation (staging only, no traffic yet)
Build: Terraform CDN + origin SAN + smoke test routing
Gate: /health returns 200 through CloudFront; direct ALB hit refused
ACs: [CF-1, CF-2, CF-3]

## Phase 2 — Asset versioning (required before enabling immutable)
Build: GlobalFilter ?v= stamp, nginx Cache-Control, Cookie::$secure
Gate: All assets carry ?v= in staging HTML; spot-checked in devtools
ACs: [AV-1, AV-2, AV-3]

## Phase 3 — WAF + upload carve-outs
...
```

This answers the single most expensive question for any implementer: "what do I build first?"

**Move the 'breaks if missed' items to the top, not into prose.** The CDN spec's TL;DR does this partially but incompletely. A dedicated 5-line "If you skip this, you break production" block at the very top of the spec (before architecture diagrams, before tables) is worth more than anything else for keeping an agent on the right path.

**Keep Boundaries and Out-of-Scope sections.** These are the highest-leverage sections in both docs. They prevent an AI agent from doing correct-but-wrong work (e.g., flipping `cdn_enable=1` because it looks related). Never cut them.

**The appendix model for technical detail in feature specs.** For app-level features, write the functional requirements doc first, then add an appendix with data model decisions, API contracts, and integration notes. The body stays testable and readable; the appendix is reference material an agent pulls as needed. The Turo README-plus-specs directory is already close to this — just make the README the primary deliverable and demote the architecture docs to "consult if needed."

---

## Recommendation for future specs

| Spec type     | Primary doc                                                    | Supplementary                    |
| ------------- | -------------------------------------------------------------- | -------------------------------- |
| App feature   | Functional requirements + phased ACs + Boundaries/Out-of-scope | Architecture/data model appendix |
| Infra/systems | Technical spec with TL;DR + phased checklist at the top        | Runbook, rollback procedure      |

The one structural change that would give you the biggest digestibility improvement across both types: **put the phased delivery order at the top, before the architecture**. Right now both specs make the implementer derive sequencing from content. Making it explicit — "Phase 1 is X, its exit gate is Y" — removes the hardest cognitive load and gives an AI agent a natural loop: implement phase, verify gate, move to next phase.
