# Output styles

Standalone, opt-in Claude Code output styles kept in this repo. They are **not** part of any plugin — nothing here is bundled into a plugin or auto-applied. You choose to install and activate a style yourself.

## Vietnamese (`vietnamese.md`)

Makes Claude **converse in Vietnamese** (Northern / Hà Nội register) while it keeps **every artifact in English** — code, comments, identifiers, file and branch names, commit messages, documentation, config, and all spec content (including `## Summary` and `## Checklist`). When it walks you through an English spec or file, it **translates the content into Vietnamese** rather than quoting the English verbatim — no English survives to the conversation, only to the files on disk.

### Install

1. Copy the style file into your user-level output-styles directory:

   ```bash
   cp claude-code/output-styles/vietnamese.md ~/.claude/output-styles/
   ```

   There is no project-level copy in this repo (it lives under `claude-code/`, not `.claude/`, per this repo's convention of keeping Claude-Code-specific content out of the root), so copy it to `~/.claude/output-styles/` to use it in any project, including this one.

2. Activate it via **`/config`** → select **"Output style"** → choose **Vietnamese**. You can also set it directly in your settings file:

   ```json
   { "outputStyle": "Vietnamese" }
   ```

   (`/config` is the documented path — there is no standalone `/output-style` command.)

### Notes

- **Optional and reversible.** Selecting the style changes only how Claude *talks to you*. It changes **no persisted artifact's language** — every file, commit, and spec stays English. Switch back the same way (`/config` → "Output style" → Default).
- **Loads at session start.** An output style is read once, at the start of a session, as part of the system prompt. Selecting or switching a style **mid-session does not take effect until you `/clear` or restart** the session.
