# claudeo

Launch local Claude Code sessions with different Claude subscription logins,
including two accounts running at the same time. A small POSIX shell wrapper for
macOS and Linux; version `0.2.0`, with no runtime package dependencies.

Each name selects its own stable `CLAUDE_CONFIG_DIR`. Claude Code handles browser
authentication, credential storage, and refresh. `claudeo` never reads, copies,
prints, or manages tokens, credential files, or Keychain entries.

**Familiar customizations, separate logins:** new accounts link selected settings,
instructions, skills, and hooks from your main `~/.claude` directory by default.
Credentials, account metadata, plugin installations, history, and sessions stay
separate. Use `--isolated` when creating an account to skip customization sharing.
Existing accounts are never silently migrated on upgrade.

## Install

Prerequisites: current Claude Code with `claude auth login --claudeai`,
`claude auth status`, and `claude auth logout`; POSIX `sh` and standard macOS/Linux
utilities. Installation and verification use `make`; ShellCheck is optional.
The real-binary smoke test should be run with your installed Claude version.

From this repository:

```sh
cd claude-code/tools/claudeo
make lint
make test
make install PREFIX="$HOME/.local"
```

Ensure `$HOME/.local/bin` is on your `PATH`. Installation does not edit shell
startup files. You can also run `bin/claudeo` directly from this directory.

## Two-account quick start

```sh
claudeo login personal --email personal@example.com
claudeo login work --email me@company.example

claudeo status personal
claudeo status work

# Terminal 1: in any project directory
claudeo personal

# Terminal 2: in the same or another project directory
claudeo work
```

Complete each browser flow with the **intended Claude account**, switching the
browser's signed-in account if needed. `--email` is a hint, not identity
verification. Check `claudeo status <name>` afterward; use `/status` inside the
session to confirm its effective authentication source. Browser login with two
real subscriptions is the manual acceptance step.

There is no global active-account switch: launching `work` does not switch an
already running `personal` session. Each subscription retains its own limits.
This tool does not rotate accounts or bypass limits. Two sessions editing the
same project still share its files; use separate worktrees when appropriate.

## Commands

```sh
claudeo init personal                     # Create private storage; no login
claudeo init --isolated independent       # No links to your main customizations
claudeo login --isolated independent      # Native login with isolated config
claudeo share personal                    # Explicitly migrate/refresh sharing
claudeo login work --sso                  # Native subscription SSO flow
claudeo run personal                      # Interactive session
claudeo run work -- -p "summarize this repository"
claudeo work --continue                   # Shorthand; forwards native arguments
claudeo status work                       # Native auth status --text
claudeo status work --json                # Native JSON, no wrapper stdout
claudeo path work                         # Absolute directory path only
claudeo list                              # Sorted names; no Claude/network calls
claudeo doctor                           # Read-only layout/binary checks
claudeo logout work                       # Native logout; directory remains
claudeo help
claudeo --version
```

`login` delegates to `claude auth login --claudeai`, accepts `--email <address>`
and `--sso`, and rejects `--console`. This is for Pro, Max, Team, and Enterprise
subscription accounts. **Anthropic profiles are a different mechanism**, used
for Console OAuth and workload identity federation, not subscription switching.

Only `init` and `login` create accounts. `run`, `status`, `logout`, `share`, and `path`
require an existing account. Names use 1–64 ASCII letters, digits, `.`, `_`, or
`-`, starting with a letter or digit. Case-only duplicates and inconsistent
casing are rejected on both platforms (macOS filesystems commonly ignore case).
Subcommand names take precedence over shorthand: use `claudeo run status` if
you intentionally named an account `status`.

The optional first `--` after the account is consumed; subsequent arguments are
passed unchanged. Native cwd, streams, terminal, exit status, and signals are
preserved using `exec`. Invalid wrapper invocations exit `2`. Native status exits
`0` when logged in and `1` when not; other native exit codes also pass through.
`run` is a transparent native-command launcher, not a command restriction layer:
the wrapper itself never invokes token-generation or credential-file commands.

## Storage and isolation

### Shared customizations

If your main configuration directory exists, newly created accounts symlink
these existing entries from it:

```text
settings.json   CLAUDE.md       keybindings.json
rules/          skills/        agents/           commands/
hooks/          output-styles/ statuslines/      themes/
```

Edits to the main files are visible to both accounts on the next load. These
are ordinary writable symlinks: edits through an account can change the main
file too. Shared configuration is trusted code/configuration, not a read-only
overlay. Relative scripts/imports still need valid paths and dependencies.

Only this allowlist is linked. In particular, neither `.claude.json` nor
`.credentials.json`, managed/remote settings, plugin storage, history, caches,
or session directories are shared. Global MCP registrations and their
authentication remain account-local; configure them through Claude normally.
Repository-scoped configuration is still loaded normally.

For an account created before `0.2.0`, or to pick up newly added customization
files/directories, run:

```sh
claudeo share personal
```

Conflicting account-local customizations are moved (not deleted) into a private
`.claudeo-config-backup.<random>` directory inside that account before linking.
Its location is reported on stderr. Repeating `share` with intact links is
idempotent. The command touches only allowlisted customization entries and its
own `.claudeo-sharing` marker; it never moves the account directory itself.
To restore a backed-up customization, unlink that individual shared entry and
move the corresponding backup entry back. No credential restoration is needed.

Some editors and native configuration commands replace a symlink with a new
regular file. `doctor` reports that sharing has drifted; run `share` again to
back up that local replacement and restore the link. Changing the shared source
does not remove old links for entries absent from the new source; review those
individually if changing sources. An absent default `~/.claude` directory simply
leaves a new account unlinked until you explicitly run `share`.

`--isolated` goes **before** the account name and skips sharing when the account
is first created. It does not remove existing shared links. Ordinary `init` or
`login` on an existing isolated account keeps it isolated.

### Plugins

Plugin enablement preferences are in shared `settings.json`, but installations
and marketplace registries remain separate. Install desired plugins through
Claude's CLI for each account; sharing the entire `plugins/` directory would
also couple its mutable state and configuration. For example:

```sh
claudeo personal plugin marketplace add anthropics/claude-plugins-official
claudeo personal plugin install frontend-design@claude-plugins-official --scope user
```

Review `/plugin` in the new account. Enabling/disabling a plugin may update
shared settings. For a migration, installing plugins **before** running `share`
preserves your main preferences and backs up the account's previous settings.
The wrapper does not parse plugin registries, install arbitrary plugins on
startup, or share plugin credentials.

### Private account storage

```text
${CLAUDEO_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/claudeo}/
└── accounts/
    ├── personal/         ← CLAUDE_CONFIG_DIR for personal
    │   └── anthropic/    ← ANTHROPIC_CONFIG_DIR for personal
    └── work/             ← CLAUDE_CONFIG_DIR for work
        └── anthropic/    ← ANTHROPIC_CONFIG_DIR for work
```

The default is `~/.config/claudeo/accounts/<name>`. The tool root, accounts root,
account directory, and its Anthropic directory are created with mode `0700`;
`init`/`login` also enforce those modes on existing directories. Claude manages
its credential-file permissions. Root/account/profile directory symlinks are
rejected; physical absolute paths are used consistently for account selection.

**Never rename or move account directories after login.** Their absolute paths
participate in macOS Keychain lookup. Keep storage overrides and ancestor paths
stable; do not retarget ancestor symlinks. To use a new location, initialize a
new account and complete a fresh login there. There is no migration or account
deletion command.

Advanced overrides:

- `CLAUDEO_HOME`: dedicated absolute tool-storage path, with no `.` or `..`
  components. Do not point it at an existing general-purpose directory; `init`
  enforces private permissions. Relative `XDG_CONFIG_HOME` is also rejected.
- `CLAUDEO_CLAUDE_BIN`: executable path or command name, defaulting to
  `command -v claude`. It is one executable, not a shell command or flags.
- `CLAUDEO_SHARED_CONFIG_DIR`: absolute main customization directory, default
  `$HOME/.claude`. It is used at account creation or explicit `share`, never
  inferred from ambient `CLAUDE_CONFIG_DIR`. Existing links keep their source
  until explicitly migrated. An explicit nonexistent source is an error.

Before launching Claude, the wrapper unsets these ambient variables in its
child environment only, including variables set to empty strings:

```text
ANTHROPIC_API_KEY             ANTHROPIC_AUTH_TOKEN
CLAUDE_CODE_OAUTH_TOKEN       CLAUDE_CODE_USE_BEDROCK
CLAUDE_CODE_USE_VERTEX        CLAUDE_CODE_USE_FOUNDRY
ANTHROPIC_PROFILE             ANTHROPIC_FEDERATION_RULE_ID
ANTHROPIC_ORGANIZATION_ID     ANTHROPIC_IDENTITY_TOKEN_FILE
ANTHROPIC_IDENTITY_TOKEN      ANTHROPIC_SERVICE_ACCOUNT_ID
ANTHROPIC_WORKSPACE_ID        ANTHROPIC_BASE_URL
```

It then sets both configuration directories. The account-local
`ANTHROPIC_CONFIG_DIR` prevents discovery of your usual active/default Anthropic
profile: unsetting `ANTHROPIC_PROFILE` alone would not isolate federation.
The wrapper does not create or inspect profiles or their credentials. Keep this
directory free of Console/federation configuration when using subscriptions.

Unrelated environment variables (including locale, terminal settings, proxies,
and Claude feature flags) remain intact; your parent shell is unchanged.

### Unexpected credential source

Run `claudeo doctor`, `claudeo path <name>`, and `claudeo status <name>`, then
`/status` in the selected session. Doctor warns about ambient overrides by
**name only**, prints the native version, and checks directory usability. It
does not authenticate, query every account, or read credential files. A missing
account root is a failed check; create one with `claudeo init <name>`.

This is ambient credential isolation, **not a security boundary against Claude
configuration**. Project/account/managed settings may inject an `env` value,
configure `apiKeyHelper`, or mandate a gateway. Explicit native arguments can
also change behavior. Review those settings through Claude's normal interfaces
if the effective source is unexpected; organizational policies remain in force.
The wrapper neither parses nor overrides settings, and cannot promise
subscription-only billing under arbitrary configuration. Bare mode is not a
substitute: it changes normal Claude behavior and authentication support.

Before sharing a source, check that its settings do not supply authentication
variables in `env`, an `apiKeyHelper`, or forced login/gateway settings. Do not
share such a source for subscription switching. This check remains your
responsibility: the dependency-free wrapper does not parse JSON or read secrets
from settings. Subsequent edits to shared settings affect every linked account.

## Verify, upgrade, and uninstall

```sh
make lint       # sh -n plus ShellCheck when installed (otherwise labeled skip)
make test       # Fake only: isolated HOME, storage, cwd; no real credentials
make smoke      # Opt-in real Claude: fresh account status must exit 1, --version

# After updating this repository, replace only the executable:
make install PREFIX="$HOME/.local"
make uninstall PREFIX="$HOME/.local"
```

To exercise another POSIX shell when installed, use
`CLAUDEO_TEST_SHELL=/bin/dash make test`.

Uninstall removes only `$PREFIX/bin/claudeo`; all account data remains. Tests
remove only their own temporary directories. The smoke test changes neither
existing logins nor the real Claude home, and does not open a browser. It reports
a skip if Claude is unavailable. There is no additional CI job because this
repository has no existing tool-specific shell-test workflow.

## Maintenance

Review the official [authentication and credential precedence documentation](https://code.claude.com/docs/en/authentication),
[CLI reference](https://code.claude.com/docs/en/cli-reference), and
[Anthropic profile directory resolution](https://platform.claude.com/docs/en/manage-claude/wif-reference#configuration-directory).
Keep the centralized sanitized-variable list current, then rerun lint, the fake
harness, and the real smoke test. Validate both browser logins manually after
authentication changes. Bump the version for CLI/storage-contract changes;
never automatically migrate account directories or add credential parsing.
