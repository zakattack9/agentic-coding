#!/usr/bin/env python3
"""Unit tests for spec_consistency.py — the deterministic AC-integrity check.

check() returns (blocking, advisory): blocking = conflict markers + duplicate AC numbers
(a caller blocks on these); advisory = dangling AC-N references (reported, never blocking).
(None, None) means "no AC section / nothing to check"."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import spec_consistency as sc  # noqa: E402


def _spec(acs="| AC | Criterion |\n| --- | --- |\n| 1 | a |\n| 2 | b |\n", body="", extra=""):
    return f"# Feature Spec\n\n## Acceptance Criteria\n\n{acs}\n{body}\n## Boundaries\n\n{extra}\n"


def test_clean_spec_passes():
    assert sc.check(_spec(body="The rule for AC-1 and AC-2 holds.")) == ([], [])


def test_duplicate_ac_number_is_blocking():
    spec = _spec(acs="| AC | Criterion |\n| --- | --- |\n| 1 | a |\n| 2 | b |\n| 2 | c |\n")
    blocking, advisory = sc.check(spec)
    assert any("duplicate" in p and "AC-2" in p for p in blocking)
    assert advisory == []


def test_dangling_reference_is_advisory_not_blocking():
    # AC-9 cited in the body but never defined — advisory, never blocks
    blocking, advisory = sc.check(_spec(body="See AC-9 for the edge case."))
    assert any("dangling" in p and "AC-9" in p for p in advisory)
    assert blocking == []


def test_conflict_marker_is_blocking():
    blocking, _ = sc.check("# S\n<<<<<<< HEAD\n## Acceptance Criteria\n| AC | Criterion |\n| --- | --- |\n| 1 | a |\n")
    assert any("conflict marker" in p for p in blocking)


def test_equals_underline_is_not_a_conflict_marker():
    # a ======= setext underline must NOT be read as a conflict marker
    assert sc.check("# S\nTitle\n=======\n## Acceptance Criteria\n| AC | Criterion |\n| --- | --- |\n| 1 | a |\n") == ([], [])


def test_ac_dash_id_format_supported():
    spec = _spec(acs="| AC | Criterion |\n| --- | --- |\n| AC-1 | a |\n| AC-2 | b |\n", body="AC-1 holds.")
    assert sc.check(spec) == ([], [])


def test_grouped_tables_global_uniqueness():
    acs = ("### 1. Alpha\n\n| AC | Criterion |\n| --- | --- |\n| 1 | a |\n\n"
           "### 2. Beta\n\n| AC | Criterion |\n| --- | --- |\n| 1 | dup across groups |\n")
    blocking, _ = sc.check(_spec(acs=acs))
    assert any("duplicate" in p and "AC-1" in p for p in blocking)


def test_numeric_table_outside_ac_section_is_not_a_definition():
    # a numeric table AFTER the AC section must not count as an AC definition,
    # so a reference to that number is still dangling (advisory)
    body = "## Data\n\n| Port | Use |\n| --- | --- |\n| 5 | db |\n\nSee AC-5.\n"
    _, advisory = sc.check(_spec(body=body))
    assert any("dangling" in p and "AC-5" in p for p in advisory)


def test_no_ac_section_returns_none():
    assert sc.check("# Spec\n\nJust prose, no acceptance criteria table.\n") == (None, None)


# ---- false-positive regression guards (vectors a / b / c / d) ----------------

def test_a_non_ac_numeric_table_in_region_not_counted():
    # a legend / priority matrix INSIDE the AC region with a numeric first column
    # must not be read as duplicate AC definitions
    acs = ("| AC | Criterion |\n| --- | --- |\n| 1 | a |\n| 2 | b |\n\n"
           "### Priorities\n\n| Rank | Item |\n| --- | --- |\n| 1 | high |\n| 2 | low |\n")
    assert sc.check(_spec(acs=acs)) == ([], [])


def test_b_conflict_marker_inside_code_fence_is_ignored():
    # a spec documenting conflict handling shows <<<<<<< inside a fence — not a real marker
    body = "## Notes\n\n```\n<<<<<<< HEAD\nfoo\n=======\nbar\n>>>>>>> branch\n```\n"
    assert sc.check(_spec(body=body)) == ([], [])


def test_b_real_conflict_marker_outside_fence_still_blocks():
    body = "## Notes\n\n<<<<<<< HEAD\nraw leftover\n"
    blocking, _ = sc.check(_spec(body=body))
    assert any("conflict marker" in p for p in blocking)


def test_c_cross_spec_prose_ref_is_advisory_only():
    # "supersedes AC-7 from the legacy spec" — out-of-range ref to a sibling spec
    blocking, advisory = sc.check(_spec(body="This supersedes AC-7 from the legacy auth spec."))
    assert blocking == []
    assert any("AC-7" in p for p in advisory)


def test_d_ac_ref_inside_code_fence_is_ignored():
    # an AC-42 token inside a code / fixture example must not be scanned as a reference
    body = "## Example\n\n```\nassert finding.id == 'AC-42'\n```\n"
    assert sc.check(_spec(body=body)) == ([], [])


# ---- main() exit codes -------------------------------------------------------

def _run(text):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    return sc.main([path])


def test_main_exit_0_clean():
    assert _run(_spec(body="AC-1, AC-2 ok.")) == 0


def test_main_exit_0_on_dangling_advisory():
    # dangling is advisory → printed to stderr, exit 0 (does not block)
    assert _run(_spec(body="AC-42 missing.")) == 0


def test_main_exit_2_on_duplicate():
    spec = _spec(acs="| AC | Criterion |\n| --- | --- |\n| 1 | a |\n| 1 | dup |\n")
    assert _run(spec) == 2


def test_main_exit_2_on_conflict_marker():
    assert _run("<<<<<<< HEAD\n## Acceptance Criteria\n| AC | Criterion |\n| --- | --- |\n| 1 | a |\n") == 2


def test_main_exit_3_no_ac_section():
    assert _run("# Spec\n\nno table\n") == 3


def test_main_exit_3_bad_usage():
    assert sc.main([]) == 3


def _main():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in funcs:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(funcs) - failures}/{len(funcs)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
