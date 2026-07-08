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


# ---- judge-refine severity (optional field, enum-checked when present) --------------

def _refine_verdict(findings):
    return {
        "perCriterion": [
            {"criterion": c, "verdict": "PASS", "reason": "ok"} for c in vr.REFINE_CRITERIA
        ],
        "findings": findings,
        "overall": "PASS",
    }

def test_judge_refine_accepts_valid_severity():
    data = _refine_verdict([{"type": "Gap", "severity": "CRITICAL", "acId": "AC-1", "detail": "x"}])
    assert vr.validate("judge-refine", data) == []

def test_judge_refine_accepts_missing_severity():
    # severity is optional — a degraded reply that omits it still validates (treated as CRITICAL)
    data = _refine_verdict([{"type": "Gap", "acId": "AC-1", "detail": "x"}])
    assert vr.validate("judge-refine", data) == []

def test_judge_refine_rejects_bad_severity():
    data = _refine_verdict([{"type": "Gap", "severity": "BLOCKER", "acId": "AC-1", "detail": "x"}])
    assert any("severity" in p for p in vr.validate("judge-refine", data))

def test_judge_refine_accepts_missing_type():
    # type is optional at validation time (same degraded-reply leniency as severity)
    data = _refine_verdict([{"severity": "CRITICAL", "acId": "AC-1", "detail": "x"}])
    assert vr.validate("judge-refine", data) == []

def test_judge_refine_rejects_bad_type():
    # a mis-emitted rubric label (not one of Gap/Ambiguity/Conflict) is caught, not passed through
    data = _refine_verdict([{"type": "Debt-perpetuation", "severity": "CRITICAL", "acId": "AC-1", "detail": "x"}])
    assert any("type" in p for p in vr.validate("judge-refine", data))


# ---- loop-review (loop-spec cross-model reviewer) -----------------------------------

def test_loop_review_registered():
    assert "loop-review" in vr.VALIDATORS

def test_loop_review_empty_findings_pass():
    # nothing material this round is a valid, expected result
    assert vr.validate("loop-review", {"findings": []}) == []

def test_loop_review_valid_populated_passes():
    data = {"findings": [
        {"severity": "CRITICAL", "location": "AC-7", "scenario": "builds wrong thing",
         "evidence": "src/x.py:12", "edit": "add an AC pinning the tenant scope"},
    ]}
    assert vr.validate("loop-review", data) == []

def test_loop_review_missing_findings_fails():
    assert any("findings" in p for p in vr.validate("loop-review", {}))

def test_loop_review_findings_not_array_fails():
    assert any("findings" in p for p in vr.validate("loop-review", {"findings": "oops"}))

def test_loop_review_accepts_missing_severity():
    # severity is optional at validation time (degraded-reply leniency, like judge-refine)
    data = {"findings": [{"location": "AC-1", "scenario": "x", "evidence": "a:1", "edit": "y"}]}
    assert vr.validate("loop-review", data) == []

def test_loop_review_rejects_bad_severity():
    data = {"findings": [{"severity": "BLOCKER", "scenario": "x"}]}
    assert any("severity" in p for p in vr.validate("loop-review", data))

def test_loop_review_non_string_field_fails():
    data = {"findings": [{"severity": "WARNING", "evidence": 123}]}
    assert any("findings[0].evidence" in p for p in vr.validate("loop-review", data))

def test_loop_review_not_an_object_fails():
    assert vr.validate("loop-review", ["a", "b"]) != []


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
