#!/usr/bin/env python3
"""board-status — SELF-CONTAINED deploy-accurate Project Status reporter.

THIS FILE IS VENDORED INTO A CONSUMING REPO at
`./.github/actions/board-status/board_status.py` and runs there with NO plugin
installed. It therefore VENDORS its own minimal GraphQL/resolution logic and
imports NOTHING from the gh-projects plugin (AC-22). Stdlib only — no pip.

What it does (one step added to an existing deploy job):
  * staging success -> set every shipped issue's Project Status to `On Staging`
    (the item stays OPEN — staging is not a terminal state).
  * prod success    -> set Status to `Done`, CLOSE the issue, and PUBLISH the
    tag's Release. Shipped issues are resolved from the DEPLOYED SHA
    (SHA -> merged PRs -> their linked/referenced issues) (AC-21).

Hard rules baked in (Phase-1 boundaries):
  * Deterministic & free — NO metered AI/model call anywhere (AC-26).
  * Every Projects v2 field write uses a GitHub App INSTALLATION token, passed
    in as `--app-token` (minted upstream by the composite action from the App
    id + private-key secrets). NEVER GITHUB_TOKEN for a Project write (AC-27).
  * Status writes are IDEMPOTENT + MONOTONIC: resolve the item's current Status
    and only ADVANCE it (In Progress < In Review < On Staging < Done). A stale
    or replayed event never regresses an item (AC-31).
  * The resolver speaks to GitHub ONLY through an INJECTABLE command runner
    (`RUN`), so tests stub gh/GraphQL and run OFFLINE — never a live org (AC-22).
  * Print no token/secret, ever (AC-3).

Exit codes: 0 ok · 2 usage/validation · 3 not found · 1 unexpected.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys


# --------------------------------------------------------------------------- #
# Injectable command runner (the single offline seam) — vendored, no import.
# --------------------------------------------------------------------------- #
class GhError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _default_run(args) -> str:
    """Shell out to `gh <args>`; return stdout. Never echoes argv (token-safe)."""
    proc = subprocess.run(["gh", *[str(a) for a in args]], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError(f"gh {_redact(args)} failed: {_scrub(proc.stderr.strip())}", code=1)
    return proc.stdout


# Tests replace this with a fake. Signature: RUN(list[str]) -> str (stdout).
RUN = _default_run


# --------------------------------------------------------------------------- #
# Secret scrubbing — nothing this module prints may carry a token/secret (AC-3).
# --------------------------------------------------------------------------- #
_SECRET_PATTERNS = [
    re.compile(r"gh[opsuram]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN[^-]+PRIVATE KEY-----.*?-----END[^-]+PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)(authorization|token|secret|private[_-]?key)[\"'\s:=]+[A-Za-z0-9._\-/+]{16,}"),
]


def _scrub(text) -> str:
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def _redact(args) -> str:
    return _scrub(" ".join(str(a) for a in args))


# --------------------------------------------------------------------------- #
# GraphQL primitive (vendored — through RUN, so it stubs offline).
# --------------------------------------------------------------------------- #
def graphql(query: str, variables: dict | None = None, *, token: str | None = None) -> dict:
    """Run a GraphQL operation via `gh api graphql`. Returns the `data` object.

    `token` (the App installation token) is passed via GH_TOKEN in the child
    env so it NEVER appears in argv/logs. GITHUB_TOKEN is never used for writes.
    """
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, val in (variables or {}).items():
        if isinstance(val, bool):
            args += ["-F", f"{key}={'true' if val else 'false'}"]
        elif isinstance(val, (int, float)):
            args += ["-F", f"{key}={val}"]
        else:
            args += ["-f", f"{key}={val}"]
    raw = _run_with_token(args, token)
    payload = json.loads(raw) if raw.strip() else {}
    if isinstance(payload, dict) and payload.get("errors"):
        raise GhError(f"graphql errors: {_scrub(json.dumps(payload['errors']))}", code=1)
    return payload.get("data", payload) if isinstance(payload, dict) else {}


def _run_with_token(args, token):
    """Invoke RUN with the App token exported as GH_TOKEN for this call only.

    Putting the token in the env (not argv) keeps it out of every log line; the
    default runner inherits it, and tests ignore it. We never read GITHUB_TOKEN.
    """
    if not token:
        return RUN(args)
    prev = os.environ.get("GH_TOKEN")
    os.environ["GH_TOKEN"] = token
    try:
        return RUN(args)
    finally:
        if prev is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = prev


# --------------------------------------------------------------------------- #
# Monotonic Status order (AC-31) — vendored copy; never regress except reopen.
# --------------------------------------------------------------------------- #
STATUS_ORDER = ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"]


def status_rank(status) -> int:
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return -1


def advance_status(current, target, *, reopen: bool = False):
    """Return the Status to write, honoring monotonicity (AC-31).

    Only advances along the order. A stale/replayed event whose target is at or
    behind `current` is a no-op (returns None — "do not write"). Only
    reopen=True moves backward.
    """
    if reopen:
        return target
    if current is None:
        return target
    if status_rank(target) > status_rank(current):
        return target
    return None


# --------------------------------------------------------------------------- #
# Shipped-issue resolution: deployed SHA -> merged PRs -> linked/closing issues
# --------------------------------------------------------------------------- #
# We resolve issues from the SHA's associated PRs and the issues those PRs link
# (closingIssuesReferences + the issue-timeline cross-references). This is the
# DEPLOY-side resolution of "what shipped" — it is intentionally separate from
# board-sync's NON-closing PR<->issue link: at deploy time we WANT the full set
# of issues the merged code resolved, so we DO read closingIssuesReferences here
# (that is GitHub's record of what a merged PR resolved, not a board-sync
# Status trigger). board-sync, by contrast, must never depend on `Closes #N`.
_SHA_PRS = """
query($owner:String!, $repo:String!, $sha:String!){
  repository(owner:$owner, name:$repo){
    object(oid:$sha){
      ... on Commit {
        oid
        associatedPullRequests(first:50){
          nodes{
            number
            merged
            closingIssuesReferences(first:50){ nodes{ number id } }
          }
        }
      }
    }
  }
}
"""


def resolve_shipped_issues(owner: str, repo: str, sha: str, *, token: str | None = None) -> list:
    """Return the de-duplicated list of issue dicts ({number,id}) shipped by SHA.

    SHA -> its merged associated PRs -> the issues each PR closed. Order-stable,
    de-duplicated by issue number.
    """
    data = graphql(_SHA_PRS, {"owner": owner, "repo": repo, "sha": sha}, token=token)
    commit = ((data.get("repository") or {}).get("object")) or {}
    if not commit:
        raise GhError(f"deployed SHA {sha[:12]} not found in {owner}/{repo}", code=3)
    seen, issues = set(), []
    for pr in ((commit.get("associatedPullRequests") or {}).get("nodes")) or []:
        if pr.get("merged") is False:
            continue
        for iss in ((pr.get("closingIssuesReferences") or {}).get("nodes")) or []:
            num = iss.get("number")
            if num is not None and num not in seen:
                seen.add(num)
                issues.append({"number": num, "id": iss.get("id")})
    return issues


# --------------------------------------------------------------------------- #
# Project item resolution + current-Status read (for the monotonic guard).
# --------------------------------------------------------------------------- #
_PROJECT_FIELDS = """
query($owner:String!, $number:Int!){
  organization(login:$owner){
    projectV2(number:$number){
      id
      field(name:"Status"){
        ... on ProjectV2SingleSelectField { id name options{ id name } }
      }
    }
  }
}
"""

_ITEM_FOR_ISSUE = """
query($issue:ID!){
  node(id:$issue){
    ... on Issue {
      number
      projectItems(first:20){
        nodes{
          id
          project{ id number }
          fieldValueByName(name:"Status"){
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""

_ISSUE_ID_BY_NUMBER = """
query($owner:String!, $repo:String!, $number:Int!){
  repository(owner:$owner, name:$repo){ issue(number:$number){ id number state } }
}
"""

_UPDATE_STATUS = (
    "mutation($project:ID!,$item:ID!,$field:ID!,$opt:String!){"
    "updateProjectV2ItemFieldValue(input:{projectId:$project,itemId:$item,fieldId:$field,"
    "value:{singleSelectOptionId:$opt}}){projectV2Item{id}}}"
)

_CLOSE_ISSUE = """
mutation($issue:ID!){
  closeIssue(input:{issueId:$issue, stateReason:COMPLETED}){ issue { id number state } }
}
"""


class ProjectStatus:
    """A resolved org Project + its Status field/options. One resolve per run."""

    def __init__(self, owner: str, number: int, token: str | None = None):
        self.owner = owner
        self.number = int(number)
        self.token = token
        self.id = None
        self.status_field_id = None
        self._option_by_name: dict[str, str] = {}

    def resolve(self) -> "ProjectStatus":
        data = graphql(_PROJECT_FIELDS, {"owner": self.owner, "number": self.number}, token=self.token)
        proj = (((data.get("organization") or {}).get("projectV2")) or {})
        if not proj.get("id"):
            raise GhError(f"project {self.owner}#{self.number} not found", code=3)
        self.id = proj["id"]
        field = proj.get("field") or {}
        self.status_field_id = field.get("id")
        for opt in field.get("options") or []:
            self._option_by_name[str(opt["name"]).lower()] = opt["id"]
        return self

    def option_id(self, name: str) -> str:
        oid = self._option_by_name.get(str(name).lower())
        if not oid:
            raise GhError(f"Status option '{name}' not found on project", code=3)
        return oid


def issue_id_by_number(owner: str, repo: str, number: int, *, token: str | None = None) -> dict:
    data = graphql(_ISSUE_ID_BY_NUMBER, {"owner": owner, "repo": repo, "number": number}, token=token)
    iss = (data.get("repository") or {}).get("issue") or {}
    if not iss.get("id"):
        raise GhError(f"issue {owner}/{repo}#{number} not found", code=3)
    return iss


def current_status_for_issue(issue_id: str, project_number: int, *, token: str | None = None):
    """Return (item_id, current_status_name) for this issue on the project."""
    data = graphql(_ITEM_FOR_ISSUE, {"issue": issue_id}, token=token)
    node = data.get("node") or {}
    for it in ((node.get("projectItems") or {}).get("nodes")) or []:
        if (it.get("project") or {}).get("number") == int(project_number):
            cur = (it.get("fieldValueByName") or {}).get("name")
            return it.get("id"), cur
    return None, None


def set_status(project: "ProjectStatus", item_id: str, target_status: str) -> dict:
    opt = project.option_id(target_status)
    graphql(
        _UPDATE_STATUS,
        {"project": project.id, "item": item_id, "field": project.status_field_id, "opt": opt},
        token=project.token,
    )
    return {"item": item_id, "status": target_status}


def close_issue(issue_id: str, *, token: str | None = None) -> dict:
    data = graphql(_CLOSE_ISSUE, {"issue": issue_id}, token=token)
    return (data.get("closeIssue") or {}).get("issue") or {}


def publish_release(repo: str, tag: str, *, token: str | None = None) -> dict:
    """Publish (or mark non-draft) the Release for `tag` via gh REST.

    `repo` is `owner/name`. Idempotent: if a draft release for the tag exists,
    flip draft=false; if a published one exists, no-op; else create from the tag.
    """
    try:
        existing = json.loads(_run_with_token(["api", f"/repos/{repo}/releases/tags/{tag}"], token) or "{}")
    except GhError:
        existing = {}
    if existing.get("id"):
        if existing.get("draft"):
            _run_with_token(
                ["api", "-X", "PATCH", f"/repos/{repo}/releases/{existing['id']}", "-F", "draft=false"],
                token,
            )
            return {"release": tag, "action": "published-existing-draft"}
        return {"release": tag, "action": "already-published"}
    _run_with_token(
        ["api", "-X", "POST", f"/repos/{repo}/releases",
         "-f", f"tag_name={tag}", "-f", f"name={tag}", "-F", "draft=false"],
        token,
    )
    return {"release": tag, "action": "created"}


# --------------------------------------------------------------------------- #
# The two operations the action invokes.
# --------------------------------------------------------------------------- #
def run_staging(owner: str, repo: str, project_number: int, sha: str, *, token: str | None = None,
                explicit_issues: list | None = None) -> dict:
    """Staging success -> advance shipped issues to `On Staging` (item stays OPEN).

    NOTE: the item is NOT closed and NOT moved to Done on staging — staging is a
    non-terminal stage. This mirrors the native 'PR merged -> On Staging'
    built-in target (also non-terminal, item stays open); see action.yml notes.
    """
    return _apply_status(
        owner, repo, project_number, sha, "On Staging",
        close=False, release_tag=None, token=token, explicit_issues=explicit_issues,
    )


def run_prod(owner: str, repo: str, project_number: int, sha: str, *, tag: str | None = None,
             token: str | None = None, explicit_issues: list | None = None) -> dict:
    """Prod success -> Done + close the issue + publish the tag's Release (AC-21)."""
    return _apply_status(
        owner, repo, project_number, sha, "Done",
        close=True, release_tag=tag, token=token, explicit_issues=explicit_issues,
    )


def _apply_status(owner, repo, project_number, sha, target_status, *, close, release_tag,
                  token, explicit_issues):
    project = ProjectStatus(owner, project_number, token=token).resolve()

    if explicit_issues:
        issues = []
        for num in explicit_issues:
            iss = issue_id_by_number(owner, repo, int(num), token=token)
            issues.append({"number": int(num), "id": iss["id"]})
    else:
        issues = resolve_shipped_issues(owner, repo, sha, token=token)

    results = []
    for iss in issues:
        issue_id = iss.get("id")
        if not issue_id:
            issue_id = issue_id_by_number(owner, repo, iss["number"], token=token)["id"]
        item_id, current = current_status_for_issue(issue_id, project_number, token=token)
        if item_id is None:
            results.append({"issue": iss["number"], "skipped": "not-on-project"})
            continue
        # MONOTONIC guard (AC-31): only advance; a replayed/stale event is a no-op.
        to_write = advance_status(current, target_status)
        wrote = False
        if to_write is not None:
            set_status(project, item_id, to_write)
            wrote = True
        closed = False
        if close:
            # Issue is closed at PROD only (never by board-sync / Closes #N).
            close_issue(issue_id, token=token)
            closed = True
        results.append({
            "issue": iss["number"], "from": current, "to": (to_write or current),
            "wrote": wrote, "closed": closed,
        })

    out = {"target": target_status, "sha": sha, "issues": results}
    if release_tag:
        out["release"] = publish_release(f"{owner}/{repo}", release_tag, token=token)
    return out


# --------------------------------------------------------------------------- #
# CLI — documented exit codes 0/2/3/1; prints no token/secret (AC-3).
# --------------------------------------------------------------------------- #
def _print_json(obj) -> None:
    sys.stdout.write(_scrub(json.dumps(obj)) + "\n")


def _split_issue_refs(raw):
    if not raw:
        return []
    out = []
    for tok in re.split(r"[\s,]+", str(raw).strip()):
        tok = tok.lstrip("#")
        if tok.isdigit():
            out.append(int(tok))
    return out


def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="board_status.py",
                                description="self-contained deploy-accurate board status reporter")
    p.add_argument("--repo", required=True, help="owner/name of the consuming repo")
    p.add_argument("--project", type=int, required=True, help="org Project number")
    p.add_argument("--status", required=True, choices=["staging", "prod"],
                   help="deploy stage that just succeeded")
    p.add_argument("--sha", default="", help="deployed commit SHA (resolves shipped issues)")
    p.add_argument("--issues", default="", help="explicit issue refs (overrides SHA resolution)")
    p.add_argument("--tag", default="", help="release tag (prod: published on success)")
    p.add_argument("--app-token", default="", help="App INSTALLATION token (never GITHUB_TOKEN)")
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)

    if "/" not in args.repo:
        sys.stderr.write("error: --repo must be owner/name\n")
        return 2
    owner_login, repo_name = args.repo.split("/", 1)
    # The org login that OWNS the Project may differ from the repo owner; default
    # to the repo owner (org-owned repos), overridable via PROJECT_OWNER env.
    project_owner = os.environ.get("PROJECT_OWNER", owner_login)
    token = args.app_token or os.environ.get("GH_APP_TOKEN") or None
    explicit = _split_issue_refs(args.issues)
    if not args.sha and not explicit:
        sys.stderr.write("error: need --sha or --issues to resolve shipped issues\n")
        return 2

    try:
        if args.status == "staging":
            out = run_staging(project_owner, repo_name, args.project, args.sha,
                              token=token, explicit_issues=explicit)
        else:
            if not args.tag:
                sys.stderr.write("error: --tag is required for prod (publishes the Release)\n")
                return 2
            out = run_prod(project_owner, repo_name, args.project, args.sha,
                           tag=args.tag, token=token, explicit_issues=explicit)
    except GhError as e:
        sys.stderr.write("error: " + _scrub(str(e)) + "\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + _scrub(str(e)) + "\n")
        return 1

    _print_json(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
