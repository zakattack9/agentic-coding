# Docker Sandbox Feasibility Test Results

> Tested: 2026-02-18
> Docker Desktop: 29.2.1 (with Sandboxes beta)
> System: macOS 15.6.1, Apple Silicon
> Auth: Interactive OAuth (Max plan)
> Base template: `docker/sandbox-templates:claude-code`

---

## Summary

| # | Test | Result | Notes |
|---|------|--------|-------|
| 1 | Docker Sandbox availability | **PASS** | `docker sandbox ls` exits 0 |
| 2 | Default sandbox + pipe mode | **PASS** | Output contains `SANDBOX_OK`, exit 0 |
| 3 | File sync (host → sandbox → host) | **PASS** | Sandbox modified file, host saw change within 2s |
| 4 | File sync latency | **PARTIAL** | See detailed notes below |
| 5 | Build custom `dclaude` template | **PASS** (with workaround) | `COPY --chmod=755` required; `RUN chmod` fails (non-root base image) |
| 6 | Custom template with pipe mode | **FAIL** (workaround found) | `--pull-template never` cannot access locally-built images; used `exec` approach instead |
| 7 | Auth persistence | **PASS** | Credentials in `~/.dclaude_state/.claude/` survive sandbox destruction + recreation |
| 8 | Ralph Loop iteration simulation | **PASS** | All 4 checks passed: file created, prd.json updated, git commit made, `<promise>COMPLETE</promise>` output |

**Overall: FEASIBLE** — Docker Sandboxes work for the Ralph Loop with architectural adjustments documented below.

---

## Detailed Notes

### Step 1: Docker Sandbox Availability

```
$ docker sandbox ls
No sandboxes found
```

Exit code 0. Feature is enabled and functional.

### Step 2: Default Sandbox + Pipe Mode

First run required auth (see step 7). After auth was configured via symlinks, pipe mode worked correctly:

```
$ docker sandbox run sb-pipe-fresh -- -p "Respond with exactly: SANDBOX_OK"
SANDBOX_OK
```

**Observation:** Occasional empty responses on pipe mode (exit 0 but no text output). Likely TTY detection or cold-start issue. Resolved on retry — not a consistent failure. `ralph.sh` should treat exit 0 with empty output as a transient failure and retry.

### Step 3: File Sync (Sandbox → Host) — Bidirectional

Created `sync-test.json` on host with `{"status": "created_on_host"}`. Asked Claude in sandbox to change status to `modified_in_sandbox`. After 2s sleep, host file reflected the change. **Sandbox → host sync is reliable.**

### Step 4: File Sync — Critical Finding

**Host → sandbox sync for file overwrites does not work.** When a file is overwritten on the host after the sandbox has already synced it, the sandbox sees the stale version **indefinitely**. This is not a latency issue — it is a **Mutagen conflict detection** issue (see root cause analysis below).

| Scenario | Result |
|----------|--------|
| New file created on host → visible in sandbox | **PASS** (within 5s) |
| File overwritten on host → sandbox sees change | **FAIL** (permanently stale) |
| Sandbox writes file → next `docker sandbox run` sees it | **PASS** (immediate) |
| Sandbox writes file → host sees change | **PASS** (within 2s) |

**Independently verified** by running `ralph/verify-sync-latency.sh` — the host→sandbox overwrite failure is reproducible.

#### Root Cause: Mutagen Conflict Detection

Docker Sandboxes use [Mutagen](https://mutagen.io/documentation/synchronization/) (acquired by Docker) as the bidirectional sync engine. Mutagen uses a **three-way merge algorithm** that tracks the last "agreed-upon" state of every file and detects what each endpoint changed since then.

When the sandbox writes a file and the host subsequently overwrites the same file, Mutagen detects **modifications on both endpoints** relative to the last agreed-upon state. In `two-way-safe` mode (the likely default for sandboxes), such conflicts are **not auto-resolved** — the file stays at whichever version was last agreed upon, which is the sandbox's version.

This is not a latency issue that resolves over time. The file is stuck in a conflict state. Docker does not expose Mutagen's sync configuration, so you cannot:
- Switch to `two-way-resolved` mode (where the host/alpha would win conflicts)
- Run `mutagen sync flush` to force a resync
- Configure conflict resolution strategy

This explains why **new files** sync fine (no prior agreed-upon state = no conflict) but **overwrites** don't.

References:
- [Mutagen file synchronization docs](https://mutagen.io/documentation/synchronization/)
- [Mutagen conflict resolution issue #271](https://github.com/mutagen-io/mutagen/issues/271) — similar bug in Mutagen v0.11, fixed in v0.12 reconciliation rewrite
- [Docker Synchronized File Shares docs](https://docs.docker.com/desktop/features/synchronized-file-sharing/)
- [Docker for Windows #14060](https://github.com/docker/for-win/issues/14060) — related file sync regression

#### Impact on Ralph Loop

**Low for the default flow.** The Ralph Loop pattern is:
1. Sandbox writes `prd.json` (and other files)
2. Host reads `prd.json` to check completion (sandbox→host sync works)
3. Next `docker sandbox run` — sandbox reads its own `prd.json` (sandbox→sandbox persistence works)

The host never overwrites workspace files between iterations. All file mutations happen inside the sandbox.

**Becomes a problem if you need:**
- Host-injected feedback between iterations (e.g., writing `ralph/feedback.txt` from `ralph.sh`)
- Hot-reloading the prompt template while the loop runs
- Manual `prd.json` edits during a paused loop
- Multi-process coordination via shared files

#### Workarounds for Host→Sandbox Writes

Ranked by reliability:

**1. `docker sandbox exec` as a write proxy (confirmed working)**

Bypass the sync layer entirely by writing directly into the sandbox's filesystem:

```bash
# Write content directly into the sandbox
docker sandbox exec my-sandbox bash -c 'cat > /project/ralph/feedback.txt' <<< 'Focus on error handling next'

# Pipe a host file into the sandbox
docker sandbox exec -i my-sandbox bash -c 'cat > /project/ralph/prd.json' < /host/path/prd.json
```

This writes at the VM filesystem level. No Mutagen conflict possible because only one endpoint changed the file. The change then syncs back to the host normally. This is the recommended approach for any host→sandbox writes that `ralph.sh` needs to perform.

**2. Delete-inside-sandbox, then write-on-host (untested, theoretically sound)**

Since Mutagen handles deletions cleanly ("deletions can be overwritten" per Mutagen docs), this sequence might break the conflict:

```bash
docker sandbox exec my-sandbox rm /project/file.json   # delete inside sandbox
sleep 2                                                  # wait for delete to sync
echo '{"new": "data"}' > /project/file.json             # host creates "new" file
```

Mutagen would see: sandbox deleted, host created → no conflict → host version wins. **Not tested** — the sync engine might still see it as a conflict. Worth exploring if the `exec` proxy approach is insufficient.

**3. Environment variables for small data**

For metadata like iteration count or status flags, bypass the filesystem entirely:

```bash
docker sandbox run my-sandbox -e RALPH_ITERATION=3 -e RALPH_STATUS=continue -- -p "$PROMPT"
```

**4. Stop/start sandbox to force resync (untested, heavy)**

```bash
docker sandbox stop my-sandbox
# host writes here
docker sandbox run my-sandbox -- ...
```

Stopping the sandbox might cause Mutagen to re-snapshot the host filesystem on restart. Adds several seconds of overhead. Only viable as a last resort.

**5. Wait for Docker to fix it**

Docker Sandboxes are beta. The Mutagen reconciliation algorithm was rewritten in v0.12 to fix a similar class of conflict bugs. Docker's internal Mutagen version may receive the same fix. Track Docker Desktop release notes.

### Step 5: Build Custom `dclaude` Template

The Dockerfile from the reference doc needed one fix:

```dockerfile
# Original (FAILS — base image runs as non-root)
RUN chmod +x /usr/local/bin/dclaude-entrypoint

# Fixed
COPY --chmod=755 entrypoint.sh /usr/local/bin/dclaude-entrypoint
```

Image built successfully at 1.55GB (`dclaude:latest`).

### Step 6: Custom Template Loading — Blocked

`docker sandbox run --pull-template never -t dclaude:latest` fails with "pull access denied" even though the image exists in the local Docker daemon. The sandbox VM has a **separate image store** and cannot access the host Docker daemon's locally-built images. The `--pull-template never` flag only controls registry pulls — it does not make host-local images available to the VM.

`docker sandbox save` can snapshot a running sandbox back to a host image, but loading that image into a new sandbox still fails with the same error. This appears to be a Docker Desktop beta limitation.

**Working approach: create + exec + run pattern**

Instead of a custom Dockerfile, use the stock `claude-code` template and customize the live sandbox via `exec`:

```bash
# Step 1: CREATE — uses Docker's official claude-code template (pulled from registry)
docker sandbox create --name ralph-myproject claude "$PROJECT_DIR" "$HOME/.dclaude_state"

# Step 2: EXEC — customize the running VM (replaces what the custom entrypoint would do)
docker sandbox exec -u root ralph-myproject bash -c '
  STATE_DIR="/Users/'"$USER"'/.dclaude_state"
  rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
  ln -s "$STATE_DIR/.claude" /home/agent/.claude
  ln -s "$STATE_DIR/.claude.json" /home/agent/.claude.json
  chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
'

# Step 3: RUN — Claude finds auth via symlinks
docker sandbox run ralph-myproject -- -p "$PROMPT"
```

**Why this works:** Step 1 uses the official image which the VM can pull from Docker Hub. Step 2 modifies the live VM's filesystem directly — no custom image needed. Step 3 runs Claude normally.

**Cost is minimal:** Steps 1 and 2 only happen once per project. The sandbox persists (1:1 workspace-to-sandbox mapping). Subsequent iterations only need Step 3. In `ralph.sh`:

```bash
if ! docker sandbox ls | grep -q "$SANDBOX_NAME"; then
  docker sandbox create --name "$SANDBOX_NAME" claude "$PROJECT_DIR" "$HOME/.dclaude_state"
  docker sandbox exec -u root "$SANDBOX_NAME" bash -c '...'  # one-time setup
fi
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT"  # every iteration
```

### Step 7: Auth Persistence

After interactive OAuth login in one sandbox:
1. Credentials saved to `~/.dclaude_state/.claude/.credentials.json` (451 bytes)
2. Sandbox destroyed with `docker sandbox rm`
3. Fresh sandbox created with same `~/.dclaude_state` mount
4. Symlinks re-established via `exec`
5. Pipe mode worked without login prompt

**Auth persists across sandbox destruction and recreation.** The symlink approach works correctly.

**Note:** `~/.dclaude_state/.claude.json` must contain valid JSON (`{}` minimum). An empty file causes parse errors. The initial `touch` in the reference doc creates an empty file — should be `echo '{}' >` instead.

### Step 8: Ralph Loop E2E Simulation

Created a minimal project with `ralph/prd.json` containing one user story (US-001: "Create hello.txt"). Initialized git repo. Ran Ralph-style prompt.

**Results:**
- `hello.txt` created with content "Hello from Ralph Loop"
- `prd.json` updated: `passes: true`, note added
- Git commit: `feat: [US-001] - Create hello.txt`
- Output: `<promise>COMPLETE</promise>`

The full Ralph Loop iteration pattern works end-to-end inside a Docker Sandbox.

---

## Auth Developer Experience

### How auth works

Claude Code stores OAuth credentials at `~/.claude/.credentials.json` and config at `~/.claude.json`. Inside a Docker Sandbox, the agent user lives at `/home/agent/`, so those files don't exist. The solution is a shared state directory (`~/.dclaude_state/`) mounted as an extra workspace, with symlinks pointing the agent's home to it:

```
Host                                    Sandbox VM (/home/agent/)
~/.dclaude_state/                         .claude → /Users/you/.dclaude_state/.claude
  ├── .claude/                            .claude.json → /Users/you/.dclaude_state/.claude.json
  │   ├── .credentials.json
  │   └── settings.json
  └── .claude.json
```

### First-time setup (one-time per machine)

1. `ralph-init.sh` detects no `~/.dclaude_state/` and creates it with `echo '{}' > ~/.dclaude_state/.claude.json`
2. `ralph.sh` creates a sandbox, sets up symlinks via `exec`, tries to run Claude
3. Claude exits with "Not logged in" (exit code 1)
4. `ralph.sh` detects auth failure and prompts: *"Run `docker sandbox run <name>` in another terminal, complete `/login`, then `/exit`"*
5. User completes OAuth flow once. Credentials land in `~/.dclaude_state/.claude/.credentials.json`
6. `ralph.sh` retries. Works from now on

### Same project, subsequent runs

The sandbox persists (1:1 with workspace path). `docker sandbox run` reconnects to the existing VM. Auth is already there via symlinks. No setup needed.

### Different project

A new sandbox is created (different workspace path = different sandbox). But `~/.dclaude_state` is the **same mount** — it's a per-user directory, not per-project. The `exec` step re-establishes symlinks in the new sandbox, pointing to the same credentials. **No re-login needed.**

```
Project A sandbox  →  symlinks → ~/.dclaude_state/.claude/.credentials.json
Project B sandbox  →  symlinks → ~/.dclaude_state/.claude/.credentials.json
                                  (same file, one login serves all)
```

### Token expiration

OAuth tokens have a TTL. If they expire, the next `ralph.sh` iteration fails with exit 1. The loop runner should detect this and prompt the user to re-login interactively, same as first-time flow.

### API key alternative

For CI or environments where interactive OAuth isn't possible:

```bash
docker sandbox run -e ANTHROPIC_API_KEY="sk-ant-..." my-sandbox -- -p "$PROMPT"
```

This bypasses OAuth entirely. The `docker-sandbox-isolation.md` caveats section notes potential conflicts between the sandbox host proxy's `apiKeyHelper` and OAuth tokens — the API key approach avoids this.

---

## Architecture Recommendations

Based on test results and follow-up analysis:

### 1. Use create + exec + run pattern (not custom Dockerfile)

The custom Dockerfile/template approach (`--pull-template never -t dclaude:latest`) does not work — the sandbox VM cannot access locally-built images. Use the three-step pattern:

```bash
# One-time per project:
docker sandbox create --name "$NAME" claude "$PROJECT_DIR" "$HOME/.dclaude_state"
docker sandbox exec -u root "$NAME" bash -c '... symlink setup ...'

# Every iteration:
docker sandbox run "$NAME" -- -p "$PROMPT"
```

Steps 1-2 are idempotent if guarded by `docker sandbox ls | grep -q "$NAME"`.

### 2. All workspace mutations must happen inside the sandbox

Due to the Mutagen conflict issue, the host must never overwrite files that the sandbox has written. The data flow is strictly:

```
ralph.sh (host)                     Sandbox VM
                                    ┌─────────────────────────┐
  reads prd.json ◄────sync────────  │ Claude writes prd.json  │
  reads progress.txt ◄──sync──────  │ Claude writes progress  │
  reads output ◄─────────────────   │ Claude outputs to stdout│
                                    │ Claude commits to git   │
  (NEVER writes to workspace) ──X   │                         │
                                    └─────────────────────────┘
```

If `ralph.sh` needs to inject data between iterations, use `docker sandbox exec` as a write proxy (see Step 4 workarounds above), not host filesystem writes.

### 3. Read completion status from host after sync delay

Sandbox→host sync works within 2s. Add a 2-3s sleep before reading `prd.json` on the host to check for `<promise>COMPLETE</promise>` or `passes: true`.

### 4. Fix `.claude.json` initialization

Use `echo '{}' > ~/.dclaude_state/.claude.json` instead of `touch`. An empty file causes JSON parse errors on sandbox startup and triggers a backup/corruption recovery cycle.

### 5. Sandbox creation is one-time per project

The `create` + `exec` setup only runs once. Subsequent `docker sandbox run` invocations reuse the existing sandbox (1:1 workspace mapping). The sandbox persists installed packages, caches, git config, and auth symlinks across iterations.

### 6. Dockerfile base image is non-root

The `docker/sandbox-templates:claude-code` image runs as a non-root `agent` user. Any `RUN chmod` commands in a derived Dockerfile fail with "Operation not permitted". Use `COPY --chmod=` at build time instead. This is relevant if the custom template approach becomes viable in the future.

### 7. Handle transient empty responses

Pipe mode occasionally returns exit 0 with no output (ANSI escape sequences only, no text). This appears to be a cold-start or TTY detection issue. `ralph.sh` should detect empty output on exit 0 and retry the iteration (with a cap on retries).

### 8. Configure git inside the sandbox

The sandbox's `agent` user has no git identity by default. `ralph.sh` should set this during the one-time `exec` setup:

```bash
docker sandbox exec ralph-myproject bash -c '
  git config --global user.email "ralph@localhost"
  git config --global user.name "Ralph Loop"
'
```

This persists for the lifetime of the sandbox.

---

## Documents to Update

Based on these findings, the following reference docs need updates before implementation:

| Document | Change needed |
|----------|---------------|
| `docker-sandbox-isolation.md` | Replace custom Dockerfile approach with create+exec+run pattern. Fix `touch` → `echo '{}'`. Document Mutagen conflict root cause. |
| `ralph-loop-plan.md` Section 3 | Update `ralph.sh` sandbox invocation to use three-step pattern, add sandbox existence check, add auth failure detection/retry |
| `ralph-loop-plan.md` Section 4 | Note that custom Dockerfile template doesn't work; sandbox setup is done via `exec` |

---

## Verification Script

`ralph/verify-sync-latency.sh` is a self-contained script that independently reproduces the host→sandbox file overwrite sync issue. It:

1. Creates a sandbox with a temp workspace
2. Tests new file sync (host → sandbox) — expected PASS
3. Tests file overwrite sync (host → sandbox) — expected FAIL
4. Tests sandbox→host sync — expected PASS
5. Cleans up all artifacts on exit

Run with: `./ralph/verify-sync-latency.sh`

---

## Test Artifacts Cleaned Up

All sandboxes, temp directories, custom template files, and Docker images created during testing were removed.
