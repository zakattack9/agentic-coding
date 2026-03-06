---
name: ascii-ui
description: Generate consistent, pixel-perfect ASCII UI wireframe mockups for specs and PRDs. Use when the user asks to draw a wireframe, mockup, UI diagram, or ASCII layout. Also use when fixing alignment in existing ASCII diagrams.
user-invocable: true
argument-hint: [description of the UI to draw]
---

# ASCII UI Wireframe Generator

You are a specialist in producing **perfectly aligned, monospace-safe ASCII UI wireframes** for use in specs, PRDs, and technical documentation. Every line inside a code block must have the **exact same character count** between outer borders.

When invoked, produce ASCII wireframes following the constraints, primitives, and rules below exactly.

---

## GRID SYSTEM

All wireframes are built on a **fixed-width character grid**. Every line within a diagram must be the same visual width.

| Property        | Value | Notes                                    |
| --------------- | ----- | ---------------------------------------- |
| Default width   | 70    | Characters per line, border-to-border    |
| Compact width   | 50    | For small components or mobile mockups   |
| Wide width      | 90    | For full-page layouts with nested boxes  |
| Content padding | 2     | Spaces inside each border before content |
| Nesting gap     | 2     | Spaces between parent and child borders  |
| Max nesting     | 2     | Levels of boxes within boxes             |

**The #1 rule**: Every line from the first `+` to the last `+` (or `|` to `|`) must contain the **exact same number of printable characters**. Count spaces meticulously. Verify by counting the width of the first border line, then ensure every subsequent line matches.

---

## BORDER CHARACTERS

Use **pure ASCII** box-drawing characters only. Never use Unicode line-drawing characters (no `─`, `│`, `┌`, `└`, etc.) because they are multi-byte and cause alignment errors in many editors and renderers.

| Element       | Character(s) | Example          |
| ------------- | ------------ | ---------------- |
| Horizontal    | `-`          | `----------`     |
| Vertical      | `            | `                | ` |  | ` |
| Corner        | `+`          | `+----------+`   |
| Section title | `+-- TITLE`  | `+-- HEADER --+` |

### Box Template

A box of width W looks like:

```
+--- TITLE ------------------------------------------+   <- W chars total
|                                                     |   <- W chars total
|  Content here, padded 2 spaces from each border     |   <- W chars total
|                                                     |   <- W chars total
+-----------------------------------------------------+   <- W chars total
```

**Counting rule for borders**: `+` + (W-2) dashes + `+` = W characters.
**Counting rule for content**: `|` + (W-2) characters (content + spaces) + `|` = W characters.

### Section Title Borders

Section titles are embedded into the top border with dashes filling the remainder:

```
+-- Section Name -----------------------------------------+
```

The pattern is: `+-- ` + title + ` ` + remaining dashes to fill width + `+`

---

## DIVIDERS

Use plain ASCII dashes for horizontal rules inside boxes. Pad with 2 spaces from each border:

```
|     |
| --- |
|     |
```

The divider is: `|  ` + (W-6) dashes + ` |` = W characters.

---

## UI COMPONENT PRIMITIVES

### Text Input

```
Label *
[placeholder text                               ]
```

Or inline:

```
Label *              [value                      ]
```

Inputs use `[` and `]` with content/placeholder between them. Pad interior with spaces to the desired width.

### Textarea

Stack multiple input-width lines:

```
[                                                ]
[                                                ]
[                                                ]
```

### Dropdown / Select

A `v` inside the closing bracket indicates a dropdown:

```
[Select an option                              v]
```

### Dropdown (Expanded)

```
+----------------------------------------------------+
| Search...                                        v |
+----------------------------------------------------+
|                                                    |
| AVAILABLE                                        |
| ------------------------------------------------ |
|                                                  |
| * 2024 Toyota Camry (ABC-1234)    <- selected    |
| 2025 Jeep Wrangler (DEF-5678)                    |
|                                                  |
| UNAVAILABLE                                      |
| ------------------------------------------------ |
|                                                  |
| 2023 Honda Civic (GHI-9012)     (greyed out)     |
|                                                  |
+----------------------------------------------------+
```

### Button

```
[ Button Label ]
```

Primary buttons: `[  Primary Action  ]`
Multiple buttons in a row: `[ Cancel ]  [ Confirm ]`

### Checkbox

```
[ ] Unchecked option
[x] Checked option
```

### Radio Button

```
( ) Unselected option
(o) Selected option
```

### Toggle Switch

```
Off:  [ o          ]   Label
On:   [          o ]   Label
```

Or with explicit state:

```
Toggle label                         [ o     ]
                                 off--^

Toggle label                         [     o ]
                                       on--^
```

### Number Stepper

```
[-]  0  [+]
```

Or as an input with arrows:

```
[0                                            ^v]
```

### Status Badges / Pills

```
[+$150.00]    <- green (positive change)
[-$30.00]     <- red (negative change)
[No change]   <- grey (neutral)
[Added]       <- green label
[Removed]     <- red label
[Swap]        <- orange label
```

Badges are inline bracketed labels. Color annotations go in comments, not in the diagram itself.

### Spinner / Loading

```
(...)  Loading message here
```

### Icons

```
Close button:     [x]
Dropdown arrow:   v
Back arrow:       <-
Forward arrow:    ->
Info:             (i)
Warning:          (!)
Checkmark:        *
```

---

## NESTING RULES

When placing boxes inside boxes (e.g., sections within a page frame):

1. **Outer border** is drawn at the full width.
2. **Inner boxes** are indented 2 spaces from the outer `|` on each side.
3. Inner box width = outer width - 6 (2 for outer `|` padding + 2 left indent + 2 right indent... simplified: inner `+` starts at position 4, ends at position W-3).

### Nesting Template (W=70)

```
+--------------------------------------------------------------------+  <- 70 chars
|                                                                    |  <- 70 chars
|  +-- Inner Section ---------------------------------------------+  |  <- 70 chars
|  |                                                              |  |  <- 70 chars
|  |  Content inside inner section                                |  |  <- 70 chars
|  |                                                              |  |  <- 70 chars
|  +--------------------------------------------------------------+  |  <- 70 chars
|                                                                    |  <- 70 chars
+--------------------------------------------------------------------+  <- 70 chars
```

**Character accounting for W=70:**
- Outer border: `+` + 68 dashes + `+` = 70
- Outer content: `|` + 68 chars + `|` = 70
- Inner border: `|  +` (4) + 60 dashes + `+  |` (3) ... WRONG, that's 67.

**Correct accounting:**
- Position 1: `|`
- Position 2-3: `  ` (2 spaces)
- Position 4: `+`
- Position 5 to 66: 62 dashes (or content chars)
- Position 67: `+`
- Position 68-69: `  ` (2 spaces)
- Position 70: `|`
- Total: 1 + 2 + 1 + 62 + 1 + 2 + 1 = 70

So inner box: `+` + 62 fill + `+` = 64 chars wide.
Inner content: `|` + 62 chars + `|` = 64 chars wide.
Wrapped in outer: `|  ` + 64 inner + `  |` = 70 chars.

### Quick Reference

| Outer Width | Inner Box Width | Inner Content Width | Dash Fill in Inner Border |
| ----------- | --------------- | ------------------- | ------------------------- |
| 70          | 64              | 62                  | 62                        |
| 80          | 74              | 72                  | 72                        |
| 90          | 84              | 82                  | 82                        |
| 50          | 44              | 42                  | 42                        |

---

## ALIGNMENT VERIFICATION PROCESS

After generating any ASCII diagram, perform this check:

1. Count the characters in the **first border line** (the `+----...----+`). This is W.
2. For **every subsequent line**, count characters and confirm it equals W exactly.
3. Pay special attention to:
   - Lines with inline content (labels, values, badges) -- trailing spaces are easy to miss.
   - Lines with nested inner borders -- the inner `+` and outer `|` positions must be consistent.
   - Lines with `[input fields]` or `[ buttons ]` -- bracket positions affect spacing.
4. If any line does not equal W, add or remove spaces **before** the closing `|` to fix it.

**Tip**: The closing `|` or `+` on the right side of every line must be in the **exact same column position**.

---

## COMPOSITION PATTERNS

### Full Page Layout

For a complete page wireframe, use the outer box as the page container and inner boxes for each section:

```
+--------------------------------------------------------------------+
|  Page Title                                         [ Action ] Back |
+--------------------------------------------------------------------+
|                                                                    |
|  +-- SECTION 1 -------------------------------------------------+  |
|  |                                                              |  |
|  |  Field 1 *                    Field 2 *                      |  |
|  |  [value                 ]     [value                 ]       |  |
|  |                                                              |  |
|  +--------------------------------------------------------------+  |
|                                                                    |
|  +-- SECTION 2 -------------------------------------------------+  |
|  |                                                              |  |
|  |  Content here                                                |  |
|  |                                                              |  |
|  +--------------------------------------------------------------+  |
|                                                                    |
|                          [ Save Changes ]                          |
|                                                                    |
+--------------------------------------------------------------------+
```

### Comparison Table (Before/After)

```
+--------------------------------------------------------------------+
|                                                                    |
| Previous     New         Change                    |
| -------------------------------------------------- |
| Line item 1     $100.00     $120.00    [+$20.00]   |
| Line item 2      $25.00      $25.00    [No change] |
| ------------------------------------------------   |
| Total            $125.00     $145.00    [+$20.00]  |
|                                                    |
+--------------------------------------------------------------------+
```

### Form Section

```
+-- Form Section ---------------------------------------------------+
|                                                                    |
|  Field 1 *                         Field 2 *                      |
|  [                           ]     [                           ]  |
|                                                                    |
|  Field 3 *                         Field 4 *                      |
|  [                           ]     [                           ]  |
|                                                                    |
+--------------------------------------------------------------------+
```

### Modal / Dialog

```
+--------------------------------------------------------------------+
|  Dialog Title                                                [x]  |
+--------------------------------------------------------------------+
|                                                                    |
|  Message or content goes here. This explains what the user         |
|  needs to decide.                                                  |
|                                                                    |
+--------------------------------------------------------------------+
|                              [ Cancel ]  [ Confirm ]               |
+--------------------------------------------------------------------+
```

---

## RESPONSE FORMAT

When the user requests an ASCII wireframe:

1. **Clarify** the target width if not obvious (default to 70).
2. **Draw** the wireframe inside a fenced code block (triple backticks).
3. **Verify** every line is the same width before returning.
4. If fixing an existing diagram, show only the corrected version (not a diff).

Always wrap the diagram in a markdown code block so it renders in monospace.
