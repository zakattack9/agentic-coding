#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# verify-sync-latency.sh
#
# Reproduces the host→sandbox file overwrite sync issue
# found during Docker Sandbox feasibility testing.
#
# What it tests:
#   1. New file on host → visible in sandbox?
#   2. File overwritten on host → visible in sandbox?
#   3. Sandbox writes file → visible on host?
#
# Prerequisites:
#   - Docker Desktop with Sandboxes enabled
#   - No existing sandbox using /tmp/ralph-sync-verify
#
# Cleanup: script cleans up after itself on exit.
# ============================================================

WORKDIR="/tmp/ralph-sync-verify"
SANDBOX_NAME="sync-verify-test"
PASS=0
FAIL=0

cleanup() {
  echo ""
  echo "=== Cleanup ==="
  docker sandbox rm "$SANDBOX_NAME" 2>/dev/null && echo "Sandbox removed" || echo "No sandbox to remove"
  rm -rf "$WORKDIR" && echo "Workdir removed"
}
trap cleanup EXIT

echo "=== Setup ==="
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"

echo "Creating sandbox..."
docker sandbox create --name "$SANDBOX_NAME" claude "$WORKDIR" 2>&1 | head -5
echo ""

# Helper: read a file inside the sandbox
sandbox_cat() {
  docker sandbox exec "$SANDBOX_NAME" cat "$1" 2>/dev/null
}

# ──────────────────────────────────────────────────────────
# TEST 1: New file created on host → sandbox can see it?
# ──────────────────────────────────────────────────────────
echo "=== Test 1: New file (host → sandbox) ==="
echo '{"test": "new_file", "value": 1}' > "$WORKDIR/test1.json"
echo "  Host wrote: $(cat "$WORKDIR/test1.json")"

SEEN=false
for wait in 2 5 10 15; do
  echo "  Checking sandbox after ${wait}s..."
  sleep "$wait"
  CONTENT=$(sandbox_cat "$WORKDIR/test1.json" 2>&1 || echo "FILE_NOT_FOUND")
  if echo "$CONTENT" | grep -q '"value": 1'; then
    echo "  ✅ PASS — Sandbox sees new file after ${wait}s"
    echo "  Sandbox read: $CONTENT"
    SEEN=true
    ((PASS++))
    break
  else
    echo "  Not yet visible (got: $CONTENT)"
  fi
done
if [ "$SEEN" = false ]; then
  echo "  ❌ FAIL — Sandbox never saw the new file (waited 32s total)"
  ((FAIL++))
fi
echo ""

# ──────────────────────────────────────────────────────────
# TEST 2: Overwrite existing file on host → sandbox sees it?
# ──────────────────────────────────────────────────────────
echo "=== Test 2: Overwrite file (host → sandbox) ==="
echo "  First, confirm sandbox currently sees test1.json..."
BEFORE=$(sandbox_cat "$WORKDIR/test1.json")
echo "  Sandbox sees: $BEFORE"

echo '{"test": "overwritten", "value": 999}' > "$WORKDIR/test1.json"
echo "  Host overwrote to: $(cat "$WORKDIR/test1.json")"

SEEN=false
for wait in 2 5 10 15 30; do
  echo "  Checking sandbox after ${wait}s..."
  sleep "$wait"
  CONTENT=$(sandbox_cat "$WORKDIR/test1.json" 2>&1)
  if echo "$CONTENT" | grep -q '"value": 999'; then
    echo "  ✅ PASS — Sandbox sees overwritten file after ${wait}s"
    echo "  Sandbox read: $CONTENT"
    SEEN=true
    ((PASS++))
    break
  else
    echo "  Still stale (sandbox sees: $CONTENT)"
  fi
done
if [ "$SEEN" = false ]; then
  echo "  ❌ FAIL — Sandbox still sees stale data after 62s total"
  echo "  Host has:    $(cat "$WORKDIR/test1.json")"
  echo "  Sandbox has: $(sandbox_cat "$WORKDIR/test1.json")"
  ((FAIL++))
fi
echo ""

# ──────────────────────────────────────────────────────────
# TEST 3: Sandbox writes file → host can see it?
# ──────────────────────────────────────────────────────────
echo "=== Test 3: Sandbox writes → host reads ==="
docker sandbox exec "$SANDBOX_NAME" bash -c "echo '{\"test\": \"from_sandbox\", \"value\": 42}' > $WORKDIR/test3.json"
echo "  Sandbox wrote test3.json"

SEEN=false
for wait in 1 2 5 10; do
  echo "  Checking host after ${wait}s..."
  sleep "$wait"
  if [ -f "$WORKDIR/test3.json" ]; then
    CONTENT=$(cat "$WORKDIR/test3.json")
    if echo "$CONTENT" | grep -q '"value": 42'; then
      echo "  ✅ PASS — Host sees sandbox-written file after ${wait}s"
      echo "  Host read: $CONTENT"
      SEEN=true
      ((PASS++))
      break
    else
      echo "  File exists but wrong content: $CONTENT"
    fi
  else
    echo "  File not yet visible on host"
  fi
done
if [ "$SEEN" = false ]; then
  echo "  ❌ FAIL — Host never saw sandbox-written file (waited 18s total)"
  ((FAIL++))
fi
echo ""

# ──────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────
echo "========================================="
echo "Results: $PASS passed, $FAIL failed"
echo ""
echo "If Test 1 passes but Test 2 fails, this"
echo "confirms the host→sandbox overwrite sync"
echo "latency issue found in feasibility testing."
echo "========================================="
