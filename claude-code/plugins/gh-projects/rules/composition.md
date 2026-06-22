# Board composition — the decision matrix

The cross-field judgment calls that no single field description can hold: when to
split work, how to structure it, and which deliberate call to record when an item
is in trouble. These are keyed on signals the board **already computes**.

This file references the board's field/option **names** but never redefines them —
`templates/project/fields.json` owns the names, and
`${CLAUDE_PLUGIN_ROOT}/rules/vocabulary.md` owns each term's meaning + the
orthogonal-axis disambiguation. It does not restate the rules with their own home:
`${CLAUDE_PLUGIN_ROOT}/rules/tier-rubric.md` (Tier → rigor),
`${CLAUDE_PLUGIN_ROOT}/rules/github-fields.md` (field homes), and
`${CLAUDE_PLUGIN_ROOT}/rules/ac-rubric.md` (the acceptance-criteria bar).

---

## Epic vs Milestone — work structure vs time boundary

These are **orthogonal**; both can apply to one issue.

- A capability that **decomposes into sub-issues**, with progress rolled up via
  Sub-issues progress → an **Epic** (a `Type`). Use it when the work is one logical
  thing that is too big to ship in a single issue and naturally breaks into parts.
- A **time / release boundary** that buckets issues toward a ship date and drives
  the Roadmap → a **Milestone**. Use it for *when*, not *what*.

They cross freely: an Epic can span several Milestones, a Milestone holds issues
from many Epics, and a single issue can belong to both. Pick the Epic for the
*structure of the work* and the Milestone for the *date it ships under* — never use
one as a substitute for the other.

## Reduce scope vs move `Target date` — protect the date or accept the slip

Triggered when `Schedule health` is `At risk` or `Overdue`. The call is keyed on
**Blast radius** plus **Schedule health**, and is **recorded** via a `Decision
needed` option — never silently both at once.

- High blast radius — `Blast radius = Blocks release` (or the item blocks a
  Milestone) → **protect the date, cut scope**. Record `Decision needed = Reduce
  scope`. The downstream cost of slipping is too high; trim the work to hold the
  line.
- Low blast radius + a soft date → **move the Target, accept the Slippage**. Record
  `Decision needed = Move date`. Nothing critical waits on it; a later date is
  cheaper than cut scope.

Make exactly one of these calls and record it. Do not quietly move the date *and*
cut scope.

## When to split

- **AC-group count ≥ 4** (which maps to `Size = L`, the cap) → split into
  **sub-issues under an Epic**, one sub-issue per AC group, with the spec's `needs`
  edges projected onto native blocked-by relationships.
- **Mixed `Type` in one issue** (e.g. a Feature bundled with a Chore) → split **by
  Type** so each issue carries a single, clean taxonomy.

Size derives from the AC-group count (`size_from_groups`): `1 → S`, `2-3 → M`,
`4+ → L`. `L` is the cap and the split signal — there is no size above it; instead,
decompose.

## `Feature` / `Bug` / `Chore` / `Infra` boundaries

- **Feature** — a new **user-facing capability** (something the product could not do
  before).
- **Bug** — a **defect in existing behavior** (it exists, but behaves wrong).
- **Chore** — **maintenance with no user-visible change** (refactors, bumps,
  cleanup).
- **Infra** — a **config-as-contract / platform** change (CI, deploy, platform
  config whose values are the contract). Treated as the full-rigor infra-spec class,
  because the configuration *is* the contract being changed.

When an item straddles two of these, it is a split signal (see *When to split*).

## Setting `Decision needed` to the right option

`Decision needed` flags a **product or architecture choice only the PM/CTO can
make**. It is **not** a dependency flag (that is `Blocked`, derived from the graph)
and **not** an effort estimate (that is `Size`). Pick the option that names the move
actually owed:

- `Move date` — push the Target date (low blast radius, soft date; see *Reduce scope
  vs move Target date*).
- `Reduce scope` — cut scope to hold the date (high blast radius; protect the date).
- `Reassign` — move the item to another owner.
- `Split` — break the item into smaller items (see *When to split*).
- `Unblock` — resolve an upstream dependency that is holding the item (the
  human-owned counterpart to a derived `Blocked` flag — someone must act to clear
  it).
- `Defer` — drop the item from the current plan.
- `No decision` — nothing pending; the default when the item needs no decision.

Set it deliberately and clear it back to `No decision` once the decision is made and acted
on.
