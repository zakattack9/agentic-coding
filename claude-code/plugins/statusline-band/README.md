# statusline-band

A mod that ports `claude-code/statuslines/statuslineV4.sh` into the band above the prompt, so the Claude Desktop Code tab (which doesn't run `statusLine` scripts) gets the same figures in two rows:

```
statusline-band  ⟡  main  ⟡  Opus 5.5  ⟡  high               2m  ⟡  v2.1.286  ⟡  f00a9b5b…afddad
5h 13% · 7d 26%  ⟡  ctx 8%  ⟡  $0.77  ⟡  Caveman                        RAM 2.03GB (6 · 2.9%)
```

Each row puts its main figures on the left and pushes the rest to the right edge. Each figure is drawn in its own color, labels included. The `5h`/`7d` labels and the RAM process count are a shade darker, and the `⟡` separators are dimmed. Colors are the script's xterm-256 palette converted to hex. A non-empty `NO_COLOR` turns them off.

The session id is a button. In the terminal, pressing it copies the full id. The Desktop app doesn't let mods write to the clipboard yet, so there it shows the full id in a toast instead.

## Install

```
/plugin marketplace add zakattack9/agentic-coding
/plugin install statusline-band@zaksak
```

Requires a Claude Code build with mods. Tested on v2.1.286 in the Desktop Code tab.

## Options

Set via `/plugin configure statusline-band@zaksak` or `/config`:

| Option | Default | What it does |
| --- | --- | --- |
| `show_in_terminal` | `false` | Also draw the band in terminal sessions. Off so the CLI's real status line isn't doubled. |
| `dir_levels` | `3` | Trailing path components shown; `0` shows the full path. |
| `refresh_seconds` | `5` | How often git, RAM and duration refresh between turns. |

## Differences from the script

- Draws **above** the prompt: mods can't draw in the status line slot below it.
- Two rows instead of three. Duration, version and session id sit on the right of row 1, output style ends row 2, and the session id is shortened to `first8…last6`. Duration and output style keep each other's old colors.
- Effort comes from the main loop's last request (`turn.step`), and is blank for a model without effort. Before the first request, or after `/effort` or `/model` changes between turns, it comes from the `/config` row until the next request.
- Output style comes from the engine's own `/config` row, matched by key name. It shows `default` when not found.
- Context shows `—` until the first response of a fresh or just-compacted session, where the script showed `0%`.
- Rate limits read `0%` once a window's reset time has passed, since the engine's reading is from the last response. A gateway's `spend_limit` shows as `spend`. With no reading at all, the segment is left out instead of saying `No ongoing session`.
- Cost is left out when the host keeps no cost ledger, instead of showing `$0.00`.
- Duration counts from this run's start, read from the engine process's uptime. The engine's own session start counts from a resumed session's first launch. `/clear` still resets it.
- RAM sums every process named `claude` for this user, as the script does: all Desktop Code tabs and terminal sessions, not just this one. This session's engine is always included, and the Desktop app's `disclaimer` wrapper is skipped.

## Develop

```
claude plugin validate claude-code/plugins/statusline-band
claude plugin test claude-code/plugins/statusline-band
claude --plugin-dir claude-code/plugins/statusline-band
```
