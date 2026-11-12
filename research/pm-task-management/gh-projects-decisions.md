# gh-projects decision log

Binding owner rulings for the gh-projects plugin and the Zilarent Task Board. Read this first. To change a ruling, add a new entry that names the one it supersedes; never edit an old entry.

## 2026-11-11: make the Zilarent Task Board usable first

Context: the 2026-11-02 audit found the plugin passes its offline tests but its core board reads and field writes fail on real GitHub. The owner set the goal: make the Zilarent Task Board usable as soon as possible, managed through Claude skills.

1. **Goal.** Build a standard workflow for every developer on `Zilarent/cars.bdv`. Product managers load new tickets through Claude. Developers pick up and work tickets through Claude. The board must reflect true ticket state. Humans should not add or configure tickets by hand in the board UI, because the many ticket fields make mistakes easy.
   Owner's words: "What I am trying to avoid is humans going into the board and manually adding tasks because this is cumbersome and due to the tickets options it is easy for a human to miss or misconfigure the different parameters on each ticket."
2. **Fix the existing plugin.** Fix whatever is broken so the board can be used efficiently; do not replace the plugin with new lean skills or an MCP server.
3. **Backfill source is free-form text.** The backfill imports no GitHub issues and no other board software. Input is unstructured text (Slack messages, Obsidian notes, other text files) that Claude analyzes and turns into proper tickets.
4. **Text input method.** Product managers paste text or point Claude at files or folders. No live Slack or Obsidian connector in the first release.
5. **Repo scope.** The board covers `Zilarent/cars.bdv` only.
6. **Sign-in.** Manual board work through Claude runs as each developer's own `gh` login. This replaces the App-token-only rule for interactive skill writes. GitHub Actions robots still use the App token.
7. **Card robots.** Ship the PR robot (`board-sync`: push to a ticket branch moves the card to In Progress; opening a PR moves it to In Review) in the first release. Defer the deploy robot (`board-status`). In the meantime, the board's built-in "PR merged" rule sets On Staging, and Claude moves shipped cards to Done in bulk after each prod release.
8. **Deferred.** Agentic development of tickets (Claude implementing tickets on its own as they move across the board) is fully deferred.
9. **Skill standards.** Rework the skills to current skill-authoring standards where needed, since the plugin was last worked on months ago.

## 2026-11-11 (later): tickets are a state ledger; board tooling moves to cars.bdv

1. **Ticket shape.** Supersedes the spec-ops delegation in the plugin. spec-ops is retired. Tickets separate tracking from development: each ticket is a state ledger of what needs doing and what was done, with the base details of what is required, not a full spec. Developers implement however they choose and ask whoever they need for more detail. The GitHub issue number is the ticket ID; PM-IDs and T3 deep-spec files are dropped.
   Owner's words: "The ticket mainly needs to be a State ledger for the work that needs to be done and what was done, and much less of how it should be implemented."
2. **Card states for the cars.bdv two-PR flow.** Push to a ticket branch: In Progress. PR opened: In Review. PR into `staging` merged: On Staging. PR into `main` merged: Done, and the issue closes.
3. **Drafts.** When a PM turns free-form text into tickets, Claude shows the drafts in the session; the PM edits and approves; Claude then creates the issues. No local draft files.
4. **Repo scope.** Confirms entry 5 above: the board serves `Zilarent/cars.bdv` only, and the tooling may be scoped down to that repo.
5. **Where the code lives.** Supersedes entry 2 above ("fix the existing plugin"). The owner approved moving only what is needed into `cars.bdv`, mapping how the existing board is set up, and adding scripts and checks that prove the board has every configuration it needs, if Claude judged this the best plan. Claude judged it best: repo-specific automation belongs in that repo, `cars.bdv` already shares Claude skills under `.claude/skills/`, the robot workflow must live there anyway, and `agentic-coding` is public. Decided by Claude, needs your review.
6. **The gh-projects plugin stays, frozen.** Once the `cars.bdv` board tooling is live, `gh-projects` stays in `agentic-coding` and the marketplace with a note pointing to `cars.bdv`. No further fixes go into the plugin.

## 2026-11-11 (final round): scope, board shape and cleanup

1. **kanban/ stays.** Supersedes the open question of the board replacing `cars.bdv`'s `kanban/` folder. Both run in parallel: `kanban/` may stay the developers' own working notes, and the GitHub board is the team's high-level ticket ledger. The owner briefs the engineering team. Migrating `kanban/` cards to the board is out of scope.
   Owner's words: "we should only be focused on creating the projects board and ensuring we have all the necessary tools and things configured so that product managers like me and developers can use the board immediately after the work here is done."
2. **No import.** The board starts fresh; no `kanban/` cards are imported. Backfill is free-form text only (decision 3 of the first entry).
3. **Who does what.** Approved as proposed. Agents (Claude skills run by a PM or developer) turn free text into tickets with every field filled, split work into parent and child tickets, set blocked-by links, order the backlog, plan sprints, report gaps, and fix tickets whose state lags. PMs approve drafts, order and priority, and answer questions by updating tickets. Developers take the top Ready ticket or an assigned one, build it however they choose, and the robot moves the card.
4. **Ticket body.** Enough for a developer or an agent to start without a meeting: What, Why, Done when (checklist), Details and links, Not included, Open questions, Source. No implementation plan.
5. **Board #27 fields.** Keep Status, Type (org issue type), Priority (org issue field, P0 to P3), Size, Sprint, Start date and Target date (org issue fields), Assignees, Parent issue, and native blocked-by links. Add an Area field (Backend, Admin UI, Public site, Infra, Data). Delete Tier, PM-ID, Spec, Schedule health, Slippage, Slippage days, Blast radius, Blast count, Blocked, Impact level and Decision needed. Template #25 ("Delivery Board Template") stays untouched as the plugin's original board.
6. **Health is computed, never stored.** A no-AI script inside the plan and report skills computes overdue, at risk, blocked, days late, blocks-how-many, stale, not ready and sprint overload on every run. Nothing is written back to the board.
7. **Board #27 views.** Delete Blockers and Triage. Strip deleted fields and Milestone from the other views. Ready has no sort so the agent-set order shows. Epics sorts by Target date. Sprint filters to the current sprint. Add Area where useful. Insights charts have no API and are checked by hand once.
8. **Ticket link.** Script it: a start-ticket helper creates a linked branch named `<type>/<issue#>-<slug>`, assigns the developer and moves the card to In Progress; an open-PRs helper opens the `staging` PR and the `main` PR, with `Closes #<issue#>` in the `main` PR. The robot accepts a linked branch or the number in the branch name, and comments on any PR with no ticket. The free plan has no branch protection, so nothing blocks a merge.
9. **Sprints.** Two-week sprints starting Monday. Sprint 7 starts Monday 2026-11-16.
10. **CLAUDE.md.** Add a short "GitHub Task Board" section to `cars.bdv`'s `CLAUDE.md`: both trackers exist, `kanban/` rules are unchanged, the board is the high-level ledger, and the board skills are named. No migration wording.
11. **Cleanup done 2026-11-11, owner-approved.** Deleted 25 fake test issues in `cars.bdv` (#188 to #211 and #220; the earlier count of 22 was wrong, the approved ranges were exact), 3 fake milestones (v1.0, v1.1, v1.2), issue #576 "Fix something", and boards #23, #29, #30, #31, #32, #33, #34, #35 and #36. Repo variables `GH_PROJECT_NUMBER` and `GH_PROJECT_URL` now point at #27. Board #7 (closed old template) is kept.

## 2026-11-11 (build session): board #27 view choices and the first apply

1. **Ready view has no grouping.** The Priority grouping is removed so the agent-set order is one list and the top row is the next ticket. Owner's answer: "No grouping (Recommended)".
2. **Roadmap groups by Area**, replacing Milestone. Owner's answer: "Area (Recommended)".
3. **First apply approved.** The owner approved the exact 20-change plan from `check_board.py` (create Area, delete the 11 fields, add Sprints 7 to 10, delete Blockers and Triage, update five views in place). Owner's answer: "Yes, apply (Recommended)".
4. **Board access.** The three non-owner org members get Write on board #27; org owners already administer every org board. Owner's answer: "Yes, grant Write (Recommended)".
5. **Sprint capacity is in points: S=1, M=2, L=4.** The plan-sprint skill asks for the points per sprint once and saves it in `tools/board/board.json`. Owner's answer: "Points S=1 M=2 L=4 (Recommended)".
6. **Health thresholds.** Stale: In Progress or In Review with no update for 5 days. At risk: Target date within 3 days and not yet In Review, or blocked with Target date within 7 days. Kept in `board.json`. Owner's answer: "Stale 5 days, at risk 3 days (Recommended)".
