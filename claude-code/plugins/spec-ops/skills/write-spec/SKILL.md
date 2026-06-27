---
name: write-spec
description: The entrypoint to the spec workflow — turn an idea, even a rough one-liner, into a concise, scannable feature spec that contains everything needed to implement the change and nothing more. It first runs a discovery pass (eliciting and distilling requirements via questions, scaled to the change) before drafting — at every rigor, unless a batch / non-interactive caller passes `--disable-questions`; refine-spec hardens the draft afterward. Use this skill when the user asks to write or update a spec, PRD, feature specification, or requirements doc, when they want to document what a feature should do, or when they describe a change they want to build — even a half-formed idea, and even if they don't use the word "spec."
argument-hint: [what to build] [@path/to/spec.md] [rigor: light|standard|full] [--disable-questions]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# Write Spec

## Rigor — how deep to go

`write-spec` always produces the **WHAT** (the behavior/contract), but at one of three depths. Read the requested rigor from the arguments (`rigor: light|standard|full`). If none is given, infer it from the ask — a self-evidently trivial change is `light`, a routine bounded feature is `standard`, a complex change or any infra / platform / config / migration spec is `full` — and **when unsure, default to `full`** (more rigor is the safe error). A caller delegating to this skill in batch (e.g. a board-intake workflow) passes the rigor explicitly; honor it — and such batch / non-interactive callers also pass **`--disable-questions`** to suppress the interactive elicitation loop (see [Discovery](#discovery--turn-a-bare-idea-into-requirements)).

| Rigor          | Use for                                                  | Emit                                                                                                                                                                                            | Clarifying questions                                                                                                                                                                                                                                                        |
| -------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`light`**    | a trivial, self-contained task                           | The `## Acceptance Criteria` table **only** (plus a one-line goal if it isn't obvious from the title). No TL;DR, Boundaries, body sections, or Checklist. A few lines total.                    | **Interactive, scaled to the task.** Run a brief [Discovery](#discovery--turn-a-bare-idea-into-requirements) pass — ask via `AskUserQuestion` about any genuine unknown, edge case, or scenario the one-liner hides; a truly trivial task may surface none, so stop fast. **With `--disable-questions`:** no loop — flag each unknown with one `[NEEDS CLARIFICATION: …]`.                                                                                                               |
| **`standard`** | a routine, bounded feature                               | TL;DR (lead with any "breaks if missed") + the AC table (grouped only if ≥2 obvious clusters) + **Boundaries** + a *lean* body **only** for behavioral rules the AC don't already make obvious. | **Interactive.** [Discovery](#discovery--turn-a-bare-idea-into-requirements) on the genuine forks, unknowns, and edge cases. **With `--disable-questions`:** markers only, as above.                                                                                                                                                                                                                                                 |
| **`full`**     | a complex change, or any infra / config-as-contract spec | **A `## TL;DR` section** (lead with any "breaks if missed") + the complete structure below — exhaustive AC, self-contained body, every relevant section.                                                                                                      | **Interactive — fullest.** Run the complete **[Discovery](#discovery--turn-a-bare-idea-into-requirements)** design-tree walk, using `AskUserQuestion` before guessing — better to ask one too many. Then draft, and hand the result to **`refine-spec`** to ground and harden. **With `--disable-questions`:** markers only. |

**Constant across all three rigors** — these hold whatever the depth:

- **Enumerate the Acceptance Criteria exhaustively — never condense.** "Cut to the bone" is for *prose*, never for coverage: a `light` spec is *all* criteria and almost no prose, yet still lists every one.
- **`light`/`standard` are strictly code-free WHAT.** Describe behavior and the *observable interface* — a route, a user-visible field, an API response shape — but name **no internal implementation** (file paths, function/class names, table/column names, config keys, framework specifics). The implementer chooses the HOW; grounding enters later in `refine-spec`. Only **`full`** may pin implementation — it's where code-grounding lives, and for an infra/config-as-contract spec the config *is* the contract.
- **A config-as-contract change doesn't fit `light`/`standard`.** A CDN, WAF, deploy-pipeline, networking, or migration change can't be carried by a code-free spec — the configuration *is* the contract. Asked for one at `light`/`standard`, draft the code-free WHAT but **flag the mismatch and recommend `full`** (for a board-intake caller, that's its T3 tier).
- **Discovery runs by default at every rigor.** The AC must capture every unknown, edge case, and scenario regardless of tier — so rigor sets the *depth* of questioning and the *prose* emitted, **never whether you elicit**. Only `--disable-questions` turns the interactive loop off (falling back to `[NEEDS CLARIFICATION]` markers). See [Discovery](#discovery--turn-a-bare-idea-into-requirements).

## Inputs

Start from whatever the user has — a rough idea, loose requirements, or a fully-formed change. You do **not** need a destination file to begin: when you start from an idea (and questions aren't disabled), run **[Discovery](#discovery--turn-a-bare-idea-into-requirements)** first and **name the spec file at the end**, once there's a draft worth saving (ask where to save it then, or propose a path the user confirms). Only take a save path up front when the user already gave one, or is updating an existing spec.

**Elicit before you write — don't guess at behavior.** Clarify any genuine ambiguity with `AskUserQuestion` before drafting; it is better to ask one too many questions than to produce an inaccurate spec. Whether that elicitation is interactive is governed by **`--disable-questions`**, not the rigor (see [Rigor](#rigor--how-deep-to-go) and [Discovery](#discovery--turn-a-bare-idea-into-requirements)) — under the flag, draft from what's given and leave a `[NEEDS CLARIFICATION: …]` marker on each genuine unknown instead of opening a question loop.

**Don't assert ungrounded facts.** At **`full`**, when the spec names a concrete internal detail — a file path, table or column name, or config key — confirm it cheaply against the codebase first; if you can't, write it as an explicit open question or ask via `AskUserQuestion` (a `[NEEDS CLARIFICATION]` marker under `--disable-questions`) rather than asserting a "currently X" claim that might be wrong (keep it light — a quick check, not a full verification pass; fact-checking the finished spec is `refine-spec`'s job). At **`light`/`standard`** there is nothing to confirm because you name **no internal implementation at all** — stay at the observable level (a *route* or user-visible field is fine; a *file / column / config key* is not), so the spec can't assert a wrong codebase fact and stays implementation-agnostic.

**If a detail truly can't be resolved** — not by a cheap check and not by asking — leave a single inline `[NEEDS CLARIFICATION: <what's unknown>]` marker rather than guessing (when interactive, prefer `AskUserQuestion` first; under `--disable-questions` the marker is your only tool). `refine-spec` blocks on any marker that remains, so none can survive into a finished `full` spec.

## Discovery — turn a bare idea into requirements

`write-spec` is the **entrypoint to the spec workflow**: it should be able to start from *nothing but an idea* and end with a structured draft. When the input is a fuzzy idea rather than settled requirements, run a **discovery pass before drafting** — **at every rigor** (unless `--disable-questions`), scaled to the change: a trivial `light` task may need only a question or two, or none; a routine `standard` feature, its genuine forks and edge cases; a `full` change, the complete design-tree walk below. Don't jump to the AC table off an under-specified ask.

Discovery is **convergent**: diverge just enough to surface what matters, then converge on the requirements. It is a *product / requirements* conversation, not a technical one — you are deciding **what should be true**, never checking what the code currently does (that grounding is `refine-spec`'s job; do not do it here). Draw out, via `AskUserQuestion` (batch related questions; take as many rounds as it needs):

- **The core goal** — the one outcome this must achieve, in the user's words.
- **The must-have behaviors** — what a user / admin should be able to do, and what must always or never happen.
- **The decisions only the user can make** — the genuine product forks (e.g. "notifications batch hourly vs. send immediately", "soft-delete vs. hard-delete"). Offer concrete options; don't silently pick for them.
- **Scope boundaries** — what is explicitly *out*, and anything the implementer must not touch.
- **The non-obvious edge cases** — the empty / limit / conflict / permission cases the happy path skips.

**Grill the design tree.** Walk these in **dependency order** — settle the decisions other choices hang on first, then the ones that depend on them — and **lead every question with your recommended answer**, so the user is confirming a default rather than starting from a blank. Ask relentlessly while the answers still change *what gets built*, but **stop when the returns diminish**: once the open items are low-stakes details an implementer can reasonably choose, you're done — don't manufacture questions to seem thorough.

Discovery may legitimately conclude that the idea **isn't ready to spec** (it's blocked on a decision only the user can make) or is **actually several specs** — surface that rather than forcing a draft. Otherwise, distill the answers into the AC-first draft below.

The line that keeps this from overlapping `refine-spec`: write-spec asks **requirements** questions sourced from the *idea* ("should it batch or send immediately?"); `refine-spec` asks **grounding** questions sourced from the *codebase* ("there's no `users.email` column — did you mean `contact_email`?"). Different questions, different stage. **Under `--disable-questions`** (batch / delegated calls) there is **no discovery loop** at any rigor — draft from what's given and leave `[NEEDS CLARIFICATION]` markers.

## Writing Philosophy

The goal is a spec that a human can scan in under 2 minutes and know exactly what to build. Every piece of the spec should pass a simple test: "Would removing this cause someone to build the wrong thing?" If no, cut it.

### Say things once, in the right place

Repeating information across sections creates maintenance burden and contradictions. If a field has a constraint, put it in the field's definition table — not in a separate "Validation" section. If a checklist covers which systems are affected, don't also include an "Affected Systems" table. Once a spec has an **Acceptance Criteria** table, the most common offender is a **Checklist that re-describes those criteria** — keep the Checklist a thin *code-area → `AC-id`* index that points at the criteria, never a second statement of them.

Consolidate related concepts into one section. Validation rules, edge cases, and selection logic about a feature belong inline with the feature's definition — not split into separate "Validation," "Edge Cases," or "Rules" sections.

### Describe behavior, not implementation

Write from the end-user or admin perspective. Describe what should happen, not how to code it. "Discount applies to the rental cost only" tells the developer what the user should see. "Add a discount_percentage column to the pricing_rules table" is an implementation decision that belongs in code, not the spec.

**The line is internal implementation vs. observable interface.** Naming the *observable* surface — a route like `/checkout`, a user-visible field, an API response shape — is behavior and is always fine. Naming *internal* implementation — a file path, function/class, table/column, config key, or framework specific — is HOW. At **`light`/`standard`** that HOW is off-limits entirely (the spec stays implementation-agnostic); only at **`full`** does it earn a place, and only where it's load-bearing or *is* the contract (the infra/config exception below). At `full`, pin the **load-bearing facts, config-as-contract values, and landmines** (the spots where the obvious approach is silently wrong) — **not a prescriptive file-by-file construction plan** (symbol decomposition, line anchors, "extract these N helpers"); that construction HOW is `launch-spec`'s job at implement-time, and `refine-spec` trims it as over-engineering. When a spec calls out such landmines as a block, title it **Watch out for** (or fold each inline under its body section) — never with the skill's internal term ("Landmines") and never with a note about how it was checked.

**Infra / platform / config / migration specs are the exception** — there the *configuration is the observable contract*. For a CDN, WAF, deploy-pipeline, or networking change, the resource names, settings, file paths, and policies are exactly what must be true, so specifying them is not over-reach — a "behavior-only" version would be unimplementable. The rule still holds in spirit: pin the **end-state config**, don't narrate the coding steps or the history of how the system got here. Expect these specs to be denser than a feature spec; that density is inherent, not bloat.

### Enumerate the acceptance criteria

Lead with a **markdown table** of **acceptance criteria** — every behavior and constraint that must hold once the change is done, each row a single testable assertion. The `AC` column holds the **bare stable number** (`1`, `2`, …; cited as `AC-1`, `AC-2` everywhere else). This table is the spec's contract: the reader's two-minute scan of *what must be true*, and what the implementation is later gated against criterion-by-criterion. **Read `${CLAUDE_PLUGIN_ROOT}/references/ac-contract.md`** for the full conventions (id format, grouping, the Checklist-as-index rule) — it's the canonical AC contract that write-spec and refine-spec share. The rules that shape a **first draft**:

- **Enumerate exhaustively — never condense.** The criteria are the one place you list *everything* — a requirement that lives only in a paragraph below gets missed at completion. Brevity is for wording, not coverage. A separate **Validation** / "how we'll test it" list is acceptance criteria wearing another hat — put those assertions here.
- **Each criterion is one atomic, observable end-state** — "Unrouted mail is quarantined, never dropped", not "build the quarantine system". Phrase what is *true* when done; the detailed rule that implements it lives in the body under its `AC-id`. Encode a **walking skeleton** as a behavioral AC (*an end-to-end path from {X} to an observable {Y} runs*), not a build step.
- **Don't silently drop non-functional constraints** — performance, security, idempotency, limits, concurrency: if the change implies one, make it its own `AC`. These are the most-lost requirements; capture the obvious ones (`refine-spec` hunts the rest).
- **Group only to aid the reader, never assert an order you can't ground.** A single flat table is the default; you *may* loosely group ≥2 obvious capability clusters under `### N. <capability>` headers as a "what am I building" map. Do **not** assert a build order or a cross-group `needs §X` dependency — that is a grounded fact `refine-spec` commits. Ids stay globally unique and stable across groups.

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

**Never narrate how the spec was authored.** The spec states what must be true, not how it was checked — strip every spec-process attestation: "verified against the codebase at HEAD", "audited against `infra/deploy/*`", "grounded against the codebase", and any internal pass name. Those describe the review, not the contract; a dev reading the spec doesn't need them, and they go stale the moment HEAD moves.

### Keep the TL;DR tight

Every standard/full spec **opens with a literal `## TL;DR` section** — not an unlabeled intro blurb, and not a `### Breaks if missed` subsection standing in for it. 2-3 bullets max, **each one short line — not a paragraph**. If the spec body is already concise, a long TL;DR just repeats it. The TL;DR should answer: what is the change in one sentence, and what's the one behavioral detail someone might get wrong without a heads-up. If the change has a **"breaks if missed"** risk, lead with it as a terse list that **points at the relevant `AC-id`s** rather than re-explaining them — the detail lives in the AC table and the body.

## Spec Structure

The skeleton below is the **`full`**-rigor shape; `light` is the Acceptance Criteria table alone and `standard` is TL;DR + AC + Boundaries (see [Rigor](#rigor--how-deep-to-go)). The **`## TL;DR` and `## Acceptance Criteria` sections are mandatory at standard/full** (plus **Boundaries** where the change has out-of-bounds areas) — never drop them, and never replace `## TL;DR` with an unlabeled intro paragraph. "Use only sections that are relevant" governs the **optional** ones (UI Changes, Data Migration, Current state → Target, Architecture, Checklist); not every spec needs those. The full skeleton is shaped for a typical feature change: **infra / platform / migration specs** usually drop **UI Changes** and **Data Migration** and add two — a **Current state → Target** view (what exists today vs. the end state, load-bearing when you're changing a running system) and a short **Architecture** diagram (mermaid). Add them only when they earn their place.

```markdown
# {Feature Name} Spec

## TL;DR
- {What the change is in one line}
- {The most important behavioral detail someone might get wrong}

---

## Acceptance Criteria
<!-- The enumerated contract: every behavior/constraint that must hold when done, as a discrete, testable assertion with a stable id. The reader's 2-minute scan AND what launch-spec's done-gate and verify-spec check 1:1. Enumerate exhaustively — never condense. Each AC is ONE atomic, observable end-state ("X is true"), not a task. Detailed rules in the body cite their AC-id so each fact is said once. -->
<!-- Default to a single FLAT table. OPTIONALLY split into named groups (### N. <capability>), one table per group, when the ACs fall into ≥2 obvious capabilities — a "what am I building" map. AC-ids stay globally unique and stable across groups. Do NOT assert a build order or cross-group `needs §X` here; refine-spec commits that after grounding against the codebase. -->

| AC  | Criterion                                       |
| --- | ----------------------------------------------- |
| 1   | {single testable assertion about the end state} |
| 2   | {…}                                             |

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

## Requirements reviewer — full rigor only, advisory

At **`full` rigor only**, after the AC table is distilled **and before the draft is committed**, get a second, **different-provider** opinion (OpenAI Codex) on *what the feature implies that the draft missed* — the single highest-value spot, since a requirement dropped at discovery is the most expensive miss. It is **optional, advisory, and fail-open**: it never gates, never blocks the draft from being written or committed, and is a no-op when Codex is absent / unauthenticated / off / slow / malformed. Run it **at most once**.

It has its **own independent off-switch**, `SPEC_OPS_CODEX_WRITE=0` (separate from the verify/refine judges' `SPEC_OPS_CODEX`), enforced by the bridge — set, the reviewer is skipped and the draft proceeds unchanged.

**Preserve the write firewall.** This is still a *requirements* review sourced from the **idea**, not a grounding review sourced from the **codebase** (that is `refine-spec`'s job). The reviewer reasons only about requirements the feature *implies* — it must **not** inspect the code. Enforce that structurally: point `--cd` at a **fresh empty scratch directory** (e.g. `mktemp -d`), so even under the read-only sandbox there is nothing to ground against.

**Availability — check this first.** Skill-load probe: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe --kind write-requirements` — if it reads `CODEX: NO`, **skip this reviewer entirely** and proceed straight to committing the draft (build no prompt, make no bridge call); only on `CODEX: YES` do the dispatch below.

Build a prompt file with the **idea + the drafted AC table + the discovery transcript** and an instruction to return only requirements implied by the feature (no codebase grounding), then dispatch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --kind write-requirements \
  --prompt-file <tmp-prompt> \
  --schema-file "${CLAUDE_PLUGIN_ROOT}/schemas/write_requirements.schema.json" \
  --cd <empty-scratch-dir>      # effort inherits SPEC_OPS_CODEX_EFFORT (default xhigh)
```

Branch on the exit code: **`0`** → the reviewer returned the `write-requirements` contract on stdout (`missingACs`, `unaskedQuestions`, `scopeRisks` — three string arrays, already shape-validated by the bridge); **`10` / `11` / `12`** → skipped / errored / unparseable, surface the one bridge log line and proceed straight to the commit.

**Disposition in ONE consolidated `AskUserQuestion`** (never a per-item loop): present every `missingACs` / `unaskedQuestions` / `scopeRisks` item together and let the user accept or reject each — an accepted `missingAC` becomes a new criterion in the AC table, an accepted `unaskedQuestion` becomes a discovery question to resolve, an accepted `scopeRisk` a trim; rejected items are dropped with a one-line reason. The findings are **advisory** — the user's dispositions shape the draft, but nothing here can block the draft from being written or committed.

## Commit the draft

Once the spec is written **to a file**, commit it — scoped to that one file — so the draft is captured in git:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_git.py" commit <abs-spec-path> "docs(spec): draft {spec name}"
```

The helper stages and commits **only the spec file** — never `git add -A`, never other staged changes, never a push — and no-ops cleanly if the path isn't in a git repo or hasn't changed. Use a conventional message naming the spec.

**Skip the commit when there is no spec file** — when a caller delegates in batch (e.g. authoring an issue *body* inline, or `light` rigor with no destination file), you produced text, not a file the user owns; commit nothing. Only ever commit the spec file itself, and never run any other git mutation.
