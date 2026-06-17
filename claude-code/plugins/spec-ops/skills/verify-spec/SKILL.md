---
name: verify-spec
description: Verify that an implementation, change, or audit result actually matches the claims made about it — grounded against the real codebase, git history, and live read-only system state, never against the spec or any doc. It does NOT check the spec document (that is refine-spec's job); it checks whether reality matches what the spec/audit/summary claims. Use this after implementing a spec, after a review/audit, or whenever the user asks "is this actually done / correct / true?" and wants every "we did X" / "the system does Y" claim confirmed against reality. Runs a grounded multi-pass loop that enumerates every checkable claim, verifies each against ground truth with cited evidence, has a fresh judge confirm completeness, and reports discrepancies — without editing code.
argument-hint: [what to verify: @spec.md | a PR/commit range | a claim] [focus areas]
model: opus
effort: xhigh
allowed-tools: Read, Grep, Glob, Bash, Write, Task
hooks:
  Stop:
    - hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/skills/verify-spec/stop_verify_spec.py"
---

# Verify Spec

Fourth companion to `write-spec`, `refine-spec`, and `launch-spec`. `write-spec` drafts the spec; `refine-spec` verifies and tightens the **spec document**; `launch-spec` compiles the ready spec into a `/goal` driver that implements it; `verify-spec` verifies **reality against the claims** — whatever asserts them (a spec, an audit, or your own summary). It confirms that what was actually built (the committed code, the live system) matches what was claimed, grounding every claim in real source. It runs over **as many passes as it takes** until every claim has a definitive, evidence-backed verdict and a fresh judge agrees the verification is complete. **It edits nothing** — not code, not the spec — it grounds claims, reports discrepancies, and stops. Do not stop after one pass, and do not start fixing things unless the user asks.

Arguments: $ARGUMENTS

## Inputs

- **What to verify** — the path / `@`-mention, PR / commit range, feature, or claim in the arguments. If none is given, ask with `AskUserQuestion`: what work or claim should I verify, and against which branch / commit? (That named branch / commit is the HEAD you ground against.)
- **Focus areas** — anything to emphasize (e.g. "just the migration", "the IAM changes").

**The thing under review is the hypothesis, not the evidence.** A spec, audit, checklist, or prior summary is exactly what you are CHECKING — never what you check against. Ground every claim against the **actual codebase at branch HEAD, the git history, and (for infra/ops) live read-only system state.** Read the target in full first; if you are verifying a spec's implementation, read the spec to extract its claims, but treat it as a list of things to prove, not a source of truth.

## The loop

Run the pass below repeatedly until every enumerated claim has a definitive, evidence-cited verdict and the independent judge attests the verification is complete. Then stop. Announce each pass (e.g. "Pass 2").

```
Enumerate → Verify → Reconcile → Judge → Re-check ↺
```

### Loop ledger — this loop is enforced, not optional

A **`Stop` hook blocks you from ending your turn** until the ledger shows a structurally complete, judge-signed verification, so you cannot sign off after a shallow pass. It reads a ledger you maintain at:

`/tmp/claude-verify-spec-${CLAUDE_SESSION_ID}.json`

**At the start of the run, and whenever a verdict or the judge result changes,** write the ledger with the `Write` tool (overwrite it each time — that also keeps it fresh so the loop doesn't expire mid-run). **Write strict, valid JSON exactly matching the schema below**, using the **live session id** in the path (an un-expanded `${CLAUDE_SESSION_ID}` literal would land the ledger where the hook can't see it and silently disable the gate). The hook validates it and blocks you with a correction message if it is malformed. **The `/tmp` ledger is the ONLY file you may write — never edit code, the spec, or any repo file.**

```json
{
  "target": "<what you are verifying — a path, feature, or commit range>",
  "claims": [
    {
      "claim": "short text of one checkable claim",
      "verdict": "unchecked",
      "evidence": "",
      "disposition": ""
    }
  ],
  "judge": {
    "ran": false,
    "verdict": "pending",
    "missed": [],
    "weakEvidence": []
  },
  "backwardSweep": {
    "ran": false,
    "base": "",
    "skippedReason": "",
    "findings": [
      {
        "hunk": "file:line / path of a substantive change mapping to NO acceptance criterion",
        "evidence": "git sha / file:line proving the change",
        "disposition": "intended | unintended | unsure",
        "proposedAC": "candidate AC text for the behavior this hunk introduces"
      }
    ]
  }
}
```

- `verdict` is one of: `unchecked` (not yet verified) · `confirmed` (true — `evidence` must cite the source) · `contradicted` (false — `evidence` must cite the source and state the actual value) · `unverifiable` (cannot be grounded — `disposition` must record the user's call).
- `evidence` must be **concrete ground truth**: a `file:line`, a `git show <sha>` hunk, or read-only CLI output. **Never** the spec, an audit, a checklist, or your own prior output.
- `judge` records the independent judge's result (step 4): `ran` true once it has run, `verdict` one of `pending` / `gaps` / `complete`, `missed` = checkable claims it found were absent from the ledger, `weakEvidence` = confirmed/contradicted claims whose evidence it found hollow, stale, or doc-based.
- `backwardSweep` records the **backward-coverage pass** (step 2's backward direction): `ran` true once it has run, `base` the diff base swept, `skippedReason` why it was skipped (if it was — e.g. no determinable base when running autonomously), and `findings` the substantive hunks that map to **no** `AC-id`. Findings are **report-only — they never block the stop** (exactly like `contradicted` claims). Omit `backwardSweep` entirely when the target is not a spec implementation with a diff to walk.

**What the hook enforces vs. what you own.** The hook mechanically requires: no claim left `unchecked`; every `confirmed`/`contradicted` claim cites non-empty `evidence`; every `unverifiable` claim has a `disposition`; and the judge `ran` with `verdict: "complete"` and empty `missed`/`weakEvidence`. It **cannot** see whether you enumerated every claim or whether a citation is genuine — **that is the judge's job**, which is why the judge's sign-off is itself gated. The hook is a backstop against a shallow stop, not a substitute for an honest verification. `contradicted` claims do **not** block the stop — they are the findings you report; **`backwardSweep.findings` are the same — reported, never gate-blockers** (the hook shape-validates the field but never gates on it; the judge attests the sweep actually ran). **If the user redirects to unrelated work, delete the ledger file and stop.**

### 1. Enumerate — list every checkable claim

From the target, extract every **checkable assertion** as a discrete claim: "added X", "removed Y", "the system now does Z", "endpoint A returns B", "table / column / route / config exists", "resource is named N", counts, and every "currently / now X" statement. Add them all to the ledger as `unchecked`. Be exhaustive — an unenumerated claim is an unverified claim, and missing one is worse than a slow pass.

**If the target is a spec with an `## Acceptance Criteria` section, seed the ledger with every `AC-id` as a claim first** — each criterion is the contract the implementation is judged against, so a missing `AC-id` is the worst kind of missed claim. Carry the `AC-id` in the claim text. Then add any other checkable claims from the body. A criterion that grounds out `contradicted` is the exact "requirement built wrong / not built" finding this gate exists to surface. If the target genuinely has **no checkable claims**, say so plainly and stop (record one `unverifiable` claim noting that, dispositioned "no checkable claims in target") — don't invent claims to fill the ledger.

### 2. Verify — ground each claim against reality

Dispatch **parallel `Explore` subagents** (the `Task` tool, `subagent_type: Explore`) to ground the claims — they are read-only and fast. Split the claims by area and scale the agent count to the size of the work. Require, for every claim, a verdict **with cited ground-truth evidence**:

> For each claim return `confirmed` / `contradicted` (state the actual value) / `unverifiable`, and cite the evidence: a `file:line`, a `git show <sha>` / `git diff` hunk, or read-only CLI output. You are **forbidden from citing the spec, an audit, a checklist, or any doc as evidence** — only real source. If you cannot ground it, return `unverifiable` and say why. Do not speculate.

Ground truth, in order of authority: the **codebase at branch HEAD**; the **git history** (`git log` / `git diff` / `git show` on the working branch — re-ground against HEAD, since claims drift after out-of-band commits and merges); and, for infra / ops claims, **live state via read-only CLI** (e.g. `aws … describe/list/get`, `gh api`).

#### Backward sweep — delivered code that owns no AC (report-only)

The claim grounding above is the *forward* direction (every claim/`AC-id` has evidence). When the target is a spec with an `## Acceptance Criteria` section, **also run the backward direction**: every substantive change in the implementation diff should map to an owning `AC-id`. A hunk that maps to **none** is the finding this pass exists to surface — scope creep, silent reinterpretation, or a *derived requirement* (a real behavior built with no criterion). The forward judge can't see it, because it re-derives ACs forward and never looks at code with no AC.

- **Diff base.** Sweep the implementation diff. If you were handed an explicit PR / commit range, *that* is the diff. Otherwise diff the working branch against its merge-base with the trunk — `git merge-base HEAD main` then `git diff <base>..HEAD`; when you are **on** the trunk, diff against the upstream instead (`git diff origin/main..HEAD` — the unpushed commits). Record the base used in `backwardSweep.base`. If no base is determinable: on **direct human invocation**, ask with `AskUserQuestion`; running **autonomously as the `/goal` done-gate**, set `backwardSweep.skippedReason` and proceed — **never block on it**.
- **Substantive only — noise filter.** A finding must be a **behavior-bearing** hunk with no owning AC: new behavior, a branch, an endpoint, a handler, persisted state, an external call, or a user-observable change. **Allowlist — never a finding:** refactors, formatting, tests, CI, config churn, and docs. For a manifest, **split by field** — `description` / `version` edits are docs (allowlist); `dependency` / `entrypoint` / `script` / `permission` edits are substantive. Docs or config that an AC *explicitly governs* (e.g. an AC "the README documents X") are **not** a backward finding — that artifact's coverage is a *forward* concern, checked as its own claim.
- **Report, propose, triage — never act.** For each unmapped substantive hunk, add an entry to `backwardSweep.findings` with its `evidence`, propose candidate AC text (`proposedAC`), and triage `disposition`: `intended` (→ "add this AC and re-run `refine-spec`") vs `unintended` (→ "remove or justify") vs `unsure`. This is **always a non-blocking report** — it never holds the gate, you **edit nothing**, and you never auto-reopen `refine-spec`. On direct human invocation you *may* use `AskUserQuestion` to confirm an ambiguous intent, but **never as a gate dependency** (the autonomous done-gate has no human to ask).

### 3. Reconcile — record verdicts and discrepancies

Update each claim's verdict + evidence in the ledger. For every `contradicted` claim, capture a precise discrepancy: **claim → expected → actual → evidence** (`file:line` / sha / CLI). For an `unverifiable` claim, dig further; if it genuinely can't be grounded (e.g. it depends on runtime state you can't observe), ask the user with `AskUserQuestion` and record their `disposition`. If many claims come back `unverifiable`, batch the dispositions into one `AskUserQuestion` rather than asking per claim. Never guess a verdict to clear the gate.

Also write the **backward sweep** into the ledger's `backwardSweep`: set `ran` true, record the `base` swept (or `skippedReason`), and list every unmapped substantive hunk in `findings`. These are reported, never blockers, and never edited away.

### 4. Judge — an independent agent confirms completeness

**The agent that did the verifying does not get to declare it complete.** Before you try to stop, dispatch a fresh **verification judge** — an independent `Task` subagent (`subagent_type: Explore`, so it can re-check source read-only) with **no memory of your passes**; hand it only the **target and the ledger**, not your reasoning. Instruct it to be adversarial: *independently re-derive the checkable claims from the target and (a) list any that are missing from the ledger (`missed`) — and if the target has an Acceptance Criteria section, confirm **every `AC-id` appears as a claim**, treating any absent one as `missed`; (b) list any `confirmed`/`contradicted` claim whose cited evidence is hollow, stale, or doc-based rather than real source (`weakEvidence`); and (c) return `verdict: "complete"` only if both lists are empty, else `"gaps"`.* Write its result into the ledger's `judge` field. Every entry in `missed`/`weakEvidence` becomes another pass.

**Also have the judge attest the backward sweep** (when the target is a spec implementation): that `backwardSweep.ran` is honest — it actually walked the diff against the right base, or recorded a legitimate `skippedReason` — and that no obviously substantive hunk was left out of `findings`. A backward gap the judge spots (an unmapped hunk that should have been a finding) is its own pass; but the **findings themselves never block** `verdict: "complete"` — they are reports, not unresolved claims.

### 5. Re-check — settle or loop

If the judge reported `gaps`, **loop**: enumerate the `missed` claims, re-ground the `weakEvidence` ones, then re-run the judge. Before stopping, make the ledger reflect reality — every claim verdicted, every verdict cited, every `unverifiable` dispositioned, and the judge `complete`. The `Stop` hook bounces you back here if anything is still `unchecked`, uncited, undispositioned, or the judge hasn't signed off.

## Completion gate

Finish only when **all** of these hold (the first four + the judge sign-off are hook-enforced; enumeration completeness and evidence authenticity are what the judge attests):

- [ ] Every checkable claim is enumerated in the ledger — none missed. If the target has acceptance criteria, **every `AC-id` is present as a claim** with a grounded verdict (a `contradicted` AC is a finding to report, not a blocker).
- [ ] Every claim has a definitive verdict — none `unchecked`.
- [ ] Every `confirmed` / `contradicted` verdict cites concrete ground-truth evidence (`file:line` / `git sha` / read-only CLI), never a doc.
- [ ] Every `unverifiable` claim carries an explicit user disposition.
- [ ] The independent judge ran and returned `complete` — no missed claims, no weak / doc-based evidence.
- [ ] If the target is a spec implementation, the **backward sweep** ran against the right diff base (or recorded why it was skipped), and every unmapped substantive hunk is reported in `backwardSweep.findings`. These are reports, never gate-blockers (judge-attested, not hook-enforced).

## Handoff

When the gate passes, report a **per-claim verdict table** — `claim | verdict | evidence (file:line / sha / CLI)` — plus a short discrepancy summary for every `contradicted` claim (expected vs actual). State plainly how many claims were confirmed vs contradicted vs unverifiable. If the backward sweep ran, add a short **backward-coverage** section listing every unmapped substantive hunk with its proposed AC and triage (`intended` / `unintended` / `unsure`), or state "every change maps to an AC" when it found nothing (and note it if the sweep was skipped, with the reason). **Stop there — do not fix the discrepancies** unless the user asks; surfacing them is the deliverable (enumerate, then let the user decide). The `Stop` hook clears the ledger automatically once the gate passes.

## Guardrails

- **Evidence is always real source.** Never cite the spec, an audit, a checklist, or your own earlier claim as proof — only the codebase, git, or live read-only state. Docs are what you check, not what you check against.
- **Observe, never change — the tool grants are broader than the contract.** This skill holds `Bash` and `Write`, but its contract is strictly read-only:
  - **Bash:** only non-mutating commands — `git log/diff/show`, `aws … describe/list/get`, `gh api` GETs, `grep`, `cat`. **Never** run anything that writes, creates, deletes, applies, deploys, commits, pushes, or redirects (`>` / `>>`, `sed -i`, `rm`, `mv`, `terraform apply`, `aws … create/put/delete`, `git commit/push/checkout`).
  - **Write:** the **only** legal target is the `/tmp` ledger. Never write or edit a repo file, the spec, or code.
  - Treat any mutating action as out-of-contract even though the tool would permit it.
- **Deterministic.** The same claim checked against the same source must yield the same verdict; if a re-check flips a verdict without the source having changed, that's a grounding error to resolve, not new information.
- **Enumerate, don't assume.** A claim you didn't list is a claim you didn't verify.
- **Backward findings are reports, not edits.** An unmapped substantive hunk is surfaced with a proposed AC and a triage — never auto-added to the spec, never a reason to reopen `refine-spec`, and never a gate-blocker. Keep the noise filter tight: behavior-bearing changes only; refactors, formatting, tests, CI, config churn, and docs are allowlisted.
- **Don't fix unless asked.** Report discrepancies; let the user decide what to do about them — many `contradicted` claims means "hand back a bug list", not "go fix N things".
