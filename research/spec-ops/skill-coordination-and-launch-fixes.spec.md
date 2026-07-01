# Spec-ops Skill Coordination & Launch Handoff Fixes

## TL;DR
- Three field-reported fixes to the **spec-ops** plugin: **(1)** turn-end / judge-await discipline so `refine-spec`, `verify-spec`, and `orchestrate-spec` never end a turn or write their ledger's done-signal while a judge or subagent is still running; **(2)** `launch-spec`'s clipboard copy works on **Linux Mint** and other common distros; **(3)** `launch-spec` emits **ready-to-paste, prefixed** prompts (`/goal …`, `/batch …`, and an `ultracode` prompt for the dynamic-workflow driver).
- **Breaks if missed:** the coordination fix is **instructions-only** — no ledger-schema or Stop-hook code changes (AC-6). The ledger's completion fields must only be written **after both judges return** — Claude *and* Codex-when-available (AC-2, AC-4) — while an unavailable Codex is resolved immediately and never waited on (AC-5).

---

## Summary

Three problems surfaced while using the plugin, each independent:

1. **Premature turn-end / early ledger writes.** In `refine-spec` and `verify-spec` the main session sometimes tries to end its turn — or writes the ledger toward a "done" state — before the readiness/completeness judges (the Claude `Task` judge and the foreground Codex bridge) have actually returned. The Stop hook then bounces the turn with an all-flags-unmet ledger. The fix hardens the **skill instructions** (not the hooks) so the session always waits for every dispatched judge/subagent to return, and only then folds the real results into the ledger. Both judges must be reconciled before the merged verdict is written; an unavailable Codex is resolved on the spot and never blocks.

2. **Clipboard copy fails on Linux Mint.** `launch-spec` pipes the driver to the clipboard through a portable wrapper, but the fallback chain omits `xsel` (common on Cinnamon/XFCE where `xclip` may be absent) and, when nothing is installed, falls to chat-only without telling the user how to fix it.

3. **Launch output isn't paste-and-run.** The emitted `/goal` / `/batch` drivers lack their command prefix, so pasting them doesn't invoke anything; and the dynamic-workflow driver emits a bare script with no runnable wrapper. The fix prefixes each prompt (`/goal …`, `/batch …`) and wraps the workflow driver in an `ultracode` prompt that actually runs it.

The coordination fix is deliberately **instructions-only** — the Stop-hook scripts and ledger schemas stay byte-identical. Driver *selection* (which driver a given spec gets) is unchanged; only the emitted artifact's runnable form and the copy mechanism change.

---

## Acceptance Criteria

### 1. Turn-end & judge-await discipline — start here

<!-- The skills touched: refine-spec, verify-spec, orchestrate-spec, and the shared cross-model-judge reference. Instructions-only. -->

| AC  | Criterion |
| --- | --------- |
| 1   | Each of `refine-spec`, `verify-spec`, and `orchestrate-spec` instructs the main session to **wait for every dispatched unit of work — grounding `Explore` agents, the Claude judge `Task`, the Codex bridge subprocess, and any background `Bash`/Agent/workflow it launched — to return** before ending its turn; it never ends a turn with dispatched work still in flight. |
| 2   | Each skill writes its ledger's **completion / done-signal fields only after all dispatched work has returned** and each result is folded in — as a **single reconciled write**, never a partial done-signal written while a judge or subagent is still running, and never split so a Stop-hook re-entry sees a half-updated done-state. (refine: the six `gate` flags and `openQuestions[].resolved`; verify: `judge.ran`, `judge.verdict`, `judge.missed`, `judge.weakEvidence`, and each sweep's `ran` flag.) |
| 3   | The Codex bridge **and** the in-session Claude judge run **synchronously in the foreground**: the skills forbid `run_in_background` on the bridge call and forbid a background/poll/`sleep` wait loop; both are issued in one turn and awaited together. (This governs the *judge* dispatch — it does **not** forbid `orchestrate-spec`'s legitimately-backgrounded build⇄verify Workflow, which AC-8 requires be **waited on**.) |
| 4   | On the concluding pass (refine's no-fix readiness pass / verify's completeness pass) **with Codex available**, the merged verdict is written **only after both** the Claude judge and the Codex judge have returned — a done-signal is never written off one judge while the other is still running. |
| 5   | When Codex is **unavailable** (skill-load probe not `CODEX: YES`) **or its bridge call does not succeed** (non-zero exit, a timeout/hang bounded by the bridge's own timeout, or malformed output), the Codex half is **resolved immediately** as unavailable and recorded — no lingering in-flight state; the run does **not** wait further, and the gate equals the Claude-only result. Fail-open is preserved end-to-end. |
| 6   | The fix is **instructions-only**: `stop_refine_spec.py`, `stop_verify_spec.py`, `stop_orchestrate_spec.py`, `subagent_validate.py`, and both ledger/judge JSON schemas are unchanged. |
| 7   | As a result, a normal `refine-spec` / `verify-spec` run reaches turn-end with a **fully-reconciled ledger**, so the Stop hook does not bounce it on an all-flags-unmet / `judge.ran:false` ledger — the premature-stop symptom is gone on the happy path. |
| 8   | `orchestrate-spec` applies the same discipline to its **build⇄verify workflow stages and delegated subagents**: it does not advance a stage, write pipeline state, or end its turn while a stage, workflow, or subagent it launched is still running. |
| 20  | A judge or subagent that **errors or returns malformed output is never treated as a pass**: it is re-dispatched (the `SubagentStop` / `validate_return` backstop forces a re-emit) or its failure is explicitly recorded, and a done-signal is written only from a **validated** result. "Returned" means *a validated result **or** a definitive failure disposition* — never "dispatched". |
| 21  | On **every pass** the ledger's judge/gate state is **re-established from the current pass's actual results** — a prior pass's done-signal (especially `judge.ran` / `judge.verdict` / gate flags) is never carried forward unverified, so a stale value left after a bounced Stop hook can't leak a false "done". |
| 22  | The **await / foreground / both-judges** rules are single-sourced in the shared **`references/cross-model-judge.md`**, and refine-spec / verify-spec / orchestrate-spec **point at it** — so every consumer of that policy inherits the same wait-and-fail-open behavior rather than each restating it. |
| 23  | When Codex is unavailable or errored, the run's **handoff/summary states the review ran Claude-only** (surfacing the single bridge log line) — a fail-open outcome is **visible**, never silently masking a cross-model failure. |

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
| 16  | The **dynamic-workflow** driver emits a **runnable `ultracode` prompt**: **`ultracode` is the leading token**, and it **carries the pre-authored workflow script inline verbatim** (fidelity preserved — not truncated or reformatted) with an instruction to run it, so a single paste opts into orchestration and executes *that* workflow — not a bare, contextless script and not a re-derived one. |
| 17  | The text **piped to the clipboard is byte-identical** to the text shown in chat, prefix included (the exact-same-bytes guarantee holds with the prefix). |
| 18  | The per-driver **copy-confirmation and handoff messages** reflect the single-paste UX (e.g. "⌘V into a fresh session — it's already prefixed with `/goal`"), not "type `/goal` then paste". |
| 19  | The `/goal` condition **length budget (≤4,000 chars)** is honored **with the `/goal ` prefix counted in** it. If the composed `/goal ` driver would exceed the budget, that is the existing signal to **phase / escalate** (the current launch-spec behavior) — never to truncate the condition. (The `ultracode` inline-script prompt is **not** a `/goal` and is **not** bound by the 4,000-char cap.) |

### 4. Release

| AC  | Criterion |
| --- | --------- |
| 24  | The **plugin version is bumped** in `.claude-plugin/marketplace.json` (the repo's single source of plugin versions); **no** `version` field is added to `plugin.json`. |

---

## Turn-end & judge-await discipline (AC-1..8, AC-20..23)

**The rule, stated positively and led with the common path.** On any turn where the skill dispatches work (grounding `Explore` agents, the Claude judge `Task`, the Codex bridge `Bash` call):

1. **Dispatch, then wait.** Issue the tool calls, then **let them all return in-transcript** before you treat the turn as done. The turn is "done" only when nothing you launched is still running. *(Why: ending the turn early makes the Stop hook evaluate a ledger that doesn't yet reflect the judges' results — the bounce the user saw.)*
2. **Write the ledger last.** Set the ledger's done-signal fields (refine `gate` flags / `openQuestions[].resolved`; verify `judge.*` and each sweep's `ran`) **only after** every dispatched judge/subagent has returned and you have folded its **actual** result in. Never write them optimistically while work is in flight. *(Why: a ledger written before the judge returns is a claim you can't back — and, on release, would let a premature stop pass.)*
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

Target fallback chain (first present wins), replacing the current four-tool chain:

```bash
{ if   command -v pbcopy   >/dev/null 2>&1; then pbcopy                        # macOS
  elif command -v wl-copy  >/dev/null 2>&1; then wl-copy                       # Wayland
  elif command -v xclip    >/dev/null 2>&1; then xclip -selection clipboard    # X11
  elif command -v xsel     >/dev/null 2>&1; then xsel --clipboard --input      # X11 (Mint/XFCE)
  elif command -v clip.exe >/dev/null 2>&1; then clip.exe                      # WSL
  else cat >/dev/null; exit 3; fi; } <<'LAUNCH_SPEC_EOF'
…the driver prompt, verbatim (already command-prefixed — see AC-14..16)…
LAUNCH_SPEC_EOF
```

- On success, print the per-driver confirmation (AC-18).
- On `exit 3` (no tool) or any non-zero, fall back to chat-only and say so, **and name the remedy** (AC-12): e.g. *"No clipboard tool found — copy the prompt above manually, or `sudo apt install xclip` (or `xsel`) to enable one-key copy."*

---

## launch-spec runnable output (AC-14..19)

The copied/shown text is the **exact** driver, now command-prefixed so a single paste runs it:

| Driver | Emitted text begins with | How the user runs it |
| --- | --- | --- |
| **`/goal`** (default) | `/goal ` + the ≤4,000-char condition | Paste into a fresh session — it invokes `/goal` directly. Pair with auto mode. |
| **`/batch`** | `/batch ` + the batch brief | Paste into a fresh session — it invokes `/batch` directly. |
| **dynamic workflow** (ultracode) | `ultracode` + the workflow script inline + "run this workflow" | Paste into a fresh session — the `ultracode` keyword opts into multi-agent orchestration and Claude runs the provided script. |

**Runnable trigger (grounded).** In Claude Code the **`ultracode` keyword** in a prompt is the entrypoint that opts a task into dynamic multi-agent orchestration (Claude authors and runs a workflow; a session-level `/effort ultracode` also exists). A *pre-authored* script can alternatively be saved to `.claude/workflows/<name>.js` and invoked as the slash command `/<name>` — but that requires writing a file into the repo, which is **outside `launch-spec`'s emit-only write boundary** (`tasks.md` only). So the emitted artifact leads with `ultracode` and **includes the script inline** with a "run this workflow" instruction, keeping `launch-spec` emit-only while still being a single paste that runs the exact composed workflow.

---

## Current state → Target

| Behavior | Current | Target |
| --- | --- | --- |
| refine/verify turn-end | can end turn / write ledger before judges return → Stop-hook bounce | waits for all judges/subagents; writes ledger last (AC-1, AC-2, AC-7) |
| both judges on final pass | merged verdict can be written off one judge | written only after both return; unavailable Codex resolved immediately (AC-4, AC-5) |
| Codex bridge dispatch | policy says foreground; prose lets it slip | foreground/synchronous is an explicit, unmissable rule (AC-3) |
| launch copy on Mint | `xclip`-only X11 path; silent chat-only fallback | `xsel` added; fallback names the fix (AC-9, AC-12) |
| launch prompt | no command prefix; workflow is a bare script | `/goal …` / `/batch …` / `ultracode` runnable prompt (AC-14..16) |

---

## Watch out for

- **Instruction-only enforcement is soft — the prose must lead with the positive/common path and stay terse.** A verbose, negative-heavy framing has previously flipped the model onto the failure branch on the happy path. State the await rule as a short, positively-led, decomposed list (each item `imperative — why`), not a defensive wall.
- **Don't treat an unavailable Codex as "still pending."** The both-judges-await rule waits only when Codex actually launched (probe `CODEX: YES` **and** a running bridge call). Otherwise it's resolved now — waiting on a judge that never started would hang the run (AC-5).
- **Adding `xsel` doesn't help a box with no X11 clipboard tool installed** — the graceful chat-only fallback **plus the install hint** (AC-12) is the real remedy there.
- **Mixed clipboard environments.** A tool can be *present but wrong for the session* — e.g. `wl-copy` installed on an X11 login: a naive "first present wins" chain would pick it and the copy would silently fail. Pick the **session-appropriate** tool (env-detect `WAYLAND_DISPLAY` / `DISPLAY`, or fall through to the next tool on a non-zero copy) so the copy actually lands (AC-10, AC-11).
- **"Foreground" scopes to the judge dispatch, not a ban on background work.** The Codex bridge + Claude judge run foreground (AC-3); `orchestrate-spec` still runs its build⇄verify **Workflow in the background** — the rule there is to **wait on it** (AC-8), not to forbid it.
- **Don't treat "instructions-only" as race-proof.** The chosen approach can't guarantee the hook sees in-flight vs done; the Stop hooks stay the backstop. This is the accepted trade-off of the instructions-only decision.
- **The `/goal` char budget includes the prefix.** `/goal ` is ~6 chars; keep the whole paste ≤4,000, and let an over-budget driver escalate to phasing rather than truncating (AC-19).

---

## Boundaries

- **Instructions-only for the coordination fix.** Do **not** edit `stop_refine_spec.py`, `stop_verify_spec.py`, `stop_orchestrate_spec.py`, `subagent_validate.py`, or any ledger/judge JSON schema. The user explicitly chose the instructions-only approach.
- **Don't change driver *selection*.** Which driver a spec gets (`/goal` vs `ultracode` vs `/batch`) is out of scope — only the emitted artifact's **runnable form** and the **copy mechanism** change.
- **Don't touch the cross-model semantics.** The AND-merge, severity gating, and fail-open behavior stay as-is; Codex remains optional and **never** gates any readiness/completeness check.
- **launch-spec stays emit-only.** `Bash` remains for the clipboard copy only; never run the driver, invoke `/goal`, or touch git/the project. `Write` is still only `tasks.md`.
- **No new git behavior.** No pushes, no broadened staging. (Version-bump end-state is AC-24.)
- **Respect the SKILL.md size budget** — the Read tool hard-errors past ~10k tokens; if a skill nears the budget, push detail into `references/` behind a one-level pointer rather than inflating the body.

---

## Checklist

### For agents
- [ ] Each of the three skills carries the explicit await/foreground rule and writes its ledger last as one reconciled write — AC-1, AC-2, AC-3, AC-4, AC-8
- [ ] A failed/malformed judge is re-dispatched or recorded, never a pass; each pass re-establishes judge state from that pass — AC-20, AC-21
- [ ] The await/foreground/both-judges policy is single-sourced in `references/cross-model-judge.md` and the three skills point at it — AC-22
- [ ] Diff proves the four hook scripts + both schemas are byte-unchanged — AC-6
- [ ] `command -v` a machine with only `xsel` (no `xclip`): the copy chain still lands the driver; a session-wrong tool (e.g. `wl-copy` on X11) doesn't swallow the copy — AC-9, AC-10
- [ ] With no clipboard tool, or a present tool that exits non-zero, the run prints the manual-copy + install-hint message, reports no false success, and still shows the driver — AC-11, AC-12
- [ ] Emitted `/goal` / `/batch` text starts with the literal prefix and the clipboard bytes equal the chat bytes — AC-14, AC-15, AC-17
- [ ] Emitted workflow driver is a runnable `ultracode`-led prompt carrying the script inline verbatim — AC-16
- [ ] A sample `/goal` driver + prefix is ≤4,000 chars (over-budget escalates, not truncates) — AC-19
- [ ] `marketplace.json` version bumped; no `version` added to `plugin.json` — AC-24

### For humans
- [ ] Run `refine-spec` on a small spec through to ready: the run never shows the "loop is still active … all flags unmet" bounce, and finishes only after you see both judges report — AC-4, AC-7
- [ ] With Codex on, the ready summary states both judges ran; with Codex off (`SPEC_OPS_CODEX=0`) it finishes Claude-only without hanging, and the summary says the review was Claude-only — AC-5, AC-23
- [ ] On Linux Mint (or any X11 box with `xsel`), run `launch-spec` and press ⌘/Ctrl-V into a fresh session — the driver pastes and is already prefixed with `/goal` — AC-9, AC-14, AC-18
- [ ] Choose a spec that lands the `ultracode` driver; the copied prompt runs the workflow when pasted (uses the `ultracode` keyword) — AC-16
