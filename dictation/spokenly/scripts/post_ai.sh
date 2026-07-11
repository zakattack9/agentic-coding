#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
exec python3 "$script_dir/post_ai.py" --snippets "$script_dir/../config/snippets.json"
