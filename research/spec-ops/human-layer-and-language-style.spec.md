# Human-Readable Spec Layer & Vietnamese Output Style Spec

> This spec **dogfoods the format it defines** — it carries the proposed `## Summary` and the new two-subsection `## Checklist` (`### For agents` / `### For humans`), so it doubles as a worked example of what the feature produces.

## TL;DR
- Add a human-reading layer to standard/full specs — a plain-language summary plus a checklist split into an agent list and a human list — and an opt-in Vietnamese chat mode that keeps every artifact in English.
- Breaks if missed: the new `## Checklist` **replaces** the old code-area index — keep every item traced to an `AC-id` and keep the agent items runnable, or verify-spec's coverage mapping and the AI implementer lose traceability (AC-8..AC-14).
- Breaks if missed: the Vietnamese style must separate **conversational language** from **persisted-artifact language**, or Vietnamese leaks into specs and code (AC-32..AC-35).

## Summary

**What this is.** This change adds a human-reading layer to the specs the spec-ops skills produce, and a Vietnamese language mode for the assistant. The specs themselves stay in English.

**Why.** Today's specs are written for AI agents. They are correct, but long and technical. A developer finds them hard to read, and an offshore developer who reads English as a second language finds it harder still. After the code is built, someone must verify the feature by hand. That hand-check is the slowest step, and a person can only verify what they understand.

**What a developer gets.** Every standard and full spec gains two plain-language parts. A short summary at the top explains what the feature does, why it exists, and how it behaves. A checklist at the end is split in two: one list of automated checks that an AI agent or CI runs, and one list of manual steps a person follows to check the feature by hand. Separately, an optional language mode lets the assistant talk to the developer in Vietnamese while it still writes every file in English.

**What is out of scope.** Existing specs are left as they are. Spec files are never translated. The output style is opt-in and is not bundled into the plugin.

---

## Acceptance Criteria

<!-- Grouped as a "what am I building" map. AC-ids are globally unique and stable across groups. No build order / `needs §X` asserted here — refine-spec commits those after grounding. -->

### 1. `## TL;DR` and `## Summary` — the reading layer at the top

| AC  | Criterion                                                                                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | The spec skeleton keeps `## TL;DR` and adds `## Summary` immediately after it; both are present at standard / full and absent at `light`.                                                                |
| 2   | `## TL;DR` is the terse top layer: a one-line identifier of the change plus the single most important "breaks if missed" constraint or failure mode (pointing at the relevant `AC-id`s) — not a mini-summary. |
| 3   | `## Summary` is zero-context onboarding for a human (dev / QA), in this order: a one-sentence definition of what it is → the problem / why → the key behaviors a user or admin can do → what is explicitly out of scope. |
| 4   | `## TL;DR` and `## Summary` sit at different altitudes and do not copy-paste each other; each reads correctly on its own.                                                                                |
| 5   | `## Summary` prose is code-free — no file paths, function / class, table / column, or config-key names — even at full rigor; technical detail stays in the body and AC table.                            |
| 6   | `## Summary` is a derived human view, not a source of truth: the `## Acceptance Criteria` table stays canonical, and refine-spec / verify-spec do not treat Summary prose as an independent groundable claim. |
| 7   | The human layer (`## Summary` and `### For humans`) follows plain-language rules for a non-native English reader: short single-idea sentences, active voice, present tense, one term per concept, no idioms or phrasal verbs, and UI labels quoted verbatim. |

### 2. `## Checklist` — split into `### For agents` and `### For humans`

| AC  | Criterion                                                                                                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 8   | The format defines exactly one checklist section, named `## Checklist` (name unchanged), as the final section, containing two subsections — `### For agents` and `### For humans`. No inline per-item human / auto tags, and no second checklist section anywhere. |
| 9   | The split is by kind of check: `### For agents` holds checks whose observation and pass / fail rule are both runnable by an agent / CI (a command, a test, a static read); `### For humans` holds checks needing human judgment (UI clickthrough, visual, UX, logic review). |
| 10  | `### For agents` items are terse and runnable: each names the exact command or test and its expected result.                                                                                          |
| 11  | `### For humans` items are scenario walkthroughs in read-then-do form — a setup / precondition where needed, one observable action, and the expected observable result — phrased so a zero-context, non-native-English reader can perform them without reading code. |
| 12  | Each checklist item ends with a parenthetical `AC-id` trace; a criterion that is part agent-checkable and part human-judgment appears in both subsections, with the human one marked `(partial)`.      |
| 13  | Every `AC-id` cited in a trace references an existing criterion (no orphan / unknown ids); every AC (at standard / full) is traced by at least one checklist item — coverage is exhaustive across the two subsections. |
| 14  | A checklist item verifies an existing AC and never introduces a requirement, value, or success criterion absent from the AC table — it is not the sole home of any fact.                              |

### 3. The `### For humans` structure — manual-verification depth

| AC  | Criterion                                                                                                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 15  | `### For humans` groups its checks under user-facing capabilities / flows (about 5–9 checks per group), not as one flat list.                                                                         |
| 16  | `### For humans` opens with the critical happy-path ("smoke") checks — the "does it even work" path — and includes the required empty / edge / error cases the spec calls for, not happy-path only.    |
| 17  | `### For humans` ends with an "Explore on your own" block that sends the verifier *past* the scripted checks — a short list of open scenarios to try plus a short list of test ideas to vary (e.g. data values, boundaries, create / read / update / delete, interruptions, roles / devices) — and it restates no scripted check. |
| 18  | `### For humans` closes with a sign-off checklist of exit conditions (for example: all checks pass, exploration done, no open critical defects).                                                       |
| 19  | Any setup the human checks need (role, state, test data, where to look) is stated in plain placeholders; performing the section never requires reading the codebase.                                   |
| 20  | Rigor scaling for `## Checklist`: absent at `light`; at `standard` a lean form (`### For agents` + a lean `### For humans` of capability checks and a short explore prompt); at `full` the complete structure (smoke + grouped capability checks + full explore block + sign-off). |

### 4. Skill & contract wiring

| AC  | Criterion                                                                                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 21  | write-spec drafts the `## Summary` and the two-subsection `## Checklist` for standard / full specs.                                                                                                     |
| 22  | refine-spec finalizes the `## Summary` and `## Checklist` after the ACs stabilize and reconciles them on any AC added, removed, renamed, merged, or split — every AC traced; no stale or orphan items or traces. |
| 23  | refine-spec's readiness gate blocks Stop when, at standard / full, the `## Summary` or `## Checklist` is missing or checklist coverage is non-exhaustive.                                                |
| 24  | The refine readiness judge (`spec-refine-judge`) verdict includes a flag asserting the human layer (Summary + both checklist subsections, exhaustive coverage) is present and consistent at standard / full. |
| 25  | verify-spec's coverage-matrix `checklist-item` column maps each `AC-id` to its `## Checklist` item(s) across both subsections, and no longer references a code-area index.                               |
| 26  | verify-spec's drift re-check flags (report-only) a stale `## Summary` / `## Checklist`, invalid or orphan AC traces, duplicate or conflicting coverage, and any checklist item matching no AC; verify-spec stays read-only and edits nothing. |
| 27  | `references/ac-contract.md` documents the new `## Checklist` (two subsections, scenario vs runnable phrasing, AC-id trace, exhaustive coverage, and the `### For humans` structure) and no longer describes a code-area → AC-id index. |
| 28  | write-spec's Writing Philosophy / "say things once" guidance is updated to match the new `## Checklist`; the human layer is an intentional comprehension restatement, exempt from "say things once" as long as it adds no new fact. |
| 29  | The spec-ops README documents `## TL;DR` + `## Summary` and the two-subsection `## Checklist`.                                                                                                          |

### 5. Vietnamese output style

| AC  | Criterion                                                                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 30  | A Vietnamese output style file exists at this repo's `.claude/output-styles/` directory, is tracked in git, and is valid, loadable Claude Code output-style syntax.                                                       |
| 31  | The style's frontmatter sets a descriptive `name`, a `description`, and `keep-coding-instructions: true`, and omits `force-for-plugin` (and any auto-apply) so it is opt-in via `/output-style`.                          |
| 32  | The style instructs Claude to respond to the user in Vietnamese (all conversational prose, explanations, questions) while writing ALL artifacts in English — code, comments, identifiers, file / branch names, commit messages, documentation, config, and every spec section including `## Summary` and `## Checklist`. |
| 33  | The style instructs that when explaining an English spec / checklist, Claude explains in Vietnamese but quotes the English text verbatim — it does not translate the artifact in place.                                   |
| 34  | The style instructs that AskUserQuestion prompts and options render in Vietnamese, while any text written into files stays English.                                                                                       |
| 35  | The style instructs that technical terms and code tokens remain English even within Vietnamese prose, and specifies the Northern (Hà Nội) Vietnamese register.                                                          |

### 6. Distribution, versioning & scope

| AC  | Criterion                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 36  | The repo README (and / or a dedicated docs note) documents installing the style: copy the file to `~/.claude/output-styles/`, activate it via `/output-style`, note it is optional and changes no persisted artifact's language, and state that an output style loads at session start so switching it needs `/clear` or a restart. |
| 37  | The spec-ops plugin version in `.claude-plugin/marketplace.json` is bumped (minor).                                                                                                              |
| 38  | All spec files and the human layer remain entirely in English — no spec content is translated into Vietnamese.                                                                                    |
| 39  | The new format applies only to specs authored under the updated write-spec; refine-spec does not rewrite a pre-existing legacy code-area `## Checklist`, and verify-spec does not flag legacy specs as non-compliant. |
| 40  | The spec-ops test suite is updated so no test asserts the old code-area-index or inline-tag `## Checklist` semantics, and the new format / wiring is covered — including light / standard / full rigor behavior; the suite passes. |

---

## Current state → Target

| Aspect                | Today                                                                              | Target                                                                                                                       |
| --------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Top-of-spec reading   | `## TL;DR` only (terse).                                                           | `## TL;DR` (one-line identifier + breaks-if-missed) **and** `## Summary` (zero-context onboarding) at two distinct altitudes. |
| `## Checklist` meaning | Optional, full-only, thin **code-area → AC-id index** for the implementer.        | The **single** checklist, split into `### For agents` (runnable) and `### For humans` (manual), each item traced to an AC-id. |
| Human verification    | verify-spec automates grounding; no human walkthrough artifact.                   | `### For humans` is a grouped, scenario-based, explore-enabled manual sign-off list; verify-spec maps and drift-checks it.    |
| Language for the team | Specs English; no localized interaction.                                          | Specs stay English; a standalone opt-in output style makes Claude converse in Vietnamese while keeping all artifacts English. |

---

## The reading layer — content rules

**`## TL;DR`** stays 2–3 short lines: the one-line "what is this change," then the single "breaks if missed" risk pointing at its `AC-id`s. It is the fast re-orientation for a reader (or agent) that needs the hardest constraint immediately — never a condensed Summary.

**`## Summary`** is for a person with zero prior context. Keep it short (3 small paragraphs / 4–8 sentences), code-free, and in order: **what it is → why → key behaviors → out of scope**. It restates for comprehension; it adds no requirement that isn't in the AC table and is never the sole home of a fact.

**Plain-language rules** for `## Summary` and `### For humans` (the offshore reader's parts): one idea per sentence (~20 words max); active voice; present tense; the **same term every time** for one concept; spell out acronyms once; no idioms, phrasal verbs, or contractions; quote UI labels (and screen / button names) **verbatim**; say *where* before *what* in a step.

## The checklist — two subsections

One `## Checklist` section, final in the spec, with two subsections distinguished by **the kind of check**:

```markdown
## Checklist

### For agents
<!-- Runnable by an agent or CI: a command, a test, a static read. Terse + the expected result. -->
- [ ] {exact command or test} → {expected result} (AC-3)

### For humans
<!-- A person must look and judge. Read the line, do it, confirm what you see. Plain language. -->

**Setup:** {role / state / test data / where to look — plain placeholders}

**{Capability or flow — ~5–9 checks, smoke/happy-path first}**
- [ ] {observable action} → {expected observable result} (AC-2, AC-5)
- [ ] (empty case) {action} → {expected result} (AC-6)
- [ ] (error case) {action} → {expected result} (AC-6)

**Explore on your own** — go past the checks above and report anything that looks wrong; the goal is to find what they did not. (Never restate a scripted check here.)
- **Scenarios to try:**
  - {an open scenario tailored to this feature's risk areas}
  - {another}
- **Test ideas** (apply to any field or action): empty · very long · 0 / huge / negative · emoji & accents · just over a limit · create / read / update / delete · refresh / Back / double-click / lose network / timeout · a different role · small screen

**Sign-off**
- [ ] All `### For agents` checks pass
- [ ] All `### For humans` checks pass
- [ ] Explored past the checklist; anything wrong is reported
- [ ] No open critical problems
```

- **Trace, don't re-describe.** Each item ends with `(AC-…)` citing only existing ids; the criterion text already lives in the AC table.
- **Partial checks live in both.** A criterion that is part machine-checkable, part human-judgment gets a `### For agents` line for the machine part and a `### For humans` line marked `(partial)` for the judgment part.
- **Coverage is exhaustive** across the two subsections: every AC is traced by ≥1 item. One item may cover several closely-related ACs; one AC may need several items.
- **Explore complements, never repeats.** The "Explore on your own" block lists only what the scripted checks deliberately leave open — if an item would restate a scripted check, drop it. Push genuinely open-ended or subjective checks *into* Explore rather than bloating the scripted list.

## Vietnamese output style — behavior contract

A single standalone style file at `.claude/output-styles/` (repo-tracked), opt-in. Its instruction body must establish, unambiguously:

- **Converse in Vietnamese** — every response to the user: prose, explanations, status, and `AskUserQuestion` prompts / options.
- **Write every artifact in English** — code, comments, identifiers, file and branch names, commit messages, documentation, config, and all spec content (including `## Summary` and `## Checklist`).
- **Explain, don't translate** — when walking the user through an English spec or checklist, explain in Vietnamese but quote the English text verbatim; never rewrite the artifact into Vietnamese.
- **Keep code tokens English** — technical terms, API names, and code stay English even inside Vietnamese prose.
- **Register: Northern (Hà Nội) Vietnamese** — phrasing and vocabulary throughout, including AskUserQuestion options.
- `keep-coding-instructions: true`; no force / auto-apply. The file must be valid, loadable output-style syntax — selecting it must not error or strip Claude Code's coding behavior.

## Watch out for

- **Output styles load at session start.** Selecting a different style mid-session via `/config` does not take effect until `/clear` or restart — the install doc must say so (AC-36).
- **Subagents are unaffected by output styles.** The spec-ops judges run with their own system prompts, so their JSON return contracts stay English regardless of the active style — no special handling needed, but don't rely on the style to localize subagent output.
- **AC-id traces belong in the spec, not in shipped code.** The existing artifact-hygiene sweep strips AC-id citations from *built* artifacts; the `## Checklist`'s traces live in the spec, which is allowed to carry them — keep the two scopes distinct.
- **The `## Checklist` heading is reused with a new meaning.** Pre-change specs keep the old code-area index under the same heading (left alone, per Boundaries). Tell the difference by shape: new checklists have `### For agents` / `### For humans` subsections; legacy ones are a flat "code area → AC-id" list. `ac-contract.md` / README must make the new meaning unambiguous so the reuse doesn't confuse readers of mixed-age specs.
- **Label by the check, not perfectly by the person.** The subsections are named `### For agents` / `### For humans`, but a part-automatable criterion legitimately appears in both — don't force every AC into exactly one subsection.

## Boundaries

- The output style is **standalone** — do **not** bundle it into the spec-ops plugin's `output-styles/` directory or declare it in `plugin.json`.
- The style must stay **opt-in** — do **not** set `force-for-plugin: true` or any auto-apply.
- Do **not** translate any written artifact (spec, code, commit, docs) into Vietnamese — English only.
- Do **not** add a `version` field to `plugin.json`; the version lives only in `marketplace.json`.
- **Leave existing checklists alone.** The new format applies only to specs authored under the updated write-spec. refine-spec does **not** rewrite a pre-existing legacy code-area `## Checklist`, and verify-spec does **not** flag legacy specs as non-compliant. Updating example fixtures under `research/spec-ops/testing/` is optional dogfooding, not required.
- `light`-rigor output is unchanged (AC-table-only) — do **not** add `## Summary` / `## Checklist` at `light`.
- Keep verify-spec **read-only** — it reports human-layer staleness, it never edits the spec.

## Checklist

### For agents
- [ ] `grep` the write-spec skeleton + rigor table → `## Summary` appears immediately after `## TL;DR`; `light` omits both Summary and Checklist, `standard` is lean, `full` is complete → (AC-1, AC-20)
- [ ] `grep` a generated `## TL;DR` → ≤3 short bullets; it leads with the change plus a "breaks if missed" `AC-id` pointer and is not a copy of the Summary → (AC-2, AC-4)
- [ ] `grep` the write-spec skeleton + ac-contract → `## Checklist` is the final section with `### For agents` and `### For humans` subsections and no inline human/auto tags → (AC-8, AC-27)
- [ ] Read ac-contract.md, write-spec philosophy, and README → no code-area-index description remains; the two-subsection semantics + the `### For humans` structure are documented → (AC-27, AC-28, AC-29)
- [ ] Inspect refine/verify logic → the `## Summary` is treated as a derived view: its prose is not enumerated as a groundable claim, and the AC table stays canonical → (AC-6)
- [ ] Inspect a generated standard/full spec → every AC is traced by ≥1 checklist item, every cited AC-id exists, no item introduces a fact absent from the AC table, partial checks appear in both subsections → (AC-12, AC-13, AC-14)
- [ ] Inspect a generated `## Checklist` → `### For agents` items each name a runnable command or test + expected result; `### For humans` items need human judgment (no runnable command) → (AC-9, AC-10)
- [ ] Inspect a full `### For humans` section → checks are grouped by capability and smoke-first, the required empty/edge/error cases are present, and it ends with an "Explore on your own" block (scenarios + test ideas, no restated checks) and a sign-off list → (AC-15, AC-16, AC-17, AC-18)
- [ ] Run write-spec on a feature → the draft already carries the `## Summary` and the two-subsection `## Checklist` → (AC-21)
- [ ] Run verify-spec on a finished spec → its coverage matrix `checklist-item` column maps each AC to the new checklist items across both subsections → (AC-25)
- [ ] Introduce a stale/orphan checklist trace, run verify-spec → it flags the stale Summary/Checklist, the invalid trace, and any unmatched item, and edits nothing → (AC-26)
- [ ] Run refine-spec on a legacy spec whose `## Checklist` is a flat code-area→AC-id list → the legacy checklist is left unchanged and verify-spec does not mark it non-compliant → (AC-39)
- [ ] Inspect `.claude/output-styles/<style>.md` → tracked; valid loadable syntax; frontmatter has name + description + `keep-coding-instructions: true`; no force/auto-apply → (AC-30, AC-31)
- [ ] Read README/docs → install steps (copy to `~/.claude/output-styles/`, `/output-style`), the "optional, changes no artifact's language" note, and the session-start/`/clear` caveat are present → (AC-36)
- [ ] `python3 -m json.tool .claude-plugin/marketplace.json` and read the spec-ops version → valid JSON; version bumped (minor) → (AC-37)
- [ ] Run the spec-ops test suite → green; no test asserts old code-area-index or inline-tag semantics; light/standard/full behavior covered → (AC-40)

### For humans

**Setup:** Install the updated spec-ops plugin locally. Have a small real feature idea ready to spec, and a scratch git repo to write into.

**Understand a generated spec**
- [ ] Generate a `standard` spec for your idea, then read only its `## Summary` → you can say what the feature does, why, and what is out of scope, without reading the rest → (AC-3, AC-5)
- [ ] Read the `## Summary` and `### For humans` checklist as an English-as-second-language reader → sentences are short and active, one term is used per concept, UI labels are quoted exactly, and there are no idioms → (AC-7)

**Verify a feature by hand**
- [ ] On a `full` spec for a real feature, follow two or three `### For humans` checks against the running feature → you can complete each step without opening the code, and what you see matches the stated result → (AC-11, AC-16, AC-19)

**Run the gate**
- [ ] Add, rename, then remove an AC and run refine-spec → the `## Summary` and `## Checklist` update to match, with no leftover traces → (AC-22)
- [ ] At `standard`/`full`, delete a `### For humans` group or the `## Summary`, then run refine-spec → it does not finish; it reports the missing human layer → (AC-23, AC-24)

**Vietnamese session**
- [ ] Select the Vietnamese style, run `/clear`, then ask a question → the reply is Northern-register Vietnamese → (AC-32, AC-35)
- [ ] Ask Claude to write or update a spec → the saved file is English, including the `## Summary` and `## Checklist` → (AC-32, AC-38)
- [ ] Ask Claude to explain the spec → it explains in Vietnamese and quotes the English text exactly; code tokens stay English → (AC-33, AC-35)
- [ ] Answer an `AskUserQuestion` it raises → the prompt and options are in Vietnamese → (AC-34)

**Explore on your own** — go past the checks above and report anything that looks wrong; the goal is to find what these checks did not.
- **Scenarios to try:**
  - Spec two very different features (a one-AC tweak and a multi-capability feature) and judge whether the Summary and `### For humans` checklist stay clear and useful at both sizes.
  - In a Vietnamese session, mix requests fast — write code, then a doc, then ask a question, then switch styles without `/clear` — and watch for any place a language goes the wrong way.
- **Test ideas:** a feature with no edge cases vs. many · an AC that is only human-verifiable vs. only machine-verifiable · grouped vs. flat ACs · a spec at each rigor.

**Sign-off**
- [ ] All `### For agents` checks pass
- [ ] All `### For humans` checks pass
- [ ] Explored past the checklist; anything wrong is reported
- [ ] No open critical problems
