#!/usr/bin/env bash
# ralph.sh — Main Ralph Loop runner
#
# Iterates Claude Code CLI against file-based specifications. Each iteration
# gets a fresh context window. State persists on disk between iterations.
#
# Dependencies: jq, claude CLI. Docker Desktop 4.58+ recommended for sandbox mode.
#
# Usage: ralph.sh [OPTIONS]

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────
MAX_ITERATIONS=15
RALPH_DIR="./.ralph"
PROJECT_DIR="$(pwd)"
MODEL=""
FORCE_SANDBOX=""
SKIP_REVIEW=false
REVIEW_CAP=5
EMPTY_RETRY_CAP=3

# ──────────────────────────────────────────────────────────────────────────────
# Usage
# ──────────────────────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
ralph.sh — Ralph Loop runner

Usage: ralph.sh [OPTIONS]

Options:
  -n, --max-iterations N    Max loop iterations (default: 15)
  --ralph-dir PATH          Path to .ralph/ directory (default: ./.ralph)
  -d, --project-dir PATH    Project root (default: cwd)
  -m, --model MODEL         Claude model to use (e.g., opus, sonnet)
  --sandbox                 Force Docker Sandbox mode (error if unavailable)
  --no-sandbox              Force direct mode with --dangerously-skip-permissions
  --skip-review             Disable the fresh-context review cycle
  --review-cap N            Max fresh-context reviews per story (default: 5)
  -h, --help                Show this help

Dependencies:
  - jq (for tasks.json verification)
  - claude CLI
  - Docker Desktop 4.58+ (recommended, for sandbox mode)
EOF
  exit 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--max-iterations) MAX_ITERATIONS="$2"; shift 2 ;;
    --ralph-dir)         RALPH_DIR="$2"; shift 2 ;;
    -d|--project-dir)    PROJECT_DIR="$2"; shift 2 ;;
    -m|--model)          MODEL="$2"; shift 2 ;;
    --sandbox)           FORCE_SANDBOX="yes"; shift ;;
    --no-sandbox)        FORCE_SANDBOX="no"; shift ;;
    --skip-review)       SKIP_REVIEW=true; shift ;;
    --review-cap)        REVIEW_CAP="$2"; shift 2 ;;
    -h|--help)           usage ;;
    *)                   echo "Unknown option: $1"; usage ;;
  esac
done

# ──────────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────────
if ! command -v jq &>/dev/null; then
  echo "Error: jq is required but not found. Install with: brew install jq" >&2
  exit 1
fi

if ! command -v claude &>/dev/null; then
  echo "Error: claude CLI is required but not found." >&2
  exit 1
fi

cd "$PROJECT_DIR"

if [[ ! -d "$RALPH_DIR" ]]; then
  echo "Error: .ralph directory not found at $RALPH_DIR" >&2
  echo "Run /ralph-install first, then ralph-init.sh to set up the project." >&2
  exit 1
fi

for required_file in tasks.json prompt.md prd.md; do
  if [[ ! -f "$RALPH_DIR/$required_file" ]]; then
    echo "Error: $RALPH_DIR/$required_file not found" >&2
    exit 1
  fi
done

# Validate tasks.json is parseable
if ! jq empty "$RALPH_DIR/tasks.json" 2>/dev/null; then
  echo "Error: $RALPH_DIR/tasks.json is not valid JSON" >&2
  exit 1
fi

# ──────────────────────────────────────────────────────────────────────────────
# Sandbox detection
# ──────────────────────────────────────────────────────────────────────────────
SANDBOX_MODE=false
SANDBOX_NAME=""

detect_sandbox() {
  if docker sandbox ls &>/dev/null 2>&1; then
    return 0
  fi
  return 1
}

if [[ "$FORCE_SANDBOX" == "yes" ]]; then
  if ! detect_sandbox; then
    echo "Error: --sandbox specified but Docker Sandbox is not available." >&2
    echo "Ensure Docker Desktop 4.58+ is installed with Sandboxes enabled." >&2
    exit 1
  fi
  SANDBOX_MODE=true
elif [[ "$FORCE_SANDBOX" == "no" ]]; then
  SANDBOX_MODE=false
else
  # Auto-detect
  if detect_sandbox; then
    SANDBOX_MODE=true
    echo "[ralph] Docker Sandbox detected — using sandbox mode"
  else
    echo "[ralph] Docker Sandbox not available — using direct mode"
    echo "[ralph] WARNING: Running with --dangerously-skip-permissions without sandbox isolation"
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
# Sandbox setup (one-time)
# ──────────────────────────────────────────────────────────────────────────────
if $SANDBOX_MODE; then
  SANDBOX_NAME="ralph-$(echo "$PROJECT_DIR" | sed 's#[^A-Za-z0-9._-]#_#g')"
  DCLAUDE_STATE="$HOME/.dclaude_state"

  # Ensure auth state directory and valid JSON exist
  mkdir -p "$DCLAUDE_STATE"
  if [[ ! -f "$DCLAUDE_STATE/.claude.json" ]] || [[ ! -s "$DCLAUDE_STATE/.claude.json" ]]; then
    echo '{}' > "$DCLAUDE_STATE/.claude.json"
  fi
  mkdir -p "$DCLAUDE_STATE/.claude" 2>/dev/null || true

  # Create sandbox if it doesn't exist
  if ! docker sandbox ls 2>/dev/null | grep -q "$SANDBOX_NAME"; then
    echo "[ralph] Creating sandbox: $SANDBOX_NAME"
    docker sandbox create --name "$SANDBOX_NAME" claude "$PROJECT_DIR" "$DCLAUDE_STATE"

    # Set up auth symlinks inside the sandbox
    echo "[ralph] Setting up auth in sandbox..."
    docker sandbox exec -u root "$SANDBOX_NAME" bash -c '
      HOST_USER="'"$USER"'"
      STATE_DIR="/Users/${HOST_USER}/.dclaude_state"
      rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
      ln -s "${STATE_DIR}/.claude" /home/agent/.claude
      ln -s "${STATE_DIR}/.claude.json" /home/agent/.claude.json
      chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true
    '

    # Configure git inside sandbox
    docker sandbox exec "$SANDBOX_NAME" bash -c '
      git config --global user.email "ralph@localhost"
      git config --global user.name "Ralph Loop"
    '
    echo "[ralph] Sandbox ready"
  else
    echo "[ralph] Reusing existing sandbox: $SANDBOX_NAME"
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
# .ralph-active marker + cleanup trap
# ──────────────────────────────────────────────────────────────────────────────
RALPH_ACTIVE=".ralph/.ralph-active"
MY_PID=$$

write_ralph_active() {
  local iteration_mode="$1"
  local snapshot="$2"

  cat > "$RALPH_ACTIVE" <<EOJSON
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pid": $MY_PID,
  "max_iterations": $MAX_ITERATIONS,
  "mode": "$( $SANDBOX_MODE && echo "sandbox" || echo "direct" )",
  "skipReview": $SKIP_REVIEW,
  "reviewCap": $REVIEW_CAP,
  "iterationMode": "$iteration_mode",
  "preIterationSnapshot": $snapshot
}
EOJSON
}

cleanup() {
  # Only remove if we own it
  if [[ -f "$RALPH_ACTIVE" ]]; then
    local stored_pid
    stored_pid=$(jq -r '.pid // 0' "$RALPH_ACTIVE" 2>/dev/null || echo 0)
    if [[ "$stored_pid" == "$MY_PID" ]]; then
      rm -f "$RALPH_ACTIVE"
    fi
  fi
}
trap cleanup EXIT INT TERM

# ──────────────────────────────────────────────────────────────────────────────
# Helper: determine iteration mode from tasks.json
# ──────────────────────────────────────────────────────────────────────────────
determine_mode() {
  local tasks_file="$1"
  # Priority: review-fix > review > implement
  if jq -e '.userStories[] | select(.reviewStatus == "changes_requested")' "$tasks_file" &>/dev/null; then
    echo "review-fix"
  elif jq -e '.userStories[] | select(.reviewStatus == "needs_review")' "$tasks_file" &>/dev/null; then
    echo "review"
  else
    echo "implement"
  fi
}

# ──────────────────────────────────────────────────────────────────────────────
# Helper: build pre-iteration snapshot from tasks.json
# ──────────────────────────────────────────────────────────────────────────────
build_snapshot() {
  local tasks_file="$1"
  jq '[.userStories[] | {key: .id, value: {passes: .passes, reviewStatus: .reviewStatus, reviewCount: .reviewCount}}] | from_entries' "$tasks_file"
}

# ──────────────────────────────────────────────────────────────────────────────
# Helper: check if all stories are complete
# ──────────────────────────────────────────────────────────────────────────────
all_stories_complete() {
  local tasks_file="$1"
  if $SKIP_REVIEW; then
    # Skip-review mode: only check passes
    local incomplete
    incomplete=$(jq '[.userStories[] | select(.passes != true)] | length' "$tasks_file")
    [[ "$incomplete" -eq 0 ]]
  else
    # Normal mode: check both passes and reviewStatus
    local incomplete
    incomplete=$(jq '[.userStories[] | select(.passes != true or .reviewStatus != "approved")] | length' "$tasks_file")
    [[ "$incomplete" -eq 0 ]]
  fi
}

# ──────────────────────────────────────────────────────────────────────────────
# Helper: run one Claude invocation
# ──────────────────────────────────────────────────────────────────────────────
run_claude() {
  local prompt="$1"
  local model_args=""

  if [[ -n "$MODEL" ]]; then
    model_args="--model $MODEL"
  fi

  if $SANDBOX_MODE; then
    # shellcheck disable=SC2086
    docker sandbox run "$SANDBOX_NAME" -- -p "$prompt" $model_args 2>&1
  else
    # shellcheck disable=SC2086
    claude -p "$prompt" --dangerously-skip-permissions $model_args 2>&1
  fi
}

# ──────────────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                     Ralph Loop Starting                      ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Project:       $(printf '%-44s' "$PROJECT_DIR")║"
echo "║  Max iterations: $(printf '%-43s' "$MAX_ITERATIONS")║"
echo "║  Mode:          $(printf '%-44s' "$( $SANDBOX_MODE && echo "sandbox" || echo "direct" )")║"
echo "║  Skip review:   $(printf '%-44s' "$SKIP_REVIEW")║"
echo "║  Review cap:    $(printf '%-44s' "$REVIEW_CAP")║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

PROMPT_TEMPLATE=$(cat "$RALPH_DIR/prompt.md")
EMPTY_RETRIES=0

for (( i=1; i<=MAX_ITERATIONS; i++ )); do
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Iteration $i of $MAX_ITERATIONS"

  # Determine mode and build snapshot
  ITERATION_MODE=$(determine_mode "$RALPH_DIR/tasks.json")
  SNAPSHOT=$(build_snapshot "$RALPH_DIR/tasks.json")

  echo "  Mode: $ITERATION_MODE"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  # Write .ralph-active with pre-iteration snapshot
  write_ralph_active "$ITERATION_MODE" "$SNAPSHOT"

  # Inject iteration variables into prompt
  PROMPT="${PROMPT_TEMPLATE//\{\{RALPH_ITERATION\}\}/$i}"
  PROMPT="${PROMPT//\{\{RALPH_MAX_ITERATIONS\}\}/$MAX_ITERATIONS}"

  # Run Claude and capture output while streaming to terminal
  OUTPUT=$(run_claude "$PROMPT" | tee /dev/stderr)

  # Handle transient empty responses
  if [[ -z "${OUTPUT// /}" ]]; then
    EMPTY_RETRIES=$((EMPTY_RETRIES + 1))
    if [[ $EMPTY_RETRIES -ge $EMPTY_RETRY_CAP ]]; then
      echo "[ralph] ERROR: $EMPTY_RETRY_CAP consecutive empty responses. Aborting." >&2
      exit 1
    fi
    echo "[ralph] Empty response — retrying iteration $i (attempt $((EMPTY_RETRIES + 1)))"
    i=$((i - 1))  # Retry same iteration number
    continue
  fi
  EMPTY_RETRIES=0

  # In sandbox mode, wait for file sync before reading tasks.json
  if $SANDBOX_MODE; then
    sleep 3
  fi

  # Check for completion: promise tag
  if echo "$OUTPUT" | grep -q '<promise>COMPLETE</promise>'; then
    echo ""
    echo "[ralph] Completion signal detected. Verifying tasks.json..."
    if all_stories_complete "$RALPH_DIR/tasks.json"; then
      echo "[ralph] All stories complete and verified!"
      echo ""
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║                  Ralph Loop Complete!                        ║"
      echo "║  Iterations used: $(printf '%-41s' "$i of $MAX_ITERATIONS")║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      exit 0
    else
      echo "[ralph] WARNING: Promise tag found but tasks.json verification failed."
      echo "[ralph] Continuing to next iteration..."
    fi
  fi

  # Fallback: check tasks.json directly (agent completed but forgot the tag)
  if all_stories_complete "$RALPH_DIR/tasks.json"; then
    echo ""
    echo "[ralph] All stories verified complete via tasks.json (no promise tag)."
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                  Ralph Loop Complete!                        ║"
    echo "║  Iterations used: $(printf '%-41s' "$i of $MAX_ITERATIONS")║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    exit 0
  fi

done

echo ""
echo "[ralph] Max iterations ($MAX_ITERATIONS) reached without completion." >&2
echo "[ralph] Check .ralph/tasks.json for remaining work." >&2
exit 1
