import json
import re
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
        value = pre_ai.process(
            "The meeting is Friday. I mean Monday.", self.snippets
        )
        self.assertEqual(
            value, "The meeting is Friday. [[SPK_CMD_SELF_CORRECTION]] Monday."
        )

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
        value = pre_ai.process(
            "The meeting is at 3. No, actually 4.", self.snippets
        )
        self.assertEqual(
            value, "The meeting is at 3. [[SPK_CMD_SELF_CORRECTION]] 4."
        )

    def test_explanatory_i_mean_is_not_marked(self):
        value = pre_ai.process(
            "I mean that sincerely and without qualification.", self.snippets
        )
        self.assertNotIn("[[SPK_CMD_SELF_CORRECTION]]", value)

    def test_that_sentence_variant(self):
        value = pre_ai.process(
            "Keep this. Remove this. Delete that sentence. Continue.", self.snippets
        )
        self.assertEqual(value, "Keep this. Continue.")

    def test_snippet_trigger_tolerates_repeated_spaces(self):
        value = pre_ai.process(
            "Use insert   my email signature.", self.snippets
        )
        self.snippet_token(value, "EMAIL_SIGNATURE", 1)

    def test_delete_last_word(self):
        value = pre_ai.process("Keep this extra delete the last word now.", self.snippets)
        self.assertEqual(value, "Keep this now.")

    def test_delete_bounded_phrase(self):
        value = pre_ai.process(
            "Keep this, remove this phrase, delete the last phrase continue.",
            self.snippets,
        )
        self.assertEqual(value, "Keep this continue.")

    def test_new_paragraph_is_deterministic(self):
        value = pre_ai.process("First topic. New paragraph. Second topic.", self.snippets)
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
        self.assertFalse(post_ai.process(protected + "\n\t ", self.snippets).endswith("\n"))

    def test_trailing_whitespace_is_removed_without_snippets(self):
        self.assertEqual(post_ai.process("safe command\n\t ", self.snippets), "safe command")

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
        protected = pre_ai.process(
            "slash go i want to create everything", config
        )
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
        protected = pre_ai.process(
            "slash go i want to create everything", config
        )
        pre_ai.record_pending_prefix(protected, config, state)
        prefix = post_ai.consume_pending_prefix(state)
        final = post_ai.restore_pending_prefix(
            post_ai.process("I want to be able to create everything.", config),
            prefix,
        )
        self.assertEqual(final, "/goal I want to be able to create everything.")
        self.assertFalse(state.exists())

    def test_slash_goal_recovery_does_not_duplicate_preserved_prefix(self):
        self.assertEqual(
            post_ai.restore_pending_prefix("/goal Keep everything.", "/goal"),
            "/goal Keep everything.",
        )


if __name__ == "__main__":
    unittest.main()
