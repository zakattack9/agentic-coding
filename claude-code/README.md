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
