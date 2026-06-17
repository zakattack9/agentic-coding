---
name: route-task
description: Project a pm-ops spec onto the board (create/update its tracker item, place it, set fields, link parent/dependencies) via the configured, board-agnostic engine. GitHub Issues + Projects ships as the default engine. Dry-by-default — previews the exact plan, applies only on explicit confirmation, then writes the board ref back into the spec's front-matter. Run after a spec is drafted/refined.
disable-model-invocation: true
model: claude-sonnet-4-6
effort: medium
allowed-tools: Bash(bash *), Bash(python3 *), Bash(gh *), Read, Edit, AskUserQuestion
argument-hint: "[PM-#### id or spec path] (add --apply only after reviewing the dry run)"
---

# route-task

Push one spec to the board through the pluggable engine. The core stays
board-agnostic: this skill only ever produces a **normalized task** and calls
`lib/engine-dispatch.sh`, which execs the engine named in `.pm-ops/config.json`
(see `${CLAUDE_PLUGIN_ROOT}/engines/INTERFACE.md`). **Never** call `gh` to mutate
the board directly — go through the engine so swapping boards stays a one-line
config change.

Let `PM=${CLAUDE_PLUGIN_ROOT}/lib/pm.py` and
`DISPATCH=${CLAUDE_PLUGIN_ROOT}/lib/engine-dispatch.sh`. Run from inside the PM
repo (or set `PM_OPS_REPO`) so the dispatcher finds `.pm-ops/`.

## 1. Resolve the spec & preflight

Resolve the target file from the argument (a `PM-####` id or a path); it should
live in `specs/draft/` or `specs/active/`. Then sanity-check config and engine:

```bash
SPEC="<repo>/specs/<stage>/<id>-<slug>.md"
python3 "$PM" normalize "$SPEC" >/dev/null         # confirms it's a valid artifact
bash "$DISPATCH" capabilities                       # confirms engine + config resolve
```

For the github engine, `.pm-ops/config.json` needs `github.owner`, `project`, and
a target repo (`impl_repo` on the spec, or `github.default_repo`/`repo_map`). If
any are missing, fix config (or set `impl_repo` on the spec) before continuing.

## 2. Dry run (always first)

```bash
python3 "$PM" normalize "$SPEC" | bash "$DISPATCH" upsert
```

The engine prints the full plan to stderr and a result JSON (`applied:false`) to
stdout. Show the user exactly what it would do — issue create/edit, board
placement, each field set — plus any `warnings` (e.g. an unmapped field, or
`gh < 2.94` degrading native types/links to labels/body notes).

**If the result has `"mode": "paste-ready"`** (the github engine emits this when
`gh` isn't installed), there's nothing to apply — present the `card` field to the
user as a copy-paste issue for the GitHub UI, then skip to step 4 only if/when they
report back the created issue number (to record `board.ref`). Don't attempt
`--apply`; install `gh` to push automatically instead.

## 3. Confirm, then apply

Use `AskUserQuestion` to confirm applying (this mutates the external tracker).
On confirmation, re-run with `--apply`:

```bash
python3 "$PM" normalize "$SPEC" | bash "$DISPATCH" upsert --apply
```

Capture `ref` and `url` from the result JSON.

## 4. Write the board ref back (deterministic)

The markdown is the source of truth; record the projection in it:

```bash
python3 "$PM" set "$SPEC" \
  board='{"engine": "github", "ref": <ref>, "url": "<url>"}' \
  status=active
```

(Move the file to `specs/active/` if it's still in `draft/` and now in flight —
`git mv` then re-`set` `spec=` to the new path.)

## 5. Link parent & dependencies (optional second pass)

If the spec has `parent` or `depends_on`, resolve their **external** refs from the
referenced artifacts' front-matter and pass them to the engine's `link` verb.
Build the augmented task with an inline transform (those items must already be
routed, i.e. carry a `board.ref`):

```bash
python3 "$PM" normalize "$SPEC" \
  | python3 -c 'import json,sys; t=json.load(sys.stdin); t["parent_ref"]=<parent_ref or "null">; t["blocked_by_refs"]=[<dep_refs>]; print(json.dumps(t))' \
  | bash "$DISPATCH" link            # add --apply after reviewing
```

Skip any ref that can't be resolved and tell the user which dependency to route
first. Engines without dependency support degrade with a warning — that's expected.

## 6. Status & reindex

If you only need to move the column later, use `set-status` (reads `board.ref`):

```bash
python3 "$PM" normalize "$SPEC" | bash "$DISPATCH" set-status --apply
```

Always finish by regenerating the index:

```bash
python3 "$PM" reindex --repo "<repo>"
```

## 7. Report

State the issue number + URL, what was set on the board, any links created, any
warnings, and the updated stage. If anything degraded (old `gh`, unmapped field,
unrouted dependency), say so plainly with the remedy.

## Guardrails
- Dry run first, every time. Only `--apply` after the user confirms.
- All board mutations go through `engine-dispatch.sh`, never raw `gh`.
- Markdown front-matter wins over the board; re-route to reconcile drift.
- Never hand-edit `index.md`; regenerate with `reindex`.
