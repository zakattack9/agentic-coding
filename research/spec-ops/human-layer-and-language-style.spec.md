# Human-Readable Spec Layer & Vietnamese Output Style Spec

> This spec **dogfoods the format it defines** — it carries the proposed `## Summary` section and the new observable `## Checklist`, so it doubles as a reference for what the feature produces.

## TL;DR
- Add a human-facing layer to every standard/full spec — a plain-language `## Summary` (right after `## TL;DR`) and a **repurposed single** `## Checklist` of observable "do X → expect Y" sign-off items — so an off-shore dev/QA can grasp and verify a feature while the spec stays AI-optimized and entirely English.
- Breaks if missed: the `## Checklist` **replaces** the old code-area→AC-id index (one checklist only, name kept). It must stay machine-useful — every item keeps an `AC-id` trace, and at `full` may note its code-area — or verify-spec's coverage mapping and the AI implementer lose traceability (AC-7..AC-14, AC-19).
- Ship a **standalone, opt-in** Vietnamese output style (artifacts stay English) tracked in this repo with an install doc — the comprehension path for the Vietnamese team (AC-24..AC-31).

## Summary

The spec-ops skills produce specs tuned for AI agents: exhaustive, technical, and long. They are accurate but hard for a human — especially an off-shore team working in Vietnamese — to read end-to-end and to *verify* against once code lands. Verification (clicking through the UI, running and reviewing tests) is the real bottleneck: implementation can be parallelized, but a feature is only "done" when a human confirms it meets the requirements, and a human can only confirm what they can comprehend.

This change adds a **human-readable layer** to the spec without changing the AI-facing core. Two new bookends frame the existing technical sections:

- A **`## Summary`** at the top (just under the TL;DR) — a short, jargon-free narrative of *what* is being built, *why*, and how it behaves, written for a person rather than an agent.
- A repurposed **`## Checklist`** at the end — a single list of concrete, observable verification steps ("open the cart, apply a promo, confirm the badge shows the discount"), each tagged as something a human must check manually or something an agent can run, and each linked back to the acceptance criteria it proves.

These stay **English** — the spec is the canonical artifact and never gets translated. The Vietnamese comprehension path is the second half of this change: a standalone, opt-in **output style** that makes Claude *converse* with the developer in Vietnamese while writing every artifact (code, specs, commits, file contents) in English. A Vietnamese-first dev can then open a session, ask Claude to walk them through the English `## Summary` and `## Checklist` in Vietnamese, and sign the feature off — without anything in the repository ever leaving English.

The human layer is **drafted by write-spec and finalized by refine-spec** (so it tracks the acceptance criteria as they settle), gated by refine's readiness check, and drift-checked by verify-spec. The `## Summary` is a derived view: the acceptance-criteria table stays the single source of truth, so the grounding passes never treat the narrative as an independent claim to fact-check.

---

## Acceptance Criteria

<!-- Grouped as a "what am I building" map. AC-ids are globally unique and stable across groups. No build order / `needs §X` asserted here — refine-spec commits those after grounding. -->

### 1. Human-readable `## Summary` section

| AC  | Criterion                                                                                                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The full-rigor spec skeleton emitted by write-spec includes a `## Summary` section positioned immediately after `## TL;DR`.                                                                          |
| 2   | `## Summary` is plain-language narrative covering what is being built, why, and the functional behavior a non-AI human reader (dev / QA) must grasp — written for human comprehension, not the agent. |
| 3   | `## Summary` prose names no internal implementation (file paths, function / class names, table / column names, config keys) even at full rigor; technical detail stays in the body and AC table.      |
| 4   | `## Summary` is a derived human view, not a source of truth: the `## Acceptance Criteria` table stays canonical, and refine-spec / verify-spec do not treat Summary prose as an independent groundable claim. |
| 5   | `## Summary` does not restate the `## TL;DR`; TL;DR stays the terse one-line + breaks-if-missed hook, Summary is the fuller walkthrough.                                                              |
| 6   | Rigor scaling for `## Summary`: absent at `light`, present and lean at `standard`, present and complete at `full`.                                                                                    |

### 2. The repurposed single `## Checklist`

| AC  | Criterion                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 7   | The spec format defines exactly one checklist section, retaining the name `## Checklist`; no second checklist section exists anywhere in the format.                                              |
| 8   | Each `## Checklist` item is a human verification step phrased as an observable check — what to do (a UI action, a test, or a command) and the expected result — in plain language.                |
| 9   | Each `## Checklist` item carries a parenthetical `AC-id` trace (e.g. `(AC-3, AC-7)`) tying it to the criteria it verifies; the trace is present but unobtrusive.                                  |
| 10  | Every acceptance criterion (at standard / full) is traced by at least one `## Checklist` item — coverage is exhaustive.                                                                          |
| 11  | Each `## Checklist` item indicates whether it is **human-only** (manual UI / visual verification) or **auto-verifiable** (a test or command an agent can run).                                    |
| 12  | At `full` rigor a `## Checklist` item may optionally note the code-area / touchpoint it lands in (recovering the old index's implementer value); this annotation is per-item and optional.        |
| 13  | The previous "code-area → AC-id index" semantics of `## Checklist` are removed from the format definition and all guidance.                                                                       |
| 14  | Rigor scaling for `## Checklist`: absent at `light`, present (lean, code-free, related ACs grouped into fewer checks) at `standard`, present (more granular, optional code-area notes) at `full`.   |
| 35  | A `## Checklist` item verifies an existing acceptance criterion and never introduces a requirement, value, or success criterion absent from the AC table — it is not the sole home of any fact.   |
| 36  | Every `AC-id` cited in a `## Checklist` trace references an existing criterion; there are no orphan or unknown ids.                                                                              |
| 37  | `[auto]` items name the runnable command or test and its expected result; `[human]` items state the visible setup, action, and expected result, phrased clearly for a non-native English reader.  |
| 38  | `## Checklist` is the final section of the spec.                                                                                                                                                 |

### 3. Skill & contract wiring

| AC  | Criterion                                                                                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 15  | write-spec drafts the `## Summary` and `## Checklist` as part of a standard / full draft.                                                                                                               |
| 16  | refine-spec finalizes the `## Summary` and `## Checklist` after the ACs stabilize and reconciles them on any AC added, removed, renamed, merged, or split — every AC traced; no stale or orphan items or traces.   |
| 17  | refine-spec's readiness gate blocks Stop when, at standard / full, the `## Summary` or `## Checklist` is missing or checklist coverage is non-exhaustive.                                                |
| 18  | The refine readiness judge (`spec-refine-judge`) verdict includes a flag asserting the human layer (Summary present + exhaustive observable Checklist) is present and consistent at standard / full.    |
| 19  | verify-spec's coverage-matrix `checklist-item` column maps each `AC-id` to the new `## Checklist` item(s) and no longer references a code-area index.                                                    |
| 20  | verify-spec's drift re-check flags (report-only) a stale `## Summary` / `## Checklist`, invalid or orphan AC traces, duplicate or conflicting coverage, and any checklist item matching no AC; verify-spec stays read-only and edits nothing. |
| 21  | `references/ac-contract.md` documents the new single-`## Checklist` semantics (observable items, AC-id trace, exhaustive coverage, optional full-rigor code-area note) and no longer describes a code-area → AC-id index. |
| 22  | write-spec's Writing Philosophy / "say things once" guidance is updated to match the new `## Checklist` semantics — no instruction to keep it a code-area index, no contradiction with the new format.   |
| 23  | The spec-ops README documents the `## Summary` section and the repurposed `## Checklist`.                                                                                                               |

### 4. Vietnamese output style

| AC  | Criterion                                                                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 24  | A Vietnamese output style file exists at this repo's `.claude/output-styles/` directory and is tracked in git.                                                                                                            |
| 25  | The style's frontmatter sets a descriptive `name`, a `description`, and `keep-coding-instructions: true`, and omits `force-for-plugin` (and any auto-apply) so it is opt-in via `/output-style`.                          |
| 26  | The style instructs Claude to respond to the user in Vietnamese (all conversational prose, explanations, questions) while writing ALL artifacts in English — code, comments, identifiers, file names, commit messages, documentation, config, and every spec section including `## Summary` and `## Checklist`. |
| 27  | The style instructs that when explaining an English spec / checklist, Claude explains in Vietnamese but quotes the English text verbatim — it does not translate the artifact in place.                                   |
| 28  | The style instructs that AskUserQuestion prompts and options render in Vietnamese, while any text written into files stays English.                                                                                       |
| 29  | The style instructs that technical terms and code tokens remain in English even within Vietnamese prose.                                                                                                                  |
| 39  | The output style file is valid, loadable Claude Code output-style syntax and sets `keep-coding-instructions: true` without otherwise disabling coding behavior.                                                            |
| 40  | The output style specifies the Northern (Hà Nội) Vietnamese register.                                                                                                                                                  |

### 5. Distribution & versioning

| AC  | Criterion                                                                                                                                                                          |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 30  | The repo README (and / or a dedicated docs note) documents installing the style: copy the style file to `~/.claude/output-styles/` and activate it via `/output-style`, and notes the style is optional and changes no persisted artifact's language. |
| 31  | The install doc states the caveat that an output style loads at session start and switching it requires `/clear` or a restart.                                                    |
| 32  | The spec-ops plugin version in `.claude-plugin/marketplace.json` is bumped (minor) to cover the Part A changes.                                                                   |
| 33  | All spec files and the human layer remain entirely in English — no spec content is translated into Vietnamese.                                                                    |
| 34  | The spec-ops test suite is updated so no test asserts the old code-area-index `## Checklist` semantics, and the new format / wiring is covered — including light/standard/full rigor behavior (light omits the layer; standard/full include and gate it); the suite passes. |

---

## Current state → Target

| Aspect                  | Today                                                                                                   | Target                                                                                                                                            |
| ----------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Human comprehension     | None in-spec; reader parses the AC table + technical body.                                               | `## Summary` narrative at the top of every standard / full spec.                                                                                  |
| `## Checklist` meaning   | Optional, full-only, thin **code-area → AC-id index** for the implementer.                              | The **single** checklist: observable human sign-off items, each with an AC-id trace, human-only / auto tag, and (full only) an optional code-area note. |
| Verification support     | verify-spec automates grounding; no human walkthrough artifact.                                         | The `## Checklist` is the human's post-implementation sign-off list; verify-spec maps its coverage matrix to it and drift-checks it.               |
| Language for the team    | Specs English; no localized interaction.                                                                | Specs stay English; a standalone opt-in output style makes Claude converse in Vietnamese while keeping all artifacts English.                      |

---

## The human layer — content rules

**`## Summary`** — a few sentences to a few short paragraphs (lean at `standard`, fuller at `full`). Answers, for a human: what does this feature do, why does it exist, and what is the behavior I'd see using it. It is a *restatement* for comprehension — it adds no requirement that isn't in the AC table, and it must not be the sole home of any fact.

**`## Checklist`** — one section, each item on one line in the shape:

```markdown
## Checklist
- [ ] {observable action} → {expected result} — [human] (AC-2, AC-5)
- [ ] {run X} → {expected output} — [auto] (AC-8)
- [ ] {observable action} → {expected result} — [auto] (AC-19) · `path/to/area`   <!-- code-area note: full rigor only, optional -->
```

- **Tag, then trace.** Each item ends with the tag (`[human]` or `[auto]`) followed by the parenthetical `(AC-…)` trace. `[human]` = a person must verify it (UI clickthrough, visual, manual QA); state the visible **setup → action → expected result** clearly enough for a non-native English reader to follow without reading code. `[auto]` = an agent / CI can run it; name the **command or test and its expected result**.
- **The tag is author judgment.** verify-spec maps coverage and flags trace / coverage problems, but does not fail an item for being tagged `[human]` where it might have run it `[auto]`.
- The trailing `(AC-…)` is the traceability anchor verify-spec's coverage matrix maps against — keep it on every item, and cite only `AC-id`s that exist (no orphan / unknown ids).
- Every AC must appear in at least one item's trace. One item may cover several closely-related ACs when that reads better for a human; one AC may need several items. At `standard`, group related ACs into fewer lean checks; at `full`, prefer more granular items.
- A checklist item **verifies** an AC — it never introduces a requirement, value, or success criterion that isn't already in the AC table (it is not the sole home of any fact).

## Vietnamese output style — behavior contract

A single standalone style file at `.claude/output-styles/` (repo-tracked), opt-in. Its instruction body must establish, unambiguously:

- **Converse in Vietnamese** — every response to the user: prose, explanations, status, and `AskUserQuestion` prompts / options.
- **Write every artifact in English** — code, comments, identifiers, file and branch names, commit messages, documentation, config, and all spec content (including the new `## Summary` and `## Checklist`).
- **Explain, don't translate** — when walking the user through an English spec or checklist, explain in Vietnamese but quote the English text verbatim; never rewrite the artifact into Vietnamese.
- **Keep code tokens English** — technical terms, API names, and code stay English even inside Vietnamese prose.
- **Register: Northern (Hà Nội) Vietnamese** — phrasing and vocabulary throughout, including AskUserQuestion options.
- `keep-coding-instructions: true`; no force / auto-apply. The file must be valid, loadable output-style syntax — selecting it must not error or strip Claude Code's coding behavior.

## Watch out for

- **Output styles load at session start.** Selecting a different style mid-session via `/config` does not take effect until `/clear` or restart — the install doc must say so (AC-31).
- **Subagents are unaffected by output styles.** The spec-ops judges run with their own system prompts, so their JSON return contracts stay English regardless of the active style — no special handling needed, but don't rely on the style to localize subagent output.
- **AC-id traces belong in the spec, not in shipped code.** The existing artifact-hygiene sweep strips AC-id citations from *built* artifacts; the `## Checklist`'s traces live in the spec, which is allowed to carry them — keep the two scopes distinct.
- **The `## Checklist` heading is reused with a new meaning.** Pre-change specs keep the old code-area index under the same heading (left alone, per Boundaries). Tell the difference by item shape: new items are observable "do X → expect Y — [tag] (AC-…)"; legacy items are "code area → AC-id" bullets. `ac-contract.md` / README must make the new meaning unambiguous so the reuse doesn't confuse readers of mixed-age specs.
- **Don't let the `## Summary` become groundable.** It's a derived view; refine / verify treat the AC table as canonical (AC-4). Wording the Summary as narrative (not as new assertions) keeps it from being double-checked or contradicting an AC.

## Boundaries

- The output style is **standalone** — do **not** bundle it into the spec-ops plugin's `output-styles/` directory or declare it in `plugin.json`.
- The style must stay **opt-in** — do **not** set `force-for-plugin: true` or any auto-apply.
- Do **not** translate any written artifact (spec, code, commit, docs) into Vietnamese — English only.
- Do **not** add a `version` field to `plugin.json`; the version lives only in `marketplace.json`.
- **Leave existing checklists alone.** The new format applies only to specs authored under the updated write-spec. refine-spec does **not** rewrite a pre-existing legacy code-area `## Checklist`, and verify-spec does **not** flag legacy specs as non-compliant — the heading is reused, and `ac-contract.md` / README document the new meaning for new specs. Updating example fixtures under `research/spec-ops/testing/` is optional dogfooding, not required.
- `light`-rigor output is unchanged (AC-table-only) — do **not** add `## Summary` / `## Checklist` at `light`.
- Keep verify-spec **read-only** — it reports human-layer staleness, it never edits the spec.

## Checklist

- [ ] Generate a standard/full spec → a `## Summary` appears right after `## TL;DR`, plain-language, no file/function/table/config names → [auto] (AC-1, AC-2, AC-3, AC-5)
- [ ] Generate a `light` spec → no `## Summary` or `## Checklist` is emitted → [auto] (AC-6, AC-14)
- [ ] Inspect refine/verify logic → Summary prose is not enumerated as a groundable claim → [auto] (AC-4)
- [ ] Inspect the format/contract → exactly one `## Checklist` (name kept), as the final section, items are observable "do X → expect Y", each ending with a `[human]`/`[auto]` tag then an `AC-id` trace → [auto] (AC-7, AC-8, AC-9, AC-11, AC-38)
- [ ] Inspect a standard/full spec → every AC is traced by ≥1 checklist item, every cited AC-id exists, and no item introduces a fact absent from the AC table → [auto] (AC-10, AC-35, AC-36)
- [ ] Inspect items → `[auto]` names a runnable command/test + expected result; `[human]` states visible setup→action→expected clearly for a non-native reader → [auto] (AC-37)
- [ ] Inspect a full-rigor checklist → an item may carry an optional code-area note → [auto] (AC-12)
- [ ] Read ac-contract.md, write-spec philosophy, and README → no code-area-index description remains; new semantics documented → [auto] (AC-13, AC-21, AC-22, AC-23)
- [ ] Run write-spec then refine-spec on a feature → draft has Summary+Checklist; refine reconciles both to the final ACs → [human] (AC-15, AC-16)
- [ ] Remove a checklist item / the Summary at standard-or-full → refine's Stop gate blocks and the refine judge flag fails → [auto] (AC-17, AC-18)
- [ ] Run verify-spec → coverage matrix's `checklist-item` column maps to the new checklist; drift re-check flags a stale Summary/Checklist; the spec is left unedited → [auto] (AC-19, AC-20)
- [ ] Inspect `.claude/output-styles/<style>.md` → tracked; valid loadable output-style syntax; frontmatter has name + description + `keep-coding-instructions: true`, no force/auto-apply → [auto] (AC-24, AC-25, AC-39)
- [ ] Activate the style and use a session → replies are Northern-register Vietnamese, but written spec/code/commit are English incl. `## Summary`/`## Checklist`; an English spec is explained in Vietnamese with English quoted verbatim; AskUserQuestion options are Vietnamese; code tokens stay English → [human] (AC-26, AC-27, AC-28, AC-29, AC-33, AC-40)
- [ ] Read README/docs → copy-to-`~/.claude` + `/output-style` install steps present, plus the session-start / `/clear` caveat → [auto] (AC-30, AC-31)
- [ ] Inspect `marketplace.json` → spec-ops version bumped (minor) → [auto] (AC-32)
- [ ] Run the spec-ops test suite → green; no test asserts old `## Checklist` semantics; new format/wiring covered → [auto] (AC-34)
