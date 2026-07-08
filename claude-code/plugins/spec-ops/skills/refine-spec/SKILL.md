---
name: refine-spec
description: Review, verify, and tighten an existing feature spec until it is accurate, hallucination-free, not over-engineered, and ready to implement. Use immediately after write-spec, or whenever the user asks to review, fact-check, refine, simplify, de-risk, or finalize a spec / PRD / requirements doc before building. Runs a grounded multi-pass loop that verifies every claim against the codebase, asks the user to resolve open questions, cuts bloat and speculative scope, and stops only when the spec passes an implementation-readiness gate.
argument-hint: [@path/to/spec.md] [focus areas] [--codex-effort xhigh|high|medium]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Edit, Write, Bash, Task
hooks:
  Stop:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/skills/refine-spec/stop_refine_spec.py"
  SubagentStop:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/subagent_validate.py refine"
---

# Refine Spec

Companion to `write-spec`. `write-spec` produces the foundational spec; this skill drives that spec — over **as many passes as it takes** — to a state that is **accurate, grounded, lean, and implementation-ready**, so the user can go straight from here into building. Loop until the readiness gate passes. Do not stop after one pass, and do not start implementing.

Arguments: $ARGUMENTS

## Inputs

- **Spec file** — the path or `@`-mention in the arguments above. If none is given, ask which file with `AskUserQuestion`.
- **Focus areas** — anything else in the arguments the user wants emphasized (e.g. "check the data model", "it feels over-engineered").

Read the spec in full before doing anything. Also read every doc, file, or sibling spec it links or refers to, so you review it in context.

## The loop

Run the five-step pass below repeatedly (step 0 — ingesting any pending `verify-spec` amendments — runs once at the start). Keep looping until a pass produces **no corrections, no open questions, and the readiness gate passes**. Then stop. Announce each pass (e.g. "Pass 2") so the user can follow the convergence.

```
Verify → Reconcile → Resolve → Refine → Re-check ↺
```

### Loop ledger — this loop is enforced, not optional

A **`Stop` hook blocks you from ending your turn** until the spec is genuinely ready, so you cannot quit a pass early. It reads a ledger you maintain at:

`/tmp/claude-refine-spec-${CLAUDE_SESSION_ID}.json`

**At the start of the run, and at the start of every pass,** write the ledger with the `Write` tool (overwrite it each time — that also keeps it fresh so the loop doesn't expire mid-run). **Write strict, valid JSON exactly matching the schema below** — `gate` flags and `resolved` must be JSON booleans (`true`/`false`, not strings), and `spec` must be the correct absolute path. The hook validates the ledger and will block you with a correction message if it is malformed, so a typo can't silently disable the gate:

```json
{
  "spec": "<absolute path to the spec file>",
  "gate": {
    "claims_verified": false,
    "no_open_questions": false,
    "no_overengineering": false,
    "no_bloat": false,
    "implementable_cold": false,
    "ac_complete": false
  },
  "openQuestions": [
    { "q": "short text of an open question you found", "resolved": false }
  ]
}
```

- Add **every** open question you find to `openQuestions`; set its `resolved` to `true` only once the user has given it a disposition — a concrete answer **or** an explicit "leave it / defer".
- Set each `gate` flag to `true` only when that dimension genuinely holds. The five flags map 1:1 to the **Readiness gate** below.
- The hook also scans the spec for leftover `TODO` / `TBD` / `FIXME` / `???` / "to be decided" / "open question" / `[NEEDS CLARIFICATION: …]` — those block the stop too, so don't leave them in the spec.
- **Wait for every dispatch, then write the done-signal last.** On a pass that dispatches grounding `Explore` agents (and, on the readiness pass, the Claude `spec-refine-judge` `Task` + the Codex bridge), don't end the turn or set the `gate` flags / `openQuestions[].resolved` until they have **all returned** and each real result is folded in — one reconciled write, with judge/gate state re-established from **this** pass's results (never a prior pass's flags carried forward). A judge that errors or returns malformed output is re-dispatched or recorded, never counted as a pass. Shared await / foreground / both-judges policy: **`${CLAUDE_PLUGIN_ROOT}/references/cross-model-judge.md`**.

When every flag is `true`, every question is `resolved`, the spec is clean, **and the ready spec is committed** (the hook enforces the commit — scoped to the spec file — see [Handoff](#handoff)), the hook removes the ledger and lets you stop. **If the user redirects to unrelated work, delete the ledger file and stop** instead of continuing to refine.

### 0. Ingest pending verify amendments (once, at the start)

A prior `verify-spec` run may have left **proposed acceptance criteria** — behaviors its backward sweep found in the *implementation* that map to no AC (a missed requirement). They're carried over a `/tmp` handoff so you don't re-key them. At the very start of the run, check for them:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_amendments.py" load <abs-spec-path>
```

- **Empty output → nothing pending.** Proceed to step 1.
- **Findings present → disposition each with the user** via `AskUserQuestion`: an **`intended`** proposal is a confirmed gap → offer to add it as a new `AC-id`; an **`unsure`** one → ask; an **`unintended`** one is *scope-creep in the code to remove*, **not** a spec change → flag it, don't add. Fold every accepted proposal into the **Acceptance Criteria** table as a new criterion (it then gets grounded by the normal loop like any other), then clear the handoff so it can't re-apply:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_amendments.py" clear <abs-spec-path>
```

This closes the **verify→refine loop**: `verify-spec` (read-only) proposes the missed requirement, `refine-spec` (with your confirmation) amends the spec. It never edits the spec on its own.

### 1. Verify — ground every claim against reality

List every **checkable claim** in the spec: file paths, function / class / method names, table / column names, routes, config or env keys, library or framework behavior, "the system currently does X" statements, data shapes, and counts. The **`## Summary`** and **`### For humans`** checklist are **derived human views**, not sources of truth — do **not** enumerate their plain-language prose as independent groundable claims; the AC table and body stay canonical.

Dispatch **parallel `Explore` subagents** (the `Task` tool, `subagent_type: Explore`) to check these claims against **ground truth, never against other docs** — they are read-only and fast. Ground truth, in order of authority:

1. the **actual codebase at branch HEAD**;
2. the **latest git commits** (`git log` / `git diff` on the working branch — specs drift after out-of-band commits and dev→infra merges, so re-ground against HEAD rather than trusting the spec's own history);
3. for infra/ops specs, **live state via the named CLI** (e.g. `aws`, `gh`).

Treat sibling or "completed" specs as **possibly stale — never as ground truth**. Split the claims by area (e.g. one agent per subsystem, model layer, or route group) and scale the agent count to the spec: a short spec may need a single verifier; a large one, several. Give each agent the relevant spec excerpt plus its claim list, and require each to return **strict JSON — one object per claim** — validating the fields before you trust them (never treat a subagent's prose as ground truth; pipe the return through `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_return.py --kind grounder-refine` for a deterministic shape check):

```json
[ { "claim": "…", "verdict": "confirmed | wrong | not-found", "evidence": "file:line / commit SHA / CLI output — with the correct value when wrong" } ]
```

Do not speculate — return `not-found` if a claim cannot be verified.

Run one more agent (or do it yourself) as a **skeptic lens**: read the whole spec hunting for internal contradictions, over-engineering, speculative scope, anything an implementer could not actually act on, and **unstated non-functional constraints the change implies but never pins as an `AC` — performance, security, idempotency, limits, concurrency** (the requirements most often dropped).

**Trace the obvious implementation — hunt the landmines.** Grounding checks the claims that are *present*; this checks the claims that are *absent*. For **each AC**, consider how a competent dev would implement it **the obvious way** and ground-check that path against the codebase for a hidden behavior that **silently breaks it** — an unbound / implicit scope that falls back to the wrong tenant or default, a setting overwritten on save, a **deploy-process gap** (a seeder that doesn't run on deploy where a migration would), a misleading helper or stale doc/comment, a **global-vs-scoped** uniqueness/index mismatch. Dispatch this against ground truth like any other claim — it is **not** answerable from the spec or from the user (only the code knows). Each confirmed trap is a **load-bearing gotcha** to capture in the body as "doing X the obvious way breaks Y"; a trap that forks into a real decision becomes a **Resolve** question. These are the spec's highest-value, most-missed content — a clean-looking spec gives no signal that a trap went unfound, so hunt them deliberately. **Where the obvious path would build on / extend an existing poor pattern**, don't just document-and-entrench it — weigh a **bounded, warranted refactor** against the `(a)(b)(c)` test in **`${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md`**: when it passes, propose the refactor as a bounded `AC` (the *Quality gap / debt-perpetuation* bucket below); when it doesn't, keep the gotcha.

### 2. Reconcile — sort what came back

Dedupe the findings and bucket each one:

| Bucket               | What it is                                                                                                                                                                                                                                                            | Action                    |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| **Inaccuracy**       | Contradicts the codebase                                                                                                                                                                                                                                              | Fix to the verified value |
| **Open question**    | Cannot be verified; needs a human decision                                                                                                                                                                                                                            | Queue for **Resolve**     |
| **Over-engineering** | Speculative, gold-plated, or beyond the stated goal — **including a prescriptive file-by-file construction plan** (symbol-by-symbol decomposition, line anchors, "extract these N helpers") that dictates a HOW a competent dev owns                                          | Propose cutting (keep the gotchas — see Refine). A **warranted** bounded refactor per `quality-bar.md` is **not** over-engineering — don't cut it |
| **Bloat**            | Text not needed to *build* it: historical/background prose, rationale for *why / previously / originally* it got this way, problem statements, changelog, speculative out-of-scope narrative, restated field names, **spec-authoring-process narration** ("verified against the codebase at HEAD", "audited against X", "grounded against the codebase", internal pass names — the contract, not the review), **duplication — classically a plan or section that re-states the Acceptance Criteria** instead of tracing them. **Keep:** decision/config/field tables, the Acceptance Criteria table, **load-bearing failure-mode rationale** — the "doing X the obvious way breaks Y" that stops an implementer applying a wrong fix (tighten it, don't cut it) — and the **two-subsection `## Checklist`**: its `### For humans` walkthroughs are an *intentional* plain-language restatement for hand-verification, **not** bloat or duplication, as long as each verification item traces an `AC-id` and adds no new fact. | Cut                       |
| **Quality gap / debt-perpetuation** | The symmetric counterpart to the two cuts above: a **materially-implied** engineering-quality vertical (architecture-fit, security, performance, scalability, maintainability, error-handling — the full list in `${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md`) with **no `AC`**, **or** the change would extend an existing **poor pattern** where a bounded refactor is **warranted** (the `(a)(b)(c)` test all holds) | Promote a discrete quality / **bounded-refactor `AC`** — but **only when warranted**; unsure ⇒ not warranted, leave it (the same discipline as the cuts, mirrored) |

### 3. Resolve — ask the user

For **every** genuine ambiguity, unverifiable assumption, or open decision that changes *what gets built*, ask the user with `AskUserQuestion`. Batch related questions into one call; ask as many as you need across passes. **It is better to ask one too many questions than to let the spec ship an assumption.** Never guess to fill a gap. Walk dependent decisions in **dependency order** (resolve the upstream fork before the ones that hinge on it) and **lead each question with your recommended answer**. Grill while the answer still changes what gets built — but **stop when the returns diminish**: a cosmetic choice or an implementer's-discretion detail isn't worth a question.

You do **not** need to ask about facts you already verified and corrected against the codebase — fix those directly and note them in the final summary. **Anything you can settle by reading the codebase, settle that way — don't ask the user what the code can already tell you.**

### 4. Refine — edit the spec

Apply, as one coherent edit per pass:

- **Corrections** — replace every inaccuracy with the verified value.
- **Resolutions** — fold in the user's answers.
- **Cuts** — remove over-engineering and bloat.
- **Grounded HOW = gotchas, not a construction plan.** Express implementation grounding as **load-bearing gotchas** — *only* the spots where the obvious approach is silently wrong (the landmines from step 1) — plus any **config-as-contract** value (env key, exact column, migration) that *is* the requirement. Do **not** author a prescriptive **file-by-file construction plan** (symbol-by-symbol decomposition, line anchors, "extract these N helpers"): that dictates a HOW a competent dev owns and rots as the code moves, and the construction HOW is **`launch-spec`'s** job at implement-time, not the stored spec. **Exception:** a pure config-as-contract spec (CDN/WAF/deploy/networking/migration) whose values *are* the spec stays detailed. The result is a spec a human can scan and verify against, not a build script. When you surface gotchas as a block, title it **Watch out for** (or fold each inline under its body section) — never with this skill's internal term ("Landmines") and never with a parenthetical about how you checked them ("verified against the codebase at HEAD", "audited against X"). State the trap; not the audit.
- **Simplification** — tighten so another dev can grasp the objective and the details fast, following the `write-spec` philosophy: say things once, in the right place; describe behavior, not implementation; show with tables / mermaid / examples instead of prose; bold the key terms; every sentence must earn its place.
- **Structural conformance — conform to the rigor's canonical shape.** First determine the spec's rigor (per **`${CLAUDE_PLUGIN_ROOT}/references/spec-format.md`** — an explicit signal, else infer from content; when unsure, the **higher** tier, so a rewrite never strips content on a guess), then **conform the spec to that rigor's canonical section-set and fill-in template**, rewriting any legacy / ad-hoc layout into it. Concretely: confirm the spec opens with a literal **`## TL;DR` section** (2-3 tight bullets leading with any "breaks if missed" — *not* an unlabeled intro paragraph and *not* a `### Breaks if missed` subsection standing in for it), and carries the **Acceptance Criteria** table and a **Boundaries** section where the change has out-of-bounds areas. **At standard/full, also require the human layer:** a **`## Summary`** immediately after the TL;DR and a two-subsection **`## Checklist`** (`### For agents` + `### For humans`) whose coverage is exhaustive — a missing `## Summary` / `## Checklist`, or non-exhaustive checklist coverage, is a structural gap that holds the gate closed (folded into `ac_complete`). **Migrate** a spec in the **legacy flat `## Checklist` shape** (a `code area → AC-id` list with no subsections) into the `### For agents` / `### For humans` form — rewritten, not grandfathered (preserve every substance; diff and surface a `removed:` list if the rewrite condenses a tracked spec). If a draft (often one synthesized from a denser source doc) replaced the TL;DR with prose, restore the section. Also strip any **spec-authoring-process narration** from the prose — "verified against the codebase at HEAD", "audited against X", "grounded against the codebase", internal pass names — the spec states the fact, never how it was checked.
- **Acceptance criteria** — ensure the spec opens with a stable-id'd **Acceptance Criteria** table capturing *every* functional requirement and constraint as a discrete, atomic, testable assertion — **read `${CLAUDE_PLUGIN_ROOT}/references/ac-contract.md`** for the full conventions (the canonical AC contract write-spec and refine-spec share). Promote anything that exists only in prose into a criterion, split compound ones, and confirm each is an observable end-state (not a task). **If the spec carries a Validation, test-plan, or acceptance section, split what it holds:** each *assertion* becomes an `AC-id` in the table; any *verification step* it documents (how to check on staging, what to observe) stays as a lean section that **cites** the `AC-id`s rather than restating them — never leave two parallel sets of assertions. Cross-check coverage **both ways**: every criterion is **traced by ≥1 `## Checklist` item** across the two subsections, and every behavioral rule in the body maps back to an `AC-id`. This table is load-bearing — never cut it as bloat.
- **Acceptance-criteria ordering & grouping** — this is the stage that **commits the grounded group order** the first-draft author couldn't (grouping rules: the same `ac-contract.md` reference). Decide whether the table stays flat or becomes **ordered named groups** (`### 1. <capability> — start here`, `### 2. <capability> — needs §1`), and add a `needs §X` header edge **only for a real dependency you have grounded against the codebase** — never a guessed or scheduling order (`needs §X` is the only *binding* order; group sequence is otherwise a suggested reading order). **No dates, time-boxes, or effort estimates** — order is dependency-derived only. If grouping would exceed **~5–6 groups**, surface it and **distinguish the cause**: a spec **bundling independent changes** → recommend splitting the spec; **one coherent change with real cross-group dependencies** → keep it whole and note that `launch-spec` will **phase the build** by group. The trigger to split is *independence*, not the count.
- **Human layer (`## Summary` + `## Checklist`) — finalize after the ACs stabilize.** At standard/full, once this pass's AC table is settled, reconcile the reading and verification layer. The **`## Summary`** sits immediately after the TL;DR: zero-context, code-free, plain-language, and a **derived view** — it restates the contract for comprehension and adds no fact absent from the AC table, so **do not enumerate its prose as a groundable claim**. The **`## Checklist`** is the final section with `### For agents` (runnable command / test + expected result) and `### For humans` (scenario walkthroughs a non-native-English reader can perform without reading code) subsections. **On any AC added, removed, renamed, merged, or split, reconcile both** — every AC traced by ≥1 checklist item across the two subsections, no stale or orphan item or trace. Do **not** collapse the `### For humans` walkthroughs into a code-area index; that plain-language restatement is intentional. **Migrate legacy:** a spec still carrying a flat `code area → AC-id` `## Checklist` (no `### For agents` / `### For humans` subsections) is **rewritten into the two-subsection form** — migrated, not grandfathered (preserve every substance). Conventions: **`${CLAUDE_PLUGIN_ROOT}/references/ac-contract.md`**; the per-rigor shape + template + conform rule: **`${CLAUDE_PLUGIN_ROOT}/references/spec-format.md`**.
- **Unstated-constraint hunt & completeness probe** — actively look for **quality verticals the change materially implies but never states**: the full set in **`${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md`** (architecture-fit, code design, security, performance, scalability, maintainability/testability, error-handling, observability, backward-compat) — not just perf/security/idempotency/limits/concurrency. Promote each **materially-implied** one into its own `AC-id` — these are the most-dropped requirements, and a capable implementer will silently skip what isn't written. Where the change would **entrench an existing poor pattern**, add a **bounded, warranted refactor `AC`** per that reference's `(a)(b)(c)` test (leave-it-better, kept disciplined so it never becomes gold-plating) — **rigor-gated**: at light/standard express it as an **observable-outcome** AC, never a code-structural refactor AC (full-rigor only). For every *behavioral* AC, run the **completeness probe** — *what initiates this, under what precondition, and what's the observable bound?* — and close any gap it exposes. This is a **prompt for finding holes, not a syntax to impose**: keep each AC a plain testable sentence (no EARS/Gherkin templates, no type tags), and **exempt** pure-math / decision-table criteria and the Boundaries section, which have no stimulus-response shape. Convey meaning over template.
- **Boundaries** — ensure the spec states explicit **Boundaries** (what the implementer must NOT touch) whenever the change has out-of-bounds areas; they are the top anti-drift lever for the implementation run. Add them, or ask, if missing. Keep them change-specific: if a boundary is really a standing project convention (architecture, "don't touch prod") rather than specific to this change, recommend it live in **CLAUDE.md** instead — re-injected every turn, durable across any driver.

**Preserve every detail an implementer needs.** Simplify *wording and structure*, never silently drop substance. If you are unsure whether a detail is load-bearing, ask before cutting it. Keep edits reviewable as a clean git diff.

**Prove no silent loss on a rewrite.** If the spec is already tracked in git and this pass rewrote or heavily condensed it, diff the result against the prior committed version (`git diff`, or `git show HEAD:<path>`) and surface a short **`removed:`** list of any non-bloat content you cut, so the user can veto a wrongful drop. Skip this for a brand-new, untracked spec.

### 5. Re-check — did the edit settle or stir?

Re-read the edited spec. Edits can introduce new claims, new ambiguities, or new contradictions. If the pass changed anything, **loop** and verify again. If a full pass produced no fixes and no questions, evaluate the readiness gate with the independent judge (below) — don't sign off on your own work. Before you try to stop, make the ledger reflect reality — unresolved questions marked, gate flags set only where they truly hold. The `Stop` hook bounces you back here if anything is still open.

## Readiness gate

Finish only when **all** of these hold. Report the gate's status at the end of each pass. Each maps to a ledger flag (in parentheses).

**The agent that did the refining does not get to declare it done.** Before setting any gate flag to `true`, dispatch a fresh **readiness judge** — the **`spec-ops:spec-refine-judge`** agent (the `Task` tool, `subagent_type: spec-ops:spec-refine-judge`) — with no memory of your edits; hand it the current **spec path** plus the six gate criteria below. Its adversarial rubric lives in the agent: read-only, it reads the spec and the codebase and hunts for any remaining inaccuracy, ambiguity, over-engineering, bloat, missing detail, or functional / **unstated non-functional constraint** (performance, security, idempotency, limits, concurrency) not captured in the Acceptance Criteria table as a discrete, testable assertion — classifying each finding `Gap` / `Ambiguity` / `Conflict` and naming the exact `AC-id` for every coverage finding. It returns strict JSON:

```json
{ "perCriterion": [ { "criterion": "claims_verified|no_open_questions|no_overengineering|no_bloat|implementable_cold|ac_complete", "verdict": "PASS|FAIL", "reason": "…" } ], "findings": [...], "overall": "PASS|FAIL" }
```

Validate the shape (`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_return.py --kind judge-refine`); set each `gate` flag `true` only for the criteria the judge `PASS`es; every `FAIL` becomes findings for another pass.

**Cross-model judge — a second, different-provider judge (when available).** So readiness isn't *Claude auditing Claude*, run a second judge of a **different provider** (OpenAI Codex) **alongside** the Claude `spec-refine-judge` — **optional and fail-open**: when Codex is absent / unauthenticated / off / slow / malformed, this is a no-op and the gate is exactly what the Claude judge produced. **Read `${CLAUDE_PLUGIN_ROOT}/references/cross-model-judge.md`** for the shared policy (final-pass-only, **wait-for-every-dispatch-then-write-the-ledger-last**, **synchronous foreground** concurrent dispatch — never background-and-poll, verbatim rubric, **severity-gated** AND-merge, fail-open branching, the **convergence offer**, stubborn-split escalation). refine-spec specifics:

- **Availability — check this first.** Skill-load probe: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --probe --kind judge-refine` — the probe prints one line; if it **shows `CODEX: YES`**, Codex is available — **do the steps below.** (Only the `CODEX: YES` verdict matters; whatever text follows it is an informational reason that may change — ignore it.) Any other line — a `CODEX: NO …` line, blank, or an error / denied result — means unavailable: **skip this whole section** and proceed Claude-only (build no prompt, make no bridge call) **and state in the handoff that the readiness review ran Claude-only**. Fail-open: a missing or denied probe never blocks the readiness gate.
- **Only on the no-fix readiness pass.** Dispatch the Codex judge on the pass where a full pass produced no fixes and you are evaluating the gate — not on earlier editing passes. ~one Codex call per run.
- **Concurrent dispatch.** In the same turn you dispatch the Claude `spec-refine-judge` `Task`, also build the Codex prompt and call the bridge — the rubric file `${CLAUDE_PLUGIN_ROOT}/agents/spec-refine-judge.md` **verbatim**, then the **spec path + repo root** (only those), written to a transient `/tmp` prompt file:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" --kind judge-refine \
    --prompt-file <tmp-prompt> \
    --schema-file "${CLAUDE_PLUGIN_ROOT}/schemas/judge_refine.schema.json" \
    --cd <repo-root> --effort <codex-effort>      # the run's --codex-effort arg, else xhigh
  ```

  The Codex judge runs **read-only** and returns the **identical `judge-refine` contract** over the six criteria, already shape-validated by the bridge on exit 0.
- **Branch on the exit code.** `0` → merge the Codex verdict; **any other outcome** — `10` / `11` / `12`, any other non-zero exit, or the call not running at all (e.g. denied / blocked) → proceed Claude-only, surface the one bridge log line if there is one, change nothing. A Codex call can never hold the gate closed.
- **AND-merge the gate flags.** When a Codex verdict came back, set each `gate` flag `true` **only when both** judges `PASS` that criterion; any criterion **either** model `FAIL`s stays `false` and becomes work for the next pass (union the `findings`). The judge now `FAIL`s a criterion **only on a `CRITICAL` finding** (`WARNING` / `SUGGESTION` are recorded, never gate-holding — see the rubric's severity tiers), so the merge withholds a flag only for a genuinely blocking finding. You are not changing the ledger shape — you are withholding the existing `gate` flags until both judges agree, so `stop_refine_spec.py` and the refine ledger schema stay unchanged.
- **Reiterate Codex's findings to the user — per criterion, every pass.** Before you fold a Codex verdict into the ledger, restate it plainly: for each criterion Codex `FAIL`ed or finding it raised, say *"Codex flagged X (its severity tier); my own judge said Y; my disposition is Z — fix / dismiss-as-noise / escalate."* A Codex-only `FAIL` must never be invisible: surface the split, don't union it silently. This is what makes the convergence easy for the dev to follow pass over pass.
- **Effort is overridable.** Thread the run's `--codex-effort` (parsed from `$ARGUMENTS`) into the bridge's `--effort`; default `xhigh`. The bridge also honors `SPEC_OPS_CODEX_EFFORT` as the env-level default, so a project can downgrade small-spec runs without editing the skill.
- **Stubborn split / convergence → escalate, never deadlock or grind.** If Codex keeps failing a criterion the Claude judge passes and no edit resolves it, escalate per the shared policy (`AskUserQuestion` interactively, or the blocked/handoff return under `orchestrate-spec`). Likewise, once Codex is down to only `WARNING` / `SUGGESTION` findings while the Claude judge passes a criterion across ≥2 passes, take the **convergence offer** (shared policy) — ship / fix / iterate is the user's call, **never** an auto-pass and never another silent loop. The user's disposition resolves the contested flag so the gate can release.

- [ ] Every factual claim is verified against the codebase or confirmed by the user — zero unverified "currently X" statements. (`claims_verified`)
- [ ] No open questions, TBDs, "decide later", `[NEEDS CLARIFICATION]` markers, or contradictions remain anywhere in the spec. (`no_open_questions`)
- [ ] No speculative scope or gold-plating — everything present serves the stated goal; a **prescriptive file-by-file construction plan** is gold-plating (keep grounded HOW as gotchas; config-as-contract excepted). (`no_overengineering`)
- [ ] No text that exists *only* for history or context (the **Bloat** row above) — nothing a builder doesn't need, **including a checklist item that re-states an AC's text instead of tracing it with an `(AC-…)` citation**. The two-subsection `## Checklist` — including its plain-language `### For humans` walkthroughs — is an intentional comprehension aid, not bloat. Decision/config/field **tables**, the AC table, and **load-bearing failure-mode rationale** stay. (`no_bloat`)
- [ ] A developer who has never seen this work could implement it end-to-end without asking a question. (`implementable_cold`)
- [ ] Every functional requirement and constraint is captured in the **Acceptance Criteria** table as a discrete, atomic, testable assertion — nothing load-bearing left only in prose, and every criterion is **traced by ≥1 `## Checklist` item**. **At standard/full the human layer is present and exhaustive:** a `## Summary` and a two-subsection `## Checklist` (`### For agents` + `### For humans`) that together trace every AC — a legacy flat code-area `## Checklist` is **migrated into this form** (`spec-format.md`), not exempt. (`ac_complete`)

## Handoff

When the gate passes, give a short summary: what you corrected, what you cut, and which open questions you resolved (with the user's answers). State plainly that the spec is ready to implement. **Then commit the ready spec** — scoped to that one file:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/spec_git.py" commit <abs-spec-path> "docs(spec): {spec name} ready for implementation"
```

The helper commits **only the spec file** (never `git add -A`, never other staged changes, never a push) and no-ops if it isn't a git repo. The **`Stop` hook enforces this**: while the spec file has uncommitted changes in a git repo it will not let the turn end — so commit *after* your final edit. The hook clears the ledger and releases the stop once the gate passes **and** the spec is committed. **Stop there — do not begin implementation.** To build it, hand the ready spec to **`launch-spec`**, which compiles it into a `/goal` driver; run that, then gate with **`verify-spec`**.

## Guardrails

- **Never invent facts** to fill a gap. Verify it, or ask.
- **Refine, don't redesign.** If you believe the design itself is wrong, raise it as a question — don't unilaterally rewrite the approach. (A **bounded, warranted** refactor `AC` per `${CLAUDE_PLUGIN_ROOT}/references/quality-bar.md` is *not* a redesign — propose it; a change that needs a true rearchitecture is a **question**, not a silent rewrite.)
