# Claude Code Workflow Audit — Zak Sakata

**Date:** 2026-06-13 · **Analyst:** Claude (Opus 4.8, ultracode) · **Scope:** every Claude Code session on this machine
**Corpus:** 999 human turns · 82 sessions with content (of 84 transcripts) · 20 project stores · 2026-05-11 → 2026-06-13
**Purpose:** reverse-engineer the user's prompting + engineering patterns to (a) recommend new user-level skills and (b) decide whether to update the existing `write-spec` / `refine-spec` skills. **Analysis only — nothing was implemented.**

---

## TL;DR

- You run a **spec-first, verification-heavy, parallelized loop**: recon → spec → enumerate-then-approve → implement under a `/goal` gate → **re-verify against live source** → explicit git wrap-up. `/goal` is your most-used command (28×).
- Your **single most-repeated manual instruction** is *"verify this against the actual code/live state, don't trust the checklist"* — it recurs in **all 10 analysis chunks**. The top skill recommendation (`ground-check`) targets exactly this.
- **4 skills survive** scrutiny: `ground-check` (high), `wrap-session` (high), `doc-sync` (high), `artifact-lint`-as-a-hook (medium). One candidate (`scoped-change`) was **cut** as over-scoped.
- **`write-spec` / `refine-spec` are already strong** — only surgical edits are warranted. The most important is **softening `write-spec`'s blanket "cut Out of Scope" rule**, which conflicts with your very-high-prevalence scope-carve-out habit.
- **Verified cleanup:** you have a **duplicate, divergent `refine-spec`** installed (stale `zaksak` copy + current `spec-kit` copy) — `/zaksak:refine-spec` runs the inferior one. Consolidate onto `spec-kit`.

---

## 1. Method & corpus

Claude Code persists every session as a JSONL transcript under `~/.claude/projects/<encoded-path>/`. The audit:

1. **Extracted** every human-authored turn from all 84 main-session transcripts (82 had content; 2 were empty/resumed) — filtering tool-results, injected context, and compaction summaries — into per-project digests — preserving verbatim prompts, slash-command invocations, session titles, git branches, and a per-session tool histogram.
2. **Packed** the digests into 10 balanced chunks (sessions kept intact).
3. **Analyzed** via a 15-agent workflow: fan-out evidence extraction (10) → unified-profile synthesis (1) → parallel recommendation — new skills + spec-skill updates (2) → adversarial critique (1) → finalize (1).
4. **Verified** every consequential claim about installed skills against the files on disk (see [Appendix](#appendix-verified-facts)).

Supporting data: [`data/corpus-inventory.md`](data/corpus-inventory.md) · [`data/command-usage.md`](data/command-usage.md) · [`data/tool-usage.md`](data/tool-usage.md).

**Tooling fingerprint (from `data/tool-usage.md`):** Bash-dominant core loop — Bash 3393 / Edit 2148 / Read 1797 — with very heavy Task-todo tracking (TaskCreate 241 + TaskUpdate 462), 128 parallel `Agent` spawns, `ToolSearch` 76 (deep MCP surface), `AskUserQuestion` 67 + Conductor variant 98, `WebSearch`/`WebFetch` 39, browser automation (claude-in-chrome) and terraform MCP. **Top commands (from `data/command-usage.md`):** `/goal` 28, `/effort` 13, `/compact` 11, `/plugin` 5, `/context` 5, `/model` 4, `/loop` 3.

---

## 2. Prompting profile

You operate as a **meticulous, spec-driven engineer who treats Claude as a high-effort reasoning partner under tight control.** Patterns, ranked by prevalence, each with verbatim evidence:

| Pattern | Signature | Prevalence |
|---|---|---|
| **Recon before action** | *"perform a comprehensive review of X"* before any change request | very high |
| **Invites interrogation** | *"**ask me as many questions as needed**"* / "surface blockers immediately" | very high |
| **Grounding over docs** | *"is that true and confirmed by the actual code source?"* — distrusts specs/audits as stale | very high |
| **Goal + scope carve-outs** | states the *why*, bounds with *"ignore prod"*, *"do NOT introduce new resources"* | very high |
| **Hard completion gate** | *"you are not done until X"* — self-terminating fixpoint, paired with `/goal` | very high |
| **Enumerate-then-approve** | *"do not make the changes yet, just enumerate them for me to review"* → approve a numbered subset | very high |
| **Separated git choreography** | commit / push / branch / merge / switch as terse standalone turns; *"commit but do not push"*; PR-only-to-main | very high |
| **@-path / absolute-path scoping** | anchors reads & writes to exact artifacts; re-attaches the same doc across turns | very high |
| **Anti-over-engineering** | *"ensure it is not overengineered… so another dev can quickly understand"*; defer premature decisions | high |
| **ID-keyed decision replies** | answers question-lists as `A1/D3/G2…`, agreeing in bulk, itemizing only exceptions | high |
| **Output-altitude control** | *"keep it high level… focus on logical flows"*; chat-vs-file; audience-aware | high |
| **Socratic verify-by-paraphrase** | *"so in short… right?"*, *"was it safe to make that fix?"* | high |
| **Session-handoff meta-prompting** | *"write a prompt for a new conversation with no prior knowledge… include all @ references"* | high |
| **Raw-error-paste + terse fix** | drops CI/AWS/console error blocks verbatim, names the exact phase | high |
| **Determinism as a hard requirement** | *"recreate it perfectly every time"*, HST cutoffs, charges-minus-refunds net | high (scripts/infra) |

### Standards & voice (the recurring quality bars)

- *"perform a comprehensive review/analysis of X"* — fixed recon-first opener.
- *"ask me as many questions as needed"* (often bolded) — clarification is a required first step, not optional.
- *"is that true and confirmed by the actual code source?"* / *"don't just rely on the checklist spec"* — grounding over assumptions.
- *"ensure it is not overengineered… so another dev can quickly understand its objectives"* — concise, right-scoped, maintainable.
- *"any non-critical or relevant historical information or prose that is unneeded should be removed"* — implementation-essential content only.
- *"do not make the changes yet, just enumerate them"* — enumerate-then-approve before any mutation.
- *"are you absolutely sure … will not affect or break the current implementation that is currently live and deployed?"* — prove safety against prod first.
- *"self-contained without needing to reference any other docs"* / *"assume the reader has 0 idea"* — audience-aware, standalone artifacts.
- *"ensure no commits are squashed … with ZERO loss of code"* — no silent loss on merges/rewrites.
- *"this is arguably worse than the previous version. revert back"* — blunt, decisive rejection of regressions.
- *"real simplifications that will not make future maintainability difficult"* — protects developer mental model against over-aggressive simplification.
- Terse confirmations between substantive turns — *"yes"*, *"option B"*, *"merged"*, *"pushed"*, *"do 1 and 2 only"* — with frequent fast-typed typos.

---

## 3. Engineering workflow

```
configure session (Opus 4.8 1M + /effort xhigh|ultracode)
  → spawn parallel Conductor agents in per-city git worktrees (curitiba, el-paso, …)
  → comprehensive-review recon → write/refine spec to @specs|@tasks (source of truth)
  → AskUserQuestion to resolve open questions → enumerate-then-approve
  → implement under a /goal hard gate → VERIFY against committed code/live state (distinct 2nd pass)
  → update living docs (README/CLAUDE.md/design) → explicit commit/push (PR-only-to-main)
  → /context budget checks + /compact at phase boundaries → generate self-contained handoff prompt
```

**Rituals:** session-config-up-front · `/goal` hard-gate loops · parallel Conductor worktrees (14–27 subagents in big sweeps) · enumerate-then-approve gate · grounded verification pass against committed code · spec-as-source-of-truth lifecycle (write → refine → implement → verify → archive to `completed/`) · background `Monitor` poll-to-green CI · living-docs maintenance on every change · session-handoff prompt generation · `TaskCreate/TaskUpdate` phase tracking · `/loop` for self-refreshing audits.

---

## 4. Pain points (the repeated inefficiencies)

These are the highest-signal findings — each is a repeated manual instruction or correction that a skill/hook could eliminate.

| # | Pain point | Impact | Frequency |
|---|---|---|---|
| 1 | **Single-pass work is never trusted** — you re-issue *"verify against the actual source"* 2–3×/session, often verbatim, because Claude declares "done" against the checklist, not the code/live state | very high | **all 10 chunks** |
| 2 | **Reviews/sweeps aren't exhaustive first time** — same review prompt re-typed 3–4× with escalating intensifiers; audit lists go stale vs your out-of-band edits | very high | 7 chunks |
| 3 | **Docs drift vs code/live-state** after every merge or out-of-band commit; you force full doc-vs-code reconciliation manually | high | 5 chunks |
| 4 | **Git wrap-up choreography hand-typed every session**; commit/push re-issued because it wasn't confirmed with a SHA (*"are all chanegs psuhed?"*) | high | 9 chunks |
| 5 | **Silent content loss** on regenerations/merges — you no longer trust a rewrite without a line-level no-loss audit (the ARM64 annotation) | high | 3 chunks |
| 6 | **Wrong effort/altitude on first try** — identical comprehensive-review prompt re-sent at turns 1/2/5 with `/effort` + `/model` changes interleaved | high | 2 chunks |
| 7 | **Non-self-contained reports** — generated docs leak external refs, assume reader context, or carry stale status framing ("is the issue currently fixed?") | high | 4 chunks |
| 8 | **Non-ASCII → broken AWS applies** — em-dash/smart-quote in names/tags → *"Character sets beyond ASCII are not supported"* across many resources | high (infra) | infra chunks |
| 9 | **Mermaid fails GitHub's renderer** — unquoted shell/semicolons/`<env>` tokens → *"Parse error on line 15"*; plus layout fixups that drove a draw.io migration | medium-high | 5 chunks |
| 10 | **Stripe API-shape confusion** + re-specifying identical script invariants (HST cutoff, charges-minus-refunds, Connect-vs-non-Connect) by hand | medium-high | scripts chunks |
| 11 | **Fixed-width currency report misalignment** — same alignment fix re-requested 4+× | medium | scripts chunk |
| 12 | **Terraform/AWS bootstrap & limit friction** re-derived each time — IAM 10240-byte inline-policy limit, first-apply chicken-and-egg | medium-high | 4 chunks |
| 13 | **Conductor worktree broken-git** blocks the autonomous loop (*"fix your workspace git, do NOT do any destructive actions"*) | medium | 1 chunk |
| 14 | **Plain-text questions / unwanted edits** — Claude batches questions in prose instead of `AskUserQuestion`, or edits when only an answer was wanted | medium | 2 chunks |

### Re-steer themes (how/why you correct Claude)

1. **Re-ground against the actual source, not your own claim or a stale doc.**
2. **Don't stop early / don't half-do it — converge to a fixpoint and prove completeness.**
3. **Cut over-engineering, bloat, stale references, and premature decisions.**
4. **Stay in scope and don't act when only analysis/answers were asked.**
5. **Prove safety before touching live/production infra.**
6. **No silent loss on rewrites and merges.**
7. **Make artifacts self-contained and audience-aware.**
8. **Correct the output's structure/format and altitude, not just its content.**
9. **Edit the right target and respect explicit conventions** (`{env}-zilarent-[resource]`, the SSM/Secrets slash-syntax exception).
10. **Re-sync to branch HEAD after out-of-band changes.**

---

## 5. Recommended new user-level skills

Ranked by priority then groundedness (5 = strongly evidenced by repeated real behavior). The adversarial critique **cut one** candidate and **reframed another** — kept here for honesty.

### 🟢 `ground-check` — HIGH · groundedness 5/5 (best-evidenced)

A grounded **second-pass verifier** that re-checks an already-completed implementation, audit, or claim against the **actual committed code, `git show`/diff, and live AWS/gh CLI** — and is **forbidden from citing the spec, an audit doc, or its own prior output** as evidence. Loops until every claim is source-confirmed.

- **Problem:** Pain point #1 — your most-repeated manual instruction, recurring in all 10 chunks. Claude declares "done" against the checklist, not reality.
- **Why not covered:** `refine-spec` verifies the **spec document**; `/goal` self-judges completion but mandates no per-claim source evidence; `code-review`/`verify` hunt for bugs, not claim-by-claim source grounding with a CONTRADICTED gate.
- **Mechanics:** `model: opus`, `effort: xhigh`, `allowed-tools` incl. **Bash** (git/aws/gh), Read, Grep, Task; skill-scoped Stop hook (mirror `refine-spec`'s `stop_refine_spec.py`). Flow: enumerate every factual/"requirement implemented" claim → fan out parallel verifier subagents labeling each `CONFIRMED / CONTRADICTED / UNVERIFIABLE` with inline `file:line` / `git show` / CLI evidence → fresh readiness-judge + Stop hook block turn-end until zero claims remain CONTRADICTED/UNVERIFIABLE. Emits a per-claim table with SHAs. `AskUserQuestion` only when a contradiction needs a human decision.
- **Risks:** cap parallel subagents on huge changesets; the `AskUserQuestion` escape valve covers legitimately-external evidence.

### 🟢 `wrap-session` — HIGH · 4/5

End-of-unit git choreographer: runs branch / write-to-dir / commit / **no-loss merge** / switch / **PR-only-to-main gate**, **echoes the commit SHA back**, refuses to squash, and (optionally, as a thin separate step) generates a self-contained handoff prompt.

- **Problem:** Pain points #4 + #5 — closes almost every session; commit/push re-issued for lack of SHA confirmation; you no longer trust a merge without a no-loss audit.
- **Why not covered:** the installed `commit-commands` skills are thin single-action and orchestrate none of this (no branch→write→merge→switch sequence, no no-loss audit, no SHA echo, no PR-only-to-main human-gate, no handoff generation).
- **Mechanics:** `model: opus`, `effort: high`, `allowed-tools: Bash(git/gh), Read, AskUserQuestion, Task`, **`disable-model-invocation: true`** (runs only on explicit `/wrap-session` — matches your deliberate git control). `AskUserQuestion` pre-filled with your defaults (Conventional Commits, PR-only-to-main with manual approval). On merge/rebase: line-level no-loss diff vs the prior commit; refuse squash unless told. Detect a broken Conductor worktree and **report non-destructively** (folds in pain point #13). Stop hook verifies the working tree matches the stated end-state.
- **Scope note:** keep handoff-prompt generation as `/wrap-session --handoff`, not bundled into every commit — it fires at a different moment and overlaps your manual `/goal`+"what's left" flow.

### 🟢 `doc-sync` — HIGH · 4/5

Reconciles a **doc set** (README / CLAUDE.md / design docs / runbooks / specs) against current committed code, latest commits, and live AWS/gh state — flags drift line-by-line in an **enumerate-then-approve report first**, edits only what's stale, then runs self-containment + no-silent-loss checks.

- **Problem:** Pain point #3 + the self-contained/audience-aware re-steer.
- **Why not covered:** your `aws-infrastructure-spec` skill only *regenerates* the infra spec from terraform; `refine-spec` is single-spec readiness, not drift-detection across a doc **set**; `init`/`writing-claude-md` author from scratch.
- **Mechanics:** `model: opus`, `effort: xhigh`, `allowed-tools: Read, Grep, Bash(git/aws/gh), Edit, Task`; Stop hook gating on zero unresolved drift. Diff each doc's claims vs source (`git log -p` on the doc vs the code paths it describes; live CLI for infra docs) → enumerate-then-approve drift report → edit only drifted lines → no-loss diff vs prior commit → self-containment lint (external refs, operator-context assumptions, stale fixed-vs-open / one-time-vs-ongoing framing).
- **Build note:** **share a grounding core with `ground-check`** — one engine, two modes (*verify-implementation-against-claim* vs *reconcile-and-edit-doc*) — to avoid two divergent fan-out engines (exactly the divergent-copy problem already seen between the `refine-spec` copies, §7).

### 🟡 `artifact-lint` — MEDIUM · 3/5 — **reframe as a HOOK, not an invokable skill**

Catches two fully-preventable failures: **non-ASCII bytes in AWS names/descriptions/tags** (pain point #8) and **Mermaid that fails GitHub's renderer** (pain point #9).

- **Why a hook, not a skill:** a skill the model must remember to invoke "will be forgotten exactly when it's needed" — you never anticipate these failures. The value is in a deterministic **PostToolUse / pre-commit hook**, configured via your existing `update-config` skill + `settings.json`.
- **Mechanics:** (1) Scan staged HCL and any AWS name/description/tag string for bytes > `0x7F`; reject with `file:line` + suggested ASCII replacement (em-dash → `-`, smart-quotes → straight). Make this the priority half; advisory-with-autofix outside strict name/tag fields. (2) **Static** Mermaid lint (quote labels with shell/semicolons/`<>`, escape `<env>`, check node-id legality) before write — no headless-render dependency. Deterministic: same input → same verdict.

### 🔴 `scoped-change` — CUT by the critique

A front-of-task wrapper (effort/altitude preflight + enumerate-then-approve + `AskUserQuestion` enforcement + anti-over-engineering). **Cut** because three of four concerns are already covered (AskUserQuestion is your global CLAUDE.md rule; the rest live in `refine-spec`'s guardrails and your own habitual openers), the effort/altitude half rests on thin evidence (2 chunks), and a start-of-every-task wrapper adds ceremony. The one real gap — **enforcing AskUserQuestion + an analyze-only Edit-block** — is a `PreToolUse` hook; fold it into the same `update-config` work as `artifact-lint`.

---

## 6. `write-spec` / `refine-spec` updates (verified against installed files)

**Verdict: both skills are already strong and closely mirror your workflow — changes are surgical, not structural.** `refine-spec`'s enforced loop (ledger + Stop hook + 5-flag readiness gate + independent readiness judge) is an almost 1:1 encoding of your "you are not done until X" + grounding + ask-before-assuming behavior. **Keep it.**

### `write-spec` — 3 grounded additions, 1 sharpen

| Action | Change | Rationale |
|---|---|---|
| **change** | **Soften the blanket "cut Out of Scope" rule** (line 42). Keep a **one-line bounded scope statement when you supplied a real carve-out** (*"do not touch prod"*, *"ignore multi-tenancy/infra/cicd"*); still cut speculative "considered but won't do" lists. | Out-of-scope carve-outs are a *very-high* prevalence part of how you frame every task; the blanket cut drops your own load-bearing scoping. **Best-grounded edit.** |
| **add** | **"Self-contained / zero-context reader" rule** — the spec must stand alone for a downstream dev / refactor team; don't reference docs they may not have. | Distinct from "no bloat" — a spec can be lean yet still leak references. Recurring specSignal + repeated re-steer. |
| **add** | **Minimal "ground before you write"** — don't assert ungrounded "currently X" facts; write them as open questions or ask. **No subagent/git/CLI grounding** (that's `refine-spec`'s job). | Front-loads fewer hallucinated facts (pain point #1) while preserving `write-spec`'s independence. |
| **keep** | The scan-in-2-min test, say-things-once, behavior-not-implementation, show-don't-tell, bold key terms, tight TL;DR, section structure, and cutting Problem-Statement noise. | Maps near-exactly to your stated standards and owned tooling (`ascii-ui`, heavy mermaid). No friction evidence. |

### `refine-spec` — 2 additions, 1 sync, keep the core

| Action | Change | Rationale |
|---|---|---|
| **add** | **Extend Verify grounding** beyond "the codebase" to **latest git commits + live AWS/gh CLI** for infra specs; re-ground against branch HEAD; treat sibling/completed specs as possibly-stale. ⚠️ **Requires adding `Bash` to `allowed-tools`** (currently `Read, Grep, Glob, Edit, Write, Task` — no Bash, so the addition is inert without it). | Pain point #3 (branch-HEAD drift) + your explicit grounding sources (*"recheck the last few commits"*, *"use the aws/github cli"*). |
| **add** | **No-silent-loss check** — for a git-tracked spec, diff the edited/regenerated version vs the prior commit and surface a `removed:` list before finalizing. Scope to tracked-file rewrites only. | Operationalizes the existing "never drop substance" principle you no longer trust without a line-level audit (pain point #5). |
| **change** | **Bloat-definition sync** — port the richer Bloat row (preserving decision/config/field tables) into the active copy (see §7). | The **active** copy has the weaker collapsed definition that could wrongly cut tables you rely on. |
| **keep** | The enforced loop + ledger + Stop hook + 5-flag gate + fresh readiness judge; the `AskUserQuestion`-driven Resolve step; the independence guarantee; "Refine, don't redesign." | Almost 1:1 with your real iteration behavior. No friction evidence; the skill's strongest match. |

**Not pushed into the generic spec skills** (they belong in CLAUDE.md / `ascii-ui` / a commit skill): naming conventions (`{env}-zilarent-[resource]`), git choreography, mermaid-render linting, currency alignment.

---

## 7. ⚠️ Verified finding: duplicate, divergent `refine-spec`

Confirmed directly on disk. **Both plugins are enabled** (`zaksak@zaksak: true`, `spec-kit@zaksak: true`), and **both ship a `refine-spec`** — but they have drifted:

| Source | `refine-spec` Bloat row | Status |
|---|---|---|
| `zaksak` 0.2.0 (cached, active) | **collapsed** — *no* "tables stay" carve-out | ⚠️ stale |
| `spec-kit` 0.1.1 (active) | **rich** — keeps *"Decision, config, and field tables are pertinent"* | ✓ current |

So `/zaksak:refine-spec` runs the **inferior** copy that could wrongly cut the decision/config tables you depend on, while `/spec-kit:refine-spec` runs the good one. The source `zaksak` plugin **already removed** `refine-spec` (and `write-spec` only ever lived in `spec-kit`), but the **cached `zaksak` 0.2.0 still carries the old copy** — its version wasn't bumped, so `autoUpdate` never re-pulled.

**Recommendation:** consolidate onto `spec-kit`; get `refine-spec` out of the `zaksak` install (bump the `zaksak` plugin version so `autoUpdate` re-pulls the source that already dropped it, or reinstall). This is the same divergent-copy hazard the shared `ground-check`/`doc-sync` core (§5) is designed to avoid.

---

## 8. Open gaps (candidate future skills, not yet recommended)

Real but lower-frequency, or belonging in CLAUDE.md / project skills rather than user-level. Highest-value first:

1. **Infra-bootstrap preflight** — IAM 10240-byte inline-policy limit (recurs turns 29/30/56/58/60), first-apply chicken-and-egg (state-lock IAM, pre-seeded SSM params, `count` depends-on-apply-time), reproducible "manual seed before first apply" runbook. Your `terraform-*`/`terrashark` skills don't cover bootstrap-order. *(medium-high)*
2. **Stripe reconciliation scaffold** with baked invariants (HST cutoff, charges-minus-refunds, charge-vs-payment_intent metadata, Connect-vs-non-Connect, companion verify-from-CSV). *(medium-high)*
3. **Deterministic fixed-width currency/financial report formatter** (`ascii-ui` covers UI wireframes, not financial column alignment).
4. **Mermaid *layout* quality** — overlapping arrows / clipped labels that drove the draw.io migration (`artifact-lint` only checks parse-validity).
5. **Stakeholder-summary status framing** — fixed-vs-open / one-time-vs-ongoing on ad-hoc slack blurbs (`doc-sync`'s lint only covers tracked docs).

---

## 9. Recommended next actions

1. **Build `ground-check`** (highest leverage — kills your #1 repeated instruction), on a **shared grounding core** that `doc-sync` reuses.
2. **Apply the verified `write-spec` / `refine-spec` edits** (incl. adding `Bash` to `refine-spec`'s `allowed-tools`) and **resolve the duplicate `refine-spec`** (§7).
3. **Wire the `artifact-lint` + AskUserQuestion-enforcement hooks** via `update-config`.
4. **Build `wrap-session`**, then **`doc-sync`**.
5. **Persist this profile to memory** so future sessions inherit your standards without re-deriving them.

---

## Appendix: verified facts

Verified by reading the files on disk (not relied on from the agents):

- **Enabled plugins** (`~/.claude/settings.json`): `zaksak@zaksak`, `spec-kit@zaksak`, plus official `commit-commands`, `frontend-design`, `pyright-lsp`, `skill-creator`.
- **`refine-spec` copies present:** `zaksak/0.2.0` (collapsed Bloat), `zaksak/0.1.0` (rich), `spec-kit/0.1.0` (collapsed), `spec-kit/0.1.1` (rich), source-repo `spec-kit` (rich). **Active = `zaksak/0.2.0` (collapsed) + `spec-kit/0.1.1` (rich).**
- **`write-spec`** exists **only** in `spec-kit` (source `zaksak` plugin has just `ascii-ui` + `writing-claude-md`).
- **`refine-spec` `allowed-tools`** = `Read, Grep, Glob, Edit, Write, Task` in **all** copies — **no `Bash`** (the git/CLI grounding addition is inert until Bash is added).
- **`write-spec`** has no `model`/`effort` frontmatter.
- **Existing user skills** (do not duplicate): `write-spec`, `refine-spec`, `ascii-ui`, `writing-claude-md`, the `ralph-*` suite; project-local `aws-infrastructure-spec`.

**Workflow run:** 15 agents · 823K agent tokens · ~14 min · 10 evidence packs. Full structured output retained separately (`profile`, `skillsRec`, `specRec`, `critique`, `final`).
