import importlib.util
from contextlib import redirect_stderr
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "run_backtracking_benchmark.py"
VERIFY_RESULTS = ROOT / "benchmarks" / "verify_results.py"
SPEC = ROOT.parents[1] / "research" / "paraqwen-dictation" / "backtracking-and-self-repair.spec.md"

spec = importlib.util.spec_from_file_location("backtracking_benchmark", BENCHMARK)
benchmark = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(benchmark)
verify_spec = importlib.util.spec_from_file_location("verify_results", VERIFY_RESULTS)
verify_results = importlib.util.module_from_spec(verify_spec)
assert verify_spec.loader is not None
verify_spec.loader.exec_module(verify_results)


class BacktrackingBenchmarkTests(unittest.TestCase):
    def test_corpus_schema_counts_review_and_categories(self):
        data = benchmark.load_corpus()
        self.assertEqual(data["case_count"], 126)
        self.assertEqual(
            sum(case["polarity"] == "positive" for case in data["cases"]), 66
        )
        self.assertEqual(
            sum(case["polarity"] == "negative" for case in data["cases"]), 60
        )

    def test_corpus_deterministic_preflight(self):
        self.assertEqual(benchmark.preflight_cases(benchmark.load_corpus()), [])

    def test_corpus_schema_rejects_claims_with_invalid_types(self):
        data = benchmark.load_corpus()
        data["cases"][0]["reviewed"] = "yes"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark.load_corpus(path)

    def test_live_predicates_count_protected_atom_and_expansion_safety(self):
        cases = {case["id"]: case for case in benchmark.load_corpus()["cases"]}
        expansion_case = cases["positive-049"]
        valid = "/spec-ops:launch-spec"
        self.assertEqual(benchmark.predicates(expansion_case, valid), (True, []))
        passed, failures = benchmark.predicates(
            expansion_case, valid + " " + valid
        )
        self.assertFalse(passed)
        self.assertTrue(any(failure.startswith("safety:") for failure in failures))

        technical_case = cases["negative-055"]
        damaged = technical_case["raw_transcript"].replace("/goal", "/invented")
        passed, failures = benchmark.predicates(technical_case, damaged)
        self.assertFalse(passed)
        self.assertTrue(any("invented protected atom" in item for item in failures))

    def test_evidence_verifier_recomputes_each_recorded_outcome(self):
        case = next(
            case
            for case in benchmark.load_corpus()["cases"]
            if case["id"] == "negative-001"
        )
        report = {
            "outcomes": [
                {
                    "run": 1,
                    "id": case["id"],
                    "polarity": case["polarity"],
                    "category": case["category"],
                    "passed": False,
                    "failures": ["fabricated result"],
                    "output": case["raw_transcript"],
                }
            ]
        }
        errors = []
        summary = verify_results._verify_outcomes(
            label="fixture",
            report=report,
            cases={case["id"]: case},
            runs=1,
            require_timing=False,
            benchmark=benchmark,
            errors=errors,
        )
        self.assertIsNotNone(summary)
        self.assertEqual(errors, ["fixture outcome negative-001:run-1 was not reproducible"])

    def test_committed_quality_and_performance_results(self):
        self.assertEqual(verify_results.verify(), [])

    def test_live_runner_explicitly_disables_reasoning(self):
        source = BENCHMARK.read_text(encoding="utf-8")
        self.assertIn('"think": False', source)
        self.assertIn('"temperature": 0.0', source)
        self.assertIn("args.runs != 3", source)

    def test_live_runner_rejects_inputs_changed_during_execution(self):
        case = next(
            case
            for case in benchmark.load_corpus()["cases"]
            if case["id"] == "negative-001"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("pre_ai.py", "post_ai.py", "repair_protocol.py"):
                (scripts / name).write_text(name, encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("before", encoding="utf-8")
            corpus = root / "corpus.json"
            corpus.write_text("{}", encoding="utf-8")
            args = SimpleNamespace(
                prompt_path=prompt,
                corpus=corpus,
                pipeline_root=root,
                case_id=[case["id"]],
                runs=1,
                model="fixture",
                endpoint="http://127.0.0.1:1",
                historical_baseline=True,
            )

            def mutate_input(*_args, **_kwargs):
                prompt.write_text("after", encoding="utf-8")
                return case["raw_transcript"], {
                    "pre_ms": 1.0,
                    "model_ms": 1.0,
                    "post_ms": 1.0,
                    "stderr_clean": True,
                }

            with redirect_stderr(io.StringIO()):
                with mock.patch.object(
                    benchmark,
                    "release_model_identity",
                    return_value={
                        "model_digest": "stable",
                        "ollama_version": "stable",
                    },
                ), mock.patch.object(benchmark, "run_pipeline", mutate_input):
                    with self.assertRaisesRegex(RuntimeError, "inputs changed"):
                        benchmark.run_live({"cases": [case]}, args)

            prompt.write_text("stable", encoding="utf-8")
            timing = {
                "pre_ms": 1.0,
                "model_ms": 1.0,
                "post_ms": 1.0,
                "stderr_clean": True,
            }
            identities = (
                {"model_digest": "first", "ollama_version": "same"},
                {"model_digest": "second", "ollama_version": "same"},
            )
            with redirect_stderr(io.StringIO()):
                with mock.patch.object(
                    benchmark, "release_model_identity", side_effect=identities
                ), mock.patch.object(
                    benchmark,
                    "run_pipeline",
                    return_value=(case["raw_transcript"], timing),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "model identity changed"
                    ):
                        benchmark.run_live({"cases": [case]}, args)

    def test_prompt_has_decision_procedure_and_targeted_examples(self):
        prompt = (ROOT / "prompts" / "qwen-prompt.md").read_text(encoding="utf-8")
        for phrase in (
            "For every numbered repair region",
            "Substitution:",
            "Full restart:",
            "Cue-free restatement:",
            "Correction chain:",
            "Additive clarification:",
            "Literal and natural-use negatives:",
            "Return no analysis or reasoning",
        ):
            self.assertIn(phrase, prompt)
        self.assertNotIn("SPK_CMD_REPLACE_NEAREST", prompt)
        self.assertNotIn("Never reproduce a control token", prompt)
        self.assertIn(
            "Send it to support. Actually, also include the escalation notes.",
            prompt,
        )

    def test_setup_pins_reasoning_none_and_temperature_zero(self):
        setup = (ROOT / "SETUP.md").read_text(encoding="utf-8")
        model = (ROOT / "ollama" / "Modelfile.spokenly-qwen9b").read_text(
            encoding="utf-8"
        )
        self.assertIn("Reasoning | **None**", setup)
        self.assertIn("PARAMETER temperature 0.0", model)

    def test_every_acceptance_criterion_has_an_agent_or_human_check(self):
        text = SPEC.read_text(encoding="utf-8")
        for number in range(1, 47):
            self.assertIn(f"| {number} |", text)
        self.assertIn("### For agents", text)
        self.assertIn("### For humans", text)

        implementation_map = (ROOT / "BACKTRACKING_IMPLEMENTATION.md").read_text(
            encoding="utf-8"
        )
        for number in range(1, 47):
            self.assertEqual(
                implementation_map.count(f"| {number} |"),
                1,
                f"acceptance criterion {number} must have one evidence row",
            )


if __name__ == "__main__":
    unittest.main()
