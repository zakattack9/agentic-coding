#!/bin/sh
# Tests vercelacc against a fake Vercel CLI in bash and zsh (whichever exist),
# plus install.sh. Uses a temporary HOME; never touches real logins.
# Snippets are single-quoted on purpose: the shell under test expands them.
# shellcheck disable=SC2016
set -eu

tool_dir=$(CDPATH='' cd -P "$(dirname "$0")/.." && pwd -P)
script=$tool_dir/vercelacc.sh
root=$(mktemp -d "${TMPDIR:-/tmp}/vercelacc-test.XXXXXXXX")
root=$(CDPATH='' cd -P "$root" && pwd -P)
trap 'rm -rf "$root"' 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM

mkdir -p "$root/bin"
ln -s "$tool_dir/test/fake-vercel" "$root/bin/vercel"
checks=0
fail() { printf 'FAIL [%s]: %s\n--- output ---\n%s\n' "$shell_name" "$1" "$(cat "$root/out")" >&2; exit 1; }

# run <cwd> <snippet>: runs snippet in the shell under test after sourcing the script.
run() {
    rc=0
    (cd "$1" && env PATH="$root/bin:$PATH" HOME="$root/home" VACCT_HOME="$vacct_home" \
        XDG_DATA_HOME="$root/xdg" "$shell_bin" -c "set -u; . '$script'; $2") > "$root/out" 2>&1 || rc=$?
}
has() { grep -qF -- "$1" "$root/out" || fail "missing: $1"; checks=$((checks + 1)); }
lacks() { if grep -qF -- "$1" "$root/out"; then fail "unexpected: $1"; fi; checks=$((checks + 1)); }
exit_is() { [ "$rc" -eq "$1" ] || fail "exit $rc, expected $1"; checks=$((checks + 1)); }

shells=${VERCELACC_TEST_SHELLS:-"bash zsh"}
for shell_name in $shells; do
    shell_bin=$(command -v "$shell_name") || { printf 'SKIP: %s not installed\n' "$shell_name"; continue; }
    base=$root/$shell_name
    vacct_home=$base/home/.config/vercel-accounts
    p=$base/projects
    mkdir -p "$root/home" "$root/xdg/com.vercel.cli" "$p/A/.vercel" "$p/B/.vercel" "$p/other" \
        "$p/t1" "$p/t2" "$p/mono/.vercel" "$p/mono/apps/web/src" "$p/mono/apps/api"
    : > "$root/xdg/com.vercel.cli/auth.json"
    echo '{"projectId":"a","orgId":"team_A"}' > "$p/A/.vercel/project.json"
    echo '{"projectId":"b","orgId":"team_B"}' > "$p/B/.vercel/project.json"
    echo '{"orgId":"team_TOP","projects":[{"id":"w","directory":"apps/web","orgId":"team_WEB"},{"id":"x","directory":"apps/api"}]}' \
        > "$p/mono/.vercel/repo.json"

    # Nothing configured: plain passthrough.
    run "$p/other" 'vercel ls; vercelacc current'
    has 'REAL: ls'; has '(Vercel CLI default login)'; exit_is 0

    # Accounts.
    run "$p/other" 'vercelacc add work; vercelacc add personal --existing; vercelacc list'
    has 'REAL: login --global-config work'; has "'personal' now uses the Vercel CLI's own login"; has '* work'
    [ "$(readlink "$vacct_home/accounts/personal")" = "$root/xdg/com.vercel.cli" ] || fail 'personal symlink target'
    run "$p/other" 'vercelacc add personal --existing'
    has "account 'personal' already exists"; exit_is 1

    # Switching.
    run "$p/other" 'vercelacc personal; vercel ls'
    has "now using 'personal'"; has 'REAL: --global-config personal ls'
    run "$p/other" 'vercelacc work deploy; vercelacc current'
    has "using 'work' (shell override)"; has 'REAL: --global-config work deploy'; has 'personal (global default)'
    run "$p/other" 'vercelacc shell work; vercel ls; vercelacc shell -; vercel ls'
    has 'REAL: --global-config work ls'; has 'REAL: --global-config personal ls'
    run "$p/other" 'vercelacc nobody'
    has "unknown command or account 'nobody'"; exit_is 1

    # Existing links are not mapped implicitly.
    run "$p/A" 'vercel ls'
    has 'org team_A is not mapped'; has 'REAL: --global-config personal ls'
    [ ! -f "$vacct_home/orgs" ] || fail 'orgs written for an existing link'
    run "$p/A" 'vercelacc map work; vc deploy'
    has "using 'work' (linked project team_A)"; has 'REAL: --global-config work deploy'

    # Target directory comes from --cwd or a path argument.
    run "$p/other" "vercel --cwd '$p/A' ls; vercel deploy '$p/A'; vercel '$p/A'"
    lacks 'global default'; has "using 'work' (linked project team_A)"
    run "$p/A" "vercel --cwd '$p/B' ls"
    has "using 'personal' (global default)"; has 'org team_B is not mapped'

    # New links are mapped, except when a token authenticated the command.
    run "$p/t1" 'vercel link --token abc'
    has 'REAL: --global-config personal link --token abc'; lacks 'mapped org'
    run "$p/t2" 'vercel --scope x link'
    has "mapped org team_NEW to 'personal'"

    # Monorepo and env-var orgs.
    run "$p/mono/apps/web/src" '_vacct_org_id "$PWD"'
    has 'team_WEB'
    run "$p/mono/apps/api" '_vacct_org_id "$PWD"'
    has 'team_TOP'
    run "$p/other" 'VERCEL_ORG_ID=team_A VERCEL_PROJECT_ID=z vercelacc current'
    has 'work (linked project team_A)'

    # Guards.
    run "$p/other" 'vercel login'
    has "'vercel login' would act on account 'personal'"; exit_is 1
    run "$p/other" 'vercel -Q /x whoami'
    has 'REAL: -Q /x whoami'
    for bad in .. .x -f help; do
        run "$p/other" "vercelacc add '$bad'"
        exit_is 1
    done
    run "$p/other" "alias vercel='npx vercel'; alias vc='vercel --prod'; shopt -s expand_aliases 2>/dev/null; . '$script'; vercelacc version"
    has 'vercelacc 0.'; exit_is 0

    # Removal.
    run "$p/other" 'FAKE_LOGOUT_FAIL=1 vercelacc remove work; vercelacc list'
    has 'logout failed; account kept'; has '  work'
    run "$p/other" 'FAKE_LOGOUT_FAIL=1 vercelacc remove work --force; vercelacc remove personal; vercelacc list'
    has "removed 'work'"; has "removed 'personal'"; lacks '  work'
    [ -f "$root/xdg/com.vercel.cli/auth.json" ] || fail 'removing a --existing account deleted the CLI login dir'
    printf 'PASS: %s\n' "$shell_name"
done

# install.sh: idempotent, replaces the legacy line, uninstall keeps account data.
shell_name=install
ihome=$root/install-home
mkdir -p "$ihome/.config/vercel-accounts/accounts/keep"
printf 'export FOO=1\n# Multiple Vercel CLI logins (vercelacc help)\nsource "$HOME/.config/vercel-accounts/vercel-accounts.sh"\n' > "$ihome/.zshrc"
: > "$ihome/.config/vercel-accounts/vercel-accounts.sh"
for _ in 1 2; do
    HOME=$ihome VERCELACC_RC=$ihome/.zshrc sh "$tool_dir/install.sh" > "$root/out" 2>&1 || fail 'install failed'
done
[ "$(grep -c 'vercelacc.sh' "$ihome/.zshrc")" -eq 1 ] || { cp "$ihome/.zshrc" "$root/out"; fail 'rc line not unique'; }
grep -q 'vercel-accounts.sh' "$ihome/.zshrc" && { cp "$ihome/.zshrc" "$root/out"; fail 'legacy rc line kept'; }
grep -q 'export FOO=1' "$ihome/.zshrc" || fail 'unrelated rc content lost'
[ ! -e "$ihome/.config/vercel-accounts/vercel-accounts.sh" ] || fail 'legacy script kept'
cmp -s "$script" "$ihome/.config/vercel-accounts/vercelacc.sh" || fail 'installed copy differs'
HOME=$ihome VERCELACC_RC=$ihome/.zshrc sh "$tool_dir/install.sh" --uninstall > "$root/out" 2>&1 || fail 'uninstall failed'
grep -q 'vercelacc' "$ihome/.zshrc" && fail 'rc line kept after uninstall'
[ -d "$ihome/.config/vercel-accounts/accounts/keep" ] || fail 'uninstall removed account data'
checks=$((checks + 7))
printf 'PASS: install\n'
printf 'PASS: %s checks\n' "$checks"
