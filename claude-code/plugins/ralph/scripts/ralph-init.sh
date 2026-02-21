#!/usr/bin/env bash
# ralph-init.sh — Initialize a ralph loop in a project
#
# Creates state files in .ralph/ from locally installed templates.
# Requires .ralph/templates/ to already exist (run /ralph-install first).
#
# Usage: ralph-init.sh [--project-dir PATH] [--name FEATURE_NAME] [--force]

set -euo pipefail

# Templates are installed locally by ralph-install.sh
TEMPLATE_DIR=".ralph/templates"

# Defaults
PROJECT_DIR="$(pwd)"
FEATURE_NAME=""
FORCE=false

# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --name)        FEATURE_NAME="$2"; shift 2 ;;
    --force)       FORCE=true; shift ;;
    -h|--help)
      echo "Usage: ralph-init.sh [--project-dir PATH] [--name FEATURE_NAME] [--force]"
      echo ""
      echo "Options:"
      echo "  --project-dir PATH    Project root (default: cwd)"
      echo "  --name FEATURE_NAME   Feature name (used for branch name and progress log)"
      echo "  --force               Overwrite existing state files"
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
if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "Error: Template directory not found at $TEMPLATE_DIR" >&2
  echo "Run /ralph-install first to set up the project." >&2
  exit 1
fi

if [[ -f "$RALPH_DIR/tasks.json" ]] && ! $FORCE; then
  echo "Warning: $RALPH_DIR/ already has state files (tasks.json exists)." >&2
  echo "Use --force to overwrite, or remove them manually." >&2
  exit 1
fi

# ──────────────────────────────────────────────────────────────────────────────
# Copy templates into .ralph/ as state files
# ──────────────────────────────────────────────────────────────────────────────

# Copy templates with renames
cp "$TEMPLATE_DIR/prompt.md"            "$RALPH_DIR/prompt.md"
cp "$TEMPLATE_DIR/prd-template.md"      "$RALPH_DIR/prd.md"
cp "$TEMPLATE_DIR/tasks-template.json"  "$RALPH_DIR/tasks.json"
cp "$TEMPLATE_DIR/progress-template.md" "$RALPH_DIR/progress.txt"

# Create planning directory for subagent research/planning output
mkdir -p "$RALPH_DIR/planning"

# ──────────────────────────────────────────────────────────────────────────────
# Substitute placeholders
# ──────────────────────────────────────────────────────────────────────────────
DATE=$(date +%Y-%m-%d)
PROJECT_NAME="${FEATURE_NAME:-$(basename "$PROJECT_DIR")}"

# progress.txt: substitute {{DATE}} and {{PROJECT_NAME}}
sed -i '' "s/{{DATE}}/$DATE/g" "$RALPH_DIR/progress.txt"
sed -i '' "s/{{PROJECT_NAME}}/$PROJECT_NAME/g" "$RALPH_DIR/progress.txt"

# tasks.json: set project name if --name provided
if [[ -n "$FEATURE_NAME" ]]; then
  if command -v jq &>/dev/null; then
    tmp=$(mktemp)
    jq --arg name "$FEATURE_NAME" '.project = $name' "$RALPH_DIR/tasks.json" > "$tmp"
    mv "$tmp" "$RALPH_DIR/tasks.json"
  fi
fi

# ──────────────────────────────────────────────────────────────────────────────
# Add .ralph/.ralph-active to .gitignore
# ──────────────────────────────────────────────────────────────────────────────
if [[ -f ".gitignore" ]]; then
  if ! grep -q '\.ralph/\.ralph-active' ".gitignore"; then
    echo "" >> ".gitignore"
    echo "# Ralph Loop runtime marker" >> ".gitignore"
    echo ".ralph/.ralph-active" >> ".gitignore"
  fi
else
  echo "# Ralph Loop runtime marker" > ".gitignore"
  echo ".ralph/.ralph-active" >> ".gitignore"
fi

# ──────────────────────────────────────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "Ralph loop initialized in $RALPH_DIR/"
echo ""
echo "Files created:"
echo "  $RALPH_DIR/prd.md        — Fill in your requirements"
echo "  $RALPH_DIR/tasks.json    — Define user stories (or use /ralph-plan)"
echo "  $RALPH_DIR/progress.txt  — Iteration log (auto-maintained)"
echo "  $RALPH_DIR/prompt.md     — Iteration prompt (customizable)"
echo "  $RALPH_DIR/planning/     — Subagent research & planning output"
echo ""
echo "Next steps:"
echo "  1. Edit $RALPH_DIR/prd.md with your requirements"
echo "  2. Run /ralph-plan to generate tasks, or fill $RALPH_DIR/tasks.json manually"
echo "  3. Run .ralph/scripts/ralph.sh to start the loop"
echo ""
