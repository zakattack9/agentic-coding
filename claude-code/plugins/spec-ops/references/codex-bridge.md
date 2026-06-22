# The Codex bridge — cross-provider second reviewer

`scripts/codex_bridge.py` is the **single, fail-open wrapper** that lets spec-ops borrow
a second, different-provider model (OpenAI Codex CLI) as an adversarial reviewer beside
its own Claude reviewers. It is the **only** component that ever invokes `codex` — every
skill that wants a Codex opinion shells out to this script and branches on its exit code.
This file is the single source for the invocation contract, the exit taxonomy, model
resolution, and the `--output-schema` caveats; the skills point here rather than restating
any of it.

## Why a bridge at all

Each spec-ops "done" check is otherwise **Claude auditing Claude**. Adding a second model
of a *different provider* at the existing independence seams catches a class of miss a
same-family judge shares. But it must be a **graceful enhancement, never a dependency**: if
Codex is absent, unauthenticated, switched off, slow, or returns junk, the run proceeds
exactly as it would with no second model. The bridge guarantees that — it can only ever
*add* findings to a review, never block or weaken a gate.

## Invocation

```
codex_bridge.py --kind <judge-verify|judge-refine|write-requirements> \
                --prompt-file <f> [--schema-file <f>] [--cd <repo>] \
                [--model <m>] [--effort xhigh|medium] [--timeout 180]
```

- `--kind` selects the return contract the reply is validated against (via
  `validate_return.py`) — `judge-verify` / `judge-refine` reuse the existing judge
  contracts verbatim; `write-requirements` is the advisory discovery-review contract.
- `--prompt-file` holds the **entire** prompt the caller built — for a judge that is the
  Claude judge's rubric file **verbatim** followed by the task inputs, so the two models
  review against a single-sourced rubric. The bridge passes it through unchanged.
- `--schema-file` (optional) is the matching `schemas/*.schema.json`, supplied to Codex as
  `--output-schema` to *shape* the reply. It is best-effort, not the gate (see below).
- `--cd` is the repo root Codex reads under (read-only).
- `--model` / `--effort` / `--timeout` override the resolved model, the reasoning effort
  (`xhigh` for a judge/review; `medium` reserved for any future grounding lane), and the
  per-call timeout.

**Availability probe (`--probe`).** `codex_bridge.py --probe --kind <kind>` prints one deterministic line — `CODEX: YES …` or `CODEX: NO — <reason>` — and exits `0` **without invoking Codex**. It mirrors the same availability / auth / env-switch guards `run()` applies. A skill injects it at load with `` !`…codex_bridge.py --probe --kind <kind>` `` (Claude Code dynamic-context injection) so it can **skip its cross-model section on `NO`** — building no prompt and making no bridge call on the common no-Codex path — and run the judge only on `YES`. The `YES` path still calls the bridge and branches on the real exit code below (a `YES` probe doesn't guarantee the judge call itself returns `0`).

Under the hood it runs, with **no escalating flag, ever**:

```
codex exec -  --sandbox read-only --skip-git-repo-check -C <repo> \
              --json -o <private-tmp> [--output-schema <schema>] \
              -m <model> -c model_reasoning_effort=<effort>
```

`codex exec` is **inherently non-interactive** — it has no approval prompt to bypass — so
`--sandbox read-only` is the whole guarantee a review cannot touch the repo. The bridge
**never** builds `--dangerously-bypass-approvals-and-sandbox`,
`--dangerously-bypass-hook-trust`, a writable `--add-dir`, or a non-`read-only` sandbox;
their absence is structural, not prompt-enforced.

## Exit taxonomy — the caller branches on the code alone

| Code | Meaning | Caller behavior |
|------|---------|-----------------|
| `0`  | valid, contract-checked JSON on stdout | fold it into the ledger / disposition |
| `10` | **skipped** — Codex not installed, not authenticated, or switched off by env | proceed with the Claude review only; one log line |
| `11` | Codex error / timeout / `turn.failed` | proceed Claude-only; one log line |
| `12` | reply unparseable after one re-dispatch | proceed Claude-only; one log line |

**Every non-zero code is fail-open.** A skipped / errored / timed-out call emits exactly
one stderr line and changes nothing about the caller's own verdict.

### Availability & auth — probed non-interactively

Before invoking, the bridge checks, with **no network call and no browser**:

1. `codex` on `PATH` — absent ⇒ `10`.
2. usable auth — `OPENAI_API_KEY` / `CODEX_API_KEY` set, **or** `codex login status` reports
   logged-in ⇒ proceed; neither ⇒ `10`. It **never** runs `codex login`.

### Env switches

| Variable | Effect |
|----------|--------|
| `SPEC_OPS_CODEX=0` | disable **all** Codex cross-model checks (any kind ⇒ `10`); behavior byte-identical to no Codex |
| `SPEC_OPS_CODEX_WRITE=0` | disable **only** the `write-requirements` discovery reviewer, independently of the verify/refine judges |
| `SPEC_OPS_CODEX_TIMEOUT` | per-call Codex timeout in **seconds** (default `180`); raise it for slow xhigh runs. An explicit `--timeout` arg still wins; invalid / non-positive ⇒ default. **Effective ceiling ~600s** — the skill dispatches the bridge as a foreground Bash call the harness caps at 600s; a true longer budget needs the dispatch moved to a background poll. |
| `CODEX_HOME` | respected when locating the user's `config.toml` |

(Off is recognized for `0` / `false` / `no` / `off`.)

## Verdict extraction — three channels, then validate

`--output-schema` is known to **silently degrade** (dropped on `*-codex` model slugs,
dropped when MCP servers/tools are active, leaked into intermediate messages on gpt-5.x),
so it is supplied for *shaping only*. The bridge recovers the verdict through three
fallback channels, in order, so a single-channel quirk never loses a valid reply:

1. the `--json` JSONL stream — the **last** `agent_message` event (last, not first: an
   intermediate message can carry leaked scratch while the final one is the real verdict);
2. the `--output-last-message` file;
3. fenced / embedded JSON in raw stdout.

A `turn.failed` / `error` event in the stream ⇒ `11`. The recovered JSON is then validated
against the `--kind` contract by `validate_return.py` — **that is the real gate.** On an
invalid shape the bridge **re-dispatches exactly once** with the canonical schema appended
to the prompt, then fails open (`12`) if it is still invalid.

## Model resolution — runtime, never hard-coded at a call site

Order: explicit `--model` arg → the user's `~/.codex/config.toml` (`CODEX_HOME` honored)
`model` key → the documented `DEFAULT_MODEL` constant in the bridge.

> **Model facts (version-sensitive — verify against the installed `codex --version`):**
> valid models are **`gpt-5.5`** (frontier) and **`gpt-5.4`**; **`gpt-5` and `gpt-5-codex`
> are retired** (blocked for new requests) and `latest` is not a valid identifier. The
> default constant is therefore revisitable, not load-bearing — prefer a plain `gpt-5.x`
> (non-`-codex`) slug, since `--output-schema` is dropped on `-codex` slugs.

## Output-schema authoring note

Codex routes `--output-schema` into OpenAI **strict** structured output, which requires
every property to appear in the object's `required` array and `additionalProperties:false`
on every object. The bundled `schemas/*.schema.json` therefore list **all** properties as
required — including the ones `validate_return.py` treats as optional. That only *shapes*
Codex to emit every field; `validate_return.py` remains the lenient, authoritative gate, so
a reply that omits an optional field (e.g. via a degraded schema and the fallback channels)
still validates.
