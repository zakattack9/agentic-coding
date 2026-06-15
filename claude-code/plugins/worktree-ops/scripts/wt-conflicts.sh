#!/usr/bin/env bash
# Deterministic conflict report: list every unmerged file and print each one's
# conflict hunks, so resolution is driven from the complete, accurate set.
# Usage: wt-conflicts.sh
# Exit 0 = no conflicts; 1 = conflicts present (printed).
set -uo pipefail

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "error: not a git repo" >&2; exit 2; }

files=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
if [[ -z "$files" ]]; then
  echo "no unmerged files"
  exit 0
fi

count=$(printf '%s\n' "$files" | grep -c .)
echo "UNMERGED FILES ($count):"
printf '%s\n' "$files" | sed 's/^/  - /'
echo

printf '%s\n' "$files" | while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  echo "===== $f ====="
  # print the conflict hunks (markers + both sides), capped for safety
  awk '/^<<<<<<</{inc=1} inc{print} /^>>>>>>>/{inc=0; print "---"}' "$f" 2>/dev/null | head -160
  echo
done

exit 1
