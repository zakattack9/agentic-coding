#!/usr/bin/env python3
"""gh-projects GraphQL/REST core (Phase 1 — deterministic, free, GitHub-native).

This is the shared contract every later phase calls. It speaks to GitHub only
through an INJECTABLE command runner (the module-level `RUN` callable) so the
whole surface can be exercised OFFLINE: tests replace `RUN` with a fake that
returns canned JSON and counts round-trips. No network, no live org, ever.

Hard rules baked into this file (Phase-1 boundaries):
  * Deterministic & free — NO metered AI/model call anywhere (AC-26).
  * Every Projects v2 field write uses a GitHub App INSTALLATION token, NEVER
    GITHUB_TOKEN (AC-27 / constraint #2). `get_app_token()` mints one.
  * No blind re-PUT of a single-select option list or `iterationConfiguration`
    — diff before mutate; IDs stay stable (AC-30 / constraint #3).
  * Capability detection PROBES the installed `gh` (`--help` text), never a
    pinned version; falls back to GraphQL when a flag is absent. There is NO
    label-based dependency fallback anywhere in this file (AC-4).
  * Resolve + CACHE project/field/option/iteration IDs — one resolve serves
    repeated lookups in a run (AC-1).
  * Two-phase field write: addProjectV2ItemById -> read item id ->
    updateProjectV2ItemFieldValue, then read back identical (AC-2).
  * Print no token/secret, ever (AC-3).

Exit codes (every CLI entrypoint): 0 ok · 2 usage/validation · 3 not found ·
1 unexpected.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------- #
# Injectable command runner
# --------------------------------------------------------------------------- #
# Everything that would touch GitHub goes through RUN(args) -> str (stdout).
# Default implementation shells out to `gh`; tests swap it for a fake that
# returns canned output and counts calls — so nothing here needs a network.


class GhError(Exception):
    """A gh/GraphQL invocation failed. Carries a code for the CLI exit map."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _default_run(args) -> str:
    """Run `gh <args>` and return stdout. Raises GhError on non-zero.

    Never echoes the argv (it can carry a token) — only a redacted form.
    """
    proc = subprocess.run(["gh", *[str(a) for a in args]], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhError(f"gh {_redact_args(args)} failed: {_scrub(proc.stderr.strip())}", code=1)
    return proc.stdout


# The single seam tests override. Signature: RUN(list[str]) -> str (stdout).
RUN = _default_run


# --------------------------------------------------------------------------- #
# Secret scrubbing — nothing this module prints may carry a token/secret.
# --------------------------------------------------------------------------- #
# GitHub token shapes + anything that looks like a private key / bearer header.
_SECRET_PATTERNS = [
    re.compile(r"gh[opsuream]_[A-Za-z0-9_]{20,}"),          # gho_, ghp_, ghs_, ghu_...
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),            # fine-grained PAT
    re.compile(r"-----BEGIN[^-]+PRIVATE KEY-----.*?-----END[^-]+PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)(authorization|token|secret|private[_-]?key)[\"'\s:=]+[A-Za-z0-9._\-/+]{16,}"),
]


def _scrub(text) -> str:
    """Redact anything token/secret-shaped from a string before it is printed."""
    s = str(text)
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def _redact_args(args) -> str:
    """A safe, single-line rendering of an argv for logs (token args masked)."""
    out, skip = [], False
    for a in args:
        a = str(a)
        if skip:
            out.append("[REDACTED]")
            skip = False
            continue
        if a in ("-H", "--header", "-f", "-F") and "token" in a.lower():
            out.append(a)
            skip = True
            continue
        out.append(_scrub(a))
    return _scrub(" ".join(out))


# --------------------------------------------------------------------------- #
# GraphQL / REST primitives (all through RUN)
# --------------------------------------------------------------------------- #
def graphql(query: str, variables: dict | None = None) -> dict:
    """Run a GraphQL operation via `gh api graphql`. Returns the `data` object."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, val in (variables or {}).items():
        # `-F` lets gh coerce numbers/booleans; strings go through `-f`.
        if isinstance(val, bool):
            args += ["-F", f"{key}={'true' if val else 'false'}"]
        elif isinstance(val, (int, float)):
            args += ["-F", f"{key}={val}"]
        else:
            args += ["-f", f"{key}={val}"]
    raw = RUN(args)
    payload = json.loads(raw) if raw.strip() else {}
    if isinstance(payload, dict) and payload.get("errors"):
        raise GhError(f"graphql errors: {_scrub(json.dumps(payload['errors']))}", code=1)
    return payload.get("data", payload) if isinstance(payload, dict) else {}


def rest(method: str, path: str, fields: dict | None = None) -> dict:
    """Run a REST call via `gh api`. Returns the parsed JSON (or {})."""
    args = ["api", "-X", method.upper(), path]
    for key, val in (fields or {}).items():
        if isinstance(val, bool):
            args += ["-F", f"{key}={'true' if val else 'false'}"]
        elif isinstance(val, (int, float)):
            args += ["-F", f"{key}={val}"]
        else:
            args += ["-f", f"{key}={val}"]
    raw = RUN(args)
    return json.loads(raw) if raw.strip() else {}


# --------------------------------------------------------------------------- #
# App installation token (AC-27 / constraint #2)
# --------------------------------------------------------------------------- #
def get_app_token() -> str:
    """Return a GitHub App INSTALLATION token for Projects writes.

    Order of resolution (all NON-`GITHUB_TOKEN`):
      1. An injected token in `GH_APP_TOKEN` (CI mints it upstream) — used as-is.
      2. Mint one from `APP_ID` + `APP_PRIVATE_KEY`/`APP_PRIVATE_KEY_PATH`
         (+ optional `APP_INSTALLATION_ID`) by signing a JWT and exchanging it
         for an installation token via the REST app API.

    NEVER reads or returns `GITHUB_TOKEN` — that token cannot write Projects v2
    fields and using it for a Project write is a hard boundary violation.
    Raises GhError(code=2) if no App credentials are configured. The returned
    value is a secret; callers must not print it (and this module never does).
    """
    injected = os.environ.get("GH_APP_TOKEN")
    if injected:
        return injected

    app_id = os.environ.get("APP_ID")
    pem = os.environ.get("APP_PRIVATE_KEY")
    pem_path = os.environ.get("APP_PRIVATE_KEY_PATH")
    if pem_path and not pem:
        try:
            with open(pem_path, "r", encoding="utf-8") as fh:
                pem = fh.read()
        except OSError as e:
            raise GhError(f"cannot read APP_PRIVATE_KEY_PATH: {_scrub(e)}", code=2)
    if not (app_id and pem):
        raise GhError(
            "no GitHub App credentials: set GH_APP_TOKEN, or APP_ID + "
            "APP_PRIVATE_KEY/APP_PRIVATE_KEY_PATH. GITHUB_TOKEN is NOT accepted "
            "for Projects writes (constraint #2).",
            code=2,
        )

    jwt = _mint_app_jwt(app_id, pem)
    installation_id = os.environ.get("APP_INSTALLATION_ID")
    if not installation_id:
        installations = json.loads(
            RUN(["api", "-H", "Authorization: Bearer " + jwt, "/app/installations"]) or "[]"
        )
        if not installations:
            raise GhError("App has no installations; set APP_INSTALLATION_ID", code=2)
        installation_id = str(installations[0]["id"])
    tok = json.loads(
        RUN([
            "api", "-X", "POST",
            "-H", "Authorization: Bearer " + jwt,
            f"/app/installations/{installation_id}/access_tokens",
        ]) or "{}"
    )
    token = tok.get("token")
    if not token:
        raise GhError("installation token exchange returned no token", code=1)
    return token


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _mint_app_jwt(app_id: str, pem: str) -> str:
    """Sign a short-lived RS256 JWT for the App (stdlib-only crypto).

    Uses `hashlib`/`hmac`-free RSA via the bundled `_rsa_sign` helper which
    shells out to `openssl` through RUN-independent subprocess ONLY when the
    pure-Python path is unavailable. Kept dependency-free; never logs the key.
    """
    import time

    header = {"alg": "RS256", "typ": "JWT"}
    now = int(time.time())
    claims = {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = _rsa_sign(signing_input.encode("ascii"), pem)
    return signing_input + "." + _b64url(signature)


def _rsa_sign(message: bytes, pem: str) -> bytes:
    """RS256 sign `message` with the PEM private key, stdlib only.

    Falls back to `openssl` if present (always available on GH runners). The
    private key is fed on stdin and never appears in argv or any log.
    """
    proc = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", "/dev/stdin"],
        input=_pem_then(pem, message),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise GhError("RSA signing failed (openssl)", code=1)
    return proc.stdout


def _pem_then(pem: str, message: bytes) -> bytes:
    # openssl can't take key + data both on stdin; write key to a temp file.
    import tempfile

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem") as kf:
        kf.write(pem)
        key_path = kf.name
    try:
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=message,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise GhError("RSA signing failed (openssl)", code=1)
        return proc.stdout
    finally:
        try:
            os.unlink(key_path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Capability detection — PROBE the installed gh, never pin a version (AC-4)
# --------------------------------------------------------------------------- #
class Capabilities:
    """Feature-detected `gh` capabilities, probed once and cached.

    We parse `--help` text rather than a version string so a backported flag is
    honored and a renamed flag fails closed to the GraphQL path. There is NO
    label-based dependency fallback — the only fallback is GraphQL.
    """

    def __init__(self):
        self._cache: dict[str, bool] = {}

    def _help(self, args) -> str:
        try:
            return RUN([*args, "--help"])
        except GhError:
            return ""

    def has(self, key: str) -> bool:
        if key in self._cache:
            return self._cache[key]
        if key == "add_blocked_by":
            val = "--add-blocked-by" in self._help(["issue", "edit"])
        elif key == "linked_branch":
            # `gh issue develop` creates an authoritative linked branch.
            val = bool(self._help(["issue", "develop"]))
        elif key == "add_sub_issue":
            val = "--add-sub-issue" in self._help(["issue", "edit"]) \
                or "--add-parent" in self._help(["issue", "edit"])
        elif key == "issue_type":
            val = "--type" in self._help(["issue", "edit"])
        else:
            val = False
        self._cache[key] = val
        return val


# --------------------------------------------------------------------------- #
# Resolver — resolve + CACHE project / field / option / iteration IDs (AC-1)
# --------------------------------------------------------------------------- #
_FIELDS_QUERY = """
query($owner:String!, $number:Int!){
  organization(login:$owner){
    projectV2(number:$number){
      id
      title
      fields(first:100){
        nodes{
          __typename
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField {
            id name options { id name description }
          }
          ... on ProjectV2IterationField {
            id name
            configuration {
              iterations { id title startDate duration }
              completedIterations { id title startDate duration }
            }
          }
        }
      }
    }
  }
}
"""


class Project:
    """A resolved org Project. One GraphQL resolve serves every later lookup."""

    def __init__(self, owner: str, number: int):
        self.owner = owner
        self.number = int(number)
        self._resolved = False
        self.id = None
        self.title = None
        self._fields_by_name: dict[str, dict] = {}

    # -- resolution + cache (AC-1) ------------------------------------------ #
    def resolve(self) -> "Project":
        """Resolve & cache the project + all field/option/iteration IDs.

        Idempotent: a second call is a no-op (no second round-trip). This is the
        AC-1 cache — every `field()/option_id()/iteration_id()` afterward reads
        the cached structure and issues NO further GraphQL.
        """
        if self._resolved:
            return self
        data = graphql(_FIELDS_QUERY, {"owner": self.owner, "number": self.number})
        proj = (((data or {}).get("organization") or {}).get("projectV2")) or {}
        if not proj.get("id"):
            raise GhError(f"project {self.owner}#{self.number} not found", code=3)
        self.id = proj["id"]
        self.title = proj.get("title")
        for node in (proj.get("fields") or {}).get("nodes") or []:
            name = node.get("name")
            if name:
                self._fields_by_name[name] = node
        self._resolved = True
        return self

    def field(self, name: str) -> dict:
        """Return the cached field node by name (resolves once if needed)."""
        if not self._resolved:
            self.resolve()
        node = self._fields_by_name.get(name)
        if not node:
            raise GhError(f"field '{name}' not found on project", code=3)
        return node

    def field_id(self, name: str) -> str:
        return self.field(name)["id"]

    def option_id(self, field_name: str, option_name: str) -> str:
        """Resolve a single-select option id by (case-insensitive) name."""
        node = self.field(field_name)
        for opt in node.get("options") or []:
            if str(opt.get("name")).lower() == str(option_name).lower():
                return opt["id"]
        raise GhError(f"option '{option_name}' not found on field '{field_name}'", code=3)

    def iteration_id(self, field_name: str, title: str) -> str:
        """Resolve an iteration id by title (active or completed)."""
        node = self.field(field_name)
        cfg = node.get("configuration") or {}
        for it in (cfg.get("iterations") or []) + (cfg.get("completedIterations") or []):
            if str(it.get("title")).lower() == str(title).lower():
                return it["id"]
        raise GhError(f"iteration '{title}' not found on field '{field_name}'", code=3)


# --------------------------------------------------------------------------- #
# Two-phase field write (AC-2): add item -> read item id -> update -> read back
# --------------------------------------------------------------------------- #
_ADD_ITEM = """
mutation($project:ID!, $content:ID!){
  addProjectV2ItemById(input:{projectId:$project, contentId:$content}){
    item { id }
  }
}
"""

_READBACK = """
query($item:ID!, $field:ID!){
  node(id:$item){
    ... on ProjectV2Item {
      id
      fieldValueByName: fieldValues(first:50){
        nodes{
          __typename
          ... on ProjectV2ItemFieldSingleSelectValue { optionId field { ... on ProjectV2FieldCommon { id } } }
          ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { id } } }
          ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { id } } }
          ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { id } } }
          ... on ProjectV2ItemFieldIterationValue { iterationId field { ... on ProjectV2FieldCommon { id } } }
        }
      }
    }
  }
}
"""


def add_item(project_id: str, content_id: str) -> str:
    """Phase 1: addProjectV2ItemById -> return the new item id."""
    data = graphql(_ADD_ITEM, {"project": project_id, "content": content_id})
    item = ((data.get("addProjectV2ItemById") or {}).get("item")) or {}
    item_id = item.get("id")
    if not item_id:
        raise GhError("addProjectV2ItemById returned no item id", code=1)
    return item_id


def _value_payload(field_node: dict, value):
    """Build the ProjectV2FieldValue payload + the expected read-back tuple.

    Reuses the single-select / number / text shape from the pm-ops engine's
    set_field, adapted to the GraphQL `value:` input. Extended to also cover the
    iteration (Sprint) and date (Start/Target) field kinds that plan-sprint sets.
    Returns (variables_value_json, expected_kind, expected_value).
    """
    dtype = (field_node.get("dataType") or "").upper()
    has_options = bool(field_node.get("options"))
    has_iterations = bool(field_node.get("configuration"))
    if "SINGLE_SELECT" in dtype or has_options:
        return ({"singleSelectOptionId": value}, "optionId", value)
    if "ITERATION" in dtype or has_iterations:
        # `value` is already the resolved iterationId (write_field resolves it).
        return ({"iterationId": value}, "iterationId", value)
    if "NUMBER" in dtype:
        return ({"number": float(value)}, "number", float(value))
    if "DATE" in dtype:
        return ({"date": str(value)}, "date", str(value))
    return ({"text": str(value)}, "text", str(value))


def set_field(project: "Project", item_id: str, field_name: str, value) -> dict:
    """Phase 2: updateProjectV2ItemFieldValue, then READ BACK identical (AC-2).

    `value` is the resolved id (single-select option id) / number / text. Raises
    GhError if the read-back does not match what we wrote.
    """
    node = project.field(field_name)
    field_id = node["id"]
    payload, kind, expected = _value_payload(node, value)
    # value is a GraphQL input object; gh's -f/-F can't nest it, so the value is
    # inlined as a typed literal built from the resolved id/number/text.
    _update_field_value(project.id, item_id, field_id, payload)

    got = _read_field_value(item_id, field_id)
    if got is None or not _values_equal(kind, got, expected):
        raise GhError(
            f"read-back mismatch for field '{field_name}': wrote {expected!r}, read {got!r}",
            code=1,
        )
    return {"item": item_id, "field": field_name, "value": expected, "verified": True}


def _update_field_value(project_id, item_id, field_id, payload: dict) -> dict:
    """Send updateProjectV2ItemFieldValue with a typed `value` input object.

    gh's `-f`/`-F` can't express a nested input object, so we inline the value
    into the query as a typed literal built from the resolved id/number/text.
    """
    if "singleSelectOptionId" in payload:
        lit = '{singleSelectOptionId:"%s"}' % payload["singleSelectOptionId"]
    elif "iterationId" in payload:
        lit = '{iterationId:"%s"}' % payload["iterationId"]
    elif "number" in payload:
        lit = "{number:%s}" % payload["number"]
    elif "date" in payload:
        lit = '{date:"%s"}' % payload["date"]
    else:
        text = str(payload.get("text", "")).replace("\\", "\\\\").replace('"', '\\"')
        lit = '{text:"%s"}' % text
    query = (
        "mutation($project:ID!,$item:ID!,$field:ID!){"
        "updateProjectV2ItemFieldValue(input:{"
        "projectId:$project,itemId:$item,fieldId:$field,value:%s}){"
        "projectV2Item{id}}}" % lit
    )
    return graphql(query, {"project": project_id, "item": item_id, "field": field_id})


def _read_field_value(item_id: str, field_id: str):
    """Read back the single field's value via the item's fieldValues."""
    data = graphql(_READBACK, {"item": item_id, "field": field_id})
    node = data.get("node") or {}
    for fv in ((node.get("fieldValueByName") or {}).get("nodes")) or []:
        f = (fv.get("field") or {}).get("id")
        if f != field_id:
            continue
        if "optionId" in fv:
            return ("optionId", fv["optionId"])
        if "iterationId" in fv:
            return ("iterationId", fv["iterationId"])
        if "number" in fv:
            return ("number", fv["number"])
        if "date" in fv:
            return ("date", fv["date"])
        if "text" in fv:
            return ("text", fv["text"])
    return None


def _values_equal(kind: str, got, expected) -> bool:
    gkind, gval = got
    if gkind != kind:
        return False
    if kind == "number":
        return float(gval) == float(expected)
    return str(gval) == str(expected)


def write_field(project: "Project", content_id: str, field_name: str, raw_value) -> dict:
    """Convenience: resolve the option (if single-select), two-phase add+set.

    For a single-select, `raw_value` is the OPTION NAME and is resolved to its
    cached option id first. For an iteration (Sprint) field, `raw_value` is the
    iteration TITLE and is resolved to its cached iteration id. Number / date /
    text values pass through unresolved. Returns the verified result dict.
    """
    node = project.field(field_name)
    dtype = (node.get("dataType") or "").upper()
    if "SINGLE_SELECT" in dtype or node.get("options"):
        value = project.option_id(field_name, raw_value)
    elif "ITERATION" in dtype or node.get("configuration"):
        value = project.iteration_id(field_name, raw_value)
    else:
        value = raw_value
    item_id = add_item(project.id, content_id)
    return set_field(project, item_id, field_name, value)


# --------------------------------------------------------------------------- #
# Monotonic Status advance (AC-31) — never regress except explicit reopen.
# --------------------------------------------------------------------------- #
STATUS_ORDER = ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"]


def status_rank(status: str) -> int:
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return -1


def advance_status(current: str | None, target: str, *, reopen: bool = False) -> str | None:
    """Return the Status to write, honoring monotonicity (AC-31).

    Only advances along Backlog<Ready<In Progress<In Review<On Staging<Done. A
    stale/late event whose target is at or behind `current` is a no-op (returns
    None — "do not write"). `reopen=True` is the only way to move backward.
    """
    if reopen:
        return target
    if current is None:
        return target
    if status_rank(target) > status_rank(current):
        return target
    return None  # idempotent no-op: already at/after the target


# --------------------------------------------------------------------------- #
# Schema mutations — DIFF before mutate; never blind re-PUT (AC-30)
# --------------------------------------------------------------------------- #
def iterations_need_update(existing: list[dict], desired: list[dict]) -> bool:
    """Return True only if the iteration set actually changed.

    `iterationConfiguration` is REPLACE-ALL: re-PUTting it wipes completed
    iterations and orphans every assignment + chart history. So we diff by
    (title, startDate, duration) and skip the mutation when nothing changed.
    NEVER call updateProjectV2Field's iterationConfiguration without this guard.
    """
    def norm(it):
        return (str(it.get("title", "")), str(it.get("startDate", "")), int(it.get("duration", 0) or 0))

    return [norm(i) for i in existing] != [norm(i) for i in desired]


def options_need_update(existing: list[dict], desired: list[dict]) -> bool:
    """Return True only if the single-select option set changed by NAME.

    Editing the option list regenerates option IDs and orphans assignments, so
    we diff names/descriptions before touching the field. Pre-existing options
    keep their ids; only genuinely new names are added by the caller.
    """
    def norm(o):
        return (str(o.get("name", "")), str(o.get("description", "") or ""))

    return [norm(o) for o in existing] != [norm(o) for o in desired]


_COPY_PROJECT = """
mutation($owner:ID!, $source:ID!, $title:String!, $includeDraft:Boolean!){
  copyProjectV2(input:{ownerId:$owner, projectId:$source, title:$title, includeDraftIssues:$includeDraft}){
    projectV2 { id number title }
  }
}
"""

_UPDATE_PROJECT = """
mutation($project:ID!, $title:String, $readme:String, $desc:String){
  updateProjectV2(input:{projectId:$project, title:$title, readme:$readme, shortDescription:$desc}){
    projectV2 { id }
  }
}
"""

_CREATE_STATUS_UPDATE = """
mutation($project:ID!, $body:String!, $status:ProjectV2StatusUpdateStatus, $start:Date, $target:Date){
  createProjectV2StatusUpdate(input:{
    projectId:$project, body:$body, status:$status, startDate:$start, targetDate:$target
  }){
    statusUpdate { id }
  }
}
"""

_ADD_SUB_ISSUE = """
mutation($parent:ID!, $child:ID!){
  addSubIssue(input:{issueId:$parent, subIssueId:$child}){
    issue { id }
  }
}
"""

_CREATE_LINKED_BRANCH = """
mutation($issue:ID!, $oid:GitObjectID!, $name:String){
  createLinkedBranch(input:{issueId:$issue, oid:$oid, name:$name}){
    linkedBranch { id ref { name } }
  }
}
"""


def copy_project(owner_id: str, source_project_id: str, title: str, include_draft: bool = True) -> dict:
    data = graphql(_COPY_PROJECT, {
        "owner": owner_id, "source": source_project_id,
        "title": title, "includeDraft": include_draft,
    })
    return (data.get("copyProjectV2") or {}).get("projectV2") or {}


def update_project(project_id: str, *, title=None, readme=None, description=None) -> dict:
    return graphql(_UPDATE_PROJECT, {
        "project": project_id, "title": title, "readme": readme, "desc": description,
    })


def create_status_update(project_id: str, body: str, *, status=None, start=None, target=None) -> dict:
    return graphql(_CREATE_STATUS_UPDATE, {
        "project": project_id, "body": body, "status": status, "start": start, "target": target,
    })


def add_sub_issue(parent_issue_id: str, child_issue_id: str) -> dict:
    """Native sub-issue link (Epic-split). No label fallback — GraphQL only."""
    return graphql(_ADD_SUB_ISSUE, {"parent": parent_issue_id, "child": child_issue_id})


def add_blocked_by(repo: str, issue_number, blocker_number, caps: "Capabilities" = None) -> dict:
    """Add a native blocked-by dependency.

    Prefers the native `gh issue edit --add-blocked-by` flag WHEN the installed
    gh supports it (probed), else falls back to GraphQL. There is NO
    label-based dependency fallback — that is a hard boundary.
    """
    caps = caps or Capabilities()
    if caps.has("add_blocked_by"):
        RUN(["issue", "edit", str(issue_number), "--repo", repo,
             "--add-blocked-by", str(blocker_number)])
        return {"via": "native", "issue": issue_number, "blocked_by": blocker_number}
    # GraphQL fallback (addIssueDependency-style mutation against the linked ids).
    data = graphql(
        "mutation($issue:ID!,$blocker:ID!){"
        "addIssueDependency(input:{issueId:$issue,dependsOnIssueId:$blocker}){"
        "issue{id}}}",
        {"issue": str(issue_number), "blocker": str(blocker_number)},
    )
    return {"via": "graphql", "result": data}


def create_linked_branch(issue_id: str, oid: str, name: str = None, repo: str = None,
                         issue_number=None, caps: "Capabilities" = None) -> dict:
    """Create an authoritative linked branch for an issue.

    Prefers native `gh issue develop` WHEN supported (probed), else falls back
    to the createLinkedBranch GraphQL mutation. No label/name-convention
    dependency fallback for the LINK itself.
    """
    caps = caps or Capabilities()
    if caps.has("linked_branch") and repo and issue_number is not None:
        args = ["issue", "develop", str(issue_number), "--repo", repo]
        if name:
            args += ["--name", name]
        RUN(args)
        return {"via": "native", "issue": issue_number, "name": name}
    data = graphql(_CREATE_LINKED_BRANCH, {"issue": issue_id, "oid": oid, "name": name})
    return {"via": "graphql", "result": (data.get("createLinkedBranch") or {}).get("linkedBranch")}


# --------------------------------------------------------------------------- #
# Org Issue Type / Issue Field ensure + repo merge-method setting
# --------------------------------------------------------------------------- #
def ensure_issue_type(org: str, name: str, *, description: str = "", color: str = "GRAY") -> dict:
    """Ensure an org Issue Type exists by name (idempotent). REST app API.

    Lists existing types and creates only the missing one — never a blind PUT.
    """
    existing = rest("GET", f"/orgs/{org}/issue-types") or []
    names = {t.get("name") for t in (existing if isinstance(existing, list) else existing.get("issue_types", []))}
    if name in names:
        return {"ensured": name, "created": False}
    rest("POST", f"/orgs/{org}/issue-types", {"name": name, "description": description, "color": color})
    return {"ensured": name, "created": True}


def set_repo_merge_method(repo: str, *, allow_squash_merge: bool = False) -> dict:
    """Set the repo merge-method setting (free no-squash enforcement, AC-10).

    Idempotent PATCH of the single boolean — does not touch other repo settings.
    """
    rest("PATCH", f"/repos/{repo}", {"allow_squash_merge": allow_squash_merge})
    return {"repo": repo, "allow_squash_merge": allow_squash_merge}


# --------------------------------------------------------------------------- #
# PR open/update — NON-CLOSING reference only (AC-1, AC-16, AC-30)
# --------------------------------------------------------------------------- #
# `Closes/Fixes/Resolves` would auto-close the issue on merge; closure stays the
# prod-time board-status job's responsibility. We carry ONLY `Relates to #N`.
_CLOSING_KEYWORDS = ("close", "closes", "closed", "fix", "fixes", "fixed",
                     "resolve", "resolves", "resolved")


def _relates_body(issue_number, extra: str | None = None) -> str:
    """Build a PR body with a NON-CLOSING `Relates to #N` reference.

    Never emits a closing keyword (Closes/Fixes/Resolves) — auto-close is the
    board-status job's job, not the PR's (AC-30).
    """
    rel = f"Relates to #{int(issue_number)}"
    body = (str(extra).rstrip() + "\n\n" + rel) if extra else rel
    # Defensive: a caller-supplied `extra` must never smuggle in a closer.
    low = body.lower()
    for kw in _CLOSING_KEYWORDS:
        if re.search(rf"\b{kw}\b\s+#\d", low):
            raise GhError(
                f"PR body carries a closing keyword '{kw} #N'; only non-closing "
                "'Relates to #N' is allowed (AC-30)",
                code=2,
            )
    return body


def _find_pr_for_branch(repo: str, head: str):
    """Return the existing PR {number,url} for `head`, or None.

    Uses `gh pr list --head <head> --json number,url` — a read, no mutation.
    """
    raw = RUN(["pr", "list", "--repo", repo, "--head", head,
               "--state", "open", "--json", "number,url"])
    prs = json.loads(raw) if raw.strip() else []
    if isinstance(prs, list) and prs:
        return {"number": prs[0].get("number"), "url": prs[0].get("url")}
    return None


def open_or_update_pr(repo: str, head: str, base: str, issue_number,
                      *, title: str | None = None, body_extra: str | None = None,
                      draft: bool = False) -> dict:
    """Open an issue-linked PR, or EDIT the existing one for the branch (AC-1).

    Body carries a NON-CLOSING `Relates to #N` (never Closes/Fixes/Resolves —
    AC-30). Idempotent: if a PR already exists for `head` we `gh pr edit` it in
    place rather than `gh pr create` (which would 422 on a duplicate). A no-diff
    re-run is therefore a clean no-op, never a duplicate-PR error (AC-16).
    Returns {"action": "created"|"updated", "number", "url"}.
    """
    body = _relates_body(issue_number, body_extra)
    existing = _find_pr_for_branch(repo, head)
    pr_title = title or f"{head}"
    if existing:
        num = existing["number"]
        args = ["pr", "edit", str(num), "--repo", repo, "--body", body]
        if title:
            args += ["--title", title]
        RUN(args)
        return {"action": "updated", "number": num, "url": existing.get("url")}
    args = ["pr", "create", "--repo", repo, "--head", head, "--base", base,
            "--title", pr_title, "--body", body]
    if draft:
        args.append("--draft")
    out = RUN(args)
    # `gh pr create` prints the PR url on stdout.
    url = (out or "").strip().splitlines()[-1] if (out or "").strip() else None
    return {"action": "created", "number": None, "url": url}


# --------------------------------------------------------------------------- #
# PR aggregate check state (AC-2, AC-18) -> green / red / pending
# --------------------------------------------------------------------------- #
def pr_check_state(repo: str, pr_number) -> str:
    """Read a PR's aggregate check state and return 'green'/'red'/'pending'.

    Uses `gh pr checks <n> --json state` (one bucket per check). Any failing
    check -> 'red'; any still-running/queued -> 'pending'; all complete and
    passing -> 'green'. An empty check set is treated as 'green' (nothing to
    gate on). Read-only — never mutates.
    """
    raw = RUN(["pr", "checks", str(pr_number), "--repo", repo, "--json", "state"])
    rows = json.loads(raw) if raw.strip() else []
    states = [str(r.get("state", "")).upper() for r in rows] if isinstance(rows, list) else []
    fail = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    pend = {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED"}
    if any(s in fail for s in states):
        return "red"
    if any(s in pend for s in states):
        return "pending"
    return "green"


# --------------------------------------------------------------------------- #
# Non-squash merge (AC-19) — NEVER --squash; the guard hard-blocks it too.
# --------------------------------------------------------------------------- #
def merge_pr(repo: str, pr_number, method: str = "merge") -> dict:
    """Merge a PR via `gh pr merge --merge`/`--rebase` only — NEVER `--squash`.

    `method` must be 'merge' or 'rebase' (GhError code=2 otherwise). The caller
    gates on green checks; this verb's invariant is simply that it never issues
    `--squash` (no-squash is also enforced by hooks/guard.sh, AC-25).
    """
    m = str(method).lower()
    if m not in ("merge", "rebase"):
        raise GhError(
            f"merge method must be 'merge' or 'rebase', never 'squash' (got {method!r})",
            code=2,
        )
    RUN(["pr", "merge", str(pr_number), "--repo", repo, f"--{m}"])
    return {"merged": True, "pr": pr_number, "method": m}


# --------------------------------------------------------------------------- #
# Milestone assign (AC-3, AC-12) — REST PATCH, idempotent (read current first)
# --------------------------------------------------------------------------- #
def set_milestone(repo: str, issue_number, milestone) -> dict:
    """Assign a repo Milestone NUMBER to an issue via REST, idempotently (AC-3).

    Reads the issue's current milestone first; if it already points at the same
    milestone number, makes NO write (returns {"changed": False}). So a
    re-assign to the same milestone is one effective write across two calls.
    """
    target = int(milestone)
    current = rest("GET", f"/repos/{repo}/issues/{int(issue_number)}") or {}
    cur_ms = current.get("milestone") or {}
    cur_num = cur_ms.get("number")
    if cur_num is not None and int(cur_num) == target:
        return {"changed": False, "issue": int(issue_number), "milestone": target}
    rest("PATCH", f"/repos/{repo}/issues/{int(issue_number)}", {"milestone": target})
    return {"changed": True, "issue": int(issue_number), "milestone": target}


# --------------------------------------------------------------------------- #
# Board-item manual-rank reorder (AC-4, AC-14) — App-token write.
# --------------------------------------------------------------------------- #
_REORDER_ITEM = """
mutation($project:ID!, $item:ID!, $after:ID){
  updateProjectV2ItemPosition(input:{projectId:$project, itemId:$item, afterId:$after}){
    items { totalCount }
  }
}
"""

_REORDER_ITEM_TOP = """
mutation($project:ID!, $item:ID!){
  updateProjectV2ItemPosition(input:{projectId:$project, itemId:$item}){
    items { totalCount }
  }
}
"""


def reorder_item(project_id: str, item_id: str, after_item_id: str | None = None) -> dict:
    """Reorder a board item's manual rank via updateProjectV2ItemPosition (AC-4).

    `after_item_id=None` OMITS afterId entirely and moves the item to the TOP of
    the manual order. App-token write (Projects v2, never GITHUB_TOKEN — AC-28).
    """
    if after_item_id is None:
        data = graphql(_REORDER_ITEM_TOP, {"project": project_id, "item": item_id})
    else:
        data = graphql(_REORDER_ITEM,
                       {"project": project_id, "item": item_id, "after": after_item_id})
    return {"reordered": item_id, "after": after_item_id,
            "result": data.get("updateProjectV2ItemPosition")}


# --------------------------------------------------------------------------- #
# Issue Assignee add/remove (AC-5) — idempotent.
# --------------------------------------------------------------------------- #
def _current_assignees(repo: str, issue_number) -> set:
    issue = rest("GET", f"/repos/{repo}/issues/{int(issue_number)}") or {}
    return {a.get("login") for a in (issue.get("assignees") or []) if a.get("login")}


def set_assignee(repo: str, issue_number, login: str, remove: bool = False) -> dict:
    """Add or remove an issue Assignee via `gh issue edit`, idempotently (AC-5).

    Adding an already-present assignee — or removing an absent one — makes NO
    write (returns {"changed": False}). Mirrors the lib's diff-before-mutate
    idempotency style (AC-33).
    """
    present = login in _current_assignees(repo, issue_number)
    if remove:
        if not present:
            return {"changed": False, "issue": int(issue_number), "login": login, "removed": True}
        RUN(["issue", "edit", str(int(issue_number)), "--repo", repo,
             "--remove-assignee", login])
        return {"changed": True, "issue": int(issue_number), "login": login, "removed": True}
    if present:
        return {"changed": False, "issue": int(issue_number), "login": login, "removed": False}
    RUN(["issue", "edit", str(int(issue_number)), "--repo", repo,
         "--add-assignee", login])
    return {"changed": True, "issue": int(issue_number), "login": login, "removed": False}


# --------------------------------------------------------------------------- #
# Link a repo to the Project (AC-21) — real linkProjectV2ToRepository, App-token,
# idempotent (read the project's linked repositories; skip if already linked).
# --------------------------------------------------------------------------- #
_PROJECT_LINKED_REPOS = """
query($project:ID!){
  node(id:$project){
    ... on ProjectV2 {
      repositories(first:100){ nodes { id } }
    }
  }
}
"""

_LINK_REPO = """
mutation($project:ID!, $repo:ID!){
  linkProjectV2ToRepository(input:{projectId:$project, repositoryId:$repo}){
    repository { id }
  }
}
"""


def _project_linked_repo_ids(project_id: str) -> set:
    """Read the Project's currently-linked repository node ids (read-only)."""
    data = graphql(_PROJECT_LINKED_REPOS, {"project": project_id})
    node = (data or {}).get("node") or {}
    nodes = ((node.get("repositories") or {}).get("nodes")) or []
    return {n.get("id") for n in nodes if n.get("id")}


def link_repo(project_id: str, repo_id: str) -> dict:
    """Link a repository to a Project via linkProjectV2ToRepository (AC-21).

    Idempotent: reads the project's already-linked repositories first and makes
    NO write when `repo_id` is already linked (returns {"changed": False}). The
    write is an App-token Projects v2 mutation — never GITHUB_TOKEN (AC-28).
    """
    if repo_id in _project_linked_repo_ids(project_id):
        return {"changed": False, "project": project_id, "repo": repo_id, "linked": True}
    data = graphql(_LINK_REPO, {"project": project_id, "repo": repo_id})
    return {"changed": True, "project": project_id, "repo": repo_id, "linked": True,
            "result": data.get("linkProjectV2ToRepository")}


# --------------------------------------------------------------------------- #
# Link a Project to a team (AC-23) — a REAL linkProjectV2ToTeam(projectId,teamId)
# write-to-team mutation. NOT the scaffold _LINK_PROJECT_APP confirmation no-op.
# Idempotent the same way link_repo is: read the project's linked teams; skip if
# already linked (detected and skipped, never a 4xx re-link — AC-33).
# --------------------------------------------------------------------------- #
_PROJECT_LINKED_TEAMS = """
query($project:ID!){
  node(id:$project){
    ... on ProjectV2 {
      teams(first:100){ nodes { id } }
    }
  }
}
"""

_LINK_TEAM = """
mutation($project:ID!, $team:ID!){
  linkProjectV2ToTeam(input:{projectId:$project, teamId:$team}){
    team { id }
  }
}
"""


def _project_linked_team_ids(project_id: str) -> set:
    """Read the Project's currently-linked team node ids (read-only)."""
    data = graphql(_PROJECT_LINKED_TEAMS, {"project": project_id})
    node = (data or {}).get("node") or {}
    nodes = ((node.get("teams") or {}).get("nodes")) or []
    return {n.get("id") for n in nodes if n.get("id")}


def link_team(project_id: str, team_id: str) -> dict:
    """Link a Project to a team via linkProjectV2ToTeam (AC-23) — write-to-team.

    A real `linkProjectV2ToTeam(projectId, teamId)` mutation (the `teamId` is
    actually sent), distinct from scaffold's grant_app_access confirmation touch.
    App-token Projects v2 write — never GITHUB_TOKEN (AC-28). Idempotent like
    `link_repo`: reads the project's already-linked teams first and makes NO write
    when `team_id` is already linked (returns {"changed": False}) — detected and
    skipped, never a 409/422 re-link (AC-33).
    """
    if team_id in _project_linked_team_ids(project_id):
        return {"changed": False, "project": project_id, "team": team_id, "linked": True}
    data = graphql(_LINK_TEAM, {"project": project_id, "team": team_id})
    return {"changed": True, "project": project_id, "team": team_id, "linked": True,
            "result": data.get("linkProjectV2ToTeam")}


# --------------------------------------------------------------------------- #
# Issue node-id / linked-branch / default-branch resolution (read-only) — these
# back the route-issue projection verbs (add-item / write-field / advance-status /
# create-linked-branch). No new mutation here; they reuse the §1 lib functions.
# --------------------------------------------------------------------------- #
def _split_repo(repo: str):
    """Split an `owner/name` string into (owner, name). GhError(2) if malformed."""
    parts = str(repo).split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise GhError(f"--repo must be owner/name (got {repo!r})", code=2)
    return parts[0], parts[1]


def issue_node_id(repo: str, issue_number) -> str:
    """Resolve an issue's GraphQL node id via REST GET (read-only)."""
    owner, name = _split_repo(repo)
    issue = rest("GET", f"/repos/{owner}/{name}/issues/{int(issue_number)}") or {}
    node_id = issue.get("node_id")
    if not node_id:
        raise GhError(f"issue {repo}#{issue_number} not found", code=3)
    return node_id


_ITEM_STATUS_QUERY = """
query($owner:String!, $number:Int!, $content:ID!){
  node(id:$content){
    ... on Issue {
      projectItems(first:50){
        nodes{
          id
          project { number owner { ... on Organization { login } } }
          fieldValueByName(name:"Status"){
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""


def current_item_status(owner: str, number: int, content_id: str) -> str | None:
    """Read the issue's current board Status option NAME on this project, or None.

    Read-only. Returns None when the issue is not on the board, or has no Status
    set yet (so advance_status treats it as a fresh advance to the target).
    """
    data = graphql(_ITEM_STATUS_QUERY,
                   {"owner": owner, "number": int(number), "content": content_id})
    node = (data or {}).get("node") or {}
    for item in ((node.get("projectItems") or {}).get("nodes")) or []:
        proj = item.get("project") or {}
        powner = (proj.get("owner") or {}).get("login")
        if proj.get("number") == int(number) and (powner is None or powner == owner):
            sv = item.get("fieldValueByName") or {}
            return sv.get("name")
    return None


_ISSUE_LINKED_BRANCHES = """
query($owner:String!, $name:String!, $number:Int!){
  repository(owner:$owner, name:$name){
    defaultBranchRef { target { oid } }
    issue(number:$number){
      id
      linkedBranches(first:10){ nodes { ref { name } } }
    }
  }
}
"""


def issue_linked_branch_state(repo: str, issue_number) -> dict:
    """Read an issue's existing linked branches + the repo default-branch oid.

    Read-only. Returns {"issue_id", "default_oid", "branches": [names]} so the
    create-linked-branch verb can no-op when a linked branch already exists (AC-9).
    """
    owner, name = _split_repo(repo)
    data = graphql(_ISSUE_LINKED_BRANCHES,
                   {"owner": owner, "name": name, "number": int(issue_number)})
    repo_node = (data or {}).get("repository") or {}
    issue = repo_node.get("issue") or {}
    if not issue.get("id"):
        raise GhError(f"issue {repo}#{issue_number} not found", code=3)
    oid = (((repo_node.get("defaultBranchRef") or {}).get("target")) or {}).get("oid")
    branches = [
        (n.get("ref") or {}).get("name")
        for n in ((issue.get("linkedBranches") or {}).get("nodes")) or []
        if (n.get("ref") or {}).get("name")
    ]
    return {"issue_id": issue["id"], "default_oid": oid, "branches": branches}


# --------------------------------------------------------------------------- #
# CLI — documented exit codes 0/2/3/1; prints no token/secret (AC-3)
# --------------------------------------------------------------------------- #
def _print_json(obj) -> None:
    sys.stdout.write(_scrub(json.dumps(obj)) + "\n")


def _cmd_resolve(args) -> int:
    proj = Project(args.owner, args.number).resolve()
    _print_json({"id": proj.id, "title": proj.title,
                 "fields": sorted(proj._fields_by_name.keys())})
    return 0


def _cmd_capabilities(_args) -> int:
    caps = Capabilities()
    _print_json({k: caps.has(k) for k in
                 ("add_blocked_by", "linked_branch", "add_sub_issue", "issue_type")})
    return 0


def _cmd_token(_args) -> int:
    """Mint an App installation token — prints ONLY a redacted confirmation,
    never the token itself (AC-3)."""
    token = get_app_token()
    _print_json({"app_token": "[REDACTED]", "len": len(token), "ok": True})
    return 0


def _cmd_open_pr(args) -> int:
    res = open_or_update_pr(args.repo, args.head, args.base, args.number,
                            title=args.title, body_extra=args.body, draft=args.draft)
    _print_json(res)
    return 0


def _cmd_pr_checks(args) -> int:
    _print_json({"state": pr_check_state(args.repo, args.pr)})
    return 0


def _cmd_merge_pr(args) -> int:
    _print_json(merge_pr(args.repo, args.pr, args.method))
    return 0


def _cmd_set_milestone(args) -> int:
    _print_json(set_milestone(args.repo, args.number, args.milestone))
    return 0


def _cmd_reorder_item(args) -> int:
    _print_json(reorder_item(args.project_id, args.item, args.after))
    return 0


def _cmd_set_assignee(args) -> int:
    _print_json(set_assignee(args.repo, args.number, args.login, remove=args.remove))
    return 0


def _cmd_link_repo(args) -> int:
    _print_json(link_repo(args.project_id, args.repo_id))
    return 0


def _cmd_link_team(args) -> int:
    _print_json(link_team(args.project_id, args.team_id))
    return 0


# -- route-issue / plan-sprint projection verbs (reuse §1 lib, idempotent) ---- #
def _cmd_add_item(args) -> int:
    """Project an issue onto the board (add_item). Idempotent: a re-add returns
    the SAME item id (addProjectV2ItemById is server-side idempotent — AC-8)."""
    proj = Project(args.owner, args.number).resolve()
    content_id = issue_node_id(args.repo, args.issue)
    item_id = add_item(proj.id, content_id)
    _print_json({"item": item_id, "issue": int(args.issue), "project": proj.id})
    return 0


def _cmd_write_field(args) -> int:
    """Write one board field for the issue's item (write_field — add_item + set +
    read-back-identical). Single-select=option name, iteration(Sprint)=iteration
    title, number/date/text=raw. Idempotent: the read-back verifies the value."""
    proj = Project(args.owner, args.number).resolve()
    content_id = issue_node_id(args.repo, args.issue)
    res = write_field(proj, content_id, args.field, args.value)
    _print_json(res)
    return 0


def _cmd_advance_status(args) -> int:
    """Advance the issue's board Status MONOTONICALLY (advance_status). Ensures the
    item exists (add_item idempotent), reads the current Status, and writes only a
    forward move; an at/past-target re-run is a no-op (no write — AC-10/AC-17)."""
    proj = Project(args.owner, args.number).resolve()
    content_id = issue_node_id(args.repo, args.issue)
    add_item(proj.id, content_id)  # idempotent: reuse existing item if present
    current = current_item_status(args.owner, args.number, content_id)
    to_write = advance_status(current, args.to)
    if to_write is None:
        _print_json({"decision": "no-op", "current": current, "target": args.to,
                     "reason": "already at/past target (monotonic)"})
        return 0
    res = write_field(proj, content_id, "Status", to_write)
    _print_json({"decision": "advanced", "from": current, "to": to_write,
                 "verified": res.get("verified", False)})
    return 0


def _cmd_create_linked_branch(args) -> int:
    """Create the issue's authoritative linked branch — IDEMPOTENT: if a linked
    branch already exists, NO-OP exit 0 (AC-9). Otherwise resolve the issue node id
    + default-branch head oid and create it (native `gh issue develop` when
    supported, else GraphQL createLinkedBranch)."""
    state = issue_linked_branch_state(args.repo, args.issue)
    if state["branches"]:
        _print_json({"action": "already-linked", "issue": int(args.issue),
                     "branches": state["branches"]})
        return 0
    res = create_linked_branch(
        state["issue_id"], state["default_oid"], name=args.name,
        repo=args.repo, issue_number=args.issue)
    _print_json({"action": "created", "issue": int(args.issue),
                 "via": res.get("via"), "name": args.name})
    return 0


def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="gh.py", description="gh-projects GraphQL/REST core")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("resolve", help="resolve & cache a project's field/option/iteration ids")
    sp.add_argument("--owner", required=True)
    sp.add_argument("--number", type=int, required=True)
    sp.set_defaults(func=_cmd_resolve)

    sp = sub.add_parser("capabilities", help="probe the installed gh for native flags")
    sp.set_defaults(func=_cmd_capabilities)

    sp = sub.add_parser("token", help="mint an App installation token (redacted output)")
    sp.set_defaults(func=_cmd_token)

    # -- write verbs (gated by engine.sh's --force rail) --------------------- #
    sp = sub.add_parser("open-pr", help="open/update an issue-linked PR (non-closing)")
    sp.add_argument("--repo", required=True, help="owner/repo")
    sp.add_argument("--head", required=True, help="head branch")
    sp.add_argument("--base", required=True, help="base branch")
    sp.add_argument("--number", type=int, required=True, help="related issue number")
    sp.add_argument("--title", default=None)
    sp.add_argument("--body", default=None, help="extra body text (a Relates-to is appended)")
    sp.add_argument("--draft", action="store_true")
    sp.set_defaults(func=_cmd_open_pr)

    sp = sub.add_parser("pr-checks", help="read a PR's aggregate check state (green/red/pending)")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--pr", type=int, required=True)
    sp.set_defaults(func=_cmd_pr_checks)

    sp = sub.add_parser("merge-pr", help="non-squash merge a PR (--merge/--rebase only)")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--pr", type=int, required=True)
    sp.add_argument("--method", default="merge", choices=["merge", "rebase"])
    sp.set_defaults(func=_cmd_merge_pr)

    sp = sub.add_parser("set-milestone", help="assign a repo milestone number to an issue (idempotent)")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--number", type=int, required=True, help="issue number")
    sp.add_argument("--milestone", type=int, required=True, help="repo-scoped milestone number")
    sp.set_defaults(func=_cmd_set_milestone)

    sp = sub.add_parser("reorder-item", help="reorder a board item's manual rank (omit --after for top)")
    sp.add_argument("--project-id", required=True, dest="project_id")
    sp.add_argument("--item", required=True, help="board item id")
    sp.add_argument("--after", default=None, help="item id to place after; omit for top")
    sp.set_defaults(func=_cmd_reorder_item)

    sp = sub.add_parser("set-assignee", help="add/remove an issue assignee (idempotent)")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--number", type=int, required=True, help="issue number")
    sp.add_argument("--login", required=True)
    sp.add_argument("--remove", action="store_true")
    sp.set_defaults(func=_cmd_set_assignee)

    sp = sub.add_parser("link-repo", help="link a repo to a Project (idempotent, App-token)")
    sp.add_argument("--project-id", required=True, dest="project_id")
    sp.add_argument("--repo-id", required=True, dest="repo_id", help="repository node id")
    sp.set_defaults(func=_cmd_link_repo)

    sp = sub.add_parser("link-team", help="link a Project to a team (write-to-team, App-token)")
    sp.add_argument("--project-id", required=True, dest="project_id")
    sp.add_argument("--team-id", required=True, dest="team_id", help="team node id")
    sp.set_defaults(func=_cmd_link_team)

    sp = sub.add_parser("add-item", help="project an issue onto the board (idempotent, same item id on re-add)")
    sp.add_argument("--owner", required=True, help="org login")
    sp.add_argument("--number", type=int, required=True, help="project number")
    sp.add_argument("--repo", required=True, help="owner/name")
    sp.add_argument("--issue", type=int, required=True, help="issue number")
    sp.set_defaults(func=_cmd_add_item)

    sp = sub.add_parser("write-field", help="write one board field for an issue's item (read-back-verified)")
    sp.add_argument("--owner", required=True, help="org login")
    sp.add_argument("--number", type=int, required=True, help="project number")
    sp.add_argument("--repo", required=True, help="owner/name")
    sp.add_argument("--issue", type=int, required=True, help="issue number")
    sp.add_argument("--field", required=True, help="board field name")
    sp.add_argument("--value", required=True,
                    help="option name (single-select) / iteration title (Sprint) / number / date / text")
    sp.set_defaults(func=_cmd_write_field)

    sp = sub.add_parser("advance-status", help="advance an issue's board Status monotonically (no-op past target)")
    sp.add_argument("--owner", required=True, help="org login")
    sp.add_argument("--number", type=int, required=True, help="project number")
    sp.add_argument("--repo", required=True, help="owner/name")
    sp.add_argument("--issue", type=int, required=True, help="issue number")
    sp.add_argument("--to", required=True, help="target Status (Backlog<Ready<In Progress<In Review<On Staging<Done)")
    sp.set_defaults(func=_cmd_advance_status)

    sp = sub.add_parser("create-linked-branch",
                        help="create an issue's authoritative linked branch (idempotent: existing branch = no-op)")
    sp.add_argument("--repo", required=True, help="owner/name")
    sp.add_argument("--issue", type=int, required=True, help="issue number")
    sp.add_argument("--name", default=None, help="branch name (optional; gh/GraphQL default otherwise)")
    sp.set_defaults(func=_cmd_create_linked_branch)

    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        # argparse exits 2 on usage error — keep our documented usage code.
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        return args.func(args)
    except GhError as e:
        sys.stderr.write("error: " + _scrub(str(e)) + "\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + _scrub(str(e)) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
