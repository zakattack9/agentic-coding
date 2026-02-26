---
name: write-spec
description: Write concise, scannable feature specs that contain everything needed to implement a change — and nothing more. Use this skill when the user asks to write or update a spec, PRD, feature specification, requirements doc, or wants to document what a feature should do. Also use it when the user describes a change they want to build and needs it written up or updated in a spec, even if they don't use the word "spec."
---

# Write Spec

## Inputs

Ask the user what the change is and where to save the spec file. Use `AskUserQuestion` to clarify any ambiguous requirements before writing — don't guess at behavior.

## Writing Philosophy

The goal is a spec that a human can scan in under 2 minutes and know exactly what to build. Every piece of the spec should pass a simple test: "Would removing this cause someone to build the wrong thing?" If no, cut it.

### Say things once, in the right place

Repeating information across sections creates maintenance burden and contradictions. If a field has a constraint, put it in the field's definition table — not in a separate "Validation" section. If a checklist covers which systems are affected, don't also include an "Affected Systems" table.

Consolidate related concepts into one section. Validation rules, edge cases, and selection logic about a feature belong inline with the feature's definition — not split into separate "Validation," "Edge Cases," or "Rules" sections.

### Describe behavior, not implementation

Write from the end-user or admin perspective. Describe what should happen, not how to code it. "Discount applies to the rental cost only" tells the developer what the user should see. "Add a discount_percentage column to the pricing_rules table" is an implementation decision that belongs in code, not the spec.

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

If a sentence restates what a field name already implies (e.g., "The minimum days field specifies the minimum number of days"), it's noise. If a section explains why the old thing was bad ("Problem Statement"), the reader doesn't need that context — they need to know what to build. If a list describes things you're NOT building ("Out of Scope"), you're introducing concepts that weren't on the table. If it's not in the spec, it doesn't exist.

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

## Checklist
<!-- Group by system/area (e.g., Dashboard, Frontend, Backend) -->
<!-- Concrete, actionable items with markdown checkboxes -->
```
