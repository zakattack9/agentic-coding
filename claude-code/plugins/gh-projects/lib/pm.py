#!/usr/bin/env python3
"""gh-projects PM-ID allocator + flow-style front-matter (Phase 1).

Salvaged from pm-ops/lib/pm.py, trimmed to what gh-projects needs: the
monotonic `PM-####` allocator + registry and the dependency-free flow-style
YAML-subset front-matter parse/serialize/normalize that round-trips T3 deep
specs WITHOUT loss (AC-5). The pm-ops folder-as-stage / index.md machinery is
deliberately DROPPED — the GitHub Project replaces it (spec "Locked decisions":
"No markdown-canonical sync, no folder-as-stage, ... no index.md").

Stdlib only. Exit codes: 0 ok · 2 usage/validation · 3 not found · 1 unexpected.

Subcommands:
  new-id    [--registry FILE] [--prefix PM]   allocate the next stable id (prints PM-0042)
  read      FILE                              print the file's front-matter as JSON
  set       FILE KEY=VALUE ...                upsert front-matter keys (VALUE is JSON or a string)
  normalize FILE                              print the engine-neutral normalized task JSON
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict

# Keys carried into the normalized task the GitHub layer consumes.
NORMALIZED_KEYS = [
    "id", "title", "type", "status", "size", "tier", "priority",
    "parent", "depends_on", "blocked_by", "spec", "impl_repo",
    "labels", "assignees", "milestone", "sprint", "board",
]

DEFAULT_REGISTRY = {"prefix": "PM", "next": 1}


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class PmError(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- #
# Front-matter parse / serialize  (dependency-free flow-style subset)
# --------------------------------------------------------------------------- #
FM_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)$", re.DOTALL)


def split_front_matter(text: str):
    """Return (front_matter_dict, body_str). No front matter -> ({}, text)."""
    m = FM_RE.match(text)
    if not m:
        return OrderedDict(), text
    raw, body = m.group(1), m.group(2)
    return parse_yaml_subset(raw), body


def _scalar(token: str):
    token = token.strip()
    if token == "" or token in ("~", "null"):
        return None
    if (token[0] == '"' and token[-1] == '"') or (token[0] == "'" and token[-1] == "'"):
        return token[1:-1]
    if token in ("true", "True"):
        return True
    if token in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token


def _split_top_level(s: str):
    """Split on commas not nested inside quotes/brackets/braces."""
    out, depth, buf, quote = [], 0, [], None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf))
    return out


def _parse_flow(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_scalar(p) for p in _split_top_level(inner)] if inner else []
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        d = OrderedDict()
        for part in _split_top_level(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip()] = _parse_flow(v) if v.strip()[:1] in "[{" else _scalar(v)
        return d
    return _scalar(value)


def parse_yaml_subset(raw: str) -> "OrderedDict":
    # Prefer PyYAML when present (handles any valid YAML the user hand-edits).
    try:
        import yaml  # type: ignore
        loaded = yaml.safe_load(raw)
        if isinstance(loaded, dict):
            return OrderedDict(loaded)
        if loaded is None:
            return OrderedDict()
    except Exception:
        pass

    data: "OrderedDict" = OrderedDict()
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if re.match(r"^\s", line):  # stray indented line with no parent key
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:  # inline scalar / flow collection
            data[key] = _parse_flow(rest)
            i += 1
            continue
        # Empty value -> look ahead for an indented block (list or map).
        block, j = [], i + 1
        while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
            if lines[j].strip():
                block.append(lines[j])
            j += 1
        if block and block[0].strip().startswith("- "):
            data[key] = [_scalar(b.strip()[2:]) for b in block]
        elif block:
            sub = OrderedDict()
            for b in block:
                if ":" in b:
                    k, v = b.split(":", 1)
                    sub[k.strip()] = _parse_flow(v.strip()) if v.strip()[:1] in "[{" else _scalar(v)
            data[key] = sub
        else:
            data[key] = None
        i = j
    return data


def _needs_quote(s: str) -> bool:
    return (
        s == ""
        or s != s.strip()
        or any(c in s for c in ":#{}[],&*!|>'\"%@`")
        or s in ("true", "false", "null", "~")
        or bool(re.fullmatch(r"-?\d+", s))
    )


def _emit_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return '"' + s.replace('"', '\\"') + '"' if _needs_quote(s) else s


def _emit_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(_emit_scalar(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_emit_scalar(val)}" for k, val in v.items()) + "}"
    return _emit_scalar(v)


def serialize_front_matter(data: "OrderedDict") -> str:
    return "".join(f"{k}: {_emit_value(v)}\n" for k, v in data.items())


def compose(data: "OrderedDict", body: str) -> str:
    body = body if body.startswith("\n") or body == "" else "\n" + body
    if body and not body.endswith("\n"):
        body += "\n"
    return f"---\n{serialize_front_matter(data)}---\n{body}"


def read_file(path: str) -> str:
    if not os.path.isfile(path):
        raise PmError(f"no such file: {path}", code=3)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# PM-#### allocator (monotonic, registry-backed)
# --------------------------------------------------------------------------- #
def allocate_id(registry_path: str, prefix: str | None = None) -> str:
    """Allocate the next monotonic PM-#### id and persist the bump.

    Reads the registry's `next`, formats `{prefix}-{next:04d}`, writes back
    `next+1`. Monotonic across calls/processes (the file is the source of
    truth). Creates the registry on first use.
    """
    if os.path.isfile(registry_path):
        with open(registry_path, "r", encoding="utf-8") as fh:
            reg = json.load(fh)
    else:
        reg = dict(DEFAULT_REGISTRY)
        os.makedirs(os.path.dirname(registry_path) or ".", exist_ok=True)
    prefix = prefix or reg.get("prefix") or "PM"
    nxt = int(reg.get("next", 1))
    if nxt < 1:
        raise PmError(f"corrupt registry: next={nxt}", code=2)
    reg["prefix"] = prefix
    reg["next"] = nxt + 1
    with open(registry_path, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=2)
        fh.write("\n")
    return f"{prefix}-{nxt:04d}"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_new_id(args) -> int:
    print(allocate_id(args.registry, args.prefix))
    return 0


def cmd_read(args) -> int:
    data, _body = split_front_matter(read_file(args.file))
    print(json.dumps(data, indent=2))
    return 0


def _coerce_value(raw: str):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def cmd_set(args) -> int:
    text = read_file(args.file)
    data, body = split_front_matter(text)
    if not args.assignments:
        raise PmError("set requires at least one KEY=VALUE")
    for pair in args.assignments:
        if "=" not in pair:
            raise PmError(f"bad assignment '{pair}' (expected KEY=VALUE)")
        key, _, raw = pair.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise PmError(f"invalid key '{key}'")
        data[key] = _coerce_value(raw)
    with open(args.file, "w", encoding="utf-8") as fh:
        fh.write(compose(data, body))
    print(json.dumps({"file": args.file, "set": [p.split("=", 1)[0] for p in args.assignments], "ok": True}))
    return 0


def cmd_normalize(args) -> int:
    data, _body = split_front_matter(read_file(args.file))
    task = OrderedDict()
    for key in NORMALIZED_KEYS:
        if key not in data:
            continue
        val = data[key]
        # Drop absent / empty values (incl. unfilled `{{...}}` placeholders).
        if val is None or val == "" or val == {} or val == []:
            continue
        task[key] = val
    if "id" not in task:
        raise PmError(f"{args.file} has no 'id' in front-matter; not a gh-projects artifact", code=2)
    for list_key in ("depends_on", "blocked_by", "labels", "assignees"):
        if list_key in task and not isinstance(task[list_key], list):
            task[list_key] = [task[list_key]]
    print(json.dumps(task))
    return 0


# --------------------------------------------------------------------------- #
# Arg parsing
# --------------------------------------------------------------------------- #
def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="pm.py", description="gh-projects PM-ID + front-matter core")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new-id")
    sp.add_argument("--registry", default=".gh-projects/registry.json")
    sp.add_argument("--prefix", default=None)
    sp.set_defaults(func=cmd_new_id)

    sp = sub.add_parser("read")
    sp.add_argument("file")
    sp.set_defaults(func=cmd_read)

    sp = sub.add_parser("set")
    sp.add_argument("file")
    sp.add_argument("assignments", nargs="*")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("normalize")
    sp.add_argument("file")
    sp.set_defaults(func=cmd_normalize)
    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        return args.func(args)
    except PmError as e:
        sys.stderr.write(f"error: {e}\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"error: unexpected: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
