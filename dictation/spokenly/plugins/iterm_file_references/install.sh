#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
source_script="$script_dir/iterm_context_daemon.py"
target_dir="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"
target_script="$target_dir/spokenly_iterm_context.py"
marker="$target_dir/.spokenly_iterm_context.managed"
marker_value="spokenly-iterm-file-references-v1"
repair=0

if [[ "${1:-}" == "--repair" && "$#" -eq 1 ]]; then
  repair=1
elif [[ "$#" -ne 0 ]]; then
  echo "Usage: $0 [--repair]" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The Spokenly iTerm file-reference plugin supports macOS only." >&2
  exit 1
fi

if [[ ! -d "/Applications/iTerm.app" && ! -d "$HOME/Applications/iTerm.app" ]]; then
  echo "iTerm2 was not found in /Applications or ~/Applications." >&2
  exit 1
fi

mkdir -p "$target_dir"
if [[ -e "$target_script" || -L "$target_script" ]]; then
  if [[ ! -L "$target_script" || "$(readlink "$target_script")" != "$source_script" ]]; then
    current_target="$(readlink "$target_script" 2>/dev/null || true)"
    recorded_target="$(sed -n '2p' "$marker" 2>/dev/null || true)"
    managed=0
    if [[ -f "$marker" && "$(sed -n '1p' "$marker")" == "$marker_value" && "$current_target" == "$recorded_target" ]]; then
      managed=1
    elif [[ "$repair" -eq 1 && "$current_target" == */dictation/spokenly/plugins/iterm_file_references/iterm_context_daemon.py ]]; then
      managed=1
    fi
    if [[ ! -L "$target_script" || "$managed" -ne 1 ]]; then
      echo "Refusing to replace an unrelated entry at $target_script" >&2
      echo "Use --repair only for a stale Spokenly symlink after moving this repository." >&2
      exit 1
    fi
  fi
fi
ln -sfn "$source_script" "$target_script"
printf '%s\n%s\n' "$marker_value" "$source_script" >"$marker"
chmod 600 "$marker"

printf '%s\n' \
  "Installed the Spokenly iTerm context daemon:" \
  "$target_script" \
  "Restart iTerm2, or run the script once from iTerm2's Scripts menu."
