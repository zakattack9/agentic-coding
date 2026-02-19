#!/usr/bin/env bash
# test_structural.sh — Structural validation (Phase 6.1) and archive test (Phase 6.7)
#
# Validates: plugin chain resolution, executable permissions, JSON validity,
# shebangs, and ralph-archive.sh behavior.
#
# Run: bash tests/test_structural.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLUGIN_ROOT="$REPO_ROOT/claude-code/plugins/ralph"

PASS=0
FAIL=0
ERRORS=()

pass() { PASS=$((PASS + 1)); echo "  PASS  $1"; }
fail() { FAIL=$((FAIL + 1)); ERRORS+=("$1: $2"); echo "  FAIL  $1: $2"; }

# ────────────────────────────────────────────────────────────────────────────
# 6.1: Structural Validation
# ────────────────────────────────────────────────────────────────────────────

test_marketplace_plugin_chain() {
  # marketplace.json → plugin source → plugin.json → hooks.json chain
  local plugin_source
  plugin_source=$(jq -r '.plugins[] | select(.name == "ralph") | .source' "$REPO_ROOT/.claude-plugin/marketplace.json")

  if [[ -z "$plugin_source" || "$plugin_source" == "null" ]]; then
    fail "marketplace_plugin_chain" "ralph not found in marketplace.json"
    return
  fi

  local plugin_dir="$REPO_ROOT/$plugin_source"
  if [[ ! -d "$plugin_dir" ]]; then
    fail "marketplace_plugin_chain" "Plugin source dir not found: $plugin_dir"
    return
  fi

  local plugin_json="$plugin_dir/.claude-plugin/plugin.json"
  if [[ ! -f "$plugin_json" ]]; then
    fail "marketplace_plugin_chain" "plugin.json not found at $plugin_json"
    return
  fi

  local hooks_ref
  hooks_ref=$(jq -r '.hooks' "$plugin_json")
  local hooks_path="$plugin_dir/$hooks_ref"
  if [[ ! -f "$hooks_path" ]]; then
    fail "marketplace_plugin_chain" "hooks.json not found at $hooks_path (ref: $hooks_ref)"
    return
  fi

  pass "marketplace_plugin_chain"
}

test_all_scripts_executable() {
  local scripts=(
    "$PLUGIN_ROOT/scripts/ralph.sh"
    "$PLUGIN_ROOT/scripts/ralph-init.sh"
    "$PLUGIN_ROOT/scripts/ralph-archive.sh"
    "$PLUGIN_ROOT/sandbox/setup.sh"
    "$PLUGIN_ROOT/hooks/scripts/context_monitor.py"
    "$PLUGIN_ROOT/hooks/scripts/stop_loop_reminder.py"
  )

  for script in "${scripts[@]}"; do
    if [[ ! -x "$script" ]]; then
      fail "all_scripts_executable" "Not executable: $script"
      return
    fi
  done

  pass "all_scripts_executable"
}

test_all_json_valid() {
  local json_files=(
    "$PLUGIN_ROOT/.claude-plugin/plugin.json"
    "$PLUGIN_ROOT/hooks/hooks.json"
    "$PLUGIN_ROOT/templates/tasks-template.json"
    "$REPO_ROOT/.claude-plugin/marketplace.json"
  )

  for jf in "${json_files[@]}"; do
    if ! jq empty "$jf" 2>/dev/null; then
      fail "all_json_valid" "Invalid JSON: $jf"
      return
    fi
  done

  pass "all_json_valid"
}

test_all_shebangs_correct() {
  local bash_scripts=(
    "$PLUGIN_ROOT/scripts/ralph.sh"
    "$PLUGIN_ROOT/scripts/ralph-init.sh"
    "$PLUGIN_ROOT/scripts/ralph-archive.sh"
    "$PLUGIN_ROOT/sandbox/setup.sh"
  )
  local python_scripts=(
    "$PLUGIN_ROOT/hooks/scripts/context_monitor.py"
    "$PLUGIN_ROOT/hooks/scripts/stop_loop_reminder.py"
  )

  for script in "${bash_scripts[@]}"; do
    local first_line
    first_line=$(head -1 "$script")
    if [[ "$first_line" != "#!/usr/bin/env bash" ]]; then
      fail "all_shebangs_correct" "$script has wrong shebang: $first_line"
      return
    fi
  done

  for script in "${python_scripts[@]}"; do
    local first_line
    first_line=$(head -1 "$script")
    if [[ "$first_line" != "#!/usr/bin/env python3" ]]; then
      fail "all_shebangs_correct" "$script has wrong shebang: $first_line"
      return
    fi
  done

  pass "all_shebangs_correct"
}

test_hooks_json_uses_plugin_root() {
  if ! grep -q 'CLAUDE_PLUGIN_ROOT' "$PLUGIN_ROOT/hooks/hooks.json"; then
    fail "hooks_json_uses_plugin_root" "hooks.json doesn't use \${CLAUDE_PLUGIN_ROOT}"
    return
  fi
  pass "hooks_json_uses_plugin_root"
}

# ────────────────────────────────────────────────────────────────────────────
# 6.7: ralph-archive.sh Validation
# ────────────────────────────────────────────────────────────────────────────

test_archive_basic() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap "rm -rf '$tmpdir'" RETURN

  cd "$tmpdir"
  git init -q && git config user.email "t@t" && git config user.name "t"

  # Initialize a ralph project
  "$PLUGIN_ROOT/scripts/ralph-init.sh" --project-dir "$tmpdir" --name "archive-test" >/dev/null

  # Simulate a completed loop — fill in tasks.json with a completed story
  cat > "$tmpdir/ralph/tasks.json" <<'EOF'
{
  "project": "test",
  "branchName": "ralph/archive-test",
  "description": "Test",
  "verifyCommands": [],
  "userStories": [
    {
      "id": "US-001",
      "title": "Test",
      "description": "Test",
      "acceptanceCriteria": ["works"],
      "priority": 1,
      "passes": true,
      "reviewStatus": "approved",
      "reviewCount": 1,
      "reviewFeedback": "",
      "notes": "Done",
      "dependsOn": []
    }
  ]
}
EOF

  # Add some progress
  echo "### Iteration 1 — implement — US-001 Test" >> "$tmpdir/ralph/progress.txt"

  # Commit everything first
  git add -A && git commit -m "complete loop" -q

  # Run archive
  "$PLUGIN_ROOT/scripts/ralph-archive.sh" --project-dir "$tmpdir" --label "v1-test" 2>/dev/null || true

  # Check archive directory was created
  if [[ ! -d "$tmpdir/ralph-archive" ]]; then
    fail "test_archive_basic" "ralph-archive/ directory not created"
    return
  fi

  # Check at least one archive subdirectory exists
  local archive_count
  archive_count=$(ls -d "$tmpdir/ralph-archive"/*/ 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$archive_count" -eq 0 ]]; then
    fail "test_archive_basic" "No archive subdirectory created"
    return
  fi

  # Check summary.md exists in archive
  local archive_dir
  archive_dir=$(ls -d "$tmpdir/ralph-archive"/*/ | head -1)
  if [[ ! -f "${archive_dir}summary.md" ]]; then
    fail "test_archive_basic" "summary.md not found in archive"
    return
  fi

  # Check ralph/ was reset (tasks.json should be template again)
  if [[ -f "$tmpdir/ralph/tasks.json" ]]; then
    local passes
    passes=$(jq -r '.userStories[0].passes' "$tmpdir/ralph/tasks.json" 2>/dev/null || echo "error")
    if [[ "$passes" == "true" ]]; then
      fail "test_archive_basic" "ralph/ not reset — tasks.json still has passes=true"
      return
    fi
  fi

  pass "test_archive_basic"
}

# ────────────────────────────────────────────────────────────────────────────
# Run all tests
# ────────────────────────────────────────────────────────────────────────────
echo "Running structural validation & archive tests..."
echo ""

echo "--- 6.1: Structural Validation ---"
test_marketplace_plugin_chain
test_all_scripts_executable
test_all_json_valid
test_all_shebangs_correct
test_hooks_json_uses_plugin_root

echo ""
echo "--- 6.7: ralph-archive.sh ---"
test_archive_basic

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
