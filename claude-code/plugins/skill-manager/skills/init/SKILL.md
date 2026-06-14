---
name: init
description: One-time setup for skill-manager — point it at your local checkout of a marketplace repo, register the marketplace, and optionally enable plugins for all projects. Use the first time the user sets up skill-manager, or when they say "set up skill manager", "configure my skills marketplace", or status reports it's not configured. Run once per machine.
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *) Bash(gh *) AskUserQuestion
argument-hint: "[--repo owner/name] [--path <checkout>]"
---

# Initialize skill-manager (one-time)

Wire skill-manager to the GitHub repo where the user keeps their skills. It operates on their existing local checkout — no second clone — adapts to any layout (plugins at the repo root, or nested in a monorepo), and on a brand-new repo it bootstraps the marketplace for them. This repo is where **every** skill gets published, so always confirm exactly which one with the user before initializing — never auto-pick.

## Steps

1. **Enumerate the existing skills repos on this machine.** Skill-manager runs out of exactly one marketplace repo. Gather every existing candidate first:
   - **Already registered?** Read `~/.claude/plugins/known_marketplaces.json` — if the user already runs a marketplace, its `source` slug is a strong hint for the repo they mean.
   - **Existing local checkouts** that are already marketplaces — search for `marketplace.json` in the user's code dirs. A repo's file lives at `<repo>/.claude-plugin/marketplace.json`, so the repo root is two levels up. Exclude managed clones and dependencies:
     ```bash
     find ~ -maxdepth 6 -name marketplace.json \
       -not -path '*/.claude/*' -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null
     ```
     Narrow the root (e.g. the current repo's parent dir) if `~` is too broad. **Treat every hit as a separate candidate — never assume the first/only one is right.**
   - **The current project** (cwd), if it's a git repo — it can be turned into a marketplace even with no `marketplace.json` yet.
   For each candidate, note its path and `origin` slug (`git -C <path> remote get-url origin`).

2. **Ask the user to choose with the `AskUserQuestion` tool — always, even with one or zero candidates.** This is the single repo every skill is published to, so never auto-pick. Present two categories of options:
   - **Use an existing repo** — one option per repo from step 1, labelled with its `owner/name` **and** local path. List them all (if more than ~3, keep the most likely and let the auto-added "Other" cover the rest).
   - **Create a new repo** — one option, for when the user wants a fresh dedicated skills repo.

3. **If they picked an existing repo**, initialize it:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" init --path <checkout>
   ```
   The slug is auto-detected from `origin`; the layout is inferred from any `marketplace.json`.

4. **If they chose "Create a new repo", create it on their behalf.** Follow up with `AskUserQuestion` to get:
   - the **repo name** (e.g. `my-skills`);
   - **where to store it on disk** — offer common spots (their Desktop, home dir, alongside their existing repos / the current project's parent) plus "Other" for a custom path or a described place ("on my desktop" → `~/Desktop`). Resolve the answer to a concrete `<parent>/<name>`.

   Then create and initialize it:
   ```bash
   gh repo create <name> --private              # creates <your-login>/<name> on GitHub (empty)
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" init --repo <login>/<name> --path <parent>/<name>
   ```
   `init` clones the empty repo into `<parent>/<name>`, bootstraps + pushes its `marketplace.json`, and registers it. Capture `<login>/<name>` from the `gh repo create` output (or `gh api user --jq .login`). If `gh` is missing or not authenticated, have the user create the empty repo on GitHub themselves, then run the same `skillctl init --repo <owner>/<name> --path <parent>/<name>`. If the repo already exists on GitHub but isn't cloned, skip `gh repo create`.

5. **Optional flags (either path):** add `--plugins-dir <dir>` only if auto-detection is wrong (`.` for repo-root plugins; inferred for a monorepo), and `--user-plugins a,b` to enable specific plugins for every project. Then report what init did and surface any push-failure WARNING — the repo needs a reachable `origin` to work from other machines.
6. Tell the user the optional last step: turn ON auto-update for the marketplace via `/plugin` → Marketplaces so new sessions pick up changes automatically (otherwise they refresh on demand). Then `/reload-plugins`.

After init, `/skill-manager:status`, `:configure`, `:push`, and `:remove` work in every project. To create the first skill, use the native **skill-creator** skill, then `/skill-manager:push` it.

## Output

Fill this skeleton from the engine's output, copying values verbatim. Drop a line if it doesn't apply:

**Configured:** repo `{owner}/{repo}` · marketplace `{name}` · plugins in `{pluginsDir}`
**Marketplace:** {created & pushed / already present} · {registered / register manually: `/plugin marketplace add {owner}/{repo}`}
**⚠️ Push failed:** {verbatim WARNING}
**Next:** (optional) turn on auto-update via `/plugin` → Marketplaces, then `/reload-plugins`.
**Then:** author a skill with the **skill-creator** skill → publish with `/skill-manager:push` → enable per project with `/skill-manager:configure`.
