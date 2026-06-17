---
name: promote-spec
description: Move a verified, ready spec out of the central PM repo and into the repo where it will actually be implemented, leaving a forwarding stub behind. Use when a spec is done being authored/refined and implementation is about to start, so the spec lives next to the code. Copies the spec into the impl repo's docs/specs/, replaces the central copy with a stub that points to it, updates status to promoted, and reindexes. The hand-off from planning to building.
disable-model-invocation: true
model: sonnet
effort: medium
allowed-tools: Bash(git *), Bash(bash *), Bash(python3 *), Read, Write, Edit, AskUserQuestion
argument-hint: "[PM-#### id or spec path] [local path to the implementation repo]"
---

# promote-spec

Relocate a finished spec from the central PM repo into its implementation repo so
it sits next to the code, and leave a **forwarding stub** in the PM repo so the id
still resolves and the index stays complete. This solves the central-vs-in-repo
tension: specs are born central, then move to the code at implementation time.

Let `PM=${CLAUDE_PLUGIN_ROOT}/lib/pm.py`.

## 1. Resolve the spec & target repo

Resolve the spec from the argument (a `PM-####` id or path); it should be in
`specs/active/` and have a finished body (light: filled inline; full: spec-ops
done). Confirm readiness with `AskUserQuestion` if there's any doubt — promotion
is a hand-off, not a checkpoint to revisit.

```bash
SPEC="<repo>/specs/active/<id>-<slug>.md"
python3 "$PM" read "$SPEC"          # shows impl_repo, status, board, etc.
```

Determine the **local working-copy path** of the implementation repo:
- Use the second argument if given.
- Else derive a candidate from `impl_repo` (`owner/name`) and check sibling dirs.
- Else ask with `AskUserQuestion`. Confirm the path is a git repo before writing.

If `impl_repo` is empty, ask for it and set it on the spec:
`python3 "$PM" set "$SPEC" impl_repo="owner/name"`.

## 2. Copy the spec into the impl repo

Default destination is `docs/specs/` (confirm/override via `AskUserQuestion` if the
repo clearly uses another convention):

```bash
DEST="<impl-repo>/docs/specs/<id>-<slug>.md"
mkdir -p "$(dirname "$DEST")"
cp "$SPEC" "$DEST"
```

The full file — pm-ops front-matter **and** body — travels, so the in-repo spec is
self-contained and the id/board link remain traceable from the code side. Stage it
in the impl repo's git (`git -C "<impl-repo>" add "docs/specs/<id>-<slug>.md"`) but
**do not commit** unless the user asks.

## 3. Leave a forwarding stub (deterministic move)

Move the central file to `specs/promoted/` and replace its body with a pointer:

```bash
git -C "<repo>" mv "specs/active/<id>-<slug>.md" "specs/promoted/<id>-<slug>.md" \
  || mv "<repo>/specs/active/<id>-<slug>.md" "<repo>/specs/promoted/<id>-<slug>.md"

python3 "$PM" set "<repo>/specs/promoted/<id>-<slug>.md" \
  status=promoted \
  spec="docs/specs/<id>-<slug>.md" \
  impl_repo="owner/name"
```

Then with `Edit`, replace the stub's body (below front-matter) with a short
forwarding note: where the live spec now lives (`<impl_repo> → docs/specs/...`),
the board URL if present, and the promotion date. Keep the front-matter intact so
the id, board ref, and links still resolve from the central index.

## 4. Reindex & update the board

```bash
python3 "$PM" reindex --repo "<repo>"
```

The spec now lives in the impl repo, so the board's **Spec field must point at the
new in-repo location** and the item should usually read In Progress. The stub's
`spec=` (set in step 3) is already the in-repo path, so re-running `upsert` repushes
that field to the existing issue and `status=promoted` maps to In Progress — one
dry-run-then-apply pass does both (dry first, as route-task does):

```bash
DISPATCH="${CLAUDE_PLUGIN_ROOT}/lib/engine-dispatch.sh"
python3 "$PM" normalize "<repo>/specs/promoted/<id>-<slug>.md" | bash "$DISPATCH" upsert
# review the plan, then on confirm:
python3 "$PM" normalize "<repo>/specs/promoted/<id>-<slug>.md" | bash "$DISPATCH" upsert --apply
```

(`upsert` edits the existing issue because the stub still carries `board.ref`; it
won't create a duplicate. If `gh` is absent the engine returns a paste-ready card —
present it instead.)

## 5. Report

State: the spec's id + title, where it now lives in the impl repo, that a stub
remains in `specs/promoted/`, the board status + that its Spec field now points
in-repo, and that nothing was committed. Point the user at the next step —
**`/spec-ops:launch-spec`** inside the impl repo to implement it.

## Guardrails
- Copy, then stub — never leave the central repo without a forwarding record.
- Preserve the `id` and front-matter on both copies; the id is the through-line.
- Do not commit or push in either repo unless the user explicitly asks.
- Confirm the impl-repo path is correct before writing into it; ask if unsure.
- Always `reindex` so `index.md` shows the promoted stage.
