#!/usr/bin/env python3
"""spec_git.py — safe, path-scoped git commits for the spec-ops skills.

spec-ops authors a spec *file*; this helper commits **only that file**, so a spec
commit can never sweep up unrelated or untracked changes (the failure mode that
motivated it). Shared by write-spec (draft commit) and refine-spec (ready
commit); the refine-spec Stop hook imports `spec_needs_commit` to enforce that
the ready spec was committed before the run can end.

Hard rules:
  - Scope to the one path: `git add -- <path>` then `git commit --only -- <path>`.
    NEVER `git add -A` / `.`; any other staged changes are left exactly as they
    were (--only commits just this path).
  - Never push, never branch, never add a repo-specific trailer.
  - No-op cleanly when it isn't a git repo or there is nothing to commit.

CLI:
  spec_git.py commit <spec-path> <message>   → scoped commit (or a clean no-op)
  spec_git.py needs-commit <spec-path>       → prints "yes" / "no"
"""

import os
import subprocess
import sys


def _git(args, cwd):
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None


def repo_root(path):
    """Absolute toplevel of the git repo containing `path`, or None if not in one.
    Uses realpath so it matches git's own symlink-resolved `--show-toplevel`."""
    d = os.path.dirname(os.path.realpath(path)) or "."
    out = _git(["rev-parse", "--show-toplevel"], cwd=d)
    if out is None or out.returncode != 0:
        return None
    return out.stdout.strip() or None


def spec_needs_commit(path):
    """True only when `path` is inside a git repo AND has uncommitted changes
    (modified, staged, or untracked). False for a clean path OR a non-repo — i.e.
    False means 'nothing to enforce'. Never raises."""
    root = repo_root(path)
    if not root:
        return False
    out = _git(["status", "--porcelain", "--", os.path.realpath(path)], cwd=root)
    if out is None or out.returncode != 0:
        return False
    return bool(out.stdout.strip())


def commit_path(path, message):
    """Stage and commit ONLY `path` with `message`. Returns (code, detail):
      0 committed · 1 nothing-to-commit · 2 not-a-repo · 3 error.
    Scoped and best-effort — never touches other paths, never pushes."""
    abspath = os.path.realpath(path)
    root = repo_root(abspath)
    if not root:
        return 2, f"{path} is not inside a git repository — no commit"
    if not os.path.exists(abspath):
        return 3, f"{path} does not exist"
    if not spec_needs_commit(abspath):
        return 1, f"{os.path.relpath(abspath, root)} is already up to date — nothing to commit"

    add = _git(["add", "--", abspath], cwd=root)
    if add is None or add.returncode != 0:
        return 3, f"git add failed: {(add.stderr if add else '').strip()}"

    # --only commits JUST this path even if other things are staged — unless the
    # repo has no commits yet (no HEAD to diff a partial commit against).
    head = _git(["rev-parse", "--verify", "HEAD"], cwd=root)
    only = ["--only"] if (head is not None and head.returncode == 0) else []
    commit = _git(["commit", *only, "-m", message, "--", abspath], cwd=root)
    if commit is None or commit.returncode != 0:
        return 3, f"git commit failed: {(commit.stderr if commit else '').strip()}"

    sha = _git(["rev-parse", "--short", "HEAD"], cwd=root)
    short = sha.stdout.strip() if (sha and sha.returncode == 0) else "?"
    return 0, f"committed {os.path.relpath(abspath, root)} as {short}"


def main(argv):
    if len(argv) >= 4 and argv[1] == "commit":
        _code, detail = commit_path(argv[2], argv[3])
        print(detail)
        return 0  # a no-op / non-repo is not a failure for the caller
    if len(argv) >= 3 and argv[1] == "needs-commit":
        print("yes" if spec_needs_commit(argv[2]) else "no")
        return 0
    sys.stderr.write("usage: spec_git.py {commit <path> <message> | needs-commit <path>}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
