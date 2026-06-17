---
name: write-spec
description: Write concise, scannable feature specs that contain everything needed to implement a change — and nothing more. Use this skill when the user asks to write or update a spec, PRD, feature specification, requirements doc, or wants to document what a feature should do. Also use it when the user describes a change they want to build and needs it written up or updated in a spec, even if they don't use the word "spec."
argument-hint: [what to build] [@path/to/spec.md to create or update]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Edit, Write
---

# Write Spec

## Inputs

Ask the user what the change is and where to save the spec file. Use `AskUserQuestion` to clarify any ambiguous requirements before writing — don't guess at behavior. It is better to ask one too many questions than to produce an incomplete or inaccurate spec.

**Don't assert ungrounded facts.** When the spec states a concrete detail — a file path, table or column name, route, or config key — confirm it cheaply against the codebase before writing it. If you can't confirm it cheaply, write it as an explicit open question or ask via `AskUserQuestion` rather than asserting a "currently X" claim that might be wrong. Keep this light: a quick check or a question, not a full verification pass — fact-checking the finished spec is `refine-spec`'s job.

## Writing Philosophy

The goal is a spec that a human can scan in under 2 minutes and know exactly what to build. Every piece of the spec should pass a simple test: "Would removing this cause someone to build the wrong thing?" If no, cut it.

### Say things once, in the right place

Repeating information across sections creates maintenance burden and contradictions. If a field has a constraint, put it in the field's definition table — not in a separate "Validation" section. If a checklist covers which systems are affected, don't also include an "Affected Systems" table.

Consolidate related concepts into one section. Validation rules, edge cases, and selection logic about a feature belong inline with the feature's definition — not split into separate "Validation," "Edge Cases," or "Rules" sections.

### Describe behavior, not implementation

Write from the end-user or admin perspective. Describe what should happen, not how to code it. "Discount applies to the rental cost only" tells the developer what the user should see. "Add a discount_percentage column to the pricing_rules table" is an implementation decision that belongs in code, not the spec.

### Enumerate the acceptance criteria

Lead with a flat, numbered list of **acceptance criteria** — every behavior and constraint that must hold once the change is done, each a single testable assertion with a stable id (`AC-1`, `AC-2`, …). This list is the spec's contract: it's the reader's two-minute scan of *what must be true*, and it's what the implementation is later gated against criterion-by-criterion. Two rules make it work:

- **Enumerate exhaustively — never condense.** Unlike prose, which you cut to the bone, the criteria are the one place you list *everything*. A requirement that lives only in a paragraph below is a requirement that gets missed at completion. Brevity is for wording, not for coverage.
- **Each criterion is one atomic, observable end-state** — "Unrouted mail is quarantined, never dropped", not "build the quarantine system". Phrase what is *true* when done (so it's checkable), not a task to do. Keep the criteria behavior-level; the detailed rule that implements each one lives in the body and carries its `AC-id`, so each fact is stated once, at its altitude.
- **Group only to aid the reader — never invent an order you can't ground.** Flat is the default. If the criteria fall into ≥2 obvious capability clusters, you *may* loosely group them under named `###` headers (`### 1. <capability>`) as a "what am I building" map. But do **not** assert a build order or a cross-group `needs §X` dependency in the first draft — a real dependency is a grounded fact, and committing it is `refine-spec`'s job. AC-ids stay globally unique and stable across groups; a one-group spec is just the flat list.

### Show, don't tell

A visual communicates faster than prose. Prefer these formats over text-based descriptions:

- **Tables** for field definitions (with constraints inline) and input/output examples
- **Screenshots or mockups** for UI changes — an annotated screenshot showing "remove this", "rename to X" beats a bulleted list of text instructions. Include clear placeholders describing exactly what the screenshot should capture.
- **Mermaid diagrams** for flows, sequences, or processes. If you're writing an ordered list of steps or a conditional flow, a mermaid diagram is almost always more scannable. Use `flowchart`, `sequenceDiagram`, or `stateDiagram` as appropriate — they render natively in markdown.
- **Examples** with setup + result: use a bulleted list for the setup data and a labeled table for the result — never inline comma-separated items when each item will be referenced later
- **ASCII mockups** for showing how data should display (e.g., pricing breakdowns, line items)

### Bold key terms for scanability

Use **bold** on terms the reader needs to remember or cross-reference — behavioral rules, field names in prose, and critical constraints. A reader scanning the spec should be able to pick out the important terms without reading full sentences.

### Every sentence earns its place

If a sentence restates what a field name already implies (e.g., "The minimum days field specifies the minimum number of days"), it's noise. If a section explains why the old thing was bad ("Problem Statement"), the reader doesn't need that context — they need to know what to build. Cut speculative "Out of Scope" lists of things you considered but won't build — they introduce concepts that weren't on the table. The one exception: when the user gave an explicit carve-out that prevents a likely scope error (e.g. "don't touch prod", "ignore multi-tenancy"), capture it as a single bounded line — not a narrative (if it constrains what the implementer may *touch*, put it in the **Boundaries** section instead). If it's not in the spec, it doesn't exist.

### Self-contained for a zero-context reader

A spec is often read in isolation by someone with no prior context — a teammate or downstream dev who receives just this file. It must stand alone: don't reference other specs, docs, or prior conversation the reader may not have; inline the few facts they'd otherwise have to chase down. Write as if the reader has zero context on the work.

### Keep the TL;DR tight

2-3 bullets max. If the spec body is already concise, a long TL;DR just repeats it. The TL;DR should answer: what is the change in one sentence, and what's the one behavioral detail someone might get wrong without a heads-up.

## Spec Structure

Use only sections that are relevant. Not every spec needs every section.

```markdown
# {Feature Name} Spec

## TL;DR
- {What the change is in one line}
- {The most important behavioral detail someone might get wrong}

---

## Acceptance Criteria
<!-- The enumerated contract: every behavior/constraint that must hold when done, as a discrete, testable assertion with a stable id. The reader's 2-minute scan AND what launch-spec's done-gate and verify-spec check 1:1. Enumerate exhaustively — never condense. Each AC is ONE atomic, observable end-state ("X is true"), not a task. Detailed rules in the body cite their AC-id so each fact is said once. -->
<!-- Default to a FLAT list. OPTIONALLY cluster into named groups (### 1. <capability>) when the ACs fall into ≥2 obvious capabilities — a "what am I building" map. AC-ids stay globally unique and stable across groups. Do NOT assert a build order or cross-group `needs §X` here; refine-spec commits that after grounding against the codebase. -->

- **AC-1** — {single testable assertion about the end state}
- **AC-2** — {…}

---

## {Feature Name}
<!-- Name this after the feature, not a generic label like "Solution" -->
<!-- One table for field/input definitions with constraints inline -->
<!-- A few bullets ONLY for behavior that isn't obvious from definitions -->
<!-- Examples/tables showing how it works in practice -->
<!-- Use mermaid diagrams for flows or multi-step processes instead of ordered lists -->

---

## UI Changes
<!-- Only if there are UI changes -->
<!-- Group by page/area -->
<!-- Each page section MUST include the URL as a clickable markdown link: [url](url) -->
<!-- Prefer screenshots/mockups over text instructions for form and layout changes -->
<!-- Use the placeholder format below for each visual that needs to be added -->
<!-- Use ASCII mockups for data display formats (pricing, line items, etc.) -->

### {Page Name}
**URL:** [{https://example.com/path/to/page}]({https://example.com/path/to/page})

> **[Screenshot needed]:** {Describe exactly what the screenshot should show, e.g., "Current pricing rule form with annotations: (1) arrow on Rule Type dropdown → rename to 'Long-Term Discount', (2) strikethrough on 'Price per Day' field → replace with 'Discount (%)' input, (3) strikethrough on 'Maximum Days' field → remove entirely"}


---

## Data Migration
<!-- Only if existing data/logic is affected -->
<!-- 1-2 lines -->

---

## Boundaries
<!-- What the implementer must NOT touch — the key to preventing drift in a long implementation (/goal) run -->
<!-- List files/dirs/systems/patterns to leave alone, and decisions already made that must not be revisited -->
<!-- Keep these change-specific. A boundary that is really a standing project convention (architecture, "don't touch prod") belongs in CLAUDE.md, not here — it's re-injected every turn regardless of which driver implements the spec -->
<!-- Include only real boundaries; omit the section if the change is fully self-contained -->

---

## Checklist
<!-- Group by system/area (e.g., Dashboard, Frontend, Backend) -->
<!-- Concrete, actionable items with markdown checkboxes -->
<!-- The Checklist is the *task* view (what to DO); the Acceptance Criteria above are the *assertion* view (what must be TRUE). Cite the AC-id(s) each item satisfies so every criterion is traceably covered. -->
```
