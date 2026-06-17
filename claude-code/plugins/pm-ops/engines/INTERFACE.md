# Board engine contract

A **board engine** projects pm-ops's canonical markdown artifacts onto an external
tracker (issues + board). The core is board-agnostic: it only ever produces a
**normalized task** (JSON) and calls an engine. Swap boards by changing `engine`
in a repo's `.pm-ops/config.json` — no skill or core change required.

## Anatomy

```
engines/<name>/
├── engine            # executable entrypoint (any language; shebang + chmod +x)
└── capabilities.json # what this board supports (informational + degradation hints)
```

`lib/engine-dispatch.sh <verb> [--apply] [args]` reads the repo's configured
`engine`, then execs `engines/<engine>/engine <verb> ...`, passing stdin and args
through and exporting `PM_OPS_REPO` (the resolved PM-repo root).

## Verbs

Every engine MUST implement these. The **normalized task JSON** arrives on stdin
for `upsert` / `link` / `set-status` / `sync`. Each verb writes **one result JSON
object to stdout** and human-readable plan/log to stderr.

| Verb | stdin | Does | Result JSON |
|------|-------|------|-------------|
| `capabilities` | — | Print this board's capability manifest | the manifest |
| `upsert` | task | Create or update the tracker item; place it on the board; set fields | `{ref, url, applied, actions[], plan[], warnings[]}` |
| `link` | task + `parent_ref`, `blocked_by_refs[]` | Set hierarchy + dependency links | `{ref, applied, actions[], warnings[]}` |
| `set-status` | task (needs `board.ref`/`url` + `status`) | Move the item to the mapped column/state | `{ref, applied, actions[], warnings[]}` |
| `sync` | task (needs `board.ref`) | Read-only: return the item's current external state | `{ref, state}` |

## Dry-by-default

`upsert` / `link` / `set-status` MUST change nothing unless `--apply` is passed.
Without it, populate `plan[]` with exactly what would run and return `applied:false`.
This is the safety rail route-task relies on (it previews, then applies on confirm).

## Normalized task

Produced by `lib/pm.py normalize <file>` from an artifact's front-matter, then
augmented by route-task before it reaches the engine:

```json
{
  "id": "PM-0042",
  "title": "Bulk discount rules",
  "type": "feature",
  "status": "active",
  "size": "L",
  "priority": "P1",
  "rigor": "full",
  "parent": "PM-0007",
  "depends_on": ["PM-0039"],
  "spec": "specs/active/PM-0042-bulk-discounts.md",
  "impl_repo": "my-org/api",
  "labels": ["pricing", "backend"],
  "assignees": ["alice", "bob"],
  "board": { "engine": "github", "ref": 123, "url": "https://.../issues/123" },

  "body": "issue body composed by route-task (optional)",
  "parent_ref": 117,
  "blocked_by_refs": [98]
}
```

- `board` is absent/empty until the first `upsert`; its result is written back into
  the artifact (`board.ref`, `board.url`) by route-task via `pm.py set`.
- `parent_ref` / `blocked_by_refs` are the **external** refs the parent / dependency
  items already carry (route-task resolves them from the referenced artifacts'
  `board.ref`). An engine without dependency support degrades gracefully.

## Adding an engine

1. `mkdir engines/<name>` and add an executable `engine` implementing the verbs above.
2. Add `capabilities.json`.
3. Set `"engine": "<name>"` (and any engine-specific config block) in `.pm-ops/config.json`.

Engines should **degrade, not fail**: if the board can't express a capability
(types, sub-issues, dependencies, custom fields), record a `warning` and continue.
This extends to a missing CLI/tool — prefer emitting a paste-ready/manual result
over hard-failing (the github engine's `upsert` returns `{"mode":"paste-ready",
"card": "..."}` when `gh` is absent, since the markdown artifact is still canonical).
