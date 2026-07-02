# Output styles

Standalone, opt-in Claude Code output styles kept in this repo. They are **not** part of any plugin — nothing here is bundled into a plugin or auto-applied. You choose to install and activate a style yourself.

An output style changes only how Claude *talks to you*, never how it *works* — it keeps full engineering rigor and changes no persisted artifact unless the style says otherwise.

## Available styles

| Style | File | What it does |
| --- | --- | --- |
| **Caveman** | `caveman.md` | Replies in **ultra-compressed "caveman" prose** — drops articles, filler, and pleasantries to cut roughly **65–75% of output tokens** while keeping every technical fact intact. |
| **Vietnamese** | `vietnamese.md` | **Converses in Vietnamese** (Northern / Hà Nội register) while keeping every artifact in English. |

### Caveman (`caveman.md`)

Code, function/API names, CLI commands, file paths, and error strings stay **exact and verbatim**; only fluff dies. It **matches your language** (Portuguese in → Portuguese caveman out) and automatically **drops back to normal prose** where clarity matters: security warnings, confirming destructive actions, order-sensitive multi-step sequences, or when you're confused. Code, commit messages, and PR descriptions are always written in standard form.

### Vietnamese (`vietnamese.md`)

Keeps **every artifact in English** — code, comments, identifiers, file and branch names, commit messages, documentation, config, and all spec content (including `## Summary` and `## Checklist`). When it walks you through an English spec or file, it **translates the content into Vietnamese** rather than quoting the English verbatim — no English survives to the conversation, only to the files on disk.

## Install & activate

The steps are the same for every style — just swap in the file name (e.g. `caveman.md`) and the style's display name (e.g. `Caveman`).

1. Copy the style file into your user-level output-styles directory:

   ```bash
   mkdir -p ~/.claude/output-styles
   cp claude-code/output-styles/<style>.md ~/.claude/output-styles/
   ```

   There is no project-level copy in this repo (styles live under `claude-code/`, not `.claude/`, per this repo's convention of keeping Claude-Code-specific content out of the root), so copy them to `~/.claude/output-styles/` to use them in any project, including this one.

2. Activate it via **`/config`** → select **"Output style"** → choose the style by name. You can also set it directly in your settings file:

   ```json
   { "outputStyle": "<StyleName>" }
   ```

   (`/config` is the documented path — there is no standalone `/output-style` command.)

## Notes

- **Optional and reversible.** Switch back the same way (`/config` → "Output style" → Default). See each style's entry above for exactly what it does and does not change.
- **Loads at session start.** An output style is read once, at the start of a session, as part of the system prompt. Selecting or switching a style **mid-session does not take effect until you `/clear` or restart** the session.
