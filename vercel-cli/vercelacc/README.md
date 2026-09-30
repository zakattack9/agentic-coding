# vercelacc

Stay logged in to several Vercel accounts in the Vercel CLI at once, and switch
between them with one command. `vercelacc` is a shell script for zsh and bash
that you source from your rc file. It needs only the Vercel CLI, and it uses
`jq` for monorepo links when `jq` is installed.

## How it works

The Vercel CLI keeps one login per global config directory, and every command
accepts `--global-config <dir>`. `vercelacc` gives each account its own
directory under `~/.config/vercel-accounts/accounts/<name>`, and wraps `vercel`
and `vc` in shell functions that pass the right directory on every call.

All logins stay valid side by side. The CLI writes each token refresh back to
that account's own directory, so nothing is copied, swapped, or goes stale.
`vercel switch` is still useful, but only for changing teams inside one account.

## Install

```sh
cd vercel-cli/vercelacc
make install
source ~/.zshrc        # or open a new terminal
```

`make install` copies `vercelacc.sh` to `~/.config/vercel-accounts/vercelacc.sh`
and adds a managed `source` line to `~/.zshrc`, or to `~/.bashrc` when your
`$SHELL` is bash. Set `VERCELACC_RC=<file>` to choose another rc file. Running
it again is safe: it replaces the installed copy and keeps a single rc line.

`make uninstall` removes the installed script and the rc line. Your account
logins under `~/.config/vercel-accounts/accounts` are kept.

## First-time setup

Name your existing Vercel CLI login, then add the other account:

```sh
vercelacc add personal --existing   # reuse the login you already have
vercelacc add work                  # device login for the second account
vercelacc personal                  # make personal the default
```

`--existing` links the account to the CLI's own config directory, so plain
`vercel` and `personal` share one session. `vercelacc add <name>` opens the
Vercel device login; sign in with the account you want for that name.

## Switch accounts

Switch the default for every terminal, one terminal, or one command:

```sh
vercelacc work              # switch to work in every terminal
vercelacc personal          # switch back
vercelacc work deploy       # run one command as work, without switching
vercelacc shell work        # use work in this terminal only
vercelacc shell -           # clear the terminal override
vercelacc                   # show which account `vercel` uses here, and why
vercelacc whoami            # show the Vercel user behind every account
```

Every wrapped command prints the account it used on stderr, for example
`vercelacc: using 'work' (linked project team_abc)`. Set `VACCT_QUIET=1` to hide
that line.

## Which account a command uses

The first rule that matches wins:

1. You passed `-Q` or `--global-config` yourself. The command runs unchanged.
2. A terminal override is set with `vercelacc shell <name>`.
3. The project's team is mapped to an account.
4. The default account set with `vercelacc <name>`.
5. No accounts are set up. The CLI's own login is used.

The project is the directory the CLI will act on: the `--cwd` value, a path
argument such as `vercel deploy ./site`, or the current directory. Its team
comes from `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` when both are set, otherwise
from `.vercel/project.json`, otherwise from the matching project in the nearest
`.vercel/repo.json`.

### Map projects to accounts

A mapping ties a Vercel team to an account, so projects in that team always use
the right login, even after you switch the default.

- **New links**: mapped automatically. When a command links a project to a
  team that has no mapping, such as `vercel link` or a first `vercel deploy`,
  the team is mapped to the account that ran it.
- **Existing links**: never mapped for you. In an already linked project,
  `vercel` prints a hint instead. Run `vercelacc map <name>` in that folder.
- **Token commands**: never mapped. A login from `--token` or
  `VERCEL_TOKEN` says nothing about which account owns the team.

Use `vercelacc unmap` in a project folder to remove its mapping.

## Command reference

All `vercelacc` commands and the arguments each one takes:

| Command | What it does |
| --- | --- |
| `vercelacc <name>` | Switch the default account in every terminal. |
| `vercelacc <name> <args>` | Run one `vercel` command as `<name>`. |
| `vercelacc add <name>` | Log in an account. Also re-logs an expired one. |
| `vercelacc add <name> --existing` | Name the CLI's own login `<name>`. |
| `vercelacc use <name>` | Same as `vercelacc <name>`. |
| `vercelacc shell <name>` | Use `<name>` in this terminal only. `-` clears it. |
| `vercelacc map <name>` | Map this folder's linked team to `<name>`. |
| `vercelacc unmap` | Remove this folder's team mapping. |
| `vercelacc list` | List accounts. `*` marks the default. |
| `vercelacc whoami` | Show the Vercel user behind every account. |
| `vercelacc current` | Show the account `vercel` uses here, and why. |
| `vercelacc remove <name> [--force]` | Log out and delete an account. |
| `vercelacc version` | Print the installed version. |

Account names use letters, digits, `.`, `_` and `-`, must not start with `.`
or `-`, and must not match a command name.

## Caveats and safety rules

Keep these behaviors in mind when you use more than one account:

- **`vercel login` and `vercel logout`**: blocked once accounts exist, since
  they would act on whichever account was picked. Use `vercelacc add` and
  `vercelacc remove` instead.
- **`VERCEL_TOKEN`**: when it is set, it overrides the chosen login. The
  wrapper prints a warning.
- **Removing a `--existing` account**: this logs out the base CLI too, because
  both share one session. The CLI's config directory itself is left in place.
- **Failed logout**: `remove` keeps the account. Add `--force` to delete it
  anyway.
- **Team selection**: `vercel switch` stores the team in each
  account's own `config.json`.
- **Renaming an account**: move its directory under
  `~/.config/vercel-accounts/accounts`, then run `vercelacc map <new-name>` in
  each mapped project. Mappings live in `~/.config/vercel-accounts/orgs`.

## Change and reinstall vercelacc

Edit `vercelacc.sh` in this folder, never the installed copy, then:

```sh
make lint       # bash -n, zsh -n, sh -n, plus ShellCheck when installed
make test       # fake Vercel CLI in bash and zsh, plus install.sh checks
make install    # copy the new version into place
source ~/.zshrc
```

The tests use a temporary `HOME` and a fake `vercel` binary, so they never touch
real logins. Set `VERCELACC_TEST_SHELLS="zsh"` to test one shell. Bump
`VERCELACC_VERSION` in `vercelacc.sh` when behavior changes.

The script relies on these Vercel CLI behaviors. Recheck them after major CLI
upgrades:

- `--global-config <dir>` is accepted on every command and holds `auth.json`
  and `config.json`.
- `vercel login --global-config <dir>` saves the login into `<dir>`.
- `--token` and `VERCEL_TOKEN` bypass the saved login.
- `.vercel/project.json` and `.vercel/repo.json` store the linked `orgId`.
