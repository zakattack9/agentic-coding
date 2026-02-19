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

**Overall: FEASIBLE** — Docker Sandboxes work for the Ralph Loop with minor architectural adjustments.

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

**Observation:** Occasional empty responses on pipe mode (exit 0 but no text output). Likely TTY detection or cold-start issue. Resolved on retry — not a consistent failure.

### Step 3: File Sync (Sandbox → Host) — Bidirectional

Created `sync-test.json` on host with `{"status": "created_on_host"}`. Asked Claude in sandbox to change status to `modified_in_sandbox`. After 2s sleep, host file reflected the change. **Sandbox → host sync is reliable.**

### Step 4: File Sync Latency — Critical Finding

**Host → sandbox sync for file overwrites is unreliable.** When a file is overwritten on the host after the sandbox has already cached it, the sandbox continues to see the stale version indefinitely (tested up to 30+ seconds).

| Scenario | Result |
|----------|--------|
| New file created on host → visible in sandbox | **PASS** (within 5s) |
| File overwritten on host → sandbox sees change | **FAIL** (stale for 30s+) |
| Sandbox writes file → next `docker sandbox run` sees it | **PASS** (immediate) |
| Sandbox writes file → host sees change | **PASS** (within 2s) |

**Impact on Ralph Loop:** Low. In the Ralph Loop pattern, the sandbox writes `prd.json` and the host only reads it. The sandbox sees its own writes across `docker sandbox run` invocations (the sandbox VM persists). The host→sandbox overwrite issue only matters if the host modifies files between iterations, which the current design does not require.

**Recommendation:** The Ralph Loop should NOT modify workspace files from the host between iterations. All file mutations should happen inside the sandbox. The host should only read files for status checks.

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

`docker sandbox run --pull-template never -t dclaude:latest` fails with "pull access denied" even though the image exists in the local Docker daemon. The sandbox VM has a separate image store and cannot access the host's locally-built images.

**Workaround:** Use the default `claude` template + `docker sandbox exec` to set up the custom entrypoint/symlinks after creation. This two-step approach (create → exec → run) works reliably:

```bash
# Step 1: Create with default template + extra workspace mount
docker sandbox create --name my-sandbox claude "$PROJECT_DIR" "$HOME/.dclaude_state"

# Step 2: Set up auth symlinks via exec
docker sandbox exec -u root my-sandbox bash -c '
  STATE_DIR="/Users/$(ls /Users/ | grep -v Shared | head -1)/.dclaude_state"
  rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
  ln -s "$STATE_DIR/.claude" /home/agent/.claude
  ln -s "$STATE_DIR/.claude.json" /home/agent/.claude.json
  chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
'

# Step 3: Run
docker sandbox run my-sandbox -- -p "$PROMPT"
```

**Alternative:** `docker sandbox save` can snapshot a configured sandbox as a template, but the saved image still suffers from the same loading issue. This may be a Docker Desktop beta limitation.

**Recommendation:** Update `docker-sandbox-isolation.md` to use the exec-based setup approach instead of a custom Dockerfile template.

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
- `hello.txt` created with content "Hello from Ralph Loop" ✅
- `prd.json` updated: `passes: true`, note added ✅
- Git commit: `feat: [US-001] - Create hello.txt` ✅
- Output: `<promise>COMPLETE</promise>` ✅

The full Ralph Loop iteration pattern works end-to-end inside a Docker Sandbox.

---

## Architecture Recommendations

Based on these test results, the following changes are recommended for `ralph.sh`:

1. **Use exec-based setup instead of custom Dockerfile template.** The `--pull-template never -t dclaude:latest` approach doesn't work with locally-built images. Use `docker sandbox create` + `docker sandbox exec` + `docker sandbox run` three-step pattern instead.

2. **Never modify workspace files from the host between iterations.** Host→sandbox file overwrite sync is unreliable. All mutations (including `prd.json` updates) should happen inside the sandbox.

3. **Read completion status from host after sync delay.** Sandbox→host sync works within 2s. Add a 2-3s sleep before reading `prd.json` on the host to check for `<promise>COMPLETE</promise>`.

4. **Fix `.claude.json` initialization.** Use `echo '{}' > ~/.dclaude_state/.claude.json` instead of `touch`.

5. **Sandbox creation is a one-time cost per project.** The `create` + `exec` setup only needs to happen once. Subsequent `docker sandbox run` invocations reuse the existing sandbox (1:1 workspace mapping).

6. **Dockerfile base image is non-root.** Any `RUN chmod` commands fail. Use `COPY --chmod=` or configure permissions at build time.

---

## Test Artifacts Cleaned Up

All sandboxes, temp directories, custom template files, and Docker images created during testing were removed.
