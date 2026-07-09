#!/usr/bin/env python3
"""spec_consistency.py — deterministic Acceptance-Criteria integrity check for a spec.

refine-spec edits ACs heavily (add / split / renumber / regroup), so a spec can end up
with a leftover merge-conflict marker, a DUPLICATE AC number, or a DANGLING AC reference
(an `AC-N` cited in the body / checklist with no defining row). These are mechanical
defects a grep catches deterministically — cheaper and more reliable than hoping a model
notices. refine-spec runs it each pass and its Stop hook blocks on a *blocking* problem;
verify-spec can reuse it. (loop-spec's emitted loop carries a coarser inline shell mirror,
since a pasted /goal prompt can't resolve ${CLAUDE_PLUGIN_ROOT}. The loop *adjudicates*
each finding rather than hard-blocking, so exact parity isn't required — keep the two
conceptually aligned. MIRROR-ANCHOR: loop-spec/SKILL.md «CONSISTENCY_CHECK».)

To avoid false-positive blocks on legitimately-finalizable specs, fenced code blocks are
masked before scanning (a spec may *illustrate* a conflict marker or an `AC-N` token in an
example), and AC definitions are read only from real AC tables (header first cell `AC` —
the canonical `| AC | Criterion |` shape), so a legend / priority / decision matrix sitting
in the AC section isn't mistaken for AC rows.

Two severities:
  BLOCKING (a caller should block finalization on these — mechanically unambiguous):
    1. leftover git conflict markers (`<<<<<<<` / `>>>>>>>`; never `=======`, a setext
       underline), scanned OUTSIDE fenced code
    2. duplicate AC numbers among the AC-table definition rows
  ADVISORY (reported, never blocking — a bare `AC-N` may legitimately reference a sibling
  spec, which is not deterministically distinguishable from a true internal orphan):
    3. dangling `AC-N` references — cited (outside code fences) but never defined here

Usage:  python3 spec_consistency.py <spec.md>
Exit:   0  clean, or advisories only (printed to stderr, non-blocking)
        2  blocking problems found (printed to stdout, one per line — a caller blocks)
        3  usage error / unreadable / no `## Acceptance Criteria` section to check
"""

import re
import sys
from collections import Counter

_TOP_HEADING = re.compile(r"^##[^#]")            # a level-2 heading, not level-3+
_AC_HEADING = re.compile(r"^##\s+Acceptance Criteria\b", re.I)
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")         # a fenced-code-block delimiter line
_CONFLICT = re.compile(r"^(<{7}|>{7})")          # only <<<<<<< / >>>>>>>, never =======
_DEF_CELL = re.compile(r"(?:AC-)?(\d+)$")        # first table cell: bare number or AC-<n>
_SEP_CELL = re.compile(r"^:?-{1,}:?$")           # a table separator cell (---, :--:, etc.)
_REF = re.compile(r"\bAC-(\d+)\b")               # a cited AC id anywhere in the spec


def mask_fenced_code(lines):
    """Return a copy of `lines` with every line inside a fenced code block (and the fence
    delimiters themselves) replaced by an empty string. Line count is preserved so reported
    line numbers stay accurate. A real leftover merge marker sits raw *outside* any fence,
    so masking fences never hides one — it only drops illustrative markers/refs in examples."""
    out = []
    in_fence = False
    for ln in lines:
        if _FENCE.match(ln):
            in_fence = not in_fence
            out.append("")           # blank the delimiter line too
            continue
        out.append("" if in_fence else ln)
    return out


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
    """AC definition rows within the AC region. Only rows belonging to a table whose header
    first cell is `AC` (the canonical `| AC | Criterion |` shape) are counted, so a legend /
    priority / decision matrix that happens to sit in the AC section and has a numeric first
    column is not mistaken for AC definitions. Grouped ACs use one `| AC | ... |` table per
    `###` group, so each group's rows are counted. Returns numbers in order (dups preserved)."""
    nums = []
    in_ac_table = False
    for ln in region_lines:
        s = ln.strip()
        if not s.startswith("|"):
            in_ac_table = False                  # any non-table line ends the current table
            continue
        first = s.strip("|").split("|")[0].strip()
        if first.lower() == "ac":                # header row of a canonical AC table
            in_ac_table = True
            continue
        if not in_ac_table:
            continue
        if _SEP_CELL.match(first):               # the header/body separator row
            continue
        m = _DEF_CELL.fullmatch(first)
        if m:
            nums.append(int(m.group(1)))
    return nums


def check(text):
    """Return `(blocking, advisory)` — two lists of human-readable problem strings.
      blocking — conflict markers + duplicate AC numbers; a caller blocks on a non-empty list.
      advisory — dangling `AC-N` references; reported but never blocking.
    Returns `(None, None)` when there is no AC section AND no conflict marker to report
    (the caller maps that to exit 3 / a no-op)."""
    masked = mask_fenced_code(text.splitlines())
    blocking = []
    advisory = []

    for i, ln in enumerate(masked, 1):
        if _CONFLICT.match(ln):
            blocking.append(f"line {i}: leftover git conflict marker ({ln[:20]!r})")

    region = find_ac_region(masked)
    if region is None:
        # No AC section: only conflict markers are meaningful. Nothing else to check.
        return (blocking, []) if blocking else (None, None)

    defs = defined_ac_numbers(masked[region[0]:region[1]])
    defined = set(defs)

    for n, c in sorted(Counter(defs).items()):
        if c > 1:
            blocking.append(f"duplicate AC number: AC-{n} is defined {c} times")

    # Only scan for dangling refs once we actually have a definition set — with no detected
    # AC table (defined == empty) every citation would look dangling, a false alarm.
    if defined:
        cited = {int(m) for m in _REF.findall("\n".join(masked))}
        for n in sorted(cited - defined):
            advisory.append(f"dangling reference: AC-{n} is cited but has no defining row")

    return (blocking, advisory)


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: spec_consistency.py <spec.md>\n")
        return 3
    try:
        text = open(argv[0], encoding="utf-8").read()
    except OSError as e:
        sys.stderr.write(f"spec_consistency: cannot read spec: {e}\n")
        return 3

    blocking, advisory = check(text)
    if blocking is None:
        sys.stderr.write("spec_consistency: no '## Acceptance Criteria' section to check\n")
        return 3
    for p in advisory:
        sys.stderr.write(f"advisory (non-blocking): {p}\n")
    if blocking:
        for p in blocking:
            print(p)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
