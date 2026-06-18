# Tier rubric — T1 / T2 / T3

`Tier` is a Project single-select set by `intake-issues`. It picks the spec-ops
`write-spec` **rigor dial** and decides whether a linked deep spec is required.
There is no separate `Rigor` field — `Tier` is the single rigor knob.

| Tier | When | `write-spec` rigor | Artifact | Deep spec? |
|---|---|---|---|---|
| **T1 trivial** | a one-liner / obvious change, no hidden coupling | `light` | AC table only (≈ the issue body) | No |
| **T2 standard** | a normal feature/bug with a clear blast radius | `standard` | TL;DR + AC + Boundaries + lean body | No |
| **T3 complex** | cross-cutting, risky, or `Type=Infra`; needs grounding + a build order | `full` + `refine-spec` | self-contained deep spec → linked `specs/<slug>.md` | Yes |

## Delegation

- **Author body + AC** → `spec-ops:write-spec` **at the tier's rigor**
  (`T1 → light` · `T2 → standard` · `T3 → full`). Light/standard becomes the issue
  body; full becomes the linked deep spec.
- **T3 only — harden + commit the group DAG** → `spec-ops:refine-spec`. It returns
  "ready" / `ac_complete` + grounded `needs §X` groups → flip `Ready`, set the
  sub-issue blocked-by edges. When `Type=Infra`, the spec is the
  **infra/config-as-contract** class.
- **Verify impl vs AC** → `spec-ops:verify-spec`.

## Boundaries of the delegation

- The **`AC-id` contract + spec/AC format are the pinned, stable interface.**
  spec-ops internals may churn without breaking gh-projects.
- **Not delegated:** `launch-spec` (the HOW). Implementation stays the dev's free
  choice — gh-projects never dictates how to implement and never depends on
  `launch-spec`.
- gh-projects owns **all** GitHub writes (branch / issue / board); spec-ops never
  touches a branch, issue, or board.
