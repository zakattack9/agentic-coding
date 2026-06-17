#!/usr/bin/env bash
# pm-ops board-engine dispatcher.
#
# Resolves the configured board engine from the current PM repo's
# .pm-ops/config.json and execs that engine's entrypoint, passing through all
# args and stdin. This is the ONLY coupling between the board-agnostic core and
# a concrete board — swap engines by changing `engine` in config.json.
#
# Usage:  engine-dispatch.sh <verb> [--apply] [engine-args...]   (normalized task JSON on stdin)
# Verbs:  capabilities | upsert | link | set-status | sync   (see engines/INTERFACE.md)
#
# Exit:   0 ok · 2 usage/config error · 3 engine not found · other = engine's own code.
set -euo pipefail

plugin_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)

# Find the PM repo root (walk up for .pm-ops/), honoring PM_OPS_REPO override.
find_repo_root() {
  local dir="${PM_OPS_REPO:-$PWD}"
  dir=$(cd "$dir" 2>/dev/null && pwd -P) || { echo "$PWD"; return; }
  while [[ "$dir" != "/" ]]; do
    [[ -d "$dir/.pm-ops" ]] && { echo "$dir"; return; }
    dir=$(dirname "$dir")
  done
  echo "${PM_OPS_REPO:-$PWD}"
}

if [[ $# -lt 1 ]]; then
  echo "error: usage: engine-dispatch.sh <verb> [--apply] [args...]" >&2
  exit 2
fi

repo_root=$(find_repo_root)
config="$repo_root/.pm-ops/config.json"
if [[ ! -f "$config" ]]; then
  echo "error: no .pm-ops/config.json found (looked up from ${PM_OPS_REPO:-$PWD}). Run consolidate-backlog or 'pm.py init' first." >&2
  exit 2
fi

engine=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("engine",""))' "$config" 2>/dev/null || true)
if [[ -z "$engine" ]]; then
  echo "error: no \"engine\" set in $config" >&2
  exit 2
fi
if [[ ! "$engine" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "error: invalid engine name '$engine' in $config" >&2
  exit 2
fi

entry="$plugin_root/engines/$engine/engine"
if [[ ! -f "$entry" ]]; then
  echo "error: board engine '$engine' is not installed (no $entry). Available: $(ls "$plugin_root/engines" 2>/dev/null | tr '\n' ' ')" >&2
  exit 3
fi

export PM_OPS_REPO="$repo_root"
exec "$entry" "$@"
