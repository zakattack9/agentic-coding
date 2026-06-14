---
name: init
description: One-time setup for skill-manager — point it at your local checkout of a marketplace repo, register the marketplace, and optionally enable plugins for all projects. Use the first time the user sets up skill-manager, or when they say "set up skill manager", "configure my skills marketplace", or status reports it's not configured. Run once per machine.
disable-model-invocation: true
model: sonnet
effort: medium
allowed-tools: Bash(python3 *) Bash(git *) Bash(gh *)
argument-hint: "[--repo owner/name] [--path <checkout>]"
---

# Initialize skill-manager (one-time)

Wire skill-manager to the GitHub repo where the user keeps their skills. It operates on their existing local checkout — no second clone — adapts to any layout (plugins at the repo root, or nested in a monorepo), and on a brand-new repo it bootstraps the marketplace for them.

## Steps

1. Figure out which repo and checkout to use:
   - **Already has a skills/marketplace repo** (common, including a monorepo): use that local checkout path as `--path`. The repo slug is auto-detected from its `origin` remote; the layout is inferred from any existing `marketplace.json`.
   - **Starting from scratch**: they need an empty GitHub repo first. If `gh` is available, offer to create one (`gh repo create <owner>/<name> --private`). Then init with `--repo <owner/name>` (and a `--path` to clone into) — init clones it, writes + pushes a `marketplace.json`, and registers it.
2. Run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" init --path <checkout> [--repo owner/name]
   ```
   - Add `--plugins-dir <dir>` only if auto-detection is wrong (use `.` for plugins at the repo root; for a monorepo it's inferred from existing entries).
   - Add `--user-plugins a,b` to enable specific plugins for every project at user scope.
3. Report what init did (config written, marketplace created/registered) and surface any push-failure WARNING — the repo must have a reachable `origin` for the marketplace to work from other machines.
4. Tell the user the optional last step: turn ON auto-update for the marketplace via `/plugin` → Marketplaces so new sessions pick up changes automatically (otherwise they refresh on demand). Then `/reload-plugins`.

After init, `/skill-manager:status`, `:configure`, `:push`, and `:remove` work in every project. To create the first skill, use the native **skill-creator** skill, then `/skill-manager:push` it.
