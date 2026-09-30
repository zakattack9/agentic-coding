# vercelacc: keep several Vercel CLI logins side by side and switch between them.
#
# Source of truth: agentic-coding/vercel-cli/vercelacc/vercelacc.sh.
# `make install` copies it to ~/.config/vercel-accounts/vercelacc.sh and adds
# a `source` line to your shell rc file. Edit the repo copy, not the installed one.
#
# How it works: every account gets its own Vercel global config directory
# (auth.json, config.json) under $VACCT_HOME/accounts/<name>. The `vercel`
# and `vc` shell functions below pass that directory to the real CLI with
# `--global-config`, so all logins stay valid at the same time and token
# refreshes are written back to the right place. Nothing is copied or swapped.
#
# Account resolution, first match wins:
#   1. You passed -Q/--global-config yourself: arguments go through untouched.
#   2. $VERCEL_ACCOUNT is set (`vercelacc shell <name>`, this shell only).
#   3. The target project's org is mapped to an account. The org comes from
#      VERCEL_ORG_ID + VERCEL_PROJECT_ID, else .vercel/project.json in the
#      target directory (--cwd, a path argument, or $PWD), else the matching
#      project in the nearest .vercel/repo.json.
#   4. The global default account (`vercelacc <name>`).
#   5. Nothing configured: the CLI's own default login is used.
#
# A mapping is recorded automatically when a command links a new org (for
# example `vercel link` or a first `vercel deploy`). Existing links are never
# mapped implicitly; use `vercelacc map <name>` for those.

VERCELACC_VERSION="0.1.0"
VACCT_HOME="${VACCT_HOME:-$HOME/.config/vercel-accounts}"

# Aliases with these names would break the function definitions below.
unalias vercel vc vercelacc 2>/dev/null || true

function _vacct_valid_name {
  case "${1:-}" in
    ''|.*|-*|*[!A-Za-z0-9._-]*)
      echo "vercelacc: invalid account name '${1:-}' (letters, digits, . _ -; must not start with . or -)" >&2
      return 1 ;;
    add|use|shell|map|unmap|list|ls|whoami|current|remove|rm|help|version)
      echo "vercelacc: '$1' is a vercelacc command and cannot be an account name" >&2
      return 1 ;;
  esac
}

# The Vercel CLI's own global config dir (where a plain `vercel login` goes).
function _vacct_default_dir {
  if [ -n "${XDG_DATA_HOME:-}" ]; then
    echo "$XDG_DATA_HOME/com.vercel.cli"
  elif [ "$(uname)" = "Darwin" ]; then
    echo "$HOME/Library/Application Support/com.vercel.cli"
  else
    echo "$HOME/.local/share/com.vercel.cli"
  fi
}

function _vacct_exists {
  [ -d "$VACCT_HOME/accounts/$1" ]
}

function _vacct_require {
  _vacct_valid_name "${1:-}" || return 1
  _vacct_exists "$1" || { echo "vercelacc: no account '$1'; run: vercelacc add $1" >&2; return 1; }
}

# Prints the orgId of the project that the CLI would use for directory $1.
function _vacct_org_id {
  local start="$1" dir rel file
  if [ -n "${VERCEL_ORG_ID:-}" ] && [ -n "${VERCEL_PROJECT_ID:-}" ]; then
    echo "$VERCEL_ORG_ID"
    return 0
  fi
  if [ -f "$start/.vercel/project.json" ]; then
    sed -n 's/.*"orgId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$start/.vercel/project.json" | head -n 1
    return 0
  fi
  dir="$start"
  while :; do
    file="$dir/.vercel/repo.json"
    if [ -f "$file" ]; then
      if [ "$dir" = "$start" ]; then rel="."; else rel="${start#"$dir"/}"; fi
      if ! { command -v jq >/dev/null 2>&1 && jq -er --arg rel "$rel" '
          (.orgId // "") as $top
          | [.projects[]? | select(.directory as $d
              | $d == "." or $d == $rel or ($rel | startswith($d + "/")))]
          | (sort_by(.directory | length) | last) // {}
          | .orgId // $top' "$file" 2>/dev/null; }; then
        sed -n 's/.*"orgId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | head -n 1
      fi
      return 0
    fi
    [ "$dir" = "/" ] || [ -z "$dir" ] && return 1
    dir="$(dirname "$dir")"
  done
}

function _vacct_org_account {
  [ -n "${1:-}" ] && [ -f "$VACCT_HOME/orgs" ] || return 1
  awk -v id="$1" '$1 == id { print $2; exit }' "$VACCT_HOME/orgs"
}

function _vacct_lock {
  local i=0
  while ! mkdir "$VACCT_HOME/orgs.lock" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 50 ]; then
      echo "vercelacc: $VACCT_HOME/orgs.lock is held; remove it if no other vercel command is running" >&2
      return 1
    fi
    sleep 0.1
  done
}

# Drops lines whose field $1 equals $2, then appends line $3 (if given).
function _vacct_orgs_rewrite {
  local field="$1" value="$2" line="${3:-}" tmp rc
  mkdir -p "$VACCT_HOME" || return 1
  _vacct_lock || return 1
  tmp="$(mktemp "$VACCT_HOME/orgs.XXXXXX")" || { rmdir "$VACCT_HOME/orgs.lock"; return 1; }
  {
    if [ -f "$VACCT_HOME/orgs" ]; then awk -v f="$field" -v v="$value" '$f != v' "$VACCT_HOME/orgs"; fi
    if [ -n "$line" ]; then echo "$line"; fi
  } > "$tmp" && mv "$tmp" "$VACCT_HOME/orgs"
  rc=$?
  rm -f "$tmp"
  rmdir "$VACCT_HOME/orgs.lock"
  return "$rc"
}

# Sets _vacct_name and _vacct_why for org $1. _vacct_name is empty when nothing applies.
function _vacct_resolve {
  local org="${1:-}" mapped=""
  _vacct_name="" _vacct_why=""
  [ -n "$org" ] && mapped="$(_vacct_org_account "$org")"

  if [ -n "${VERCEL_ACCOUNT:-}" ]; then
    _vacct_name="$VERCEL_ACCOUNT" _vacct_why="shell override"
    if [ -n "$mapped" ] && [ "$mapped" != "$VERCEL_ACCOUNT" ]; then
      echo "vercelacc: warning: this project is mapped to '$mapped' but the shell override is '$VERCEL_ACCOUNT'" >&2
    fi
  elif [ -n "$mapped" ]; then
    _vacct_name="$mapped" _vacct_why="linked project $org"
  elif [ -f "$VACCT_HOME/current" ]; then
    _vacct_name="$(cat "$VACCT_HOME/current")" _vacct_why="global default"
  fi

  if [ -n "$_vacct_name" ] && ! _vacct_exists "$_vacct_name"; then
    echo "vercelacc: account '$_vacct_name' ($_vacct_why) does not exist; run: vercelacc add $_vacct_name" >&2
    return 1
  fi
}

function vercel {
  local arg skip="" cwd="" pos=0 first="" second="" token=0 target org_before org_after rc

  for arg in "$@"; do
    if [ -n "$skip" ]; then
      [ "$skip" = "cwd" ] && cwd="$arg"
      skip=""
      continue
    fi
    case "$arg" in
      -Q|--global-config|--global-config=*) command vercel "$@"; return ;;
      --cwd) skip="cwd" ;;
      --cwd=*) cwd="${arg#--cwd=}" ;;
      -t|--token) token=1; skip="value" ;;
      --token=*) token=1 ;;
      -S|--scope|-A|--local-config|-e|--env|-b|--build-env|-m|--meta|--target|--regions) skip="value" ;;
      -*) ;;
      *)
        pos=$((pos + 1))
        if [ "$pos" -eq 1 ]; then first="$arg"; elif [ "$pos" -eq 2 ]; then second="$arg"; fi ;;
    esac
  done
  [ -n "${VERCEL_TOKEN:-}" ] && token=1

  # The directory the CLI will treat as the project.
  target="$cwd"
  if [ -z "$target" ]; then
    if [ -n "$first" ] && [ -d "$first" ]; then
      target="$first"
    elif { [ "$first" = "deploy" ] || [ "$first" = "dev" ]; } && [ -n "$second" ] && [ -d "$second" ]; then
      target="$second"
    fi
  fi
  target="$(cd "${target:-.}" 2>/dev/null && pwd)" || target="$PWD"

  org_before="$(_vacct_org_id "$target" 2>/dev/null)"
  _vacct_resolve "$org_before" || return 1
  if [ -z "$_vacct_name" ]; then
    command vercel "$@"
    return
  fi

  case "$first" in
    login|logout)
      echo "vercelacc: 'vercel $first' would act on account '$_vacct_name'." >&2
      echo "vercelacc: use 'vercelacc add <name>' or 'vercelacc remove <name>' instead." >&2
      return 1 ;;
  esac

  if [ -n "${VERCEL_TOKEN:-}" ]; then
    echo "vercelacc: warning: VERCEL_TOKEN is set and overrides the '$_vacct_name' login" >&2
  fi
  if [ -z "${VACCT_QUIET:-}" ]; then
    echo "vercelacc: using '$_vacct_name' ($_vacct_why)" >&2
    if [ -n "$org_before" ] && [ "$_vacct_why" = "global default" ]; then
      echo "vercelacc: org $org_before is not mapped; run 'vercelacc map <name>' to pin it" >&2
    fi
  fi

  command vercel --global-config "$VACCT_HOME/accounts/$_vacct_name" "$@"
  rc=$?

  # Remember which account owns a project this command just linked.
  if [ "$rc" -eq 0 ] && [ "$token" -eq 0 ]; then
    org_after="$(_vacct_org_id "$target" 2>/dev/null)"
    if [ -n "$org_after" ] && [ "$org_after" != "$org_before" ] && [ -z "$(_vacct_org_account "$org_after")" ]; then
      _vacct_orgs_rewrite 1 "$org_after" "$org_after $_vacct_name" \
        && echo "vercelacc: mapped org $org_after to '$_vacct_name'" >&2
    fi
  fi
  return "$rc"
}

function vc {
  vercel "$@"
}

function vercelacc {
  local cmd="${1:-}" name org current force=0
  [ $# -gt 0 ] && shift
  case "$cmd" in
    add)
      name="${1:-}"; _vacct_valid_name "$name" || return 1
      if [ "${2:-}" = "--existing" ]; then
        # Reuse the CLI's own login instead of logging in again.
        if [ -e "$VACCT_HOME/accounts/$name" ]; then
          echo "vercelacc: account '$name' already exists" >&2
          return 1
        fi
        [ -f "$(_vacct_default_dir)/auth.json" ] \
          || echo "vercelacc: warning: no login in $(_vacct_default_dir) yet; run: vercelacc add $name" >&2
        mkdir -p "$VACCT_HOME/accounts" && chmod 700 "$VACCT_HOME" || return 1
        ln -s "$(_vacct_default_dir)" "$VACCT_HOME/accounts/$name" || return 1
        echo "vercelacc: '$name' now uses the Vercel CLI's own login"
      else
        mkdir -p "$VACCT_HOME/accounts/$name" && chmod 700 "$VACCT_HOME" "$VACCT_HOME/accounts/$name" || return 1
        command vercel login --global-config "$VACCT_HOME/accounts/$name" || return
      fi
      [ -f "$VACCT_HOME/current" ] || echo "$name" > "$VACCT_HOME/current"
      ;;
    use)
      name="${1:-}"; _vacct_require "$name" || return 1
      echo "$name" > "$VACCT_HOME/current"
      echo "vercelacc: global default is now '$name'"
      ;;
    shell)
      name="${1:-}"
      if [ -z "$name" ] || [ "$name" = "-" ]; then
        unset VERCEL_ACCOUNT
        echo "vercelacc: shell override cleared"
        return 0
      fi
      _vacct_require "$name" || return 1
      export VERCEL_ACCOUNT="$name"
      echo "vercelacc: this shell now uses '$name'"
      ;;
    map)
      name="${1:-}"; _vacct_require "$name" || return 1
      org="$(_vacct_org_id "$PWD")"
      [ -n "$org" ] || { echo "vercelacc: no linked project here" >&2; return 1; }
      _vacct_orgs_rewrite 1 "$org" "$org $name" || return 1
      echo "vercelacc: mapped org $org to '$name'"
      ;;
    unmap)
      org="$(_vacct_org_id "$PWD")"
      [ -n "$org" ] || { echo "vercelacc: no linked project here" >&2; return 1; }
      _vacct_orgs_rewrite 1 "$org" || return 1
      echo "vercelacc: removed mapping for org $org"
      ;;
    list|ls)
      [ -d "$VACCT_HOME/accounts" ] || { echo "vercelacc: no accounts yet; run: vercelacc add <name>"; return 0; }
      current="$(cat "$VACCT_HOME/current" 2>/dev/null)"
      find "$VACCT_HOME/accounts" -mindepth 1 -maxdepth 1 -exec basename {} \; | sort | while IFS= read -r name; do
        if [ "$name" = "$current" ]; then echo "* $name"; else echo "  $name"; fi
      done
      ;;
    whoami)
      [ -d "$VACCT_HOME/accounts" ] || { echo "vercelacc: no accounts yet"; return 0; }
      find "$VACCT_HOME/accounts" -mindepth 1 -maxdepth 1 -exec basename {} \; | sort | while IFS= read -r name; do
        printf '%s: ' "$name"
        command vercel whoami --global-config "$VACCT_HOME/accounts/$name" 2>/dev/null </dev/null || echo "(not logged in)"
      done
      ;;
    current|"")
      _vacct_resolve "$(_vacct_org_id "$PWD" 2>/dev/null)" || return 1
      if [ -n "$_vacct_name" ]; then echo "$_vacct_name ($_vacct_why)"; else echo "(Vercel CLI default login)"; fi
      ;;
    remove|rm)
      name="${1:-}"
      [ "${2:-}" = "--force" ] && force=1
      _vacct_require "$name" || return 1
      if ! command vercel logout --global-config "$VACCT_HOME/accounts/$name" && [ "$force" -eq 0 ]; then
        echo "vercelacc: logout failed; account kept. Re-run with --force to delete it anyway." >&2
        return 1
      fi
      rm -rf "${VACCT_HOME:?}/accounts/$name" || { echo "vercelacc: could not delete $VACCT_HOME/accounts/$name" >&2; return 1; }
      _vacct_orgs_rewrite 2 "$name"
      [ "$(cat "$VACCT_HOME/current" 2>/dev/null)" = "$name" ] && rm -f "$VACCT_HOME/current"
      echo "vercelacc: removed '$name'"
      ;;
    version|--version)
      echo "vercelacc $VERCELACC_VERSION"
      ;;
    help|-h|--help)
      cat <<'EOF'
vercelacc - multiple Vercel CLI logins

  vercelacc <name>                  switch to account <name> (all shells)
  vercelacc <name> <vercel args>    run one vercel command as <name>
  vercelacc add <name>              log in an account (new, or re-login an expired one)
  vercelacc add <name> --existing   name the Vercel CLI's own login <name>
  vercelacc use <name>              same as `vercelacc <name>`
  vercelacc shell <name>            use <name> in this shell only; `vercelacc shell -` clears it
  vercelacc map <name>              map the linked project's org in this folder to <name>
  vercelacc unmap                   remove that mapping
  vercelacc list                    list accounts (* = global default)
  vercelacc whoami                  show the Vercel user behind every account
  vercelacc current                 show which account `vercel` would use here, and why
  vercelacc remove <name> [--force] log out and delete an account
  vercelacc version                 print the installed version

A project is mapped automatically when a vercel command links it to a new
org, and mapped projects always use their own account. Set VACCT_QUIET=1 to
hide the "using ..." line.
EOF
      ;;
    *)
      if _vacct_valid_name "$cmd" 2>/dev/null && _vacct_exists "$cmd"; then
        if [ $# -eq 0 ]; then
          # `vercelacc <name>`: switch the global default.
          echo "$cmd" > "$VACCT_HOME/current"
          echo "vercelacc: now using '$cmd' (all shells; linked projects keep their mapped account)"
        else
          # `vercelacc <name> <vercel args>`: run one command as <name>.
          (export VERCEL_ACCOUNT="$cmd"; vercel "$@")
        fi
        return
      fi
      echo "vercelacc: unknown command or account '$cmd' (try: vercelacc help)" >&2
      return 1
      ;;
  esac
}
