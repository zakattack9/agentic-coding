#!/usr/bin/env python3
"""Pin auditable ParaQwen benchmark reports as repository evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import tempfile

import run_backtracking_benchmark as benchmark


HERE = Path(__file__).resolve().parent
BASELINE = HERE / "pre-change-baseline-v1.json"
RESULTS = HERE / "results"
LIVE_TARGET = RESULTS / "backtracking-live-summary-v1.json"
COMPARISON_TARGET = RESULTS / "backtracking-comparison-v1.json"
PERFORMANCE_TARGET = RESULTS / "processor-performance-v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded_json(value: dict[str, object]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(encoded_json(value))
        temporary = Path(handle.name)
    temporary.chmod(0o644)
    temporary.replace(path)


def normalized_outcome(
    outcome: dict[str, object], case: dict[str, object]
) -> dict[str, object]:
    output = outcome.get("output")
    if not isinstance(output, str):
        raise ValueError(f"outcome {case['id']} has no output")
    passed, failures = benchmark.predicates(case, output)
    timing = outcome.get("timing")
    compact_timing = None
    if isinstance(timing, dict):
        compact_timing = {
            key: timing[key]
            for key in ("pre_ms", "model_ms", "post_ms", "stderr_clean")
            if key in timing
        }
        if timing.get("stderr_clean") is False:
            failures.append("safety: processor wrote unexpected stderr")
            passed = False
    result = {
        "run": outcome.get("run"),
        "id": case["id"],
        "polarity": case["polarity"],
        "category": case["category"],
        "passed": passed,
        "failures": failures,
        "output": output,
    }
    if compact_timing:
        result["timing"] = compact_timing
    return result


def summary(outcomes: list[dict[str, object]]) -> dict[str, object]:
    counts = Counter((item["polarity"], item["passed"]) for item in outcomes)
    positive_total = sum(item["polarity"] == "positive" for item in outcomes)
    negative_total = sum(item["polarity"] == "negative" for item in outcomes)
    positive_rate = 100 * counts[("positive", True)] / positive_total
    negative_rate = 100 * counts[("negative", True)] / negative_total
    safety = [
        item
        for item in outcomes
        if any(str(value).startswith("safety:") for value in item["failures"])
    ]
    categories: defaultdict[str, list[bool]] = defaultdict(list)
    for item in outcomes:
        categories[str(item["category"])].append(bool(item["passed"]))
    return {
        "positive_rate": positive_rate,
        "negative_preservation_rate": negative_rate,
        "safety_failures": len(safety),
        "safety_failure_ids": [
            f"{item['id']}:run-{item['run']}" for item in safety
        ],
        "category_rates": {
            key: 100 * sum(values) / len(values)
            for key, values in sorted(categories.items())
        },
    }


def exact_coverage(
    outcomes: list[dict[str, object]], case_ids: set[str], runs: int
) -> bool:
    actual = Counter((item.get("run"), item.get("id")) for item in outcomes)
    expected = {
        (run, case_id) for run in range(1, runs + 1) for case_id in case_ids
    }
    return set(actual) == expected and all(count == 1 for count in actual.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-report", type=Path, action="append", required=True
    )
    parser.add_argument("--live-report", type=Path)
    parser.add_argument("--performance-report", type=Path)
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="pin the auditable frozen baseline before measuring performance",
    )
    args = parser.parse_args()

    corpus = benchmark.load_corpus()
    cases = {case["id"]: case for case in corpus["cases"]}
    case_ids = set(cases)

    baseline_outcomes = []
    baseline_identity = None
    for path in args.baseline_report:
        source = json.loads(path.read_text(encoding="utf-8"))
        identity = {
            key: source.get(key)
            for key in (
                "model",
                "model_digest",
                "ollama_version",
                "prompt_digest",
                "reasoning",
                "temperature",
                "machine",
                "python",
            )
        }
        if baseline_identity is None:
            baseline_identity = identity
        elif identity != baseline_identity:
            raise ValueError("baseline inputs use different model/runtime identities")
        for outcome in source.get("outcomes", []):
            case_id = outcome.get("id")
            if case_id not in cases:
                raise ValueError(f"unknown baseline case: {case_id}")
            baseline_outcomes.append(normalized_outcome(outcome, cases[case_id]))
    if not exact_coverage(baseline_outcomes, case_ids, 1):
        raise ValueError("baseline inputs do not cover every corpus case once")
    baseline_summary = summary(baseline_outcomes)

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline_live = baseline["live_model_accuracy"]
    baseline_live.update(baseline_summary)
    baseline_live.update(baseline_identity or {})
    baseline_live["case_count"] = len(cases)
    baseline_live["outcome_count"] = len(baseline_outcomes)
    baseline_live["outcomes"] = baseline_outcomes
    baseline_live["evidence_input_digests"] = {
        path.name: digest(path) for path in args.baseline_report
    }

    if args.baseline_only:
        write_json(BASELINE, baseline)
        print("Pinned auditable frozen baseline evidence.")
        return 0
    if args.live_report is None or args.performance_report is None:
        parser.error(
            "--live-report and --performance-report are required unless "
            "--baseline-only is used"
        )

    live = json.loads(args.live_report.read_text(encoding="utf-8"))
    if live.get("runs") != 3:
        raise ValueError("release report must contain exactly three runs")
    expected_live_digests = {
        "prompt_digest": digest(benchmark.PROMPT),
        "corpus_digest": digest(benchmark.CORPUS),
        "snippets_digest": digest(benchmark.SNIPPETS),
        "pre_ai_digest": digest(benchmark.SPOKENLY / "scripts" / "pre_ai.py"),
        "post_ai_digest": digest(benchmark.SPOKENLY / "scripts" / "post_ai.py"),
        "repair_protocol_digest": digest(
            benchmark.SPOKENLY / "scripts" / "repair_protocol.py"
        ),
        "benchmark_digest": digest(Path(benchmark.__file__)),
    }
    for key, expected in expected_live_digests.items():
        if live.get(key) != expected:
            raise ValueError(f"live report has stale {key}")
    if live.get("reasoning") != "disabled (think=false)" or live.get(
        "temperature"
    ) != 0.0:
        raise ValueError("live report did not disable reasoning and creativity")
    live_outcomes = []
    for outcome in live.get("outcomes", []):
        case_id = outcome.get("id")
        if case_id not in cases:
            raise ValueError(f"unknown live case: {case_id}")
        live_outcomes.append(normalized_outcome(outcome, cases[case_id]))
    if not exact_coverage(live_outcomes, case_ids, 3):
        raise ValueError("live input does not cover every corpus case three times")
    live.update(summary(live_outcomes))
    live["outcomes"] = live_outcomes
    live["case_count"] = len(cases)
    live["outcome_count"] = len(live_outcomes)
    live["gates"] = {
        "positive_95": live["positive_rate"] >= 95,
        "negative_99": live["negative_preservation_rate"] >= 99,
        "zero_safety": live["safety_failures"] == 0,
        "three_runs": True,
        "complete_corpus": True,
    }
    if not all(live["gates"].values()):
        raise ValueError("live report does not satisfy every release gate")

    base_categories = baseline_summary["category_rates"]
    live_categories = live["category_rates"]
    improvement = live["positive_rate"] - baseline_summary["positive_rate"]
    worst_regression = max(
        0.0,
        max(
            base_categories[category] - rate
            for category, rate in live_categories.items()
        ),
    )
    comparison = {
        "schema_version": 1,
        "corpus_version": corpus["corpus_version"],
        "baseline_commit": baseline["branch_commit"],
        "baseline_runs": 1,
        "implementation_runs": 3,
        "baseline_positive_rate": baseline_summary["positive_rate"],
        "implementation_positive_rate": live["positive_rate"],
        "positive_improvement_points": improvement,
        "baseline_negative_preservation_rate": baseline_summary[
            "negative_preservation_rate"
        ],
        "implementation_negative_preservation_rate": live[
            "negative_preservation_rate"
        ],
        "negative_improvement_points": live["negative_preservation_rate"]
        - baseline_summary["negative_preservation_rate"],
        "baseline_safety_failures": baseline_summary["safety_failures"],
        "implementation_safety_failures": live["safety_failures"],
        "worst_category_regression_points": worst_regression,
        "improved_categories": {
            category: live_categories[category] - base_categories[category]
            for category in live_categories
            if live_categories[category] > base_categories[category]
        },
        "gates": {
            "positive_improvement_at_least_five_points": improvement >= 5,
            "no_category_regression_over_two_points": worst_regression <= 2,
            "hard_safety_not_regressed": live["safety_failures"]
            <= baseline_summary["safety_failures"],
        },
    }
    if not all(comparison["gates"].values()):
        raise ValueError("baseline comparison does not satisfy every release gate")
    performance = json.loads(args.performance_report.read_text(encoding="utf-8"))
    if not all(performance.get("gates", {}).values()):
        raise ValueError("performance report does not satisfy every release gate")
    for key in ("pre_ai_digest", "post_ai_digest", "repair_protocol_digest"):
        if performance.get(key) != expected_live_digests[key]:
            raise ValueError(f"performance report has stale {key}")
    if performance.get("benchmark_digest") != digest(
        HERE / "benchmark_processors.py"
    ):
        raise ValueError("performance report has stale benchmark_digest")
    expected_baseline_digest = hashlib.sha256(
        encoded_json(baseline).encode("utf-8")
    ).hexdigest()
    if performance.get("baseline_digest") != expected_baseline_digest:
        raise ValueError(
            "performance report was not measured against the pinned baseline"
        )

    write_json(BASELINE, baseline)
    write_json(LIVE_TARGET, live)
    write_json(COMPARISON_TARGET, comparison)
    write_json(PERFORMANCE_TARGET, performance)
    print("Pinned auditable live, baseline, comparison, and performance evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
