# The loop-spec brief — fill-in skeleton

`loop-spec` emits this brief, filled from the target spec, as the `/goal`-prefixed driver a fresh
session runs to converge the spec. Copy the driver verbatim, replacing every `«…»` placeholder with
spec-derived content; **drop** a placeholder's line entirely if it doesn't apply (never emit a
literal `«…»`). Everything not in `«…»` is fixed — keep it as-is so the materiality bar, the loop,
the Codex-concurrency rule, and the convergence rule stay intact.

Placeholders you fill (all derived by the skill before emitting — see `SKILL.md`):
- `«SPEC_PATH»`, `«BRANCH»` — the target spec and its branch.
- `«CONVERGENCE_GOAL»` — the end state in one clause (e.g. "implementation-ready and, once built and
  tested in staging, safe to promote to prod"; for a pure app/library spec, just
  "implementation-ready — unambiguous and complete enough to build without guessing").
- `«GROUNDING»` — the lean context block: what the spec covers + the key repo files reviewers must
  check spec claims against.
- `«LENSES»` — the 3–5 tailored review lenses (one per risk surface of THIS spec), each a
  `Lens X — <focus>` line; always include an implementability / spec-doc-quality lens.
- `«CONSISTENCY_CHECK»` — the (compact) shell check matched to the spec's AC format.
- `«ROUNDS»` — the hard-cap round count (default 6).

**Emit only the driver below the `---` rule.** This header block is guidance for `loop-spec`; it is
NOT part of the driver. The driver is a **`/goal `-prefixed prompt** — the pasted/copied text starts
with the literal `/goal ` token so a fresh session (with auto mode) runs it as an autonomous goal.
`/goal` supplies the turn-to-turn autonomy; the loop **self-terminates** on the convergence rule, and
the worker emits a transcript-visible `CONVERGENCE REACHED` line the `/goal` evaluator keys on — so
the driver's correctness does not depend on the tool-less evaluator re-deriving the goal (unlike
launch-spec's `/goal` done-gate).

**Fit `/goal`'s ~4,000-char condition budget (the `/goal ` prefix counts).** `/goal` caps the
condition at 4,000 chars and its overflow behavior is undocumented — so keep the FILLED driver under
it. The fixed text below is already tight; the flex is the fills — if `«GROUNDING»` / `«LENSES»` /
`«CONSISTENCY_CHECK»` would push the total over ~4,000, **trim them to essentials** (fewer, broader
lenses; a leaner grounding block; a one-line consistency check). The loop still converges — here the
budget is a size limit, not a hard done-gate contract.

---

/goal Converge spec @«SPEC_PATH» (branch «BRANCH») to «CONVERGENCE_GOAL», then STOP. You ORCHESTRATE a review→fix loop: each round dispatch FRESH reviewers (they get only the current spec + repo, never your notes — no anchoring), adjudicate, edit the spec directly, decide convergence. Do NOT run any spec-ops skill; do NOT write code; the ONLY file you edit is the spec. Track a FIX-log + a DECLINE-log.

GROUNDING (give to EVERY reviewer): «GROUNDING» Reviewers check spec claims against the ACTUAL repo (code, config, migrations, workflows), not prose — the real defects are spec-vs-code mismatches and ambiguities.

ROUND — in ONE message dispatch all of these concurrently, wait for all, then adjudicate:
• one general-purpose Agent per LENS below (check spec claims vs repo; return ONLY material findings);
• ONE Agent of type spec-ops:codex-review, SAME message so Codex runs concurrently — give it the spec path, the GROUNDING, "review the whole spec vs the repo", the MATERIALITY BAR, and the finding shape; it returns { codexAvailable, findings }.
LENSES:
«LENSES»
Finding shape: { severity, location (AC-id/§), scenario (wrong-thing-built or risk), evidence (file:line), edit (precise spec change) }. A Claude lens returns findings or exactly `NO MATERIAL FINDINGS`; codex-review always returns its { codexAvailable, findings } envelope. Codex is FAIL-OPEN — never block: codexAvailable:false OR an Agent error / missing type (count it a COMPLETED unavailable result, don't retry) → proceed on the Claude lenses; never fabricate a Codex review.

MATERIALITY BAR (apply strictly — prevents churn). MATERIAL only if it would plausibly cause: a broken build/deploy; data loss or a security/privacy leak; an unsafe/irreversible blast radius; a genuine AMBIGUITY two engineers build differently; an internal CONTRADICTION or a stale claim the code refutes; a REQUIRED behavior with NO acceptance criterion; or ENTRENCHING a poor pattern where a bounded, in-objective, warranted refactor would leave the code better (or a materially-implied quality vertical — security/perf/scale/maintainability/error-handling — has no AC). If the spec is CODE-FREE, capture a quality finding as an OBSERVABLE-OUTCOME AC, never a code-structural refactor AC. NOT material (DECLINE, log one line): wording/style, detail that doesn't change what gets built, speculative/future scope, re-litigating an accepted trade-off, unwarranted refactor/gold-plating. Unsure → NOT material.

ADJUDICATE each finding (read spec + cited code): FIX (real+material+uncovered) → edit the spec now (continue AC numbering; correct in place any claim it contradicts); ALREADY-OK → note; DECLINE → log with a reason. Dedupe across reviewers + the DECLINE-log. After each edit batch run the consistency check, fix any failure: «CONSISTENCY_CHECK» A round is CLEAN when zero material findings survive.

CONVERGE: STOP at TWO CONSECUTIVE CLEAN rounds (a Codex-unavailable round is neutral — judged on the Claude lenses; never fails a round or resets the streak). Any material fix resets the streak. Cap: «ROUNDS» rounds. Begin your FINAL message with `CONVERGENCE REACHED` or `HALTED — ROUND CAP` so /goal detects completion, then report: rounds + fixes/round, the FIX-log (edit + AC), the DECLINE-log, the consistency result, and a verdict on «CONVERGENCE_GOAL». Do NOT commit — leave the spec edited for me to review.
