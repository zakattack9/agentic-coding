# Spec-ops Skill Coordination & Launch Handoff Fixes

## TL;DR
- Three field-reported fixes to the **spec-ops** plugin: **(1)** turn-end / judge-await discipline so `refine-spec`, `verify-spec`, and `orchestrate-spec` never end a turn or write their ledger's done-signal while a judge or subagent is still running; **(2)** `launch-spec`'s clipboard copy works on **Linux Mint** and other common distros; **(3)** `launch-spec` emits **ready-to-paste, prefixed** prompts (`/goal …`, `/batch …`, and an `ultracode` prompt for the dynamic-workflow driver).
- **Breaks if missed:** the coordination fix is **instructions-only** — no Stop-hook, engine, or schema code changes (AC-6). The ledger's completion fields must only be written **after both judges return** — Claude *and* Codex-when-available (AC-2, AC-4) — while an unavailable Codex is resolved immediately and never waited on (AC-5).

---

## Summary

Three problems surfaced while using the plugin, each independent:

1. **Premature turn-end / early ledger writes.** In `refine-spec` and `verify-spec` the main session sometimes tries to end its turn — or writes the ledger toward a "done" state — before the readiness/completeness judges (the Claude `Task` judge and the foreground Codex bridge) have actually returned. The Stop hook then bounces the turn with an all-flags-unmet ledger. The fix hardens the **skill instructions** (not the hooks) so the session always waits for every dispatched judge/subagent to return, and only then folds the real results into the ledger. Both judges must be reconciled before the merged verdict is written; an unavailable Codex is resolved on the spot and never blocks.

2. **Clipboard copy fails on Linux Mint.** `launch-spec` pipes the driver to the clipboard through a portable wrapper, but the fallback chain omits `xsel` (common on Cinnamon/XFCE where `xclip` may be absent) and, when nothing is installed, falls to chat-only without telling the user how to fix it.

3. **Launch output isn't paste-and-run.** The emitted `/goal` / `/batch` drivers lack their command prefix, so pasting them doesn't invoke anything; and the dynamic-workflow driver isn't emitted as a ready-to-paste `ultracode` prompt (a prior run even emitted a raw workflow script). The fix prefixes each prompt (`/goal …`, `/batch …`) and emits the dynamic-workflow driver as an `ultracode`-led prompt that opts into orchestration and runs the workflow.

The coordination fix is deliberately **instructions-only** — the Stop-hook scripts and their in-hook ledger validation stay byte-identical. Driver *selection* (which driver a given spec gets) is unchanged; only the emitted artifact's runnable form and the copy mechanism change.

---

## Acceptance Criteria

### 1. Turn-end & judge-await discipline — start here

<!-- The skills touched: refine-spec, verify-spec, orchestrate-spec, and the shared cross-model-judge reference. Instructions-only. -->

| AC  | Criterion |
| --- | --------- |
| 1   | Each of `refine-spec`, `verify-spec`, and `orchestrate-spec` instructs the main session to **wait for every dispatched unit of work — grounding `Explore` agents, the Claude judge `Task`, the Codex bridge subprocess, and any background `Bash`/Agent/workflow it launched — to return** before ending its turn; it never ends a turn with dispatched work still in flight. |
| 2   | Each skill writes its ledger's **completion / done-signal fields only after all dispatched work has returned** and each result is folded in — as a **single reconciled write**, never a partial done-signal written while a judge or subagent is still running, and never split so a Stop-hook re-entry sees a half-updated done-state. (refine: the six `gate` flags and `openQuestions[].resolved`; verify: the per-claim results — each claim's `verdict` / `evidence` / `method` / `disposition` — plus `judge.ran`, `judge.verdict`, `judge.missed`, `judge.weakEvidence`. The `backwardSweep` / `specLinkageSweep` `ran` flags are shape-only and never gate, so they aren't part of the done-signal.) |
| 3   | The Codex bridge **and** the in-session Claude judge run **synchronously in the foreground**: the skills forbid `run_in_background` on the bridge call and forbid a background/poll/`sleep` wait loop; both are issued in one turn and awaited together. (This governs the *judge* dispatch — it does **not** forbid `orchestrate-spec`'s build⇄verify Workflow, which the Workflow tool runs **asynchronously** — it returns immediately and notifies on completion — and AC-8 requires be **waited on**.) |
| 4   | On the concluding pass (refine's no-fix readiness pass / verify's completeness pass) **with Codex available**, the merged verdict is written **only after both** the Claude judge and the Codex judge have returned — a done-signal is never written off one judge while the other is still running. |
| 5   | When Codex is **unavailable** (skill-load probe not `CODEX: YES`) **or its bridge call does not succeed** (non-zero exit, a timeout/hang bounded by the bridge's own timeout, or malformed output), the Codex half is **resolved immediately** as unavailable and recorded — no lingering in-flight state; the run does **not** wait further, and the gate equals the Claude-only result. Fail-open is preserved end-to-end. |
| 6   | The fix is **instructions-only** — no code or schema file changes. `stop_refine_spec.py`, `stop_verify_spec.py`, `stop_orchestrate_spec.py`, `subagent_validate.py`, `validate_return.py`, `spec_orchestrator.py`, and both judge schemas (`judge_refine.schema.json`, `judge_verify.schema.json`) stay byte-identical. (The refine/verify ledgers are validated in Python **inside** the unchanged Stop hooks — there are no standalone ledger-schema files, so "unchanged hooks" already covers the ledger contract.) |
| 7   | As a result, a normal `refine-spec` / `verify-spec` run reaches turn-end with a **fully-reconciled ledger**, so the Stop hook does not bounce it on an all-flags-unmet / `judge.ran:false` ledger — the premature-stop symptom is gone on the happy path. |
| 8   | `orchestrate-spec` applies the same discipline to its **build⇄verify workflow stages and delegated subagents**: it does not advance a stage, write pipeline state, or end its turn while a stage, workflow, or subagent it launched is still running. |
| 20  | A judge or subagent that **errors or returns malformed output is never treated as a pass**: it is re-dispatched (the `SubagentStop` / `validate_return` backstop forces a re-emit) or its failure is explicitly recorded, and a done-signal is written only from a **validated** result. "Returned" means *a validated result **or** a definitive failure disposition* — never "dispatched". |
| 21  | On **every pass** the ledger's judge/gate state is **re-established from the current pass's actual results** — a prior pass's done-signal (especially `judge.ran` / `judge.verdict` / gate flags) is never carried forward unverified, so a stale value left after a bounced Stop hook can't leak a false "done". |
| 22  | The **await / foreground / both-judges** rules are single-sourced in the shared **`references/cross-model-judge.md`**, and refine-spec / verify-spec / orchestrate-spec **point at it** — so every consumer of that policy inherits the same wait-and-fail-open behavior rather than each restating it. |
| 23  | When Codex is unavailable or errored, the run's **handoff/summary states the review ran Claude-only** (surfacing the single bridge log line) — a fail-open outcome is **visible**, never silently masking a cross-model failure. |
| 27  | Because AC-16 changes launch-spec's ultracode output from a JS script to a prompt, **`orchestrate-spec`'s description of that output is reconciled** in the same edit: it no longer states launch-spec *emits* the `pipeline()` / `parallel()` **JS** mechanism (launch emits the **prompt/brief**; Claude authors the workflow), so the two skills no longer contradict each other. |

### 2. launch-spec clipboard copy — cross-distro

| AC  | Criterion |
| --- | --------- |
| 9   | `launch-spec`'s clipboard copy **succeeds on Linux Mint** and other common **desktop X11** distros by including **`xsel --clipboard --input`** in the fallback chain. (It does not claim universal Linux support — headless/minimal shells are handled by the graceful fallback, AC-11.) |
| 10  | The chain picks the **session-appropriate** present tool in a deterministic order — **`pbcopy`** (macOS) → **`wl-copy`** (Wayland) → **`xclip`** (X11) → **`xsel`** (X11) → **`clip.exe`** (WSL) — so a tool present but wrong for the session (e.g. `wl-copy` on an X11 session) doesn't win and swallow the copy (see *Watch out for*). |
| 11  | When the copy **doesn't land** — no tool present, a headless/remote shell, **or a present tool exits non-zero** — it **falls back to chat-only**, never reports a false success, and never blocks the handoff (the driver is still shown in chat). |
| 12  | The chat-only fallback message **names how to enable copy** (e.g. install `xclip` or `xsel`) so the user can remedy a bare box, rather than failing silently. |
| 13  | The copy still uses a **single quoted heredoc** so the driver is never written to disk and needs no escaping — `$`, backticks, and quotes pass through literally. |

### 3. launch-spec runnable output — command prefixes — needs §2

<!-- needs §2: the prefixed text is the exact text piped by the §2 copy path, so the copy mechanism must land first. -->

| AC  | Criterion |
| --- | --------- |
| 14  | The **`/goal`** driver's emitted (and copied) text **begins with `/goal `**, so a single paste into a fresh session invokes the goal command with the driver as its condition. |
| 15  | The **`/batch`** brief's emitted (and copied) text **begins with `/batch `**. |
| 16  | The **dynamic-workflow** driver emits a **runnable `ultracode`-led prompt — never a JavaScript workflow script**. **`ultracode` is the leading token**, followed by a self-contained brief that carries **every** element every driver's output carries, not just the shape-specific ones: **(a)** a read directive to the spec, **(b)** the measurable goal (every `AC-id` holds, grounded by `verify-spec`), **(c)** the **workflow shape** — phased by AC groups, with `verify-spec` as the **final and per-phase gate** (and the sibling-judge dispatch where a workflow `agent()` can't spawn a `Task`), **(d)** the spec's inlined Boundaries, **(e)** a per-phase commit-cadence instruction (scoped, citing that phase's `AC-id`s), and **(f)** the artifact-hygiene rule. A single paste opts into orchestration and Claude **authors + runs** the workflow from the brief; launch-spec never emits a literal workflow script (Claude converts the prompt internally — emit-only is preserved). |
| 17  | The text **piped to the clipboard is byte-identical** to the text shown in chat, prefix included (the exact-same-bytes guarantee holds with the prefix). |
| 18  | The per-driver **copy-confirmation and handoff messages** reflect the single-paste UX (e.g. "⌘V into a fresh session — it's already prefixed with `/goal`"), not "type `/goal` then paste". |
| 19  | The `/goal` condition **length budget (≤4,000 chars)** is honored **with the `/goal ` prefix counted in** it. If the composed `/goal ` driver would exceed the budget, that is the existing signal to **phase / escalate** (the current launch-spec behavior) — never to truncate the condition. (The `ultracode` workflow prompt is **not** a `/goal` and is **not** bound by the 4,000-char cap.) |
| 25  | The **`README.md` launch-spec example** reflects the prefixed single-paste UX — no stale `⌘V into a fresh /goal session` / "paste into /goal" phrasing that predates the prefix (the paste itself now carries `/goal `). Only the example wording changes; the README's driver-selection content is untouched. |
| 26  | launch-spec's **emit-only contract and driver *selection* are preserved**: after the change it still writes **only `tasks.md`**, uses `Bash` **solely for the clipboard copy**, **never** runs the driver / invokes `/goal` / touches git, and picks the same driver (`/goal` vs `ultracode` vs `/batch`) by the same structural signals. Only the emitted artifact's runnable form and the copy mechanism change (see *Boundaries*). |

### 4. Release

| AC  | Criterion |
| --- | --------- |
| 24  | The **plugin version is bumped** in `.claude-plugin/marketplace.json` (the repo's single source of plugin versions); **no** `version` field is added to `plugin.json`. |

---

## Turn-end & judge-await discipline (AC-1..8, AC-20..23)

**The rule, stated positively and led with the common path.** On any turn where the skill dispatches work (grounding `Explore` agents, the Claude judge `Task`, the Codex bridge `Bash` call):

1. **Dispatch, then wait.** Issue the tool calls, then **let them all return in-transcript** before you treat the turn as done. The turn is "done" only when nothing you launched is still running. *(Why: ending the turn early makes the Stop hook evaluate a ledger that doesn't yet reflect the judges' results — the bounce the user saw.)*
2. **Write the ledger last.** Set the ledger's done-signal fields (refine `gate` flags / `openQuestions[].resolved`; verify the per-claim results + `judge.*` — the `backwardSweep` / `specLinkageSweep` `ran` flags are shape-only and don't gate) **only after** every dispatched judge/subagent has returned and you have folded its **actual** result in. Never write them optimistically while work is in flight. *(Why: a ledger written before the judge returns is a claim you can't back — and, on release, would let a premature stop pass.)*
3. **Foreground only.** Run the Codex bridge as a single **synchronous foreground** `Bash` call and the Claude judge as a `Task` — **never** `run_in_background`, and **never** a poll/`sleep` loop. Issuing both in one turn is what makes them concurrent; the harness already awaits both. *(Why: a backgrounded judge lets the turn end while Codex is still running.)*
4. **Both judges before the merge.** On the concluding pass, when Codex is available, write the merged verdict **only after both** judges return; a done-signal off the Claude judge alone, while Codex is still running, is forbidden.
5. **Unavailable Codex resolves immediately.** If the skill-load probe isn't `CODEX: YES`, or the bridge exits non-zero / hangs to its own timeout / returns malformed output / can't run, the Codex half is **done now** — record it as unavailable (fail-open) and proceed Claude-only. **Do not wait** on a judge that never launched, and leave **no in-flight marker** behind (AC-5). Say so in the handoff (AC-23) — a fail-open must be visible, not silent.
6. **A failed judge isn't a pass.** If a judge or subagent errors or returns malformed output, re-dispatch it (the `SubagentStop` / `validate_return` backstop forces a re-emit) or record the failure — never write a done-signal off a result you couldn't validate. "Returned" = a *validated* result **or** a *definitive failure*, not "dispatched" (AC-20).
7. **Re-establish state each pass.** Rewrite the ledger's judge / gate state from *this* pass's actual results; never carry a prior pass's `judge.ran` / `verdict` / gate flags forward unverified, so a stale value left by a bounced Stop can't leak a false "done" (AC-21).

**What "in flight" covers:** any `Task` subagent, any `agent()` workflow stage, the `codex_bridge.py` subprocess, and any `Bash`/Agent you dispatched with `run_in_background`. The discipline is the same for all: the session doesn't end its turn, and doesn't advance ledger/pipeline state, until they've returned.

**Single-source the policy.** These await / foreground / both-judges rules live in `references/cross-model-judge.md`; refine-spec, verify-spec, and orchestrate-spec **point at it** rather than each restating them, so the behavior can't drift between skills (AC-22).

This is an **instruction** change (AC-6) — the Stop hooks stay as they are. Their block-on-incomplete-ledger behavior is correct; the point is to stop *reaching* them with an incomplete ledger, and to never write a done-signal the judges haven't earned. **Accepted limitation:** instructions-only cannot make this race-*proof* — the Stop hooks can't observe whether a subprocess is truly still running, so they remain the **backstop** (they still bounce an incomplete ledger), while this discipline is what keeps the happy path from reaching them prematurely.

---

## launch-spec clipboard copy (AC-9..13)

Target fallback chain (first **session-appropriate** tool present wins), replacing the current four-tool chain:

```bash
{ if   command -v pbcopy   >/dev/null 2>&1; then pbcopy                                                   # macOS
  elif [ -n "$WAYLAND_DISPLAY" ] && command -v wl-copy >/dev/null 2>&1; then wl-copy                       # Wayland
  elif [ -n "$DISPLAY" ]        && command -v xclip   >/dev/null 2>&1; then xclip -selection clipboard     # X11
  elif [ -n "$DISPLAY" ]        && command -v xsel    >/dev/null 2>&1; then xsel --clipboard --input       # X11 (Mint/XFCE)
  elif command -v clip.exe >/dev/null 2>&1; then clip.exe                                                  # WSL
  else cat >/dev/null; exit 3; fi; } <<'LAUNCH_SPEC_EOF'
…the driver prompt, verbatim (already command-prefixed — see AC-14..16)…
LAUNCH_SPEC_EOF
```

The `wl-copy` / `xclip` / `xsel` branches are **gated on the session's display env** (`$WAYLAND_DISPLAY` / `$DISPLAY`) so a tool present but wrong for the session doesn't win and swallow the copy (AC-10). A single-feed heredoc pipes to exactly one chosen tool — it can't retry a second — so **selection** is what has to be right; a chosen tool that still exits non-zero degrades to chat-only (AC-11).

- On success, print the per-driver confirmation (AC-18).
- On `exit 3` (no tool) or any non-zero, fall back to chat-only and say so, **and name the remedy** (AC-12): e.g. *"No clipboard tool found — copy the prompt above manually, or `sudo apt install xclip` (or `xsel`) to enable one-key copy."*

---

## launch-spec runnable output (AC-14..19)

The copied/shown text is the **exact** driver, now command-prefixed so a single paste runs it:

| Driver | Emitted text begins with | How the user runs it |
| --- | --- | --- |
| **`/goal`** (default) | `/goal ` + the ≤4,000-char condition | Paste into a fresh session — it invokes `/goal` directly. Pair with auto mode. |
| **`/batch`** | `/batch ` + the batch brief | Paste into a fresh session — it invokes `/batch` directly. |
| **dynamic workflow** (ultracode) | `ultracode` + a workflow brief (read-directive · goal · shape · boundaries · commit cadence · artifact hygiene · `verify-spec` gate) | Paste into a fresh session — the `ultracode` keyword opts into multi-agent orchestration and Claude authors + runs the workflow from the brief. |

**Runnable trigger.** Per Claude Code's docs, the **`ultracode` keyword** in a pasted prompt is the entrypoint for dynamic multi-agent orchestration: Claude highlights it, **authors a workflow for the task, and runs it** (a session-level `/effort ultracode` does the same for every task). A *pre-authored* script could instead be saved under `.claude/workflows/<name>` and invoked as the slash command `/<name>` — but that writes a file into the repo, **outside `launch-spec`'s emit-only write boundary** (`tasks.md` only). So the dynamic-workflow driver is emitted as an **`ultracode`-led prompt** (read-directive + goal + workflow shape + boundaries + commit cadence + artifact hygiene + `verify-spec` gate), **not a workflow script**: a single paste that opts into orchestration and lets Claude author + run the intended workflow, keeping `launch-spec` emit-only. Emitting a literal script is both unnecessary (Claude converts the prompt internally) and inconsistent with emit-only.

---

## Current state → Target

| Behavior | Current | Target |
| --- | --- | --- |
| refine/verify turn-end | can end turn / write ledger before judges return → Stop-hook bounce | waits for all judges/subagents; writes ledger last (AC-1, AC-2, AC-7) |
| both judges on final pass | merged verdict can be written off one judge | written only after both return; unavailable Codex resolved immediately (AC-4, AC-5) |
| Codex bridge dispatch | policy says foreground; prose lets it slip | foreground/synchronous is an explicit, unmissable rule (AC-3) |
| launch copy on Mint | `xclip`-only X11 path; chat-only fallback with **no install remedy** | `xsel` added + session-gated; fallback names the fix (AC-9, AC-10, AC-12) |
| launch prompt | no command prefix; workflow not emitted as a paste-ready prompt | `/goal …` / `/batch …` / `ultracode`-led runnable prompt (AC-14..16) |

---

## Watch out for

- **Instruction-only enforcement is soft — the prose must lead with the positive/common path and stay terse.** A verbose, negative-heavy framing has previously flipped the model onto the failure branch on the happy path. State the await rule as a short, positively-led, decomposed list (each item `imperative — why`), not a defensive wall.
- **Don't treat an unavailable Codex as "still pending."** The both-judges-await rule waits only when Codex actually launched (probe `CODEX: YES` **and** a running bridge call). Otherwise it's resolved now — waiting on a judge that never started would hang the run (AC-5).
- **Adding `xsel` doesn't help a box with no X11 clipboard tool installed** — the graceful chat-only fallback **plus the install hint** (AC-12) is the real remedy there.
- **Mixed clipboard environments.** A tool can be *present but wrong for the session* — e.g. `wl-copy` installed on an X11 login: a naive "first present wins" chain would pick it and the copy would silently fail. Gate the `wl-copy` / `xclip` / `xsel` branches on the session's display env (`$WAYLAND_DISPLAY` / `$DISPLAY`) so the **session-appropriate** tool is chosen and the copy lands (AC-10). Note the single-feed heredoc can't "fall through" to the next tool after a failed copy (stdin is consumed once), so getting the *selection* right up front is the fix — a chosen-but-broken tool just degrades to chat-only (AC-11).
- **"Foreground" scopes to the judge dispatch, not a ban on async work.** The Codex bridge + Claude judge run foreground (AC-3); `orchestrate-spec` still runs its build⇄verify **Workflow** — which the Workflow tool runs **asynchronously** (returns immediately, notifies on completion) — and the rule there is to **wait on it** (AC-8), not to forbid it.
- **Don't treat "instructions-only" as race-proof.** The chosen approach can't guarantee the hook sees in-flight vs done; the Stop hooks stay the backstop. This is the accepted trade-off of the instructions-only decision.
- **The `/goal` char budget includes the prefix.** `/goal ` is ~6 chars; keep the whole paste ≤4,000, and let an over-budget driver escalate to phasing rather than truncating (AC-19).
- **AC-27 is a real cross-skill landmine, not polish.** `orchestrate-spec/SKILL.md` already has two adjacent lines that disagree — one calls launch's ultracode driver the thing that *emits* `pipeline()` / `parallel()` **JS**, the next says it "emits a prompt/brief." AC-16 settles it (launch emits the brief; Claude authors the JS), so fix the stale JS line in the **same edit** or `verify-spec` will surface the contradiction (AC-27).
- **AC-16's content list is easy to under-implement.** A dev fixing only the prompt-vs-script format bug can satisfy (a)/(b)/(c) while quietly dropping boundaries, commit cadence, and artifact hygiene from the ultracode brief specifically — those three are the ones most often missing from a real ultracode-driver emission even when they're present in the very same run's `/goal` output. Implement (d)/(e)/(f) as part of the same template, not as an afterthought.
- **The driver-selection preview must match the final artifact's form.** `launch-spec` previews the `ultracode` option (e.g. via `AskUserQuestion`) before compiling the final brief. That preview needs the same natural-language, never-a-script treatment as the compiled output (AC-16) — a script-shaped preview primes the wrong mental model even if the final paste is corrected, and risks the final compile copying the preview's (wrong) shape.

---

## Boundaries

- **Instructions-only for the coordination fix (§1).** Do **not** edit any hook or engine script (`stop_refine_spec.py`, `stop_verify_spec.py`, `stop_orchestrate_spec.py`, `subagent_validate.py`, `validate_return.py`, `spec_orchestrator.py`) or any judge schema (`schemas/*.json`) — the refine/verify ledgers are validated in-Python inside those unchanged hooks, so there's no separate ledger schema to touch. §1 changes only the `refine-spec` / `verify-spec` / `orchestrate-spec` `SKILL.md`s and `references/cross-model-judge.md`.
- **Whole-spec file scope.** Across all four sections, the *only* files that change are: the three §1 `SKILL.md`s + `references/cross-model-judge.md` (§1), `launch-spec/SKILL.md` (§2–§3), `README.md` (AC-25), and `marketplace.json` (AC-24). **No code or schema file changes anywhere** — that byte-identity is AC-6's diff test.
- **Don't change driver *selection*.** Which driver a spec gets (`/goal` vs `ultracode` vs `/batch`) is out of scope — only the emitted artifact's **runnable form** and the **copy mechanism** change.
- **Don't touch the cross-model semantics.** The AND-merge, severity gating, and fail-open behavior stay exactly as-is — this change neither strengthens nor weakens them. That means an **available** Codex judge can still withhold a gate flag on a `CRITICAL` finding (AND-merge), while an **absent / denied / failed** Codex never blocks a gate (fail-open — Codex is optional and never *required*, but it is not "advisory-only" when present).
- **launch-spec stays emit-only.** `Bash` remains for the clipboard copy only; never run the driver, invoke `/goal`, or touch git/the project. `Write` is still only `tasks.md`.
- **No new git behavior.** No pushes, no broadened staging. (Version-bump end-state is AC-24.)
- **Respect the SKILL.md size budget** — the Read tool hard-errors past ~10k tokens; if a skill nears the budget, push detail into `references/` behind a one-level pointer rather than inflating the body.

---

## Checklist

### For agents
- [ ] Each of the three skills carries the explicit await/foreground rule and writes its ledger last as one reconciled write — AC-1, AC-2, AC-3, AC-4, AC-8
- [ ] A failed/malformed judge is re-dispatched or recorded, never a pass; each pass re-establishes judge state from that pass — AC-20, AC-21
- [ ] The await/foreground/both-judges policy is single-sourced in `references/cross-model-judge.md` and the three skills point at it — AC-22
- [ ] `orchestrate-spec` no longer describes launch's ultracode output as emitted JS — its two lines agree that launch emits the prompt/brief — AC-27
- [ ] Diff proves every hook/engine script (`stop_*`, `subagent_validate.py`, `validate_return.py`, `spec_orchestrator.py`) and both judge schemas are byte-unchanged; the only changed files are the four touched `SKILL.md`s (refine/verify/orchestrate/launch) + `cross-model-judge.md` + `README.md` + `marketplace.json` — AC-6
- [ ] The copy uses a **single quoted heredoc** — driver never written to disk, `$`/backticks/quotes pass through literally — AC-13
- [ ] launch-spec still writes only `tasks.md`, `Bash` only for the copy, never runs the driver / touches git, and picks the same driver by the same signals — AC-26
- [ ] `command -v` a machine with only `xsel` (no `xclip`): the copy chain still lands the driver; a session-wrong tool (e.g. `wl-copy` on X11) doesn't swallow the copy — AC-9, AC-10
- [ ] With no clipboard tool, or a present tool that exits non-zero, the run prints the manual-copy + install-hint message, reports no false success, and still shows the driver — AC-11, AC-12
- [ ] Emitted `/goal` / `/batch` text starts with the literal prefix and the clipboard bytes equal the chat bytes — AC-14, AC-15, AC-17
- [ ] Emitted workflow driver is a runnable `ultracode`-led prompt (read-directive · goal · workflow shape · boundaries · commit cadence · artifact hygiene · `verify-spec` gate), **not** a JS workflow script — AC-16
- [ ] A sample `/goal` driver + prefix is ≤4,000 chars (over-budget escalates, not truncates) — AC-19
- [ ] The `README.md` launch-spec example reflects the prefixed single-paste UX — AC-25
- [ ] `marketplace.json` version bumped (current `0.30.0`); no `version` added to `plugin.json` — AC-24

### For humans
- [ ] Run `refine-spec` on a small spec through to ready: the run never shows the "loop is still active … all flags unmet" bounce, and finishes only after you see both judges report — AC-4, AC-7
- [ ] With Codex on, the ready summary states both judges ran; with Codex off (`SPEC_OPS_CODEX=0`) it finishes Claude-only without hanging, and the summary says the review was Claude-only — AC-5, AC-23
- [ ] On Linux Mint (or any X11 box with `xsel`), run `launch-spec` and press ⌘/Ctrl-V into a fresh session — the driver pastes and is already prefixed with `/goal` — AC-9, AC-14, AC-18
- [ ] Choose a spec that lands the `ultracode` driver; the copied prompt is an `ultracode`-led brief (not a JS script) that, when pasted, makes Claude author + run the workflow — AC-16
