#!/usr/bin/env bash
set -euo pipefail

target="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/spokenly_iterm_context.py"
legacy_target="$HOME/Library/ApplicationSupport/iTerm2/Scripts/AutoLaunch/spokenly_iterm_context.py"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
expected="$script_dir/iterm_context_daemon.py"
marker="$(dirname "$target")/.spokenly_iterm_context.managed"
marker_value="spokenly-iterm-file-references-v1"
removed=0

if [[ -L "$target" ]]; then
  current_target="$(readlink "$target")"
  recorded_target="$(sed -n '2p' "$marker" 2>/dev/null || true)"
  managed=0
  if [[ -f "$marker" && "$(sed -n '1p' "$marker")" == "$marker_value" && "$current_target" == "$recorded_target" ]]; then
    managed=1
  fi
  if [[ "$current_target" != "$expected" && "$managed" -ne 1 ]]; then
    echo "Refusing to remove an unrelated symlink at $target" >&2
    exit 1
  fi
  rm "$target"
  printf 'Removed %s\n' "$target"
  removed=1
elif [[ -e "$target" ]]; then
  echo "Refusing to remove a non-symlink at $target" >&2
  exit 1
fi

if [[ -f "$marker" && "$(sed -n '1p' "$marker")" == "$marker_value" ]]; then
  rm "$marker"
fi

if [[ -L "$legacy_target" && "$(readlink "$legacy_target")" == "$expected" ]]; then
  rm "$legacy_target"
  printf 'Removed legacy symlink %s\n' "$legacy_target"
  removed=1
fi

if [[ "$removed" -eq 0 ]]; then
  printf 'The Spokenly iTerm context daemon is not installed.\n'
fi
