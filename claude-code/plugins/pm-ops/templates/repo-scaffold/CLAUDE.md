# Central PM / spec repo

Managed by the **pm-ops** plugin. Markdown-in-git is the source of truth; the
board (GitHub Issues + Projects by default) is a projection.

## Structure
- `inbox/` — raw, unstructured dumps of features/fixes, verbatim.
- `backlog/` — consolidated candidate items (one file each), produced by `consolidate-backlog`.
- `stories/` is intentionally absent — **everything is a spec** (one format, scaled rigor).
- `specs/draft/` — specs being authored / refined.
- `specs/active/` — refined, ready, or in-flight specs.
- `specs/promoted/` — forwarding stubs left behind after a spec moves into its impl repo.
- `index.md` — generated cross-link of every item. Do not hand-edit (`pm.py reindex`).
- `.pm-ops/` — `config.json` (board engine + field mappings) and `registry.json` (id counter).

## Item contract
Every artifact carries YAML front-matter with a stable `id` (e.g. `PM-0042`) that
never changes as the file moves between folders. See pm-ops `rules/repo-conventions.md`.

## Workflow
1. Drop a brain-dump into `inbox/`, run **`/pm-ops:consolidate-backlog`**.
2. **`/pm-ops:draft-spec`** scopes a candidate into a spec at the right rigor; the
   body always comes from `/spec-ops:write-spec` (full rigor also runs `/spec-ops:refine-spec`).
3. **`/pm-ops:route-task`** pushes it to the board.
4. **`/pm-ops:promote-spec`** moves a verified spec into its implementation repo;
   then `/spec-ops:launch-spec` implements it.
