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
    set_field, adapted to the GraphQL `value:` input.
    Returns (variables_value_json, expected_kind, expected_value).
    """
    dtype = (field_node.get("dataType") or "").upper()
    has_options = bool(field_node.get("options"))
    if "SINGLE_SELECT" in dtype or has_options:
        return ({"singleSelectOptionId": value}, "optionId", value)
    if "NUMBER" in dtype:
        return ({"number": float(value)}, "number", float(value))
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
    elif "number" in payload:
        lit = "{number:%s}" % payload["number"]
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
        if "number" in fv:
            return ("number", fv["number"])
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
    cached option id first. Returns the verified result dict.
    """
    node = project.field(field_name)
    if (node.get("dataType") or "").upper().find("SINGLE_SELECT") >= 0 or node.get("options"):
        value = project.option_id(field_name, raw_value)
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
