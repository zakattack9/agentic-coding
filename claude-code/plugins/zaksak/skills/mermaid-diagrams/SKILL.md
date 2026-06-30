---
name: mermaid-diagrams
description: Author or fix Mermaid diagrams that render correctly on GitHub. Use whenever writing, editing, or debugging a ```mermaid block — flowchart, sequence, state, ER, class, gantt — or when a diagram shows "Unable to render rich display" / a parse error. Encodes the exact escaping, quoting, ID, and block-balance rules that keep GitHub's strict renderer from failing.
---

# Mermaid Diagrams — GitHub-Safe Authoring

GitHub renders ` ```mermaid ` fenced blocks with a strict, sandboxed build (`securityLevel:
strict`; JS/click disabled; HTML in labels sanitized). **One syntax error fails the whole
block** — it shows *"Unable to render rich display."* No partial render, no warning.

**Golden rule:** keep text plain and **reword around special characters** instead of escaping
them. The breakers are a small set — `< > & ; [ ] { } ( )` — and rewording wins every time,
because *escaping itself breaks some contexts* (see below).

## The two text contexts (this decides how to escape)

Every piece of text in a diagram is either **quoted** or **bare**, and they have **opposite**
rules:

| Context    | Where it appears                                                   | Rule for `< > &`                                                   |
| ---------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| **Quoted** | inside `"…"` — `id["…"]`, `A -->\|"…"\| B`, `participant P as "…"` | content is literal; you *may* entity-escape: `&lt;` `&gt;` `&amp;` |
| **Bare**   | sequence message after `:`, unquoted labels, `alt`/condition text  | **never entity-escape** — reword to remove `< > &` instead         |

**Why bare text can't be escaped:** `;` is a **statement separator** in Mermaid, and every HTML
entity ends in `;`. So escaping `<id>` → `&lt;id&gt;` *in a sequence message* makes the parser
split the line at each `;` into invalid fragments → *"Parse error … Expecting arrow, got
NEWLINE."* In bare text write `(id)` or `id` — never `&lt;id&gt;`.

## Cardinal rules

1. **Fence + type line.** Open with only ` ```mermaid `, close with ` ``` `. The **first content
   line declares the type** (`flowchart TB`, `sequenceDiagram`, `stateDiagram-v2`, `erDiagram`,
   `classDiagram`, `gantt`); no blank line before it.

2. **Quote every label that isn't a single plain word** — `id["…"]` for nodes, `A -->|"…"| B` for
   edge labels. Quoting neutralizes spaces, `()`, `:`, `/`, `*`, `.`, `,`, `'`. Quote by default —
   it's free.

3. **Reword to avoid `<` `>` `&` `;` in text.** Placeholder → `id` or `(id)`, not `<id>`;
   conjunction → "and", not `&`; comparison → "ge"/"le" or the Unicode `≥`/`≤`, not `>=`/`<`. A
   literal `;` in **bare** text always ends the statement — never write one. Only inside a
   **quoted** label may you use `&lt;`/`&gt;`/`&amp;` (and only if rewording won't do); **never**
   in sequence-message text.

4. **No `[ ] { }` inside a label, even quoted** — a bracket opens another shape and breaks the
   lexer. Reword (`"env overlay"`, not `"env[...] overlay"`); if truly needed, quoted labels only:
   `&#91;` `&#93;` `&#123;` `&#125;`.

5. **Parentheses break *unquoted flowchart* labels/edges** — quote the label. (They're fine inside
   quotes and in sequence-message text.)
   - ✅ `n["step (optional)"]`   ✅ `A -->|"forward (all)"| B`   ❌ `A -->|forward (all)| B`

6. **IDs are `[A-Za-z_][A-Za-z0-9_]*`** — letters, digits, underscore; no spaces, hyphens, dots, or
   slashes. The pretty name goes in the *label*. Don't name a bare node `end` (it closes a
   subgraph).
   - ✅ `web_host["Web host"]`   ❌ `web-host[...]`   ❌ `web.host[...]`

7. **Balance every block.** Each `subgraph`/`alt`/`opt`/`loop`/`par`/`critical` needs an `end`;
   `else` lives inside an `alt`. Balance quotes and brackets too.

8. **Line break inside a label is `<br/>`** — never a real newline.

## Common breakers → fixes

| Construct                                                                          | Fix                                                  |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `X->>Y: build &lt;id&gt;` — entity in a sequence message (the `;` splits the line) | reword: `X->>Y: build (id)`                          |
| `n["a env[...] b"]` — brackets inside a label                                      | reword: `n["a env-overlay b"]`                       |
| `A -->\|step (x)\| B` — parens in an unquoted edge label                           | `A -->\|"step (x)"\| B`                              |
| `n[build <id>]` — raw `<…>` dropped as HTML in a flowchart label                   | quote + entity: `n["build &lt;id&gt;"]`              |
| `subgraph my-group[...]` — hyphen in an ID                                         | `subgraph my_group["…"]`                             |
| node named `end` collapses a subgraph                                              | rename (`done`/`End`) or quote `["end"]`             |
| blank / "Unable to render" with no obvious cause                                   | check `subgraph`/`alt` ↔ `end` balance and stray `"` |

## Per-type notes

**flowchart** — declare a direction (`TB`/`LR`/`TD`/`RL`/`BT`). Shapes: `id["rect"]`,
`id(["stadium"])`, `id[("database")]`, `id{"rhombus"}` — the label inside still obeys rules 3–5.
`A & B --> C` node lists are valid (escape any `&` in a *label*). `subgraph id["Title"] … end`; an
edge may target a subgraph by its `id`; inside one you can set `direction LR`.

**sequenceDiagram** — message text after the first `:` is **bare** (rule 3 and the `;` warning bite
hardest here); a `:` *within* the message is fine. Quote a participant alias that has special
chars: `participant P as "Pretty (name)"`. Balance `alt/else/end`, `opt/end`, `loop/end`,
`par/and/end`.

**stateDiagram-v2 / erDiagram / classDiagram / gantt** — rules 3 (reword/escape) and 7 (balance)
still apply. `classDiagram` generics are `~T~` (e.g. `List~int~`), **not** `<T>`. `erDiagram`
entity names obey rule 6 (no hyphens).

## Self-check (before saving — no tools needed)

Read the block top-to-bottom and confirm each box:

- [ ] Opens with ` ```mermaid ` + a valid type on line 1; closes with ` ``` `.
- [ ] **Bare text** (sequence messages, unquoted labels, `alt`/conditions) has no `<`, `>`, `&`, or `;` — reworded, *not* entity-escaped.
- [ ] Entities (`&lt;` `&gt;` `&amp;`) appear **only inside `"quoted"` labels**, if at all.
- [ ] No `[ ] { }` inside any label; parentheses appear only inside quotes or sequence messages.
- [ ] Every multi-word / special-char label is `"quoted"`; every special-char edge label is `|"…"|`.
- [ ] Every ID matches `[A-Za-z_][A-Za-z0-9_]*` (no `-` `.` space); no node is bare `end`.
- [ ] Every `subgraph`/`alt`/`opt`/`loop`/`par` has a matching `end`; all quotes and brackets balanced.
