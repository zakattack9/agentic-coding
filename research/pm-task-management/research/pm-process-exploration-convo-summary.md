## Decision: GitHub Projects, not Linear/Jira

For a 4-engineer team (plus 1–2 occasional devs) where you're the PM actively steering the board with weekly reviews, Linear's per-seat cost buys you native automations that are mostly low-value at your scale — stale-issue flagging, time-based auto-transitions, cascading parent/child progress. You catch all of that in your weekly cadence or enforce it through process. GitHub Projects is free, lives in your repo, and lets you own the orchestration layer with Claude Code, which is where your real leverage is.

One correction to carry forward: earlier I kept calling your orchestration layer a "Cline plugin." That was my error — you're building a **Claude Code plugin with skills underneath it**. Worth fixing in any notes since it changes what docs/APIs you reference.

## Data model you're working with

In GitHub Projects, the **issue is the atomic unit**. Everything else is a view over issues: the **board** (Kanban) and the **roadmap** (timeline). Milestones group issues but give you no hierarchy, and there's no sprint primitive — just target dates. Linear's differentiators (cycles, projects, sub-issues) give you nesting and sprint structure you don't need given your mostly-parallel work with occasional same-team synchronized sprints.

## Roadmap capabilities and limits

Roadmap gives you target dates, a calendar/timeline view, milestone grouping, filtering by assignee/label/status, and visual flagging of past-due items. It does **not** give you dependency/critical-path modeling, auto-rescheduling of dependents, or burndown/velocity. Your stated need is narrow — set deadlines, see them on a calendar, surface what's behind — and roadmap covers the deadline + overdue visibility. The "behind schedule relative to plan" detection is the one thing it won't do natively; Claude Code has to compute that.

## Claude Code + Max plan billing (the part most likely to bite you)

The `anthropics/claude-code-action` is real and works on Pro/Max, triggered by `@claude` mentions, issue assignment, or explicit automation prompts. But the **June 15, 2026 billing split** is the hardening-critical detail: automated/Agent-SDK-style usage (which is what GitHub Actions runs are) draws from a **separate monthly credit pool** — roughly $20 Pro / $100 Max 5x / $200 Max 20x — that drains first, doesn't roll over, and once empty either bills at API rates (only if "extra usage" is toggled on) or **silently stops returning errors**. Interactive terminal/IDE use stays on your normal session limits, a separate meter.

For cost scale: one tracked dev's peak month would've been ~$5,623 at API rates (busiest day ~8,930 messages / 9 sessions). So a maxed Max plan is enormous value for interactive work, but **automation-heavy GitHub Actions pipelines can exhaust the $100/$200 credit fast**, after which you're on overages. If your auto-implementation loop runs frequently, model the token burn and consider direct API billing with prompt caching for the CI side.

## Issue lifecycle / linking

Link issue↔PR with `Closes #42` / `Fixes #42` in the PR; link branch via issue number in the branch name (`feature/42-user-auth`). GitHub then surfaces the full lifecycle on the issue page — branch, commits, PR, merge time. On PR merge, your Action updates the issue's status field to reflect pipeline position.

## Automation philosophy you settled on

Make the happy path frictionless, handle one-offs gracefully, don't over-rigidify:

- **Automate:** auto-assign to whoever moves an issue to In Progress; auto-link PRs to issues retroactively (detect issue number from branch name or PR title).
- **Don't bother automating:** branch and PR creation — it's ~2 seconds of muscle memory and the auto-versions are awkward (you can't open a PR without a commit; you'd end up with empty draft PRs).
- **Light enforcement only:** issue number somewhere in branch name or PR title, so automation has a match anchor.
- **Claude Code's real job here:** a reconciliation/report loop — periodically scan for orphaned PRs, orphaned branches, stale issues, and behind-schedule items; surface them in a weekly report rather than enforcing rigidly.

## Hardening considerations to design around

1. **Column-move → deploy is not a trivial trigger.** GitHub Projects has no native external-action automation. Moving a card fires `projects_v2_item` events, *not* `issues` events — these are more awkward to wire than a label change, and people often mirror project status to a label or drive it off PR-merge/status-field updates instead. Verify the exact event shape before you build the staging/prod deploy hooks; this is a common source of "why isn't my workflow firing."
2. **GitHub API rate limits** on your roadmap-scan loop — fine at daily/weekly cadence for a small team, but back off and batch if you scale frequency.
3. **Behind-schedule logic must live in your skill.** Roadmap only knows "past due." If you want "this slipped relative to the milestone / velocity," Claude Code computes it.
4. **Make auto-assign/auto-link idempotent** so re-runs (retries, replays) don't double-act or thrash assignees.
5. **Credit-aware automation.** Build in awareness of the monthly Agent SDK credit so a runaway loop doesn't either silently stop mid-pipeline or quietly rack up overages.

If it'd help the build, the natural next step is mapping each of these to concrete plugin skills (story-distiller, issue-syncer, reconciler/reporter, deploy-status-updater) and the GitHub Action triggers each one hangs off of — say the word and I'll lay that out.
