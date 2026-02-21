#!/usr/bin/env bash
# ralph-archive.sh — Archive a completed ralph loop
#
# Moves .ralph/ artifacts to an archive directory and resets .ralph/ for the next loop.
#
# Usage: ralph-archive.sh [--project-dir PATH] [--label LABEL]

set -euo pipefail

# Templates are installed locally by ralph-install.sh
TEMPLATE_DIR=".ralph/templates"

# Defaults
PROJECT_DIR="$(pwd)"
LABEL=""

# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --label)       LABEL="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: ralph-archive.sh [--project-dir PATH] [--label LABEL]"
      echo ""
      echo "Options:"
      echo "  --project-dir PATH    Project root (default: cwd)"
      echo "  --label LABEL         Archive label (default: branch name from tasks.json)"
      echo "  -h, --help            Show this help"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

cd "$PROJECT_DIR"
RALPH_DIR=".ralph"

# ──────────────────────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────────────────────
if [[ ! -d "$RALPH_DIR" ]]; then
  echo "Error: $RALPH_DIR/ directory not found" >&2
  exit 1
fi

for required_file in tasks.json prd.md progress.txt; do
  if [[ ! -f "$RALPH_DIR/$required_file" ]]; then
    echo "Error: $RALPH_DIR/$required_file not found" >&2
    exit 1
  fi
done

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required but not found. Install with: brew install jq" >&2
  exit 1
fi

# ──────────────────────────────────────────────────────────────────────────────
# Determine archive name
# ──────────────────────────────────────────────────────────────────────────────
DATE=$(date +%Y-%m-%d)

if [[ -z "$LABEL" ]]; then
  # Try to get project name from tasks.json
  LABEL=$(jq -r '.project // empty' "$RALPH_DIR/tasks.json" 2>/dev/null || true)
  if [[ -z "$LABEL" ]]; then
    LABEL=$(git branch --show-current 2>/dev/null || echo "unnamed")
  fi
fi

# Sanitize label for use as directory name
SAFE_LABEL=$(echo "$LABEL" | sed 's#[^A-Za-z0-9._-]#-#g')
ARCHIVE_DIR=".ralph/archive/${DATE}-${SAFE_LABEL}"

# ──────────────────────────────────────────────────────────────────────────────
# Create archive
# ──────────────────────────────────────────────────────────────────────────────
mkdir -p "$ARCHIVE_DIR"

# Move artifacts
mv "$RALPH_DIR/prd.md"       "$ARCHIVE_DIR/prd.md"
mv "$RALPH_DIR/tasks.json"   "$ARCHIVE_DIR/tasks.json"
mv "$RALPH_DIR/progress.txt" "$ARCHIVE_DIR/progress.txt"

# Archive planning folder if it exists and has content
if [[ -d "$RALPH_DIR/planning" ]] && [ "$(ls -A "$RALPH_DIR/planning" 2>/dev/null)" ]; then
  mv "$RALPH_DIR/planning" "$ARCHIVE_DIR/planning"
fi

# ──────────────────────────────────────────────────────────────────────────────
# Generate summary
# ──────────────────────────────────────────────────────────────────────────────
TOTAL_STORIES=$(jq '.userStories | length' "$ARCHIVE_DIR/tasks.json")
COMPLETED_STORIES=$(jq '[.userStories[] | select(.passes == true)] | length' "$ARCHIVE_DIR/tasks.json")
PROJECT_NAME=$(jq -r '.project // "N/A"' "$ARCHIVE_DIR/tasks.json")

cat > "$ARCHIVE_DIR/summary.md" <<EOF
# Ralph Loop Archive — $SAFE_LABEL

- **Project:** $PROJECT_NAME
- **Archived:** $DATE
- **Stories:** $COMPLETED_STORIES / $TOTAL_STORIES completed

## Files
- \`prd.md\` — Requirements specification
- \`tasks.json\` — Final task state
- \`progress.txt\` — Iteration log
- \`planning/\` — Subagent research & planning output (if present)
EOF

echo "[ralph-archive] Archive created at $ARCHIVE_DIR/"

# ──────────────────────────────────────────────────────────────────────────────
# Reset .ralph/ with fresh templates (preserve prompt.md customizations)
# ──────────────────────────────────────────────────────────────────────────────
if [[ -d "$TEMPLATE_DIR" ]]; then
  cp "$TEMPLATE_DIR/prd-template.md"      "$RALPH_DIR/prd.md"
  cp "$TEMPLATE_DIR/tasks-template.json"  "$RALPH_DIR/tasks.json"
  cp "$TEMPLATE_DIR/progress-template.md" "$RALPH_DIR/progress.txt"
  mkdir -p "$RALPH_DIR/planning"
  echo "[ralph-archive] .ralph/ reset with fresh templates (prompt.md preserved)"
else
  echo "[ralph-archive] WARNING: Template directory not found — .ralph/ not reset" >&2
fi

# ──────────────────────────────────────────────────────────────────────────────
# Commit the archive
# ──────────────────────────────────────────────────────────────────────────────
if git rev-parse --is-inside-work-tree &>/dev/null; then
  git add "$ARCHIVE_DIR" "$RALPH_DIR"
  git commit -m "archive(ralph): $SAFE_LABEL — $COMPLETED_STORIES/$TOTAL_STORIES stories completed"
  echo "[ralph-archive] Archive committed"
else
  echo "[ralph-archive] Not in a git repo — skipping commit"
fi

echo ""
echo "Archive complete: $ARCHIVE_DIR/"
echo ".ralph/ has been reset for the next loop."
