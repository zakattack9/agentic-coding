---
name: init
description: One-time setup for skill-manager — point it at your local checkout of a marketplace repo, register the marketplace, and optionally enable plugins for all projects. Use the first time the user sets up skill-manager, or when they say "set up skill manager", "configure my skills marketplace", or status reports it's not configured. Run once per machine.
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(git *)
argument-hint: "[--repo owner/name] [--path <checkout>]"
---

# Initialize skill-manager (one-time)

Wire skill-manager to the marketplace repo you author skills in. It operates on your existing local checkout — no second clone — and adapts to any layout (plugins at the repo root, or nested in a monorepo).

## Steps

1. Determine the marketplace repo and its local checkout:
   - If the user already has the repo cloned (common), use that path as `--path`. The repo slug is auto-detected from its `origin` remote.
   - If they don't, ask for the `owner/name` and a path to clone into.
2. Run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/bin/skillctl" init --path <checkout> [--repo owner/name]
   ```
   - Add `--plugins-dir <dir>` only if auto-detection is wrong (use `.` for plugins at the repo root). For a monorepo it's inferred from existing entries in `marketplace.json`.
   - Add `--user-plugins a,b` to enable plugins for every project at user scope.
3. Tell the user the one remaining manual step: turn ON auto-update for the marketplace (third-party marketplaces default off) via `/plugin` → Marketplaces, then `/reload-plugins`.

After init, `/skill-manager:status`, `:configure`, `:push`, and `:remove` work in every project.
