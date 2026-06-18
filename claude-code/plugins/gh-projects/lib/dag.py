#!/usr/bin/env python3
"""gh-projects dependency-DAG signals (Phase 1 — deterministic, no AI).

Input: the native blocked-by edges GitHub exposes (issue dependencies). From
them this derives, per item, the three board signals (AC-6):

  * Blocked      — yes/no: does the item have >=1 OPEN blocker?
  * Blast radius — None / Blocks 1 / Blocks many / Blocks release:
                   what breaks if THIS item slips, by downstream reach.
  * Blast-count  — # of DISTINCT downstream items transitively blocked by it.

"Blocks release" wins when any transitively-blocked item is a release blocker
(its `release_blocker` flag, e.g. milestone/impact = Release blocker). All math
is pure graph traversal — NO model call, NO label heuristic. Matches a
hand-checked fixture in lib/tests/test_dag.py.

Edge convention: `blocked_by[A] = [B, C]` means "A is blocked by B and C", i.e.
B and C each BLOCK A. So the "downstream" of B (what B blocks) is everything
reachable by following reversed edges.

Exit codes: 0 ok · 2 usage/validation · 3 not found · 1 unexpected.
"""
from __future__ import annotations

import json
import sys

BLAST_NONE = "None"
BLAST_ONE = "Blocks 1"
BLAST_MANY = "Blocks many"
BLAST_RELEASE = "Blocks release"


class DagError(Exception):
    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


def _build_blocks(items: dict) -> dict:
    """From per-item `blocked_by` lists, build `blocks[x] = set(items x blocks)`.

    Ignores edges whose blocker is closed (a closed blocker no longer blocks)
    and edges referencing unknown ids (degrade, don't fail).
    """
    blocks: dict[str, set] = {k: set() for k in items}
    for item_id, meta in items.items():
        for blocker in (meta.get("blocked_by") or []):
            b = str(blocker)
            if b not in items:
                continue  # unknown id — skip rather than crash
            blocker_open = items[b].get("state", "open") != "closed"
            if not blocker_open:
                continue  # a closed blocker no longer blocks
            blocks[b].add(str(item_id))
    return blocks


def _downstream(start: str, blocks: dict) -> set:
    """All items transitively reachable from `start` via the blocks-edges.

    Cycle-safe via a visited set (GitHub permits accidental dependency cycles).
    Excludes `start` itself.
    """
    seen: set = set()
    stack = list(blocks.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(blocks.get(node, ()))
    seen.discard(start)
    return seen


def is_blocked(item_id: str, items: dict) -> bool:
    """True if the item has at least one OPEN blocker (drives the Blocked flag)."""
    for blocker in (items.get(str(item_id), {}).get("blocked_by") or []):
        b = str(blocker)
        if b in items and items[b].get("state", "open") != "closed":
            return True
    return False


def signals_for(item_id: str, items: dict) -> dict:
    """Return {blocked, blast_radius, blast_count} for one item (AC-6)."""
    item_id = str(item_id)
    if item_id not in items:
        raise DagError(f"unknown item '{item_id}'", code=3)
    blocks = _build_blocks(items)
    down = _downstream(item_id, blocks)
    count = len(down)
    blocks_release = any(items.get(d, {}).get("release_blocker") for d in down)
    if blocks_release:
        radius = BLAST_RELEASE
    elif count == 0:
        radius = BLAST_NONE
    elif count == 1:
        radius = BLAST_ONE
    else:
        radius = BLAST_MANY
    return {
        "blocked": is_blocked(item_id, items),
        "blast_radius": radius,
        "blast_count": count,
    }


def compute(items: dict) -> dict:
    """Compute signals for EVERY item. Returns {item_id: signals}.

    `items` is {id: {"blocked_by": [...], "state": "open|closed",
    "release_blocker": bool}}. Blocks is built once and reused across items.
    """
    blocks = _build_blocks(items)
    out: dict[str, dict] = {}
    for item_id in items:
        item_id = str(item_id)
        down = _downstream(item_id, blocks)
        count = len(down)
        blocks_release = any(items.get(d, {}).get("release_blocker") for d in down)
        if blocks_release:
            radius = BLAST_RELEASE
        elif count == 0:
            radius = BLAST_NONE
        elif count == 1:
            radius = BLAST_ONE
        else:
            radius = BLAST_MANY
        out[item_id] = {
            "blocked": is_blocked(item_id, items),
            "blast_radius": radius,
            "blast_count": count,
        }
    return out


# --------------------------------------------------------------------------- #
# CLI — reads the items graph as JSON on stdin or from a file
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="dag.py", description="gh-projects blocked-by signals")
    parser.add_argument("file", nargs="?", help="items graph JSON (default: stdin)")
    parser.add_argument("--item", help="compute signals for a single item id")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)

    try:
        if args.file:
            import os
            if not os.path.isfile(args.file):
                sys.stderr.write(f"error: no such file: {args.file}\n")
                return 3
            with open(args.file, "r", encoding="utf-8") as fh:
                raw = fh.read()
        else:
            raw = sys.stdin.read()
        if not raw.strip():
            sys.stderr.write("error: expected items graph JSON on stdin or as FILE\n")
            return 2
        items = json.loads(raw)
        if not isinstance(items, dict):
            sys.stderr.write("error: items graph must be a JSON object {id: {...}}\n")
            return 2
        if args.item:
            print(json.dumps(signals_for(args.item, items)))
        else:
            print(json.dumps(compute(items)))
        return 0
    except DagError as e:
        sys.stderr.write(f"error: {e}\n")
        return e.code
    except json.JSONDecodeError as e:
        sys.stderr.write(f"error: invalid JSON: {e}\n")
        return 2
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"error: unexpected: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
