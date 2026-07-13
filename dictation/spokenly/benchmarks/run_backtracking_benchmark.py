#!/usr/bin/env python3
"""Validate the corpus or run the explicit three-pass local-Qwen benchmark."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
from urllib import request


HERE = Path(__file__).resolve().parent
SPOKENLY = HERE.parent
SCRIPTS = SPOKENLY / "scripts"
CORPUS = HERE / "backtracking-corpus-v1.json"
SNIPPETS = HERE / "snippets.benchmark.json"
PROMPT = SPOKENLY / "prompts" / "qwen-prompt.md"
sys.path.insert(0, str(SCRIPTS))

import pre_ai  # noqa: E402
import repair_protocol  # noqa: E402


REQUIRED_FIELDS = {
    "id", "polarity", "category", "source_kind", "raw_transcript",
    "expected_repair_type", "required_retained", "required_removed",
    "protected_atoms", "expansion_occurrences", "allowed_formatting_variants",
    "forbidden_additions", "expected_pre", "expected_fallback", "reviewed",
    "provenance",
}
POLARITIES = {"positive", "negative"}
REPAIR_TYPES = {
    "replacement", "restart", "restatement", "chain", "multiple",
    "explicit_discard", "protected_replacement", "preserve",
}
SOURCE_KINDS = {"authored", "spokenly_parakeet"}


def load_corpus(path: Path = CORPUS) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported corpus schema")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) < 120:
        raise ValueError("corpus must contain at least 120 cases")
    if data.get("case_count") != len(cases):
        raise ValueError("corpus case_count is incorrect")
    ids = set()
    polarity = Counter()
    positive_categories = set()
    negative_categories = set()
    parakeet_categories = set()
    configured_expansions = " ".join(
        str(item["text"])
        for item in json.loads(SNIPPETS.read_text(encoding="utf-8"))
    ).casefold()
    for case in cases:
        if not isinstance(case, dict) or REQUIRED_FIELDS - set(case):
            raise ValueError(f"invalid corpus record: {case.get('id') if isinstance(case, dict) else '?'}")
        if case["reviewed"] is not True:
            raise ValueError(f"unreviewed corpus record: {case['id']}")
        if not isinstance(case["id"], str) or not case["id"]:
            raise ValueError("corpus record has an invalid id")
        if case["id"] in ids:
            raise ValueError(f"duplicate corpus id: {case['id']}")
        ids.add(case["id"])
        if case["polarity"] not in POLARITIES:
            raise ValueError(f"invalid polarity in {case['id']}")
        if not isinstance(case["category"], str) or not case["category"]:
            raise ValueError(f"invalid category in {case['id']}")
        if case["source_kind"] not in SOURCE_KINDS:
            raise ValueError(f"invalid source kind in {case['id']}")
        if not isinstance(case["provenance"], str) or not case["provenance"].strip():
            raise ValueError(f"missing provenance in {case['id']}")
        if not isinstance(case["raw_transcript"], str) or not case["raw_transcript"].strip():
            raise ValueError(f"invalid raw transcript in {case['id']}")
        if case["expected_repair_type"] not in REPAIR_TYPES:
            raise ValueError(f"invalid expected repair type in {case['id']}")
        for field in (
            "required_retained", "required_removed", "protected_atoms",
            "allowed_formatting_variants", "forbidden_additions",
        ):
            if not isinstance(case[field], list) or not all(
                isinstance(value, str) and value for value in case[field]
            ):
                raise ValueError(f"invalid {field} in {case['id']}")
        if not isinstance(case["expansion_occurrences"], list) or not all(
            isinstance(item, dict)
            and set(item) == {"id", "count"}
            and isinstance(item["id"], str)
            and item["id"]
            and isinstance(item["count"], int)
            and item["count"] > 0
            for item in case["expansion_occurrences"]
        ):
            raise ValueError(f"invalid expansion occurrences in {case['id']}")
        expected_pre = case["expected_pre"]
        if (
            not isinstance(expected_pre, dict)
            or set(expected_pre) != {"model_region", "type"}
            or not isinstance(expected_pre["model_region"], bool)
            or not isinstance(expected_pre["type"], str)
        ):
            raise ValueError(f"invalid expected_pre in {case['id']}")
        if not isinstance(case["expected_fallback"], str):
            raise ValueError(f"invalid expected fallback in {case['id']}")
        if case["expected_fallback"] != case["expected_fallback"].rstrip():
            raise ValueError(f"fallback has trailing whitespace in {case['id']}")
        polarity[case["polarity"]] += 1
        category_set = positive_categories if case["polarity"] == "positive" else negative_categories
        category_set.add(case["category"])
        if case["source_kind"] == "spokenly_parakeet":
            parakeet_categories.add(case["category"])
        source_folded = case["raw_transcript"].casefold()
        for span in (
            case["required_retained"]
            + case["required_removed"]
            + case["protected_atoms"]
        ):
            if span.casefold() not in source_folded and span.casefold() not in configured_expansions:
                raise ValueError(f"predicate is not source-grounded in {case['id']}: {span}")
    if polarity["positive"] < 60 or polarity["negative"] < 60:
        raise ValueError("corpus needs at least 60 positive and 60 negative cases")
    required_positive = {"replacement", "restart", "restatement", "chain", "multiple", "discard", "punctuation", "technical", "expansion_intersection", "long_dictation", "deliberate_repetition", "snippet_intersection", "file_reference_intersection"}
    required_negative = {"natural_cue", "quotation", "reported_speech", "additive", "emphasis", "repeated_identifier", "insufficient_target", "missing_repair", "adversarial", "technical_preserve"}
    if not required_positive <= positive_categories or not required_negative <= negative_categories:
        raise ValueError("corpus category coverage is incomplete")
    if not (required_positive | required_negative) <= parakeet_categories:
        raise ValueError("every category needs a real Spokenly/Parakeet transcript")
    return data


def preflight_cases(data: dict[str, object]) -> list[str]:
    failures = []
    benchmark_snippets = pre_ai.load_snippets(SNIPPETS)
    for case in data["cases"]:
        processed, prepared, _snippets = pre_ai.prepare_process(
            case["raw_transcript"], SNIPPETS
        )
        expected = case["expected_pre"]
        if bool(prepared.regions) != bool(expected["model_region"]):
            failures.append(f"{case['id']}: model_region mismatch")
            continue
        expected_type = expected["type"]
        if prepared.regions and expected_type not in {
            prepared.regions[0]["type"],
            "replacement" if len(prepared.regions) > 1 else "",
        }:
            failures.append(
                f"{case['id']}: expected {expected_type}, got {prepared.regions[0]['type']}"
            )
        for occurrence in case["expansion_occurrences"]:
            token_prefix = f"SPK_SNIPPET_{occurrence['id']}__"
            if processed.count(token_prefix) != occurrence["count"]:
                failures.append(
                    f"{case['id']}: protected expansion manifest mismatch for {occurrence['id']}"
                )
        if case["expected_repair_type"] == "protected_replacement" and "SPK_SNIPPET_SLASH_GOAL" in processed:
            failures.append(f"{case['id']}: superseded protected expansion survived")
        fallback = pre_ai.expand_snippets_in_source(
            prepared.safe_source, benchmark_snippets
        )
        if fallback != case["expected_fallback"]:
            failures.append(f"{case['id']}: deterministic fallback mismatch")
    return failures


def ollama_generate(
    model: str, transcript: str, endpoint: str, prompt_path: Path = PROMPT
) -> tuple[str, dict[str, object]]:
    payload = {
        "model": model,
        "system": prompt_path.read_text(encoding="utf-8"),
        "prompt": transcript,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "top_p": 0.8, "top_k": 20, "repeat_penalty": 1.0},
    }
    call = request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with request.urlopen(call, timeout=180) as response:
        result = json.loads(response.read())
    result["wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
    if result.get("thinking"):
        raise RuntimeError("model returned reasoning despite think=false")
    output = result.get("response")
    if not isinstance(output, str):
        raise RuntimeError("Ollama response did not contain transcript text")
    return output, result


def run_pipeline(
    source: str,
    model: str,
    endpoint: str,
    pipeline_root: Path = SPOKENLY,
    prompt_path: Path = PROMPT,
) -> tuple[str, dict[str, object]]:
    with tempfile.TemporaryDirectory() as directory:
        state = Path(directory) / "source-state.json"
        slash = Path(directory) / "slash-state.json"
        environment = os.environ.copy()
        environment.update({
            "SPOKENLY_ITERM_FILE_REFERENCES": "0",
            "SPOKENLY_SOURCE_RECOVERY_STATE": str(state),
            "SPOKENLY_SLASH_SNIPPET_STATE": str(slash),
            "PARAQWEN_DIAGNOSTICS": "0",
        })
        started = time.perf_counter()
        pre = subprocess.run(
            [sys.executable, str(pipeline_root / "scripts" / "pre_ai.py"), "--snippets", str(SNIPPETS)],
            input=source, text=True, capture_output=True, env=environment, check=True,
        )
        pre_ms = (time.perf_counter() - started) * 1000
        model_output, model_meta = ollama_generate(
            model, pre.stdout, endpoint, prompt_path
        )
        started = time.perf_counter()
        post = subprocess.run(
            [sys.executable, str(pipeline_root / "scripts" / "post_ai.py"), "--snippets", str(SNIPPETS)],
            input=model_output, text=True, capture_output=True, env=environment, check=True,
        )
        post_ms = (time.perf_counter() - started) * 1000
        return post.stdout, {
            "pre_ms": round(pre_ms, 3), "model_ms": model_meta["wall_ms"],
            "post_ms": round(post_ms, 3), "stderr_clean": not pre.stderr and not post.stderr,
            "pre_output": pre.stdout, "model_output": model_output,
        }


def predicates(case: dict[str, object], output: str) -> tuple[bool, list[str]]:
    folded = output.casefold()
    failures = []

    def contains(span: str) -> bool:
        if span.casefold() in folded:
            return True
        if "equivalent number formatting" not in case["allowed_formatting_variants"]:
            return False
        expected = repair_protocol._number_value(span)
        if expected is None:
            return False
        return any(
            repair_protocol._number_value(match.group(0)) == expected
            for match in re.finditer(
                r"(?<!\w)(?:-?\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?!\w)",
                output,
                re.IGNORECASE,
            )
        )

    for span in case["required_retained"]:
        if not contains(span):
            failures.append(f"missing retained span: {span}")
    for span in case["required_removed"]:
        if contains(span):
            failures.append(f"retained removed span: {span}")
    for addition in case["forbidden_additions"]:
        if addition.casefold() in folded:
            failures.append(f"forbidden addition: {addition}")

    snippet_config = {
        str(item["id"]): str(item["text"])
        for item in json.loads(SNIPPETS.read_text(encoding="utf-8"))
    }
    removed_folded = {span.casefold() for span in case["required_removed"]}
    mandatory_atoms = [
        atom
        for atom in case["protected_atoms"]
        if atom.casefold() not in removed_folded
    ]
    search_position = 0
    for atom in mandatory_atoms:
        position = folded.find(atom.casefold(), search_position)
        if position < 0:
            failures.append(f"safety: missing protected atom: {atom}")
        else:
            search_position = position + len(atom)

    allowed_atom_keys = Counter(
        map(
            repair_protocol.atom_key,
            repair_protocol.extract_protected_atoms(case["raw_transcript"]),
        )
    )
    for occurrence in case["expansion_occurrences"]:
        expansion = snippet_config.get(occurrence["id"])
        if expansion is None:
            failures.append(
                f"safety: unknown configured expansion: {occurrence['id']}"
            )
            continue
        actual_count = output.count(expansion)
        if actual_count != occurrence["count"]:
            failures.append(
                "safety: protected expansion count mismatch: "
                f"{occurrence['id']} expected {occurrence['count']} got {actual_count}"
            )
        expansion_atoms = repair_protocol.extract_protected_atoms(expansion)
        expansion_keys = Counter(map(repair_protocol.atom_key, expansion_atoms))
        for key, count in expansion_keys.items():
            allowed_atom_keys[key] += count * occurrence["count"]

    output_atom_keys = Counter(
        map(repair_protocol.atom_key, repair_protocol.extract_protected_atoms(output))
    )
    for key, count in output_atom_keys.items():
        if count > allowed_atom_keys[key]:
            failures.append(f"safety: invented protected atom: {key[0]}:{key[1]}")
    token_check = output
    for literal in case["required_retained"]:
        if re.fullmatch(r"\[\[(?:SPK|PARAQWEN)_[^\]]+\]\]", literal):
            token_check = token_check.replace(literal, "")
    if re.search(r"\[\[(?:SPK|PARAQWEN)_", token_check):
        failures.append("safety: structural token leak")
    if output != output.rstrip():
        failures.append("safety: trailing whitespace")
    return not failures, failures


def model_digest(model: str, endpoint: str) -> str:
    try:
        with request.urlopen(endpoint.rstrip("/") + "/api/tags", timeout=10) as response:
            tags = json.loads(response.read()).get("models", [])
        for item in tags:
            if item.get("name") == model or item.get("model") == model:
                digest = item.get("digest")
                if isinstance(digest, str) and digest:
                    return digest
    except (OSError, ValueError, TypeError):
        pass
    try:
        result = subprocess.run(["ollama", "show", model, "--modelfile"], text=True, capture_output=True, check=True)
        return hashlib.sha256(result.stdout.encode()).hexdigest()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "unavailable"


def release_input_digests(args: argparse.Namespace) -> dict[str, str]:
    return {
        "prompt_digest": file_digest(args.prompt_path),
        "corpus_digest": file_digest(args.corpus),
        "snippets_digest": file_digest(SNIPPETS),
        "pre_ai_digest": file_digest(args.pipeline_root / "scripts" / "pre_ai.py"),
        "post_ai_digest": file_digest(args.pipeline_root / "scripts" / "post_ai.py"),
        "repair_protocol_digest": file_digest(
            args.pipeline_root / "scripts" / "repair_protocol.py"
        ),
        "benchmark_digest": file_digest(Path(__file__)),
    }


def release_model_identity(args: argparse.Namespace) -> dict[str, str]:
    return {
        "model_digest": model_digest(args.model, args.endpoint),
        "ollama_version": subprocess.run(
            ["ollama", "--version"], text=True, capture_output=True
        ).stdout.strip(),
    }


def run_live(data: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    input_digests = release_input_digests(args)
    model_identity = release_model_identity(args)
    outcomes = []
    selected_ids = set(args.case_id or [])
    selected_cases = [
        case for case in data["cases"]
        if not selected_ids or case["id"] in selected_ids
    ]
    found_ids = {case["id"] for case in selected_cases}
    if selected_ids - found_ids:
        raise ValueError(
            f"unknown corpus case(s): {', '.join(sorted(selected_ids - found_ids))}"
        )
    for run_number in range(1, args.runs + 1):
        for case in selected_cases:
            output, timing = run_pipeline(
                case["raw_transcript"], args.model, args.endpoint,
                args.pipeline_root, args.prompt_path,
            )
            passed, failures = predicates(case, output)
            if not timing["stderr_clean"]:
                failures.append("safety: processor wrote unexpected stderr")
                passed = False
            outcomes.append({"run": run_number, "id": case["id"], "polarity": case["polarity"], "category": case["category"], "passed": passed, "failures": failures, "output": output, "timing": timing})
            print(f"run {run_number}/{args.runs} {case['id']}: {'PASS' if passed else 'FAIL'}", file=sys.stderr)
    counts = Counter((item["polarity"], item["passed"]) for item in outcomes)
    positive_total = sum(1 for item in outcomes if item["polarity"] == "positive")
    negative_total = sum(1 for item in outcomes if item["polarity"] == "negative")
    positive_rate = (
        100 * counts[("positive", True)] / positive_total if positive_total else 100.0
    )
    negative_rate = (
        100 * counts[("negative", True)] / negative_total if negative_total else 100.0
    )
    safety_failures = [
        item for item in outcomes
        if any(failure.startswith("safety:") for failure in item["failures"])
    ]
    categories = defaultdict(list)
    for item in outcomes:
        categories[item["category"]].append(item["passed"])
    if release_input_digests(args) != input_digests:
        raise RuntimeError("benchmark inputs changed during the live run")
    if release_model_identity(args) != model_identity:
        raise RuntimeError("model identity changed during the live run")
    report = {
        "schema_version": 1, "corpus_version": data["corpus_version"],
        "case_count": len(selected_cases), "outcome_count": len(outcomes),
        "created_at": time.time(), "model": args.model,
        **model_identity,
        **input_digests,
        "reasoning": "disabled (think=false)", "temperature": 0.0,
        "machine": platform.platform(), "python": platform.python_version(),
        "runs": args.runs, "positive_rate": positive_rate, "negative_preservation_rate": negative_rate,
        "category_rates": {key: 100 * sum(values) / len(values) for key, values in sorted(categories.items())},
        "safety_failures": len(safety_failures),
        "safety_failure_ids": [f"{item['id']}:run-{item['run']}" for item in safety_failures],
        "outcomes": outcomes,
        "mode": "historical_baseline" if args.historical_baseline else "release",
        "gates": {"positive_95": positive_rate >= 95, "negative_99": negative_rate >= 99, "zero_safety": not safety_failures, "three_runs": args.runs == 3, "complete_corpus": not selected_ids},
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--live", action="store_true", help="run the explicit local-model suite")
    parser.add_argument("--model", default="spokenly-qwen9b:latest")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--case-id", action="append", help="debug selected cases; repeatable and never satisfies the complete-corpus gate")
    parser.add_argument("--pipeline-root", type=Path, default=SPOKENLY)
    parser.add_argument("--prompt-path", type=Path, default=PROMPT)
    parser.add_argument("--historical-baseline", action="store_true", help="record a frozen old implementation; permits one run and does not apply release gates")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = load_corpus(args.corpus)
    failures = preflight_cases(data)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    if not args.live:
        print(f"Corpus {data['corpus_version']}: {len(data['cases'])} reviewed cases; deterministic preflight passed")
        print("Live model not run. Use --live --runs 3; a skipped live suite is not a pass.")
        return 0
    if args.runs != 3 and not (args.historical_baseline and args.runs == 1):
        print("The release gate requires exactly three complete runs.", file=sys.stderr)
        return 2
    report = run_live(data, args)
    report_path = args.report or HERE / f"results/backtracking-{int(time.time())}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("positive_rate", "negative_preservation_rate", "safety_failures", "gates")}, indent=2))
    print(f"Report: {report_path}")
    if args.historical_baseline:
        return 0
    return 0 if all(report["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
