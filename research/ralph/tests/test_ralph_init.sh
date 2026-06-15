#!/usr/bin/env bash
# test_ralph_init.sh — Validation tests for ralph-init.sh (Phase 6.3)
#
# Tests: file creation, placeholder substitution, gitignore setup, idempotency
#
# Run: bash tests/test_ralph_init.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLUGIN_ROOT="$REPO_ROOT/claude-code/plugins/ralph"
INIT_SCRIPT="$PLUGIN_ROOT/scripts/ralph-init.sh"

PASS=0
FAIL=0
ERRORS=()

pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
fail() { FAIL=$((FAIL + 1)); ERRORS+=("$1: $2"); echo "  FAIL  $1: $2"; }

# ────────────────────────────────────────────────────────────────────────────
# Test 1: All files created with correct content
# ────────────────────────────────────────────────────────────────────────────
test_files_created() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  "$INIT_SCRIPT" --project-dir "$tmpdir" --name "test-feature" >/dev/null

  for f in ralph/prd.md ralph/tasks.json ralph/progress.txt ralph/prompt.md; do
    if [[ ! -f "$f" ]]; then
      fail "test_files_created" "Missing file: $f"
      return
    fi
  done

  # Verify tasks.json is valid JSON
  if ! jq empty ralph/tasks.json 2>/dev/null; then
    fail "test_files_created" "tasks.json is not valid JSON"
    return
  fi

  pass "test_files_created"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 2: {{DATE}} and {{PROJECT_NAME}} substituted in progress.txt
# ────────────────────────────────────────────────────────────────────────────
test_placeholder_substitution() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  "$INIT_SCRIPT" --project-dir "$tmpdir" --name "my-feature" >/dev/null

  # Check {{DATE}} was replaced with an actual date
  if grep -q '{{DATE}}' ralph/progress.txt; then
    fail "test_placeholder_substitution" "{{DATE}} not substituted"
    return
  fi

  # Check {{PROJECT_NAME}} was replaced
  if grep -q '{{PROJECT_NAME}}' ralph/progress.txt; then
    fail "test_placeholder_substitution" "{{PROJECT_NAME}} not substituted"
    return
  fi

  # Verify the actual date is there (YYYY-MM-DD format)
  if ! grep -qE '[0-9]{4}-[0-9]{2}-[0-9]{2}' ralph/progress.txt; then
    fail "test_placeholder_substitution" "No date found in progress.txt"
    return
  fi

  # Verify project name is there
  if ! grep -q 'my-feature' ralph/progress.txt; then
    fail "test_placeholder_substitution" "Project name 'my-feature' not in progress.txt"
    return
  fi

  pass "test_placeholder_substitution"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 3: .ralph-active added to .gitignore
# ────────────────────────────────────────────────────────────────────────────
test_gitignore_updated() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  "$INIT_SCRIPT" --project-dir "$tmpdir" >/dev/null

  if [[ ! -f .gitignore ]]; then
    fail "test_gitignore_updated" ".gitignore not created"
    return
  fi

  if ! grep -q '\.ralph-active' .gitignore; then
    fail "test_gitignore_updated" ".ralph-active not in .gitignore"
    return
  fi

  pass "test_gitignore_updated"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 4: Branch name set in tasks.json when --name provided
# ────────────────────────────────────────────────────────────────────────────
test_branch_name_set() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  "$INIT_SCRIPT" --project-dir "$tmpdir" --name "auth-flow" >/dev/null

  local branch
  branch=$(jq -r '.branchName' ralph/tasks.json)
  if [[ "$branch" != "ralph/auth-flow" ]]; then
    fail "test_branch_name_set" "Expected 'ralph/auth-flow', got '$branch'"
    return
  fi

  pass "test_branch_name_set"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 5: Re-running warns about existing ralph/ directory
# ────────────────────────────────────────────────────────────────────────────
test_idempotency_warning() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  "$INIT_SCRIPT" --project-dir "$tmpdir" >/dev/null

  # Run again — should fail with warning
  local output
  if output=$("$INIT_SCRIPT" --project-dir "$tmpdir" 2>&1); then
    fail "test_idempotency_warning" "Expected non-zero exit, but got success"
    return
  fi

  if ! echo "$output" | grep -qi 'already exists'; then
    fail "test_idempotency_warning" "Expected 'already exists' warning, got: $output"
    return
  fi

  pass "test_idempotency_warning"
}

# ────────────────────────────────────────────────────────────────────────────
# Test 6: --force overwrites existing
# ────────────────────────────────────────────────────────────────────────────
test_force_overwrite() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  "$INIT_SCRIPT" --project-dir "$tmpdir" --name "v1" >/dev/null

  # Modify a file
  echo "custom content" > ralph/prd.md

  # Force reinit
  "$INIT_SCRIPT" --project-dir "$tmpdir" --name "v2" --force >/dev/null

  # Verify it was overwritten (prd.md should be template, not custom)
  if grep -q 'custom content' ralph/prd.md; then
    fail "test_force_overwrite" "prd.md was not overwritten by --force"
    return
  fi

  # Verify new branch name
  local branch
  branch=$(jq -r '.branchName' ralph/tasks.json)
  if [[ "$branch" != "ralph/v2" ]]; then
    fail "test_force_overwrite" "Expected 'ralph/v2', got '$branch'"
    return
  fi

  pass "test_force_overwrite"
}

# ────────────────────────────────────────────────────────────────────────────
# Run all tests
# ────────────────────────────────────────────────────────────────────────────
echo "Running ralph-init.sh tests..."
echo ""

test_files_created
test_placeholder_substitution
test_gitignore_updated
test_branch_name_set
test_idempotency_warning
test_force_overwrite

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
