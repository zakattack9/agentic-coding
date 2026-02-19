---
name: ralph-plan
description: Interactively generate a PRD and task list for a Ralph Loop — invoke to plan a feature before running ralph.sh
---

# Ralph Plan — Interactive PRD & Task List Generator

You are helping the user plan a feature for execution by the Ralph Loop. Your goal is to produce two artifacts:

1. **`ralph/prd.md`** — A complete requirements specification
2. **`ralph/tasks.json`** — A task list with right-sized user stories

---

## Prerequisite Check

First, check if `ralph/` directory exists in the project root. If it does not:

> The `ralph/` directory doesn't exist yet. Run `ralph-init.sh` first to set up the project structure, then invoke `/ralph-plan` again.

Stop here if the directory doesn't exist.

---

## Determine Mode

Read `ralph/prd.md`. Determine which mode to use:

### Mode 1: Full Planning (prd.md is empty or template scaffold)

If prd.md contains only the template scaffold (section headers with HTML comments, no real content), use full planning mode:

1. **Ask clarifying questions** — Ask as many questions as needed until the requirements are clear. No fixed limit. Focus on:
   - What problem are we solving? Who is the user?
   - What is the core functionality?
   - What are the explicit scope boundaries (non-goals)?
   - What is the technical context (stack, existing patterns, key file paths)?
   - What constraints must be respected?
   - What does success look like?
   - Continue asking until you are confident the specification is complete

2. **Generate `ralph/prd.md`** — Fill in all relevant sections following the PRD template structure:
   - Summary, Problem Statement, Goals, Non-Goals
   - Background & Context (architecture, key files, patterns)
   - Technical Design (only relevant subsections)
   - Constraints (cross-cutting invariants)
   - Edge Cases & Error Handling (if applicable)
   - Risks & Mitigations (if applicable)
   - Open Questions (if any remain)

3. **Derive `ralph/tasks.json`** — Break requirements into user stories (see Task Derivation Rules below)

4. **Present both files** for user review before writing them

### Mode 2: Task Derivation (prd.md already has content)

If prd.md already contains real requirements content:

1. **Read existing `ralph/prd.md`** thoroughly
2. **Ask targeted questions** only if requirements are ambiguous or incomplete
3. **Derive `ralph/tasks.json`** from the specification (see Task Derivation Rules below)
4. **Present tasks** for user review before writing

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
- Ask the user if you're unsure which commands to include

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

- **Do not write files until the user approves** — Present your draft of prd.md and tasks.json, get confirmation, then write
- **prd.md should be human-readable** — Write for a developer who will read it cold
- **tasks.json should be machine-parseable** — Ensure valid JSON with all required fields
- **Story IDs** use the format `US-001`, `US-002`, etc.
- **Branch name** should follow `ralph/<feature-name>` convention
