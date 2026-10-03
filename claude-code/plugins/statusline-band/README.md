# statusline-band

A mod that ports `claude-code/statuslines/statuslineV4.sh` into the band above the prompt, so the Claude Desktop Code tab (which doesn't run `statusLine` scripts) gets the same three rows:

1. directory ✦ git branch ✦ model ✦ effort
2. 5h / 7d rate limits ✦ RAM ✦ context % ✦ cost ✦ duration
3. Claude Code version ✦ session id ✦ output style

Colors are the script's xterm-256 palette converted to hex. `NO_COLOR` turns them off.

## Install

```
/plugin marketplace add zakattack9/agentic-coding
/plugin install statusline-band@zaksak
```

Requires Claude Code v2.1.287 or later (mods).

## Options

Set via `/plugin configure statusline-band@zaksak` or `/config`:

| Option | Default | What it does |
| --- | --- | --- |
| `show_in_terminal` | `false` | Also draw the band in terminal sessions. Off so the CLI's real status line isn't doubled. |
| `dir_levels` | `3` | Trailing path components shown; `0` shows the full path. |
| `refresh_seconds` | `5` | How often git, RAM and duration refresh between turns. |

## Differences from the script

- Draws **above** the prompt: mods can't draw in the status line slot below it.
- Effort comes from the main loop's last request (`turn.step`); before the first request it falls back to the `/config` row.
- Output style comes from the `/config` row, matched by key name; shows `default` when not found.
- RAM uses the script's `pgrep claude` match, which may not find the Desktop app's process.

## Develop

```
claude plugin validate claude-code/plugins/statusline-band
claude plugin test claude-code/plugins/statusline-band
claude --plugin-dir claude-code/plugins/statusline-band
```
