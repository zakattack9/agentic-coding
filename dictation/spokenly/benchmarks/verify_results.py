#!/usr/bin/env python3
"""Verify committed ParaQwen quality, comparison, and performance evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
SPOKENLY = HERE.parent
CORPUS = HERE / "backtracking-corpus-v1.json"
SNIPPETS = HERE / "snippets.benchmark.json"
PROMPT = SPOKENLY / "prompts" / "qwen-prompt.md"
PRE = SPOKENLY / "scripts" / "pre_ai.py"
POST = SPOKENLY / "scripts" / "post_ai.py"
REPAIR = SPOKENLY / "scripts" / "repair_protocol.py"
BENCHMARK = HERE / "run_backtracking_benchmark.py"
BASELINE = HERE / "pre-change-baseline-v1.json"
LIVE = HERE / "results" / "backtracking-live-summary-v1.json"
COMPARISON = HERE / "results" / "backtracking-comparison-v1.json"
PERFORMANCE = HERE / "results" / "processor-performance-v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _benchmark_module():
    specification = importlib.util.spec_from_file_location(
        "paraqwen_evidence_benchmark", BENCHMARK
    )
    module = importlib.util.module_from_spec(specification)
    assert specification.loader is not None
    specification.loader.exec_module(module)
    return module


def _load(path: Path, errors: list[str]) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"cannot read {path.name}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} is not a JSON object")
        return {}
    return value


def _summarize(
    outcomes: list[dict[str, object]],
) -> tuple[float, float, int, dict[str, float]]:
    counts = Counter((item["polarity"], item["passed"]) for item in outcomes)
    positive_total = sum(item["polarity"] == "positive" for item in outcomes)
    negative_total = sum(item["polarity"] == "negative" for item in outcomes)
    positive_rate = (
        100 * counts[("positive", True)] / positive_total
        if positive_total
        else 100.0
    )
    negative_rate = (
        100 * counts[("negative", True)] / negative_total
        if negative_total
        else 100.0
    )
    safety_count = sum(
        any(str(failure).startswith("safety:") for failure in item["failures"])
        for item in outcomes
    )
    categories: defaultdict[str, list[bool]] = defaultdict(list)
    for item in outcomes:
        categories[str(item["category"])].append(bool(item["passed"]))
    category_rates = {
        category: 100 * sum(values) / len(values)
        for category, values in sorted(categories.items())
    }
    return positive_rate, negative_rate, safety_count, category_rates


def _verify_outcomes(
    *,
    label: str,
    report: dict[str, object],
    cases: dict[str, dict[str, object]],
    runs: int,
    require_timing: bool,
    benchmark,
    errors: list[str],
) -> tuple[float, float, int, dict[str, float]] | None:
    outcomes = report.get("outcomes")
    expected_count = len(cases) * runs
    if not isinstance(outcomes, list) or len(outcomes) != expected_count:
        errors.append(
            f"{label} does not contain {expected_count} auditable outcomes"
        )
        return None

    coverage: Counter[tuple[int, str]] = Counter()
    verified: list[dict[str, object]] = []
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            errors.append(f"{label} outcome {index} is not an object")
            continue
        case_id = outcome.get("id")
        run = outcome.get("run")
        if not isinstance(case_id, str) or case_id not in cases:
            errors.append(f"{label} outcome {index} has an unknown case")
            continue
        if not isinstance(run, int) or not 1 <= run <= runs:
            errors.append(f"{label} outcome {case_id} has an invalid run")
            continue
        coverage[(run, case_id)] += 1
        case = cases[case_id]
        if outcome.get("polarity") != case["polarity"]:
            errors.append(f"{label} outcome {case_id} has stale polarity")
        if outcome.get("category") != case["category"]:
            errors.append(f"{label} outcome {case_id} has stale category")
        output = outcome.get("output")
        if not isinstance(output, str):
            errors.append(f"{label} outcome {case_id} has no output text")
            continue
        passed, failures = benchmark.predicates(case, output)
        timing = outcome.get("timing")
        if require_timing and (
            not isinstance(timing, dict)
            or set(("pre_ms", "model_ms", "post_ms", "stderr_clean"))
            - set(timing)
            or not all(
                isinstance(timing[key], (int, float))
                and not isinstance(timing[key], bool)
                and timing[key] >= 0
                for key in ("pre_ms", "model_ms", "post_ms")
            )
            or timing.get("stderr_clean") is not True
        ):
            errors.append(f"{label} outcome {case_id}:run-{run} has invalid timing")
        if isinstance(timing, dict) and timing.get("stderr_clean") is False:
            failures.append("safety: processor wrote unexpected stderr")
            passed = False
        if outcome.get("passed") != passed or outcome.get("failures") != failures:
            errors.append(f"{label} outcome {case_id}:run-{run} was not reproducible")
        verified.append(
            {
                "polarity": case["polarity"],
                "category": case["category"],
                "passed": passed,
                "failures": failures,
            }
        )

    expected_coverage = {
        (run, case_id) for run in range(1, runs + 1) for case_id in cases
    }
    if set(coverage) != expected_coverage or any(
        count != 1 for count in coverage.values()
    ):
        errors.append(f"{label} does not cover every case exactly once per run")
    if len(verified) != expected_count:
        return None
    return _summarize(verified)


def _same_number(left: object, right: float) -> bool:
    return isinstance(left, (int, float)) and abs(float(left) - right) <= 1e-9


def verify() -> list[str]:
    errors: list[str] = []
    benchmark = _benchmark_module()
    try:
        corpus = benchmark.load_corpus(CORPUS)
    except (OSError, ValueError) as exc:
        return [f"corpus validation failed: {exc}"]
    cases = {case["id"]: case for case in corpus["cases"]}

    baseline = _load(BASELINE, errors)
    live = _load(LIVE, errors)
    comparison = _load(COMPARISON, errors)
    performance = _load(PERFORMANCE, errors)
    if errors:
        return errors

    current_digests = {
        "prompt_digest": digest(PROMPT),
        "corpus_digest": digest(CORPUS),
        "snippets_digest": digest(SNIPPETS),
        "pre_ai_digest": digest(PRE),
        "post_ai_digest": digest(POST),
        "repair_protocol_digest": digest(REPAIR),
        "benchmark_digest": digest(BENCHMARK),
    }
    for key, expected in current_digests.items():
        if live.get(key) != expected:
            errors.append(f"live report has stale {key}")
    if live.get("reasoning") != "disabled (think=false)" or live.get(
        "temperature"
    ) != 0.0:
        errors.append("live report did not disable reasoning and creativity")
    if live.get("runs") != 3:
        errors.append("live report does not contain exactly three runs")
    if live.get("case_count") != len(cases) or live.get("outcome_count") != 3 * len(
        cases
    ):
        errors.append("live report counts do not cover the complete corpus")
    if live.get("model_digest") in (None, "", "unavailable"):
        errors.append("live report does not pin the model digest")
    if not isinstance(live.get("ollama_version"), str) or not live[
        "ollama_version"
    ]:
        errors.append("live report does not pin the Ollama version")

    live_summary = _verify_outcomes(
        label="live report",
        report=live,
        cases=cases,
        runs=3,
        require_timing=True,
        benchmark=benchmark,
        errors=errors,
    )
    if live_summary is not None:
        positive, negative, safety, categories = live_summary
        if not _same_number(live.get("positive_rate"), positive):
            errors.append("live positive rate is not reproducible")
        if not _same_number(live.get("negative_preservation_rate"), negative):
            errors.append("live negative rate is not reproducible")
        if live.get("safety_failures") != safety:
            errors.append("live safety count is not reproducible")
        if live.get("category_rates") != categories:
            errors.append("live category rates are not reproducible")
        expected_gates = {
            "positive_95": positive >= 95,
            "negative_99": negative >= 99,
            "zero_safety": safety == 0,
            "three_runs": True,
            "complete_corpus": True,
        }
        if live.get("gates") != expected_gates or not all(expected_gates.values()):
            errors.append("live quality gates are incomplete or failing")

    baseline_live = baseline.get("live_model_accuracy")
    baseline_summary = None
    if not isinstance(baseline_live, dict):
        errors.append("baseline has no live-model evidence")
    else:
        if baseline_live.get("runs") != 1:
            errors.append("baseline must contain one frozen complete run")
        if baseline_live.get("case_count") != len(cases) or baseline_live.get(
            "outcome_count"
        ) != len(cases):
            errors.append("baseline counts do not cover the complete corpus")
        for field in ("model", "model_digest", "reasoning", "temperature"):
            if baseline_live.get(field) != live.get(field):
                errors.append(f"baseline and live report use different {field}")
        evidence_digests = baseline_live.get("evidence_input_digests")
        if not isinstance(evidence_digests, dict) or not evidence_digests or not all(
            isinstance(value, str) and len(value) == 64
            for value in evidence_digests.values()
        ):
            errors.append("baseline does not pin its raw evidence inputs")
        baseline_summary = _verify_outcomes(
            label="baseline",
            report=baseline_live,
            cases=cases,
            runs=1,
            require_timing=False,
            benchmark=benchmark,
            errors=errors,
        )
        if baseline_summary is not None:
            positive, negative, safety, categories = baseline_summary
            for field, expected in (
                ("positive_rate", positive),
                ("negative_preservation_rate", negative),
            ):
                if not _same_number(baseline_live.get(field), expected):
                    errors.append(f"baseline {field} is not reproducible")
            if baseline_live.get("safety_failures") != safety:
                errors.append("baseline safety count is not reproducible")
            if baseline_live.get("category_rates") != categories:
                errors.append("baseline category rates are not reproducible")

    if live_summary is not None and baseline_summary is not None:
        live_positive, live_negative, live_safety, live_categories = live_summary
        base_positive, base_negative, base_safety, base_categories = baseline_summary
        improvement = live_positive - base_positive
        negative_improvement = live_negative - base_negative
        regressions = [
            base_categories[category] - rate
            for category, rate in live_categories.items()
        ]
        worst_regression = max(0.0, max(regressions))
        improved = {
            category: live_categories[category] - base_categories[category]
            for category in live_categories
            if live_categories[category] > base_categories[category]
        }
        expected_comparison = {
            "baseline_positive_rate": base_positive,
            "implementation_positive_rate": live_positive,
            "positive_improvement_points": improvement,
            "baseline_negative_preservation_rate": base_negative,
            "implementation_negative_preservation_rate": live_negative,
            "negative_improvement_points": negative_improvement,
            "baseline_safety_failures": base_safety,
            "implementation_safety_failures": live_safety,
            "worst_category_regression_points": worst_regression,
            "improved_categories": improved,
        }
        for field, expected in expected_comparison.items():
            actual = comparison.get(field)
            if isinstance(expected, float):
                matches = _same_number(actual, expected)
            else:
                matches = actual == expected
            if not matches:
                errors.append(f"comparison has stale {field}")
        for field, expected in (
            ("schema_version", 1),
            ("corpus_version", corpus["corpus_version"]),
            ("baseline_commit", baseline.get("branch_commit")),
            ("baseline_runs", 1),
            ("implementation_runs", 3),
        ):
            if comparison.get(field) != expected:
                errors.append(f"comparison has stale {field}")
        expected_gates = {
            "positive_improvement_at_least_five_points": improvement >= 5,
            "no_category_regression_over_two_points": worst_regression <= 2,
            "hard_safety_not_regressed": live_safety <= base_safety,
        }
        if comparison.get("gates") != expected_gates or not all(
            expected_gates.values()
        ):
            errors.append("historical comparison gate failed")

    performance_digests = {
        "pre_ai_digest": current_digests["pre_ai_digest"],
        "post_ai_digest": current_digests["post_ai_digest"],
        "repair_protocol_digest": current_digests["repair_protocol_digest"],
        "baseline_digest": digest(BASELINE),
        "benchmark_digest": digest(HERE / "benchmark_processors.py"),
    }
    for key, expected in performance_digests.items():
        if performance.get(key) != expected:
            errors.append(f"performance report has stale {key}")
    timing = baseline.get("processor_timing_ms")
    results = performance.get("results")
    required_cases = {"short", "thirty_sentence", "two_thousand_word"}
    if not isinstance(timing, dict) or not isinstance(results, dict) or set(
        results
    ) != required_cases:
        errors.append("performance report has incomplete representative cases")
    else:
        try:
            worst_p95 = max(float(results[name]["p95_ms"]) for name in required_cases)
            max_ratio = max(
                float(results[name]["p95_ms"]) / float(timing[name]["p95"])
                for name in required_cases
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            errors.append("performance report contains invalid measurements")
        else:
            if not _same_number(performance.get("worst_p95_ms"), worst_p95):
                errors.append("performance worst p95 is not reproducible")
            if not _same_number(performance.get("max_baseline_ratio"), max_ratio):
                errors.append("performance baseline ratio is not reproducible")
            expected_gates = {
                "p95_under_150_ms": worst_p95 < 150,
                "regression_under_25_percent": max_ratio <= 1.25,
            }
            if performance.get("gates") != expected_gates or not all(
                expected_gates.values()
            ):
                errors.append("processor latency exceeds its contract")
    if not isinstance(performance.get("iterations"), int) or performance[
        "iterations"
    ] < 40:
        errors.append("performance report has fewer than 40 iterations")
    if performance.get("representative_max_words") != 2000:
        errors.append("performance report does not cover 2,000 words")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        "Committed ParaQwen benchmark evidence is auditable, internally "
        "consistent, and all gates pass."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
