---
name: analyze-sprint
description: Read the current iteration through a tactical lens and tell the PM what the sprint will actually deliver — per-assignee working-day capacity vs assigned load, who is over-allocated, which items won't land this sprint, and a suggested rebalancing. Use when the user asks to "analyze the sprint", "is this sprint overloaded", "who's over capacity", "what won't land this sprint", "check the sprint load", or wants a current-iteration health read. READ-ONLY — it never writes a field, posts a Status update, emits/posts a digest anywhere, or schedules a cron. Reuses the working-day capacity engine. Does NOT schedule the sprint or rebalance the board (plan-sprint), file issues (create-issues), or recompute signals (sync-signals).
model: claude-opus-4-8
effort: high
allowed-tools: Bash(python3 *), Bash(gh api *), Read, AskUserQuestion
argument-hint: "--owner <org> --number <project#> --start <iter-startDate> --duration <iter-days>"
references:
  - ${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md
  - ${CLAUDE_PLUGIN_ROOT}/rules/composition.md
---

# analyze-sprint

A tactical, current-iteration read: per-assignee **capacity vs load**, who is
**over-allocated**, which items **won't land**, and a **suggested rebalancing** —
so the PM knows what the sprint will actually deliver. Thin narration over a
deterministic engine; the numbers come straight from
`${CLAUDE_PLUGIN_ROOT}/lib/sprint.py` (working-day capacity) and
`${CLAUDE_PLUGIN_ROOT}/lib/analysis.py` (the read-only board snapshot).

Let `ANALYSIS=${CLAUDE_PLUGIN_ROOT}/lib/analysis.py` and
`SPRINT=${CLAUDE_PLUGIN_ROOT}/lib/sprint.py`.

## The AI boundary (read this)

The capacity and load **math is deterministic** — working-day capacity is the same
`working_day_capacity` engine `plan-sprint` uses, and the per-item read is the
read-only `analysis.py` snapshot. This skill **only narrates and prioritizes** on
the model and **writes nothing**: no field write, no Status-update post, no digest
posted or emitted anywhere, no cron. It reads and reports to you, here, now.

Read `${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md` for the term meanings (Sprint,
Target date, Assignees, Schedule health) and
`${CLAUDE_PLUGIN_ROOT}/rules/composition.md` for the Reassign-vs-Reduce-scope
judgment when proposing a rebalance.

## 1. Working-day capacity (deterministic, no AI)

The iteration's capacity is its working-day count — the same half-open
`[start, start + duration)` convention `plan-sprint` uses:

```bash
python3 "$SPRINT" capacity --start <iter-startDate> --duration <iter-days>
```

It prints `{"working_days": N}`. That `N` is each assignee's capacity for the
iteration (one full-time dev = N working days).

## 2. Read the board (read-only) for the assigned load

```bash
python3 "$ANALYSIS" --owner <org> --number <project#>
```

It pages the board read-only (GraphQL GETs only) and prints the snapshot the load
is computed from — each item's `status`, `assignees`, `size`, `target`, and the
written signals. Treat it as ground truth; invent no values.

Compute per-assignee **load** deterministically from that snapshot: the in-sprint
items (`status` in Ready / In Progress / In Review / On Staging) assigned to each
person, weighted by `Size` (`S`=1, `M`=2, `L`=3 working days — the appetite). Load
> capacity is over-allocation.

## 3. Render the fixed skeleton

Copy the skeleton verbatim and fill each slot from the tool output — **never
invent a value**. Drop any line that does not apply.

```
## Sprint analysis — <project>
Iteration capacity: <working_days> working days/assignee  (start <start> · <duration>d)

### Capacity vs load (per assignee)
- <assignee> — load <load>d / cap <working_days>d  (<pct>%)  <OVER-ALLOCATED if load > cap>

### Won't land this sprint
- #<number> — <reason: unassigned, over-capacity owner, blocked, or overdue>   [evidence: <status/assignee/size/target>]

### Suggested rebalancing
- move #<number> from <assignee> → <assignee or backlog>  (reason)
- defer #<number> to next iteration  (reason)
```

The capacity number, the per-item snapshot, and the working-day math are the
engine's; the rebalancing suggestion is the model's narration over them (grounded
in `composition.md`). The actual rescheduling/reassignment is `plan-sprint`'s job
— this skill only reads and recommends.

## Guardrails
- **READ-ONLY.** Never write a field, post a Status update, post/emit the digest
  anywhere, or schedule a cron. `allowed-tools` carries no write verb and no
  issue-edit command.
- **No invented values.** Capacity and the per-item snapshot come from the
  engines; only the rebalancing narration is model-authored.
- **Reuses the capacity engine** — `sprint.py working_day_capacity`, the same one
  `plan-sprint` uses; this skill does not reimplement it.
- The rebalance is a **recommendation** — actually scheduling/assigning is
  `plan-sprint`. This skill never mutates the board.
- Exit codes from the engines: `0` ok · `2` usage · `3` project not found ·
  `1` unexpected.
