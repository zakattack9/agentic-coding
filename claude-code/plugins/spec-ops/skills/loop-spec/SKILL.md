---
name: loop-spec
description: Compile a spec into a self-contained review→fix CONVERGENCE-LOOP driver prompt that a fresh session runs to harden the spec until an independent sweep finds nothing material — then stop. Use it for a heavy, unbiased, cross-model spec-hardening pass in a dedicated session: "loop on this spec", "converge/harden this spec", "run a review loop until the spec is airtight", "beat on this spec with fresh reviewers" — especially big / high-stakes / infra specs. It reads the spec, derives tailored review lenses + grounding + a consistency check, and emits the loop brief (fresh Claude lens reviewers AND the codex:codex-review agent fire concurrently each round, adjudicate, edit the spec in place, converge on two clean rounds), then copies it to the clipboard and quits. It does NOT run the loop or edit the spec — the emitted driver does. NOT refine-spec (the in-session interactive hardening loop); NOT launch-spec/goal (those implement a finished spec; loop-spec improves the spec doc).
argument-hint: [@path/to/spec.md] [focus areas] [--rounds N]
model: opus
effort: high
allowed-tools: Read, Grep, Glob, Bash
---

# Loop Spec

Fifth companion to `write-spec`, `refine-spec`, `verify-spec`, and `launch-spec`. It **compiles a
spec into the driver a fresh session needs to converge it** — a review→fix loop that fires fresh
unbiased reviewers (Claude lenses + a cross-model Codex reviewer) each round, adjudicates their
findings, edits the spec in place, and stops when two consecutive fresh sweeps find nothing
material — then **quits**. A fresh session runs the emitted loop; you never run it here.

**This skill is emit-only. It never runs the loop, reviews, edits the spec, or polls.** It reads
the spec and repo to derive the brief's inputs, then emits the driver and copies it to the
clipboard; nothing else.

Arguments: $ARGUMENTS

## Inputs

- **Spec** — the path / `@`-mention of the spec to converge. If none is given, ask with `AskUserQuestion`.
- **Focus areas** — anything to scope or weight (e.g. "focus the loop on the data-migration risk").
- **`--rounds N`** — override the hard-cap round count (default 6).

## When to reach for it (vs. its siblings)

`loop-spec` is the **emit-only, heavyweight, cross-model** hardening pass — a standalone brief run
in a dedicated fresh session. Reach for it over the siblings when you want an unbiased fresh-reviewer
convergence sweep, typically on a big or high-stakes spec:

- **vs. `refine-spec`** — refine is the *in-session, interactive* hardening loop (it asks you
  questions, resolves them live). `loop-spec` *emits a driver* that runs autonomously in a fresh
  session with fresh reviewers each round and no anchoring — decoupled from your working session.
- **vs. `launch-spec` / `/goal`** — those compile a *finished* spec into an **implement** driver.
  `loop-spec` improves the *spec document* itself; run it before `launch-spec`, not instead of it.

This is a heuristic, not a gate — `loop-spec` works on any spec, even one still mid-refinement.

## What it compiles

The emitted brief is the fill-in skeleton in **`references/loop-brief.md`** — read it; it is the
verbatim driver with `«…»` placeholders. Your job is to **derive each placeholder from the spec +
repo**, fill them, and emit the result. Everything outside the placeholders is fixed (the
materiality bar, the loop, the Codex-concurrency rule, the convergence rule) — never rewrite it.

Derive:

- **`«CONVERGENCE_GOAL»`** — the end state in one clause. If the spec's implementation carries
  real deploy/data/prod risk, make it two-part ("implementation-ready **and** safe to promote to
  prod after staging/dev testing"); for a self-contained app/library spec, just
  "implementation-ready — unambiguous and complete enough to build without guessing".
- **`«GROUNDING»`** — a **lean** context block: 2–5 bullets on what the spec covers and the **key
  repo files** reviewers must check the spec's claims against. Skim the spec and `Grep`/`Glob` the
  repo to name the real files (commands, migrations, workflows, infra, config). Do NOT paste file
  bodies — name paths; reviewers read them. This block goes into *every* reviewer prompt, so keep
  it tight.
- **`«LENSES»`** — **3–5 review lenses tailored to THIS spec's risk surface**, one per surface, so
  concurrent reviewers don't overlap. Read the spec and pick the lenses its content demands (e.g.
  infra/blast-radius, CI/CD orchestration, data/PII correctness, dependency-ordering/bring-up,
  API/contract, concurrency). **Always include one implementability / spec-doc-quality lens**
  (dangling/duplicate AC refs, contradictions, ambiguity, is each required behavior a concrete
  testable AC). Fold any user **focus areas** in as an extra lens or by weighting an existing one.
  Format each as a `Lens X — <focus>` line.
- **`«CONSISTENCY_CHECK»`** — a shell one-liner matched to the spec's **actual AC format** so the
  orchestrator can catch conflict markers, duplicate AC numbers, and dangling AC refs after each
  edit batch. Start from the default below and adjust the AC-id pattern / table shape to the spec
  (drop the table-row checks if the spec lists ACs as prose or a bulleted list):

  ```bash
  F=«SPEC_PATH»; grep -cE '^(<{7}|={7}|>{7})' $F;
  grep -oE '^\| [0-9]+ ' $F | sort | uniq -d;
  d=$(grep -oE '^\| [0-9]+ ' $F | grep -oE '[0-9]+' | sort -un);
  for n in $(grep -oE 'AC-[0-9]+' $F | grep -oE '[0-9]+' | sort -un); do echo "$d" | grep -qx "$n" || echo "DANGLING AC-$n"; done
  ```
  (want: 0 conflict markers, no dup AC numbers, no DANGLING.)
- **`«SPEC_PATH»`, `«BRANCH»`, `«ROUNDS»`** — the spec path, its current branch (`git rev-parse
  --abbrev-ref HEAD`), and the round cap (`--rounds`, else 6).

### The Codex-concurrency optimization (the point of the loop's dispatch shape)

The brief tells the orchestrator to dispatch the cross-model reviewer as **one `Agent` of type
`codex:codex-review`, in the SAME message as the Claude lens agents**, so Codex runs **concurrently**
with them — not as a separate skill call after they return. That agent (shipped by the `codex`
plugin) invokes `ask-codex` internally, distills the answer to material findings, and returns
`{ codexAvailable, findings }` in the loop's finding shape — so the orchestrator adjudicates it
exactly like a Claude lens and its context stays lean. It is **fail-open**: `codexAvailable: false`
(Codex absent/unauthenticated/off, or the agent type not installed) → the round proceeds Claude-only
and the orchestrator notes it. Keep this dispatch rule in the brief verbatim; it is the efficiency
win over running a Codex skill sequentially.

## Handoff

Show the filled brief in chat, then **copy it to the clipboard** so the handoff is a single ⌘V —
follow **`references/clipboard-copy.md`** (portable heredoc, session-gated tool selection,
chat-only fallback). The clipboard bytes must be byte-identical to what you showed. Copying is not
running — it stays emit-only.

- **On success**, print e.g. `📋 Copied — ⌘V into a fresh session to run the convergence loop`.
- **On no clipboard tool / non-zero exit**, fall back to chat-only per the reference and name the remedy.

Tell the user to paste it into a **fresh session** (optionally with auto mode so the loop runs
unattended), and **stop**. The fresh session then runs the loop and converges the spec; re-run
`loop-spec` only if you want a new driver.

## Guardrails

- **Emit-only, forever.** Never run the loop, dispatch its reviewers, edit the spec, or poll. If
  you're tempted to start reviewing, stop and hand the brief to the user — the emitted driver owns
  the loop.
- **`Bash` is for derivation + the clipboard copy only.** Read-only `git`/`grep`/`glob` to derive
  the brief's placeholders, and the one clipboard pipe (see the reference). Never edit the spec,
  run a reviewer, or touch the project otherwise.
- **Don't rewrite the fixed brief.** Fill the `«…»` placeholders in `references/loop-brief.md`;
  keep the materiality bar, the loop, the concurrent-Codex dispatch rule, and the convergence rule
  verbatim so the emitted loop can't drift into churn or a self-auditing pass.
- **The cross-model reviewer is best-effort.** The brief already makes Codex fail-open and
  non-blocking; never emit a driver that stalls waiting on Codex or fabricates a Codex review.
- **Don't re-implement refine-spec.** This skill compiles a *hardening loop driver*; it does not
  itself refine, and it does not implement (that's `launch-spec` / `/goal`).
