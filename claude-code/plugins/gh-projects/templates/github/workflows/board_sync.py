#!/usr/bin/env python3
"""board-sync — event-driven GitHub Projects v2 Status writer (vendored).

THIS FILE IS VENDORED INTO A CONSUMING REPO alongside `board-sync.yml` and runs
there with NO plugin installed. It VENDORS its own minimal GraphQL/resolution
logic and imports NOTHING from the gh-projects plugin (so `board-sync.yml` never
imports `lib/*`). Stdlib only — no pip.

What it does, driven by repo `push` / `pull_request` events (we INVERT the
trigger — `projects_v2_item` can't trigger a repo workflow, constraint #1):

  * `push` to an ISSUE-LINKED branch -> set that issue's item to `In Progress`
    via an App-token GraphQL write.
  * `pull_request` opened/ready/draft -> a READY PR -> `In Review`; a DRAFT PR
    holds `In Progress` until `ready_for_review`.
  * Resolve the PR<->issue link from the LINKED BRANCH first, then a branch-name
    `123-foo` parse fallback. It NEVER depends on `Closes #N` / any closing
    keyword.

Hard rules baked in:
  * Deterministic & free — NO metered AI/model call anywhere.
  * Every Projects v2 field write uses a GitHub App INSTALLATION token (passed in
    as `--app-token` / GH_APP_TOKEN), NEVER GITHUB_TOKEN (constraint #2).
  * Status writes are IDEMPOTENT + MONOTONIC: resolve the item's current Status
    and only ADVANCE it (In Progress < In Review < On Staging < Done). A stale or
    replayed event never regresses an item. Items are NEVER closed here.
  * The resolver speaks to GitHub ONLY through an INJECTABLE command runner
    (`RUN`), so tests stub gh/GraphQL and run OFFLINE — never a live org.
  * Print no token/secret, ever.

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
    proc = subprocess.run(["gh", *[str(a) for a in args]], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError(f"gh {_redact(args)} failed: {_scrub(proc.stderr.strip())}", code=1)
    return proc.stdout


RUN = _default_run


# --------------------------------------------------------------------------- #
# Secret scrubbing.
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
# Monotonic Status order.
# --------------------------------------------------------------------------- #
STATUS_ORDER = ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"]


def status_rank(status) -> int:
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return -1


def advance_status(current, target, *, reopen: bool = False):
    """Only advance along the order; a stale/replayed event is a no-op (None)."""
    if reopen:
        return target
    if current is None:
        return target
    if status_rank(target) > status_rank(current):
        return target
    return None


# --------------------------------------------------------------------------- #
# PR<->issue link resolution: LINKED BRANCH first, branch-name parse fallback.
# NEVER parses `Closes #N` / any closing keyword.
# --------------------------------------------------------------------------- #
# A branch created via `gh issue develop` / the dev panel is an AUTHORITATIVE
# linked branch — GitHub records it on the issue (`linkedBranches`). We resolve
# that first. Only if no linked branch exists do we fall back to the
# conventional `123-foo` branch-name prefix. We deliberately do NOT read the PR
# body or any closing-keyword reference here — board-sync must never depend on a
# `Closes`-style keyword to find the issue.
_BRANCH_NAME_RE = re.compile(r"^(\d+)[-_/]")

# Authoritative linked-branch -> issue mapping. GitHub exposes the linked branch
# on the ISSUE (issue.linkedBranches). We search by branch name across the
# repo's open issues' linked branches — that is the authoritative link a
# `gh issue develop` / dev-panel branch records, independent of any PR body.
_LINKED_BRANCH_LOOKUP = """
query($owner:String!, $repo:String!, $name:String!){
  repository(owner:$owner, name:$repo){
    issues(first:50, states:OPEN, orderBy:{field:UPDATED_AT, direction:DESC}){
      nodes{
        number id
        linkedBranches(first:10){ nodes{ ref{ name } } }
      }
    }
  }
}
"""


def short_branch(ref: str) -> str:
    """Strip refs/heads/ and a leading origin/ from a branch ref."""
    name = ref
    for prefix in ("refs/heads/", "refs/remotes/origin/", "origin/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def issue_from_linked_branch(owner: str, repo: str, branch: str, *, token: str | None = None):
    """Return the issue number whose AUTHORITATIVE linked branch == `branch`.

    This is the FIRST resolution path. Returns None if no issue has this
    branch as a linked branch (caller then tries the branch-name parse).
    """
    name = short_branch(branch)
    data = graphql(_LINKED_BRANCH_LOOKUP, {"owner": owner, "repo": repo, "name": name}, token=token)
    issues = (((data.get("repository") or {}).get("issues")) or {}).get("nodes") or []
    for iss in issues:
        for lb in ((iss.get("linkedBranches") or {}).get("nodes")) or []:
            if short_branch((lb.get("ref") or {}).get("name") or "") == name:
                return {"number": iss.get("number"), "id": iss.get("id"), "via": "linked-branch"}
    return None


def issue_from_branch_name(branch: str):
    """Fallback: parse a leading `123-foo` issue number from the branch name.

    NEVER reads `Closes #N`. Returns None if the name has no numeric prefix.
    """
    m = _BRANCH_NAME_RE.match(short_branch(branch))
    if not m:
        return None
    return {"number": int(m.group(1)), "id": None, "via": "branch-name"}


def resolve_issue_for_branch(owner: str, repo: str, branch: str, *, token: str | None = None):
    """LINKED BRANCH first, branch-name parse fallback. No `Closes #N`."""
    linked = issue_from_linked_branch(owner, repo, branch, token=token)
    if linked and linked.get("number"):
        return linked
    return issue_from_branch_name(branch)


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

_ISSUE_ID_BY_NUMBER = """
query($owner:String!, $repo:String!, $number:Int!){
  repository(owner:$owner, name:$repo){ issue(number:$number){ id number } }
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

_UPDATE_STATUS = (
    "mutation($project:ID!,$item:ID!,$field:ID!,$opt:String!){"
    "updateProjectV2ItemFieldValue(input:{projectId:$project,itemId:$item,fieldId:$field,"
    "value:{singleSelectOptionId:$opt}}){projectV2Item{id}}}"
)


class ProjectStatus:
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


def issue_id_by_number(owner: str, repo: str, number: int, *, token: str | None = None) -> str:
    data = graphql(_ISSUE_ID_BY_NUMBER, {"owner": owner, "repo": repo, "number": number}, token=token)
    iss = (data.get("repository") or {}).get("issue") or {}
    if not iss.get("id"):
        raise GhError(f"issue {owner}/{repo}#{number} not found", code=3)
    return iss["id"]


def current_status_for_issue(issue_id: str, project_number: int, *, token: str | None = None):
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


# --------------------------------------------------------------------------- #
# Event -> target Status mapping (the pure, fully-testable core).
# --------------------------------------------------------------------------- #
def target_for_event(event_name: str, action: str | None, *, draft: bool) -> str | None:
    """Map a repo event to the Status target board-sync would advance toward.

    push                         -> In Progress (work has started on the branch)
    pull_request, DRAFT          -> In Progress (draft honesty; holds until ready)
    pull_request, READY          -> In Review
    Returns None for events board-sync ignores.
    """
    if event_name == "push":
        return "In Progress"
    if event_name == "pull_request":
        if draft:
            return "In Progress"
        return "In Review"
    return None


def apply_event(owner: str, repo: str, project_number: int, *, event_name: str,
                action: str | None, branch: str, draft: bool,
                pr_issue_number: int | None = None, token: str | None = None) -> dict:
    """Resolve the issue + advance its Status for this event (idempotent/monotonic).

    `branch` is the head ref (the pushed branch or the PR head branch). The issue
    is resolved LINKED-BRANCH-FIRST then by branch name unless a caller
    passes an already-known `pr_issue_number` (still never from `Closes #N`).
    """
    target = target_for_event(event_name, action, draft=draft)
    if target is None:
        return {"skipped": "event-ignored", "event": event_name, "action": action}

    if pr_issue_number is not None:
        link = {"number": int(pr_issue_number), "id": None, "via": "linked-branch"}
    else:
        link = resolve_issue_for_branch(owner, repo, branch, token=token)
    if not link or not link.get("number"):
        return {"skipped": "no-issue-link", "branch": short_branch(branch)}

    issue_id = link.get("id") or issue_id_by_number(owner, repo, link["number"], token=token)
    project = ProjectStatus(owner, project_number, token=token).resolve()
    item_id, current = current_status_for_issue(issue_id, project_number, token=token)
    if item_id is None:
        return {"skipped": "not-on-project", "issue": link["number"]}

    # MONOTONIC guard: only advance; a stale/replayed event is a no-op.
    to_write = advance_status(current, target)
    if to_write is None:
        return {"issue": link["number"], "from": current, "to": current,
                "wrote": False, "via": link["via"], "target": target}
    set_status(project, item_id, to_write)
    return {"issue": link["number"], "from": current, "to": to_write,
            "wrote": True, "via": link["via"], "target": target}


# --------------------------------------------------------------------------- #
# CLI — reads the GitHub event payload; documented exit codes; no secret print.
# --------------------------------------------------------------------------- #
def _print_json(obj) -> None:
    sys.stdout.write(_scrub(json.dumps(obj)) + "\n")


def _load_event(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _params_from_event(event_name: str, event: dict, ref_env: str | None):
    """Extract (action, branch, draft, pr_issue_number) from the event payload.

    For `pull_request` we use the PR's head ref + draft flag. For `push` we use
    GITHUB_REF / the event's `ref`. No closing-keyword parsing anywhere.
    """
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        head = (pr.get("head") or {}).get("ref") or ""
        return event.get("action"), head, bool(pr.get("draft")), None
    # push
    ref = event.get("ref") or ref_env or ""
    return None, ref, False, None


def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="board_sync.py", description="event-driven board Status sync")
    p.add_argument("--repo", required=True, help="owner/name of the consuming repo")
    p.add_argument("--project", type=int, required=True, help="org Project number")
    p.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    p.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    p.add_argument("--app-token", default="", help="App INSTALLATION token (never GITHUB_TOKEN)")
    p.add_argument("--project-owner", default="", help="org login owning the Project")
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
    project_owner = args.project_owner or os.environ.get("PROJECT_OWNER", owner_login)
    token = args.app_token or os.environ.get("GH_APP_TOKEN") or None
    if not args.event_name:
        sys.stderr.write("error: no --event-name / GITHUB_EVENT_NAME\n")
        return 2

    event = _load_event(args.event_path)
    action, branch, draft, pr_issue = _params_from_event(
        args.event_name, event, os.environ.get("GITHUB_REF")
    )

    try:
        out = apply_event(
            project_owner, repo_name, args.project,
            event_name=args.event_name, action=action, branch=branch, draft=draft,
            pr_issue_number=pr_issue, token=token,
        )
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
