# delegate-codex — composing the task and attributing the diff

## No-argument path — suggesting tasks

Open one `AskUserQuestion` with **2–4** concrete, context-derived tasks as options (e.g. "Fix
the failing test in X", "Add validation to Y", "Refactor Z"). The tool auto-adds **"Other"**
for a freeform task — do **not** add your own. When context is **sparse**, ask the user to
type the task instead of inventing one; this skill writes to the tree, so a wrong guess is
costly.

## Pre-run snapshot — required for honest attribution

A plain `git diff` after the run conflates Codex's edits with a tree that was already dirty.
Before the run, capture:

```bash
git status --porcelain
```

- **Empty** → the tree was clean; after the run, the entire `git diff` (plus any new untracked
  files) is **Codex's work** — attribute it cleanly.
- **Non-empty** → there were pre-existing changes; after the run, attribution is **best-effort**.
  Show the full diff and state plainly which paths were already dirty before the run, so the
  reader knows those changes are not necessarily Codex's.
- **Errors / "not a git repository"** → there is no repo to diff; note that no diff or
  attribution is possible, and still run (the bridge passes `--skip-git-repo-check`).

## Prompt template (fill, then pipe to the bridge on stdin with `--write`)

```
You are completing a coding task in this repository (<repo name / cwd>) with permission to
edit the working tree. Read the relevant code first, then make the change.

Task: <the user's task, composed into a clear, self-contained instruction with any constraints
the conversation established>.

Make the edits directly in the working tree. Do not commit, stage, or create branches — leave
the changes uncommitted so they can be reviewed. Keep the change focused on the task.
```

## After the run

Run `git diff` (and check for untracked files, e.g. `git status --porcelain`) to capture what
Codex changed, and surface it alongside Codex's verbatim output:

- Codex's output **verbatim** (it explains what it did),
- the **`git diff`** (Codex's edits), with the pre-run attribution note,
- the **session id** (shared metadata block).

Leave everything uncommitted and unstaged. If the diff is empty, say no workspace change
resulted but still surface the output and the session id. On an error after the run began
(exit 11), still show the diff so partial edits are visible — do not roll back, and do not
finish the task as Claude.
