# iTerm2 file-reference plugin

This optional plugin expands explicitly spoken file references for local Codex
and Claude Code CLI sessions running in iTerm2 on macOS. The portable Spokenly
processors do not load it unless `SPOKENLY_ITERM_FILE_REFERENCES=1` is set.

## Supported environment

- macOS with the sideload build of Spokenly
- iTerm2 with its Python API runtime and shell integration enabled
- one local Codex or Claude Code process in the focused iTerm2 pane
- a foreground CLI process whose OS working directory is inside a Git working
  tree or linked worktree

The first version intentionally rejects SSH sessions, regular tmux sessions,
containers without a verified local path mapping, non-Git directories, other
terminal emulators, desktop agent apps, unrelated foreground processes, and
extra workspace roots added outside the harness's primary Git worktree. A Git
submodule is its own project when the harness is launched inside it; submodule
contents are not folded into a superproject index.

The plugin uses the foreground CLI process's OS working directory, with iTerm's
pane path as a fallback. It does not install Codex or Claude Code hooks and
therefore cannot observe a different logical directory maintained internally by
the CLI. For reliable references, launch `codex` or `claude` from the intended
project or worktree and do not relocate the session with Codex `-C/--cd`, Claude
Code `/cd`, or persistent in-session shell directory changes.

## Install the iTerm2 context daemon

Run:

```bash
dictation/spokenly/plugins/iterm_file_references/install.sh
```

The installer creates missing parent directories and a symlink at
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/spokenly_iterm_context.py`.
Restart iTerm2, or launch `spokenly_iterm_context.py` once from the **Scripts**
menu. If iTerm2 asks to install or update its Python runtime, allow it. Check
**Scripts → Manage → Console** if the daemon reports an error.

The daemon monitors only iTerm2 focus and session metadata. It writes the
focused window, tab, pane/session ID, TTY, foreground PID, process title,
working directory, hostname, and SSH integration level to a mode-`0600` file
in the current user's temporary directory. It does not read transcript text,
terminal contents, project file contents, or command history.

## Enable the plugin in Spokenly

Turn on **Include Focused App Context** for the Spokenly mode. Keep the existing
Pre-AI and Post-AI scripts, but export the opt-in variable in both wrappers.

Pre-AI:

```bash
#!/usr/bin/env bash
export SPOKENLY_ITERM_FILE_REFERENCES=1
exec "/absolute/path/to/agentic-coding/dictation/spokenly/scripts/pre_ai.sh"
```

Post-AI:

```bash
#!/usr/bin/env bash
export SPOKENLY_ITERM_FILE_REFERENCES=1
exec "/absolute/path/to/agentic-coding/dictation/spokenly/scripts/post_ai.sh"
```

Unset the variable, set it to `0`, or remove the two export lines to disable the
plugin without changing the portable processors. Run `uninstall.sh` to remove
the iTerm2 AutoLaunch symlink.

## Spoken forms

The parser intentionally requires an explicit file-reference phrase:

| Dictation | Example result |
| --- | --- |
| `at file readme dot markdown` | `@README.md` |
| `mention file pre AI dot pie` | `@scripts/pre_ai.py` |
| `at file server slash config dot pie` | `@server/config.py` |
| `at file button dot tee ess ex` | `@../../src/Button.tsx` from a nested CWD |
| `at file preload dot pee aitch pee` | `@preload.php` |
| `at file variables dot terraform variables` | `@variables.tfvars` |
| `at file diagram dot draw dot eye oh` | `@diagram.drawio` |
| literal `@README.md` from transcription | `@README.md` |

Bare conversational uses of “at” are not commands. A basename prefers matching
candidates beneath the active harness CWD, then selects the first path returned
by Git's project-file enumeration. Speak one or more parent directories to
select a later match explicitly. Individually ignored files are referenceable;
ignored directories are not recursively indexed.
Extensions accept their literal spelling, separately transcribed letters and
digits (for example, `pee aitch pee` or `double you oh eff eff two`), and common
format names such as `PowerShell`, `Terraform`, `markdown`, or `comma separated
values`. The same vocabulary applies to compound suffixes such as `.d.ts`,
`.pkr.hcl`, and `.xml.dist`.

## Resolution and safety

The plugin obtains the exact focused iTerm2 session rather than using titles or
recency. If iTerm reports a foreground child such as an MCP or language server,
the resolver walks same-TTY process ancestors to bind to the owning Codex or
Claude Code process. It then discovers the actual Git worktree with `git
rev-parse --show-toplevel` and indexes tracked, untracked non-ignored, and
individually ignored files. Ignored directories, missing sparse-checkout files,
and symlinks whose targets leave the worktree are excluded. Paths containing
terminal control characters are also excluded.

The absolute canonical file is retained internally. The inserted `@` path is
rendered relative to the foreground process's OS CWD and verified by resolving
it back to the same canonical file. This handles normal branches, linked
worktrees, CLIs launched from nested working directories, multiple windows,
multiple tabs, and multiple split panes.

Pre-AI stores exact resolved references in private state keyed by both a random
run nonce and the globally unique iTerm2 session ID. Qwen receives only protected
tokens. Post-AI rechecks the pane ID, foreground PID, harness, process CWD,
worktree, and file before restoring each path. If focus, pane, harness, CWD, or
file verification fails, the plugin restores the original spoken file phrase
from a separate recovery manifest and lets the portable dictation pipeline
continue. If Qwen damages the structural frames after the pane and paths pass
verification, Post-AI ignores the model output and applies the recorded paths to
their exact spans in the original source transcript. Plugin enrichment failures
therefore do not block or discard a dictation, and Qwen cannot determine a
recovered path's content or placement.

When several files match, the first deterministic Git-enumerated candidate is
selected; a spoken parent directory selects another candidate explicitly.
Unrecognized spoken file names are left as ordinary transcript text. A plugin
prerequisite failure before a protected reference is created is a silent no-op
for unrelated applications and otherwise fails open to the unchanged portable
dictation pipeline.

The parser also tolerates a missing transcription boundary after “file,” such
as `at filesnippets.json`. For speed, normal Git files are searched first;
individually ignored files are queried only when the first pass has an
unresolved explicit reference. Alias construction is restricted to prefixes
that occur in the current transcript, and each process ancestor is inspected
with one bounded `ps` call.

## Diagnostics

Optional-plugin failures and recovery events never print to Spokenly's stderr
or change the script exit status. They are appended as JSON Lines to a private
mode-`0600` log:

```text
~/Library/Logs/Spokenly/iterm-file-references.log
```

The log rotates at 512 KiB and retains one `.1` backup. Follow it while testing:

```bash
tail -f "$HOME/Library/Logs/Spokenly/iterm-file-references.log"
```

Set `SPOKENLY_ITERM_FILE_REFERENCE_LOG` in both script wrappers to override the
location. Logging is best-effort and can never block dictation.
