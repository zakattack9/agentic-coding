# PRD Template for AI Coding Agents

> **Purpose:** This document defines the optimal structure for Product Requirements Documents (PRDs) that will be handed off to an AI coding agent for implementation. It is derived from analysis of 28 real-world PRDs used to ship features, bug fixes, and refactors across a full-stack rental software suite, combined with best practices for AI-assisted development.

> **See also:** [SPEC_DOC_TEMPLATE.md](./SPEC_DOC_TEMPLATE.md) — the companion template for functional specification documents. PRDs prescribe **what to build**; Spec Docs describe **how the system works**. Read existing spec docs for context before writing a PRD. Update relevant spec docs after implementation is complete.

---

## How to Use This Template

Every section below is annotated with:
- **When to include:** Whether the section is **Required**, **Recommended**, or **Optional** based on task complexity.
- **Why it matters:** How this section helps an AI agent produce correct, scoped output.
- **Guidance:** What to write and what to avoid.

**Complexity tiers:**
| Tier | Description | Example | Sections needed |
|------|-------------|---------|-----------------|
| **S — Patch** | Single-file bug fix or config change | Fix a typo in validation, update a threshold | Title, Summary, Problem Statement, Technical Design, Acceptance Criteria |
| **M — Feature** | Multi-file feature or meaningful refactor touching 2-10 files | New API endpoint with frontend integration | All Required + Recommended sections |
| **L — Epic** | Cross-cutting system change touching 10+ files across repos | New pricing engine, auth overhaul | All sections + companion checklist file |

---

# `{Feature/Fix Name}`

> _{One-line description of the change.}_

| Field | Value |
|-------|-------|
| **Complexity** | S / M / L |
| **Author** | _{name}_ |
| **Date** | _{YYYY-MM-DD}_ |
| **Status** | Draft / In Progress / Complete |
| **Repos affected** | _{e.g., booking-website-backend, zilarent-dashboard}_ |

---

## 1. Summary

> **Required** for all tiers. | AI agents read this first to form a mental model of the full scope before diving into details.

Write 2-4 sentences covering: what is being built/changed, who it's for, and the expected outcome. This is the "elevator pitch" that anchors the agent's understanding of every subsequent section.

```
Example:
Add per-day custom pricing on rental items, allowing businesses to override the
default daily rate for specific dates. This requires a new DB table, two new API
endpoints (GET/PUT), and modifications to the booking cost calculation logic.
Affects backend and dashboard repos.
```

---

## 2. Problem Statement

> **Required** for all tiers. | Gives the agent the "why" — critical for making correct judgment calls when implementation details are ambiguous.

Describe:
- What the current behavior or state is
- Why it's a problem (user pain, technical debt, business impact)
- What triggers this work now

Keep it factual and concise. Link to error logs, screenshots, or support tickets if relevant.

---

## 3. Goals

> **Required** for M/L tiers. **Optional** for S tier. | Helps the agent prioritize when trade-offs arise during implementation.

Bulleted list of 3-6 specific, measurable outcomes. Frame as "Enable X" or "Ensure Y" rather than vague aspirations.

```
Example:
- Enable businesses to set custom prices for any future date on any item
- Ensure booking cost calculation uses custom prices when available, falling back to default_price
- Expose a bulk-upsert API that is idempotent and validates date ranges
```

---

## 4. Non-Goals

> **Required** for M/L tiers. **Recommended** for S tier. | This is the single most important section for AI agents. Without explicit boundaries, agents over-engineer, add unrequested features, or refactor surrounding code.

Bulleted list of things that are explicitly **out of scope**. Be specific — don't just say "performance optimization"; say "Do not add caching to the pricing lookup in this iteration."

```
Example:
- Do not build a calendar UI for setting prices (dashboard work is a separate PRD)
- Do not migrate existing bookings to the new pricing table
- Do not add bulk import from CSV
- Do not refactor the existing calculate_costs function beyond what's needed for custom pricing
```

---

## 5. Background & Context

> **Recommended** for M/L tiers. **Optional** for S tier. | Provides the codebase-specific knowledge the agent needs to work within existing patterns rather than inventing new ones.

Include:
- **Architecture overview** relevant to this feature (not the whole system — just what matters)
- **Key file paths** the agent will need to read or modify
- **Existing patterns to follow** — point to a specific file/function as the reference implementation
- **Database schema context** — relevant tables, RLS policies, multi-tenant considerations
- **Terminology** — define any domain-specific terms the agent might misinterpret

```
Example:
### Key Files
- Cost calculation: `lambdas/apigateway/bookings/services/pricing_service.py`
- Item DAO: `lambdas/apigateway/items/daos/item_dao.py`
- Route base class: `lambdas/apigateway/shared/rentals_route.py` (handles RLS tenant context)

### Existing Pattern to Follow
The `PUT /items/daily-prices` endpoint should follow the same pattern as
`PUT /unavailability` in `lambdas/apigateway/unavailability/routes/manage_unavailability.py`.
```

---

## 6. Technical Design

> **Required** for all tiers. | This is the core implementation specification. The more concrete and unambiguous this section is, the better the agent's output.

Structure this section based on what the feature requires. Use the subsections below as needed:

### 6a. Database Changes

> Include for any feature that modifies the schema.

Provide exact DDL or Flyway migration SQL. Include:
- Table/column definitions with types and constraints
- Indexes
- RLS policy implications
- Seed data if applicable

```sql
-- Example
CREATE TABLE rentals.item_pricing (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID NOT NULL REFERENCES rentals.items(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES rentals.businesses(id),
    date DATE NOT NULL,
    price NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_id, date)
);

CREATE INDEX idx_item_pricing_item_date ON rentals.item_pricing (item_id, date);
```

### 6b. API Contracts

> Include for any feature that adds or modifies endpoints.

For each endpoint, specify:
- Method + path
- Request body/params (with JSON example)
- Response body (with JSON example)
- Error responses and status codes
- Auth/permission requirements

````
### PUT /items/daily-prices

**Request:**
```json
{
  "prices": {
    "<item_id>": [
      { "date": "2025-03-15", "price": 150.00 },
      { "date": "2025-03-16", "price": null }
    ]
  }
}
```

> Note: `null` price = delete the custom price for that date.

**Response (200):**
```json
{
  "updated": 1,
  "deleted": 1
}
```

**Errors:**
| Status | Code | When |
|--------|------|------|
| 400 | `INVALID_DATE` | Date is in the past |
| 400 | `INVALID_PRICE` | Price is negative |
| 404 | `ITEM_NOT_FOUND` | item_id doesn't exist for this business |
````

### 6c. Core Logic Changes

> Include for any feature that modifies business logic.

Describe the logic change in precise terms. Use pseudocode, decision trees, or step-by-step algorithms rather than vague descriptions. Reference the exact function/method being modified.

```
Example:
Modify `calculate_costs()` in `pricing_service.py`:

1. Accept new param: `custom_prices: dict[date, Decimal] | None`
2. For each rental day in the booking range:
   a. If custom_prices contains an entry for that date → use it
   b. Else → use item.default_price (current behavior)
3. Sum all daily prices → subtotal
4. Apply existing tax/fee logic unchanged
```

### 6d. Frontend Changes

> Include when UI modifications are needed.

Describe:
- Which components/pages are affected (with file paths)
- New UI states (loading, error, empty, populated)
- Data flow (which API calls, which hooks/stores)
- User interaction flow (step by step)

Attach wireframes or ASCII mockups if the layout is non-obvious. For simple changes, a text description suffices.

### 6e. Infrastructure / Config Changes

> Include when cloud resources, environment variables, CDK stacks, or CI/CD changes are needed.

Specify exact resource definitions (CDK constructs, IAM policies, S3 lifecycle rules, etc.) with code/JSON examples.

---

## 7. Implementation Plan

> **Required** for M/L tiers. **Recommended** for S tier. | Gives the agent a sequenced execution plan. Without this, agents may attempt changes in the wrong order (e.g., frontend before backend, logic before schema).

Break work into ordered phases. Each phase should be independently deployable or at least independently testable. For each phase, list:
- What gets built
- Which files are created/modified
- Dependencies on prior phases
- How to verify the phase is complete

```
Example:
### Phase 1: Database Schema (no dependencies)
- [ ] Create Flyway migration `V{next}__add_item_pricing_table.sql`
- [ ] Add RLS policy for `item_pricing` table
- **Verify:** Migration runs cleanly; table visible in DB with RLS active

### Phase 2: Backend DAO + Service (depends on Phase 1)
- [ ] Create `ItemPricingDAO` in `lambdas/apigateway/items/daos/item_pricing_dao.py`
  - Follow pattern from `UnavailabilityDAO`
- [ ] Add `get_custom_prices(item_id, start_date, end_date)` method
- [ ] Add `upsert_prices(item_id, prices)` method
- [ ] Modify `calculate_costs()` in `pricing_service.py` to accept and use custom prices
- **Verify:** Unit-testable; pricing returns custom price when set, default otherwise

### Phase 3: API Routes (depends on Phase 2)
- [ ] Add `PUT /items/daily-prices` route
- [ ] Add `GET /items/daily-prices` route
- [ ] Wire routes into API Gateway stack
- **Verify:** cURL/Postman tests against local SAM return expected responses
```

---

## 8. Edge Cases & Error Handling

> **Recommended** for M/L tiers. **Optional** for S tier. | AI agents handle the happy path well by default; explicitly listing edge cases prevents bugs in boundary conditions.

List specific scenarios the implementation must handle correctly. Use the 4-column table format for consistency with spec docs:

| Scenario | Trigger | Expected Behavior | Error/Response |
|----------|---------|-------------------|----------------|
| [Scenario name] | [What causes it] | [What should happen] | [Status code or user-facing message] |

```
Example:
| Mixed pricing | Booking spans custom + default dates | Use custom where available, default_price for the rest | 200 with blended subtotal |
| Zero-dollar day | Custom price set to $0.00 | Allowed; treated as a free day | 200 |
| Concurrent upserts | Two requests update same item's prices | Last write wins (upsert is idempotent) | Both return 200 |
| Retroactive price change | Custom price changed after booking exists | Existing booking cost is NOT retroactively updated | No effect on existing bookings |
```

---

## 9. Acceptance Criteria

> **Required** for all tiers. | These are the "done" conditions. The agent should be able to check each criterion after implementation.

Write as a checklist of verifiable statements. Each criterion should be testable without ambiguity.

```
Example:
- [ ] `PUT /items/daily-prices` upserts prices and returns 200 with counts
- [ ] `GET /items/daily-prices?start_date=X&end_date=Y` returns all custom prices in range
- [ ] `calculate_costs()` uses custom prices when available
- [ ] Booking creation validates `expected_subtotal` against custom-price-aware calculation
- [ ] Existing bookings are not affected by subsequent price changes
- [ ] RLS prevents cross-tenant access to pricing data
```

---

## 10. Risks & Mitigations

> **Recommended** for M/L tiers. | Helps the agent anticipate and handle problems rather than getting stuck.

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Migration fails on large table | Low | High | Test on staging with production-like data volume first |
| Custom prices conflict with discount rules | Medium | Medium | Custom price is the final price — discounts do not stack |

---

## 11. Open Questions

> **Recommended** for all tiers. | Explicitly flags unresolved decisions. An AI agent should surface these rather than making assumptions.

List anything that needs human decision before or during implementation. Strike through and annotate once resolved.

```
Example:
- ~~Should custom prices include or exclude tax?~~ → **Resolved:** Exclude tax; tax is calculated separately
- Should we allow custom prices for past dates? → **Unresolved; default to: reject past dates with 400**
```

---

## 12. Rollout Plan

> **Optional** for S tier. **Recommended** for M/L tiers. | Prevents the agent from shipping incomplete work and documents the deployment sequence.

Numbered steps from development to production:

```
Example:
1. Deploy migration to staging
2. Deploy backend changes to staging
3. QA: verify API contracts with Postman collection
4. Deploy frontend changes to staging (Vercel preview)
5. QA: end-to-end walkthrough on staging
6. Deploy migration to production
7. Deploy backend to production
8. Deploy frontend to production
9. Monitor CloudWatch for errors (24h)
```

---

## 13. Companion Checklist _(for L-tier PRDs)_

> **Required** for L tier. | For large features, a separate `{feature-name}.checklist.md` file prevents the main PRD from becoming unwieldy and gives the agent a clear task-by-task execution list.

The checklist should:
- Mirror the Implementation Plan phases
- Break each phase into atomic, checkbox-trackable tasks
- Include file paths for each task
- Group by repo when multiple repos are affected
- Be updated in real-time as work progresses

```
Example (separate file):
# Custom Pricing — Implementation Checklist

## Backend
### Phase 1: Database
- [x] Create migration V045__add_item_pricing_table.sql
- [x] Verify RLS policy

### Phase 2: DAO & Service
- [x] Create ItemPricingDAO
- [ ] Modify calculate_costs()
- [ ] Add expected_subtotal validation to booking creation
...
```

---

## Appendix: Writing Principles for AI-Consumable PRDs

These principles are distilled from patterns observed across 28 real PRDs and their implementation outcomes:

### 1. Be Concrete, Not Abstract
- **Do:** "Add column `applies_to_pickups BOOLEAN NOT NULL DEFAULT TRUE` to `business_closures`"
- **Don't:** "Update the closures table to support selective operations"

### 2. Show, Don't Tell
- Include JSON request/response examples for every API endpoint
- Include DDL for every schema change
- Include pseudocode or step-by-step algorithms for logic changes
- Use tables over paragraphs for structured data

### 3. Reference Existing Code
- Always point to a file/function that serves as the pattern to follow
- AI agents produce more consistent code when they can mimic an existing pattern
- Use relative paths from repo root: `lambdas/apigateway/bookings/routes/create_booking.py`

### 4. Scope Aggressively via Non-Goals
- The Non-Goals section prevents more bugs than the Goals section
- If in doubt about whether something is in scope, list it as a non-goal
- AI agents are eager to "improve" surrounding code — non-goals rein this in

### 5. Order the Work Explicitly
- Never assume the agent will figure out the right order
- Number phases and mark dependencies between them
- Each phase should have a verification step

### 6. Make Acceptance Criteria Binary
- Every criterion should be answerable with yes/no
- Avoid subjective criteria like "performs well" — use thresholds: "responds in < 500ms at p95"
- Frame as checkboxes that the agent marks off

### 7. Resolve Ambiguity Before Handoff
- Every open question in the PRD is a potential wrong assumption by the agent
- Resolve as many questions as possible before implementation begins
- For truly unresolved items, provide a sensible default and mark it clearly

### 8. Separate Specification from Tracking
- For L-tier PRDs, keep the specification (PRD) and the execution tracking (checklist) in separate files
- The PRD is the "what and why"; the checklist is the "status of each task"
- This prevents the PRD from becoming cluttered with status markers

### 9. Include Rollback Considerations
- For M/L-tier PRDs, mention what happens if things go wrong
- "Migration is additive (new table) — rollback is a no-op"
- "Feature flag X can disable the new behavior without a deploy"

### 10. Keep It Dense
- AI agents process dense, structured content better than verbose prose
- Prefer bullet points over paragraphs
- Prefer tables over bullet points when comparing items
- Prefer code blocks over text descriptions of code
