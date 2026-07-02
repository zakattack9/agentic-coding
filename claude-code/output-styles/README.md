# Output styles

Standalone, opt-in Claude Code output styles kept in this repo. They are **not** part of any plugin — nothing here is bundled into a plugin or auto-applied. You choose to install and activate a style yourself.

An output style changes only how Claude *talks to you*, never how it *works* — it keeps full engineering rigor and changes no persisted artifact unless the style says otherwise.

## Available styles

| Style | File | What it does |
| --- | --- | --- |
| **Caveman** | `caveman.md` | Replies in **ultra-compressed "caveman" prose** — drops articles, filler, and pleasantries to cut roughly **65–75% of output tokens** while keeping every technical fact intact. The default, balanced level. |
| **Caveman Lite** | `caveman-lite.md` | The **gentlest** level — drops filler, pleasantries, and hedging but **keeps full sentences and articles**. Tighter than normal, still fully readable. |
| **Caveman Ultra** | `caveman-ultra.md` | The **densest** level — everything full does, **plus** abbreviated prose words (DB/auth/fn), stripped conjunctions, and causal arrows (`X → Y`). Maximum squeeze. |
| **Vietnamese** | `vietnamese.md` | **Converses in Vietnamese** (Northern / Hà Nội register) while keeping every artifact in English. |

### Caveman family — three intensity levels (`caveman.md`, `caveman-lite.md`, `caveman-ultra.md`)

All three share the same guardrails: code, function/API names, CLI commands, file paths, and error strings stay **exact and verbatim**; they **match your language** (Portuguese in → Portuguese out) and automatically **drop back to normal prose** where clarity matters — security warnings, confirming destructive actions, order-sensitive multi-step sequences, or when you're confused. Code, commit messages, and PR descriptions are always written in standard form. They differ only in how hard they compress your prose:

| Level | Keeps | Drops / adds |
| --- | --- | --- |
| **Lite** (`caveman-lite.md`) | Articles + full sentences | Drops filler, pleasantries, hedging |
| **Caveman** (`caveman.md`) | Meaning; code exact | Drops articles; fragments OK; short synonyms |
| **Ultra** (`caveman-ultra.md`) | Code / API / errors exact | Full **plus** abbreviated prose words, stripped conjunctions, causal arrows `X → Y` |

Same question — *"Why does my React component re-render?"* — at each level:

- **Lite:** Your component re-renders because you create a new object reference each render. Wrap it in `useMemo`.
- **Caveman:** New object ref each render. Inline object prop = new ref = re-render. Wrap in `useMemo`.
- **Ultra:** Inline obj prop → new ref → re-render. `useMemo`.

These examples are the canonical ones from the upstream caveman skill, so the three styles stay faithful to the original level definitions. Install whichever single level you want, or install all three and switch between them via `/config`.

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
