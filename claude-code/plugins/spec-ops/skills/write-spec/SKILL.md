---
name: write-spec
description: The entrypoint to the spec workflow — turn an idea, even a rough one-liner, into a concise, scannable feature spec that contains everything needed to implement the change and nothing more. At full rigor it first runs a short discovery pass (eliciting and distilling requirements via questions) before drafting; refine-spec hardens the draft afterward. Use this skill when the user asks to write or update a spec, PRD, feature specification, or requirements doc, when they want to document what a feature should do, or when they describe a change they want to build — even a half-formed idea, and even if they don't use the word "spec."
argument-hint: [what to build / a rough idea] [@path/to/spec.md — optional; can be named after drafting] [rigor: light|standard|full]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# Write Spec

## Rigor — how deep to go

`write-spec` always produces the **WHAT** (the behavior/contract), but at one of three depths. Read the requested rigor from the arguments (`rigor: light|standard|full`). If none is given, infer it from the ask — a self-evidently trivial change is `light`, a routine bounded feature is `standard`, a complex change or any infra / platform / config / migration spec is `full` — and **when unsure, default to `full`** (more rigor is the safe error). A caller delegating to this skill in batch (e.g. a board-intake workflow) passes the rigor explicitly; honor it.

| Rigor | Use for | Emit | Clarifying questions |
|---|---|---|---|
| **`light`** | a trivial, self-contained task | The `## Acceptance Criteria` table **only** (plus a one-line goal if it isn't obvious from the title). No TL;DR, Boundaries, body sections, or Checklist. A few lines total. | **Markers only.** Draft from what's given; flag a genuine unknown with one `[NEEDS CLARIFICATION: …]` and move on. Do **not** open an `AskUserQuestion` loop. |
| **`standard`** | a routine, bounded feature | TL;DR (lead with any "breaks if missed") + the AC table (grouped only if ≥2 obvious clusters) + **Boundaries** + a *lean* body **only** for behavioral rules the AC don't already make obvious. | **Markers only**, as above. |
| **`full`** | a complex change, or any infra / config-as-contract spec | The complete structure below — exhaustive AC, self-contained body, every relevant section. | **Interactive.** Run **[Discovery](#discovery--turn-a-bare-idea-into-requirements)** to elicit requirements from the idea, using `AskUserQuestion` before guessing — better to ask one too many. Then draft, and hand the result to **`refine-spec`** to ground and harden. |

**Constant across all three:** the **Acceptance Criteria are enumerated exhaustively, never condensed** — "cut to the bone" is for *prose*, never for coverage. A `light` spec is *all* criteria and almost no prose; it still lists every one. And **`light`/`standard` are strictly code-free WHAT** — they describe behavior and the *observable interface* (a route, a user-visible field, an API response shape) but name **no internal implementation** (file paths, function/class names, table/column names, config keys, framework specifics); the implementer chooses the HOW, and grounding enters later in `refine-spec`. Only **`full`** may pin implementation — it's where code-grounding lives, and for an infra/config-as-contract spec the config *is* the contract. **So a config-as-contract change — CDN, WAF, deploy-pipeline, networking, migration — does not fit `light`/`standard`: a code-free spec can't carry a contract that *is* configuration.** If you're asked for one at `light`/`standard`, draft the code-free WHAT but **flag the mismatch and recommend `full`** (for a board-intake caller, that's its T3 tier).

## Inputs

Start from whatever the user has — a rough idea, loose requirements, or a fully-formed change. You do **not** need a destination file to begin: at **`full`** rigor, run **[Discovery](#discovery--turn-a-bare-idea-into-requirements)** first and **name the spec file at the end**, once there's a draft worth saving (ask where to save it then, or propose a path the user confirms). Only take a save path up front when the user already gave one, or is updating an existing spec.

How you then handle ambiguity depends on the **rigor** (see [Rigor](#rigor--how-deep-to-go)): at **`full`**, elicit and clarify with `AskUserQuestion` before writing — don't guess at behavior; it is better to ask one too many questions than to produce an inaccurate spec. At **`light`/`standard`** (and whenever a caller is delegating in batch), do **not** open a question loop — draft from what's given and leave a `[NEEDS CLARIFICATION: …]` marker on any genuine unknown for later resolution.

**Don't assert ungrounded facts.** At **`full`**, when the spec names a concrete internal detail — a file path, table or column name, or config key — confirm it cheaply against the codebase first; if you can't, write it as an explicit open question or ask via `AskUserQuestion` rather than asserting a "currently X" claim that might be wrong (keep it light — a quick check, not a full verification pass; fact-checking the finished spec is `refine-spec`'s job). At **`light`/`standard`** there is nothing to confirm because you name **no internal implementation at all** — stay at the observable level (a *route* or user-visible field is fine; a *file / column / config key* is not), so the spec can't assert a wrong codebase fact and stays implementation-agnostic.

**If a detail truly can't be resolved** — not by a cheap check and not by asking — leave a single inline `[NEEDS CLARIFICATION: <what's unknown>]` marker rather than guessing. Prefer `AskUserQuestion` first **at `full`** rigor; at `light`/`standard` the marker *is* the primary tool (no question loop). `refine-spec` blocks on any that remain, so a marker can't survive into a finished `full` spec.

## Discovery — turn a bare idea into requirements

`write-spec` is the **entrypoint to the spec workflow**: it should be able to start from *nothing but an idea* and end with a structured draft. When the input is a fuzzy idea rather than settled requirements **and rigor is `full`**, run a short **discovery pass before drafting** — don't jump to the AC table off an under-specified ask.

Discovery is **convergent**: diverge just enough to surface what matters, then converge on the requirements. It is a *product / requirements* conversation, not a technical one — you are deciding **what should be true**, never checking what the code currently does (that grounding is `refine-spec`'s job; do not do it here). Draw out, via `AskUserQuestion` (batch related questions; take as many rounds as it needs):

- **The core goal** — the one outcome this must achieve, in the user's words.
- **The must-have behaviors** — what a user / admin should be able to do, and what must always or never happen.
- **The decisions only the user can make** — the genuine product forks (e.g. "notifications batch hourly vs. send immediately", "soft-delete vs. hard-delete"). Offer concrete options; don't silently pick for them.
- **Scope boundaries** — what is explicitly *out*, and anything the implementer must not touch.
- **The non-obvious edge cases** — the empty / limit / conflict / permission cases the happy path skips.

Discovery may legitimately conclude that the idea **isn't ready to spec** (it's blocked on a decision only the user can make) or is **actually several specs** — surface that rather than forcing a draft. Otherwise, distill the answers into the AC-first draft below.

The line that keeps this from overlapping `refine-spec`: write-spec asks **requirements** questions sourced from the *idea* ("should it batch or send immediately?"); `refine-spec` asks **grounding** questions sourced from the *codebase* ("there's no `users.email` column — did you mean `contact_email`?"). Different questions, different stage. At `light` / `standard` rigor (and any batch / delegated call) there is **no discovery loop** — draft from what's given and leave `[NEEDS CLARIFICATION]` markers.

## Writing Philosophy

The goal is a spec that a human can scan in under 2 minutes and know exactly what to build. Every piece of the spec should pass a simple test: "Would removing this cause someone to build the wrong thing?" If no, cut it.

### Say things once, in the right place

Repeating information across sections creates maintenance burden and contradictions. If a field has a constraint, put it in the field's definition table — not in a separate "Validation" section. If a checklist covers which systems are affected, don't also include an "Affected Systems" table. Once a spec has an **Acceptance Criteria** table, the most common offender is a **Checklist that re-describes those criteria** — keep the Checklist a thin *code-area → `AC-id`* index that points at the criteria, never a second statement of them.

Consolidate related concepts into one section. Validation rules, edge cases, and selection logic about a feature belong inline with the feature's definition — not split into separate "Validation," "Edge Cases," or "Rules" sections.

### Describe behavior, not implementation

Write from the end-user or admin perspective. Describe what should happen, not how to code it. "Discount applies to the rental cost only" tells the developer what the user should see. "Add a discount_percentage column to the pricing_rules table" is an implementation decision that belongs in code, not the spec.

**The line is internal implementation vs. observable interface.** Naming the *observable* surface — a route like `/checkout`, a user-visible field, an API response shape — is behavior and is always fine. Naming *internal* implementation — a file path, function/class, table/column, config key, or framework specific — is HOW. At **`light`/`standard`** that HOW is off-limits entirely (the spec stays implementation-agnostic); only at **`full`** does it earn a place, and only where it's load-bearing or *is* the contract (the infra/config exception below).

**Infra / platform / config / migration specs are the exception** — there the *configuration is the observable contract*. For a CDN, WAF, deploy-pipeline, or networking change, the resource names, settings, file paths, and policies are exactly what must be true, so specifying them is not over-reach — a "behavior-only" version would be unimplementable. The rule still holds in spirit: pin the **end-state config**, don't narrate the coding steps or the history of how the system got here. Expect these specs to be denser than a feature spec; that density is inherent, not bloat.

### Enumerate the acceptance criteria

Lead with a **markdown table** of **acceptance criteria** — every behavior and constraint that must hold once the change is done, each row a single testable assertion (`| AC | Criterion |`). The `AC` column holds the bare stable number (`1`, `2`, …; the header already says "AC", so don't repeat the prefix); everywhere else — the body, the Checklist, the gates — cite it as `AC-1`, `AC-2`, …. This table is the spec's contract: it's the reader's two-minute scan of *what must be true*, and it's what the implementation is later gated against criterion-by-criterion. Two rules make it work:

- **Enumerate exhaustively — never condense.** Unlike prose, which you cut to the bone, the criteria are the one place you list *everything*. A requirement that lives only in a paragraph below is a requirement that gets missed at completion. Brevity is for wording, not for coverage. A separate **Validation** or "how we'll test it" list is acceptance criteria wearing another hat — put those assertions here, not in a parallel section.
- **Each criterion is one atomic, observable end-state** — "Unrouted mail is quarantined, never dropped", not "build the quarantine system". Phrase what is *true* when done (so it's checkable), not a task to do. Keep the criteria behavior-level; the detailed rule that implements each one lives in the body and carries its `AC-id`, so each fact is stated once, at its altitude.
- **Group only to aid the reader — never invent an order you can't ground.** A single table is the default. If the criteria fall into ≥2 obvious capability clusters, you *may* loosely group them under named `###` headers (`### 1. <capability>`), **one table per group**, as a "what am I building" map. But do **not** assert a build order or a cross-group `needs §X` dependency in the first draft — a real dependency is a grounded fact, and committing it is `refine-spec`'s job. AC-ids stay globally unique and stable across groups; a one-group spec is just the single table.
- **Don't silently drop non-functional constraints.** Performance, security, idempotency, limits, concurrency — if the change implies one, make it its own `AC` (these are the requirements most often lost). `refine-spec` hunts for any you miss, but capture the obvious ones up front.
- **Encode a "thin end-to-end first" as a criterion, not a build step.** Where a walking skeleton matters, write it as a behavioral AC — `AC-1` — *an end-to-end path from {X} to an observable {Y} runs* — rather than an instruction to "build the skeleton first." It stays checkable like any other criterion and naturally becomes the first group's "start here" AC.

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

2-3 bullets max, **each one short line — not a paragraph**. If the spec body is already concise, a long TL;DR just repeats it. The TL;DR should answer: what is the change in one sentence, and what's the one behavioral detail someone might get wrong without a heads-up. If the change has a **"breaks if missed"** risk, lead with it as a terse list that **points at the relevant `AC-id`s** rather than re-explaining them — the detail lives in the AC table and the body.

## Spec Structure

The skeleton below is the **`full`**-rigor shape; `light` is the Acceptance Criteria table alone and `standard` is TL;DR + AC + Boundaries (see [Rigor](#rigor--how-deep-to-go)). Use only sections that are relevant. Not every spec needs every section. The full skeleton is shaped for a typical feature change: **infra / platform / migration specs** usually drop **UI Changes** and **Data Migration** and add two — a **Current state → Target** view (what exists today vs. the end state, load-bearing when you're changing a running system) and a short **Architecture** diagram (mermaid). Add them only when they earn their place.

```markdown
# {Feature Name} Spec

## TL;DR
- {What the change is in one line}
- {The most important behavioral detail someone might get wrong}

---

## Acceptance Criteria
<!-- The enumerated contract: every behavior/constraint that must hold when done, as a discrete, testable assertion with a stable id. The reader's 2-minute scan AND what launch-spec's done-gate and verify-spec check 1:1. Enumerate exhaustively — never condense. Each AC is ONE atomic, observable end-state ("X is true"), not a task. Detailed rules in the body cite their AC-id so each fact is said once. -->
<!-- Default to a single FLAT table. OPTIONALLY split into named groups (### N. <capability>), one table per group, when the ACs fall into ≥2 obvious capabilities — a "what am I building" map. AC-ids stay globally unique and stable across groups. Do NOT assert a build order or cross-group `needs §X` here; refine-spec commits that after grounding against the codebase. -->

| AC | Criterion |
|----|-----------|
| 1 | {single testable assertion about the end state} |
| 2 | {…} |

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
<!-- OPTIONAL, and a thin TRACEABILITY INDEX — never a third copy of the spec. The AC table is the *assertion* view (what must be TRUE); the body is the *detail* view (how/where + the load-bearing why); the Checklist is the *task* view, organized by the one axis neither of those gives: CODE AREA. -->
<!-- Include it only when the work spans several code areas/systems and a "by where in the code" map helps the implementer. If every item would just restate one AC, the Checklist adds nothing over the AC table — omit it. -->
<!-- Each item is ONE line: name the area's work in a few words and cite the AC-id(s) that land there. Cite the ids; do NOT re-describe what the criteria assert — that text already lives in the AC table and the body. -->
<!-- Never let a checklist item be the SOLE home of a fact. Exact config values, file paths, and policy/resource names are part of the contract and belong in the body (or an AC); a checklist item points at them, it never introduces them. -->

**{Code area — e.g. Terraform · modules/cdn}**
- [ ] {the area's work in a few words} — AC-1, AC-3, AC-8
- [ ] {…} — AC-5
```

## Commit the draft

Once the spec is written **to a file**, commit it — scoped to that one file — so the draft is captured in git:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_git.py" commit <abs-spec-path> "docs(spec): draft {spec name}"
```

The helper stages and commits **only the spec file** — never `git add -A`, never other staged changes, never a push — and no-ops cleanly if the path isn't in a git repo or hasn't changed. Use a conventional message naming the spec.

**Skip the commit when there is no spec file** — when a caller delegates in batch (e.g. authoring an issue *body* inline, or `light` rigor with no destination file), you produced text, not a file the user owns; commit nothing. Only ever commit the spec file itself, and never run any other git mutation.
