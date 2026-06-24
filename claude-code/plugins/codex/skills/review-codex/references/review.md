# review-codex — composing the review

## Choosing the bridge mode

| Situation | Bridge call | Why |
| --------- | ----------- | --- |
| No target; working tree has uncommitted/staged changes | `--review` | `codex exec review` defaults to the uncommitted working tree |
| A focus target (a module/file in the working tree, or a concern like "security", "perf") | `--review` | Same default scope; the target is the review *focus*, not a new scope |
| A target naming a specific commit / branch / range ("review commit abc123", "review against main", "the changes on branch X") | plain call (no `--review`) | `review`'s scope flags (`--uncommitted`/`--base`/`--commit`) cannot be combined with a prompt; instead direct Codex to inspect the range via read-only `git` |
| No target and a clean tree / no clear focus | neither — ask for a target | Don't invent a review or open a picker |

You never pass a `review` scope flag yourself — the bridge's `--review` mode relies on the
default uncommitted scope, and the branch/commit case uses a plain call.

## Grounding before you compose

- `git status --porcelain` — is the tree dirty? what changed?
- `git diff` (and `git diff --staged`) — the uncommitted/staged changes to focus on.
- `git log --oneline -n 5` — recent context; for a named commit/branch, the range to inspect.
- The conversation — what was just being worked on, what the user cares about.

Don't paste large diffs/files into the prompt — Codex reads the repo itself under `-C`. Name
the files/range and the focus; let Codex ground.

## Prompt template (fill, then pipe to the bridge on stdin)

```
You are giving a focused, read-only code review as a second-opinion model.

Repository: <repo name / cwd>. Review focus: <the uncommitted working tree | the named
target | the changes in <range>>.
<For a branch/commit/range target: Inspect the changes with read-only git — e.g.
`git diff main...HEAD`, `git show <sha>`, `git diff <base>..<head>`. Do not assume; read
the actual diff and the surrounding code.>

What to look for: correctness and logic bugs, edge cases, security issues, error handling,
concurrency, performance, API misuse, and anything that would break or surprise a maintainer.
<Add any user-specified focus here.>

Report findings in your own severity order (most severe first), each with the file:line and
a concrete explanation. Be specific and cite real code.

Important — this is a READ-ONLY review: do NOT modify any files, do NOT run formatters or
linters that rewrite files, and do NOT install dependencies, even if a fix seems obvious.
Describe the fix; do not apply it.
```

The final paragraph is **defense-in-depth** atop the read-only sandbox — keep it even though
the bridge already pins `--sandbox read-only`.

## Surfacing

Surface Codex's review verbatim and in full, in **Codex's own severity ordering**. Frame it
minimally (e.g. a one-line header "Codex review — <focus>") and append the session-id /
diagnostic metadata block from the shared rules. Do not parse, re-sort, or rewrite the
findings. After presenting, stop; offer a follow-up fix only if the user asks.
