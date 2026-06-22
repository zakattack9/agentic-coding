---
name: analyze-board
description: Read the whole gh-projects board through one strategic lens and tell the PM/CTO what matters — the rollup health, the critical chain (release-blockers that are themselves blocked), overdue × high-blast-radius items, intake-hygiene gaps (Ready items missing an AC table / Size / Target date), unassigned in-sprint work, stalled epics, and every item whose Decision needed ≠ No decision — each line carrying its evidence and the one-command skill that resolves it. Use when the user asks to "analyze the board", "what needs my attention", "what's at risk", "give me the program rollup", "what should I decide", or wants a whole-program digest instead of reading eight views. READ-ONLY — it never writes a field, posts a Status update, emits/posts a digest anywhere, or schedules a cron. Does NOT plan the sprint (plan-sprint), file issues (create-issues), or recompute signals (sync-signals).
model: claude-opus-4-8
effort: high
allowed-tools: Bash(python3 *), Bash(gh api *), Read, AskUserQuestion
argument-hint: "--owner <org> --number <project#>"
references:
  - ${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md
  - ${CLAUDE_PLUGIN_ROOT}/rules/composition.md
---

# analyze-board

A strategic, whole-program read of the board: surface what the PM/CTO must decide
and act on **without reading every issue or view**. This is a thin narration over
a deterministic engine — every finding, its evidence, and its resolving action
come straight from `${CLAUDE_PLUGIN_ROOT}/lib/analysis.py`.

Let `ANALYSIS=${CLAUDE_PLUGIN_ROOT}/lib/analysis.py`.

## The AI boundary (read this)

The findings **math is deterministic** and lives in `analysis.py` — what fires,
the evidence it carries, the severity rank, the stable order, and the resolving
skill. This skill **only narrates, prioritizes, and explains** that output on the
model. It invents **no** values, computes **no** new findings, and (critically)
**writes nothing**: no field write, no Status-update post, no digest posted or
emitted anywhere, no cron. It reads the board and reports to you, here, now.

Before interpreting, Read `${CLAUDE_PLUGIN_ROOT}/rules/composition.md` — it is the
rule source for the epic-vs-milestone, when-to-split, intake-hygiene, and
Decision-needed interpretation — and `${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md`
for the exact term meanings (Schedule health, Blast radius, Blocked, Impact level,
Decision needed, and the orthogonal-axis disambiguation). Narrate against those
definitions, not ad-hoc judgment.

## 1. Run the engine (read-only)

```bash
python3 "$ANALYSIS" --owner <org> --number <project#>
```

It pages the board read-only (GraphQL GETs only) and prints one JSON object:

```json
{
  "project": "<org>#<number>",
  "counts": {"items": N, "overdue": N, "at_risk": N, "blocked": N, "decisions_owed": N},
  "findings": [
    {"kind": "...", "severity": N, "number": "...",
     "title": "...", "summary": "...",
     "evidence": {...the triggering numbers + field values...},
     "action": {"skill": "<resolving-skill>|null", "args": "...", "note": "..."}}
  ]
}
```

`findings` is already **ranked** (most urgent first) and **stable** — the same
board state always yields the same order. Treat this JSON as ground truth.

## 2. Render the fixed skeleton

Copy the skeleton below verbatim and fill each slot from the engine JSON —
**never invent a value**. Drop any section whose group has no findings. For each
finding, the **action** line is the one-command fix: render
`<skill> <args>` from `action.skill` + `action.args`; when `action.skill` is
`null` the finding is a PM decision — render the `action.note` (the named
`Decision needed` option) as the move owed.

```
## Board rollup — <project>
<counts.items> items · <counts.overdue> overdue · <counts.at_risk> at risk · <counts.blocked> blocked · <counts.decisions_owed> decisions owed

### Critical chain (release-blockers that are themselves blocked)
- #<number> — <summary>  → action: start-issue <args>   [evidence: <evidence>]

### Overdue × high blast radius
- #<number> — <summary>  → action: plan-sprint <args>   [evidence: <evidence>]

### Stalled epics
- #<number> — <summary>  → action: plan-sprint <args>   [evidence: <evidence>]

### Decisions owed (Decision needed ≠ No decision)
- #<number> — <summary>  → decide: <decision option owed>   [evidence: <evidence>]

### Intake-hygiene gaps (Ready items missing AC table / Size / Target date)
- #<number> — <summary>  → action: create-issues <args>   [evidence: <evidence>]

### Unassigned in-sprint work
- #<number> — <summary>  → action: plan-sprint <args>   [evidence: <evidence>]
```

Group the findings by their `kind`:
`critical_chain` → Critical chain · `overdue_high_blast` → Overdue × high blast
radius · `stalled_epic` → Stalled epics · `decision_needed` → Decisions owed ·
`intake_hygiene` → Intake-hygiene gaps · `unassigned_in_sprint` → Unassigned
in-sprint work.

## 3. Prioritize + explain

After the skeleton, add a short model-authored read: the 1–3 things to do first
and **why** (grounded in `composition.md` — e.g. a `Blocks release` chokepoint
outranks a low-blast slip; a `Reduce scope` decision protects a date). This is the
narration layer; it adds no new findings and changes no value.

## Guardrails
- **READ-ONLY.** Never write a field, post a Status update, post/emit the digest
  anywhere, or schedule a cron. `allowed-tools` carries no write verb and no
  issue-edit command — the engine reads, you report.
- **No invented values.** Every reported line comes from the engine JSON; the
  model only narrates and orders the model-authored prioritization paragraph.
- **The math is the engine's.** Findings, evidence, severity, and the resolving
  action are deterministic (`analysis.py`); this skill does not recompute them.
- Cite `composition.md` for the decision interpretation and `vocabulary.md` for
  the terms — judgment is grounded in the versioned rules, not ad-hoc.
- Exit codes from the engine: `0` ok · `2` usage · `3` project not found ·
  `1` unexpected.
