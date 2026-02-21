# PRD: [Project Name]

<!--
  THIS FILE IS FOR CLAUDE — Write for Claude AI's comprehension, not human readability.
  Claude reads this at the start of EVERY ralph iteration in a fresh context window.

  TOKEN BUDGET: Target 2,000-3,000 words maximum (~2,500-4,000 tokens).
  Every word here costs context budget across every iteration. Each extra 1,000 words
  steals ~1,300 tokens from Claude's "smart zone" (30-60% context utilization) where
  reasoning quality is highest.

  ROLE: Base context document. Provides the stable what/why/who/constraints/design
  that orients each fresh session. Per-story details belong in tasks.json, not here.

  FORMATTING RULES:
  - Bullet points and tables over prose — Claude parses structured formats more efficiently
  - Concrete references (file paths, function names, exact values) over abstract descriptions
  - Imperative constraints ("Use X", "Do NOT do Y") over suggestions ("We prefer X")
  - Frontload key information in each section — most important details first
  - Delete any section that doesn't apply — empty sections waste tokens
  - Do NOT duplicate per-story details from tasks.json
-->

## 1. Summary
<!-- 2-4 sentences: what is being built, who it's for, expected outcome -->
<!-- Write as a briefing that orients Claude immediately in a fresh context window -->



## 2. Problem Statement
<!-- Current state, why it's a problem, what triggers this work -->
<!-- Keep factual and concise — Claude needs the "why" to make good implementation decisions -->



## 3. Goals
<!-- 3-6 specific, measurable outcomes -->
<!-- Write as assertions Claude can verify: "Users can filter by status" not "Improve UX" -->

-

## 4. Non-Goals
<!-- Explicit scope boundaries — what Claude must NOT do -->
<!-- CRITICAL: This is the primary guardrail against Claude over-engineering or scope-creeping -->
<!-- Be specific and imperative: "Do NOT add pagination" not "Keep it simple" -->
<!-- Every non-goal saves iterations by preventing wasted work -->

-

## 5. Background & Context
<!-- Key file paths, architecture patterns, naming conventions, existing code to reference -->
<!-- This section prevents Claude from "rediscovering" the codebase each iteration -->
<!-- Use directory listings and file path references — Claude acts on these directly -->
<!-- Example format:
  - Routes: src/routes/*.ts (follow pattern in src/routes/products.ts)
  - Components: src/components/ (use existing Button, Modal from src/components/ui/)
  - Database: Supabase PostgreSQL, migrations in supabase/migrations/
-->



## 6. Technical Design
<!-- Include ONLY relevant subsections — DELETE the rest to save tokens -->
<!-- Write in formats Claude can act on: schemas, signatures, pseudocode -->

### 6a. Database Changes
<!-- Exact DDL, column types, indexes, RLS policies -->

### 6b. API Contracts
<!-- Method, path, request/response JSON shapes, error codes -->

### 6c. Core Logic Changes
<!-- Pseudocode or step-by-step algorithms — not narrative descriptions -->

### 6d. Frontend Changes
<!-- Component tree, data flow, state management approach -->

### 6e. Infrastructure / Config Changes
<!-- Exact env var names, CI/CD changes, deployment steps -->

## 7. Constraints
<!-- Cross-cutting rules Claude must follow in ALL stories across EVERY iteration -->
<!-- Write as imperative instructions — these function like rules/directives for Claude -->
<!-- Examples:
  - Use date-fns for all date formatting — do NOT use moment.js
  - All monetary values: NUMERIC(10,2), never floats
  - All new endpoints must be idempotent
  - Follow existing error handling pattern in src/lib/errors.ts
-->

-

## 8. Edge Cases & Error Handling
<!-- Global error handling strategy — story-specific edge cases belong in tasks.json acceptance criteria -->

| Scenario | Expected Behavior |
|----------|-------------------|
|          |                   |

## 9. Open Questions
<!-- Strikethrough + annotate when resolved: ~~Question~~ — Resolved: [answer] -->

-
