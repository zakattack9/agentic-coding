#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
source_script="$script_dir/iterm_context_daemon.py"
target_dir="$HOME/Library/ApplicationSupport/iTerm2/Scripts/AutoLaunch"
target_script="$target_dir/spokenly_iterm_context.py"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The Spokenly iTerm file-reference plugin supports macOS only." >&2
  exit 1
fi

if [[ ! -d "/Applications/iTerm.app" && ! -d "$HOME/Applications/iTerm.app" ]]; then
  echo "iTerm2 was not found in /Applications or ~/Applications." >&2
  exit 1
fi

mkdir -p "$target_dir"
ln -sfn "$source_script" "$target_script"

printf '%s\n' \
  "Installed the Spokenly iTerm context daemon:" \
  "$target_script" \
  "Restart iTerm2, or run the script once from iTerm2's Scripts menu."
