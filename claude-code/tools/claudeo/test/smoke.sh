#!/bin/sh
set -eu

# Opt-in integration test. No login, logout, credential inspection, or API calls.
tool_dir=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd -P)
if ! real_claude=$(command -v claude); then
    printf 'SKIP: real Claude Code executable is unavailable\n'
    exit 0
fi
# Resolve a relative PATH entry before moving to the isolated working directory.
case $real_claude in /*) ;; *) real_claude=$(pwd -P)/$real_claude ;; esac
smoke_root=$(mktemp -d "${TMPDIR:-/tmp}/claudeo-smoke.XXXXXXXX")
smoke_root=$(CDPATH='' cd -P "$smoke_root" && pwd -P)
trap 'rm -rf "$smoke_root"' 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM
export HOME="$smoke_root/home" XDG_CONFIG_HOME="$smoke_root/xdg"
export CLAUDEO_HOME="$smoke_root/claudeo" CLAUDEO_CLAUDE_BIN="$real_claude"
unset CLAUDEO_SHARED_CONFIG_DIR
mkdir -p "$HOME" "$smoke_root/project"
cd "$smoke_root/project"
"$tool_dir/bin/claudeo" init --isolated smoke >/dev/null
status=0
"$tool_dir/bin/claudeo" status smoke > "$smoke_root/status" 2> "$smoke_root/stderr" || status=$?
if [ "$status" -ne 1 ]; then
    printf 'FAIL: isolated auth status returned %s; expected unauthenticated (1)\n' "$status" >&2
    exit 1
fi
printf 'PASS: isolated real-Claude auth status returned unauthenticated (1)\n'
"$tool_dir/bin/claudeo" run smoke -- --version
printf 'PASS: real-Claude --version; temporary test storage will be removed\n'
