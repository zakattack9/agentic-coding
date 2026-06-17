---
name: draft-spec
description: Scope a single backlog candidate into a proper spec at the right rigor. Use after consolidate-backlog when the user wants to flesh out one item into something a developer can pick up. Everything is a spec (one format); spec-ops owns 100% of the spec body — draft-spec is a thin wrapper that sets the pm-ops front-matter, hands the body to spec-ops:write-spec for every item, and additionally runs spec-ops:refine-spec only when rigor is full. Moves the item from backlog/ to specs/draft/, keeping its stable PM-#### id.
model: opus
effort: high
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(python3 *), Bash(git *), Bash(mv *), AskUserQuestion
argument-hint: "[PM-#### id or path of the backlog candidate to scope]"
---

# draft-spec

Turn one **candidate** into a **spec**. pm-ops uses a single format for every item
and **spec-ops owns 100% of the spec body**. draft-spec is the thin wrapper: it
sets the pm-ops front-matter, hands the body to **`spec-ops:write-spec`** for
*every* item, and runs **`spec-ops:refine-spec`** *only* when rigor is `full`.
Rigor never changes the format the developer sees — it only decides whether the
heavy grounding loop runs. The item keeps its id and moves `backlog/ → specs/draft/`.

Let `PM=${CLAUDE_PLUGIN_ROOT}/lib/pm.py`.

## 1. Select the candidate

Resolve the target from the argument (a `PM-####` id or a path). If none given,
list `backlog/*.md` and ask with `AskUserQuestion` which to scope (prefer highest
priority / unscoped). Read it:

```bash
python3 "$PM" read "<repo>/backlog/<id>-<slug>.md"
```

If the file isn't in `backlog/` (already a spec), say so and stop — re-drafting an
existing spec is `refine-spec`'s job, not this skill's.

## 2. Decide rigor

Read `${CLAUDE_PLUGIN_ROOT}/rules/rigor-rubric.md` and form a recommendation from
the candidate's content. Confirm with `AskUserQuestion` (`light` vs `full`),
showing the trigger behind your pick. **Default to `full` on a close call** —
under-specifying costs an implementation, over-specifying costs minutes.

Both levels get their body from `spec-ops:write-spec` (which already emits a short
spec for trivial items via its conditional sections). Rigor decides only whether
`refine-spec` runs afterward:
- **light** — one repo/surface, obvious approach, S–M, no schema/API/migration,
  low blast radius. `write-spec` only.
- **full** — schema/migration/API/auth change, a real design choice, multi-repo/
  team, L–XL or unknown size, high blast radius. `write-spec` + `refine-spec`.

## 3. Move the file into specs/draft/

Keep the same id and slug; only the folder changes (the id is immutable across
folders — see `rules/repo-conventions.md`). Prefer `git mv` so history follows:

```bash
git -C "<repo>" mv "backlog/<id>-<slug>.md" "specs/draft/<id>-<slug>.md" \
  || mv "<repo>/backlog/<id>-<slug>.md" "<repo>/specs/draft/<id>-<slug>.md"
```

Set the wrapper fields:

```bash
python3 "$PM" set "<repo>/specs/draft/<id>-<slug>.md" \
  status=draft rigor=<light|full> spec="specs/draft/<id>-<slug>.md"
```

## 4. Hand the body to spec-ops (always)

Keep the pm-ops front-matter block intact; **spec-ops owns 100% of the body below
it** — never author spec content yourself, at either rigor. Seed the body with the
skeleton from `${CLAUDE_PLUGIN_ROOT}/templates/spec.md` (everything under the
front-matter) so write-spec has the pm-ops shape to fill, then delegate:

> Run **`/spec-ops:write-spec`** pointed at `specs/draft/<id>-<slug>.md` to author
> the body. **If `rigor: full`**, then also run **`/spec-ops:refine-spec`** on the
> same file to ground and harden it. Preserve the pm-ops front-matter wrapper at the
> top of the file untouched.

`write-spec`'s conditional sections already yield a short spec for a light item and
a full one for a heavy item — so the *format* is identical; only whether
`refine-spec` runs differs. If you are continuing autonomously, invoke
`spec-ops:write-spec` now (and `spec-ops:refine-spec` after it when rigor is full).
Either way the front-matter `id`, `rigor`, and `spec` stay as set in step 3.

## 5. Normalize-check, reindex, report

```bash
python3 "$PM" normalize "<repo>/specs/draft/<id>-<slug>.md" >/dev/null
python3 "$PM" reindex --repo "<repo>"
```

Report: the id + title, the chosen rigor (and why), the new path, and the next
step — **`/pm-ops:route-task`** to push it to the board once the spec body is ready
(after `write-spec`, and `refine-spec` too when rigor is full).

## Guardrails
- One format only. Never create a separate "story" artifact or folder.
- Never change an item's `id`; only its folder/status change here.
- **Never write the spec body yourself, at any rigor** — spec-ops owns 100% of it.
  Your job is the front-matter wrapper + the hand-off (and gating `refine-spec`).
- Always `reindex` after the move so `index.md` reflects the new stage.
