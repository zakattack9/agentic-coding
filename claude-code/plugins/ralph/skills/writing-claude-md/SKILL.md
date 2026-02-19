---
name: writing-claude-md
description: Guidelines for writing effective CLAUDE.md files and .claude/rules/ — invoke when creating or editing CLAUDE.md or rule files
---

# Writing CLAUDE.md and Rules for This Project

---

## Core Principles

1. **Less is more** - Keep root CLAUDE.md under 100 lines. Claude Code's system prompt uses ~50 instructions; models reliably follow ~150-200 total. Every instruction in CLAUDE.md competes for that budget.

2. **Universal applicability** - If it only applies sometimes, make it a scoped rule. As instruction count increases, quality degrades uniformly across ALL instructions.

3. **Map, not territory** - Point to docs with `@path/to/file`, don't embed them. Prefer `file:line` references over code snippets.

4. **Be specific** - "Use `bun` not `npm`" not "use the right tool"

5. **Claude learns from codebase** - Skip code style rules. Claude is an in-context learner and will follow existing patterns in the codebase.

---

## Root CLAUDE.md Structure

```markdown
# Project Name

One-line description.

## Stack
- Runtime, framework, database

## Structure
- `src/` - what it contains
- `tests/` - what it contains

## Commands
- Build: `command`
- Test: `command`
- Lint: `command`

## Key Patterns
- [2-3 max, universally applicable]

## See Also
- @docs/topic.md for details
```

---

## When to Use Rules vs Root CLAUDE.md

| Root CLAUDE.md     | `.claude/rules/`         |
| ------------------ | ------------------------ |
| Universal context  | Topic-specific           |
| Essential commands | File-type conventions    |
| Project structure  | Conditional instructions |

---

## Rule File Structure

```
.claude/rules/
├── api-design.md        # No paths = always loaded
├── testing.md
└── frontend/
    └── react.md         # Subdirectories supported
```

### Rule File Naming

- Use lowercase with hyphens: `api-design.md`, `database-migrations.md`
- Name should indicate scope/topic at a glance
- One topic per file; if name needs "and", split it

### Path Scoping

```yaml
---
paths:
  - "src/api/**/*.ts"
---
```

**Use often** to properly scope rules to specific directories or file types. This leads to shorter rule files (less context bloat) and pinpoint accurate guidance.

### Patterns

| Pattern             | Matches               |
| ------------------- | --------------------- |
| `**/*.ts`           | All .ts files         |
| `src/**/*`          | Everything under src/ |
| `src/**/*.{ts,tsx}` | .ts and .tsx in src/  |

---

## Import Syntax

```markdown
See @README for overview.
For API work: @docs/api.md
```

- Relative paths from project root
- Max depth: 5 hops
- Ignored inside code blocks

**Limitations:**
- `@file#section` anchors are NOT supported
- For large docs, consider plain text references instead: "see FILENAME section X"

---

## Never Include

- Code style rules (use linters; Claude learns from codebase)
- Code snippets (go stale; use `file:line` refs instead)
- Secrets or credentials

---

## Checklist

- [ ] Root CLAUDE.md under 100 lines
- [ ] Instruction count minimized (budget: ~100-150 after system prompt)
- [ ] Every instruction universally applicable (or scoped)
- [ ] Uses `@imports` or `file:line` refs instead of embedding content
- [ ] Commands tested and accurate
- [ ] No code snippets, no style rules
- [ ] Conditional rules used sparingly
