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

1. **Discover the candidates.** Skill-manager runs out of exactly one marketplace repo, so gather the options first:
   - **Already registered?** Read `~/.claude/plugins/known_marketplaces.json` — if the user already runs a marketplace, its `source` slug is a strong hint for the repo they mean.
   - **Existing local checkouts** that are already marketplaces — search for `marketplace.json` in the user's code dirs. A repo's file lives at `<repo>/.claude-plugin/marketplace.json`, so the repo root is two levels up. Exclude managed clones and dependencies:
     ```bash
     find ~ -maxdepth 6 -name marketplace.json \
       -not -path '*/.claude/*' -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null
     ```
     Narrow the root (e.g. the current repo's parent dir) if `~` is too broad. **Treat every hit as a separate candidate — never assume the first/only one is right.**
   - **The current project** (cwd), if it's a git repo — it can be initialized into a marketplace even with no `marketplace.json` yet.
   - Optionally `gh repo list <owner> --limit 100` to surface an intended skills repo that isn't cloned locally.
   For each candidate, note its path, its `origin` slug (`git -C <path> remote get-url origin`), and whether it already has a `marketplace.json`.

2. **Always confirm the target with the `AskUserQuestion` tool — never skip this, even with a single candidate.** This is the one repo every skill is published to and that skill-manager operates out of, so the user must pick it explicitly. Offer:
   - each discovered candidate as an option, labelled with its `owner/name` **and** local path so the choice is unambiguous (if more than ~3 were found, keep the most likely and let the auto-added "Other" cover the rest);
   - a **"New / different repo"** option for publishing to a fresh or other repo — the user gives the `owner/name`; if it doesn't exist yet and `gh` is available, offer `gh repo create <owner>/<name> --private`, otherwise have them create it on GitHub first.
   If several `marketplace.json` files were found, list them all as distinct options — do not choose one for the user.

3. **Initialize the chosen repo:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" init --path <checkout> [--repo owner/name]
   ```
   - Existing checkout: `--path` alone is enough (slug auto-detected from origin; layout inferred from any `marketplace.json`).
   - New repo: pass `--repo owner/name` and a `--path` to clone into — init clones it, writes + pushes a `marketplace.json`, and registers it.
   - Add `--plugins-dir <dir>` only if auto-detection is wrong (`.` for repo-root plugins; inferred for a monorepo). Add `--user-plugins a,b` to enable specific plugins for every project.
4. Report what init did (config written, marketplace created/registered) and surface any push-failure WARNING — the repo needs a reachable `origin` to work from other machines.
5. Tell the user the optional last step: turn ON auto-update for the marketplace via `/plugin` → Marketplaces so new sessions pick up changes automatically (otherwise they refresh on demand). Then `/reload-plugins`.

After init, `/skill-manager:status`, `:configure`, `:push`, and `:remove` work in every project. To create the first skill, use the native **skill-creator** skill, then `/skill-manager:push` it.

## Output

Fill this skeleton from the engine's output, copying values verbatim. Drop a line if it doesn't apply:

**Configured:** repo `{owner}/{repo}` · marketplace `{name}` · plugins in `{pluginsDir}`
**Marketplace:** {created & pushed / already present} · {registered / register manually: `/plugin marketplace add {owner}/{repo}`}
**⚠️ Push failed:** {verbatim WARNING}
**Next:** (optional) turn on auto-update via `/plugin` → Marketplaces, then `/reload-plugins`.
**Then:** author a skill with the **skill-creator** skill → publish with `/skill-manager:push` → enable per project with `/skill-manager:configure`.
