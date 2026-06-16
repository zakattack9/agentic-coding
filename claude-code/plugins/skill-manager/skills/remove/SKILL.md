---
name: remove
description: Remove a skill from a central plugin, or delete an entire plugin from the marketplace, then push the removal. Use when the user says "remove this skill", "delete this skill from the marketplace", "deprecate this skill", "delete this plugin", or "unregister a plugin". Destructive and pushes to git; user-invoked only.
model: claude-sonnet-4-6
effort: medium
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *) AskUserQuestion
argument-hint: "<skill-name> | --plugin <plugin>"
---

# Remove a skill or plugin from the marketplace

Delete a central skill (or a whole plugin), clean up the catalog and bump the version, commit, and push.

## Steps

1. Confirm exactly what to remove — a single skill, or an entire plugin (which deletes all its skills). List the candidates from `/skill-manager:status` and confirm with the user via `AskUserQuestion` first; this is destructive and pushes to git. **Respect the 4-option cap:** `AskUserQuestion` shows at most 4 options, so when there are more than 4 skills/plugins, **page through them** rather than dropping any — offer 3 plus a `Show more (N left)…` option and re-ask with the next batch (the auto-added "Other" lets them type the exact name to skip paging).
2. Remove a skill (owning plugin auto-detected):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" remove-skill <skill> --force
   ```
   Remove a whole plugin (also unregisters it and clears user-scope enablement):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" remove-plugin <plugin> --force
   ```
   `--force` is the confirmation. Run the command without it first if you want the tool to print exactly what it will delete before doing it.
3. Report using the **Output** skeleton, including the two-command marketplace-update + reload steps the engine prints (`/plugin marketplace update <marketplace>` then `/reload-plugins`; custom marketplaces don't auto-refresh, so `/reload-plugins` alone won't pick up the change). **Surface any push-failure WARNING.** Removing a plugin can't clean up its enablement in *other* projects — mention that if relevant.

## Stay grounded — this is destructive and writes to git

- **Confirm the exact name against `/skill-manager:status` before removing**, and get the
  user's explicit OK. Never guess a skill or plugin name — a wrong name could delete the
  wrong thing or fail confusingly.
- **Relay the tool's actual output.** Only report success if it confirmed the removal, and
  surface any push-failure `WARNING` — until the push lands, the removal is local-only.

## Output

Fill this skeleton from the engine's output, copying values verbatim. Drop a line if it doesn't apply:

**Removed:** {skill `{name}` from `{plugin}` (now v`{version}`) / plugin `{name}` and all its skills}
**⚠️ Push failed:** {verbatim WARNING} — committed locally, not on the remote yet.
**Cleanup:** {only if the engine noted `{plugin}` has no skills left} → remove the empty plugin too with `/skill-manager:remove`.
**Apply it (required after every removal):** custom marketplaces don't reliably auto-update — not even new sessions — so run these two commands each time (substitute the real marketplace name for `{marketplace}`): `/plugin marketplace update {marketplace}` then `/reload-plugins`.
**Heads up:** {plugin removal only} enablement of `{plugin}` in other projects must be cleaned up manually.
