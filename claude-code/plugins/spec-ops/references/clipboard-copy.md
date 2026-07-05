# Portable clipboard copy — for emit-only skills

How an **emit-only** skill (`launch-spec`, `loop-spec`) copies the prompt it just showed in
chat to the system clipboard so the handoff is a single ⌘V. Single-sourced here because both
skills need the exact same mechanism and any drift between two copies is a silent bug.

**Copying is not running — it stays emit-only.** Piping the shown text to the clipboard changes
nothing and runs nothing; it is the last step before the skill stops.

## The rule

Pipe the **exact same text you showed in chat** (its leading command prefix, if any, included —
the clipboard bytes must be **byte-identical** to the chat bytes) to the clipboard via a
**single quoted heredoc**, so the driver is never written to disk and no escaping is needed
(`$`, backticks, and quotes pass through literally).

Pick the **session-appropriate** tool present — **gate the Wayland/X11 branches on the session's
display env** (`$WAYLAND_DISPLAY` / `$DISPLAY`) so a tool that is installed but wrong for the
session can't win and swallow the copy — and fall back to chat-only if none land:

```bash
{ if   command -v pbcopy   >/dev/null 2>&1; then pbcopy                                                   # macOS
  elif [ -n "$WAYLAND_DISPLAY" ] && command -v wl-copy >/dev/null 2>&1; then wl-copy                       # Wayland
  elif [ -n "$DISPLAY" ]        && command -v xclip   >/dev/null 2>&1; then xclip -selection clipboard     # X11
  elif [ -n "$DISPLAY" ]        && command -v xsel    >/dev/null 2>&1; then xsel --clipboard --input       # X11 (Mint/XFCE)
  elif command -v clip.exe >/dev/null 2>&1; then clip.exe                                                  # WSL
  else cat >/dev/null; exit 3; fi; } <<'EMIT_EOF'
…the emitted prompt, verbatim (already prefixed if the driver has a command token)…
EMIT_EOF
```

A single-feed heredoc pipes to exactly one chosen tool and can't retry a second, so getting the
**selection** right up front is the fix — a chosen tool that still exits non-zero just degrades to
chat-only.

## Branch on the result

- **On success**, print a confirmation reflecting the single-paste UX — e.g.
  `📋 Copied — ⌘V into a fresh session`. The calling skill supplies the exact wording (naming the
  driver prefix, if any).
- **On `exit 3` (no tool found) or any non-zero exit**, fall back to chat-only: **never report a
  false success**, never block the handoff (the prompt is still shown in chat), **and name the
  remedy** — e.g. *"No clipboard tool found — copy the prompt above manually, or `sudo apt install
  xclip` (or `xsel`) to enable one-key copy."*
