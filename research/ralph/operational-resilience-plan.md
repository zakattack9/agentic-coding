# Operational Resilience Additions — Plan for ralph-loop-plan.md

## Context

Cross-comparison of the ralph loop plan against ecosystem research ([Claude-Ralph-DR-1.md](../research/ralph-loops/deep-research/Claude-Ralph-DR-1.md), [ChatGPT-Ralph-DR-1.md](../research/ralph-loops/deep-research/ChatGPT-Ralph-DR-1.md)) revealed four gaps that the broader Ralph Loop ecosystem has converged on but the current plan doesn't address. These are operational resilience features critical for AFK/unattended operation:

1. **BLOCKED/DECIDE promise signals** — structured human-in-the-loop escalation
2. **Stuck detection / circuit breakers** — detect and halt non-productive iterations
3. **Per-iteration timing and cost summary** — operational telemetry
4. **Per-iteration output logging** — post-mortem debugging capability

None of these change the review cycle, stop hook, or transition validation — they extend ralph.sh and the prompt template with operational safeguards that run alongside the existing architecture.

---

## 1. BLOCKED/DECIDE Promise Signals

### Problem

The loop currently supports only `<promise>COMPLETE</promise>`. When the agent genuinely cannot proceed — ambiguous requirements, missing credentials, external dependency down, or a design decision that needs human input — it has no structured way to signal this. It either spins uselessly consuming iterations, documents the blocker in progress.txt (which the user won't see until the loop finishes or they manually check), or stops with the blocker unresolved.

The PageAI implementation addresses this with `BLOCKED` and `DECIDE` promise tags. The fredflint gist and Goose recipes have similar patterns.

### Design

Two new promise signals alongside the existing COMPLETE:

| Signal | Format | Meaning | ralph.sh behavior |
|---|---|---|---|
| BLOCKED | `<promise>BLOCKED:reason</promise>` | Agent genuinely cannot proceed. Requires human resolution before the loop can continue. | Stop loop. Write reason to `ralph/blocked.txt`. Exit code 2. |
| DECIDE | `<promise>DECIDE:question</promise>` | Agent needs a human decision between alternatives before proceeding. | Stop loop. Write question to `ralph/decide.txt`. Exit code 3. |

**ralph.sh signal handling:**

```
# After capturing AGENT_OUTPUT each iteration:
1. Check for <promise>COMPLETE</promise> → verify tasks.json, exit 0 if valid
2. Check for <promise>BLOCKED:...</promise> → extract reason, write to ralph/blocked.txt, exit 2
3. Check for <promise>DECIDE:...</promise> → extract question, write to ralph/decide.txt, exit 3
4. Otherwise → continue to next iteration
```

- ralph.sh validates that the reason/question is non-empty — rejects empty `<promise>BLOCKED:</promise>` tags (treats as no signal, continues iteration).
- The stop hook does NOT need changes — BLOCKED/DECIDE are output signals parsed by ralph.sh after the agent has already stopped. The agent stops normally after outputting them.

**Resume workflow:**

- **BLOCKED**: User resolves the blocker externally (e.g., sets up credentials, clarifies requirements in prd.md). Deletes `ralph/blocked.txt`. Re-runs `ralph.sh` — it resumes from the current tasks.json state (no iteration counter reset needed since each run starts fresh from `1` but tasks.json tracks actual progress).
- **DECIDE**: User opens `ralph/decide.txt`, reads the question, writes their answer below a `---` separator in the same file. Re-runs `ralph.sh`. The prompt template reads `decide.txt` at Step 1 (Orient) and uses the answer. The agent deletes the file after acting on it.

**decide.txt format:**

```markdown
## Question (from iteration 7, 2025-06-15T14:30:00Z)
Should the notification system use WebSockets for real-time updates or polling with a 5-second interval? WebSockets would be more responsive but adds infrastructure complexity. Polling is simpler but adds latency.

---
## Answer
Use polling for now. We can upgrade to WebSockets in a future PRD if latency becomes an issue.
```

### Sections to update in ralph-loop-plan.md

- **§3 ralph.sh core behavior**: Add BLOCKED/DECIDE detection after the existing COMPLETE detection bullet points
- **§3 ralph.sh arguments**: No new flags (signal handling is always-on)
- **§3 ralph.sh exit codes**: Document exit codes 0/1/2/3/4 in a table
- **§6 Prompt template, Step 1 (Orient)**: Read `ralph/decide.txt` if it exists
- **§6 Prompt template, Step 6 (Commit & Signal)**: Add BLOCKED/DECIDE signal instructions
- **§6 Hard rules**: Add "Do not use BLOCKED/DECIDE to avoid difficult tasks — these are for genuine blockers only. Exhaust all alternatives first."
- **§10 ralph-init.sh**: Add `ralph/blocked.txt` and `ralph/decide.txt` to `.gitignore`
- **Design Decisions table**: Add entry
- **Verification Plan**: Add test cases

### Exit code table (new, for §3)

| Exit code | Meaning |
|---|---|
| 0 | All stories complete (COMPLETE signal verified) |
| 1 | Max iterations reached without completion |
| 2 | BLOCKED — human resolution required. See `ralph/blocked.txt` |
| 3 | DECIDE — human decision required. See `ralph/decide.txt` |
| 4 | Stuck — no progress for N consecutive iterations (see §2 below) |

---

## 2. Stuck Detection / Circuit Breakers

### Problem

`--max-iterations` caps total iterations but can't distinguish productive iterations from wasted ones. If the agent fails to produce a commit for 3 iterations in a row — spinning on a broken test, fighting a misconfigured environment, or looping on a task it can't complete — the loop burns iterations (and API cost) with no progress.

The Cursor CLI ecosystem detects "gutter" states (repeated failing commands, file thrashing). frankbria's implementation has explicit stuck detection. The ChatGPT research doc recommends circuit breakers as a standard upgrade.

### Design

**Commit-based progress detection** — simple, reliable, no output parsing:

- After each iteration, ralph.sh runs `git rev-parse HEAD` and compares to the previous iteration's HEAD.
- If HEAD hasn't changed (no new commit), increment `STUCK_COUNT`.
- If HEAD changed, reset `STUCK_COUNT` to 0.
- If `STUCK_COUNT` reaches `--max-stuck` (default: 3), stop the loop with exit code 4.

**Why commit-based, not output-based:**
- The stop hook already enforces that the agent commits before stopping (Check 3: uncommitted changes). So a "successful" iteration always produces a commit.
- An iteration that fails to commit means the agent couldn't complete any meaningful unit of work — it either failed verification, got stuck, or produced nothing.
- No output parsing complexity. `git rev-parse HEAD` is deterministic and instant.

**What it catches:**
- Empty iterations (agent produces no output or no meaningful changes)
- Agent spinning without producing commits (broken tests, environment issues)
- Review cycles where the agent can't resolve feedback (keeps failing the same way)
- Transient failures that persist beyond the retry mechanism

**What it doesn't catch:**
- Intra-iteration stuck loops (agent retrying the same failing command within a single iteration) — bounded by context window limits and the context monitor's 90% CRITICAL alert
- Agent making commits but not making progress (e.g., committing reverts). This would require semantic analysis of commits, which is over-engineering for this stage.

**Interaction with review cycle:**
- Review iterations that approve produce a commit (tasks.json update). `STUCK_COUNT` resets.
- Review iterations that request changes produce a commit (tasks.json + reviewFeedback update). `STUCK_COUNT` resets.
- Review-fix iterations that successfully address feedback produce a commit. `STUCK_COUNT` resets.
- Only truly failed iterations (agent stops without committing, or the stop hook blocks the stop due to validation failure and the agent can't recover) increment `STUCK_COUNT`.

### Sections to update in ralph-loop-plan.md

- **§3 ralph.sh core behavior**: Add stuck detection logic, `STUCK_COUNT` tracking, `--max-stuck` flag
- **§3 ralph.sh arguments**: Add `--max-stuck N` with default 3
- **§3 .ralph-active payload**: Add `stuckCount` field
- **Design Decisions table**: Add entry
- **Verification Plan**: Add test cases

---

## 3. Per-Iteration Timing and Cost Summary

### Problem

After a 15-iteration loop, there's no way to answer: how long did it take? How long was each iteration? How many stories were completed vs attempted? This data is essential for tuning `--max-iterations`, evaluating whether the review cycle is worth the overhead, and estimating costs for future PRDs.

The research notes that AnandChowdhary/continuous-claude adds duration limits and budget tracking. Multiple implementations log per-iteration timing.

### Design

**Always-on timing + summary CSV:**

- ralph.sh records `$SECONDS` (bash built-in, auto-incrementing) at the start and end of each iteration. Computes per-iteration elapsed time.
- After each iteration, appends a one-line entry to `ralph/logs/summary.csv`:

```csv
iteration,mode,duration_seconds,commit_hash,stories_complete,stories_total,stuck_count,timestamp
1,implement,127,abc1234,0,5,0,2025-06-15T10:30:00Z
2,review,84,def5678,1,5,0,2025-06-15T10:32:07Z
3,implement,156,,0,5,1,2025-06-15T10:34:43Z
```

- `commit_hash` is empty if no commit was produced (stuck iteration).
- `stories_complete` / `stories_total` counted via `jq` on tasks.json (stories with `passes: true` vs total).
- At loop completion (any exit code), prints a summary to stdout:

```
Ralph Loop Summary
──────────────────
Exit:        COMPLETE (code 0)
Iterations:  12 / 15
Duration:    47m 23s
Stories:     5/5 complete
Avg/iter:    3m 57s
Stuck iters: 1
Log:         ralph/logs/summary.csv
```

**File layout:**

```
ralph/logs/
├── summary.csv          # One-line-per-iteration telemetry
├── iteration-001.log    # Full output (see §4)
├── iteration-002.log
└── ...
```

- `ralph/logs/` is `.gitignore`d — operational telemetry, not source.
- ralph-archive.sh moves `ralph/logs/` into the archive with an `--include-logs` flag (default: exclude to keep archives lean).

### Sections to update in ralph-loop-plan.md

- **File Layout** (top of plan): Add `ralph/logs/` to the target-project layout
- **§3 ralph.sh core behavior**: Add timing, CSV writing, summary output
- **§10 ralph-init.sh**: Create `ralph/logs/` directory, add to `.gitignore`
- **§11 ralph-archive.sh**: Add `--include-logs` flag
- **Design Decisions table**: Add entry
- **Verification Plan**: Add test cases

---

## 4. Per-Iteration Output Logging

### Problem

ralph.sh streams output to the terminal via `tee /dev/stderr` but doesn't persist it. After a 15-iteration loop, you can't go back and see what happened in iteration 4. If the agent did something unexpected — approved a story questionably, produced an odd commit, or got stuck — the full output is gone.

### Design

**Per-iteration log files alongside the summary CSV:**

- Each iteration's full Claude output is written to `ralph/logs/iteration-{NNN}.log` (zero-padded to 3 digits).
- The existing terminal streaming is preserved — output goes to both terminal AND log file via `tee`.
- Implementation in ralph.sh:

```bash
# Before each iteration
LOG_FILE="$RALPH_DIR/logs/iteration-$(printf '%03d' $i).log"

# During iteration (sandbox mode)
docker sandbox run "$SANDBOX_NAME" -- -p "$PROMPT" 2>&1 | tee "$LOG_FILE" | tee /dev/stderr

# During iteration (direct mode)
claude -p "$PROMPT" --dangerously-skip-permissions 2>&1 | tee "$LOG_FILE" | tee /dev/stderr
```

- Log files are `.gitignore`d (same as summary.csv — operational telemetry).
- ralph-archive.sh includes logs when `--include-logs` is passed.

**Size considerations:**
- A typical iteration produces 5-50KB of output. A 15-iteration loop produces 75-750KB total. This is negligible on disk.
- For very long loops (50+ iterations), logs may accumulate 2-5MB. Still negligible. No rotation needed.

### Sections to update in ralph-loop-plan.md

- **§3 ralph.sh core behavior**: Change output handling to include per-iteration log file
- **Design Decisions table**: Add entry
- **Verification Plan**: Add test cases

---

## Design Decisions to Add

| Decision | Choice | Rationale |
|---|---|---|
| BLOCKED/DECIDE signals | Promise tags parsed by ralph.sh, not stop hook | Agent signals escalation via output; ralph.sh writes state files and exits with specific codes. Stop hook stays focused on validation. Resume workflow is file-based (delete/edit the state file, re-run). Matches PageAI's promise tag pattern. |
| Stuck detection method | Commit-based (git rev-parse HEAD comparison) | Simple, reliable, no output parsing. A "successful" iteration always commits (stop hook enforces this). No-commit = no progress. Avoids complexity of parsing agent output for failure patterns. |
| Stuck threshold default | 3 consecutive no-commit iterations | Tolerant enough for transient failures (1-2 bad iterations are normal). Strict enough to catch genuine stuck loops before burning too many iterations. Configurable via `--max-stuck`. |
| Per-iteration telemetry | summary.csv + per-iteration .log files | CSV is machine-readable for post-completion analysis and tooling. Log files enable post-mortem debugging. Both are .gitignored (operational, not source). |
| Telemetry default | Always-on, no opt-out flag | Overhead is negligible (one jq call + one file write per iteration). The data is always useful. No reason to make it optional. |
| Archive log inclusion | Opt-in via `--include-logs` on ralph-archive.sh | Default excludes logs to keep archives lean. Logs are useful for debugging recent runs but rarely needed in historical archives. |

---

## Verification Additions

### BLOCKED/DECIDE signal tests
- Run 1-iteration loop where the prompt forces a `<promise>BLOCKED:missing API key</promise>` output. Verify:
  - ralph.sh exits with code 2
  - `ralph/blocked.txt` exists and contains "missing API key"
  - Re-running after deleting `blocked.txt` resumes normally
- Run loop that forces `<promise>DECIDE:WebSockets or polling?</promise>`. Verify:
  - ralph.sh exits with code 3
  - `ralph/decide.txt` exists with question
  - Write answer below `---`, re-run, verify agent reads the answer and deletes the file
- Empty signal test: `<promise>BLOCKED:</promise>` (empty reason) → should be ignored (treated as no signal, iteration continues)
- BLOCKED during review mode: verify the blocked story retains its current `reviewStatus` and `reviewCount` (no corruption)

### Stuck detection tests
- Run loop with a prompt that produces no commits for 3 iterations. Verify:
  - ralph.sh exits with code 4 after 3 iterations (default `--max-stuck`)
  - Summary output mentions stuck iterations
- Run with `--max-stuck 1`. Verify exit after first no-commit iteration.
- Verify that a stuck iteration followed by a successful commit resets the counter (run 2 stuck + 1 success + 2 stuck → should NOT exit at the 4th iteration because counter was reset)
- Verify stuck detection works correctly with the review cycle (a review iteration that commits a tasks.json update should reset the counter)

### Per-iteration logging and timing tests
- Run 3-iteration loop. Verify:
  - `ralph/logs/iteration-001.log`, `iteration-002.log`, `iteration-003.log` exist
  - Each log file is non-empty and contains Claude output
  - `ralph/logs/summary.csv` has 3 data rows (plus optional header)
  - Each CSV row has all fields populated (iteration, mode, duration_seconds, etc.)
- Verify summary table is printed to stdout at loop completion
- Verify `ralph/logs/` is in `.gitignore`
- **ralph-archive.sh**: Run without `--include-logs` → verify logs are NOT in archive. Run with `--include-logs` → verify logs ARE in archive.

---

## Interaction with Existing Features

These four additions are additive — they don't modify any existing enforcement mechanisms:

| Existing feature | Interaction |
|---|---|
| Stop hook (Checks 1, 2, 2.5, 3) | No changes. BLOCKED/DECIDE are output signals, not stop hook concerns. The agent stops normally before ralph.sh parses the output. |
| Transition validation (snapshot) | No changes. Stuck iterations that don't commit don't modify tasks.json, so the snapshot comparison is moot. BLOCKED/DECIDE iterations may or may not commit depending on when the signal fires. |
| Review cycle | Stuck detection respects the review cycle — review/review-fix iterations that commit tasks.json updates reset the stuck counter. Only truly failed iterations (no commit at all) count as stuck. |
| Context monitor | No changes. Per-iteration logs capture the full output including any context monitor alerts, which is useful for post-mortem analysis. |
| Skip-review mode | Fully compatible. All four features work identically in skip-review mode. |
| .ralph-active | `stuckCount` added to the payload. No other fields change. |
