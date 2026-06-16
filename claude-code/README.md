# Claude Code

Plugins, skills, hooks, commands, and agents for Claude Code live under `plugins/`. See `CLAUDE.md` for repo structure and `rules/writing-skills.md` for authoring patterns.

## Known issues

### Skill `model:` frontmatter triggers "Usage credits required for 1M context" on Max

**Symptom.** A skill that pins `model: claude-sonnet-4-6` (or `sonnet`) in its `SKILL.md` frontmatter fails at invocation with:

```
API Error: Usage credits required for 1M context · run /usage-credits to turn them on, or /model to switch to standard context
```

This happens even though the skill explicitly names Sonnet 4.6 (the 200k model included in the Max plan), and even with the full model ID rather than the `sonnet` alias.

**Root cause.** The 1M extended-context window is a **session-level tier**, not something encoded in a skill's `model:` string. When a skill overrides `model:`, it switches the model *family* but **inherits the session's 1M tier**. On the Max plan, Opus 1M is free (sessions auto-upgrade to it), but **Sonnet 1M is billed even on Max**. So a 1M Opus session that invokes a Sonnet skill produces Sonnet + 1M → the paid gate fires → the error above. Neither the full model ID nor `context: fork` strips the inherited tier.

This is a known Claude Code bug:

- [#45847 — API Error: Extra usage is required for 1M context when invoking skill with `model:` frontmatter from Opus [1m] session on Max](https://github.com/anthropics/claude-code/issues/45847)
- [#57249 — Skill subagent inherits parent's 1M-context tier but not extra-usage entitlement](https://github.com/anthropics/claude-code/issues/57249)
- [#34296 — Skill `model:` frontmatter triggers 429 "Extra usage required" when session uses opus[1m]](https://github.com/anthropics/claude-code/issues/34296)

**Fix.** Disable the 1M tier for all sessions so no skill can inherit it. Add to the `env` block of `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"
  }
}
```

Then **restart Claude Code** — `env` settings apply at startup. This removes the 1M variants from the model picker; Sonnet skills then run at 200k for free.

**Notes.**

- Editing or removing the skill's `model:` line does **not** fix this — the frontmatter is already correct; the inherited session tier is the problem. Don't chase it by changing `model:`.
- Trade-off: this disables 1M for *every* session, including the free Opus 1M. To use 1M for a one-off large task, temporarily remove the env var and restart.
- If the error returns, confirm the env var is still set and that Claude Code was restarted.

### Third-party marketplaces serve a stale cache — pushed updates don't appear

**Symptom.** After publishing new or updated skills to a third-party marketplace repo (e.g. via `/skill-manager:push`, which commits and pushes to the marketplace's GitHub repo), the changes **don't show up in Claude Code**. New sessions still load the old skills, `/plugin` shows the previous version, and `claude plugin update` insists nothing changed:

```
✔ <plugin> is already at the latest version (ab7b40fdd4f2)
```

This is exactly why **skill-manager requires you to manually refresh the marketplace after pushing** — a push updates the *remote* repo, but Claude Code keeps reading its local copy.

**Root cause.** Three overlapping bugs in Claude Code's plugin manager, all rooted in cache staleness:

1. **Third-party marketplaces aren't auto-pulled.** `claude-plugins-official` is `git pull`ed on every session start, but marketplaces added via `/plugin marketplace add <owner>/<repo>` stop being auto-pulled after install day — new commits are never discovered without manual intervention. ([#26744](https://github.com/anthropics/claude-code/issues/26744))
2. **`update`/`install` compare against the stale clone without fetching.** `claude plugin update`/`install` check the installed commit SHA against the local marketplace clone at `~/.claude/plugins/marketplaces/<name>/` **without running `git fetch`/`git pull` first**, so they report "already at latest version" even when the remote HEAD has advanced. ([#46081](https://github.com/anthropics/claude-code/issues/46081), [#36938](https://github.com/anthropics/claude-code/issues/36938), [#16866](https://github.com/anthropics/claude-code/issues/16866))
3. **The executed-from cache isn't invalidated.** Even once the marketplace clone updates, the running copy under `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` is not cleared, so Claude keeps executing the old code (and can show stale errors referencing the old version). ([#14061](https://github.com/anthropics/claude-code/issues/14061), [#17361](https://github.com/anthropics/claude-code/issues/17361), [#59206](https://github.com/anthropics/claude-code/issues/59206))

**Fix / workaround.** In-session, after a push, refresh the marketplace and reload:

```
/plugin marketplace update <marketplace>
/reload-plugins
```

If that still serves stale content (bugs 2–3 above), force a fresh pull and drop the cached copy, then reinstall:

```bash
cd ~/.claude/plugins/marketplaces/<marketplace>
git pull origin main
rm -rf ~/.claude/plugins/cache/<marketplace>/<plugin>/*
claude plugin install <plugin>@<marketplace>
```

Turning **auto-update ON** for the marketplace (`/plugin` → Marketplaces) makes new sessions refresh on their own — though per #26744 this is unreliable for third-party marketplaces, so keep the manual refresh handy. For automation, the community [`plugin-updater`](https://github.com/diegomarino/claude-toolshed/tree/main/plugins/plugin-updater) plugin runs `claude plugin marketplace update` + `claude plugin update` for every third-party marketplace on a `SessionStart` hook (with a 1-hour cooldown).

**Notes.**

- This is a *publishing* limitation, not a repo bug: editing the source in this repo never takes effect until the marketplace clone **and** the plugin cache are both refreshed. When testing local skill changes, expect to refresh between edits.
- Always bump the plugin version in `.claude-plugin/marketplace.json` on every change (see root `CLAUDE.md`) — a version bump is what `update`/`install` keys off once the clone is actually fresh.
