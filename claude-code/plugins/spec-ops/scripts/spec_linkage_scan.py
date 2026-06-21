#!/usr/bin/env python3
"""spec_linkage_scan.py — detect build-spec linkage leaking into a delivered artifact.

A spec is *build scaffolding*: the acceptance-criteria numbering, build phases, spec
ids, and predecessor-component provenance exist to drive the build, not to ship. A
finished artifact should read standalone — a future dev or agent should never be
pointed back at the spec that produced it. This scanner finds the references that tie
an artifact to its own construction so they can be stripped, while preserving the
engineering *why* (rationale, pattern callouts, in-repo cross-refs) that earns its keep.

It is the deterministic detector behind verify-spec's report-only "spec-linkage
hygiene" sweep (run it over the implementation diff), and a standalone linter for
cleaning an already-shipped artifact (run it over a path).

Five leakage classes, each with a false-positive guard so a superficially-similar KEEP
survives:

  ac-id            `AC-12`, `class AC34_Foo`            — a numbered build-spec criterion
  build-phase      `Phase 1`, `§4 lib`, `P1.3`         — a slot in the construction timeline
  spec-ref         `SPEC-12`, `foo.spec.md`, "drifted" — a pointer to the build spec itself
  provenance       "Salvaged from the old engine"      — where the code came from
  temporal         "newly exposed", "now adds"         — framing relative to the build moment

KEEPs the guards protect (never flagged):
  - `Phase 1`/`Phase 2` naming the two STEPS of a documented two-phase protocol — they
    co-occur, or sit near read-back / write-protocol / handshake tokens — not build phases;
  - `constraint #N` and other in-repo cross-refs that resolve in the shipped tree;
  - a real in-tree dependency the artifact legitimately names (e.g. a sibling package);
  - `AC-id`, `AC-group`, an Acceptance-Criteria table, and `AC-1`/`AC-N` placeholders a
    template / issue body / rubric file fills in;
  - a setup/onboarding runbook's own section numbering (e.g. `Phase 0.x` in a README/SETUP);
  - a regression-guard assertion that a deleted predecessor stays out of a manifest.

Scope & limits — this is the deterministic *first* pass, tuned for precision (no false
positives) over recall. It finds the greppable patterns above; it deliberately does NOT
judge two classes that need reading comprehension — verify-spec's hygiene sweep covers
those as a judgment pass:
  - identifier: a function / variable / class / test *named after* the spec, a build
    phase, or a predecessor rather than after what it does. Only the obvious `AC<digits>_`
    and `Phase<digit>` forms are caught here; an arbitrary one (`spec07_fields`,
    `legacy_dispatch`) is project-specific and not greppable in general.
  - background: a comment/docstring carrying inert historical context (what the code used
    to be, alternatives considered and rejected) as opposed to the load-bearing rationale
    that should stay — a distinction only judgment can draw.
So a clean exit means "no greppable linkage", not "no leakage" — pair it with the sweep.

Output (stdout):
  --json : {"findings": [{file,line,patternType,severity,snippet,autostrip,suggested}],
            "counts": {...}, "scanned": N}
  default: a human-readable grouped table.

Exit codes:  0 no leakage · 3 leakage found · 2 usage error · 1 unexpected.
(3-not-1 for "found", so a caller can branch on "clean vs has-findings" without
treating findings as a crash.)

Usage:
  spec_linkage_scan.py <path> [<path> ...]      # scan files / dirs (recursive)
  spec_linkage_scan.py --diff <base>            # scan files changed in <base>..HEAD
  spec_linkage_scan.py --json <path> ...        # machine-readable findings
  spec_linkage_scan.py --quiet <path> ...       # exit code only, no output
"""

import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------- #
# What to scan: text files only. Everything else (binaries, caches) is skipped.
# --------------------------------------------------------------------------- #
TEXT_EXTS = {".py", ".md", ".sh", ".yml", ".yaml", ".json", ".txt", ".cfg", ".toml"}
EXTRA_NAMES = {"CODEOWNERS", ".gitignore"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}

# Files where `AC-1`/`AC-N` and an Acceptance-Criteria table are a CONSUMER's own fill-in
# contract format (a template / issue body / rubric), not this artifact's build spec — so
# the ac-id rule is suppressed for them. Matched by GENERAL template/issue/rubric naming,
# never one project's filenames.
CONSUMER_AC_FILES = re.compile(
    r"ISSUE_TEMPLATE|PULL_REQUEST_TEMPLATE"
    r"|[._-]template\.\w+$|\.tmpl$"
    r"|issue[-_]?body|deep[-_]spec|[-_]rubric\.md$",
    re.IGNORECASE,
)

# A setup/onboarding runbook's own `Phase 0.x` section numbering is doc scaffolding (its
# own ordered steps), not the build spec's phasing. Matched by GENERAL runbook/readme
# naming, never one project's filenames.
RUNBOOK_FILES = re.compile(
    r"readme\.md$|setup[^/]*\.md$|[-_]setup\.md$|install[^/]*\.md$"
    r"|runbook|getting[-_]started|onboarding",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Detection patterns.
# --------------------------------------------------------------------------- #

# ac-id: a numbered acceptance criterion, or an AC-prefixed code identifier. `AC-id`,
# `AC-group`, `AC-N` (literal N) never match \bAC-\d so the unnumbered nouns are safe.
RE_AC_ID = re.compile(r"\bAC-\d+(?:\.\.\d+)?\b")
RE_AC_IDENT = re.compile(r"\b(?:class|def)\s+AC\d+_\w+|\bAC\d+_[A-Za-z]\w*")

# build-phase: a construction-timeline slot. `§N` is the build spec's section sigil.
RE_PHASE = re.compile(r"\bPhase[\s-]?\d+(?:\.\d+)?\b", re.IGNORECASE)
RE_PHASE_SECTION = re.compile(r"§\s?\d+|\bP1\.\d\b")

# spec-ref: a pointer to the build spec itself. STRONG signals are unambiguous build-doc
# markers. A bare spec/ticket id is split out because a product's OWN id allocator (and
# standards tokens like UTF-8 / SHA-256) share the shape, so a bare id flags only with
# build context.
RE_SPEC_STRONG = re.compile(
    r"[\w./-]+\.spec\.md\b"                                # a spec filename
    r"|\bthe build spec\b|\bbuild contract\b"              # explicit build-doc nouns
    r"|\bthe specs?\b[^.\n]{0,40}\bdrift(?:ed|s|ing)?\b"   # "the spec ... drifted"
    r"|\bLocked decisions?\b"                              # a spec's locked-decisions log
    r"|\bout of scope for\s+[A-Z][A-Z0-9]{1,5}-\d",        # "out of scope for <SPEC-ID>"
    re.IGNORECASE,
)
# A generic spec/ticket id: an uppercase prefix + digits — SPEC-12, RFC-42, ENG-456,
# ADR-7, JIRA-1234. Any scheme, not one project's.
RE_SPEC_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,5}-\d{1,6}\b")
# A bare id is a build-spec reference (not a product example or a standards token) only
# alongside spec/AC/section/research/phase context.
RE_SPEC_BUILD_CTX = re.compile(
    r"\bspecs?\b|§|\bACs?\b|\bAC-\d|research/|out of scope|\bPhase\b|\bLocked\b"
    r"|acceptance criteria|build contract|build spec",
    re.IGNORECASE,
)

# provenance: where code came from / a predecessor's lifecycle. General verbs + "from the
# <X> <kind>" phrasing — no project name hardcoded (the "<verb> from <whatever>" pattern
# catches a named predecessor on its own).
RE_PROVENANCE = re.compile(
    r"\b(?:Salvaged|Collapsed|Ported|Adapted|Extracted|Trimmed|Migrated|Lifted)\s+from\b"
    r"|\bcarried over from\b"
    r"|\bfrom the [\w-]+ (?:engine|plugin|module|service|library|component|codebase|predecessor)'?s?\b"
    r"|\b(?:its|the) predecessor\b",
    re.IGNORECASE,
)

# temporal: framing relative to the moment of building. Kept tight — bare "new" is too
# noisy ("new item", "new PR"), so only unambiguous build-increment phrasings are flagged.
RE_TEMPORAL = re.compile(
    r"\bnewly\b|\bnow (?:adds?|returns?|uses?|exposes?)\b"
    r"|\bwas (?:already|previously|formerly)\b|\bstill (?:on|uses?)\b"
    r"|\bused to\b|\bpreviously\b|\boriginally\b|\bformerly\b|\bno longer\b"
    r"|\bin the (?:old|previous|prior|former)\b",
    re.IGNORECASE,
)

# Two-phase protocol tokens: when `Phase 1/2` sits near these (or both Phase 1 AND Phase 2
# co-occur on the line) it labels a step in a documented runtime protocol — a write +
# read-back / handshake — not a build phase, so it is KEEP. General protocol words, no
# project API names.
RE_TWO_PHASE_CTX = re.compile(
    r"\btwo-phase\b|\btwo-step\b|read[ -]back|write protocol|commit protocol"
    r"|handshake|round[ -]trip",
    re.IGNORECASE,
)

# Signals that an ac-id sits inside user-facing OUTPUT (ships in a live manifest / log a
# future operator reads) rather than a source comment — higher severity.
RE_OUTPUT_CTX = re.compile(
    r"\.append\(|\.write\(|print\(|sys\.stderr|f\"|f'|\"note\"|'note'|\"reason\"|'reason'"
)


# This scanner is the *producer* of the non-judgment patternTypes — `ac-id`,
# `build-phase`, `spec-ref`, `provenance`, `temporal` (emitted below). The two
# judgment classes a model adds by reading the diff — `identifier`, `background` —
# are documented in verify-spec/SKILL.md and stop_verify_spec.py's PATTERN_TYPES.
# Keep all three sites in sync when the set changes.
class Finding:
    __slots__ = ("file", "line", "patternType", "severity", "snippet", "autostrip", "suggested")

    def __init__(self, file, line, ptype, severity, snippet, autostrip, suggested):
        self.file = file
        self.line = line
        self.patternType = ptype
        self.severity = severity
        self.snippet = snippet
        self.autostrip = autostrip
        self.suggested = suggested

    def as_dict(self):
        return {
            "file": self.file,
            "line": self.line,
            "patternType": self.patternType,
            "severity": self.severity,
            "snippet": self.snippet,
            "autostrip": self.autostrip,
            "suggested": self.suggested,
        }


def _strip_ac_token(text):
    """Mechanically remove an AC-id reference from a line, tidying the connective it
    rode in on, so the rule + rationale survive and only the linkage is gone.
    Handles the common shapes: `(AC-2)`, ` (AC-1, AC-16, AC-30)`, ` — AC-31`,
    `, AC-5`, `realizes AC-31`, ` (AC-27 / constraint #2)` -> ` (constraint #2)`."""
    s = text
    # `(AC-7)` / `[AC-25]` whole-parenthetical of only AC-ids (+ separators) -> drop it.
    s = re.sub(r"\s*[\(\[]\s*AC-\d+(?:\s*[/,&]\s*AC-\d+)*\s*[\)\]]", "", s)
    # ` (AC-27 / constraint #2)` -> ` (constraint #2)` : drop the AC, keep the rest.
    s = re.sub(r"AC-\d+(?:\.\.\d+)?\s*/\s*", "", s)
    # "realizes/per/both halves of AC-31" lead-ins -> drop verb + id.
    s = re.sub(r"\s*\b(?:realiz\w+|per|covers?|both halves of)\s+AC-\d+(?:\.\.\d+)?\b", "", s)
    # ` — AC-31` / `, AC-5` / ` AC-2` trailing or inline ids + a leading connective.
    s = re.sub(r"\s*[—,:;-]?\s*AC-\d+(?:\.\.\d+)?\b", "", s)
    # Tidy a doubled space the removals may leave (but never touch real `()` calls).
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.rstrip()


def scan_line(path, lineno, raw):
    """Return a list of Findings for one line."""
    out = []
    line = raw.rstrip("\n")
    stripped = line.strip()
    is_consumer_ac = bool(CONSUMER_AC_FILES.search(path))
    is_runbook = bool(RUNBOOK_FILES.search(path))

    # --- ac-id ------------------------------------------------------------- #
    if not is_consumer_ac:
        if RE_AC_ID.search(line) or RE_AC_IDENT.search(line):
            ident_only = RE_AC_IDENT.search(line) and not RE_AC_ID.search(line)
            high = bool(RE_OUTPUT_CTX.search(line)) and bool(RE_AC_ID.search(line))
            # A code identifier (class AC34_Foo) is a load-bearing name: flag, don't autostrip.
            if ident_only:
                out.append(Finding(path, lineno, "ac-id", "judgment", stripped, False, ""))
            else:
                suggested = _strip_ac_token(line).strip()
                out.append(Finding(
                    path, lineno, "ac-id",
                    "high" if high else "normal",
                    stripped, True,
                    suggested if suggested != stripped else "",
                ))

    # --- build-phase ------------------------------------------------------- #
    mphase = RE_PHASE.search(line)
    if mphase:
        token = mphase.group(0)
        is_phase0 = re.match(r"(?i)phase[\s-]?0\b", token)
        # Phase 1/2 is a protocol STEP (KEEP) when a protocol token is near, or when both
        # Phase 1 and Phase 2 appear on the line (two steps named together).
        both_phases = (bool(re.search(r"(?i)phase[\s-]?1\b", line))
                       and bool(re.search(r"(?i)phase[\s-]?2\b", line)))
        two_phase = ((bool(RE_TWO_PHASE_CTX.search(line)) or both_phases)
                     and re.match(r"(?i)phase[\s-]?[12]\b", token))
        if two_phase:
            pass  # KEEP — two-phase write protocol step.
        elif is_runbook and is_phase0:
            pass  # KEEP — the setup runbook's own Phase 0.x section structure.
        else:
            # Phase 0 in a non-runbook (e.g. a JSON _comment) is judgment: rephrase the
            # label to the operational fact; an ordinary build-phase token autostrips.
            out.append(Finding(
                path, lineno, "build-phase",
                "judgment" if is_phase0 else "normal",
                stripped, not is_phase0, "",
            ))
    elif RE_PHASE_SECTION.search(line):
        out.append(Finding(path, lineno, "build-phase", "normal", stripped, False, ""))

    # --- spec-ref ---------------------------------------------------------- #
    # A strong build-doc marker always flags. A bare spec/ticket id flags only with build
    # context (else it is the product's own allocator output, a KEEP).
    # A bare id flags only with build context AROUND it — strip the id tokens first so an
    # id like `SPEC-0042` can't self-satisfy the context via its own `SPEC` prefix.
    if RE_SPEC_STRONG.search(line) or (
        RE_SPEC_ID.search(line) and RE_SPEC_BUILD_CTX.search(RE_SPEC_ID.sub("", line))
    ):
        out.append(Finding(path, lineno, "spec-ref", "normal", stripped, False, ""))

    # --- provenance -------------------------------------------------------- #
    if RE_PROVENANCE.search(line):
        # The live guard assertion (a deleted predecessor must stay out of a manifest) is
        # KEEP; only its build-history justification comment is leakage. A general
        # "assert ... not in" covers any manifest, not one project's file.
        low = line.lower()
        guard = "assert" in low and ("notin" in low or "not in" in low or "not_in" in low)
        if not guard:
            out.append(Finding(path, lineno, "provenance", "judgment", stripped, False, ""))

    # --- temporal ---------------------------------------------------------- #
    if RE_TEMPORAL.search(line):
        out.append(Finding(path, lineno, "temporal", "judgment", stripped, False, ""))

    return out


def iter_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
        elif os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in sorted(files):
                    yield os.path.join(root, f)
        # silently ignore a path that is neither (e.g. a deleted file in --diff)


def is_text(path):
    base = os.path.basename(path)
    if base in EXTRA_NAMES:
        return True
    _, ext = os.path.splitext(path)
    return ext.lower() in TEXT_EXTS


def changed_files(base):
    """Files changed in <base>..HEAD (added/modified), as repo-relative paths."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", f"{base}..HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        sys.stderr.write(f"spec_linkage_scan: git diff failed: {e}\n")
        sys.exit(2)
    return [ln for ln in out.splitlines() if ln.strip()]


def scan(paths):
    findings = []
    scanned = 0
    for path in iter_files(paths):
        if not is_text(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        scanned += 1
        for i, raw in enumerate(lines, start=1):
            findings.extend(scan_line(path, i, raw))
    return findings, scanned


def main(argv):
    args = list(argv)
    fmt = "text"
    quiet = False
    diff_base = None
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            fmt = "json"
        elif a == "--quiet":
            quiet = True
        elif a == "--diff":
            i += 1
            if i >= len(args):
                sys.stderr.write("spec_linkage_scan: --diff needs a <base> argument\n")
                return 2
            diff_base = args[i]
        elif a in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return 0
        elif a.startswith("-"):
            sys.stderr.write(f"spec_linkage_scan: unknown flag {a!r}\n")
            return 2
        else:
            paths.append(a)
        i += 1

    if not diff_base and not paths:
        sys.stderr.write("spec_linkage_scan: nothing to scan (give a path or --diff <base>)\n")
        return 2
    if diff_base:
        paths = changed_files(diff_base) + paths
    if not paths:
        # A source WAS given (e.g. --diff) but nothing matched — an empty diff is a
        # clean result, not a usage error, so a caller can branch on exit code alone.
        if not quiet:
            sys.stdout.write("clean — no changed files to scan\n" if fmt == "text"
                             else '{"findings": [], "counts": {}, "scanned": 0}\n')
        return 0

    findings, scanned = scan(paths)

    counts = {}
    for f in findings:
        counts[f.patternType] = counts.get(f.patternType, 0) + 1

    if not quiet:
        if fmt == "json":
            json.dump(
                {"findings": [f.as_dict() for f in findings], "counts": counts, "scanned": scanned},
                sys.stdout, indent=2,
            )
            sys.stdout.write("\n")
        else:
            if not findings:
                sys.stdout.write(f"clean — no spec-linkage in {scanned} file(s)\n")
            else:
                by_file = {}
                for f in findings:
                    by_file.setdefault(f.file, []).append(f)
                for path in sorted(by_file):
                    sys.stdout.write(f"\n{path}\n")
                    for f in sorted(by_file[path], key=lambda x: x.line):
                        tag = f"{f.patternType}/{f.severity}"
                        sys.stdout.write(f"  {f.line:>4}  [{tag}]  {f.snippet[:100]}\n")
                        if f.suggested:
                            sys.stdout.write(f"        -> {f.suggested[:100]}\n")
                total = len(findings)
                summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                sys.stdout.write(f"\n{total} finding(s) across {len(by_file)} file(s): {summary}\n")

    return 3 if findings else 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — a detector crash must be distinct from "found"
        sys.stderr.write(f"spec_linkage_scan: unexpected error: {e}\n")
        sys.exit(1)
