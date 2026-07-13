import json
import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import diagnostics  # noqa: E402
import pre_ai  # noqa: E402
import repair_protocol as repair  # noqa: E402


class RepairProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.snippets = Path(self.tempdir.name) / "snippets.json"
        self.snippets.write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def state_for(self, source):
        prepared = repair.prepare_repairs(source)
        state = repair.build_state(
            prepared,
            framed_source=prepared.framed_source,
            verified_text=prepared.safe_source,
            portable_text=prepared.safe_source,
            file_nonce=None,
            expected_counts={},
            prompt_config_digest="TEST",
        )
        return prepared, repair.resolve_state_sources(state)

    def accepted_output(self, prepared, replacements):
        output = prepared.framed_source
        for region, replacement in reversed(list(zip(prepared.regions, replacements))):
            start, end = str(region["start_token"]), str(region["end_token"])
            left = output.find(start) + len(start)
            right = output.find(end, left)
            output = output[:left] + replacement + output[right:]
        return output

    def test_required_explicit_cues_are_typed(self):
        cues = [
            "I mean", "I meant", "Sorry, I meant", "No, actually", "No, wait",
            "or rather", "make that", "I should say", "what I meant was",
            "let me rephrase", "let me start over",
        ]
        for cue in cues:
            with self.subTest(cue=cue):
                prepared = repair.prepare_repairs(f"Send it Friday. {cue} Monday.")
                self.assertEqual(len(prepared.regions), 1)
                expected = "restart" if cue.casefold() in {"no, wait", "let me rephrase", "let me start over"} else "replacement"
                self.assertEqual(prepared.regions[0]["type"], expected)

    def test_every_required_cue_accepts_asr_punctuation_without_dangling_marks(self):
        cues = (
            "I mean",
            "I meant",
            "Sorry, I meant",
            "No, actually",
            "No, wait",
            "or rather",
            "make that",
            "I should say",
            "what I meant was",
            "let me rephrase",
            "let me start over",
        )
        for cue in cues:
            with self.subTest(cue=cue):
                prepared, state = self.state_for(
                    f"Use Friday? {cue}: Monday."
                )
                model = self.accepted_output(prepared, ["Use Monday."])
                accepted = repair.validate_model_output(model, state)
                self.assertEqual(accepted, "Use Monday.")
                self.assertNotRegex(accepted, r"[,;:]\s*[.!?]")

    def test_asr_boundaries_and_editing_interval_punctuation_are_normalized(self):
        cases = (
            "Use Friday, I mean, Monday.",
            "Use Friday. I mean: Monday.",
            "Use Friday? No, actually, Monday.",
            "Use Friday! No, wait: use Monday.",
            "Use Friday.\nI should say, Monday.",
        )
        for source in cases:
            with self.subTest(source=source):
                prepared = repair.prepare_repairs(source)
                self.assertTrue(prepared.regions)
                self.assertNotRegex(
                    prepared.framed_source,
                    r"_CUE_[^\]]+\]\]\s*[,;:]",
                )

    def test_accepted_repairs_preserve_unrelated_punctuation_without_dangling_marks(self):
        cases = (
            ("Use Friday, I mean, Monday.", "Use Monday."),
            ("Use Friday. I mean: Monday.", "Use Monday."),
            ("Use Friday? No, actually, Monday.", "Use Monday."),
            ("Use Friday! No, wait: use Monday.", "Use Monday."),
            ("Use Friday.\nI should say, Monday.", "Use Monday."),
        )
        for source, replacement in cases:
            with self.subTest(source=source):
                prepared, state = self.state_for(source)
                model_output = self.accepted_output(prepared, [replacement])
                self.assertEqual(
                    repair.validate_model_output(model_output, state),
                    replacement,
                )

        source = (
            "Keep this question?\n\n"
            "Keep https://example.com/CasePath?x=1, dev@example.com, "
            "@src/app.py, /tmp/App.py, BuildFile.py, CacheKey, abcdef1, "
            "v2.4, 2026-07-12, 09:30, 3GB, and /goal! "
            "Use Friday, I mean Monday.\n\n"
            "Keep this answer!"
        )
        prepared, state = self.state_for(source)
        model_output = self.accepted_output(prepared, ["Use Monday."])
        accepted = repair.validate_model_output(model_output, state)
        for literal in (
            "Keep this question?",
            "https://example.com/CasePath?x=1",
            "dev@example.com",
            "@src/app.py",
            "/tmp/App.py",
            "BuildFile.py",
            "CacheKey",
            "abcdef1",
            "v2.4",
            "2026-07-12",
            "09:30",
            "3GB",
            "/goal!",
            "Use Monday.",
            "Keep this answer!",
        ):
            self.assertIn(literal, accepted)
        self.assertNotRegex(accepted, r"[,;:]\s*[.!?]")

    def test_chain_is_one_ordered_region(self):
        prepared = repair.prepare_repairs("Send it to Alex, no Sam, no Priya.")
        self.assertEqual(len(prepared.regions), 1)
        self.assertEqual(prepared.regions[0]["type"], "chain")
        self.assertEqual([cue["number"] for cue in prepared.regions[0]["cues"]], [1, 2])

    def test_independent_repairs_are_separate_and_ordered(self):
        prepared = repair.prepare_repairs(
            "First is red, I mean blue. Second is tall, I mean short."
        )
        self.assertEqual([r["number"] for r in prepared.regions], [1, 2])
        self.assertTrue(prepared.regions[0]["source_end"] <= prepared.regions[1]["source_start"])

    def test_restart_never_crosses_paragraph(self):
        prepared = repair.prepare_repairs(
            "Unrelated paragraph.\n\nWe should ship Friday. Let me start over. Review first."
        )
        self.assertEqual(len(prepared.regions), 1)
        self.assertNotIn("Unrelated", prepared.regions[0]["source_text"])
        no_restart = repair.prepare_repairs(
            "Use Friday. No, tell me the release plan instead."
        )
        self.assertEqual(no_restart.regions[0]["type"], "restart")

    def test_cue_free_parallel_restatement_is_framed(self):
        prepared = repair.prepare_repairs(
            "I wanted to buy a record as a gift, as a present."
        )
        self.assertEqual(prepared.regions[0]["type"], "restatement")
        clause = repair.prepare_repairs(
            "We should ship Friday, we should ship Monday."
        )
        self.assertEqual(clause.regions[0]["type"], "restatement")

    def test_weak_topical_similarity_is_not_framed(self):
        prepared = repair.prepare_repairs(
            "The release is important. The support guide is useful."
        )
        self.assertEqual(prepared.regions, [])

    def test_exact_multiword_repetition_is_tier_one(self):
        prepared = repair.prepare_repairs("Use alpha beta, alpha beta today.")
        self.assertEqual(prepared.safe_source, "Use alpha beta today.")
        self.assertEqual(prepared.deterministic_edits[0]["type"], "exact_repetition")

    def test_complete_repeated_phrase_can_remain_deliberate_emphasis(self):
        source = "Never give up, never give up."
        prepared = repair.prepare_repairs(source)
        self.assertEqual(prepared.safe_source, source)
        self.assertEqual(prepared.deterministic_edits, [])

    def test_deliberate_emphasis_is_preserved(self):
        prepared = repair.prepare_repairs("This is very, very important.")
        self.assertEqual(prepared.safe_source, "This is very, very important.")
        self.assertEqual(prepared.regions, [])

        long_source = (
            "This release is very, very important for every customer and every "
            "support team in the company."
        )
        prepared, state = self.state_for(long_source)
        with self.assertRaises(repair.RepairValidationError):
            repair.validate_model_output(
                long_source.replace("very, very", "very"), state
            )

    def test_additive_clarification_is_preserved(self):
        source = "Send it to support. Actually, also include the escalation notes."
        prepared = repair.prepare_repairs(source)
        self.assertEqual(prepared.regions, [])
        self.assertTrue(prepared.ambiguous_spans)

    def test_natural_cue_uses_are_not_repairs(self):
        for source in (
            "I actually think Thursday is better.",
            "There is no reason to change it.",
            "Sorry, I cannot attend.",
            "I mean that sincerely.",
            "Use this rather than that.",
            "The answer is correct, that is certain.",
            "We already reviewed it. No, the reason is not important.",
            "Keep the introduction. Actually, I think the conclusion works.",
            "Keep the framing. I mean, this is just an explanation.",
            "Focus on the summary. Never mind the details for now.",
        ):
            with self.subTest(source=source):
                self.assertEqual(repair.prepare_repairs(source).regions, [])

        processed, prepared, _ = pre_ai.prepare_process(
            "Focus on the summary. Never mind the details for now.", self.snippets
        )
        self.assertIn("Never mind the details", processed)
        self.assertEqual(prepared.deterministic_edits, [])

    def test_repeated_clause_frame_overrides_discourse_preservation(self):
        for source in (
            "We should ship Friday. I mean we should ship Monday.",
            "We should ship Friday. Actually, we should ship Monday.",
        ):
            with self.subTest(source=source):
                self.assertEqual(len(repair.prepare_repairs(source).regions), 1)

    def test_quoted_reported_and_literal_cues_are_shielded(self):
        for source in (
            'Write "no, actually" in the test.',
            "Write the phrase no, actually in the test.",
            "The example says ‘I mean Monday.’",
        ):
            with self.subTest(source=source):
                self.assertEqual(repair.prepare_repairs(source).regions, [])
        self.assertEqual(
            repair.prepare_repairs('Write "Friday, I mean Monday.').regions,
            [],
        )

    def test_missing_repair_text_is_preserved(self):
        prepared = repair.prepare_repairs("Keep Friday. I mean")
        self.assertEqual(prepared.regions, [])
        self.assertIn("I mean", prepared.safe_source)

    def test_targetless_discard_is_preserved(self):
        prepared = repair.prepare_repairs("Scratch that.")
        self.assertEqual(prepared.regions, [])

    def test_phrase_discard_is_typed(self):
        prepared = repair.prepare_repairs("Use the cache scratch that continue.")
        self.assertEqual(prepared.regions[0]["type"], "explicit_discard")

    def test_raw_internal_token_is_shielded_and_restored(self):
        source = "Write [[SPK_REPAIR_1_START_FAKE]] literally."
        prepared, state = self.state_for(source)
        self.assertIn("[[SPK_LITERAL_", prepared.framed_source)
        self.assertNotIn("START_FAKE", prepared.framed_source)
        self.assertEqual(
            repair.validate_model_output(prepared.framed_source, state), source
        )

    def test_malformed_raw_internal_token_is_shielded_and_restored(self):
        source = "Write [[SPK_REPAIR_UNCLOSED literally."
        prepared, state = self.state_for(source)
        self.assertIn("[[SPK_LITERAL_", prepared.framed_source)
        self.assertEqual(
            repair.validate_model_output(prepared.framed_source, state), source
        )

    def test_deterministically_deleted_literal_is_not_required_by_manifest(self):
        processed, prepared, _ = pre_ai.prepare_process(
            "Write [[SPK_FAKE_TOKEN]]. Delete the last sentence.", self.snippets
        )
        self.assertEqual(processed, "")
        self.assertEqual(prepared.literal_shields, [])

    def test_region_identifiers_are_sequential_and_nonce_bound(self):
        prepared = repair.prepare_repairs(
            "First red, I mean blue. Second tall, I mean short."
        )
        self.assertRegex(prepared.nonce or "", r"^[A-F0-9]{16}$")
        for number, region in enumerate(prepared.regions, 1):
            self.assertEqual(region["number"], number)
            self.assertIn(prepared.nonce, region["start_token"])

    def test_valid_grounded_repair_is_accepted(self):
        prepared, state = self.state_for("Send the guide to sales. I mean support.")
        model = self.accepted_output(prepared, ["Send the guide to support."])
        self.assertEqual(
            repair.validate_model_output(model, state), "Send the guide to support."
        )

    def test_missing_duplicated_reordered_and_forged_boundaries_fail(self):
        prepared, state = self.state_for(
            "First red, I mean blue. Second tall, I mean short."
        )
        valid = self.accepted_output(prepared, ["First blue.", "Second short."])
        corruptions = [
            valid.replace(str(prepared.regions[0]["start_token"]), "", 1),
            valid + str(prepared.regions[0]["end_token"]),
            valid.replace("SPK_REPAIR_1_START", "SPK_REPAIR_9_START", 1),
            valid.replace(prepared.nonce or "", "0000000000000000", 1),
        ]
        for value in corruptions:
            with self.subTest(value=value[-80:]):
                with self.assertRaises(repair.RepairValidationError):
                    repair.validate_model_output(value, state)

    def test_corrupted_region_and_cue_manifest_checksums_fail(self):
        prepared, state = self.state_for("Use Friday. I mean Monday.")
        valid = self.accepted_output(prepared, ["Use Monday."])
        corruptions = []
        for field in ("integrity", "start_token", "source_atoms"):
            damaged = json.loads(json.dumps(state))
            if field == "source_atoms":
                damaged["repair_regions"][0][field] = [
                    {"kind": "number", "value": "9", "start": 0, "end": 1}
                ]
            else:
                damaged["repair_regions"][0][field] = "CORRUPTED"
            corruptions.append(damaged)
        damaged = json.loads(json.dumps(state))
        damaged["repair_regions"][0]["cues"][0]["digest"] = "00000000"
        corruptions.append(damaged)
        for manifest in corruptions:
            with self.subTest(field=manifest["repair_regions"][0]):
                with self.assertRaises(repair.RepairValidationError):
                    repair.validate_model_output(valid, manifest)

    def test_corrupted_literal_shield_manifest_checksum_fails(self):
        prepared, state = self.state_for("Write [[SPK_FAKE_TOKEN]] literally.")
        state["literal_shields"][0]["digest"] = "00000000"
        with self.assertRaisesRegex(repair.RepairValidationError, "checksum"):
            repair.validate_model_output(prepared.framed_source, state)

    def test_cue_token_leak_fails(self):
        prepared, state = self.state_for("Use Friday. I mean Monday.")
        with self.assertRaisesRegex(repair.RepairValidationError, "cue"):
            repair.validate_model_output(prepared.framed_source, state)

    def test_invented_replacement_content_fails_grounding(self):
        prepared, state = self.state_for("Use Friday. I mean Monday.")
        model = self.accepted_output(prepared, ["Invent an unprecedented helicopter explanation."])
        with self.assertRaisesRegex(repair.RepairValidationError, "grounded"):
            repair.validate_model_output(model, state)

    def test_even_short_invention_or_word_duplication_fails_grounding(self):
        prepared, state = self.state_for("Send the guide to sales. I mean support.")
        for replacement in (
            "Send the guide to support. Looks good.",
            "Send the guide to support support.",
            "Send the guide or support.",
        ):
            with self.subTest(replacement=replacement):
                model = self.accepted_output(prepared, [replacement])
                with self.assertRaisesRegex(repair.RepairValidationError, "grounded"):
                    repair.validate_model_output(model, state)

        # The nouns in this separate source are grounded; only the article is new.
        article_prepared, article_state = self.state_for(
            "Send onboarding guide to sales team. I mean support team."
        )
        article_model = self.accepted_output(
            article_prepared, ["Send the onboarding guide to the support team."]
        )
        self.assertEqual(
            repair.validate_model_output(article_model, article_state),
            "Send the onboarding guide to the support team.",
        )

    def test_outside_region_insertion_and_deletion_fail_alignment(self):
        prepared, state = self.state_for(
            "Keep this unrelated sentence. Use Friday, I mean Monday. Keep the ending."
        )
        valid = self.accepted_output(prepared, ["Use Monday."])
        for damaged in (
            valid.replace("Keep this unrelated sentence.", ""),
            "Invent several unrelated requirements and promises. " + valid,
        ):
            with self.assertRaisesRegex(repair.RepairValidationError, "outside repair"):
                repair.validate_model_output(damaged, state)

    def test_protected_atoms_outside_region_cannot_change(self):
        source = "Keep https://example.com and version v2.4. Use Friday, I mean Monday."
        prepared, state = self.state_for(source)
        valid = self.accepted_output(prepared, ["Use Monday."])
        for damaged in (
            valid.replace("https://example.com", "https://evil.example"),
            valid.replace("v2.4", "v2.5"),
        ):
            with self.assertRaises(repair.RepairValidationError):
                repair.validate_model_output(damaged, state)
        absolute = repair.extract_protected_atoms(
            "Keep /Users/example/project/src/app.py unchanged."
        )
        self.assertEqual(absolute[0]["kind"], "path")
        self.assertEqual(absolute[0]["value"], "/Users/example/project/src/app.py")

    def test_case_sensitive_url_paths_and_filenames_cannot_change_case(self):
        for source, damaged in (
            ("Keep https://example.com/CasePath.", "Keep https://example.com/casepath."),
            ("Keep BuildFile.py.", "Keep buildfile.py."),
        ):
            with self.subTest(source=source):
                _prepared, state = self.state_for(source)
                with self.assertRaises(repair.RepairValidationError):
                    repair.validate_model_output(damaged, state)

        _prepared, state = self.state_for("Keep HTTPS://EXAMPLE.COM/CasePath.")
        self.assertEqual(
            repair.validate_model_output("Keep https://example.com/CasePath.", state),
            "Keep https://example.com/CasePath.",
        )

    def test_numeric_repair_cannot_delete_older_unrelated_number(self):
        prepared, state = self.state_for("Send 3 files at 4, I mean 5.")
        valid = self.accepted_output(prepared, ["Send 3 files at 5."])
        self.assertEqual(
            repair.validate_model_output(valid, state), "Send 3 files at 5."
        )
        damaged = self.accepted_output(prepared, ["Send files at 5."])
        with self.assertRaises(repair.RepairValidationError):
            repair.validate_model_output(damaged, state)

        prepared, state = self.state_for("Use 3, no 4, no 5.")
        final_chain = self.accepted_output(prepared, ["Use 5."])
        self.assertEqual(repair.validate_model_output(final_chain, state), "Use 5.")

    def test_grounded_filename_repair_is_allowed_but_cannot_reorder_atoms(self):
        prepared, state = self.state_for("Use old.py. I mean new.py.")
        valid = self.accepted_output(prepared, ["Use new.py."])
        self.assertEqual(repair.validate_model_output(valid, state), "Use new.py.")

        prepared, state = self.state_for(
            "Use old.py before stable.py. I mean use new.py before stable.py."
        )
        moved = self.accepted_output(prepared, ["Use stable.py after new.py."])
        with self.assertRaisesRegex(repair.RepairValidationError, "relocated"):
            repair.validate_model_output(moved, state)

    def test_invented_slash_command_and_file_reference_fail(self):
        prepared, state = self.state_for("Keep this ordinary sentence.")
        for addition in (" /goal", " @src/secret.py"):
            with self.assertRaises(repair.RepairValidationError):
                repair.validate_model_output(prepared.framed_source + addition, state)

    def test_number_word_digit_equivalence_is_supported(self):
        source = repair.extract_protected_atoms("Use 3 items.")[0]
        spoken = {"kind": "number", "value": "three"}
        self.assertEqual(repair.atom_key(source), repair.atom_key(spoken))
        prepared, state = self.state_for("Use three items.")
        self.assertEqual(
            repair.validate_model_output("Use 3 items.", state), "Use 3 items."
        )
        prepared, state = self.state_for("Use twenty one items.")
        self.assertEqual(
            repair.validate_model_output("Use 21 items.", state), "Use 21 items."
        )

    def test_different_numeric_value_is_not_equivalent(self):
        three = repair.atom_key({"kind": "number", "value": "3"})
        four = repair.atom_key({"kind": "number", "value": "4"})
        self.assertNotEqual(three, four)
        milliseconds = repair.atom_key({"kind": "number", "value": "3ms"})
        gigabytes = repair.atom_key({"kind": "number", "value": "3GB"})
        self.assertNotEqual(milliseconds, gigabytes)

    def test_compound_number_words_are_equivalent_to_digits(self):
        for words, digits in (
            ("twenty one", "21"),
            ("one hundred twenty one", "121"),
            ("two thousand five hundred", "2500"),
        ):
            with self.subTest(words=words):
                source_atom = repair.extract_protected_atoms(words)[0]
                digit_atom = repair.extract_protected_atoms(digits)[0]
                self.assertEqual(
                    repair.atom_key(source_atom), repair.atom_key(digit_atom)
                )
        _prepared, state = self.state_for("Use one hundred twenty one items.")
        self.assertEqual(
            repair.validate_model_output("Use 121 items.", state), "Use 121 items."
        )

    def test_numeric_units_are_preserved_by_end_to_end_validation(self):
        _prepared, state = self.state_for("Keep the timeout at 3ms.")
        with self.assertRaises(repair.RepairValidationError):
            repair.validate_model_output("Keep the timeout at 3GB.", state)

    def test_mixed_case_code_identifiers_are_protected(self):
        values = "CacheKey HTTPServer Build_Config cache-key"
        identifiers = [
            atom["value"]
            for atom in repair.extract_protected_atoms(values)
            if atom["kind"] == "identifier"
        ]
        self.assertEqual(
            identifiers, ["CacheKey", "HTTPServer", "Build_Config", "cache-key"]
        )

    def test_protected_atom_relocation_is_rejected(self):
        prepared, state = self.state_for("Use 3 before 4 in the sequence.")
        with self.assertRaisesRegex(repair.RepairValidationError, "relocated"):
            repair.validate_model_output("Use 4 before 3 in the sequence.", state)

    def test_ambiguous_span_deletion_fails(self):
        source = "Send it to support. Actually, also include the notes."
        prepared, state = self.state_for(source)
        with self.assertRaises(repair.RepairValidationError):
            repair.validate_model_output("Send it to support.", state)

        long_source = (
            "Keep the release context and every verified requirement. "
            "Actually, also include the detailed escalation notes for support."
        )
        _prepared, state = self.state_for(long_source)
        with self.assertRaisesRegex(repair.RepairValidationError, "ambiguous"):
            repair.validate_model_output(
                long_source.replace("Actually, ", ""), state
            )

    def test_quoted_literal_span_cannot_be_removed_from_long_context(self):
        source = (
            "Keep all of this surrounding release context for the final report. "
            "Write the phrase ‘no, actually’ in the regression test exactly. "
            "Preserve every other verified requirement and conclusion."
        )
        _prepared, state = self.state_for(source)
        damaged = source.replace("‘no, actually’ ", "")
        with self.assertRaisesRegex(repair.RepairValidationError, "ambiguous"):
            repair.validate_model_output(damaged, state)

    def test_every_accepted_branch_strips_trailing_whitespace(self):
        prepared, state = self.state_for("Keep this sentence.")
        self.assertEqual(
            repair.validate_model_output(prepared.framed_source + "\n\t ", state),
            "Keep this sentence.",
        )

    def test_protected_trigger_correction_occurs_before_manifest(self):
        config = Path(self.tempdir.name) / "commands.json"
        config.write_text(json.dumps([
            {"id": "GOAL", "triggers": ["slash goal"], "text": "/goal", "consume_trailing_punctuation": True},
            {"id": "LAUNCH", "triggers": ["slash launch spec"], "text": "/launch", "consume_trailing_punctuation": True},
        ]), encoding="utf-8")
        processed, prepared, _ = pre_ai.prepare_process(
            "slash goal, I mean slash launch spec", config
        )
        self.assertNotIn("SPK_SNIPPET_GOAL", processed)
        self.assertIn("SPK_SNIPPET_LAUNCH", processed)
        self.assertEqual(prepared.deterministic_edits[0]["type"], "protected_replacement")

    def test_additive_protected_triggers_both_survive(self):
        config = Path(self.tempdir.name) / "commands.json"
        config.write_text(json.dumps([
            {"id": "A", "triggers": ["insert alpha"], "text": "ALPHA"},
            {"id": "B", "triggers": ["insert bravo"], "text": "BRAVO"},
        ]), encoding="utf-8")
        processed = pre_ai.process("insert alpha and insert bravo", config)
        self.assertIn("SPK_SNIPPET_A", processed)
        self.assertIn("SPK_SNIPPET_B", processed)

    def test_grounded_repair_spanning_a_snippet_expansion_is_accepted(self):
        config = Path(self.tempdir.name) / "repair-with-snippet.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "id": "BRIEFING_LABEL",
                        "triggers": ["insert briefing label"],
                        "text": "[BRIEFING]",
                        "consume_trailing_punctuation": False,
                    },
                    {
                        "id": "SLASH_GOAL",
                        "triggers": ["slash goal"],
                        "text": "/goal",
                        "consume_trailing_punctuation": True,
                    },
                ]
            ),
            encoding="utf-8",
        )
        repeated = pre_ai.process(
            "insert briefing label, insert briefing label today", config
        )
        self.assertEqual(repeated.count("SPK_SNIPPET_BRIEFING_LABEL"), 2)
        cases = (
            (
                "insert briefing label then use sales, I mean support.",
                "[BRIEFING] then use support.",
            ),
            (
                "slash goal then review sales, I mean support.",
                "/goal then review support.",
            ),
            (
                "alpha beta, alpha beta today insert briefing label then use "
                "sales, I mean support.",
                "alpha beta today [BRIEFING] then use support.",
            ),
        )
        for index, (source, expected) in enumerate(cases):
            with self.subTest(source=source):
                environment = os.environ.copy()
                environment.update(
                    {
                        "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                        "SPOKENLY_SOURCE_RECOVERY_STATE": str(
                            Path(self.tempdir.name) / f"snippet-repair-source-{index}.json"
                        ),
                        "SPOKENLY_SLASH_SNIPPET_STATE": str(
                            Path(self.tempdir.name) / f"snippet-repair-slash-{index}.json"
                        ),
                    }
                )
                pre = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "pre_ai.py"),
                        "--snippets",
                        str(config),
                    ],
                    input=source,
                    text=True,
                    capture_output=True,
                    env=environment,
                    check=True,
                )
                model = re.sub(
                    r"(?P<prefix>then (?:use|review)) sales,\s*"
                    r"\[\[SPK_REPAIR_1_CUE_1_REPLACEMENT_[^\]]+\]\]\s*support\.",
                    r"\g<prefix> support.",
                    pre.stdout,
                )
                self.assertNotEqual(model, pre.stdout)
                self.assertGreater(
                    pre.stdout.find("[[SPK_REPAIR_1_START_"),
                    pre.stdout.find("[[SPK_SNIPPET_"),
                )
                post = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "post_ai.py"),
                        "--snippets",
                        str(config),
                    ],
                    input=model,
                    text=True,
                    capture_output=True,
                    env=environment,
                    check=True,
                )
                self.assertEqual(post.stdout, expected)

    def test_directive_created_trigger_is_still_protected(self):
        config = Path(self.tempdir.name) / "created-trigger.json"
        config.write_text(
            json.dumps(
                [{"id": "GOAL", "triggers": ["slash goal"], "text": "/goal"}]
            ),
            encoding="utf-8",
        )
        processed = pre_ai.process("slash extra scratch word goal", config)
        self.assertIn("SPK_SNIPPET_GOAL", processed)

    def test_file_reference_to_file_reference_correction_is_deterministic(self):
        extras = [
            {
                "id": "FILE_REF_AAAAAAAAAAAAAAAA_1",
                "triggers": ["at file first dot pie"],
                "text": "@first.py",
                "consume_trailing_punctuation": False,
            },
            {
                "id": "FILE_REF_AAAAAAAAAAAAAAAA_2",
                "triggers": ["at file second dot pie"],
                "text": "@second.py",
                "consume_trailing_punctuation": False,
            },
        ]
        processed, prepared, _ = pre_ai.prepare_process(
            "Use at file first dot pie, no, at file second dot pie.",
            self.snippets,
            extras,
        )
        self.assertNotIn("FILE_REF_AAAAAAAAAAAAAAAA_1", processed)
        self.assertIn("FILE_REF_AAAAAAAAAAAAAAAA_2", processed)
        self.assertEqual(prepared.regions, [])

    def test_state_is_owner_only_atomic_and_consumed_once(self):
        state_path = Path(self.tempdir.name) / "state.json"
        pre_ai.record_source_recovery_state("verified", "portable", None, {}, state_path)
        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        self.assertIsNotNone(pre_ai.consume_source_recovery_state(state_path))
        self.assertIsNone(pre_ai.consume_source_recovery_state(state_path))

    def test_corrupted_expansion_occurrence_state_is_rejected(self):
        state_path = Path(self.tempdir.name) / "corrupt-expansions.json"
        prepared = repair.prepare_repairs("Keep this sentence.")
        state = repair.build_state(
            prepared,
            framed_source=prepared.framed_source,
            verified_text=prepared.safe_source,
            portable_text=prepared.safe_source,
            file_nonce=None,
            expected_counts={"EXAMPLE": 1},
            prompt_config_digest="TEST",
        )
        state["expansion_occurrences"] = []
        pre_ai.record_source_recovery_state(
            prepared.safe_source,
            prepared.safe_source,
            None,
            {"EXAMPLE": 1},
            state_path,
            repair_state=state,
        )
        self.assertIsNone(pre_ai.consume_source_recovery_state(state_path))

    def test_stale_future_and_world_writable_state_are_rejected(self):
        state_path = Path(self.tempdir.name) / "state.json"
        base = {
            "version": 1, "created_at": time.time() - 121, "file_nonce": None,
            "expected_counts": {}, "verified_text": "a", "portable_text": "a",
        }
        for created, mode in (
            (time.time() - 121, 0o600),
            (time.time() + 2, 0o600),
            (time.time(), 0o622),
            (time.time(), 0o640),
        ):
            base["created_at"] = created
            state_path.write_text(json.dumps(base), encoding="utf-8")
            state_path.chmod(mode)
            self.assertIsNone(pre_ai.consume_source_recovery_state(state_path))

    def test_symlink_state_is_rejected_and_consumed(self):
        target = Path(self.tempdir.name) / "target.json"
        target.write_text("{}", encoding="utf-8")
        state_path = Path(self.tempdir.name) / "state.json"
        state_path.symlink_to(target)
        self.assertIsNone(pre_ai.consume_source_recovery_state(state_path))
        self.assertFalse(state_path.exists())

    def test_state_persistence_failure_emits_no_repair_regions(self):
        occupied = Path(self.tempdir.name) / "occupied"
        occupied.write_text("not a directory", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(occupied / "state.json"),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "slash.json"
                ),
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "pre_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input="Send it Friday. I mean Monday.",
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("[[SPK_REPAIR_", result.stdout)
        self.assertIn("I mean", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_state_persistence_failure_emits_no_unverifiable_literal_shield(self):
        occupied = Path(self.tempdir.name) / "literal-occupied"
        occupied.write_text("not a directory", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(occupied / "state.json"),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "literal-slash.json"
                ),
            }
        )
        source = "Write [[SPK_FAKE_TOKEN]] literally."
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pre_ai.py"), "--snippets", str(self.snippets)],
            input=source,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertEqual(result.stdout, source)
        self.assertNotIn("[[SPK_LITERAL_", result.stdout)

    def test_preprocessor_core_fallback_always_strips_trailing_whitespace(self):
        invalid = Path(self.tempdir.name) / "invalid-snippets.json"
        invalid.write_text("not-json", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(
                    Path(self.tempdir.name) / "fallback-source.json"
                ),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "fallback-slash.json"
                ),
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "pre_ai.py"),
                "--snippets",
                str(invalid),
            ],
            input="Keep this text.\n\t ",
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "Keep this text.")
        self.assertEqual(result.stderr, "")

    def test_damaged_model_region_falls_forward_with_exit_zero(self):
        state = Path(self.tempdir.name) / "source.json"
        slash = Path(self.tempdir.name) / "slash.json"
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(state),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(slash),
            }
        )
        source = "Send it Friday. I mean Monday."
        pre = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pre_ai.py"), "--snippets", str(self.snippets)],
            input=source,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        damaged = re.sub(r"\[\[SPK_REPAIR_1_END_[^\]]+\]\]", "", pre.stdout)
        post = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "post_ai.py"), "--snippets", str(self.snippets)],
            input=damaged + "\n\t ",
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(post.returncode, 0)
        self.assertEqual(post.stdout, source)
        self.assertEqual(post.stderr, "")
        self.assertFalse(post.stdout.endswith((" ", "\n", "\t", "\r")))

    def test_missing_state_never_leaks_repair_structure(self):
        environment = os.environ.copy()
        state = Path(self.tempdir.name) / "missing-source.json"
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(state),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "missing-slash.json"
                ),
            }
        )
        pre = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pre_ai.py"), "--snippets", str(self.snippets)],
            input="Use Friday. I mean Monday.",
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        state.unlink()
        post = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "post_ai.py"), "--snippets", str(self.snippets)],
            input=pre.stdout,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertNotIn("[[SPK_", post.stdout)
        self.assertTrue(post.stdout)

    def test_missing_state_never_leaks_malformed_internal_structure(self):
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(
                    Path(self.tempdir.name) / "absent-source.json"
                ),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "absent-slash.json"
                ),
            }
        )
        post = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "post_ai.py"), "--snippets", str(self.snippets)],
            input="Safe text [[SPK_REPAIR_UNCLOSED",
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertEqual(post.stdout, "Safe text")
        self.assertNotIn("[[SPK_", post.stdout)

    def test_semantic_command_fallback_never_leaks_internal_token(self):
        state = Path(self.tempdir.name) / "command-source.json"
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(state),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "command-slash.json"
                ),
            }
        )
        source = "Delete the last sentence."
        pre = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pre_ai.py"), "--snippets", str(self.snippets)],
            input=source,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertIn("SPK_CMD_DELETE_SENTENCE", pre.stdout)
        post = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "post_ai.py"), "--snippets", str(self.snippets)],
            input="Damaged output [[SPK_CMD_DELETE_SENTENCE]]",
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertEqual(post.stdout, source)
        self.assertNotIn("[[SPK_", post.stdout)

    def test_explicit_list_formatting_passes_semantic_validation(self):
        state = Path(self.tempdir.name) / "list-source.json"
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(state),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "list-slash.json"
                ),
            }
        )
        source = (
            "The priorities are speed, safety, and quality. "
            "Make those a list."
        )
        pre = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pre_ai.py"), "--snippets", str(self.snippets)],
            input=source,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertIn("SPK_CMD_BULLET_LIST", pre.stdout)
        model = "The priorities are:\n\n- Speed\n- Safety\n- Quality"
        post = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "post_ai.py"), "--snippets", str(self.snippets)],
            input=model,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertEqual(post.stdout, model)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old = os.environ.copy()
        os.environ["PARAQWEN_DIAGNOSTICS"] = "1"
        os.environ["PARAQWEN_DIAGNOSTIC_DIR"] = self.tempdir.name

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)
        self.tempdir.cleanup()

    def test_trace_is_private_redacted_and_has_all_stages(self):
        trace_id = diagnostics.new_trace_id()
        secret = "https://secret.example/private"
        diagnostics.write_trace(trace_id, stages={"raw": secret, "pre": "pre"}, expansion_values=[secret])
        diagnostics.write_trace(trace_id, stages={"model": "model", "post": "post"}, validators={"accepted": True})
        path = Path(self.tempdir.name) / f"{trace_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(data["stages"]), {"raw", "pre", "model", "post"})
        self.assertNotIn(secret, path.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_rotation_keeps_at_most_twenty_records(self):
        for _ in range(25):
            diagnostics.write_trace(diagnostics.new_trace_id(), stages={"raw": "x"})
        self.assertLessEqual(len(list(Path(self.tempdir.name).glob("*.json"))), 20)

    def test_rotation_removes_records_older_than_seven_days(self):
        old_trace = diagnostics.new_trace_id()
        diagnostics.write_trace(old_trace, stages={"raw": "old"})
        old_path = Path(self.tempdir.name) / f"{old_trace}.json"
        old_time = time.time() - diagnostics.MAX_AGE_SECONDS - 1
        os.utime(old_path, (old_time, old_time))
        diagnostics.write_trace(diagnostics.new_trace_id(), stages={"raw": "new"})
        self.assertFalse(old_path.exists())

    def test_metadata_and_validators_are_redacted_and_audio_is_omitted(self):
        trace_id = diagnostics.new_trace_id()
        secret = "PRIVATE EXPANSION"
        diagnostics.write_trace(
            trace_id,
            stages={"raw": "safe"},
            metadata={"nested": {"value": secret}, "audio_path": "/tmp/raw.wav"},
            validators={"detail": secret, "audio_bytes": b"private"},
            expansion_values=[secret],
        )
        record = json.loads(
            (Path(self.tempdir.name) / f"{trace_id}.json").read_text(encoding="utf-8")
        )
        serialized = json.dumps(record)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("raw.wav", serialized)
        self.assertEqual(record["metadata"]["audio_path"], "[OMITTED]")
        self.assertEqual(record["validators"]["audio_bytes"], "[OMITTED]")

    def test_disabled_mode_writes_nothing(self):
        os.environ["PARAQWEN_DIAGNOSTICS"] = "0"
        self.assertIsNone(diagnostics.new_trace_id())
        self.assertEqual(list(Path(self.tempdir.name).glob("*.json")), [])

    def test_symlinked_trace_record_is_not_followed(self):
        trace_id = "a" * 24
        outside = Path(self.tempdir.name).parent / "paraqwen-outside-trace.json"
        outside.write_text("untouched", encoding="utf-8")
        link = Path(self.tempdir.name) / f"{trace_id}.json"
        link.symlink_to(outside)
        try:
            diagnostics.write_trace(trace_id, stages={"raw": "private"})
            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")
        finally:
            outside.unlink(missing_ok=True)

    def test_entrypoints_redact_expansion_from_post_stage(self):
        config = Path(self.tempdir.name) / "snippets.json"
        secret = "PRIVATE EXPANSION VALUE"
        config.write_text(
            json.dumps(
                [{
                    "id": "PRIVATE_VALUE",
                    "triggers": ["insert private value"],
                    "text": secret,
                    "consume_trailing_punctuation": True,
                }]
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "PARAQWEN_DIAGNOSTICS": "1",
                "PARAQWEN_DIAGNOSTIC_DIR": self.tempdir.name,
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(
                    Path(self.tempdir.name) / "source.json"
                ),
                "SPOKENLY_SLASH_SNIPPET_STATE": str(
                    Path(self.tempdir.name) / "slash.json"
                ),
            }
        )
        command = [sys.executable, str(ROOT / "scripts" / "pre_ai.py"), "--snippets", str(config)]
        pre = subprocess.run(
            command,
            input="insert private value",
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        post = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "post_ai.py"), "--snippets", str(config)],
            input=pre.stdout,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertEqual(post.stdout, secret)
        traces = [
            path for path in Path(self.tempdir.name).glob("*.json")
            if path.name not in {"snippets.json", "source.json", "slash.json"}
        ]
        self.assertEqual(len(traces), 1)
        trace_text = traces[0].read_text(encoding="utf-8")
        self.assertNotIn(secret, trace_text)
        self.assertEqual(
            set(json.loads(trace_text)["stages"]), {"raw", "pre", "model", "post"}
        )


if __name__ == "__main__":
    unittest.main()
