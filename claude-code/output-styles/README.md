# Output styles

Standalone, opt-in Claude Code output styles kept in this repo. They are **not** part of any plugin — nothing here is bundled into a plugin or auto-applied. You choose to install and activate a style yourself.

## Vietnamese (`vietnamese.md`)

Makes Claude **converse in Vietnamese** (Northern / Hà Nội register) while it keeps **every artifact in English** — code, comments, identifiers, file and branch names, commit messages, documentation, config, and all spec content (including `## Summary` and `## Checklist`). When it walks you through an English spec or file, it explains in Vietnamese but quotes the English text verbatim rather than translating it.

### Install

1. Copy the style file into your user-level output-styles directory:

   ```bash
   cp .claude/output-styles/vietnamese.md ~/.claude/output-styles/
   ```

   (A project-level `.claude/output-styles/` is also discovered when you run Claude Code from this repo, so inside this repo you may not need to copy it. Copy it to `~/.claude/output-styles/` to use it in any project.)

2. Activate it via **`/config`** → select **"Output style"** → choose **Vietnamese**. You can also set it directly in your settings file:

   ```json
   { "outputStyle": "Vietnamese" }
   ```

   (`/config` is the documented path — there is no standalone `/output-style` command.)

### Notes

- **Optional and reversible.** Selecting the style changes only how Claude *talks to you*. It changes **no persisted artifact's language** — every file, commit, and spec stays English. Switch back the same way (`/config` → "Output style" → Default).
- **Loads at session start.** An output style is read once, at the start of a session, as part of the system prompt. Selecting or switching a style **mid-session does not take effect until you `/clear` or restart** the session.
