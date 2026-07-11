import json
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
            protected, "Please reply and [[SPK_SNIPPET_EMAIL_SIGNATURE__1]]"
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
        self.assertIn("[[SPK_SNIPPET_EMAIL_SIGNATURE__1]]", value)

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
        with self.assertRaisesRegex(ValueError, "unknown snippet token"):
            post_ai.process("[[SPK_SNIPPET_UNKNOWN__1]]", self.snippets)

    def test_duplicated_snippet_token_fails_closed(self):
        token = "[[SPK_SNIPPET_EMAIL_SIGNATURE__1]]"
        with self.assertRaisesRegex(ValueError, "duplicated snippet token"):
            post_ai.process(f"{token} {token}", self.snippets)

    def test_two_intentional_snippet_occurrences_are_distinct(self):
        protected = pre_ai.process(
            "insert my booking link and insert my booking link", self.snippets
        )
        self.assertIn("[[SPK_SNIPPET_BOOKING_LINK__1]]", protected)
        self.assertIn("[[SPK_SNIPPET_BOOKING_LINK__2]]", protected)
        expanded = post_ai.process(protected, self.snippets)
        self.assertEqual(
            expanded, "https://example.com/book and https://example.com/book"
        )


if __name__ == "__main__":
    unittest.main()
