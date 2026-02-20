#!/usr/bin/env bash
# ralph-install.sh — Per-project install of Ralph Loop scripts and templates
#
# Creates .ralph/ directory structure and downloads scripts + templates
# from GitHub. Idempotent — safe to re-run.
#
# Usage: ralph-install.sh [--branch BRANCH]

set -euo pipefail

# Defaults
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/zakattack9/agentic-coding"
PLUGIN_PATH="claude-code/plugins/ralph"

# ──────────────────────────────────────────────────────────────────────────────
# Usage
# ──────────────────────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
ralph-install.sh — Per-project Ralph Loop installer

Usage: ralph-install.sh [OPTIONS]

Options:
  --branch BRANCH    GitHub branch to download from (default: main)
  -h, --help         Show this help

Creates .ralph/ directory with scripts and templates needed to run Ralph loops.
EOF
  exit 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

RAW_BASE="$BASE_URL/$BRANCH/$PLUGIN_PATH"

# ──────────────────────────────────────────────────────────────────────────────
# Create directory structure
# ──────────────────────────────────────────────────────────────────────────────
echo "[ralph-install] Setting up .ralph/ directory..."
mkdir -p .ralph/scripts
mkdir -p .ralph/templates
mkdir -p .ralph/sandbox

# ──────────────────────────────────────────────────────────────────────────────
# Download scripts
# ──────────────────────────────────────────────────────────────────────────────
echo "[ralph-install] Downloading scripts..."
curl -fsSL "$RAW_BASE/scripts/ralph.sh"         -o .ralph/scripts/ralph.sh
curl -fsSL "$RAW_BASE/scripts/ralph-init.sh"    -o .ralph/scripts/ralph-init.sh
curl -fsSL "$RAW_BASE/scripts/ralph-archive.sh" -o .ralph/scripts/ralph-archive.sh

chmod +x .ralph/scripts/ralph.sh
chmod +x .ralph/scripts/ralph-init.sh
chmod +x .ralph/scripts/ralph-archive.sh

# ──────────────────────────────────────────────────────────────────────────────
# Download templates
# ──────────────────────────────────────────────────────────────────────────────
echo "[ralph-install] Downloading templates..."
curl -fsSL "$RAW_BASE/templates/prompt.md"              -o .ralph/templates/prompt.md
curl -fsSL "$RAW_BASE/templates/prd-template.md"        -o .ralph/templates/prd-template.md
curl -fsSL "$RAW_BASE/templates/tasks-template.json"    -o .ralph/templates/tasks-template.json
curl -fsSL "$RAW_BASE/templates/progress-template.md"   -o .ralph/templates/progress-template.md

# ──────────────────────────────────────────────────────────────────────────────
# Download sandbox setup
# ──────────────────────────────────────────────────────────────────────────────
echo "[ralph-install] Downloading sandbox setup..."
curl -fsSL "$RAW_BASE/sandbox/setup.sh" -o .ralph/sandbox/setup.sh
chmod +x .ralph/sandbox/setup.sh

# ──────────────────────────────────────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────────────────────────────────────
echo ""
echo "[ralph-install] Installation complete!"
echo ""
echo "  .ralph/"
echo "  ├── scripts/"
echo "  │   ├── ralph.sh"
echo "  │   ├── ralph-init.sh"
echo "  │   └── ralph-archive.sh"
echo "  ├── templates/"
echo "  │   ├── prompt.md"
echo "  │   ├── prd-template.md"
echo "  │   ├── tasks-template.json"
echo "  │   └── progress-template.md"
echo "  └── sandbox/"
echo "      └── setup.sh"
echo ""
echo "Next steps:"
echo "  1. Run: .ralph/scripts/ralph-init.sh --name my-feature"
echo "  2. Run: /ralph-plan to generate your PRD and task list"
echo "  3. Run: .ralph/scripts/ralph.sh --no-sandbox to start the loop"
echo ""
