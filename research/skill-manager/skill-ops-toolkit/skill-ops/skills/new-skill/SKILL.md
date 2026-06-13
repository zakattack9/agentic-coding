---
name: new-skill
description: Scaffold a new SKILL.md with correct frontmatter, either in the current project or directly in a central plugin. Use whenever the user wants to start a new skill from scratch and says "create a skill", "scaffold a skill", "new skill for X", or "add a skill to <plugin>". For turning an existing project skill into a centralized one, use promote-skill instead.
disable-model-invocation: true
allowed-tools: Bash(skillctl *) Bash(git *)
argument-hint: "<skill-name> [--plugin <plugin> | --project]"
---

# Scaffold a new skill

Create a well-formed `SKILL.md` so the user can start writing instructions immediately.

## Decide where it lives

- **Project-local** (`--project`): iterate privately in this repo first, promote later. Good default when the skill is experimental or project-specific.
- **Central plugin** (`--plugin <name>`, default `core`): publish straight to the marketplace. Good when you already know it's reusable.

Ask which the user wants if it isn't clear.

## Steps

1. Get a lowercase-hyphenated name (e.g. `tf-plan-review`).
2. Draft a strong `description`: state what the skill does AND the contexts/phrases that should trigger it. Skills tend to under-trigger, so make the description specific and slightly pushy about when to use it.
3. Run either:
   - `skillctl new-skill <name> --project` (project), or
   - `skillctl new-skill <name> --plugin <plugin> --description "<desc>"` (central).
4. Open the generated `SKILL.md` and help the user fill in the body (keep it under ~500 lines; move long reference material into separate files in the skill folder).
5. If it was created centrally, remind them it loads as `/<plugin>:<name>` after `/reload-plugins`. If project-local, mention they can later run the promote-skill skill.
