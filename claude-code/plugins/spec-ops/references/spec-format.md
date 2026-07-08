# The spec-ops spec format — the canonical shape per rigor

Every spec-ops spec has one of three shapes, by **rigor** (`light` / `standard` / `full`). This is
the single source for **which sections a spec carries at each rigor**, the **code-free rule**, how to
**detect a spec's rigor**, and the rule that **`write-spec` and `refine-spec` conform ANY spec they
touch to this shape** — rewriting a legacy or ad-hoc layout into it. For the AC table + Checklist
conventions themselves, see **`ac-contract.md`** (this file says *which* sections a spec carries; that
one says how the AC table and the Checklist work).

## The three shapes

- **`light`** — the `## Acceptance Criteria` table **only** (plus a one-line goal if the title isn't
  self-evident). No TL;DR, Summary, Boundaries, body, or Checklist. A few lines total.
- **`standard`** — `## TL;DR` → `## Summary` → `## Acceptance Criteria` → **Boundaries** (when the
  change has out-of-bounds areas) → a *lean body* (only for behavioral rules the AC don't already make
  obvious) → a lean two-subsection `## Checklist` (`### For agents` + a lean `### For humans`).
- **`full`** — `## TL;DR` → `## Summary` → `## Acceptance Criteria` → **Boundaries** → a self-contained
  body → the relevant optional sections (**UI Changes**, **Data Migration**, or — for infra/migration —
  **Current state → Target** + a short **Architecture** diagram) → the full two-subsection
  `## Checklist` (smoke checks first, grouped capability checks with the required edge/error cases, an
  explore block, and a sign-off).

`## TL;DR`, `## Summary`, `## Acceptance Criteria`, and `## Checklist` are **mandatory at
standard/full** (plus **Boundaries** where the change has out-of-bounds areas); `light` is the AC table
alone. The `write-spec` skeleton is the fill-in template for the full shape; optional sections appear
only when they earn their place.

## Code-free vs. code-pinning

- **`light` / `standard` are strictly code-free** — describe behavior and the *observable* interface
  (a route, a user-visible field, an API response shape); name **no** internal implementation (file
  paths, functions/classes, tables/columns, config keys, framework specifics). The implementer owns
  the HOW.
- **`full`** may pin the **load-bearing** internal facts, config-as-contract values, and landmines —
  but not a prescriptive file-by-file construction plan (that is `launch-spec`'s job at
  implement-time). A **config-as-contract** change (CDN / WAF / deploy / networking / migration)
  belongs at **full**, because the configuration *is* the observable contract; asked for one at
  light/standard, draft the code-free WHAT but flag the mismatch and recommend `full`.

## Detecting a spec's rigor

Prefer an explicit signal — a `rigor:` argument, or an obvious tier from the ask. Otherwise infer from
the spec's content:

- **code-free + self-evidently trivial** → `light`;
- **code-free + a routine bounded feature** → `standard`;
- **complex, cross-cutting, infra / platform / config-as-contract, or already code-pinning** → `full`.

**When the tier is unclear, choose the HIGHER one** — richer is the safe error, and it never strips
content on a guess (this mirrors `write-spec`'s "when unsure, default to full"). If the shape a spec
*is* in and the shape its content *implies* disagree in a way that would add or drop real content,
resolve it with the user rather than silently reshaping.

## Conform any spec to its shape — rewrite legacy, never grandfather it

`write-spec` (when it updates an existing spec) and `refine-spec` (every run) **conform the spec they
are handed to the canonical shape for its rigor** — this is what keeps every spec-ops spec consistent:

- **Restore a missing mandatory section** — an unlabeled intro paragraph → a literal `## TL;DR`; add
  the `## Summary`; add the two-subsection `## Checklist`.
- **Migrate a legacy / ad-hoc layout into the canonical one.** Most commonly an old flat
  `code area → AC-id` `## Checklist` (no subsections) is **rewritten** into the `### For agents` +
  `### For humans` form. A legacy shape is **migrated, not exempted** — this supersedes any earlier
  "leave a pre-format spec as-is" carve-out.
- **Preserve every substance.** Reformatting changes *structure*, never drops a requirement, value, or
  load-bearing detail. If a rewrite condenses a tracked spec, diff it and surface a short `removed:`
  list so a wrongful drop can be vetoed (the same no-silent-loss rule `refine-spec` already applies).
- **Respect rigor while conforming.** A `light` / `standard` spec stays **code-free** — conforming
  never introduces internal implementation the tier forbids; when unsure of the tier, prefer the
  higher shape and keep the content.

The judge (`spec-refine-judge`) enforces conformance **read-only**: a spec not in its rigor's canonical
shape is a structural `Gap`.

## The fill-in template

The single fill-in skeleton for every spec-ops spec, **shared by `write-spec` (drafting) and
`refine-spec` (conforming)**. It is the **`full`**-rigor shape; each section is tagged with the rigor
that includes it — copy the sections your rigor includes and fill them, drop the rest. The inline
`<!-- … -->` comments are drafting guidance (delete them in the output). Per-rigor tags:

- **`[all]`** — every rigor, including `light`.
- **`[standard+]`** — `standard` and `full` (omit at `light`).
- **`[full]`** — `full` only.
- **`[optional]`** — include only when the change needs it (and its rigor allows it).

`light` = the `## Acceptance Criteria` table alone (plus a one-line goal if the title isn't
self-evident). `standard` = TL;DR + Summary + AC + Boundaries (when there are out-of-bounds areas) + a
lean body (only for non-obvious rules) + a lean two-subsection Checklist. `full` = the whole skeleton,
with the optional sections that earn their place. Infra / platform / migration specs usually drop **UI
Changes** and **Data Migration** and add a **Current state → Target** view + a short **Architecture**
diagram. The drafting rules for each section (keep the TL;DR tight, write the Summary for a newcomer,
plain language for the offshore reader, show-don't-tell, code-free at light/standard) live in
`write-spec`.

```markdown
# {Feature Name} Spec
<!-- [all] At light, a one-line goal here may stand in for a title if the title isn't self-evident. -->

## TL;DR
<!-- [standard+] 2-3 tight bullets, each one short line. Lead with the "breaks if missed" risk, pointing at its AC-id. A terse re-orientation, NOT a condensed Summary. Never an unlabeled intro paragraph. -->
- {What the change is in one line}
- {The most important behavioral detail someone might get wrong — point at its AC-id}

## Summary
<!-- [standard+] Zero-context onboarding for a human (dev / QA). Short: ~3 small paragraphs / 4–8 sentences. CODE-FREE even at full — no file paths, functions/classes, tables/columns, or config keys. Order: what it is → why → key behaviors → out of scope. A DERIVED view: restates the contract in plain language, adds NO fact absent from the AC table, never the sole home of a fact. Follows the plain-language rules (short active-voice sentences, one term per concept, UI labels quoted verbatim). -->

**What this is:** {one sentence — what the feature is}
**Why:** {the problem it solves / who is slowed down today}
**Expected result:** {the key behaviors a user or admin can perform once it is built}
**Out of scope:** {what it explicitly does not do}

---

## Acceptance Criteria
<!-- [all] The enumerated contract: every behavior/constraint that must hold when done, as a discrete, testable assertion with a stable id. The reader's 2-minute scan AND what launch-spec's done-gate and verify-spec check 1:1. Enumerate exhaustively — never condense. Each AC is ONE atomic, observable end-state ("X is true"), not a task. Detailed rules in the body cite their AC-id so each fact is said once. -->
<!-- Default to a single FLAT table. OPTIONALLY split into named groups (### N. <capability>), one table per group, when the ACs fall into ≥2 obvious capabilities — a "what am I building" map. AC-ids stay globally unique and stable across groups. Do NOT assert a build order or cross-group `needs §X` here; refine-spec commits that after grounding against the codebase. -->

| AC  | Criterion                                       |
| --- | ----------------------------------------------- |
| 1   | {single testable assertion about the end state} |
| 2   | {…}                                             |

---

## {Feature Name}
<!-- [standard+] The body: at standard, lean — only for behavioral rules the AC don't already make obvious. Omit at light. Name this after the feature, not a generic label like "Solution". -->
<!-- One table for field/input definitions with constraints inline -->
<!-- A few bullets ONLY for behavior that isn't obvious from definitions -->
<!-- Examples/tables showing how it works in practice -->
<!-- Use mermaid diagrams for flows or multi-step processes instead of ordered lists -->

---

## UI Changes
<!-- [full][optional] Only if there are UI changes -->
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
<!-- [full][optional] Only if existing data/logic is affected -->
<!-- 1-2 lines -->

---

## Boundaries
<!-- [standard+][optional] Include when the change has out-of-bounds areas. What the implementer must NOT touch — the key to preventing drift in a long implementation (/goal) run -->
<!-- List files/dirs/systems/patterns to leave alone, and decisions already made that must not be revisited -->
<!-- Keep these change-specific. A boundary that is really a standing project convention (architecture, "don't touch prod") belongs in CLAUDE.md, not here — it's re-injected every turn regardless of which driver implements the spec -->
<!-- Include only real boundaries; omit the section if the change is fully self-contained -->

---

## Checklist
<!-- [standard+] The FINAL section. MANDATORY at standard/full (omit only at light). ONE checklist, split by the KIND of check into two subsections — no inline human/auto tags, no second checklist section anywhere. It is the VERIFICATION view: how a reader confirms each criterion holds once the change is built. Every verification item ends with a parenthetical (AC-…) tracing an EXISTING id; it never re-describes the criterion and never introduces a fact absent from the AC table. Coverage is exhaustive: every AC is traced by ≥1 item across the two subsections; one item may cover several ACs, one AC may need several items. A part-automatable criterion appears in BOTH subsections (the For humans line marked (partial)). Rigor: `standard` = For agents + a lean For humans (capability checks + a short explore prompt); `full` = the complete structure below. -->

### For agents
<!-- Runnable by an agent or CI: a command, a test, a static read. Terse + the expected result. -->
- [ ] {exact command or test} → {expected result} (AC-3)

### For humans
<!-- A person must look and judge (UI clickthrough, visual, UX, logic review — no runnable command). Read the line, do it, confirm what you see. Plain language, code-free — a zero-context non-native-English reader can perform it without opening the code. Group by user-facing capability/flow (~5–9 checks per group), smoke / happy-path first, then the required empty / edge / error cases the spec calls for. -->

**Setup:** {role / state / test data / where to look — plain placeholders}

**{Capability or flow — ~5–9 checks, smoke/happy-path first}**
- [ ] {observable action} → {expected observable result} (AC-2, AC-5)
- [ ] (empty case) {action} → {expected result} (AC-6)
- [ ] (error case) {action} → {expected result} (AC-6)

**Explore on your own** — go past the checks above and report anything that looks wrong; the goal is to find what they did not. (Never restate a scripted check here.)
- **Scenarios to try:**
  - {an open scenario tailored to this feature's risk areas}
  - {another}
- **Test ideas** (apply to any field or action):
  - Empty
  - Very long
  - 0 / huge / negative
  - Emoji & accents
  - Just over a limit
  - Create / read / update / delete
  - Refresh / Back / double-click / lose network / timeout
  - A different role
  - Small screen

**Sign-off**
- [ ] All `### For agents` checks pass
- [ ] All `### For humans` checks pass
- [ ] Explored past the checklist; anything wrong is reported
- [ ] No open critical problems
```
