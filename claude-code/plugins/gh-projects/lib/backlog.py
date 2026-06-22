#!/usr/bin/env python3
"""gh-projects backlog — the DETERMINISTIC staging-ledger engine behind the
resumable `create-issues` intake pipeline.

Intake is a three-stage pipeline (decompose -> refine -> promote) that does NOT
create a GitHub issue up front. Instead each candidate is captured as a local
DRAFT in a git-tracked staging area, refined there (body + acceptance criteria),
and only PROMOTED to a real board issue once it passes the readiness bar. This
file owns that staging area: the on-disk drafts + a JSON ledger, and the
deterministic lifecycle/promote logic the skill must not invent in prose.

Why a local staging area at all:
  * Resumable — an interrupted intake leaves finished drafts on disk; re-running
    create-issues picks up exactly the unpromoted ones, never re-doing work.
  * Clarifying questions resolve against the LOCAL draft file — there is no
    GitHub issue yet, so nothing half-formed leaks onto the board.
  * Promotion is ONE-WAY: once a draft becomes a canonical issue, its staging
    file is removed so it can never be edited as a competing second source of
    truth. The GitHub issue is the canonical unit thereafter.

Where the staging area lives:
  At the GIT ROOT of the repo create-issues runs in — `<git-root>/.gh-projects/
  backlog/`. Resolved via `git rev-parse --show-toplevel` so it works from any
  subdirectory, and is git-TRACKED (team-visible — drafts are shared work, not
  scratch). The root is injectable (a `--root` flag / function param) so the
  offline tests run in a throwaway temp git repo with no network.

What stays out of this file:
  * No metered AI — the AC/body authoring is the skill's delegation to spec-ops;
    here we only record/serve drafts and drive the deterministic promote.
  * Projects v2 writes (add_item / write_field / add_sub_issue / add_blocked_by)
    are lib/gh.py's, run with the GitHub App installation token, never
    GITHUB_TOKEN; the issue-create itself rides lib/gh.py's injectable RUN seam.
  * Size / Epic-split / ready-gate / tier->rigor decisions are lib/intake.py's.

Stdlib only. CLI exit codes: 0 ok · 2 usage/validation · 3 not found · 1 unexpected.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import gh
import intake
import pm

# --------------------------------------------------------------------------- #
# Errors — mirror the lib's error-class + CLI exit map.
# --------------------------------------------------------------------------- #
class BacklogError(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Draft lifecycle + ledger shape.
# --------------------------------------------------------------------------- #
# The draft moves stub -> drafting -> ready -> promoted. Only a `ready` draft may
# promote; a stub/drafting one is refused with a reason. `promoted` is terminal —
# the staging file is removed and the draft is never re-edited.
LIFECYCLE = ("stub", "drafting", "ready", "promoted")

# The directory convention at the git root (tracked, team-visible).
STAGING_SUBDIR = os.path.join(".gh-projects", "backlog")
LEDGER_NAME = "ledger.json"
REGISTRY_NAME = "registry.json"  # the pm.py PM-#### registry, alongside the ledger

# The PM-triage fields promote sets on the board item (exact fields.json names).
# Size/Tier/Type/Priority are single-selects; PM-ID/Spec are text. Spec is only
# set for the full-rigor (T3) tier; T1/T2 leave it empty.
TRIAGE_SINGLE_SELECTS = ("Type", "Tier", "Priority", "Size")
TRIAGE_TEXT_FIELDS = ("PM-ID", "Spec")

# The documented `list` columns (rendered verbatim by the skill).
LIST_COLUMNS = ("slug", "title", "status", "type", "tier", "size", "priority",
                "parent", "target_repo", "pm_id", "issue", "file")


# --------------------------------------------------------------------------- #
# Staging-area resolution.
# --------------------------------------------------------------------------- #
def git_root(start: str | None = None) -> str:
    """Resolve the git toplevel of `start` (defaults to cwd).

    Uses `git rev-parse --show-toplevel` so the staging area resolves to the same
    `<git-root>/.gh-projects/backlog/` no matter which subdirectory create-issues
    runs from. Raises BacklogError(3) when not inside a git work tree.
    """
    cwd = start or os.getcwd()
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
    except OSError as e:  # git not installed
        raise BacklogError(f"cannot run git: {e}", code=1)
    if proc.returncode != 0:
        raise BacklogError(
            f"not a git work tree at {cwd!r}; the staging area lives at the git root",
            code=3,
        )
    return proc.stdout.strip()


class Staging:
    """The on-disk staging area + its JSON ledger.

    `root` is the git toplevel (resolved or injected). The ledger persists across
    sessions so an interrupted intake resumes the unpromoted drafts.
    """

    def __init__(self, root: str):
        self.root = root
        self.dir = os.path.join(root, STAGING_SUBDIR)
        self.ledger_path = os.path.join(self.dir, LEDGER_NAME)
        self.registry_path = os.path.join(self.dir, REGISTRY_NAME)

    @classmethod
    def resolve(cls, root: str | None = None, start: str | None = None) -> "Staging":
        """Build a Staging at an explicit `root`, else at the git toplevel of `start`."""
        return cls(root if root else git_root(start))

    # -- ledger I/O (diff-before-mutate) ----------------------------------- #
    def load(self) -> dict:
        """Read the ledger, or an empty one. {"drafts": {slug: entry}}."""
        if not os.path.isfile(self.ledger_path):
            return {"drafts": {}}
        with open(self.ledger_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "drafts" not in data:
            raise BacklogError(f"corrupt ledger at {self.ledger_path}", code=1)
        return data

    def _save(self, data: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        with open(self.ledger_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")

    def draft_file(self, slug: str) -> str:
        return os.path.join(self.dir, f"{slug}.md")


# --------------------------------------------------------------------------- #
# Slug + entry construction.
# --------------------------------------------------------------------------- #
_SLUG_OK = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    s = _SLUG_OK.sub("-", str(title).strip().lower()).strip("-")
    if not s:
        raise BacklogError("title produces an empty slug; give a non-empty title")
    return s[:80]


def _new_entry(*, slug, title, type_=None, tier=None, size=None, priority=None,
               parent=None, target_repo=None, file_path=None) -> dict:
    """A fresh ledger entry. Records the decompose tree + proposed triage fields.

    On promote the entry additionally gains: pm_id, issue (number), and — for the
    full-rigor tier — spec (the published deep-spec path).
    """
    return {
        "slug": slug,
        "title": title,
        "type": type_,
        "tier": tier,
        "size": size,
        "priority": priority,
        "parent": parent,            # epic slug this draft is a sub-issue of
        "blocked_by": [],            # sibling slugs this draft is blocked by
        "target_repo": target_repo,  # may be unset until promote; required to promote
        "file": file_path,
        "status": "stub",
        "pm_id": None,
        "issue": None,
        "spec": None,
    }


# --------------------------------------------------------------------------- #
# add — capture a draft stub (its file + a ledger entry).
# --------------------------------------------------------------------------- #
def add_draft(staging: "Staging", *, title, type_=None, tier=None, size=None,
              priority=None, parent=None, target_repo=None, body="",
              force=False) -> dict:
    """Capture a new draft: a front-matter'd staging file + a ledger entry.

    Dry-by-default: without `force` returns the planned slug/file/entry and writes
    nothing. With `force` writes the draft file (front-matter via pm.py) and the
    ledger entry. Idempotent: re-adding the same slug returns the existing entry
    unchanged (never clobbers an in-progress draft).
    """
    slug = slugify(title)
    data = staging.load()
    if slug in data["drafts"]:
        return {"action": "exists", "slug": slug, "entry": data["drafts"][slug],
                "applied": False}
    file_path = os.path.join(STAGING_SUBDIR, f"{slug}.md")
    entry = _new_entry(slug=slug, title=title, type_=type_, tier=tier, size=size,
                       priority=priority, parent=parent, target_repo=target_repo,
                       file_path=file_path)
    if not force:
        return {"action": "add", "slug": slug, "entry": entry, "applied": False}
    # Write the draft file: a front-matter header (round-trips via pm.py) + body.
    from collections import OrderedDict
    fm = OrderedDict()
    fm["title"] = title
    if type_:
        fm["type"] = type_
    if tier:
        fm["tier"] = tier
    fm["status"] = "stub"
    os.makedirs(staging.dir, exist_ok=True)
    with open(staging.draft_file(slug), "w", encoding="utf-8") as fh:
        fh.write(pm.compose(fm, body or "\n"))
    data["drafts"][slug] = entry
    staging._save(data)
    return {"action": "add", "slug": slug, "entry": entry, "applied": True}


# --------------------------------------------------------------------------- #
# set-status / set-field — advance the lifecycle, fill proposed triage fields.
# --------------------------------------------------------------------------- #
def _require(staging: "Staging", data: dict, slug: str) -> dict:
    entry = data["drafts"].get(slug)
    if entry is None:
        raise BacklogError(f"no draft {slug!r} in the staging area", code=3)
    return entry


def set_status(staging: "Staging", slug: str, status: str, *, force=False) -> dict:
    """Move a draft along stub -> drafting -> ready. Never set `promoted` here —
    that is promote()'s terminal write. Idempotent (same status = no-op)."""
    if status not in ("stub", "drafting", "ready"):
        raise BacklogError(
            f"set-status target must be stub/drafting/ready (got {status!r}); "
            "`promoted` is set only by promote", code=2)
    data = staging.load()
    entry = _require(staging, data, slug)
    if entry["status"] == "promoted":
        raise BacklogError(f"{slug!r} is promoted (canonical); staging never re-edits it",
                           code=2)
    if entry["status"] == status:
        return {"action": "set-status", "slug": slug, "status": status,
                "changed": False, "applied": False}
    if not force:
        return {"action": "set-status", "slug": slug, "status": status,
                "changed": True, "applied": False}
    entry["status"] = status
    staging._save(data)
    return {"action": "set-status", "slug": slug, "status": status,
            "changed": True, "applied": True}


def set_fields(staging: "Staging", slug: str, *, type_=None, tier=None, size=None,
               priority=None, target_repo=None, spec=None, force=False) -> dict:
    """Upsert a draft's proposed triage fields / target repo. Dry-by-default."""
    data = staging.load()
    entry = _require(staging, data, slug)
    if entry["status"] == "promoted":
        raise BacklogError(f"{slug!r} is promoted (canonical); staging never re-edits it",
                           code=2)
    updates = {k: v for k, v in (
        ("type", type_), ("tier", tier), ("size", size),
        ("priority", priority), ("target_repo", target_repo), ("spec", spec),
    ) if v is not None}
    if not force:
        return {"action": "set-fields", "slug": slug, "updates": updates, "applied": False}
    entry.update(updates)
    staging._save(data)
    return {"action": "set-fields", "slug": slug, "updates": updates, "applied": True}


# --------------------------------------------------------------------------- #
# link — build the epic / sub-issue tree (the decompose DAG).
# --------------------------------------------------------------------------- #
def link_draft(staging: "Staging", child_slug: str, *, parent=None,
               blocked_by=None, force=False) -> dict:
    """Link a draft into the decompose tree: a parent Epic slug and/or sibling
    blocked-by slugs. Validates every referenced slug exists. Dry-by-default."""
    data = staging.load()
    child = _require(staging, data, child_slug)
    if child["status"] == "promoted":
        raise BacklogError(f"{child_slug!r} is promoted (canonical); staging never re-edits it",
                           code=2)
    if parent is not None:
        if parent == child_slug:
            raise BacklogError("a draft cannot be its own parent", code=2)
        _require(staging, data, parent)
    blockers = list(blocked_by or [])
    for b in blockers:
        if b == child_slug:
            raise BacklogError("a draft cannot block itself", code=2)
        _require(staging, data, b)
    if not force:
        return {"action": "link", "slug": child_slug, "parent": parent,
                "blocked_by": blockers, "applied": False}
    if parent is not None:
        child["parent"] = parent
    if blockers:
        child["blocked_by"] = sorted(set(child.get("blocked_by") or []) | set(blockers))
    staging._save(data)
    return {"action": "link", "slug": child_slug, "parent": child.get("parent"),
            "blocked_by": child.get("blocked_by"), "applied": True}


# --------------------------------------------------------------------------- #
# list / show — render the ledger.
# --------------------------------------------------------------------------- #
def list_drafts(staging: "Staging") -> dict:
    """Return the drafts as documented columns + their statuses."""
    data = staging.load()
    rows = []
    for slug in sorted(data["drafts"]):
        e = data["drafts"][slug]
        rows.append({col: e.get(col) for col in LIST_COLUMNS})
    return {"columns": list(LIST_COLUMNS), "rows": rows}


def show_draft(staging: "Staging", slug: str) -> dict:
    data = staging.load()
    return {"slug": slug, "entry": _require(staging, data, slug)}


# --------------------------------------------------------------------------- #
# promote — the readiness-gated, one-way, idempotent board-creation.
# --------------------------------------------------------------------------- #
def _read_draft_body(staging: "Staging", slug: str) -> tuple:
    """Return (front_matter, body) of the draft file, or ({}, '') if absent."""
    path = staging.draft_file(slug)
    if not os.path.isfile(path):
        return {}, ""
    with open(path, "r", encoding="utf-8") as fh:
        return pm.split_front_matter(fh.read())


def _gh_issue_create(repo: str, title: str, body: str) -> dict:
    """Create the real GitHub issue via the injectable lib/gh.py RUN seam.

    `gh issue create` is a repo write authed by `gh` itself — only the downstream
    Projects v2 writes require the App installation token. Returns {number, url}.
    """
    out = gh.RUN(["issue", "create", "--repo", repo, "--title", title,
                  "--body", body or ""])
    url = (out or "").strip().splitlines()[-1] if (out or "").strip() else None
    number = None
    if url:
        m = re.search(r"/issues/(\d+)\s*$", url)
        if m:
            number = int(m.group(1))
    return {"number": number, "url": url}


def promote_draft(staging: "Staging", slug: str, *, owner, project_number,
                  force=False) -> dict:
    """Promote a `ready` draft into a canonical board issue.

    Sequence (only the writes happen under `force`; otherwise it is a preview):
      1. READINESS GATE — refuse a stub/drafting draft WITH A REASON; only `ready`
         promotes. A target repo is REQUIRED (refuse with a reason if unset).
      2. IDEMPOTENT NO-OP — an already-`promoted` draft reads its recorded issue
         number and returns without creating a duplicate.
      3. Allocate a PM-#### (pm.py, registry-backed) for the issue's PM-ID.
      4. T3 (full rigor) PUBLISHES the deep spec to specs/<slug>.md in the target
         repo (a durable path, NOT the staging draft) and Spec links it; T1/T2
         leave Spec empty and the draft body becomes the issue body.
      5. `gh issue create` (repo write via gh auth), then the Projects v2 writes —
         add_item / write_field (Type/Tier/Priority/Size/PM-ID/Spec) /
         add_sub_issue / add_blocked_by — ALL with the App installation token,
         never GITHUB_TOKEN. The item lands at Backlog (no Status write here).
      6. ONE-WAY — mark the draft `promoted`, REMOVE its staging file, and record
         the pm_id / issue number / published spec path in the ledger.

    Returns a plan dict; `applied` is True only under `force`.
    """
    data = staging.load()
    entry = _require(staging, data, slug)

    # (2) idempotent no-op for an already-promoted draft — never a duplicate issue.
    if entry["status"] == "promoted":
        return {"action": "promote", "slug": slug, "applied": False,
                "noop": True, "issue": entry.get("issue"), "pm_id": entry.get("pm_id"),
                "reason": "already promoted; reusing the recorded issue (no duplicate)"}

    # (1) readiness gate.
    if entry["status"] != "ready":
        return {"action": "promote", "slug": slug, "applied": False, "ready": False,
                "reason": f"draft is {entry['status']!r}, not 'ready' — refused promote "
                          "(refine it to ready first)"}
    target_repo = entry.get("target_repo")
    if not target_repo:
        return {"action": "promote", "slug": slug, "applied": False, "ready": False,
                "reason": "target repo unset — required to promote (the issue needs a "
                          "destination repo); set it on the draft first"}

    tier = intake.normalize_tier(entry["tier"]) if entry.get("tier") else None
    is_full = bool(tier and intake.TIER_RIGOR.get(tier, {}).get("rigor") == "full")
    _fm, body = _read_draft_body(staging, slug)

    spec_path = f"specs/{slug}.md" if is_full else None
    parent = entry.get("parent")
    blockers = list(entry.get("blocked_by") or [])

    plan = {
        "action": "promote",
        "slug": slug,
        "ready": True,
        "target_repo": target_repo,
        "title": entry["title"],
        "fields": {
            "Type": entry.get("type"),
            "Tier": tier,
            "Priority": entry.get("priority"),
            "Size": entry.get("size"),
            "Spec": spec_path,
        },
        "spec_publish": spec_path,
        "parent": parent,
        "blocked_by": blockers,
        "lands_at": "Backlog",
    }
    if not force:
        plan["applied"] = False
        return plan

    # (3) allocate the PM-#### now (registry-backed, monotonic).
    pm_id = pm.allocate_id(staging.registry_path)
    plan["fields"]["PM-ID"] = pm_id

    # (4) T3: publish the deep spec to a durable path in the TARGET repo. This
    #     published spec persists; it is NOT the staging draft.
    published_spec = None
    if is_full:
        abs_spec = os.path.join(staging.root, spec_path)
        os.makedirs(os.path.dirname(abs_spec), exist_ok=True)
        with open(abs_spec, "w", encoding="utf-8") as fh:
            fh.write(body or "")
        published_spec = spec_path

    # (5a) create the issue (repo write via gh auth).
    created = _gh_issue_create(target_repo, entry["title"], body)
    issue_number = created["number"]

    # (5b) Projects v2 writes — App installation token, never GITHUB_TOKEN.
    proj = gh.Project(owner, project_number).resolve()
    content_id = gh.issue_node_id(target_repo, issue_number)
    gh.add_item(proj.id, content_id)
    for fname in TRIAGE_SINGLE_SELECTS:
        val = plan["fields"].get(fname)
        if val:
            gh.write_field(proj, content_id, fname, val)
    if pm_id:
        gh.write_field(proj, content_id, "PM-ID", pm_id)
    if spec_path:
        gh.write_field(proj, content_id, "Spec", spec_path)

    # (5c) re-establish the recorded parent/sub-issue + blocked-by edges by the
    #      promoted issue numbers of the linked drafts.
    if parent:
        parent_entry = data["drafts"].get(parent) or {}
        parent_issue = parent_entry.get("issue")
        if parent_issue:
            parent_id = gh.issue_node_id(target_repo, parent_issue)
            gh.add_sub_issue(parent_id, content_id)
    for b in blockers:
        b_entry = data["drafts"].get(b) or {}
        b_issue = b_entry.get("issue")
        if b_issue:
            gh.add_blocked_by(target_repo, issue_number, b_issue)

    # (6) one-way: mark promoted, REMOVE the staging file, record the results.
    entry["status"] = "promoted"
    entry["pm_id"] = pm_id
    entry["issue"] = issue_number
    entry["spec"] = published_spec
    draft_path = staging.draft_file(slug)
    if os.path.isfile(draft_path):
        os.remove(draft_path)
    staging._save(data)

    plan.update({
        "applied": True,
        "pm_id": pm_id,
        "issue": issue_number,
        "url": created["url"],
        "spec_published": published_spec,
        "staging_file_removed": True,
    })
    return plan


# --------------------------------------------------------------------------- #
# CLI — documented exit codes 0/2/3/1.
# --------------------------------------------------------------------------- #
def _staging(args) -> "Staging":
    return Staging.resolve(getattr(args, "root", None))


def _emit(obj) -> None:
    sys.stdout.write(gh._scrub(json.dumps(obj, indent=2)) + "\n")


def _cmd_add(args) -> int:
    res = add_draft(_staging(args), title=args.title, type_=args.type, tier=args.tier,
                    size=args.size, priority=args.priority, parent=args.parent,
                    target_repo=args.repo, body=args.body or "", force=args.force)
    _emit(res)
    return 0


def _cmd_set_status(args) -> int:
    _emit(set_status(_staging(args), args.slug, args.status, force=args.force))
    return 0


def _cmd_set_fields(args) -> int:
    _emit(set_fields(_staging(args), args.slug, type_=args.type, tier=args.tier,
                     size=args.size, priority=args.priority, target_repo=args.repo,
                     spec=args.spec, force=args.force))
    return 0


def _cmd_link(args) -> int:
    _emit(link_draft(_staging(args), args.slug, parent=args.parent,
                     blocked_by=args.blocked_by, force=args.force))
    return 0


def _cmd_list(args) -> int:
    _emit(list_drafts(_staging(args)))
    return 0


def _cmd_show(args) -> int:
    _emit(show_draft(_staging(args), args.slug))
    return 0


def _cmd_promote(args) -> int:
    res = promote_draft(_staging(args), args.slug, owner=args.owner,
                        project_number=args.number, force=args.force)
    _emit(res)
    # A refused (not-ready / no-repo) promote is a validation refusal -> exit 2.
    if res.get("ready") is False:
        return 2
    return 0


def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="backlog.py",
                                description="gh-projects staging-ledger engine")
    p.add_argument("--root", default=None,
                   help="staging git-root override (default: git rev-parse --show-toplevel)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("add", help="capture a draft stub (file + ledger entry)")
    sp.add_argument("--title", required=True)
    sp.add_argument("--type", default=None)
    sp.add_argument("--tier", default=None)
    sp.add_argument("--size", default=None)
    sp.add_argument("--priority", default=None)
    sp.add_argument("--parent", default=None, help="parent Epic slug")
    sp.add_argument("--repo", default=None, dest="repo", help="target owner/name (optional until promote)")
    sp.add_argument("--body", default=None)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_add)

    sp = sub.add_parser("set-status", help="advance a draft (stub/drafting/ready)")
    sp.add_argument("slug")
    sp.add_argument("status", choices=["stub", "drafting", "ready"])
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_set_status)

    sp = sub.add_parser("set-fields", help="upsert a draft's proposed triage fields / target repo")
    sp.add_argument("slug")
    sp.add_argument("--type", default=None)
    sp.add_argument("--tier", default=None)
    sp.add_argument("--size", default=None)
    sp.add_argument("--priority", default=None)
    sp.add_argument("--repo", default=None, dest="repo", help="target owner/name")
    sp.add_argument("--spec", default=None)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_set_fields)

    sp = sub.add_parser("link", help="link a draft into the epic/sub-issue tree")
    sp.add_argument("slug")
    sp.add_argument("--parent", default=None, help="parent Epic slug")
    sp.add_argument("--blocked-by", dest="blocked_by", action="append", default=[],
                    help="sibling slug this draft is blocked by (repeatable)")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_link)

    sp = sub.add_parser("list", help="render the drafts + statuses (documented columns)")
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("show", help="show one draft's full ledger entry")
    sp.add_argument("slug")
    sp.set_defaults(func=_cmd_show)

    sp = sub.add_parser("promote", help="promote a ready draft to a board issue (App-token writes)")
    sp.add_argument("slug")
    sp.add_argument("--owner", required=True, help="org login")
    sp.add_argument("--number", type=int, required=True, help="project number")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_promote)
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        return args.func(args)
    except (BacklogError, pm.PmError, gh.GhError, intake.IntakeError) as e:
        sys.stderr.write("error: " + gh._scrub(str(e)) + "\n")
        return getattr(e, "code", 1)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + gh._scrub(str(e)) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
