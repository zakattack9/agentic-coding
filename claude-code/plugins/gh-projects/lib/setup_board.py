#!/usr/bin/env python3
"""One-shot golden-template setup for gh-projects, driven by the template JSON.

Builds as much of the golden-template Project as the GitHub API allows, straight
from `templates/project/{fields,iterations,views}.json`, so the one-time setup never
hand-writes a query. Uses the REST Projects API (`X-GitHub-Api-Version: 2026-03-10`)
for fields/views/issue-types and GraphQL for the few REST can't do.

WHAT IT AUTOMATES (no UI):
  * create the Project + set it private          (GraphQL createProjectV2 / updateProjectV2)
  * org Issue Type `Type` (+ options)            (REST POST /orgs/{org}/issue-types)
  * org Issue Fields (Priority/Start/Target)     (REST POST /orgs/{org}/issue-fields)
  * ALL project fields incl. the Sprint ITERATION (REST POST .../projectsV2/{n}/fields)
  * add the org Issue Fields as project columns  (REST POST .../fields {issue_field_id})
  * the 8 views WITH their visible columns       (REST POST .../views — visible_fields
    resolved from each view's `fields` in views.json)
  * mark it the org template                     (GraphQL markProjectV2AsTemplate)

WHAT NO API CAN DO — printed as a punch-list to finish in the UI, once:
  * edit the built-in Status field's options to the 6-stage lifecycle (no field-update API)
  * finish each view's grouping / slice / sort / swimlane (view-create takes
    name/layout/filter/visible_fields only; no group/sort param, no view-update API)
  * build the 9 Insights charts (no API at all)

Run it as YOURSELF: `gh auth` granting the `project` AND `admin:org` scopes
(`gh auth refresh -s project,admin:org`). Dry-by-default — prints the full plan and
mutates nothing; re-run with `--apply`. Idempotent: every create skips a name that
already exists, so a second run is a clean no-op. Re-target an existing project with
`--project-number` (or `--title`, which is reused if a project of that title exists).

Self-contained: stdlib only, imports nothing from the plugin, reaches GitHub only
through an injectable `RUN` seam — so it is exercised fully offline by the tests.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent / "templates" / "project"
API_VERSION = "2026-03-10"

# Single-select option color is required by both APIs but absent from the schema;
# default to neutral. NOTE the casing differs per API (REST quirk).
PROJECT_OPTION_COLOR = "GRAY"   # projectsV2 fields: UPPERCASE enum
ISSUE_TYPE_COLOR = "gray"       # issue-types: lowercase enum

_VIEW_LAYOUT = {"BOARD_LAYOUT": "board", "TABLE_LAYOUT": "table", "ROADMAP_LAYOUT": "roadmap"}
# Project-field types the REST create endpoint accepts.
_CREATABLE = {"single_select", "number", "text", "date", "iteration"}


# --------------------------------------------------------------------------- #
# Load the template JSON (self-contained — no plugin import).
# --------------------------------------------------------------------------- #
def _load(name: str) -> dict:
    p = PROJECT_DIR / name
    if not p.is_file():
        raise FileNotFoundError(f"{name} not found at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_fields() -> dict:
    return _load("fields.json")


def load_iterations() -> dict:
    return _load("iterations.json")


def load_views() -> dict:
    return _load("views.json")


# --------------------------------------------------------------------------- #
# Pure request-body builders (no network — the testable core).
# --------------------------------------------------------------------------- #
def issue_type_payloads(fields_schema: dict) -> list[dict]:
    """Org Issue Type create bodies, from the `Type` field's options."""
    out: list[dict] = []
    for f in fields_schema.get("fields", []):
        if f.get("home") == "issue_type":
            for o in f.get("options", []):
                out.append({
                    "name": o["name"],
                    "description": o.get("description", ""),
                    "color": ISSUE_TYPE_COLOR,
                    "is_enabled": True,
                })
    return out


def issue_field_payloads(fields_schema: dict) -> list[dict]:
    """Org Issue Field create bodies (home == 'issue_field')."""
    out: list[dict] = []
    for f in fields_schema.get("fields", []):
        if f.get("home") != "issue_field":
            continue
        body = {"name": f["name"], "data_type": f["type"]}
        if f.get("type") == "single_select":
            body["single_select_options"] = [
                {"name": o["name"], "description": o.get("description", "")}
                for o in f.get("options", [])
            ]
        out.append(body)
    return out


def issue_field_names(fields_schema: dict) -> list[str]:
    """The org Issue Fields (home == 'issue_field') that must be surfaced as project
    columns — Priority / Start date / Target date."""
    return [f["name"] for f in fields_schema.get("fields", []) if f.get("home") == "issue_field"]


def _project_field_body(f: dict, iterations_schema: dict) -> dict:
    body = {"name": f["name"], "data_type": f["type"]}
    if f["type"] == "single_select":
        body["single_select_options"] = [
            {"name": o["name"], "description": o.get("description", ""), "color": PROJECT_OPTION_COLOR}
            for o in f.get("options", [])
        ]
    elif f["type"] == "iteration":
        # The REST create endpoint wants a start anchor + duration and generates the
        # iterations itself. Passing an explicit `iterations` array (or duration alone)
        # 500s — only `{start_date, duration}` is accepted (verified live, 2026-03-10).
        first = (iterations_schema.get("iterations") or [{}])[0]
        body["iteration_configuration"] = {
            "start_date": iterations_schema.get("anchor") or first.get("startDate"),
            "duration": iterations_schema.get("cadence_days", 14),
        }
    return body


def project_field_payloads(fields_schema: dict, iterations_schema: dict) -> list[dict]:
    """Create bodies for every home:'project' field the API can make.

    Excludes built-ins (Status, Parent issue) — Status options are a UI edit and
    Parent issue is automatic.
    """
    out: list[dict] = []
    for f in fields_schema.get("fields", []):
        if f.get("home") != "project" or f.get("builtin"):
            continue
        if f.get("type") in _CREATABLE:
            out.append(_project_field_body(f, iterations_schema))
    return out


def view_payloads(views_schema: dict, field_ids: dict | None = None) -> list[dict]:
    """View create bodies (name + layout + filter + visible_fields). Grouping, slicing,
    sorting and swimlanes have no create param and are finished in the UI.

    `field_ids` ({field_name: int id}) translates each view's `fields` (names, in order)
    into `visible_fields` (ids); a name absent from the map is skipped — it isn't on the
    project yet (notably an org issue field that hasn't been added). Roadmap views take
    no visible_fields.
    """
    out: list[dict] = []
    for v in views_schema.get("views", []):
        layout = _VIEW_LAYOUT.get(v.get("layout"), "table")
        body = {"name": v["name"], "layout": layout}
        if v.get("filter"):
            body["filter"] = v["filter"]
        if field_ids is not None and layout != "roadmap":
            vis = [field_ids[n] for n in v.get("fields", []) if n in field_ids]
            if vis:
                body["visible_fields"] = vis
        out.append(body)
    return out


def unresolved_view_fields(views_schema: dict, field_ids: dict) -> dict:
    """{view_name: [field names not on the project]} — visible columns a view wants that
    aren't resolvable yet (add them to the project, then recreate the view)."""
    miss: dict = {}
    for v in views_schema.get("views", []):
        if _VIEW_LAYOUT.get(v.get("layout")) == "roadmap":
            continue
        absent = [n for n in v.get("fields", []) if n not in field_ids]
        if absent:
            miss[v["name"]] = absent
    return miss


def stale_views(views_schema: dict, field_ids: dict, current_columns: dict) -> list:
    """Names of EXISTING views whose visible columns are missing a desired, resolvable
    field. GitHub's view API is **create-only** (no update, no delete — both 404), so a
    view built by an older run can't be refreshed in place: it must be deleted in the UI
    and recreated. `current_columns` is {view_name: [current column names]} from
    `view_column_names`."""
    stale = []
    for v in views_schema.get("views", []):
        name = v["name"]
        if name not in current_columns or _VIEW_LAYOUT.get(v.get("layout")) == "roadmap":
            continue
        have = set(current_columns[name])
        if any(n not in have for n in v.get("fields", []) if n in field_ids):
            stale.append(name)
    return stale


def punch_list(fields_schema: dict, views_schema: dict) -> list[str]:
    """The residual UI steps no API can perform."""
    status = next((f for f in fields_schema.get("fields", []) if f.get("name") == "Status"), {})
    status_opts = " · ".join(o["name"] for o in status.get("options", []))
    lines = [
        f"Edit the built-in **Status** field's options to: {status_opts}  (no API to set options).",
        "Finish each view's grouping / slice / sort / swimlane in the UI — the view-create API "
        "takes name/layout/filter/visible_fields only (no group/sort param). Per views.json:",
    ]
    for v in views_schema.get("views", []):
        bits = []
        if v.get("group"):
            bits.append(f"group by {v['group']}")
        if v.get("slice"):
            bits.append(f"slice by {v['slice']}")
        if bits:
            lines.append(f"   - {v['name']}: {', '.join(bits)} (+ sort/cards per views.md)")
    lines.append("Build the 9 Insights charts (no API) — see templates/project/insights.md.")
    return lines


# --------------------------------------------------------------------------- #
# Apply path — reached only with --apply. Injectable runner for offline tests.
# --------------------------------------------------------------------------- #
def _default_run(args: list[str], stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True).stdout


RUN = _default_run


def _rest(method: str, path: str, body: dict | None = None, run=None) -> str:
    run = run or RUN
    args = ["api", "--method", method, path, "-H", f"X-GitHub-Api-Version: {API_VERSION}"]
    if body is not None:
        return run(args + ["--input", "-"], stdin=json.dumps(body))
    return run(args)


def _graphql(query: str, run=None, **variables) -> dict:
    run = run or RUN
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    out = run(args)
    return json.loads(out) if out else {}


_ORG_ID_Q = "query($l:String!){ organization(login:$l){ id } }"
_FIND_PROJECT_Q = "query($l:String!){ organization(login:$l){ projectsV2(first:100){ nodes { id number title } } } }"
_CREATE_PROJECT_Q = ("mutation($o:ID!,$t:String!){ createProjectV2(input:{ownerId:$o,title:$t}) "
                     "{ projectV2 { id number } } }")
_SET_PRIVATE_Q = "mutation($p:ID!){ updateProjectV2(input:{projectId:$p,public:false}){ projectV2 { id } } }"


def find_project_by_title(org: str, title: str, run=None) -> dict | None:
    data = _graphql(_FIND_PROJECT_Q, run=run, l=org)
    nodes = ((((data.get("data") or {}).get("organization") or {}).get("projectsV2") or {}).get("nodes")) or []
    for n in nodes:
        if n.get("title") == title:
            return {"id": n["id"], "number": n["number"]}
    return None


def create_project(org: str, title: str, run=None) -> dict:
    data = _graphql(_ORG_ID_Q, run=run, l=org)
    org_id = (((data.get("data") or {}).get("organization") or {}).get("id"))
    if not org_id:
        raise ValueError(f"could not resolve org node id for '{org}'")
    data = _graphql(_CREATE_PROJECT_Q, run=run, o=org_id, t=title)
    pv = (((data.get("data") or {}).get("createProjectV2") or {}).get("projectV2")) or {}
    if not pv.get("id"):
        raise ValueError("createProjectV2 returned no project")
    _graphql(_SET_PRIVATE_Q, run=run, p=pv["id"])
    return pv


def _existing_names(path: str, run=None) -> set[str]:
    """Names already present at a REST list endpoint (list or {key:[...]} shapes)."""
    out = _rest("GET", path, run=run)
    data = json.loads(out) if out else []
    if isinstance(data, dict):
        items = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        items = data
    return {i.get("name") for i in items if isinstance(i, dict) and i.get("name")}


def existing_view_names(org: str, number: int, run=None) -> set[str]:
    """View names already on the project. Views have **no REST list endpoint** (GET
    404s), so read them through the GraphQL `projectV2.views` connection, which is."""
    data = _graphql(
        "query($l:String!){ organization(login:$l){ projectV2(number:%d){ "
        "views(first:50){ nodes { name } } } } }" % int(number), run=run, l=org)
    nodes = (((((data.get("data") or {}).get("organization") or {})
               .get("projectV2") or {}).get("views") or {}).get("nodes")) or []
    return {n.get("name") for n in nodes if n and n.get("name")}


def view_column_names(org: str, number: int, run=None) -> dict:
    """{view_name: [current visible column names]} via the GraphQL views connection
    (views have no REST read). Used to detect existing views that are out of date."""
    data = _graphql(
        "query($l:String!){ organization(login:$l){ projectV2(number:%d){ "
        "views(first:50){ nodes { name fields(first:50){ nodes { "
        "... on ProjectV2FieldCommon { name } } } } } } } }" % int(number), run=run, l=org)
    nodes = (((((data.get("data") or {}).get("organization") or {})
               .get("projectV2") or {}).get("views") or {}).get("nodes")) or []
    out = {}
    for v in nodes:
        if v and v.get("name"):
            out[v["name"]] = [f.get("name") for f in ((v.get("fields") or {}).get("nodes") or [])
                              if f and f.get("name")]
    return out


def resolve_field_ids(org: str, number: int, run=None) -> dict:
    """{field_name: integer field id} for the project's current fields (REST list)."""
    out = _rest("GET", f"/orgs/{org}/projectsV2/{number}/fields", run=run)
    data = json.loads(out) if out else []
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return {f["name"]: f["id"] for f in data
            if isinstance(f, dict) and f.get("name") and f.get("id") is not None}


def project_meta(org: str, number: int, run=None) -> dict:
    """{'id': node_id, 'is_template': bool} for the project (REST get)."""
    out = _rest("GET", f"/orgs/{org}/projectsV2/{number}", run=run)
    d = json.loads(out) if out else {}
    return {"id": d.get("node_id"), "is_template": bool(d.get("is_template"))}


def org_issue_field_ids(org: str, run=None) -> dict:
    """{name: org issue-field id} for the org's Issue Fields (GET /orgs/{org}/issue-fields)."""
    out = _rest("GET", f"/orgs/{org}/issue-fields", run=run)
    data = json.loads(out) if out else []
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return {f["name"]: f["id"] for f in data
            if isinstance(f, dict) and f.get("name") and f.get("id") is not None}


def add_org_fields_to_project(org: str, number: int, fields_schema: dict, run=None):
    """Surface each org Issue Field (Priority/Start/Target) as a PROJECT column via
    `POST .../fields {"issue_field_id": <org id>}` — which gives it a project field id
    so views can show it. Idempotent: skips fields already on the project. Returns
    (rows, missing) where `missing` lists any org field absent at the org level.
    """
    run = run or RUN
    present = set(resolve_field_ids(org, number, run=run))
    org_ids = org_issue_field_ids(org, run=run)
    rows, missing = [], []
    for name in issue_field_names(fields_schema):
        if name in present:
            rows.append({"name": name, "action": "skip"})
        elif name in org_ids:
            _rest("POST", f"/orgs/{org}/projectsV2/{number}/fields",
                  body={"issue_field_id": org_ids[name]}, run=run)
            rows.append({"name": name, "action": "create"})
        else:
            missing.append(name)
    return rows, missing


def ensure(path: str, payloads: list[dict], run=None, present=None) -> list[dict]:
    """Idempotently POST each payload whose `name` isn't already present.

    `present` is the set of existing names; when None it's read from `path`'s REST list
    endpoint. Views have no REST list endpoint, so their caller passes `present` from
    `existing_view_names` (a GraphQL read)."""
    run = run or RUN
    if present is None:
        present = _existing_names(path, run=run)
    rows = []
    for body in payloads:
        if body["name"] in present:
            rows.append({"name": body["name"], "action": "skip"})
        else:
            _rest("POST", path, body=body, run=run)
            rows.append({"name": body["name"], "action": "create"})
    return rows


def _print_plan(fields, iters, views) -> None:
    its, ifs = issue_type_payloads(fields), issue_field_payloads(fields)
    pfs, vws = project_field_payloads(fields, iters), view_payloads(views)
    print("# DRY RUN — re-run with --apply to execute. Nothing is mutated.\n")
    print(f"GraphQL: create the Project (private) — or reuse it by title/number.")
    print(f"REST  POST /orgs/<org>/issue-types        : {len(its)}  ({', '.join(p['name'] for p in its)})")
    print(f"REST  POST /orgs/<org>/issue-fields       : {len(ifs)}  ({', '.join(p['name'] for p in ifs)})")
    print(f"REST  POST .../projectsV2/<n>/fields      : {len(pfs)}  ({', '.join(p['name'] for p in pfs)})")
    print(f"REST  POST .../projectsV2/<n>/views       : {len(vws)}  ({', '.join(p['name'] for p in vws)})")
    print("       (each view's visible columns come from views.json `fields`, resolved to")
    print("        field ids at --apply; org fields not yet on the project are skipped + warned)")
    print("\n# Example body (first project field):")
    if pfs:
        print(json.dumps(pfs[0], indent=2))
    print("\n# After --apply, finish these in the UI (no API):")
    for line in punch_list(fields, views):
        print(f"  - {line}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="One-shot golden-template setup from the template JSON.")
    ap.add_argument("--org", required=True, help="the organization login (e.g. zilarent)")
    ap.add_argument("--title", help="title for a new template Project (reused if it already exists)")
    ap.add_argument("--project-number", type=int, help="operate on this existing project (skip create)")
    ap.add_argument("--apply", action="store_true", help="execute (default: print the plan only)")
    args = ap.parse_args(argv)

    fields, iters, views = load_fields(), load_iterations(), load_views()

    if not args.apply:
        _print_plan(fields, iters, views)
        return 0

    if not args.title and not args.project_number:
        ap.error("with --apply you must pass --title (create/reuse) or --project-number (existing)")

    # Resolve / create the project.
    if args.project_number:
        number = args.project_number
        print(f"using existing project #{number}")
    else:
        proj = find_project_by_title(args.org, args.title)
        if proj:
            number = proj["number"]
            print(f"reusing existing project '{args.title}' (#{number})")
        else:
            proj = create_project(args.org, args.title)
            number = proj["number"]
            print(f"created project '{args.title}' (#{number}, private)")

    def _report(label, rows):
        created = sum(1 for r in rows if r["action"] == "create")
        skipped = sum(1 for r in rows if r["action"] == "skip")
        print(f"{label:>14}: {created} created, {skipped} skipped")

    _report("issue types", ensure(f"/orgs/{args.org}/issue-types", issue_type_payloads(fields)))
    _report("issue fields", ensure(f"/orgs/{args.org}/issue-fields", issue_field_payloads(fields)))
    _report("project fields", ensure(f"/orgs/{args.org}/projectsV2/{number}/fields",
                                     project_field_payloads(fields, iters)))
    # Surface the org Issue Fields (Priority/Start/Target) as project columns — they
    # don't auto-appear; add each via {issue_field_id} so the views can show them.
    orows, omissing = add_org_fields_to_project(args.org, number, fields)
    _report("org→project", orows)
    if omissing:
        print(f"  ! org issue fields missing at the org level (create them first): {', '.join(omissing)}")
    # Views: resolve visible_fields from the project's live fields (now incl. the org
    # columns just added); views have no REST list endpoint, so read existing view
    # names via GraphQL for idempotency.
    field_ids = resolve_field_ids(args.org, number)
    _report("view shells", ensure(f"/orgs/{args.org}/projectsV2/{number}/views",
                                  view_payloads(views, field_ids=field_ids),
                                  present=existing_view_names(args.org, number)))
    missing = unresolved_view_fields(views, field_ids)
    if missing:
        print("  ! view columns still unresolved (field not on the project):")
        for vname, fnames in missing.items():
            print(f"      {vname}: {', '.join(fnames)}")
    stale = stale_views(views, field_ids, view_column_names(args.org, number))
    if stale:
        print("  ! these existing views are OUT OF DATE and can't be refreshed via API")
        print("    (GitHub's view API is create-only) — delete them in the UI, then re-run:")
        for n in stale:
            print(f"      {n}")

    # Mark it the org template so scaffold-repo / org→org copy can find it.
    meta = project_meta(args.org, number)
    if meta.get("is_template"):
        print(f"{'template':>14}: already a template")
    elif meta.get("id"):
        _graphql("mutation($p:ID!){ markProjectV2AsTemplate(input:{projectId:$p}){ projectV2 { id } } }",
                 run=RUN, p=meta["id"])
        print(f"{'template':>14}: marked as org template")

    print("\nFinish in the UI (no API for these):")
    for line in punch_list(fields, views):
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write((e.stderr or str(e)) + "\n")
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"{e}\n")
        sys.exit(2)
