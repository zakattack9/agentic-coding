#!/usr/bin/env python3
"""Unit tests for the write-requirements contract added to validate_return.py.

The pre-existing contracts (grounder/judge) are exercised by the skills in practice;
these cover the new advisory requirements-review shape end to end.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_return as vr  # noqa: E402


def test_write_requirements_registered():
    assert "write-requirements" in vr.VALIDATORS

def test_valid_empty_arrays_pass():
    data = {"missingACs": [], "unaskedQuestions": [], "scopeRisks": []}
    assert vr.validate("write-requirements", data) == []

def test_valid_populated_passes():
    data = {
        "missingACs": ["idempotency on retry is unstated"],
        "unaskedQuestions": ["soft-delete or hard-delete?"],
        "scopeRisks": ["the draft also touches billing, beyond the goal"],
    }
    assert vr.validate("write-requirements", data) == []

def test_missing_key_fails():
    problems = vr.validate("write-requirements", {"missingACs": [], "unaskedQuestions": []})
    assert any("scopeRisks" in p for p in problems)

def test_non_array_fails():
    problems = vr.validate("write-requirements", {
        "missingACs": "oops", "unaskedQuestions": [], "scopeRisks": [],
    })
    assert any("missingACs" in p for p in problems)

def test_non_string_item_fails():
    problems = vr.validate("write-requirements", {
        "missingACs": [123], "unaskedQuestions": [], "scopeRisks": [],
    })
    assert any("missingACs[0]" in p for p in problems)

def test_not_an_object_fails():
    assert vr.validate("write-requirements", ["a", "b"]) != []


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
