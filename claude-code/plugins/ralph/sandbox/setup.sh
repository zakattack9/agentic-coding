#!/usr/bin/env bash
# setup.sh — Auth symlink setup + git config for Docker Sandbox
#
# Run once after sandbox creation via:
#   docker sandbox exec -u root "$SANDBOX_NAME" bash < setup.sh
#
# Prerequisites:
#   - ~/.dclaude_state/.claude.json must contain valid JSON ({} minimum)
#     Using `touch` to create an empty file causes JSON parse errors on startup.
#     Initialize with: echo '{}' > ~/.dclaude_state/.claude.json
#   - ~/.dclaude_state/.claude/ directory should exist with auth state

set -euo pipefail

# The host user's dclaude_state directory is mounted into the sandbox at this path.
# Adjust if your sandbox mount point differs.
HOST_USER="${HOST_USER:-$(ls /Users/ 2>/dev/null | head -1)}"
STATE_DIR="/Users/${HOST_USER}/.dclaude_state"

# --- Root operations: symlink auth state into the agent user's home ---

# Remove any existing .claude / .claude.json in agent home (idempotent)
rm -rf /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true

# Symlink the mounted auth state into the agent user's home
ln -s "${STATE_DIR}/.claude" /home/agent/.claude
ln -s "${STATE_DIR}/.claude.json" /home/agent/.claude.json

# Fix ownership of the symlinks (not the targets) so the agent user can follow them
chown -h agent:agent /home/agent/.claude /home/agent/.claude.json 2>/dev/null || true

echo "[setup.sh] Auth symlinks created:"
echo "  /home/agent/.claude -> ${STATE_DIR}/.claude"
echo "  /home/agent/.claude.json -> ${STATE_DIR}/.claude.json"

# --- Agent-level operations: git config ---
# These run as root but configure the agent user's git via --global
# (git respects HOME, which is /home/agent when exec'd as agent)
su - agent -c 'git config --global user.email "ralph@localhost"'
su - agent -c 'git config --global user.name "Ralph Loop"'

echo "[setup.sh] Git config set for agent user"
echo "[setup.sh] Setup complete"
