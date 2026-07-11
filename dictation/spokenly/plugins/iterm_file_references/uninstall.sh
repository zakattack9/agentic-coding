#!/usr/bin/env bash
set -euo pipefail

target="$HOME/Library/ApplicationSupport/iTerm2/Scripts/AutoLaunch/spokenly_iterm_context.py"

if [[ -L "$target" ]]; then
  rm "$target"
  printf 'Removed %s\n' "$target"
elif [[ -e "$target" ]]; then
  echo "Refusing to remove a non-symlink at $target" >&2
  exit 1
else
  printf 'The Spokenly iTerm context daemon is not installed.\n'
fi
