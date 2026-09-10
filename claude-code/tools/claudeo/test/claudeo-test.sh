#!/bin/sh
set -eu

tool_dir=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd -P)
cli=$tool_dir/bin/claudeo
test_shell=${CLAUDEO_TEST_SHELL:-/bin/sh}
test_root=$(mktemp -d "${TMPDIR:-/tmp}/claudeo-test.XXXXXXXX")
test_root=$(CDPATH='' cd -P "$test_root" && pwd -P)
trap 'rm -rf "$test_root"' 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM
export HOME="$test_root/home" XDG_CONFIG_HOME="$test_root/xdg"
export CLAUDEO_HOME="$test_root/accounts with spaces"
export CLAUDEO_CLAUDE_BIN="$tool_dir/test/fake-claude"
export CLAUDEO_TEST_CAPTURE="$test_root/capture"
export CLAUDEO_TEST_SENTINEL='unchanged value'
unset CLAUDEO_TEST_MODE CLAUDEO_TEST_EXIT
mkdir -p "$HOME" "$test_root/project"
cd "$test_root/project"
checks=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
expect_command() {
    wanted=$1; shift
    actual=0
    "$@" > "$test_root/stdout" 2> "$test_root/stderr" || actual=$?
    if [ "$actual" -ne "$wanted" ]; then
        cat "$test_root/stderr" >&2
        fail "$*: expected exit $wanted, got $actual"
    fi
    if [ "$wanted" -eq 2 ]; then [ -s "$test_root/stderr" ] || fail 'missing actionable error'; fi
    checks=$((checks + 1))
}
expect() {
    expected_code=$1; shift
    expect_command "$expected_code" "$test_shell" "$cli" "$@"
}
expect_env() {
    expected_code=$1; env_override=$2; shift 2
    expect_command "$expected_code" env "$env_override" "$test_shell" "$cli" "$@"
}
file_is() {
    printf '%s' "$2" > "$test_root/expected"
    cmp -s "$1" "$test_root/expected" || fail "unexpected contents: $1"
    checks=$((checks + 1))
}
argv_is() {
    file_is "$CLAUDEO_TEST_CAPTURE/argc" "$#"
    index=0
    for expected_arg do
        file_is "$CLAUDEO_TEST_CAPTURE/arg.$index" "$expected_arg"
        index=$((index + 1))
    done
}
private() {
    mode=$(stat -f '%Lp' "$1" 2>/dev/null) || mode=$(stat -c '%a' "$1")
    [ "$mode" = 700 ] || fail "permissions $mode, expected 700: $1"
    checks=$((checks + 1))
}

expect 0 help
expect 0 --help
expect 0 --version
file_is "$test_root/stdout" '0.1.0
'
expect 2
expect 2 --bogus
expect 2 logni
expect 0 list
file_is "$test_root/stdout" ''
expect 1 doctor
[ ! -e "$CLAUDEO_HOME" ] || fail 'read-only commands created storage'

long64=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
for name in '' . .. ../escape a/b /absolute 'two words' 'tab	name' '-bad' '_bad' '.hidden' 'é' "$long64"x; do
    expect 2 init "$name"
done
for name in personal work A0._- "$long64"; do expect 0 init "$name"; done
personal=$CLAUDEO_HOME/accounts/personal
work=$CLAUDEO_HOME/accounts/work
expect 0 init personal
file_is "$test_root/stdout" "$personal
"
private "$CLAUDEO_HOME"
private "$CLAUDEO_HOME/accounts"
private "$personal"
private "$personal/anthropic"
file_is "$CLAUDEO_TEST_CAPTURE/calls" 'call
'
expect 2 init Personal
expect 2 run PERSONAL
for cmd in run status logout path; do expect 2 "$cmd" missing; done
[ ! -e "$CLAUDEO_HOME/accounts/missing" ] || fail 'unknown account created'
ln -s "$personal" "$CLAUDEO_HOME/accounts/link"
ln -s "$test_root/nonexistent" "$CLAUDEO_HOME/accounts/dangling"
for name in link dangling; do
    for cmd in init login run status logout path; do expect 2 "$cmd" "$name"; done
done
expect 1 doctor
unlink "$CLAUDEO_HOME/accounts/link"
unlink "$CLAUDEO_HOME/accounts/dangling"
expect 0 path personal
file_is "$test_root/stdout" "$personal
"
expect 0 list
file_is "$test_root/stdout" "A0._-
$long64
personal
work
"

# These are synthetic values; never enumerate or dump the caller's environment.
for variable in ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN \
    CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY \
    ANTHROPIC_PROFILE ANTHROPIC_FEDERATION_RULE_ID ANTHROPIC_ORGANIZATION_ID \
    ANTHROPIC_IDENTITY_TOKEN_FILE ANTHROPIC_IDENTITY_TOKEN \
    ANTHROPIC_SERVICE_ACCOUNT_ID ANTHROPIC_WORKSPACE_ID ANTHROPIC_BASE_URL; do
    export "$variable=synthetic-test-only"
done
export CLAUDE_CONFIG_DIR="$test_root/wrong-claude" ANTHROPIC_CONFIG_DIR="$test_root/wrong-profile"
expect 0 run personal -- -p 'with spaces' '' '--flag=value' '*' 'a
b'
argv_is -p 'with spaces' '' '--flag=value' '*' 'a
b'
file_is "$CLAUDEO_TEST_CAPTURE/config" "$personal"
file_is "$CLAUDEO_TEST_CAPTURE/profile" "$personal/anthropic"
file_is "$CLAUDEO_TEST_CAPTURE/overrides" ''
file_is "$CLAUDEO_TEST_CAPTURE/sentinel" 'unchanged value'
file_is "$CLAUDEO_TEST_CAPTURE/cwd" "$test_root/project
"
[ "$ANTHROPIC_API_KEY" = synthetic-test-only ] || fail 'parent environment changed'
expect 0 run work --continue
argv_is --continue
file_is "$CLAUDEO_TEST_CAPTURE/config" "$work"
expect 0 personal -p 'hello world'
argv_is -p 'hello world'
expect 0 work -- --continue
argv_is --continue
expect 0 run personal
argv_is
expect 0 login new --email 'not prevalidated' --sso
argv_is auth login --claudeai --email 'not prevalidated' --sso
file_is "$CLAUDEO_TEST_CAPTURE/overrides" ''
expect 0 login personal --sso
argv_is auth login --claudeai --sso
expect 2 login forbidden --console
[ ! -e "$CLAUDEO_HOME/accounts/forbidden" ] || fail 'malformed login created account'
expect 2 login personal --email
expect 2 login personal --unknown
expect 0 status personal
argv_is auth status --text
file_is "$test_root/stdout" 'Not logged in
'
file_is "$CLAUDEO_TEST_CAPTURE/overrides" ''
expect 0 status personal --json
argv_is auth status
file_is "$test_root/stdout" '{"loggedIn":false}
'
expect 0 logout personal
argv_is auth logout
file_is "$CLAUDEO_TEST_CAPTURE/overrides" ''
[ -d "$personal" ] || fail 'logout removed account'
for code in 1 7 42; do
    export CLAUDEO_TEST_EXIT=$code
    for cmd in login run status logout; do expect "$code" "$cmd" personal; done
done
unset CLAUDEO_TEST_EXIT

export CLAUDEO_TEST_MODE=stdin
printf 'piped input\n' | "$test_shell" "$cli" personal > "$test_root/stdout" 2> "$test_root/stderr"
file_is "$test_root/stdout" 'piped input
'
file_is "$test_root/stderr" 'fake stderr
'
unset CLAUDEO_TEST_MODE
CLAUDEO_TEST_CAPTURE="$test_root/signal" CLAUDEO_TEST_MODE=signal "$test_shell" "$cli" personal &
signal_pid=$!
attempt=0
while [ ! -f "$test_root/signal/ready" ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 10 ] || fail 'signal test did not start'
    sleep 1
done
file_is "$test_root/signal/pid" "$signal_pid"
kill -TERM "$signal_pid"
signal_status=0
wait "$signal_pid" || signal_status=$?
[ "$signal_status" -eq 73 ] || fail 'TERM did not reach the native process'
checks=$((checks + 1))

CLAUDEO_TEST_CAPTURE="$test_root/one" CLAUDEO_TEST_PEER="$test_root/two" CLAUDEO_TEST_MODE=concurrent "$test_shell" "$cli" personal &
one=$!
CLAUDEO_TEST_CAPTURE="$test_root/two" CLAUDEO_TEST_PEER="$test_root/one" CLAUDEO_TEST_MODE=concurrent "$test_shell" "$cli" work &
two=$!
wait "$one" || fail 'first concurrent session failed'
wait "$two" || fail 'second concurrent session failed'
file_is "$test_root/one/config" "$personal"
file_is "$test_root/two/config" "$work"
file_is "$test_root/one/profile" "$personal/anthropic"
file_is "$test_root/two/profile" "$work/anthropic"

expect 0 doctor
file_is "$test_root/stdout" 'fake-claude 1.0.0
'
grep -q ANTHROPIC_API_KEY "$test_root/stderr" || fail 'doctor omitted warning'
if grep -q synthetic-test-only "$test_root/stderr"; then fail 'doctor leaked a value'; fi
mkdir "$CLAUDEO_HOME/accounts/bad name"
expect 1 doctor
rmdir "$CLAUDEO_HOME/accounts/bad name"
touch "$CLAUDEO_HOME/accounts/not-directory"
expect 1 doctor
unlink "$CLAUDEO_HOME/accounts/not-directory"
rmdir "$personal/anthropic"
ln -s "$work/anthropic" "$personal/anthropic"
expect 2 run personal
expect 2 init personal
expect 1 doctor
unlink "$personal/anthropic"
expect 0 init personal
for cmd in init run status logout path login; do expect 2 "$cmd"; done
for cmd in list doctor help --version; do expect 2 "$cmd" extra; done
expect 2 status personal --text
expect 2 status personal --json extra
expect 2 logout personal extra
expect 2 path personal extra
expect 2 init personal extra

saved_root=$CLAUDEO_HOME
expect_env 2 CLAUDEO_HOME=relative init personal
expect_env 2 CLAUDEO_HOME=/ init personal
expect_env 2 CLAUDEO_HOME="$test_root/../elsewhere" init personal
ln -s "$saved_root" "$test_root/root-link"
expect_env 2 CLAUDEO_HOME="$test_root/root-link" init personal
mkdir "$test_root/unsafe-root"
ln -s "$saved_root/accounts" "$test_root/unsafe-root/accounts"
expect_env 2 CLAUDEO_HOME="$test_root/unsafe-root" init personal
expect_env 2 CLAUDEO_CLAUDE_BIN="$test_root/missing" run personal
expect_env 1 CLAUDEO_CLAUDE_BIN="$test_root/missing" doctor
expect_env 2 CLAUDEO_CLAUDE_BIN="$test_root" run personal
expect_env 0 CLAUDEO_HOME="$saved_root/" path personal
file_is "$test_root/stdout" "$personal
"
# Empty exported overrides must be unset as well, not merely blanked.
expect_env 0 ANTHROPIC_API_KEY= run personal
file_is "$CLAUDEO_TEST_CAPTURE/overrides" ''
# Installation is isolated too; uninstall must preserve siblings and account data.
(cd "$tool_dir" && make install PREFIX="$test_root/install prefix") > "$test_root/install-log"
expect_command 0 "$test_root/install prefix/bin/claudeo" --version
file_is "$test_root/stdout" '0.1.0
'
touch "$test_root/install prefix/bin/keep-me"
(cd "$tool_dir" && make uninstall PREFIX="$test_root/install prefix") >> "$test_root/install-log"
[ ! -e "$test_root/install prefix/bin/claudeo" ] || fail 'uninstall left executable'
[ -f "$test_root/install prefix/bin/keep-me" ] || fail 'uninstall removed sibling'
[ -d "$personal" ] || fail 'uninstall removed account data'
checks=$((checks + 3))
# Default storage fallbacks are still confined to the test home.
unset CLAUDEO_HOME
expect 0 init xdg
file_is "$test_root/stdout" "$XDG_CONFIG_HOME/claudeo/accounts/xdg
"
unset XDG_CONFIG_HOME
expect 0 init default
file_is "$test_root/stdout" "$HOME/.config/claudeo/accounts/default
"
printf 'PASS: %s assertions (isolated fake-Claude harness)\n' "$checks"
