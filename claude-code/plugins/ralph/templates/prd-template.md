# PRD: [Project Name]

## 1. Summary
<!-- Required for all tiers (S-Patch, M-Feature, L-Epic) -->
<!-- 2-4 sentences: what is being built, who it's for, expected outcome -->



## 2. Problem Statement
<!-- Required for all tiers -->
<!-- Current state, why it's a problem, what triggers this work -->



## 3. Goals
<!-- Required for M/L tiers, Optional for S -->
<!-- 3-6 specific, measurable outcomes -->

-

## 4. Non-Goals
<!-- Required for M/L tiers, Recommended for S -->
<!-- Explicit scope boundaries — what we are NOT doing -->
<!-- This is the most important section for AI agents: prevents over-engineering and unrequested changes -->

-

## 5. Background & Context
<!-- Recommended for M/L tiers -->
<!-- Architecture overview, key file paths, existing patterns to follow, database schema context, terminology -->



## 6. Technical Design
<!-- Required for all tiers — include only relevant subsections -->

### 6a. Database Changes
<!-- DDL, indexes, RLS policies -->



### 6b. API Contracts
<!-- Method, path, request/response JSON, error codes -->



### 6c. Core Logic Changes
<!-- Pseudocode, step-by-step algorithms -->



### 6d. Frontend Changes
<!-- Components, data flow, interaction flow -->



### 6e. Infrastructure / Config Changes
<!-- Environment variables, CI/CD, deployment changes -->



## 7. Constraints
<!-- Recommended for M/L tiers -->
<!-- Cross-cutting invariants that apply to ALL stories across every iteration -->
<!-- Examples: "All monetary values stored as NUMERIC(10,2), never floats" -->
<!-- Examples: "Use spatie/laravel-enum, not native PHP enums" -->
<!-- Examples: "All new endpoints must be idempotent" -->

-

## 8. Edge Cases & Error Handling
<!-- Recommended for M/L tiers -->

| Scenario | Trigger | Expected Behavior | Error Code/Message |
|----------|---------|-------------------|-------------------|
|          |         |                   |                   |

## 9. Risks & Mitigations
<!-- Recommended for M/L tiers -->

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
|      |           |        |            |

## 10. Open Questions
<!-- Recommended for all tiers -->
<!-- Strikethrough + annotate when resolved: ~~Question~~ — Resolved: [answer] -->

-
