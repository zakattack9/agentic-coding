---
name: ralph-plan
description: Interactively generate a PRD and task list for a Ralph Loop — invoke to plan a feature before running ralph.sh
allowed-tools: Bash(ls:*), Bash(cat:*), Read, Write, AskUserQuestion
---

# Ralph Plan — Interactive PRD & Task List Generator

You are helping the user plan a feature for execution by the Ralph Loop. Your goal is to produce two artifacts:

1. **`.ralph/prd.md`** — A complete requirements specification
2. **`.ralph/tasks.json`** — A task list with right-sized user stories

---

## Prerequisite Check

!`echo "--- Ralph Status ---" && if [ -d .ralph ]; then echo "RALPH_DIR: installed"; else echo "RALPH_DIR: MISSING"; fi && if [ -f .ralph/templates/prd-template.md ]; then echo "TEMPLATES: installed"; else echo "TEMPLATES: MISSING"; fi && if [ -f .ralph/prd.md ]; then echo "PRD: exists ($(wc -l < .ralph/prd.md | tr -d ' ') lines)"; else echo "PRD: MISSING"; fi && if [ -f .ralph/tasks.json ]; then echo "TASKS: exists"; else echo "TASKS: MISSING"; fi`

Evaluate the status output above:

- If **RALPH_DIR is MISSING**: Tell the user to run `/ralph-install` first, then `/ralph-init --name my-feature`, then `/ralph-plan` again. **Stop here.**
- If **TEMPLATES is MISSING**: Tell the user to run `/ralph-install` to restore templates. **Stop here.**
- If **PRD is MISSING** or **TASKS is MISSING**: Tell the user to run `/ralph-init --name my-feature` to initialize state files, then `/ralph-plan` again. **Stop here.**
- If all checks pass: proceed to Determine Mode.

---

## Determine Mode

!`cat .ralph/prd.md 2>/dev/null`

Read the prd.md content above to determine which mode to use:

### Mode 1: Full Planning (prd.md is empty or template scaffold)

If prd.md contains only the template scaffold (section headers with HTML comments, no real content), use full planning mode:

1. **Gather requirements via AskUserQuestion** — Use the `AskUserQuestion` tool to ask clarifying questions. Ask as many rounds as needed — there is no limit. Do NOT proceed until you are confident the specification is complete. Focus on:
   - What problem are we solving? Who is the user?
   - What is the core functionality?
   - What are the explicit scope boundaries (non-goals)?
   - What is the technical context (stack, existing patterns, key file paths)?
   - What constraints must be respected?
   - What does success look like?
   - Use `AskUserQuestion` again for follow-ups. Keep asking until every ambiguity is resolved and you have enough detail to write a spec that another developer could implement without further questions.

2. **Generate `.ralph/prd.md`** — Fill in all relevant sections following the PRD template structure:
   - Summary, Problem Statement, Goals, Non-Goals
   - Background & Context (architecture, key files, patterns)
   - Technical Design (only relevant subsections)
   - Constraints (cross-cutting invariants)
   - Edge Cases & Error Handling (if applicable)
   - Risks & Mitigations (if applicable)
   - Open Questions (if any remain)

3. **Derive `.ralph/tasks.json`** — Break requirements into user stories (see Task Derivation Rules below)

4. **Present both files for review** — Use `AskUserQuestion` to present your draft of prd.md and tasks.json and ask the user to approve, request changes, or add missing requirements. Iterate until the user confirms both artifacts are ready.

### Mode 2: Task Derivation (prd.md already has content)

If prd.md already contains real requirements content:

1. **Read existing `.ralph/prd.md`** thoroughly (already loaded above)
2. **Clarify gaps via AskUserQuestion** — If requirements are ambiguous, incomplete, or could be interpreted multiple ways, use `AskUserQuestion` to resolve them. Do not guess.
3. **Derive `.ralph/tasks.json`** from the specification (see Task Derivation Rules below)
4. **Present tasks for review** — Use `AskUserQuestion` to present the task list and ask the user to approve or request changes. Iterate until confirmed.

---

## Task Derivation Rules

Apply these rules when creating the task list in both modes:

### Story Sizing
- Each story must be completable in **one ralph iteration** (one context window)
- Rule of thumb: if you can't describe the change in 2-3 sentences, it's too big — split it
- Prefer more small stories over fewer large ones

### Story Ordering
- Order by dependency: schema/database → backend logic → API routes → frontend components → integration/summary views
- Set `dependsOn` explicitly when story order matters beyond priority number
- Lower priority numbers execute first

### Acceptance Criteria
- Every story gets **verifiable** acceptance criteria
- Be specific: "Filter dropdown has options: All, Active, Done" not "works correctly"
- Include both positive and negative cases where relevant

### Verify Commands
- Populate `verifyCommands` from the project's existing test/lint/typecheck commands
- Use `AskUserQuestion` if you're unsure which commands to include

### Initial State
All stories must start with:
```json
{
  "passes": false,
  "reviewStatus": null,
  "reviewCount": 0,
  "reviewFeedback": ""
}
```

### tasks.json Structure
```json
{
  "project": "<project name>",
  "branchName": "ralph/<feature-name>",
  "description": "<brief description>",
  "verifyCommands": ["<test command>", "<lint command>"],
  "userStories": [
    {
      "id": "US-001",
      "title": "<short title>",
      "description": "<what to implement>",
      "acceptanceCriteria": ["<specific, verifiable criterion>"],
      "priority": 1,
      "passes": false,
      "reviewStatus": null,
      "reviewCount": 0,
      "reviewFeedback": "",
      "notes": "",
      "dependsOn": []
    }
  ]
}
```

---

## Important Notes

- **Do not write files until the user approves** — Always use `AskUserQuestion` to get explicit confirmation before writing prd.md and tasks.json
- **Use AskUserQuestion liberally** — It is better to ask one too many questions than to produce an incomplete or incorrect spec. The ralph loop cannot ask for clarification mid-execution, so the plan must be airtight before it starts.
- **prd.md should be human-readable** — Write for a developer who will read it cold
- **tasks.json should be machine-parseable** — Ensure valid JSON with all required fields
- **Story IDs** use the format `US-001`, `US-002`, etc.
- **Branch name** should follow `ralph/<feature-name>` convention
