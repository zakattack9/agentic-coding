#!/usr/bin/env bash
# gh-projects engine entrypoint — the single seam the skills call.
#
# Collapsed from pm-ops's multi-engine engine-dispatch.sh to the ONE GitHub
# backend (lib/gh.py). It has NO logic of its own beyond enforcing the
# DRY-BY-DEFAULT / --force rail: nothing mutates GitHub unless --force is
# passed. Without --force it prints the intended command and exits without
# running it (dry preview). All Project writes downstream use the GitHub App
# installation token, never GITHUB_TOKEN (constraint #2).
#
# Usage:  engine.sh <gh.py-subcommand> [args...] [--force]
# Verbs:  resolve | capabilities | token | <future write verbs>
#
# Exit:   0 ok · 2 usage · 3 not found · 1 unexpected (mirrors gh.py).
set -euo pipefail

# Resolve the plugin lib dir from this script's location (never a hardcoded
# ~/.claude path): prefer ${CLAUDE_PLUGIN_ROOT}/lib, else this script's dir.
if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -f "${CLAUDE_PLUGIN_ROOT}/lib/gh.py" ]]; then
  lib_dir="${CLAUDE_PLUGIN_ROOT}/lib"
else
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
fi
gh_py="$lib_dir/gh.py"

if [[ $# -lt 1 ]]; then
  echo "error: usage: engine.sh <verb> [args...] [--force]" >&2
  exit 2
fi
if [[ ! -f "$gh_py" ]]; then
  echo "error: gh.py not found at $gh_py" >&2
  exit 3
fi

# Split --force out of the arg vector; everything else passes through verbatim.
force=0
args=()
for a in "$@"; do
  if [[ "$a" == "--force" ]]; then
    force=1
  else
    args+=("$a")
  fi
done

if [[ "$force" -ne 1 ]]; then
  # Dry-by-default: show the resolved command, mutate nothing.
  printf 'dry-run (no --force): would run: python3 %s' "$gh_py" >&2
  for a in "${args[@]}"; do printf ' %q' "$a" >&2; done
  printf '\n' >&2
  # Read-only verbs are safe to actually run even in dry mode; write verbs are
  # not. gh.py is itself dry/idempotent for the Phase-1 read verbs, so we run
  # them; anything else stays a preview until --force.
  case "${args[0]}" in
    resolve|capabilities|token)
      exec python3 "$gh_py" "${args[@]}"
      ;;
    *)
      echo "  (pass --force to execute this write verb)" >&2
      exit 0
      ;;
  esac
fi

exec python3 "$gh_py" "${args[@]}"
