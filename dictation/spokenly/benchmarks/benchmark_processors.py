#!/usr/bin/env python3
"""Measure combined deterministic Pre-AI/Post-AI processor latency."""

from __future__ import annotations

import argparse
import json
import hashlib
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
SPOKENLY = HERE.parent
PRE = SPOKENLY / "scripts" / "pre_ai.py"
POST = SPOKENLY / "scripts" / "post_ai.py"
SNIPPETS = HERE / "snippets.benchmark.json"
BASELINE = HERE / "pre-change-baseline-v1.json"


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def processor_input_digests() -> dict[str, str]:
    return {
        "pre_ai_digest": file_digest(PRE),
        "post_ai_digest": file_digest(POST),
        "repair_protocol_digest": file_digest(
            SPOKENLY / "scripts" / "repair_protocol.py"
        ),
        "baseline_digest": file_digest(BASELINE),
        "benchmark_digest": file_digest(Path(__file__)),
    }


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[
        max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    ]


def run_case(text: str, iterations: int) -> dict[str, float]:
    samples = []
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "state.json"
        slash_state = Path(directory) / "slash.json"
        environment = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "SPOKENLY_ITERM_FILE_REFERENCES": "0",
            "SPOKENLY_SOURCE_RECOVERY_STATE": str(state),
            "SPOKENLY_SLASH_SNIPPET_STATE": str(slash_state),
            "PARAQWEN_DIAGNOSTICS": "0",
        }
        for _ in range(iterations):
            started = time.perf_counter()
            pre = subprocess.run([sys.executable, str(PRE), "--snippets", str(SNIPPETS)], input=text, text=True, capture_output=True, env=environment, check=True)
            subprocess.run([sys.executable, str(POST), "--snippets", str(SNIPPETS)], input=pre.stdout, text=True, capture_output=True, env=environment, check=True)
            samples.append((time.perf_counter() - started) * 1000)
    return {"median_ms": statistics.median(samples), "p95_ms": percentile(samples, 0.95)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.iterations < 2:
        parser.error("--iterations must be at least 2")
    input_digests = processor_input_digests()
    sentence = "Tomorrow send the onboarding guide to sales. I mean support."
    neutral = "Review the implementation carefully and preserve every verified requirement before producing the final report."
    long_words = (" ".join([neutral] * 70) + " " + sentence + " " + " ".join([neutral] * 300)).split()
    long_text = " ".join(long_words[:2000])
    cases = {
        "short": sentence,
        "thirty_sentence": " ".join([neutral] * 29 + [sentence]),
        "two_thousand_word": long_text,
    }
    results = {name: run_case(text, args.iterations) for name, text in cases.items()}
    if processor_input_digests() != input_digests:
        raise RuntimeError("processor benchmark inputs changed during the run")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["processor_timing_ms"]
    worst_p95 = max(item["p95_ms"] for item in results.values())
    regression = max(results[name]["p95_ms"] / baseline[name]["p95"] for name in results)
    report = {
        "schema_version": 1,
        "created_at": time.time(),
        "iterations": args.iterations,
        "representative_max_words": 2000,
        "machine": platform.platform(),
        "python": platform.python_version(),
        **input_digests,
        "results": results,
        "worst_p95_ms": worst_p95,
        "max_baseline_ratio": regression,
        "gates": {
            "p95_under_150_ms": worst_p95 < 150,
            "regression_under_25_percent": regression <= 1.25,
        },
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2))
    return 0 if all(report["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
