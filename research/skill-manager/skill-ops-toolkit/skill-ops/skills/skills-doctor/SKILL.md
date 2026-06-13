---
name: skills-doctor
description: Diagnose the centralized skills setup — config, repo clones, marketplace registration, user-scope enablement, and whether the installed marketplace clone has drifted behind the central repo. Use whenever skills aren't loading, a promoted skill isn't showing up, the marketplace seems stale, or the user asks to "check my skills setup", "why isn't my skill working", or "is my marketplace up to date".
allowed-tools: Bash(skillctl *) Bash(git *)
---

# Diagnose the skills setup

Run `skillctl doctor` and walk the user through any failures. Common fixes the tool will suggest:

- **Not configured** → run the bootstrap (`skillctl bootstrap --repo <owner/name>`).
- **Marketplace not registered** → `claude plugin marketplace add <owner/name>`.
- **Installed clone is behind** → `skillctl refresh` (this works around the known bug where `claude plugin update` fetches but doesn't merge, leaving the clone on an old commit), then `/reload-plugins`.
- **Auto-update is off** → third-party marketplaces default to off; turn it on via `/plugin` → Marketplaces → enable auto-update.
- **A skill isn't triggering** even though it's loaded → its description probably needs to be more specific; offer to improve it and sync the change up.

After fixes, suggest `/reload-plugins` or a new session.
