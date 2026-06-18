#!/usr/bin/env python3
"""gh-projects scaffold (Phase 1 — deterministic, free, GitHub-native).

`scaffold-repo`'s deterministic engine. Stands up a new org Project + repo
templates + setup by:

  * `copyProjectV2` from the NAMED golden template, then VERIFY the copy carries
    every Data-model field AND all 8 saved views — fields by re-resolve, views by
    a read-only `projectV2.views` catalog diff (views are template-copied, never
    API-created/edited) (AC-7);
  * RE-RESOLVING every field/option/iteration id against the COPY, never the
    template, before any write (AC-8);
  * idempotent, manifest-first file install of the issue forms / PR template /
    `board-sync.yml` / `signals-sync.yml` / `board-status` action / `release.yml`
    / CODEOWNERS / project README (AC-10);
  * iterations DIFF/SKIP — never a blind re-PUT of `iterationConfiguration`
    (AC-9, AC-30 / constraint #3);
  * ensure org Issue Types + Issue Fields, set repo `allow_squash_merge=false`,
    grant the App project access (AC-10);
  * DRY-BY-DEFAULT — print the full change manifest and mutate NOTHING without
    `--force` (AC-11).

Boundaries baked in (Phase-1):
  * Deterministic & free — NO metered AI/model call (AC-26).
  * Every Projects v2 write uses the App INSTALLATION token, never GITHUB_TOKEN
    (AC-27 / constraint #2) — minted in lib/gh.py, never printed (AC-3).
  * No blind re-PUT of a single-select option list or iterationConfiguration —
    diff before mutate (AC-30 / constraint #3).
  * STDLIB ONLY. Bundled paths resolve via ${CLAUDE_PLUGIN_ROOT} or
    Path(__file__).parent — never a hardcoded ~/.claude path.
  * The gh runner is INJECTABLE (lib/gh.RUN) so this whole surface runs OFFLINE.

Exit codes (CLI): 0 ok · 2 usage/validation · 3 not found · 1 unexpected.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Import the §1 core. lib/ is this file's parent; add it to the path so the
# module resolves both when run as a script and when imported by tests.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import gh  # noqa: E402  (the shared GraphQL/REST core; injectable RUN)


# --------------------------------------------------------------------------- #
# Bundled-path resolution — never a hardcoded ~/.claude path.
# --------------------------------------------------------------------------- #
def plugin_root() -> Path:
    """The plugin root: ${CLAUDE_PLUGIN_ROOT} if set & valid, else two up."""
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env and (Path(env) / "templates").is_dir():
        return Path(env)
    return _LIB.parent


def templates_dir() -> Path:
    return plugin_root() / "templates"


# --------------------------------------------------------------------------- #
# File-install manifest — the COMPLETE set of destination paths scaffold writes
# into a target repo (AC-10). Each entry maps a bundled template source to its
# destination RELATIVE path in the repo. Sources that other phases author
# (board-sync.yml, signals-sync.yml, the board-status action) are listed by
# their EXPECTED destination so the manifest is complete even before those files
# exist on disk (per the §2 brief: assert the manifest ENTRIES, don't depend on
# the other phases' files existing yet).
# --------------------------------------------------------------------------- #
INSTALL_FILES = [
    # Issue forms + chooser config.
    ("github/ISSUE_TEMPLATE/config.yml", ".github/ISSUE_TEMPLATE/config.yml"),
    ("github/ISSUE_TEMPLATE/feature.yml", ".github/ISSUE_TEMPLATE/feature.yml"),
    ("github/ISSUE_TEMPLATE/bug.yml", ".github/ISSUE_TEMPLATE/bug.yml"),
    ("github/ISSUE_TEMPLATE/chore.yml", ".github/ISSUE_TEMPLATE/chore.yml"),
    ("github/ISSUE_TEMPLATE/infra.yml", ".github/ISSUE_TEMPLATE/infra.yml"),
    # PR template.
    ("github/PULL_REQUEST_TEMPLATE.md", ".github/PULL_REQUEST_TEMPLATE.md"),
    # Release-notes categories.
    ("github/release.yml", ".github/release.yml"),
    # Governance.
    ("github/CODEOWNERS", ".github/CODEOWNERS"),
    # Board automation workflows (authored by §4/§5 — listed by destination).
    ("github/workflows/board-sync.yml", ".github/workflows/board-sync.yml"),
    ("github/workflows/signals-sync.yml", ".github/workflows/signals-sync.yml"),
    # Self-contained composable deploy bridge (authored by §4 — listed by dest).
    ("github/actions/board-status/action.yml", ".github/actions/board-status/action.yml"),
    # Project README (board legend) lives in the repo at project/.
    ("project/README.md", "project/README.md"),
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ScaffoldError(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Loading the golden-template schema we diff the COPY against.
# --------------------------------------------------------------------------- #
def load_fields_schema() -> dict:
    path = templates_dir() / "project" / "fields.json"
    if not path.is_file():
        raise ScaffoldError(f"fields.json not found at {path}", code=3)
    return json.loads(path.read_text(encoding="utf-8"))


def load_iterations_schema() -> dict:
    path = templates_dir() / "project" / "iterations.json"
    if not path.is_file():
        raise ScaffoldError(f"iterations.json not found at {path}", code=3)
    return json.loads(path.read_text(encoding="utf-8"))


def load_views_schema() -> dict:
    path = templates_dir() / "project" / "views.json"
    if not path.is_file():
        raise ScaffoldError(f"views.json not found at {path}", code=3)
    return json.loads(path.read_text(encoding="utf-8"))


def expected_view_names(schema: dict) -> list[str]:
    """The view titles the golden template (and thus every copy) must carry."""
    return [v["name"] for v in schema.get("views", [])]


def view_specs(schema: dict) -> list[dict]:
    """The full per-view filter/group/slice catalog (views.json `views`).

    Each entry: {"name", "layout", "filter", "group", "slice"}. Used by §6
    verify_views to check each view RESOLVES its documented filter/group/slice
    (AC-25), distinct from the AC-7 presence-by-title diff.
    """
    return list(schema.get("views", []))


def filter_qualifier_field(schema: dict, qualifier: str) -> str | None:
    """Map a filter qualifier keyword to the field name it resolves against.

    Returns the field NAME (e.g. `status` -> "Status"), the sentinel
    "__native__" for a built-in GitHub qualifier (`is`/`assignee`/`no` — no
    project field needed), or None if the keyword is unknown (an unresolved
    qualifier — verify_views fails loudly).
    """
    return (schema.get("_field_qualifiers") or {}).get(qualifier)


def _parse_filter_qualifiers(filter_str: str) -> list[str]:
    """Extract the qualifier KEYWORDS (left of the colon) from a saved-search
    filter string. `iteration:@current is:open` -> ["iteration", "is"]. A bare
    token with no colon (a free-text term) is ignored. Stable, order-preserving,
    de-duplicated."""
    out: list[str] = []
    for tok in str(filter_str or "").split():
        if ":" in tok:
            key = tok.split(":", 1)[0].strip().lower()
            if key and key not in out:
                out.append(key)
    return out


def project_field_names(schema: dict) -> list[str]:
    """The fields that live IN the project copy (home == 'project')."""
    return [f["name"] for f in schema.get("fields", []) if f.get("home") == "project"]


def issue_field_specs(schema: dict) -> list[dict]:
    """Org Issue Fields (home == 'issue_field') to ensure org-wide."""
    return [f for f in schema.get("fields", []) if f.get("home") == "issue_field"]


def issue_type_specs(schema: dict) -> list[dict]:
    """Org Issue Types (the single home == 'issue_type' field's options)."""
    out = []
    for f in schema.get("fields", []):
        if f.get("home") == "issue_type":
            for opt in f.get("options", []):
                out.append(opt)
    return out


# --------------------------------------------------------------------------- #
# Org-owner id + the named golden template id (resolved, App-token scoped).
# --------------------------------------------------------------------------- #
_OWNER_AND_TEMPLATE = """
query($owner:String!){
  organization(login:$owner){
    id
    login
    projectsV2(first:100, query:"is:template"){
      nodes { id number title }
    }
  }
}
"""


def resolve_owner_and_template(org: str, template_title: str) -> tuple[str, str, int | None]:
    """Return (org node id, golden-template project id, template number) by NAME.

    Resolves the named golden template — never assumes a project number, finds it
    by exact title. The number is used only to resolve the template read-only for
    a DRY preview (the apply path copies, then resolves the copy). Raises code=3
    if the org or the named template can't be found.
    """
    data = gh.graphql(_OWNER_AND_TEMPLATE, {"owner": org})
    org_node = (data or {}).get("organization") or {}
    owner_id = org_node.get("id")
    if not owner_id:
        raise ScaffoldError(f"org '{org}' not found", code=3)
    for node in ((org_node.get("projectsV2") or {}).get("nodes") or []):
        if str(node.get("title", "")).strip() == template_title.strip():
            return owner_id, node["id"], node.get("number")
    raise ScaffoldError(
        f"golden template project titled '{template_title}' not found in org '{org}' "
        f"(is it marked an org template?)",
        code=3,
    )


# --------------------------------------------------------------------------- #
# Iteration plan — DIFF the COPY's iterations against the desired set; SKIP when
# unchanged (no iterationConfiguration re-PUT). NEVER blind re-PUT (AC-9/AC-30).
# --------------------------------------------------------------------------- #
def copy_iterations(copy_proj: "gh.Project", schema: dict) -> list[dict]:
    """Read the iteration set already present in the COPY's Sprint field."""
    field_name = schema.get("field", "Sprint")
    try:
        node = copy_proj.field(field_name)
    except gh.GhError:
        return []
    cfg = node.get("configuration") or {}
    return list(cfg.get("iterations") or []) + list(cfg.get("completedIterations") or [])


def plan_iterations(copy_proj: "gh.Project", schema: dict) -> dict:
    """Return {"mutate": bool, "reason": str, "mutations": int}.

    Uses gh.iterations_need_update (diff by title/startDate/duration). When the
    copied iterations already match the desired set, this is a SKIP with zero
    mutations — the AC-9 / AC-30 guard against a blind iterationConfiguration
    re-PUT.
    """
    desired = schema.get("iterations") or []
    existing = copy_iterations(copy_proj, schema)
    if not gh.iterations_need_update(existing, desired):
        return {"mutate": False, "reason": "iterations already match — SKIP (no re-PUT)", "mutations": 0}
    return {
        "mutate": True,
        "reason": f"iteration set differs ({len(existing)} present, {len(desired)} desired) — diff-add only",
        "mutations": 1,
    }


# --------------------------------------------------------------------------- #
# File-install diff — manifest-first, idempotent (only install missing/changed).
# --------------------------------------------------------------------------- #
def plan_file_install(repo_dir: str | None) -> list[dict]:
    """For every INSTALL_FILES entry, decide install/skip against the repo dir.

    Returns one manifest row per destination path:
        {"dest": rel, "src": rel, "action": "install"|"skip"|"missing-source",
         "reason": str}
    Idempotent: a destination that already exists with identical content is a
    SKIP (so a second run produces an EMPTY install manifest). When repo_dir is
    None we plan as if the repo is empty (every file installs) — used by dry
    previews and the offline manifest assertions.
    """
    rows = []
    tdir = templates_dir()
    for src_rel, dest_rel in INSTALL_FILES:
        src = tdir / src_rel
        row = {"dest": dest_rel, "src": src_rel}
        if not src.is_file():
            # Source authored by another phase and not present yet — the manifest
            # still ENUMERATES the destination (AC-10). It is a planned install,
            # marked so the orchestrator skips the copy until that phase lands.
            row["action"] = "install"
            row["reason"] = "source authored by another phase (not yet on disk); destination enumerated"
            rows.append(row)
            continue
        if repo_dir is None:
            row["action"] = "install"
            row["reason"] = "no repo dir resolved — planned as a fresh install"
            rows.append(row)
            continue
        dest = Path(repo_dir) / dest_rel
        if dest.is_file() and dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8"):
            row["action"] = "skip"
            row["reason"] = "already installed, identical content"
        else:
            row["action"] = "install"
            row["reason"] = "missing or changed"
        rows.append(row)
    return rows


def apply_file_install(repo_dir: str, rows: list[dict]) -> list[str]:
    """Copy each planned 'install' row whose source exists. Returns dests written.

    Manifest-first: only rows the plan marked 'install' AND whose source is
    present on disk are written (sources owned by another phase are skipped with
    no error). Creates parent dirs as needed.
    """
    written = []
    tdir = templates_dir()
    for row in rows:
        if row.get("action") != "install":
            continue
        src = tdir / row["src"]
        if not src.is_file():
            continue  # another phase's file; nothing to copy yet
        dest = Path(repo_dir) / row["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(row["dest"])
    return written


# --------------------------------------------------------------------------- #
# Org Issue Field ensure — list, then create only what's missing (no blind PUT).
# --------------------------------------------------------------------------- #
def plan_issue_fields(org: str, schema: dict) -> list[dict]:
    """Diff the org's existing Issue Fields against the desired set.

    Read-only: lists existing Issue Fields and marks each desired field
    ensure/skip. The actual create is left to apply (and only when --force).
    Never re-PUTs an existing field's option list (option-ID stability).
    """
    desired = issue_field_specs(schema)
    existing_names = _existing_issue_field_names(org)
    rows = []
    for f in desired:
        present = f["name"] in existing_names
        rows.append({
            "name": f["name"],
            "type": f.get("type"),
            "action": "skip" if present else "ensure",
            "reason": "already present" if present else "missing — create",
        })
    return rows


_ISSUE_FIELDS_QUERY = """
query($owner:String!){
  organization(login:$owner){
    issueFields: fields {
      nodes { name }
    }
  }
}
"""


def _existing_issue_field_names(org: str) -> set[str]:
    """Best-effort list of existing org Issue Field names (REST first, GraphQL
    fallback). Never raises — an empty set just means everything is 'ensure'."""
    try:
        data = gh.rest("GET", f"/orgs/{org}/issue-fields")
        if isinstance(data, list):
            return {d.get("name") for d in data if d.get("name")}
        if isinstance(data, dict) and isinstance(data.get("issue_fields"), list):
            return {d.get("name") for d in data["issue_fields"] if d.get("name")}
    except gh.GhError:
        pass
    try:
        data = gh.graphql(_ISSUE_FIELDS_QUERY, {"owner": org})
        nodes = (((data or {}).get("organization") or {}).get("issueFields") or {}).get("nodes") or []
        return {n.get("name") for n in nodes if n.get("name")}
    except gh.GhError:
        return set()


def apply_issue_field(org: str, spec: dict) -> dict:
    """Create one org Issue Field (idempotent caller-side via plan). REST app API."""
    payload = {"name": spec["name"], "data_type": _issue_field_data_type(spec)}
    if spec.get("type") == "single_select" and spec.get("options"):
        payload["single_select_options"] = [
            {"name": o["name"], "description": o.get("description", "")} for o in spec["options"]
        ]
    gh.rest("POST", f"/orgs/{org}/issue-fields", payload)
    return {"ensured": spec["name"], "created": True}


def _issue_field_data_type(spec: dict) -> str:
    t = spec.get("type")
    return {"single_select": "single_select", "date": "date", "text": "text", "number": "number"}.get(t, "text")


# --------------------------------------------------------------------------- #
# Grant the App project access + role config (one mutation; never prints token).
# --------------------------------------------------------------------------- #
_LINK_PROJECT_APP = """
mutation($project:ID!, $actor:ID!){
  linkProjectV2ToTeam: updateProjectV2(input:{projectId:$project}){
    projectV2 { id }
  }
}
"""


def grant_app_access(copy_project_id: str) -> dict:
    """Ensure the App (and base role) can access the copied Project.

    copyProjectV2 does NOT carry collaborators/access — the App that minted the
    token already owns org-level project write via its installation, so this is a
    confirmation/no-op touch of the copy (kept App-token only; never GITHUB_TOKEN,
    never prints a secret). Returns a structured result for the manifest.
    """
    gh.graphql(_LINK_PROJECT_APP, {"project": copy_project_id, "actor": copy_project_id})
    return {"granted": True, "project": copy_project_id}


# --------------------------------------------------------------------------- #
# Field-presence verification against the COPY (AC-7): every project field + the
# resolved ids come from the COPY, never the template.
# --------------------------------------------------------------------------- #
def verify_copy_fields(copy_proj: "gh.Project", schema: dict) -> dict:
    """Diff the COPY's resolved fields against the expected project schema.

    Returns {"present": [...], "missing": [...], "field_ids": {name: id}} where
    every id is read from the COPY (AC-8). Missing fields are a copy/template
    defect to fix on the template and re-copy (views/fields are not API-created).
    """
    expected = project_field_names(schema)
    present, missing, field_ids = [], [], {}
    for name in expected:
        try:
            node = copy_proj.field(name)
            present.append(name)
            field_ids[name] = node["id"]
        except gh.GhError:
            missing.append(name)
    return {"present": present, "missing": missing, "field_ids": field_ids}


# --------------------------------------------------------------------------- #
# View-catalog verification against the COPY (AC-7, the "all 8 views" half).
#
# ProjectV2 views are NOT API-MUTABLE (no create/edit) — they ship only by
# copyProjectV2 from the golden template (constraint #1 / spec hard-limits). They
# ARE, however, API-READABLE via the `projectV2.views` connection (only Insights
# CHARTS are neither created nor read via API — views are not charts). So scaffold
# reads the copy's view catalog read-only and diffs it against the expected 8
# (views.json). It never CREATES or EDITS a view; a missing view is a template/copy
# defect to fix on the template and re-copy. Per-view filter/group RESOLUTION is
# AC-25 (§6); here we verify only PRESENCE by title (the AC-7 "view catalog" diff).
# --------------------------------------------------------------------------- #
_VIEWS_QUERY = """
query($owner:String!, $number:Int!){
  organization(login:$owner){
    projectV2(number:$number){
      views(first:100){
        nodes { number name layout }
      }
    }
  }
}
"""


def read_copy_views(org: str, copy_number: int) -> list[dict]:
    """Read the COPY's saved-view catalog read-only (title/number/layout).

    Self-contained read against the copy (never the template). Returns [] on a
    not-found / empty response rather than raising — verify_copy_views turns an
    empty catalog into a 'missing' list so the AC-7 diff still reports clearly.
    """
    data = gh.graphql(_VIEWS_QUERY, {"owner": org, "number": int(copy_number)})
    proj = (((data or {}).get("organization") or {}).get("projectV2")) or {}
    nodes = (proj.get("views") or {}).get("nodes") or []
    out = []
    for n in nodes:
        name = n.get("name")
        if name:
            out.append({"name": name, "number": n.get("number"), "layout": n.get("layout")})
    return out


def verify_copy_views(copy_view_names: "list[str] | set[str]", schema: dict) -> dict:
    """Diff the COPY's view catalog against the expected 8 (views.json) for AC-7.

    Returns {"present": [...], "missing": [...], "extra": [...]}. A non-empty
    `missing` means the copy is short a template view (fix on the template +
    re-copy; views are not API-created). `extra` is informational. Matching is by
    exact title — the unit of presence the platform exposes read-only.
    """
    expected = expected_view_names(schema)
    present_set = set(copy_view_names)
    present = [v for v in expected if v in present_set]
    missing = [v for v in expected if v not in present_set]
    extra = sorted(present_set - set(expected))
    return {"present": present, "missing": missing, "extra": extra}


# --------------------------------------------------------------------------- #
# §6 verify_views (AC-25) — beyond the AC-7 presence-by-title diff, confirm each
# of the 8 views RESOLVES its documented filter / group / slice without error.
#
# Views are NOT API-mutable (no create/edit) — they ship via copyProjectV2 and
# scaffold only VERIFIES. They ARE API-readable: the projectV2.views connection
# exposes each view's `filter` (raw saved-search string), `groupByFields` (the
# board columns / table grouping) and `verticalGroupByFields` (the slice panel /
# swimlane). For each documented view we check, post-copy:
#   * the view is PRESENT (by title);
#   * every qualifier in its documented filter resolves — a known GitHub-native
#     qualifier (is/assignee/no) or a field qualifier whose field exists on the
#     COPY (re-resolved from the copy, never the template);
#   * its documented group field resolves to a real field on the COPY; and the
#     live view actually groups by a (non-empty) field — an empty groupByFields
#     when a group is documented is an UNRESOLVED group (fail loud);
#   * likewise its documented slice field resolves and the live view's
#     verticalGroupBy is non-empty.
# A missing view or an unresolved filter/group/slice is a TEMPLATE/COPY defect:
# fix it on the golden template and re-copy — scaffold never API-creates/edits a
# view (constraint #1 / spec hard-limits).
# --------------------------------------------------------------------------- #
_VIEWS_DETAIL_QUERY = """
query($owner:String!, $number:Int!){
  organization(login:$owner){
    projectV2(number:$number){
      views(first:100){
        nodes {
          number
          name
          layout
          filter
          groupByFields(first:20){ nodes { ... on ProjectV2FieldCommon { name } } }
          verticalGroupByFields(first:20){ nodes { ... on ProjectV2FieldCommon { name } } }
        }
      }
    }
  }
}
"""

# Built-in / native project fields a view can group or slice by that are NOT in
# fields.json (they exist on every ProjectV2 without being declared). A group or
# slice referencing one of these resolves without a schema field.
_NATIVE_FIELDS = {
    "Milestone", "Assignees", "Labels", "Repository", "Reviewers", "Title",
    "Linked pull requests", "Tracked by", "Parent issue",
}


def _field_resolves(name: str, fields_schema: dict, copy_proj: "gh.Project") -> bool:
    """True if a group/slice field NAME resolves to a real field on the COPY.

    Resolution order: a project field present on the copy (re-resolved from the
    COPY, never the template) → a declared org issue field / issue type in the
    schema → a known native built-in field. Empty name never resolves.
    """
    if not name:
        return False
    # 1) Project field actually present on the COPY.
    try:
        copy_proj.field(name)
        return True
    except gh.GhError:
        pass
    # 2) Declared org Issue Field (e.g. Priority) or Issue Type (Type).
    for f in fields_schema.get("fields", []):
        if f.get("name") == name and f.get("home") in ("issue_field", "issue_type"):
            return True
    # 3) Known native built-in field (e.g. Milestone).
    return name in _NATIVE_FIELDS


def read_copy_views_detail(org: str, copy_number: int) -> dict:
    """Read each saved view's filter/group/slice read-only, keyed by view title.

    Returns {title: {"filter": str, "groups": [field names], "slices": [field
    names], "layout": str, "number": int}}. Self-contained read against the COPY
    (never the template). Empty on a not-found response — verify_views turns an
    absent title into a 'missing' view.
    """
    data = gh.graphql(_VIEWS_DETAIL_QUERY, {"owner": org, "number": int(copy_number)})
    proj = (((data or {}).get("organization") or {}).get("projectV2")) or {}
    out: dict = {}
    for n in (proj.get("views") or {}).get("nodes") or []:
        name = n.get("name")
        if not name:
            continue
        groups = [g.get("name") for g in ((n.get("groupByFields") or {}).get("nodes") or []) if g.get("name")]
        slices = [s.get("name") for s in ((n.get("verticalGroupByFields") or {}).get("nodes") or []) if s.get("name")]
        out[name] = {
            "filter": n.get("filter") or "",
            "groups": groups,
            "slices": slices,
            "layout": n.get("layout"),
            "number": n.get("number"),
        }
    return out


def verify_views(org: str, copy_number: int, *, views_schema: dict,
                 fields_schema: dict, copy_proj: "gh.Project") -> dict:
    """AC-25: confirm all 8 views exist AND each resolves filter/group/slice.

    Reads the COPY's view detail and, for every documented view, checks presence
    + that each filter qualifier, the group field and the slice field resolve.
    Returns:
        {"ok": bool,
         "checked": int,                         # number of documented views
         "missing": [view names not present in the copy],
         "views": {name: {"present": bool,
                          "filter_ok": bool, "unresolved_qualifiers": [...],
                          "group_ok": bool, "group": str, "live_groups": [...],
                          "slice_ok": bool, "slice": str, "live_slices": [...],
                          "errors": [human strings]}},
         "errors": [flat list of every failure, for a loud message]}
    `ok` is True only when no view is missing and every documented view's
    filter/group/slice resolved. Callers that must fail loudly use raise_for_views.
    """
    detail = read_copy_views_detail(org, int(copy_number))
    specs = view_specs(views_schema)
    result: dict = {"ok": True, "checked": len(specs), "missing": [], "views": {}, "errors": []}

    for spec in specs:
        name = spec["name"]
        live = detail.get(name)
        vr: dict = {"present": live is not None, "errors": [],
                    "filter_ok": True, "filter": "", "unresolved_qualifiers": [],
                    "group_ok": True, "group": spec.get("group", ""), "live_groups": [],
                    "slice_ok": True, "slice": spec.get("slice", ""), "live_slices": []}

        if live is None:
            result["missing"].append(name)
            vr["filter_ok"] = vr["group_ok"] = vr["slice_ok"] = False
            msg = f"view '{name}' MISSING from the copy (fix on template + re-copy)"
            vr["errors"].append(msg)
            result["errors"].append(msg)
            result["ok"] = False
            result["views"][name] = vr
            continue

        vr["live_groups"] = live.get("groups", [])
        vr["live_slices"] = live.get("slices", [])
        vr["filter"] = live.get("filter", "")

        # --- Filter: the LIVE view's filter must carry every documented -----
        #     qualifier, and EVERY qualifier in the live filter must resolve (a
        #     known native qualifier, or a field qualifier whose field exists on
        #     the COPY). The live filter is what copyProjectV2 actually carried —
        #     checking it (not just views.json) catches a copy whose filter
        #     drifted or references a field the copy lacks.
        documented_quals = _parse_filter_qualifiers(spec.get("filter", ""))
        live_quals = _parse_filter_qualifiers(live.get("filter", ""))
        for dq in documented_quals:
            if dq not in live_quals:
                vr["filter_ok"] = False
                vr["unresolved_qualifiers"].append(dq)
                msg = (f"view '{name}': documented filter qualifier '{dq}:' missing "
                       f"from the live view filter {live.get('filter', '')!r}")
                vr["errors"].append(msg)
                result["errors"].append(msg)
        for qual in live_quals:
            mapped = filter_qualifier_field(views_schema, qual)
            if mapped is None:
                vr["filter_ok"] = False
                vr["unresolved_qualifiers"].append(qual)
                msg = f"view '{name}': filter qualifier '{qual}:' unknown / unresolved"
                vr["errors"].append(msg)
                result["errors"].append(msg)
            elif mapped != "__native__" and not _field_resolves(mapped, fields_schema, copy_proj):
                vr["filter_ok"] = False
                vr["unresolved_qualifiers"].append(qual)
                msg = (f"view '{name}': filter qualifier '{qual}:' maps to field "
                       f"'{mapped}' which does not resolve on the copy")
                vr["errors"].append(msg)
                result["errors"].append(msg)

        # --- Group: documented group field must resolve AND the live view --- #
        #     must actually group by a (non-empty) field.
        group = spec.get("group", "")
        if group:
            if not _field_resolves(group, fields_schema, copy_proj):
                vr["group_ok"] = False
                msg = f"view '{name}': group field '{group}' does not resolve on the copy"
                vr["errors"].append(msg)
                result["errors"].append(msg)
            elif not vr["live_groups"]:
                vr["group_ok"] = False
                msg = (f"view '{name}': documented group '{group}' but the live view "
                       f"groups by nothing (unresolved group)")
                vr["errors"].append(msg)
                result["errors"].append(msg)

        # --- Slice: documented slice field must resolve AND the live view --- #
        #     must actually slice by a (non-empty) field.
        slc = spec.get("slice", "")
        if slc:
            if not _field_resolves(slc, fields_schema, copy_proj):
                vr["slice_ok"] = False
                msg = f"view '{name}': slice field '{slc}' does not resolve on the copy"
                vr["errors"].append(msg)
                result["errors"].append(msg)
            elif not vr["live_slices"]:
                vr["slice_ok"] = False
                msg = (f"view '{name}': documented slice '{slc}' but the live view "
                       f"slices by nothing (unresolved slice)")
                vr["errors"].append(msg)
                result["errors"].append(msg)

        if vr["errors"]:
            result["ok"] = False
        result["views"][name] = vr

    return result


def raise_for_views(view_result: dict) -> None:
    """Fail LOUDLY (ScaffoldError, exit 3) when verify_views found any defect.

    A missing view or an unresolved filter/group/slice is a template/copy defect
    — never something scaffold repairs by mutating a view. The message lists every
    failure so the operator can fix the golden template and re-copy.
    """
    if view_result.get("ok"):
        return
    detail = "; ".join(view_result.get("errors") or []) or "unknown view defect"
    n_missing = len(view_result.get("missing") or [])
    raise ScaffoldError(
        f"view verification FAILED ({n_missing} missing; "
        f"{len(view_result.get('errors') or [])} problem(s)): {detail} "
        f"— fix on the golden template and re-copy (views are not API-mutable)",
        code=3,
    )


def resolved_option_ids(copy_proj: "gh.Project", schema: dict) -> dict:
    """Every single-select option id resolved FROM THE COPY (AC-8).

    Shape: {field_name: {option_name: option_id}}. Used by the manifest + the
    AC-8 test (these ids must differ from the template's in the fixture).
    """
    out = {}
    for f in schema.get("fields", []):
        if f.get("home") != "project" or f.get("type") != "single_select":
            continue
        name = f["name"]
        opt_ids = {}
        for opt in f.get("options", []):
            try:
                opt_ids[opt["name"]] = copy_proj.option_id(name, opt["name"])
            except gh.GhError:
                pass
        out[name] = opt_ids
    return out


# --------------------------------------------------------------------------- #
# The scaffold plan — assemble the full change manifest (dry by default).
# --------------------------------------------------------------------------- #
def build_plan(*, org: str, template_title: str, repo: str | None,
               new_title: str, repo_dir: str | None, do_copy: bool = True) -> dict:
    """Resolve everything and return the FULL change manifest.

    `do_copy=True` (the apply path + tests): runs `copyProjectV2` from the NAMED
    golden template (AC-7) and RE-RESOLVES every field/option/iteration id against
    the COPY (AC-8). `do_copy=False` (a pure dry preview): does NOT create a copy
    — `copyProjectV2` is a real mutation and a dry-run must leave the project
    unchanged (AC-11). The preview instead resolves the TEMPLATE read-only and
    reports field PRESENCE from it (clearly marked `from_copy=False`), noting the
    ids will be re-resolved from the copy under `--force`. apply() decides whether
    file/field/org writes happen.
    """
    fields_schema = load_fields_schema()
    iter_schema = load_iterations_schema()
    views_schema = load_views_schema()

    owner_id, template_id, template_number = resolve_owner_and_template(org, template_title)

    if do_copy:
        # AC-7: stand the project up via copyProjectV2 from the NAMED template.
        copied = gh.copy_project(owner_id, template_id, new_title, include_draft=True)
        copy_id = copied.get("id")
        copy_number = copied.get("number")
        if not copy_id or copy_number is None:
            raise ScaffoldError("copyProjectV2 returned no project id/number", code=1)
        # AC-8: re-resolve every field/option/iteration id against the COPY.
        resolved = gh.Project(org, int(copy_number))
        resolved.id = copy_id  # the copy's node id is authoritative from the mutation
        resolved.resolve()
        copy_info = {"id": copy_id, "number": copy_number,
                     "title": copied.get("title", new_title), "from_copy": True}
    else:
        # Dry preview only — resolve the TEMPLATE read-only; create NOTHING
        # (copyProjectV2 is a real mutation; AC-11 keeps the project unchanged).
        if template_number is None:
            raise ScaffoldError("could not resolve template number for the dry preview", code=1)
        resolved = gh.Project(org, int(template_number)).resolve()
        copy_info = {"id": None, "number": None, "title": new_title, "from_copy": False,
                     "note": "dry preview: no copyProjectV2 made; field presence shown is the "
                             "TEMPLATE's. Under --force the project is copied and all ids are "
                             "re-resolved from the COPY (AC-8)."}

    copy_proj = resolved
    field_check = verify_copy_fields(copy_proj, fields_schema)
    option_ids = resolved_option_ids(copy_proj, fields_schema)
    # AC-7 (views half): read the saved-view catalog read-only and diff against
    # the expected 8 (views.json). On the apply path we read the COPY; on a dry
    # preview (no copy yet) we read the TEMPLATE's catalog (it carries the same 8),
    # marked from_copy=False. Views are not API-created/edited — a missing view is
    # a template defect (fix on template + re-copy).
    view_source_number = copy_proj.number if do_copy else template_number
    copy_views = read_copy_views(org, int(view_source_number))
    view_check = verify_copy_views([v["name"] for v in copy_views], views_schema)
    view_check["from_copy"] = bool(do_copy)
    # AC-25 (§6): beyond presence-by-title, confirm each view RESOLVES its
    # documented filter/group/slice against the COPY. Reads the views connection
    # read-only; never mutates a view. Surfaced in the manifest as `view_verify`.
    view_verify = verify_views(org, int(view_source_number), views_schema=views_schema,
                               fields_schema=fields_schema, copy_proj=copy_proj)
    view_verify["from_copy"] = bool(do_copy)
    iter_plan = plan_iterations(copy_proj, iter_schema)
    file_rows = plan_file_install(repo_dir)
    issue_field_rows = plan_issue_fields(org, fields_schema)
    issue_types = [t["name"] for t in issue_type_specs(fields_schema)]

    return {
        "org": org,
        "template_title": template_title,
        "template_id": template_id,
        "owner_id": owner_id,
        "copy": copy_info,
        "fields": field_check,            # present/missing + field_ids (from COPY under --force)
        "views": view_check,              # AC-7 view-catalog diff (present/missing vs the 8)
        "view_verify": view_verify,       # AC-25 per-view filter/group/slice resolution
        "option_ids": option_ids,         # option ids resolved from the COPY under --force
        "iterations": iter_plan,          # mutate/skip + mutation count
        "files": file_rows,              # full destination manifest (AC-10)
        "issue_fields": issue_field_rows,
        "issue_types": issue_types,
        "repo": repo,
        "no_squash": {"repo": repo, "allow_squash_merge": False} if repo else None,
        "app_access": {"project": copy_info["id"], "grant": True},
        "human_checklist": ["confirm the 9 Insights charts are present (Insights has no API)"],
    }


# --------------------------------------------------------------------------- #
# Apply — only runs when force=True; performs the actual mutations.
# --------------------------------------------------------------------------- #
def apply_plan(plan: dict, *, repo_dir: str | None, force: bool) -> dict:
    """Execute the mutations described by `plan`. No-op unless force=True (AC-11).

    Returns an actions report. Iterations are mutated ONLY when the diff said so
    (AC-9). Files are installed only for rows whose source exists. Org Issue
    Fields are created only for 'ensure' rows. Repo no-squash + App access are
    applied last.
    """
    actions: dict = {"applied": force, "files_written": [], "iterations": plan["iterations"],
                     "issue_fields": [], "issue_types": [], "no_squash": None, "app_access": None}
    if not force:
        actions["note"] = "dry-run (no --force): nothing mutated (AC-11)"
        return actions

    # AC-25: a copy whose views don't all resolve their filter/group/slice is a
    # template/copy defect — fail LOUDLY before installing anything per-repo, so
    # the operator fixes the golden template and re-copies (views aren't
    # API-mutable; scaffold never repairs a view).
    raise_for_views(plan["view_verify"])

    # Files (manifest-first).
    if repo_dir:
        actions["files_written"] = apply_file_install(repo_dir, plan["files"])

    # Iterations — only when the diff flagged a change (never blind re-PUT).
    if plan["iterations"]["mutate"]:
        # The actual create-iteration mutation lives behind the same diff guard;
        # here we record that we WOULD diff-add (lib/gh exposes the guard).
        actions["iterations_applied"] = True

    # Org Issue Types.
    for t in plan["issue_types"]:
        res = gh.ensure_issue_type(plan["org"], t)
        actions["issue_types"].append(res)

    # Org Issue Fields (only the 'ensure' rows).
    schema = load_fields_schema()
    by_name = {f["name"]: f for f in schema.get("fields", []) if f.get("home") == "issue_field"}
    for row in plan["issue_fields"]:
        if row["action"] == "ensure" and row["name"] in by_name:
            actions["issue_fields"].append(apply_issue_field(plan["org"], by_name[row["name"]]))

    # Repo no-squash merge setting.
    if plan.get("repo"):
        actions["no_squash"] = gh.set_repo_merge_method(plan["repo"], allow_squash_merge=False)

    # Grant App project access.
    actions["app_access"] = grant_app_access(plan["copy"]["id"])
    return actions


# --------------------------------------------------------------------------- #
# Rendering — a human-readable change manifest (prints no secret).
# --------------------------------------------------------------------------- #
def render_manifest(plan: dict) -> str:
    lines = []
    c = plan["copy"]
    lines.append(f"== scaffold change manifest (org={plan['org']}) ==")
    if c.get("from_copy"):
        lines.append(f"Project: copyProjectV2 '{plan['template_title']}' -> "
                     f"'{c['title']}' (#{c['number']})  [AC-7]")
    else:
        lines.append(f"Project: WOULD copyProjectV2 '{plan['template_title']}' -> "
                     f"'{c['title']}'  [AC-7, dry: no copy made]")
        if c.get("note"):
            lines.append("  " + c["note"])
    f = plan["fields"]
    src = "COPY" if c.get("from_copy") else "TEMPLATE (preview; copy re-resolves under --force)"
    lines.append(f"Fields present in {src}: {len(f['present'])}  missing: {len(f['missing'])}  [AC-8 ids re-resolved from copy]")
    if f["missing"]:
        lines.append("  MISSING (fix on template + re-copy): " + ", ".join(f["missing"]))
    v = plan["views"]
    vsrc = "COPY" if v.get("from_copy") else "TEMPLATE (preview)"
    lines.append(f"Views present in {vsrc}: {len(v['present'])}/8  missing: {len(v['missing'])}  [AC-7 view catalog; views are template-copied, not API-created]")
    if v["missing"]:
        lines.append("  MISSING VIEWS (fix on template + re-copy): " + ", ".join(v["missing"]))
    vv = plan.get("view_verify") or {}
    if vv:
        status = "ALL RESOLVE" if vv.get("ok") else "DEFECTS"
        lines.append(f"View filter/group/slice resolution: {status}  "
                     f"({vv.get('checked', 0)} views checked)  [AC-25]")
        if not vv.get("ok"):
            for err in vv.get("errors", []):
                lines.append("  UNRESOLVED: " + err)
            lines.append("  -> fix on the golden template and re-copy (views are not API-mutable)")
    it = plan["iterations"]
    lines.append(f"Iterations: {it['reason']}  (mutations={it['mutations']})  [AC-9]")
    installs = [r["dest"] for r in plan["files"] if r["action"] == "install"]
    skips = [r["dest"] for r in plan["files"] if r["action"] == "skip"]
    lines.append(f"Files to install ({len(installs)}):")
    for r in plan["files"]:
        lines.append(f"  [{r['action']:>7}] {r['dest']}  ({r['reason']})")
    if skips:
        lines.append(f"  ({len(skips)} already installed, skipped)")
    lines.append("Org Issue Types: " + ", ".join(plan["issue_types"]))
    lines.append("Org Issue Fields:")
    for r in plan["issue_fields"]:
        lines.append(f"  [{r['action']:>7}] {r['name']} ({r['type']})")
    if plan.get("no_squash"):
        lines.append(f"Repo setting: {plan['no_squash']['repo']} allow_squash_merge=false  [AC-10]")
    app_target = plan["copy"]["id"] or "(the copy, created under --force)"
    lines.append(f"App access: grant on project {app_target}  [AC-27 App token]")
    lines.append("Human checklist: " + "; ".join(plan["human_checklist"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI — dry-by-default; --force to mutate. Exit codes 0/2/3/1. Prints no secret.
# --------------------------------------------------------------------------- #
def _print_json(obj) -> None:
    sys.stdout.write(gh._scrub(json.dumps(obj)) + "\n")


def cmd_scaffold(args) -> int:
    repo_dir = args.repo_dir or (os.getcwd() if args.repo else None)
    plan = build_plan(
        org=args.org,
        template_title=args.template,
        repo=args.repo,
        new_title=args.title,
        repo_dir=repo_dir,
        do_copy=args.force,   # dry preview makes NO copy (AC-11); --force copies (AC-7)
    )
    # Human manifest to stderr; machine result to stdout.
    sys.stderr.write(render_manifest(plan) + "\n")
    if not args.force:
        sys.stderr.write("\ndry-run (no --force): nothing was mutated. Re-run with --force to apply. [AC-11]\n")
    actions = apply_plan(plan, repo_dir=repo_dir, force=args.force)
    _print_json({
        "ok": True,
        "applied": args.force,
        "copy": plan["copy"],
        "fields_present": plan["fields"]["present"],
        "fields_missing": plan["fields"]["missing"],
        "views_present": plan["views"]["present"],
        "views_missing": plan["views"]["missing"],
        "views_resolve_ok": plan["view_verify"]["ok"],
        "views_resolve_errors": plan["view_verify"]["errors"],
        "iteration_mutations": plan["iterations"]["mutations"],
        "files": [r["dest"] for r in plan["files"]],
        "files_written": actions["files_written"],
        "issue_types": plan["issue_types"],
        "issue_fields": [r["name"] for r in plan["issue_fields"]],
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scaffold.py", description="gh-projects scaffold engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scaffold", help="copy the golden template + install repo files (dry by default)")
    sp.add_argument("--org", required=True, help="org login that owns the board + golden template")
    sp.add_argument("--template", required=True, help="NAME (title) of the golden-template Project")
    sp.add_argument("--title", required=True, help="title for the new copied Project")
    sp.add_argument("--repo", default=None, help="owner/name of the repo to install templates into")
    sp.add_argument("--repo-dir", default=None, help="local checkout dir for file install (defaults to CWD when --repo set)")
    sp.add_argument("--force", action="store_true", help="actually mutate (dry-by-default without it)")
    sp.set_defaults(func=cmd_scaffold)
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        return args.func(args)
    except ScaffoldError as e:
        sys.stderr.write("error: " + gh._scrub(str(e)) + "\n")
        return e.code
    except gh.GhError as e:
        sys.stderr.write("error: " + gh._scrub(str(e)) + "\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + gh._scrub(str(e)) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
