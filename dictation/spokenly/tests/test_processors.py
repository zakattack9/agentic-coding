import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import post_ai  # noqa: E402
import pre_ai  # noqa: E402


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.snippets = Path(self.tempdir.name) / "snippets.json"
        self.snippets.write_text(
            json.dumps(
                [
                    {
                        "id": "EMAIL_SIGNATURE",
                        "triggers": ["insert my email signature"],
                        "text": "Best,\nExample Person",
                        "consume_trailing_punctuation": True,
                    },
                    {
                        "id": "BOOKING_LINK",
                        "triggers": ["insert my booking link"],
                        "text": "https://example.com/book",
                        "consume_trailing_punctuation": True,
                    },
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def snippet_token(self, protected, snippet_id, position):
        match = re.search(
            rf"\[\[SPK_SNIPPET_{snippet_id}__{position}__[A-F0-9]{{8}}\]\]",
            protected,
        )
        self.assertIsNotNone(match)
        return match.group(0)

    def assert_repair_protocol(self, value, repair_type="REPLACEMENT", count=1):
        self.assertNotIn("[[SPK_CMD_REPLACE_NEAREST]]", value)
        self.assertEqual(len(re.findall(r"\[\[SPK_REPAIR_\d+_START_", value)), count)
        self.assertEqual(len(re.findall(r"\[\[SPK_REPAIR_\d+_END_", value)), count)
        self.assertIn(f"_CUE_1_{repair_type}_", value)

    def test_deletes_previous_sentence(self):
        value = pre_ai.process(
            "Keep this. Remove this sentence. Delete the last sentence. Keep this too.",
            self.snippets,
        )
        self.assertEqual(value, "Keep this. Keep this too.")

    def test_reported_directive_is_preserved(self):
        value = pre_ai.process(
            'Write the phrase "delete the last sentence" in the guide.', self.snippets
        )
        self.assertIn("delete the last sentence", value.lower())

    def test_list_directive_becomes_control_token(self):
        value = pre_ai.process(
            "The priorities are speed, safety, and quality. Make those a list.",
            self.snippets,
        )
        self.assertIn("[[SPK_CMD_BULLET_LIST]]", value)
        self.assertNotIn("Make those a list", value)

    def test_correction_gets_hint(self):
        value = pre_ai.process("The meeting is Friday. I mean Monday.", self.snippets)
        self.assert_repair_protocol(value)
        self.assertIn("The meeting is Friday.", value)
        self.assertIn(" Monday.", value)

    def test_i_mean_can_correct_a_repeated_clause(self):
        value = pre_ai.process(
            "We should ship Friday, I mean we should ship Monday after review.",
            self.snippets,
        )
        self.assert_repair_protocol(value)

    def test_i_mean_can_correct_to_infinitive_phrase(self):
        value = pre_ai.process(
            "I want to send the old version, I mean to create the new version.",
            self.snippets,
        )
        self.assert_repair_protocol(value)

    def test_long_clear_i_mean_correction_gets_hint(self):
        value = pre_ai.process(
            "The meeting is Friday, I mean Monday morning at nine with the entire "
            "product and engineering team in the main conference room.",
            self.snippets,
        )
        self.assert_repair_protocol(value)

    def test_other_clear_repair_phrases_get_hints(self):
        cases = [
            "The meeting is Tuesday, or rather Thursday.",
            "The meeting is Tuesday. No, wait, Thursday.",
            "The meeting is Tuesday, actually Thursday.",
            "The meeting is Tuesday, correct that, Thursday.",
            "The meeting is Tuesday. What I meant was Thursday.",
        ]
        for transcript in cases:
            with self.subTest(transcript=transcript):
                value = pre_ai.process(transcript, self.snippets)
                expected = "RESTART" if "No, wait" in transcript else "REPLACEMENT"
                self.assert_repair_protocol(value, expected)

    def test_ambiguous_repair_words_are_not_marked(self):
        cases = [
            "I actually think Thursday is better.",
            "There is no reason to change the meeting.",
            "Sorry, I cannot attend the meeting.",
        ]
        for transcript in cases:
            with self.subTest(transcript=transcript):
                value = pre_ai.process(transcript, self.snippets)
                self.assertNotIn("[[SPK_REPAIR_", value)

    def test_snippet_is_protected_and_expanded_exactly(self):
        protected = pre_ai.process(
            "Please reply and insert my email signature.", self.snippets
        )
        self.assertEqual(
            protected,
            "[[SPK_SEGMENT_0_START]]Please reply and [[SPK_SEGMENT_0_END]]"
            f"{self.snippet_token(protected, 'EMAIL_SIGNATURE', 1)}"
            "[[SPK_SEGMENT_1_START_AFTER_EMAIL_SIGNATURE__7467D256]]"
            "[[SPK_SEGMENT_1_END]]",
        )
        expanded = post_ai.process(protected, self.snippets)
        self.assertEqual(expanded, "Please reply and Best,\nExample Person")

    def test_multiple_snippets(self):
        protected = pre_ai.process(
            "Use insert my booking link and insert my email signature.", self.snippets
        )
        expanded = post_ai.process(protected, self.snippets)
        self.assertIn("https://example.com/book", expanded)
        self.assertIn("Best,\nExample Person", expanded)

    def test_entrypoint_recovers_static_snippet_when_model_drops_all_frames(self):
        recovery_state = Path(self.tempdir.name) / "source-recovery.json"
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_SOURCE_RECOVERY_STATE": str(recovery_state),
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(
                    Path(self.tempdir.name) / "diagnostics.log"
                ),
            }
        )
        source = "Please reply and insert my email signature."
        pre = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "pre_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input=source,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(pre.returncode, 0, pre.stderr)
        post = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "post_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input="Please reply.",
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(post.stdout, "Please reply and Best,\nExample Person")

    def test_unresolved_control_token_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unresolved internal token"):
            post_ai.process("Text [[SPK_CMD_BULLET_LIST]]", self.snippets)

    def test_numbered_list_and_paragraph_commands(self):
        value = pre_ai.process(
            "First paragraph. New paragraph. The steps are install, test, and ship. "
            "Format as a numbered list.",
            self.snippets,
        )
        self.assertIn("First paragraph.\n\nThe steps", value)
        self.assertIn("[[SPK_CMD_NUMBERED_LIST]]", value)

    def test_delete_previous_word(self):
        value = pre_ai.process(
            "The release is Tuesday Wednesday. Delete the last word. Friday.",
            self.snippets,
        )
        self.assertEqual(value, "The release is Tuesday Friday.")

    def test_no_actually_gets_correction_hint(self):
        value = pre_ai.process("The meeting is at 3. No, actually 4.", self.snippets)
        self.assert_repair_protocol(value)
        self.assertIn("The meeting is at 3.", value)
        self.assertIn(" 4.", value)

    def test_explanatory_i_mean_is_not_marked(self):
        value = pre_ai.process(
            "I mean that sincerely and without qualification.", self.snippets
        )
        self.assertNotIn("[[SPK_REPAIR_", value)

    def test_reported_explicit_correction_is_preserved(self):
        cases = [
            'Write the phrase "no, actually" in the guide.',
            "Write the phrase no, actually in the guide.",
            "Type the example or rather into the document.",
        ]
        for transcript in cases:
            with self.subTest(transcript=transcript):
                value = pre_ai.process(transcript, self.snippets)
                self.assertNotIn("[[SPK_REPAIR_", value)

    def test_sentence_boundary_correction_is_scoped_as_replacement(self):
        value = pre_ai.process(
            "Tomorrow I want to send the onboarding guide to the sales team. "
            "I mean the support team.",
            self.snippets,
        )
        self.assert_repair_protocol(value)
        self.assertIn("the sales team.", value)
        self.assertIn(" the support team.", value)

    def test_that_sentence_variant(self):
        value = pre_ai.process(
            "Keep this. Remove this. Delete that sentence. Continue.", self.snippets
        )
        self.assertEqual(value, "Keep this. Continue.")

    def test_snippet_trigger_tolerates_repeated_spaces(self):
        value = pre_ai.process("Use insert   my email signature.", self.snippets)
        self.snippet_token(value, "EMAIL_SIGNATURE", 1)

    def test_delete_last_word(self):
        value = pre_ai.process(
            "Keep this extra delete the last word now.", self.snippets
        )
        self.assertEqual(value, "Keep this now.")

    def test_scratch_word_deletes_previous_word(self):
        value = pre_ai.process("Keep this extra scratch word now.", self.snippets)
        self.assertEqual(value, "Keep this now.")

    def test_delete_that_discards_previous_utterance(self):
        value = pre_ai.process(
            "Keep this. Remove this. Delete that. Continue.", self.snippets
        )
        self.assertEqual(value, "Keep this. Continue.")

    def test_delete_that_inside_sentence_is_not_a_directive(self):
        value = pre_ai.process(
            "We should delete that file after review.", self.snippets
        )
        self.assertEqual(value, "We should delete that file after review.")

    def test_delete_bounded_phrase(self):
        value = pre_ai.process(
            "Keep this, remove this phrase, delete the last phrase continue.",
            self.snippets,
        )
        self.assertEqual(value, "Keep this continue.")

    def test_new_paragraph_is_deterministic(self):
        value = pre_ai.process(
            "First topic. New paragraph. Second topic.", self.snippets
        )
        self.assertEqual(value, "First topic.\n\nSecond topic.")

    def test_unknown_snippet_fails_closed(self):
        protected = (
            "[[SPK_SEGMENT_0_START]]Text [[SPK_SEGMENT_0_END]]"
            f"[[SPK_SNIPPET_UNKNOWN__1__{pre_ai.snippet_checksum('UNKNOWN', 1)}]]"
            "[[SPK_SEGMENT_1_START_AFTER_UNKNOWN__"
            f"{pre_ai.snippet_checksum('UNKNOWN', 1)}]][[SPK_SEGMENT_1_END]]"
        )
        with self.assertRaisesRegex(ValueError, "unknown snippet token"):
            post_ai.process(protected, self.snippets)

    def test_duplicated_snippet_token_fails_closed(self):
        protected = pre_ai.process("insert my email signature", self.snippets)
        token = self.snippet_token(protected, "EMAIL_SIGNATURE", 1)
        with self.assertRaisesRegex(ValueError, "duplicated snippet position"):
            post_ai.process(f"{protected}{token}", self.snippets)

    def test_two_intentional_snippet_occurrences_are_distinct(self):
        protected = pre_ai.process(
            "insert my booking link and insert my booking link", self.snippets
        )
        self.snippet_token(protected, "BOOKING_LINK", 1)
        self.snippet_token(protected, "BOOKING_LINK", 2)
        expanded = post_ai.process(protected, self.snippets)
        self.assertEqual(
            expanded, "https://example.com/book and https://example.com/book"
        )

    def test_moved_snippet_is_restored_to_original_slot(self):
        protected = pre_ai.process(
            "Before insert my booking link after.", self.snippets
        )
        token = self.snippet_token(protected, "BOOKING_LINK", 1)
        moved = protected.replace(token, "") + token
        self.assertEqual(
            post_ai.process(moved, self.snippets),
            "Before https://example.com/book after.",
        )

    def test_final_snippet_is_expanded(self):
        protected = pre_ai.process(
            "Please use insert my email signature.", self.snippets
        )
        self.assertEqual(
            post_ai.process(protected, self.snippets),
            "Please use Best,\nExample Person",
        )

    def test_missing_standalone_snippet_is_recovered_from_segment(self):
        protected = pre_ai.process("Use insert my booking link now.", self.snippets)
        token = self.snippet_token(protected, "BOOKING_LINK", 1)
        damaged = protected.replace(token, "")
        self.assertEqual(
            post_ai.process(damaged, self.snippets),
            "Use https://example.com/book now.",
        )

    def test_text_outside_frames_fails_closed(self):
        protected = pre_ai.process("Use insert my booking link now.", self.snippets)
        with self.assertRaisesRegex(ValueError, "unexpected text outside"):
            post_ai.process(protected + " invented text", self.snippets)

    def test_trailing_whitespace_is_removed_after_expansion(self):
        protected = pre_ai.process("insert my email signature", self.snippets)
        self.assertFalse(
            post_ai.process(protected + "\n\t ", self.snippets).endswith("\n")
        )

    def test_trailing_whitespace_is_removed_without_snippets(self):
        self.assertEqual(
            post_ai.process("safe command\n\t ", self.snippets), "safe command"
        )

    def test_post_ai_consumes_punctuation_added_after_final_snippet(self):
        protected = pre_ai.process("insert my email signature", self.snippets)
        model_output = protected.replace(
            "[[SPK_SEGMENT_1_END]]", ".[[SPK_SEGMENT_1_END]]"
        )
        self.assertEqual(
            post_ai.process(model_output, self.snippets),
            "Best,\nExample Person",
        )

    def test_post_ai_consumes_spaced_punctuation_after_middle_snippet(self):
        protected = pre_ai.process(
            "Use insert my booking link then continue", self.snippets
        )
        model_output = protected.replace(
            " then continue[[SPK_SEGMENT_1_END]]",
            " . Then continue[[SPK_SEGMENT_1_END]]",
        )
        self.assertEqual(
            post_ai.process(model_output, self.snippets),
            "Use https://example.com/book Then continue",
        )

    def test_post_ai_preserves_punctuation_when_consumption_is_disabled(self):
        config = Path(self.tempdir.name) / "punctuation-snippets.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "id": "LABEL",
                        "triggers": ["insert my label"],
                        "text": "Label",
                        "consume_trailing_punctuation": False,
                    }
                ]
            ),
            encoding="utf-8",
        )
        protected = pre_ai.process("insert my label then continue", config)
        model_output = protected.replace(
            " then continue[[SPK_SEGMENT_1_END]]",
            ". Then continue[[SPK_SEGMENT_1_END]]",
        )
        self.assertEqual(
            post_ai.process(model_output, config),
            "Label. Then continue",
        )

    def test_unframed_snippet_fails_closed(self):
        token = (
            "[[SPK_SNIPPET_BOOKING_LINK__1__"
            f"{pre_ai.snippet_checksum('BOOKING_LINK', 1)}]]"
        )
        with self.assertRaisesRegex(ValueError, "unframed snippet token"):
            post_ai.process(token, self.snippets)

    def test_mixed_snippets_use_textual_positions(self):
        protected = pre_ai.process(
            "insert my email signature then insert my booking link", self.snippets
        )
        self.snippet_token(protected, "EMAIL_SIGNATURE", 1)
        self.snippet_token(protected, "BOOKING_LINK", 2)

    def test_modified_snippet_identity_fails_checksum(self):
        protected = pre_ai.process("insert my email signature", self.snippets)
        damaged = protected.replace("EMAIL_SIGNATURE", "BOOKING_LINK")
        with self.assertRaisesRegex(ValueError, "invalid snippet metadata checksum"):
            post_ai.process(damaged, self.snippets)

    def test_slash_goal_survives_dropped_token_and_trimmed_segment(self):
        config = Path(self.tempdir.name) / "slash-snippets.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "id": "SLASH_GOAL",
                        "triggers": ["slash goal", "slash go"],
                        "text": "/goal",
                        "consume_trailing_punctuation": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        protected = pre_ai.process("slash go i want to create everything", config)
        token = self.snippet_token(protected, "SLASH_GOAL", 1)
        model_output = protected.replace(token, "").replace(
            " i want to create everything", "I want to be able to create everything."
        )
        self.assertEqual(
            post_ai.process(model_output, config),
            "/goal I want to be able to create everything.",
        )

    def test_slash_goal_survives_all_markers_being_removed(self):
        config = Path(self.tempdir.name) / "slash-state-snippets.json"
        state = Path(self.tempdir.name) / "pending-prefix.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "id": "SLASH_GOAL",
                        "triggers": ["slash goal", "slash go"],
                        "text": "/goal",
                        "consume_trailing_punctuation": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        protected = pre_ai.process("slash go i want to create everything", config)
        pre_ai.record_pending_slash_commands(protected, config, state)
        commands = post_ai.consume_pending_slash_commands(state)
        final = post_ai.restore_pending_slash_commands(
            post_ai.process("I want to be able to create everything.", config),
            commands,
        )
        self.assertEqual(final, "/goal I want to be able to create everything.")
        self.assertFalse(state.exists())

    def test_slash_goal_recovery_does_not_duplicate_preserved_prefix(self):
        self.assertEqual(
            post_ai.restore_pending_slash_commands(
                "/goal Keep everything.",
                [
                    {
                        "text": "/goal",
                        "leading": True,
                        "consume_trailing_punctuation": True,
                    }
                ],
            ),
            "/goal Keep everything.",
        )

    def test_recovered_slash_command_consumes_added_punctuation(self):
        commands = [
            {
                "text": "/goal",
                "leading": True,
                "consume_trailing_punctuation": True,
            }
        ]
        self.assertEqual(
            post_ai.restore_pending_slash_commands("/goal. Continue.", commands),
            "/goal Continue.",
        )
        commands[0]["leading"] = False
        self.assertEqual(
            post_ai.restore_pending_slash_commands("Use /. Continue.", commands),
            "Use /goal Continue.",
        )

    def test_slash_recovery_ignores_unrelated_longer_command(self):
        commands = [
            {
                "text": "/goal",
                "leading": False,
                "consume_trailing_punctuation": True,
            }
        ]
        self.assertEqual(
            post_ai.restore_pending_slash_commands("Keep /goalkeeper and /.", commands),
            "Keep /goalkeeper and /goal",
        )

    def test_missing_middle_slash_command_fails_closed(self):
        commands = [
            {
                "text": "/spec-ops:refine-spec",
                "leading": False,
                "consume_trailing_punctuation": True,
            }
        ]
        with self.assertRaisesRegex(ValueError, "missing recoverable slash command"):
            post_ai.restore_pending_slash_commands(
                "Refine the spec without a placeholder.", commands
            )

    def test_leftover_normalized_slash_alias_is_removed(self):
        commands = [
            {
                "text": "/goal",
                "leading": True,
                "consume_trailing_punctuation": False,
            },
            {
                "text": "/spec-ops:refine-spec",
                "leading": False,
                "consume_trailing_punctuation": False,
            },
            {
                "text": "/spec-ops:launch-spec",
                "leading": False,
                "consume_trailing_punctuation": False,
            },
            {
                "text": "/spec-ops:verify-spec",
                "leading": False,
                "consume_trailing_punctuation": False,
            },
        ]
        model_output = (
            "/goal, we will refactor everything using the "
            "/spec-ops:refine-spec, then run /spec-ops:launch-spec. After "
            "implementation, verify using /spec-ops:verify-spec, and a human "
            "will review/spec_ops_verify_spec"
        )
        self.assertEqual(
            post_ai.restore_pending_slash_commands(model_output, commands),
            "/goal, we will refactor everything using the "
            "/spec-ops:refine-spec, then run /spec-ops:launch-spec. After "
            "implementation, verify using /spec-ops:verify-spec, and a human "
            "will review",
        )

    def test_validated_slash_output_is_not_mutated_after_validation(self):
        commands = [
            {
                "text": "/spec-ops:verify-spec",
                "leading": False,
                "consume_trailing_punctuation": False,
            }
        ]
        source = (
            "Keep the literal /spec_ops_verify_spec and then run "
            "/spec-ops:verify-spec"
        )
        self.assertEqual(
            post_ai.restore_pending_slash_commands(
                source, commands, structurally_validated=True
            ),
            source,
        )

    def test_invalid_recovery_state_path_does_not_crash_processors(self):
        config = Path(self.tempdir.name) / "state-snippets.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "id": "SLASH_GOAL",
                        "triggers": ["slash goal"],
                        "text": "/goal",
                        "consume_trailing_punctuation": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        invalid_parent = Path(self.tempdir.name) / "not-a-directory"
        invalid_parent.write_text("occupied", encoding="utf-8")
        state = invalid_parent / "state.json"
        protected = pre_ai.process("slash goal do the work", config)
        pre_ai.clear_pending_slash_commands(state)
        pre_ai.record_pending_slash_commands(protected, config, state)
        self.assertEqual(post_ai.consume_pending_slash_commands(state), [])

    def test_all_slash_commands_are_restored_from_bare_placeholders(self):
        config = Path(self.tempdir.name) / "slash-command-snippets.json"
        state = Path(self.tempdir.name) / "pending-commands.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "id": "SLASH_GOAL",
                        "triggers": ["slash goal"],
                        "text": "/goal",
                        "consume_trailing_punctuation": True,
                    },
                    {
                        "id": "SPEC_OPS_REFINE_SPEC",
                        "triggers": ["slash refine spec"],
                        "text": "/spec-ops:refine-spec",
                        "consume_trailing_punctuation": True,
                    },
                    {
                        "id": "SPEC_OPS_LAUNCH_SPEC",
                        "triggers": ["slash launch spec"],
                        "text": "/spec-ops:launch-spec",
                        "consume_trailing_punctuation": True,
                    },
                ]
            ),
            encoding="utf-8",
        )
        source = (
            "slash goal perform a comprehensive review of the spec and all the code "
            "then use slash refine spec to refine the spec until everything is "
            "completed finally you will run slash launch spec to produce the final prompt"
        )
        protected = pre_ai.process(source, config)
        pre_ai.record_pending_slash_commands(protected, config, state)
        commands = post_ai.consume_pending_slash_commands(state)
        model_output = (
            "/goal perform a comprehensive review of the spec and all the code then "
            "use / to refine the spec until everything is completed. Finally, you "
            "will run / to produce the final prompt"
        )
        self.assertEqual(
            post_ai.restore_pending_slash_commands(model_output, commands),
            "/goal perform a comprehensive review of the spec and all the code then "
            "use /spec-ops:refine-spec to refine the spec until everything is "
            "completed. Finally, you will run /spec-ops:launch-spec to produce the "
            "final prompt",
        )

        shifted_model_output = (
            "perform a comprehensive review of the spec and all the code then use / "
            "to refine the spec until everything is completed. Finally you will run "
            "/ to produce the final prompt."
        )
        self.assertEqual(
            post_ai.restore_pending_slash_commands(shifted_model_output, commands),
            "/goal perform a comprehensive review of the spec and all the code then "
            "use /spec-ops:refine-spec to refine the spec until everything is "
            "completed. Finally you will run /spec-ops:launch-spec to produce the "
            "final prompt.",
        )

        rewritten_model_output = (
            "/goal perform a comprehensive review of the spec and all the code. Then "
            "use /goal to refine the spec until everything is completed. Finally, "
            "you will run /spec_ops_refine_spec to produce the final output."
        )
        self.assertEqual(
            post_ai.restore_pending_slash_commands(rewritten_model_output, commands),
            "/goal perform a comprehensive review of the spec and all the code. Then "
            "use /spec-ops:refine-spec to refine the spec until everything is "
            "completed. Finally, you will run /spec-ops:launch-spec to produce the "
            "final output.",
        )

        missing_model_output = (
            "/goal perform a comprehensive review of the spec and all the code. Then "
            "use to refine the spec until everything is completed. Finally, you will "
            "run to produce the final prompt."
        )
        self.assertEqual(
            post_ai.restore_pending_slash_commands(missing_model_output, commands),
            "/goal perform a comprehensive review of the spec and all the code. Then "
            "use /spec-ops:refine-spec to refine the spec until everything is "
            "completed. Finally, you will run /spec-ops:launch-spec to produce the "
            "final prompt.",
        )


if __name__ == "__main__":
    unittest.main()
