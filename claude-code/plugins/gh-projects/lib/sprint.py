#!/usr/bin/env python3
"""gh-projects sprint planning math (Phase 1 — deterministic, free, no AI).

Pure stdlib helpers that `plan-sprint` calls for capacity and Ready-order
recommendations. NO model/AI call anywhere (AC-27). NO network. Every function
is a pure computation over its inputs, so the whole surface is exercised
offline with plain fixtures.

Exit codes (the CLI entrypoint): 0 ok · 2 usage/validation · 3 not found ·
1 unexpected — mirrors gh.py.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys


class SprintError(Exception):
    """A sprint computation failed. Carries a code for the CLI exit map."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def _parse_date(value) -> _dt.date:
    """Parse an ISO `YYYY-MM-DD` date (or accept a date already). GhError-ish."""
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError) as e:
        raise SprintError(f"invalid date {value!r}: {e}", code=2)


# --------------------------------------------------------------------------- #
# Working-day capacity (AC-6, AC-13)
# --------------------------------------------------------------------------- #
def working_day_capacity(start, end) -> int:
    """Count working days (Mon–Fri, weekends excluded) in an Iteration window.

    Boundary convention — the Iteration window is the HALF-OPEN interval
    ``[start, end)``: `start` is INCLUSIVE, `end` is EXCLUSIVE. This matches the
    Projects v2 iteration model where an iteration spans
    ``[startDate, startDate + duration)`` and the next iteration begins exactly
    on the previous one's `end`, so a day is never double-counted across
    adjacent iterations.

    `end` may be passed two ways and both agree:
      * as the exclusive end date directly, or
      * derived by the caller as ``start + duration`` (e.g. a 14-day iteration
        starting Mon counts the 10 weekdays of its two weeks).

    Weekends (Saturday=5, Sunday=6 in `date.weekday()`) are excluded. An empty
    or inverted window (``end <= start``) has zero capacity. Public holidays are
    NOT modeled (out of scope — the spec's deferral).

    Returns the integer working-day count.
    """
    s = _parse_date(start)
    e = _parse_date(end)
    if e <= s:
        return 0
    count = 0
    day = s
    one = _dt.timedelta(days=1)
    while day < e:  # half-open: end is EXCLUSIVE
        if day.weekday() < 5:  # 0=Mon … 4=Fri are working days
            count += 1
        day += one
    return count


def working_day_capacity_from_duration(start, duration_days: int) -> int:
    """Convenience: capacity of ``[start, start + duration_days)`` (half-open).

    A 14-day iteration starting on a Monday covers exactly 10 working days.
    """
    s = _parse_date(start)
    e = s + _dt.timedelta(days=int(duration_days))
    return working_day_capacity(s, e)


# --------------------------------------------------------------------------- #
# Ready-order recommendation (AC-7, AC-14)
# --------------------------------------------------------------------------- #
# Expected item shape (a list of dicts):
#   {"id": <board item id, str>,        # stable tiebreak key + reorder target
#    "priority": <int|str|None>,        # lower sorts first; missing -> last
#    "target": <"YYYY-MM-DD"|None>}     # earlier date sorts first; missing -> last
# Unknown/missing priority or target sort AFTER known ones (a None is "no signal",
# so it should not jump ahead of a graded item). The final tiebreak is the item's
# original position in the input list — a STABLE order, so the result is fully
# deterministic and a re-run over the same list yields the identical sequence.

_PRIORITY_RANK = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "p4": 4,
                  "urgent": 0, "high": 1, "medium": 2, "low": 3}

_FAR_FUTURE = _dt.date(9999, 12, 31)
_MAX_PRIORITY = 10 ** 9


def _priority_key(value):
    """Normalize a priority to a sortable int (lower = more urgent).

    Accepts an int, a numeric string, or a named bucket (P0/P1…, urgent/high/
    medium/low). Missing/unknown -> a large sentinel so it sorts LAST.
    """
    if value is None:
        return _MAX_PRIORITY
    if isinstance(value, bool):  # guard: bool is an int subclass
        return _MAX_PRIORITY
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip().lower()
    if not s:
        return _MAX_PRIORITY
    if s in _PRIORITY_RANK:
        return _PRIORITY_RANK[s]
    try:
        return int(s)
    except ValueError:
        return _MAX_PRIORITY


def _target_key(value):
    """Normalize a target date to a sortable date (earlier = first).

    Missing/empty/unparseable -> the far future so it sorts LAST.
    """
    if not value:
        return _FAR_FUTURE
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return _FAR_FUTURE


def recommend_ready_order(items):
    """Return items reordered by Priority ascending, then Target ascending.

    Deterministic with a STABLE tiebreak: items that compare equal on
    (priority, target) keep their original input order (the list index is the
    final key). Pure function — does not mutate its input; returns a new list.

    See the module-level note for the expected item shape. Missing priority or
    target sorts after known values (a None is "no signal").
    """
    indexed = list(enumerate(items or []))

    def key(pair):
        idx, it = pair
        return (_priority_key((it or {}).get("priority")),
                _target_key((it or {}).get("target")),
                idx)

    return [it for _, it in sorted(indexed, key=key)]


# --------------------------------------------------------------------------- #
# CLI — documented exit codes 0/2/3/1 (no AI, no token, no secret)
# --------------------------------------------------------------------------- #
def _print_json(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")


def _cmd_capacity(args) -> int:
    if args.duration is not None:
        cap = working_day_capacity_from_duration(args.start, args.duration)
    else:
        if not args.end:
            raise SprintError("capacity needs --end or --duration", code=2)
        cap = working_day_capacity(args.start, args.end)
    _print_json({"working_days": cap})
    return 0


def _cmd_ready_order(args) -> int:
    raw = sys.stdin.read() if args.items == "-" else args.items
    try:
        items = json.loads(raw) if raw and raw.strip() else []
    except json.JSONDecodeError as e:
        raise SprintError(f"invalid items JSON: {e}", code=2)
    if not isinstance(items, list):
        raise SprintError("items must be a JSON array", code=2)
    _print_json({"order": [it.get("id") for it in recommend_ready_order(items)]})
    return 0


def build_parser():
    import argparse

    p = argparse.ArgumentParser(prog="sprint.py", description="gh-projects sprint math")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("capacity", help="working-day capacity of an iteration window")
    sp.add_argument("--start", required=True, help="iteration start (YYYY-MM-DD, inclusive)")
    sp.add_argument("--end", default=None, help="iteration end (YYYY-MM-DD, EXCLUSIVE)")
    sp.add_argument("--duration", type=int, default=None, help="iteration length in days")
    sp.set_defaults(func=_cmd_capacity)

    sp = sub.add_parser("ready-order", help="recommended Ready order (Priority↑ then Target↑)")
    sp.add_argument("--items", default="-", help="JSON array of items, or - for stdin")
    sp.set_defaults(func=_cmd_ready_order)

    return p


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else (e.code or 0)
    try:
        return args.func(args)
    except SprintError as e:
        sys.stderr.write("error: " + str(e) + "\n")
        return e.code
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("error: unexpected: " + str(e) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
