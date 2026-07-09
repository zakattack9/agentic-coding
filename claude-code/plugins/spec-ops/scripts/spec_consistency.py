#!/usr/bin/env python3
"""spec_consistency.py — deterministic Acceptance-Criteria integrity check for a spec.

refine-spec edits ACs heavily (add / split / renumber / regroup), so a spec can end up
with a leftover merge-conflict marker, a DUPLICATE AC number, or a DANGLING AC reference
(an `AC-N` cited in the body / checklist with no defining row). These are mechanical
defects a grep catches deterministically — cheaper and more reliable than hoping a model
notices. refine-spec runs it each pass and its Stop hook blocks on a real failure;
verify-spec can reuse it. (loop-spec's emitted loop carries the equivalent inline shell
check, since a pasted /goal prompt can't resolve ${CLAUDE_PLUGIN_ROOT} — MIRROR-ANCHOR:
keep the two in sync.)

Checks — scoped to the `## Acceptance Criteria` section so other numeric tables can't
false-positive as AC rows (references are scanned across the whole spec):
  1. leftover git conflict markers (`<<<<<<<` / `>>>>>>>`; never `=======`, a setext underline)
  2. duplicate AC numbers among the definition rows
  3. dangling `AC-N` references — cited anywhere but never defined

Usage:  python3 spec_consistency.py <spec.md>
Exit:   0  clean
        2  problems found (printed, one per line — a caller blocks on this)
        3  usage error / unreadable / no `## Acceptance Criteria` section to check
"""

import re
import sys
from collections import Counter

_TOP_HEADING = re.compile(r"^##[^#]")            # a level-2 heading, not level-3+
_AC_HEADING = re.compile(r"^##\s+Acceptance Criteria\b", re.I)
_CONFLICT = re.compile(r"^(<{7}|>{7})")          # only <<<<<<< / >>>>>>>, never =======
_DEF_CELL = re.compile(r"(?:AC-)?(\d+)$")        # first table cell: bare number or AC-<n>
_REF = re.compile(r"\bAC-(\d+)\b")               # a cited AC id anywhere in the spec


def find_ac_region(lines):
    """[start, end) line indices of the `## Acceptance Criteria` section — its heading
    through the line before the next level-2 heading. None if there is no AC section."""
    start = None
    for i, ln in enumerate(lines):
        if _AC_HEADING.match(ln):
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if _TOP_HEADING.match(lines[j]):
            return (start, j)
    return (start, len(lines))


def defined_ac_numbers(region_lines):
    """AC definition rows within the AC region: a table row whose first cell is a bare
    number or `AC-<n>`. Returns the numbers in order (duplicates preserved). The header
    (`| AC |`) and separator (`| --- |`) rows have non-numeric first cells and are skipped."""
    nums = []
    for ln in region_lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        first = s.strip("|").split("|")[0].strip()
        m = _DEF_CELL.fullmatch(first)
        if m:
            nums.append(int(m.group(1)))
    return nums


def check(text):
    """Return a list of human-readable problem strings (empty == clean), or None when
    there is no AC section to check (the caller maps that to exit 3)."""
    lines = text.splitlines()
    problems = []

    for i, ln in enumerate(lines, 1):
        if _CONFLICT.match(ln):
            problems.append(f"line {i}: leftover git conflict marker ({ln[:20]!r})")

    region = find_ac_region(lines)
    if region is None:
        return problems or None  # conflict markers still reported; else "no AC section"

    defs = defined_ac_numbers(lines[region[0]:region[1]])
    defined = set(defs)

    for n, c in sorted(Counter(defs).items()):
        if c > 1:
            problems.append(f"duplicate AC number: AC-{n} is defined {c} times")

    cited = {int(m) for m in _REF.findall(text)}
    for n in sorted(cited - defined):
        problems.append(f"dangling reference: AC-{n} is cited but has no defining row")

    return problems


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: spec_consistency.py <spec.md>\n")
        return 3
    try:
        text = open(argv[0], encoding="utf-8").read()
    except OSError as e:
        sys.stderr.write(f"spec_consistency: cannot read spec: {e}\n")
        return 3

    problems = check(text)
    if problems is None:
        sys.stderr.write("spec_consistency: no '## Acceptance Criteria' section to check\n")
        return 3
    if problems:
        for p in problems:
            print(p)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
