#!/usr/bin/env bash
set -euo pipefail

target="$HOME/Library/ApplicationSupport/iTerm2/Scripts/AutoLaunch/spokenly_iterm_context.py"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
expected="$script_dir/iterm_context_daemon.py"

if [[ -L "$target" ]]; then
  if [[ "$(readlink "$target")" != "$expected" ]]; then
    echo "Refusing to remove an unrelated symlink at $target" >&2
    exit 1
  fi
  rm "$target"
  printf 'Removed %s\n' "$target"
elif [[ -e "$target" ]]; then
  echo "Refusing to remove a non-symlink at $target" >&2
  exit 1
else
  printf 'The Spokenly iTerm context daemon is not installed.\n'
fi
