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
| **`light`**    | a trivial, self-contained task                           | The `## Acceptance Criteria` table **only** (plus a one-line goal if it isn't obvious from the title). No TL;DR, Summary, Boundaries, body sections, or Checklist. A few lines total.                    | **Interactive, scaled to the task.** Run a brief [Discovery](#discovery--turn-a-bare-idea-into-requirements) pass — ask via `AskUserQuestion` about any genuine unknown, edge case, or scenario the one-liner hides; a truly trivial task may surface none, so stop fast. **With `--disable-questions`:** no loop — flag each unknown with one `[NEEDS CLARIFICATION: …]`.                                                                                                               |
| **`standard`** | a routine, bounded feature                               | TL;DR (lead with any "breaks if missed") + a **`## Summary`** (zero-context onboarding) + the AC table (grouped only if ≥2 obvious clusters) + **Boundaries** + a *lean* body **only** for behavioral rules the AC don't already make obvious + a lean **`## Checklist`** (`### For agents` + a lean `### For humans` of capability checks and a short explore prompt). | **Interactive.** [Discovery](#discovery--turn-a-bare-idea-into-requirements) on the genuine forks, unknowns, and edge cases. **With `--disable-questions`:** markers only, as above.                                                                                                                                                                                                                                                 |
| **`full`**     | a complex change, or any infra / config-as-contract spec | **A `## TL;DR` + `## Summary` section** (lead with any "breaks if missed") + the complete structure below — exhaustive AC, self-contained body, the full two-subsection **`## Checklist`** (smoke + grouped capability checks + explore block + sign-off), every relevant section.                                                                                                      | **Interactive — fullest.** Run the complete **[Discovery](#discovery--turn-a-bare-idea-into-requirements)** design-tree walk, using `AskUserQuestion` before guessing — better to ask one too many. Then draft, and hand the result to **`refine-spec`** to ground and harden. **With `--disable-questions`:** markers only. |

**Constant across all three rigors** — these hold whatever the depth:

- **Enumerate the Acceptance Criteria exhaustively — never condense.** "Cut to the bone" is for *prose*, never for coverage: a `light` spec is *all* criteria and almost no prose, yet still lists every one.
- **`light`/`standard` are strictly code-free WHAT.** Describe behavior and the *observable interface* — a route, a user-visible field, an API response shape — but name **no internal implementation** (file paths, function/class names, table/column names, config keys, framework specifics). The implementer chooses the HOW; grounding enters later in `refine-spec`. Only **`full`** may pin implementation — it's where code-grounding lives, and for an infra/config-as-contract spec the config *is* the contract.
- **A config-as-contract change doesn't fit `light`/`standard`.** A CDN, WAF, deploy-pipeline, networking, or migration change can't be carried by a code-free spec — the configuration *is* the contract. Asked for one at `light`/`standard`, draft the code-free WHAT but **flag the mismatch and recommend `full`** (for a board-intake caller, that's its T3 tier).
- **Discovery runs by default at every rigor.** The AC must capture every unknown, edge case, and scenario regardless of tier — so rigor sets the *depth* of questioning and the *prose* emitted, **never whether you elicit**. Only `--disable-questions` turns the interactive loop off (falling back to `[NEEDS CLARIFICATION]` markers). See [Discovery](#discovery--turn-a-bare-idea-into-requirements).

## Inputs

Start from whatever the user has — a rough idea, loose requirements, or a fully-formed change. You do **not** need a destination file to begin: when you start from an idea (and questions aren't disabled), run **[Discovery](#discovery--turn-a-bare-idea-into-requirements)** first and **name the spec file at the end**, once there's a draft worth saving (ask where to save it then, or propose a path the user confirms). Only take a save path up front when the user already gave one, or is updating an existing spec — and when you **update an existing spec, conform it to its rigor's canonical shape and template** (`${CLAUDE_PLUGIN_ROOT}/references/spec-format.md`), migrating any legacy layout while preserving every substance.

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
- **The quality bar & leave-it-better appetite** — any performance / security / scale / robustness the change must meet, and whether you want it to **leave the touched area better** (a warranted, in-scope cleanup) rather than pile onto existing patterns. This is a *product* decision about the desired end state — you are **not** inspecting code; `refine-spec` grounds which debt actually exists and scopes any bounded refactor (`${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md`).

**Grill the design tree.** Walk these in **dependency order** — settle the decisions other choices hang on first, then the ones that depend on them — and **lead every question with your recommended answer**, so the user is confirming a default rather than starting from a blank. Ask relentlessly while the answers still change *what gets built*, but **stop when the returns diminish**: once the open items are low-stakes details an implementer can reasonably choose, you're done — don't manufacture questions to seem thorough.

Discovery may legitimately conclude that the idea **isn't ready to spec** (it's blocked on a decision only the user can make) or is **actually several specs** — surface that rather than forcing a draft. Otherwise, distill the answers into the AC-first draft below.

The line that keeps this from overlapping `refine-spec`: write-spec asks **requirements** questions sourced from the *idea* ("should it batch or send immediately?"); `refine-spec` asks **grounding** questions sourced from the *codebase* ("there's no `users.email` column — did you mean `contact_email`?"). Different questions, different stage. **Under `--disable-questions`** (batch / delegated calls) there is **no discovery loop** at any rigor — draft from what's given and leave `[NEEDS CLARIFICATION]` markers.

## Writing Philosophy

The goal is a spec that a human can scan in under 2 minutes and know exactly what to build. Every piece of the spec should pass a simple test: "Would removing this cause someone to build the wrong thing?" If no, cut it.

### Say things once, in the right place

Repeating information across sections creates maintenance burden and contradictions. If a field has a constraint, put it in the field's definition table — not in a separate "Validation" section. The **`## Checklist`** is not a second statement of the criteria: each verification item **traces** the `AC-id`(s) it checks with a parenthetical `(AC-…)` and never re-describes what the criterion asserts — that text already lives in the AC table.

**The human layer is a deliberate exception.** The **`## Summary`** and the **`### For humans`** checklist restate the contract in plain language for a person who must understand the feature and verify it by hand — that comprehension restatement is intentional and does **not** violate "say things once", *as long as it adds no new fact*: no requirement, value, or success criterion absent from the AC table. Keep it a derived view — never the sole home of a fact.

Consolidate related concepts into one section. Validation rules, edge cases, and selection logic about a feature belong inline with the feature's definition — not split into separate "Validation," "Edge Cases," or "Rules" sections.

### Describe behavior, not implementation

Write from the end-user or admin perspective. Describe what should happen, not how to code it. "Discount applies to the rental cost only" tells the developer what the user should see. "Add a discount_percentage column to the pricing_rules table" is an implementation decision that belongs in code, not the spec.

**The line is internal implementation vs. observable interface.** Naming the *observable* surface — a route like `/checkout`, a user-visible field, an API response shape — is behavior and is always fine. Naming *internal* implementation — a file path, function/class, table/column, config key, or framework specific — is HOW. At **`light`/`standard`** that HOW is off-limits entirely (the spec stays implementation-agnostic); only at **`full`** does it earn a place, and only where it's load-bearing or *is* the contract (the infra/config exception below). At `full`, pin the **load-bearing facts, config-as-contract values, and landmines** (the spots where the obvious approach is silently wrong) — **not a prescriptive file-by-file construction plan** (symbol decomposition, line anchors, "extract these N helpers"); that construction HOW is `launch-spec`'s job at implement-time, and `refine-spec` trims it as over-engineering. When a spec calls out such landmines as a block, title it **Watch out for** (or fold each inline under its body section) — never with the skill's internal term ("Landmines") and never with a note about how it was checked.

**Infra / platform / config / migration specs are the exception** — there the *configuration is the observable contract*. For a CDN, WAF, deploy-pipeline, or networking change, the resource names, settings, file paths, and policies are exactly what must be true, so specifying them is not over-reach — a "behavior-only" version would be unimplementable. The rule still holds in spirit: pin the **end-state config**, don't narrate the coding steps or the history of how the system got here. Expect these specs to be denser than a feature spec; that density is inherent, not bloat.

### Enumerate the acceptance criteria

Lead with a **markdown table** of **acceptance criteria** — every behavior and constraint that must hold once the change is done, each row a single testable assertion. The `AC` column holds the **bare stable number** (`1`, `2`, …; cited as `AC-1`, `AC-2` everywhere else). This table is the spec's contract: the reader's two-minute scan of *what must be true*, and what the implementation is later gated against criterion-by-criterion. **Read `${CLAUDE_PLUGIN_ROOT}/references/ac-contract.md`** for the full conventions (id format, grouping, the two-subsection `## Checklist`) — it's the canonical AC contract that write-spec and refine-spec share. The rules that shape a **first draft**:

- **Enumerate exhaustively — never condense.** The criteria are the one place you list *everything* — a requirement that lives only in a paragraph below gets missed at completion. Brevity is for wording, not coverage. A separate **Validation** / "how we'll test it" list is acceptance criteria wearing another hat — put those assertions here.
- **Each criterion is one atomic, observable end-state** — "Unrouted mail is quarantined, never dropped", not "build the quarantine system". Phrase what is *true* when done; the detailed rule that implements it lives in the body under its `AC-id`. Encode a **walking skeleton** as a behavioral AC (*an end-to-end path from {X} to an observable {Y} runs*), not a build step.
- **Don't silently drop non-functional constraints** — the quality verticals in `${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md` (performance, security, scalability, maintainability, error-handling, …): if the change materially implies one, make it its own `AC`. If the user set a **leave-it-better appetite**, note it as intent for `refine-spec` to scope. These are the most-lost requirements; capture the obvious ones (`refine-spec` hunts the rest).
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

Every standard/full spec **opens with a literal `## TL;DR` section** — not an unlabeled intro blurb, and not a `### Breaks if missed` subsection standing in for it. 2-3 bullets max, **each one short line — not a paragraph**. It is the terse top layer: what is the change in one sentence, and the key **"breaks if missed"** risk. Lead with that risk as a terse list that **points at the relevant `AC-id`s** rather than re-explaining them — the detail lives in the AC table and the body. It is a fast re-orientation for a reader (or agent) that needs the hardest constraint immediately — **never a condensed Summary.** The TL;DR and the Summary sit at **different altitudes** and must not copy-paste each other; each reads correctly on its own.

### Write the Summary for a newcomer

Standard/full specs carry a **`## Summary`** immediately after the TL;DR — zero-context onboarding for a person (a developer or QA) who has never seen the work. Keep it short (about 3 small paragraphs / 4–8 sentences), and in this order: **what it is** (one sentence defining the feature) → **why** (the problem it solves) → **key behaviors** (what a user or admin can do) → **out of scope** (what it explicitly does not do).

- **Code-free, even at full.** Name no file paths, functions / classes, tables / columns, or config keys — the technical detail stays in the body and the AC table. The Summary describes behavior a non-technical reader can follow.
- **A derived human view, not a source of truth.** The Acceptance Criteria table stays canonical. The Summary restates the contract for comprehension and adds **no** requirement absent from the table — it is never the sole home of a fact, so `refine-spec` / `verify-spec` do not treat its prose as an independent groundable claim.
- **A different altitude from the TL;DR.** The TL;DR is the terse re-orientation; the Summary is the full plain-language onboarding. Neither copy-pastes the other.

Write it — and the `### For humans` checklist — to the plain-language rules below.

### Plain language for the offshore reader

The **`## Summary`** and the **`### For humans`** checklist are read by a person who may read English as a second language and must verify the feature by hand. Write both parts to these rules:

- One idea per sentence (about **20 words maximum**); **active voice**; **present tense**.
- Use the **same term every time** for one concept; spell out each acronym once.
- No idioms, no phrasal verbs, no contractions.
- Quote UI labels — screen, button, and field names — **verbatim**.
- In a step, say **where before what** ("On the Settings page, select Save"), so the reader orients before acting.

## Spec Structure

The canonical fill-in skeleton — single-sourced in `spec-format.md` (pointer below) — is the **`full`**-rigor shape; `light` is the Acceptance Criteria table alone and `standard` is TL;DR + Summary + AC + Boundaries + a lean Checklist (see [Rigor](#rigor--how-deep-to-go)). The per-rigor section-set, the code-free rule, and the rule that an **updated / passed-in spec is conformed to its rigor's shape** (rewriting a legacy layout, never grandfathering it) are single-sourced in **`${CLAUDE_PLUGIN_ROOT}/references/spec-format.md`** — shared with `refine-spec`. The **`## TL;DR`, `## Summary`, `## Acceptance Criteria`, and `## Checklist` sections are mandatory at standard/full** (plus **Boundaries** where the change has out-of-bounds areas) — never drop them, and never replace `## TL;DR` with an unlabeled intro paragraph. "Use only sections that are relevant" governs the **optional** ones (UI Changes, Data Migration, Current state → Target, Architecture); not every spec needs those. The full skeleton is shaped for a typical feature change: **infra / platform / migration specs** usually drop **UI Changes** and **Data Migration** and add two — a **Current state → Target** view (what exists today vs. the end state, load-bearing when you're changing a running system) and a short **Architecture** diagram (mermaid). Add them only when they earn their place.

**The fill-in template is single-sourced in `${CLAUDE_PLUGIN_ROOT}/references/spec-format.md`** ("The fill-in template") — the full-rigor skeleton with per-rigor `[all]` / `[standard+]` / `[full]` / `[optional]` tags and the drafting comments. Copy the sections your rigor includes, fill them, and delete the guidance comments. The per-section drafting rules above (keep the TL;DR tight, write the Summary for a newcomer, plain language, show-don't-tell, code-free at light/standard) still apply.

## Requirements reviewer — standard/full, advisory

At **`standard` and `full` rigor** (skip at `light` — a trivial task has little a reviewer would surface), after the AC table is distilled **and before the draft is committed**, get a second, **different-provider** opinion (OpenAI Codex) on *what the feature implies that the draft missed* — the single highest-value spot, since a requirement dropped at discovery is the most expensive miss (and these misses cluster at `standard`, the common tier — which is why the pass runs there too, not just at `full`). At `standard` the pass is naturally lighter (fewer implied criteria to surface); the mechanism is identical. It is **optional, advisory, and fail-open**: it never gates, never blocks the draft from being written or committed, and is a no-op when Codex is absent / unauthenticated / off / slow / malformed. Run it **at most once**.

It has its **own independent off-switch**, `SPEC_OPS_CODEX_WRITE=0` (separate from the verify/refine judges' `SPEC_OPS_CODEX`), enforced by the bridge — set, the reviewer is skipped and the draft proceeds unchanged.

**Preserve the write firewall.** This is still a *requirements* review sourced from the **idea**, not a grounding review sourced from the **codebase** (that is `refine-spec`'s job). The reviewer reasons only about requirements the feature *implies* — it must **not** inspect the code. Enforce that structurally: point `--cd` at a **fresh empty scratch directory** (e.g. `mktemp -d`), so even under the read-only sandbox there is nothing to ground against.

**Availability — check this first.** Skill-load probe: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe --kind write-requirements` — the probe prints one line; if it **shows `CODEX: YES`**, Codex is available — **run the reviewer below.** (Only the `CODEX: YES` verdict matters; whatever text follows it is an informational reason that may change — ignore it.) Any other line — a `CODEX: NO …` line, blank, or an error / denied result — means unavailable: **skip the reviewer entirely** and proceed straight to committing the draft (build no prompt, make no bridge call). Fail-open: a missing or denied probe never blocks the draft.

Build a prompt file with the **idea + the drafted AC table + the discovery transcript** and an instruction to return only requirements implied by the feature (no codebase grounding), then dispatch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --kind write-requirements \
  --prompt-file <tmp-prompt> \
  --schema-file "${CLAUDE_PLUGIN_ROOT}/schemas/write_requirements.schema.json" \
  --cd <empty-scratch-dir>      # effort inherits SPEC_OPS_CODEX_EFFORT (default xhigh)
```

Branch on the exit code: **`0`** → the reviewer returned the `write-requirements` contract on stdout (`missingACs`, `unaskedQuestions`, `scopeRisks` — three string arrays, already shape-validated by the bridge); **anything else** — `10` / `11` / `12`, any other non-zero exit, or the call not running at all (e.g. denied / blocked) → skipped / errored / unparseable / unavailable: surface the one bridge log line if there is one and proceed straight to the commit. The reviewer can never block the draft.

**Disposition in ONE consolidated `AskUserQuestion`** (never a per-item loop): present every `missingACs` / `unaskedQuestions` / `scopeRisks` item together and let the user accept or reject each — an accepted `missingAC` becomes a new criterion in the AC table, an accepted `unaskedQuestion` becomes a discovery question to resolve, an accepted `scopeRisk` a trim; rejected items are dropped with a one-line reason. The findings are **advisory** — the user's dispositions shape the draft, but nothing here can block the draft from being written or committed.

## Commit the draft

Once the spec is written **to a file**, commit it — scoped to that one file — so the draft is captured in git:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_git.py" commit <abs-spec-path> "docs(spec): draft {spec name}"
```

The helper stages and commits **only the spec file** — never `git add -A`, never other staged changes, never a push — and no-ops cleanly if the path isn't in a git repo or hasn't changed. Use a conventional message naming the spec.

**Skip the commit when there is no spec file** — when a caller delegates in batch (e.g. authoring an issue *body* inline, or `light` rigor with no destination file), you produced text, not a file the user owns; commit nothing. Only ever commit the spec file itself, and never run any other git mutation.
