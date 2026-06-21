# Cross-model judge policy

How a skill runs a **second, different-provider judge** (OpenAI Codex, via the
[Codex bridge](codex-bridge.md)) **beside** its own Claude judge so a "done" check is no
longer Claude auditing Claude. `verify-spec` (completeness judge) and `refine-spec`
(readiness judge) both follow this policy; each keeps only its own target/contract details
inline and points here for the shared mechanics. The cross-model judge is **optional and
fail-open** — when Codex is absent / unauthenticated / off / slow / malformed, the skill
behaves exactly as it does today, judged by Claude alone.

## When it runs — final pass only

Dispatch the Codex judge **only on the pass that would otherwise conclude** — the
completeness pass (verify) or the no-fix readiness pass (refine) — **never on every
intermediate iteration**. Cross-model review then costs **~one Codex call per run**, not
one per loop. On intermediate passes with known gaps you judge with Claude as today; you
only bring in the second model when you are about to sign off.

## Concurrent dispatch — added wall-clock is the slower judge, not the sum

On that final pass, dispatch **both judges in the same turn**: the Claude judge as a `Task`
subagent **and** the Codex judge as a `codex_bridge.py` subprocess (a `Bash` call), so they
run **concurrently**. Issue both tool calls together; do not wait for one before starting
the other. The added wall-clock is at most the slower of the two.

## The Codex judge gets the Claude rubric verbatim

Build the Codex prompt file as the **Claude judge's rubric file, verbatim**, followed by
the same inputs the Claude judge gets:

1. read the rubric file — `agents/spec-verify-judge.md` (verify) or `agents/spec-refine-judge.md`
   (refine) — and copy its **full body** into the prompt unchanged (single-sourced — never
   paraphrase it; that is what makes the two judges review against one rubric and inherit
   the skill's exact materiality / diminishing-returns bar);
2. append the judge's inputs (verify: the target + the ledger; refine: the spec path + repo
   root);
3. write that to a transient `/tmp` prompt file (not a repo file) and pass it as
   `--prompt-file`.

Then dispatch the bridge with the matching kind and schema:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_bridge.py" \
  --kind <judge-verify|judge-refine> \
  --prompt-file <tmp-prompt> \
  --schema-file "${CLAUDE_PLUGIN_ROOT}/schemas/<judge_verify|judge_refine>.schema.json" \
  --cd <repo-root> --effort xhigh
```

The Codex judge returns that judge's **exact existing contract**; the bridge has already
validated the shape with `validate_return.py` before printing it, so on **exit 0** you can
trust stdout as a contract-valid verdict.

## Branch on the bridge exit code

| Exit | Meaning | What the skill does |
|------|---------|---------------------|
| `0`  | contract-valid Codex verdict on stdout | merge it with the Claude verdict (below) |
| `10` / `11` / `12` | skipped / errored / unparseable | **proceed Claude-only**; surface the bridge's single log line; the verdict is exactly what Claude produced |

A non-zero code never changes the outcome beyond what Claude alone produced.

## Merge — AND-on-pass (strictly stronger, never weaker)

When a Codex verdict came back (exit 0):

- **A criterion passes only when both judges pass it.** The completeness verdict is
  `complete` / a readiness flag is `true` **only when both** the Claude and Codex judges
  pass it. Any FAIL from either model holds the gate closed and becomes work for the next
  pass.
- **The gap set is the union.** Combine both judges' findings (verify: `missed` +
  `weakEvidence`; refine: the FAILed criteria + `findings`). Fold the **union** into the
  single existing ledger field the Stop hook already reads — you are not adding a field, you
  are withholding the existing done-signal until both judges agree.

The combined gate is therefore **strictly stronger** than Claude alone — it can only add
work, never remove it.

## Unchanged Stop hook & ledger — the skill withholds the done-signal

The relevant Stop hook and ledger schema are **unmodified** (`stop_verify_spec.py` /
`stop_refine_spec.py`). Codex influences only *whether the skill writes the existing
done-signal*, never any artifact a hook keys on. A run with Codex absent passes every
existing gate exactly as before; **no hook or ledger ever requires a Codex flag.**

## Stubborn-split escalation — never deadlock the gate

A Claude/Codex split that **doesn't resolve through the normal loop** — Claude passes a
criterion but Codex keeps failing it with **no further fix available** — must not spin the
loop silently or deadlock the gate. Escalate it to the user for disposition:

- **Run interactively:** ask with `AskUserQuestion` — is the Codex finding a genuine gap
  (loop and fix it) or noise to override (drop it and pass)?
- **Delegated under `orchestrate-spec`:** return the skill's normal **blocked / handoff**
  result describing the contested criterion; the orchestrator owns the question and re-runs
  the skill with the disposition.

The user's disposition **resolves the contested flag**: an accepted gap loops as normal
work; an override drops that Codex-only finding from the merged set so the existing Stop
hook can release. A stubborn Codex FAIL can never deadlock the gate.
