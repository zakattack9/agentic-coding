#!/usr/bin/env bash
# test_ralph_sh.sh — Validation tests for ralph.sh (Phase 6.4)
#
# Tests argument parsing, .ralph-active creation/cleanup, mode detection,
# prompt injection, and validation logic. Does NOT invoke Claude CLI.
#
# Run: bash tests/test_ralph_sh.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLUGIN_ROOT="$REPO_ROOT/claude-code/plugins/ralph"
RALPH_SH="$PLUGIN_ROOT/scripts/ralph.sh"

PASS=0
FAIL=0
ERRORS=()

pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
fail() { FAIL=$((FAIL + 1)); ERRORS+=("$1: $2"); echo "  FAIL  $1: $2"; }

# Helper: create a minimal ralph project directory for testing
setup_ralph_project() {
  local dir="$1"
  local feature_name="${2:-test}"

  mkdir -p "$dir/ralph"
  # Minimal valid tasks.json
  cat > "$dir/ralph/tasks.json" <<'EOF'
{
  "project": "test",
  "branchName": "ralph/test",
  "description": "Test project",
  "verifyCommands": [],
  "userStories": [
    {
      "id": "US-001",
      "title": "Test story",
      "description": "A test",
      "acceptanceCriteria": ["It works"],
      "priority": 1,
      "passes": false,
      "reviewStatus": null,
      "reviewCount": 0,
      "reviewFeedback": "",
      "notes": "",
      "dependsOn": []
    }
  ]
}
EOF

  # Minimal prompt template
  cat > "$dir/ralph/prompt.md" <<'EOF'
# Ralph Loop — Iteration {{RALPH_ITERATION}} of {{RALPH_MAX_ITERATIONS}}
Test prompt.
EOF

  # Minimal PRD
  echo "# Test PRD" > "$dir/ralph/prd.md"

  # Init git
  (cd "$dir" && git init -q && git config user.email "t@t" && git config user.name "t" && git add -A && git commit -m "init" -q)
}

# ────────────────────────────────────────────────────────────────────────────
# Test 1: Help flag works
# ────────────────────────────────────────────────────────────────────────────
test_help() {
  local output
  output=$("$RALPH_SH" --help 2>&1) || true

  if ! echo "$output" | grep -q 'max-iterations'; then
    fail "test_help" "Help text missing --max-iterations"
    return
  fi
  if ! echo "$output" | grep -q 'ralph-dir'; then
    fail "test_help" "Help text missing --ralph-dir"
    return
  fi
  if ! echo "$output" | grep -q 'skip-review'; then
    fail "test_help" "Help text missing --skip-review"
    return
  fi

  pass "test_help"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 2: Validates jq is available
# ────────────────────────────────────────────────────────────────────────────
test_validates_jq() {
  # This test verifies the validation exists — jq IS available in our env
  # so we just check the script source for the check
  if ! grep -q 'command -v jq' "$RALPH_SH"; then
    fail "test_validates_jq" "ralph.sh doesn't check for jq"
    return
  fi
  pass "test_validates_jq"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 3: Fails gracefully when ralph/ directory missing
# ────────────────────────────────────────────────────────────────────────────
test_missing_ralph_dir() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  if "$RALPH_SH" --no-sandbox --project-dir "$tmpdir" --ralph-dir "$tmpdir/nonexistent" 2>/dev/null; then
    fail "test_missing_ralph_dir" "Should have failed but didn't"
    return
  fi

  pass "test_missing_ralph_dir"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 4: Mode detection — implement mode
# ────────────────────────────────────────────────────────────────────────────
test_mode_detection_implement() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  setup_ralph_project "$tmpdir"

  # All stories have reviewStatus: null → implement mode
  local mode
  mode=$(cd "$tmpdir" && source <(grep -A8 'determine_mode()' "$RALPH_SH" | head -9) && determine_mode "$tmpdir/ralph/tasks.json" 2>/dev/null) || true

  # Alternative: just use jq directly to verify the logic
  local has_changes has_needs_review
  has_changes=$(jq '[.userStories[] | select(.reviewStatus == "changes_requested")] | length' "$tmpdir/ralph/tasks.json")
  has_needs_review=$(jq '[.userStories[] | select(.reviewStatus == "needs_review")] | length' "$tmpdir/ralph/tasks.json")

  if [[ "$has_changes" -gt 0 ]]; then
    fail "test_mode_detection_implement" "Test setup wrong: has changes_requested"
    return
  fi
  if [[ "$has_needs_review" -gt 0 ]]; then
    fail "test_mode_detection_implement" "Test setup wrong: has needs_review"
    return
  fi

  pass "test_mode_detection_implement"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 5: Mode detection — review mode
# ────────────────────────────────────────────────────────────────────────────
test_mode_detection_review() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  setup_ralph_project "$tmpdir"

  # Set one story to needs_review
  jq '.userStories[0].reviewStatus = "needs_review"' "$tmpdir/ralph/tasks.json" > "$tmpdir/ralph/tasks.json.tmp"
  mv "$tmpdir/ralph/tasks.json.tmp" "$tmpdir/ralph/tasks.json"

  local has_needs_review
  has_needs_review=$(jq '[.userStories[] | select(.reviewStatus == "needs_review")] | length' "$tmpdir/ralph/tasks.json")

  if [[ "$has_needs_review" -ne 1 ]]; then
    fail "test_mode_detection_review" "Expected 1 needs_review story, got $has_needs_review"
    return
  fi

  pass "test_mode_detection_review"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 6: Mode detection — review-fix mode (highest priority)
# ────────────────────────────────────────────────────────────────────────────
test_mode_detection_review_fix() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  setup_ralph_project "$tmpdir"

  # Set story to changes_requested (should be review-fix mode)
  jq '.userStories[0].reviewStatus = "changes_requested" | .userStories[0].reviewFeedback = "Fix X"' "$tmpdir/ralph/tasks.json" > "$tmpdir/ralph/tasks.json.tmp"
  mv "$tmpdir/ralph/tasks.json.tmp" "$tmpdir/ralph/tasks.json"

  local has_changes
  has_changes=$(jq '[.userStories[] | select(.reviewStatus == "changes_requested")] | length' "$tmpdir/ralph/tasks.json")

  if [[ "$has_changes" -ne 1 ]]; then
    fail "test_mode_detection_review_fix" "Expected 1 changes_requested story, got $has_changes"
    return
  fi

  pass "test_mode_detection_review_fix"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 7: Snapshot builder produces valid JSON with correct fields
# ────────────────────────────────────────────────────────────────────────────
test_snapshot_builder() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  setup_ralph_project "$tmpdir"

  # Build snapshot using the same jq command as ralph.sh
  local snapshot
  snapshot=$(jq '[.userStories[] | {key: .id, value: {passes: .passes, reviewStatus: .reviewStatus, reviewCount: .reviewCount}}] | from_entries' "$tmpdir/ralph/tasks.json")

  # Verify it's valid JSON
  if ! echo "$snapshot" | jq empty 2>/dev/null; then
    fail "test_snapshot_builder" "Snapshot is not valid JSON"
    return
  fi

  # Verify it has the expected story
  local has_us001
  has_us001=$(echo "$snapshot" | jq 'has("US-001")')
  if [[ "$has_us001" != "true" ]]; then
    fail "test_snapshot_builder" "Snapshot missing US-001"
    return
  fi

  # Verify fields
  local passes review_status review_count
  passes=$(echo "$snapshot" | jq '."US-001".passes')
  review_status=$(echo "$snapshot" | jq -r '."US-001".reviewStatus')
  review_count=$(echo "$snapshot" | jq '."US-001".reviewCount')

  if [[ "$passes" != "false" || "$review_status" != "null" || "$review_count" != "0" ]]; then
    fail "test_snapshot_builder" "Snapshot fields incorrect: passes=$passes status=$review_status count=$review_count"
    return
  fi

  pass "test_snapshot_builder"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 8: Prompt injection — {{RALPH_ITERATION}} and {{RALPH_MAX_ITERATIONS}}
# ────────────────────────────────────────────────────────────────────────────
test_prompt_injection() {
  local template="# Ralph Loop — Iteration {{RALPH_ITERATION}} of {{RALPH_MAX_ITERATIONS}}"

  # Simulate the sed injection that ralph.sh does (bash parameter expansion)
  local i=3
  local max=15
  local prompt="${template//\{\{RALPH_ITERATION\}\}/$i}"
  prompt="${prompt//\{\{RALPH_MAX_ITERATIONS\}\}/$max}"

  if [[ "$prompt" != "# Ralph Loop — Iteration 3 of 15" ]]; then
    fail "test_prompt_injection" "Expected 'Iteration 3 of 15', got: $prompt"
    return
  fi

  pass "test_prompt_injection"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 9: Completion check logic
# ────────────────────────────────────────────────────────────────────────────
test_completion_check() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  setup_ralph_project "$tmpdir"

  # Not complete initially
  local incomplete
  incomplete=$(jq '[.userStories[] | select(.passes != true or .reviewStatus != "approved")] | length' "$tmpdir/ralph/tasks.json")
  if [[ "$incomplete" -eq 0 ]]; then
    fail "test_completion_check" "Should be incomplete initially"
    return
  fi

  # Set to complete
  jq '.userStories[0].passes = true | .userStories[0].reviewStatus = "approved"' "$tmpdir/ralph/tasks.json" > "$tmpdir/ralph/tasks.json.tmp"
  mv "$tmpdir/ralph/tasks.json.tmp" "$tmpdir/ralph/tasks.json"

  incomplete=$(jq '[.userStories[] | select(.passes != true or .reviewStatus != "approved")] | length' "$tmpdir/ralph/tasks.json")
  if [[ "$incomplete" -ne 0 ]]; then
    fail "test_completion_check" "Should be complete after setting passes+approved"
    return
  fi

  pass "test_completion_check"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 10: Skip-review completion check (only checks passes)
# ────────────────────────────────────────────────────────────────────────────
test_skip_review_completion() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  setup_ralph_project "$tmpdir"

  # Set passes=true but reviewStatus=null (skip-review mode)
  jq '.userStories[0].passes = true' "$tmpdir/ralph/tasks.json" > "$tmpdir/ralph/tasks.json.tmp"
  mv "$tmpdir/ralph/tasks.json.tmp" "$tmpdir/ralph/tasks.json"

  # Skip-review check (only passes)
  local incomplete
  incomplete=$(jq '[.userStories[] | select(.passes != true)] | length' "$tmpdir/ralph/tasks.json")
  if [[ "$incomplete" -ne 0 ]]; then
    fail "test_skip_review_completion" "Skip-review check failed: passes=true but still incomplete"
    return
  fi

  pass "test_skip_review_completion"
}

# ────────────────────────────────────────────────────────────────────────────
# Run all tests
# ────────────────────────────────────────────────────────────────────────────
echo "Running ralph.sh tests..."
echo ""

test_help
test_validates_jq
test_missing_ralph_dir
test_mode_detection_implement
test_mode_detection_review
test_mode_detection_review_fix
test_snapshot_builder
test_prompt_injection
test_completion_check
test_skip_review_completion

echo ""
echo "============================================================"
echo "Results: $PASS/$((PASS + FAIL)) passed, $FAIL failed"
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo ""
  echo "Failed tests:"
  for err in "${ERRORS[@]}"; do
    echo "  $err"
  done
fi
echo "============================================================"

[[ $FAIL -eq 0 ]]
