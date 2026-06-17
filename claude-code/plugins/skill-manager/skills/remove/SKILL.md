---
name: remove
description: Remove a skill from a central plugin, or delete an entire plugin from the marketplace, then push the removal. Use when the user says "remove this skill", "delete this skill from the marketplace", "deprecate this skill", "delete this plugin", or "unregister a plugin". Destructive and pushes to git; user-invoked only.
# model: claude-sonnet-4-6
# effort: medium
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *) AskUserQuestion
argument-hint: "[skill or plugin]"
---

# Remove a skill or plugin from the marketplace

Delete a central skill (or a whole plugin), clean up the catalog and bump the version, commit, and push. The engine renders a numbered menu and resolves the pick itself — you never enumerate or map names, and because a skill index encodes its plugin there's no ambiguity to resolve.

## Steps

1. **Show the numbered menu:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" remove
   ```
   **Reproduce the menu in your reply inside a fenced ``` block** — copy it verbatim so the user can read it without expanding the raw tool output. Plugins get a bare number (`2`), each skill a compound index (`2.3`). Those numbers are ground truth; don't renumber or invent entries.

2. **Get the pick.** If the user already named a target (as args or in chat), use it. Otherwise ask in plain text to reply with a number — a skill index like `1.2`, or a plugin number like `2` to delete the whole plugin (this open-ended reply doesn't fit `AskUserQuestion`'s fixed options). Pass their reply through unchanged.

3. **Preview the deletion** (writes nothing):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" remove --select "<their reply>"
   ```
   The engine prints exactly what it would delete (the skill, or the plugin and all its skills). Relay that verbatim. If it errors on a bad index/name, show the message and re-ask (back to step 2).

4. **Confirm before deleting** with `AskUserQuestion` — this is destructive and pushes to git:
   - **Delete** — proceed with what the preview showed.
   - **Cancel** — make no changes.

5. **Apply** the confirmed deletion, reusing the same `--select` value the preview echoed:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" remove --select "<ref>" --force
   ```

6. Report using the **Output** skeleton, including the two-command marketplace-update + reload steps the engine prints (`/plugin marketplace update <marketplace>` then `/reload-plugins`; custom marketplaces don't auto-refresh, so `/reload-plugins` alone won't pick up the change). **Surface any push-failure WARNING.** Removing a plugin can't clean up its enablement in *other* projects — mention that if relevant.

For direct, name-based removal (e.g. scripting), `skillctl remove-skill <skill> [--plugin P] --force` and `skillctl remove-plugin <plugin> --force` still work and resolve the same way.

## Stay grounded — this is destructive and writes to git

- **The menu and `--select` are the source of truth.** The engine resolves the index to a real skill/plugin and prints what it will delete; never delete by a name you inferred yourself. Always run the preview (step 3) and get the user's explicit OK (step 4) before `--force`.
- **Relay the tool's actual output.** Only report success if it confirmed the removal, and surface any push-failure `WARNING` — until the push lands, the removal is local-only.

## Output

Fill this skeleton from the engine's output, copying values verbatim. Drop a line if it doesn't apply:

**Removed:** {skill `{name}` from `{plugin}` (now v`{version}`) / plugin `{name}` and all its skills}
**⚠️ Push failed:** {verbatim WARNING} — committed locally, not on the remote yet.
**Cleanup:** {only if the engine noted `{plugin}` has no skills left} → run the menu again and pick its plugin number to remove it too.
**Apply it (required after every removal):** custom marketplaces don't reliably auto-update — not even new sessions — so run these two commands each time (substitute the real marketplace name for `{marketplace}`): `/plugin marketplace update {marketplace}` then `/reload-plugins`.
**Heads up:** {plugin removal only} enablement of `{plugin}` in other projects must be cleaned up manually.

If the user cancelled, say so and confirm nothing was deleted.
