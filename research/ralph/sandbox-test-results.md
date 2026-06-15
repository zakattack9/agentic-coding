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

**Host → sandbox sync for file overwrites does not work.** Once Mutagen has synced a file version into the sandbox, subsequent host overwrites of that same file path are silently ignored — **permanently**, not as a temporary delay.

#### Basic sync behavior

| Scenario | Result |
|----------|--------|
| New file created on host → visible in sandbox | **PASS** (within 3-5s) |
| File overwritten on host → sandbox sees change | **FAIL** (permanently stale) |
| Sandbox writes file → next `docker sandbox run` sees it | **PASS** (immediate) |
| Sandbox writes file → host sees change | **PASS** (within 2-3s) |

**Independently verified** by running `ralph/verify-sync-latency.sh` — the host→sandbox overwrite failure is reproducible.

#### Targeted follow-up tests

After the initial findings, six additional tests were run to pinpoint exactly when the issue triggers and which workarounds are effective:

| Test | Scenario | Result |
|------|----------|--------|
| A | Host creates new file → sandbox reads it | **PASS** — visible in 5s |
| B | Host overwrites file that sandbox previously read (sandbox never wrote it) | **FAIL** — permanently stale |
| C | Host creates file, then overwrites within 5s before sandbox syncs first version | **PASS** — sandbox sees version 2 (only synced once) |
| D | Sandbox writes file, then host overwrites it | **FAIL** — permanently stale |
| E | Same as D but with 30s wait between host write and check | **FAIL** — still stale after 30s |
| F | `docker sandbox stop` then restart after host overwrite | **PASS** — sandbox picks up host version |
| G | Delete file inside sandbox via `exec`, then host writes new version | **PASS** — sandbox sees new version |

Key takeaway from Test B: **the sandbox does not need to have written the file** for the issue to occur. Simply having synced and read a file is enough. Any subsequent host overwrite of that file is ignored.

Key takeaway from Test C: If the host overwrites a file **before** Mutagen has synced the first version into the sandbox, the sandbox gets the latest version. The issue only triggers after a successful sync has established a cached version.

#### Root Cause: Mutagen Sync Staleness

Docker Sandboxes use [Mutagen](https://mutagen.io/documentation/synchronization/) (acquired by Docker) as the bidirectional sync engine. Mutagen creates an ext4 cache in the sandbox VM and uses a three-way merge algorithm to track file state.

The initial hypothesis was that this was a two-sided Mutagen conflict (both endpoints modified the file). **Test B disproved this** — the sandbox only read the file, never wrote it. A one-sided host modification should propagate cleanly in any Mutagen sync mode.

The actual root cause appears to be a **sync cache staleness bug** in Docker's Mutagen integration: once a file has been synced into the sandbox VM's ext4 cache, the Mutagen filesystem watcher fails to detect or propagate subsequent host-side overwrites of that file. This is consistent with:
- [Docker for Windows #14060](https://github.com/docker/for-win/issues/14060) — files not updating inside container after Docker Desktop upgrade (same symptom, different platform)
- [Mutagen conflict resolution issue #271](https://github.com/mutagen-io/mutagen/issues/271) — reconciliation algorithm bugs fixed in v0.12 rewrite
- [Docker Synchronized File Shares stalling #7281](https://github.com/docker/for-mac/issues/7281) — sync stalling on macOS

Docker does not expose Mutagen's sync configuration, so you cannot:
- Run `mutagen sync flush` to force a resync
- Change the sync mode or conflict resolution strategy
- Inspect the sync session state

#### Volume mounts are not an alternative

Docker Sandboxes do not support `-v` or `--mount` flags. The `docker sandbox create` command only accepts workspace paths. The [architecture docs](https://docs.docker.com/ai/sandboxes/architecture/) state: "This is file synchronization, not volume mounting. Files are copied between host and VM." The sync mechanism is baked into the sandbox design and cannot be swapped for bind mounts.

#### Impact on Ralph Loop

**No impact on the default automated flow.** The Ralph Loop pattern is:
1. Sandbox writes `prd.json` (and other files)
2. Host reads `prd.json` to check completion (sandbox→host sync works)
3. Next `docker sandbox run` — sandbox reads its own `prd.json` (sandbox→sandbox persistence works)

The host never overwrites workspace files during the loop. All file mutations happen inside the sandbox.

**Impacts manual intervention scenarios:**
- Editing `prd.json` on the host to add/remove stories while the loop is paused — sandbox won't see the changes
- Hot-reloading `ralph/prompt.md` while the loop runs — sandbox keeps the old version
- `ralph.sh` injecting a feedback file between iterations — sandbox won't see it
- Any multi-process coordination via shared workspace files

#### Workarounds for Host→Sandbox Writes

Three confirmed workarounds and two additional options, ranked by practicality:

**1. `docker sandbox exec` as a write proxy (confirmed working)**

Bypass the sync layer entirely by writing directly into the sandbox's filesystem:

```bash
# Write content directly into the sandbox
docker sandbox exec my-sandbox bash -c 'cat > /project/ralph/feedback.txt' <<< 'Focus on error handling next'

# Pipe a host file into the sandbox
docker sandbox exec -i my-sandbox bash -c 'cat > /project/ralph/prd.json' < /host/path/prd.json
```

This writes at the VM filesystem level. No sync issue possible because the write happens inside the VM. The change then syncs back to the host normally. Best for programmatic writes from `ralph.sh`.

**2. Delete-inside-sandbox, then write-on-host (confirmed working — Test G)**

Delete the file inside the sandbox, wait for the deletion to sync, then write the new version on the host:

```bash
docker sandbox exec my-sandbox rm /project/file.json   # delete inside sandbox
sleep 3                                                  # wait for delete to sync
echo '{"new": "data"}' > /project/file.json             # host creates "new" file
```

Mutagen treats the host write as a new file (no prior synced version to conflict with). Best for cases where you want to edit files on the host side (e.g., with your editor) rather than piping through `exec`.

**3. Stop/start the sandbox to force resync (confirmed working — Test F)**

```bash
docker sandbox stop my-sandbox
# Make any host edits here — they will be picked up on restart
docker sandbox run my-sandbox -- -p "$PROMPT"
```

Stopping and restarting the sandbox forces Mutagen to re-snapshot the host filesystem. All host changes are picked up. Adds a few seconds of overhead. **Best for manual intervention** — e.g., pausing the loop, editing `prd.json` in your editor, then resuming. `ralph.sh` could use this approach when resuming after a pause.

**4. Environment variables for small data**

For metadata like iteration count or status flags, bypass the filesystem entirely:

```bash
docker sandbox run my-sandbox -e RALPH_ITERATION=3 -e RALPH_STATUS=continue -- -p "$PROMPT"
```

**5. Wait for Docker to fix it**

Docker Sandboxes are beta. The Mutagen reconciliation algorithm was rewritten in v0.12 to fix a similar class of bugs. Docker's internal Mutagen version may receive fixes. Track Docker Desktop release notes.

#### Recommended strategy for `ralph.sh`

- **During automated iteration:** No workaround needed. The sandbox reads its own writes.
- **Programmatic host→sandbox writes (feedback injection, prompt updates):** Use `docker sandbox exec` (workaround 1).
- **Resuming after user pause with manual edits:** Use `docker sandbox stop` + restart (workaround 3). This is the simplest UX — the user edits files normally on the host, and `ralph.sh` does a stop/start cycle when resuming.
- **Optional safety net:** `ralph.sh` could `docker sandbox stop` + restart between every N iterations as a cheap way to guarantee the sandbox always has the latest host state. The overhead is a few seconds per stop/start cycle.

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

### 2. Host cannot overwrite files the sandbox has already synced

Once Mutagen has synced a file into the sandbox, host-side overwrites of that file are permanently ignored (see Step 4 root cause analysis). This is not limited to files the sandbox wrote — even files the sandbox only read are affected.

The default automated loop avoids this naturally:

```
ralph.sh (host)                     Sandbox VM
                                    ┌─────────────────────────┐
  reads prd.json ◄────sync────────  │ Claude writes prd.json  │
  reads progress.txt ◄──sync──────  │ Claude writes progress  │
  reads output ◄─────────────────   │ Claude outputs to stdout│
                                    │ Claude commits to git   │
                                    └─────────────────────────┘
```

For scenarios where the host does need to write into the sandbox (feedback injection, manual edits, prompt updates), three confirmed workarounds exist:

| Scenario | Recommended workaround |
|----------|----------------------|
| `ralph.sh` injects data programmatically | `docker sandbox exec` write proxy |
| User edits files on host during pause | `docker sandbox stop` + restart before resuming |
| User wants to edit a specific file | `docker sandbox exec ... rm`, then edit on host |

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

## Documents Updated

The following reference docs have been updated based on these findings:

| Document | Changes applied |
|----------|----------------|
| `docker-sandbox-isolation.md` | Replaced custom Dockerfile approach with create+exec+run pattern. Fixed `touch` → `echo '{}'`. Replaced "file sync latency" caveat with full sync staleness documentation including stop/start-on-resume pattern for IDE editing. Updated `dclaude` wrapper. Updated invocation section. |
| `ralph-loop-plan.md` Section 3 | Updated sandbox invocation to create+exec+run pattern with existence check. Documented stop/start-on-resume and `exec` write proxy for file sync constraint. |
| `ralph-loop-plan.md` Section 4 | Notes that custom Dockerfile template doesn't work; sandbox setup is done via `exec`. Fixed `.claude.json` initialization. |

---

## Sandbox Stop/Start Timing

Measured across multiple cycles to determine the overhead of a stop/start cycle (relevant for workaround 3 and the optional safety-net resync).

### Raw results

**Stop + start cycles (no `run` in between — warm):**

| Cycle | Stop | Start | Total |
|-------|------|-------|-------|
| 1 (cold) | 10,300ms | 133ms | 10,433ms |
| 2 | 133ms | 127ms | 260ms |
| 3 | 126ms | 122ms | 248ms |
| 4 | 129ms | 126ms | 255ms |
| 5 | 124ms | 127ms | 251ms |

**Stop + start after a `run` (pipe mode) — realistic Ralph pattern:**

| Cycle | Stop | Start | Run (`-p "Say OK"`) | Total |
|-------|------|-------|---------------------|-------|
| 1 | 146ms | 147ms | 6,195ms | 6,488ms |
| 2 | 10,332ms | 133ms | 5,742ms | 16,207ms |
| 3 | 10,355ms | 139ms | 5,652ms | 16,146ms |

**Second warm stop/start run (confirming bimodal pattern):**

| Cycle | Stop | Start | Total |
|-------|------|-------|-------|
| 1 (first after run) | 10,334ms | 122ms | 10,456ms |
| 2 | 130ms | 124ms | 254ms |
| 3 | 139ms | 143ms | 282ms |
| 4 | 121ms | 130ms | 251ms |
| 5 | 122ms | 137ms | 259ms |

### Analysis

There is a clear **bimodal pattern**:

| Scenario | Stop time | Start time | Total overhead |
|----------|-----------|------------|----------------|
| After `docker sandbox run` (realistic) | ~10.3s | ~130ms | **~10.4s** |
| Back-to-back stop/start (warm, no run) | ~125ms | ~130ms | **~250ms** |

- **Start is always fast** (~130ms) regardless of scenario
- **Stop is the bottleneck** — ~10.3s after a `run` command, likely due to process/session teardown inside the sandbox
- **Pipe mode `run` adds ~6s** minimum even for trivial prompts (real Ralph iterations take much longer)

### Implications for Ralph Loop

- **Workaround 3 (stop/start resync)** adds ~10.4s overhead per use. Acceptable for manual-pause-and-resume (happens rarely, user is already waiting). Acceptable as an every-N-iterations safety net.
- A full iteration cycle is: **~10s stop + ~0.1s start + Ns run**. For real work where `run` takes minutes, the 10s overhead is negligible (<5% for a 3-minute iteration).
- **The stop overhead does NOT compound** — warm stop/start (without a preceding `run`) is ~250ms.

---

## Verification Script

`ralph/verify-sync-latency.sh` is a self-contained script that reproduces the host→sandbox file overwrite sync issue. It does not require Claude auth — only `docker sandbox create/exec/rm` and file I/O.

Tests:
1. New file sync (host → sandbox) — expected **PASS**
2. File overwrite sync (host → sandbox) — expected **FAIL**
3. Sandbox→host sync — expected **PASS**

Cleans up all artifacts on exit. Run with: `./ralph/verify-sync-latency.sh`

The follow-up tests (A through G) documented in Step 4 were run interactively and are not in the script. They could be added if a more comprehensive regression test is needed.

---

## Test Artifacts Cleaned Up

All sandboxes, temp directories, custom template files, and Docker images created during testing were removed.
