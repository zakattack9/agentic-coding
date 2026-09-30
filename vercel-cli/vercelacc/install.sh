#!/bin/sh
# Install or uninstall vercelacc.
#   sh install.sh             copy vercelacc.sh and add a source line to the rc file
#   sh install.sh --uninstall remove the installed script and the source line
# Account data under $VACCT_HOME/accounts is never touched.
set -eu

tool_dir=$(CDPATH='' cd -P "$(dirname "$0")" && pwd -P)
home_dir=${VACCT_HOME:-$HOME/.config/vercel-accounts}
dest=$home_dir/vercelacc.sh
marker='# vercelacc (managed by agentic-coding/vercel-cli/vercelacc)'

if [ -n "${VERCELACC_RC:-}" ]; then
    rc=$VERCELACC_RC
else
    case ${SHELL:-} in
        */bash) rc=$HOME/.bashrc ;;
        *) rc=$HOME/.zshrc ;;
    esac
fi

# Drops our managed block and the legacy line from the first manual install.
strip_rc() {
    [ -f "$rc" ] || return 0
    tmp=$(mktemp "$rc.vercelacc.XXXXXX")
    awk -v marker="$marker" '
        $0 == marker { skip = 1; next }
        skip { skip = 0; next }
        $0 == "# Multiple Vercel CLI logins (vercelacc help)" { next }
        $0 == "# Multiple Vercel CLI logins (vacct help)" { next }
        index($0, "/.config/vercel-accounts/vercel-accounts.sh") { next }
        { print }
    ' "$rc" > "$tmp"
    cat "$tmp" > "$rc"
    rm -f "$tmp"
}

if [ "${1:-}" = "--uninstall" ]; then
    strip_rc
    rm -f "$dest" "$home_dir/vercel-accounts.sh"
    printf 'vercelacc: uninstalled from %s (account data kept in %s/accounts)\n' "$rc" "$home_dir"
    exit 0
fi

mkdir -p "$home_dir"
chmod 700 "$home_dir"
install -m 644 "$tool_dir/vercelacc.sh" "$dest"
rm -f "$home_dir/vercel-accounts.sh"

strip_rc
if [ "$home_dir" = "$HOME/.config/vercel-accounts" ]; then
    line="source \"\$HOME/.config/vercel-accounts/vercelacc.sh\""
else
    line="export VACCT_HOME=\"$home_dir\"; source \"$dest\""
fi
printf '%s\n%s\n' "$marker" "$line" >> "$rc"

printf 'vercelacc: installed %s\n' "$dest"
printf 'vercelacc: sourced from %s; open a new terminal or run: source %s\n' "$rc" "$rc"
