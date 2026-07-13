#!/usr/bin/env python3
"""Typed, bounded self-repair protocol for ParaQwen Dictation.

This module is intentionally independent of Spokenly, macOS, iTerm2, and the
optional file-reference plugin.  Pre-AI uses it to plan and frame repairs;
Post-AI uses the persisted manifest to validate the single model response.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
import hashlib
import json
import os
import re
import secrets
import time
from typing import Iterable, Sequence


SCHEMA_VERSION = 2
MAX_REGION_CHARACTERS = 2400
TOKEN_NAMESPACE = re.compile(r"\[\[(?:SPK|PARAQWEN)_[^\]\n]*\]\]")
INTERNAL_TOKEN_PREFIX = re.compile(r"\[\[(?:SPK|PARAQWEN)_")
INTERNAL_LIKE_TOKEN = re.compile(
    r"\[\[(?:SPK|PARAQWEN)_[^\n]*?(?:\]\]|(?=\n|$))", re.MULTILINE
)
REPAIR_TOKEN = re.compile(r"\[\[SPK_REPAIR_[^\]\n]+\]\]")
SEMANTIC_COMMAND_TOKEN = re.compile(r"\[\[SPK_CMD_[A-Z0-9_]+\]\]")
LITERAL_TOKEN = re.compile(
    r"\[\[SPK_LITERAL_([1-9][0-9]*)__([A-F0-9]{16})__([A-F0-9]{8})\]\]"
)

# The longer and more specific forms must win at the same source position.
CUE_PATTERN = re.compile(
    r"\b(?:"
    r"sorry\s*,?\s*i\s+(?:mean|meant)|"
    r"oops\s*,?\s*i\s+(?:mean|meant)|"
    r"what\s+i\s+(?:really\s+)?meant\s+(?:was|is)|"
    r"let\s+me\s+(?:start\s+over|rephrase|correct\s+that)|"
    r"i\s+should\s+say|"
    r"no\s*,?\s*(?:actually|wait)|"
    r"no|"
    r"make\s+that|"
    r"or\s+rather|"
    r"i\s+(?:mean|meant)|"
    r"scratch\s+that|never\s*mind(?:\s+that)?|forget\s+that|"
    r"correct\s+that|correction(?:\s+is)?|"
    r"actually"
    r")\b",
    re.IGNORECASE,
)
RESTART_CUE = re.compile(
    r"^(?:let\s+me\s+(?:start\s+over|rephrase)|no\s*,?\s*(?:wait|tell\s+me))$",
    re.IGNORECASE,
)
DISCARD_CUE = re.compile(
    r"^(?:scratch\s+that|never\s*mind(?:\s+that)?|forget\s+that)$",
    re.IGNORECASE,
)
ADDITIVE_START = re.compile(
    r"^(?:also\b|and\b|plus\b|include\b|add\b|as\s+well\b|in\s+addition\b)",
    re.IGNORECASE,
)
REPORTING_PREFIX = re.compile(
    r"\b(?:say|write|type|read|quote|mention|discuss|explain)\s+"
    r"(?:(?:the|this|a)\s+)?(?:phrase|command|instruction|words?|example)\b"
    r"[^.!?\n]{0,160}$",
    re.IGNORECASE,
)
EXPLICIT_LITERAL_PREFIX = re.compile(
    r"\b(?:literal(?:ly)?|verbatim|exact(?:\s+text|ly)?|the\s+command\s+is)\b"
    r"[^.!?\n]{0,120}$",
    re.IGNORECASE,
)
REPORTED_LITERAL_PREFIX = re.compile(
    r"\b(?:(?:the\s+)?(?:example|instruction|guide|test)\s+"
    r"(?:says?|reads?|contains?)|(?:he|she|they)\s+(?:said|wrote|asked))\b"
    r"[^.!?\n]{0,140}$",
    re.IGNORECASE,
)

WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
ALIGNMENT_TOKEN = re.compile(
    r"-?\d+(?:\.\d+)?(?:%|ms|s|m|h|kb|mb|gb)?|"
    r"[^\W_]+(?:[-'][^\W_]+)*",
    re.IGNORECASE | re.UNICODE,
)
NUMBER_WORD_ATOM = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|million|billion"
)
SINGLE_WORD_REPEAT = re.compile(
    r"(?<!\w)([^\W_]+(?:[-'][^\W_]+)*)\s*[,]?\s+\1(?!\w)",
    re.IGNORECASE | re.UNICODE,
)
PROTECTED_PATTERNS = (
    ("url", re.compile(r"\b(?:https?|ssh|git)://[^\s<>()]+", re.IGNORECASE)),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("at_reference", re.compile(r"(?<!\w)@(?:\.\.?/)?[^\s,;:!?()]+")),
    ("path", re.compile(r"(?<!\w)(?:~|\.{1,2}|/)?(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+")),
    ("slash_command", re.compile(r"(?<!\w)/(?:[A-Za-z][A-Za-z0-9_-]*)(?::[A-Za-z][A-Za-z0-9_-]*)?")),
    ("filename", re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_.-]*\.[A-Za-z][A-Za-z0-9]{0,19}\b")),
    ("version", re.compile(r"\bv?\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?\b", re.IGNORECASE)),
    ("time", re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]m)?\b", re.IGNORECASE)),
    ("date", re.compile(r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4})\b")),
    ("hash", re.compile(r"\b(?:[a-f0-9]{7,64})\b", re.IGNORECASE)),
    ("number", re.compile(
        r"(?<![\w.])-?\d+(?:\.\d+)?(?:%|ms|s|m|h|kb|mb|gb)?(?!\w)(?!\.\d)",
        re.IGNORECASE,
    )),
    ("number", re.compile(
        rf"\b(?:{NUMBER_WORD_ATOM})(?:[- ]+(?:(?:and)[- ]+)?(?:{NUMBER_WORD_ATOM}))+\b",
        re.IGNORECASE,
    )),
    ("number", re.compile(
        r"\b(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
        r"(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|"
        r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
        r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)\b",
        re.IGNORECASE,
    )),
    ("identifier", re.compile(
        r"\b(?:"
        r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|"
        r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+|"
        r"[a-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*|"
        r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+|"
        r"[A-Z]{2,}[A-Za-z0-9]*|"
        r"[A-Z][A-Z0-9_]{2,}"
        r")\b"
    )),
)

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
NUMBER_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
FUNCTION_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
    "from", "has", "have", "he", "her", "his", "i", "in", "is", "it",
    "its", "me", "my", "of", "on", "or", "our", "she", "that", "the",
    "their", "them", "they", "this", "to", "was", "we", "were", "with",
    "you", "your",
}
GROUNDING_INSERTION_WORDS = {"a", "an", "the"}
INFLECTION_EQUIVALENTS = {
    "am": "be", "are": "be", "is": "be", "was": "be", "were": "be",
    "been": "be", "being": "be", "has": "have", "had": "have",
    "does": "do", "did": "do",
}


class TriggerSpan:
    __slots__ = ("start", "end", "snippet_id", "trigger")

    def __init__(self, start: int, end: int, snippet_id: str, trigger: str):
        self.start = start
        self.end = end
        self.snippet_id = snippet_id
        self.trigger = trigger


class PreparedRepairs:
    __slots__ = (
        "raw_source", "safe_source", "framed_source", "nonce", "regions",
        "literal_shields", "ambiguous_spans", "deterministic_edits",
        "validation_source",
    )

    def __init__(
        self,
        raw_source: str,
        safe_source: str,
        framed_source: str,
        nonce: str | None,
        regions: list[dict[str, object]],
        literal_shields: list[dict[str, object]],
        ambiguous_spans: list[str],
        deterministic_edits: list[dict[str, object]],
    ):
        self.raw_source = raw_source
        self.safe_source = safe_source
        self.framed_source = framed_source
        self.nonce = nonce
        self.regions = regions
        self.literal_shields = literal_shields
        self.ambiguous_spans = ambiguous_spans
        self.deterministic_edits = deterministic_edits
        self.validation_source = safe_source

    @property
    def has_model_regions(self) -> bool:
        return bool(self.regions and self.nonce)

    def manifest(self) -> dict[str, object]:
        return {
            "repair_schema": SCHEMA_VERSION,
            "repair_nonce": self.nonce,
            "repair_regions": self.regions,
            "literal_shields": self.literal_shields,
            "ambiguous_spans": self.ambiguous_spans,
            "deterministic_edits": self.deterministic_edits,
        }


class RepairValidationError(ValueError):
    """The one model output cannot be trusted for semantic insertion."""


def _digest(*parts: object, size: int = 4) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.blake2s(payload, digest_size=size).hexdigest().upper()


def literal_spans(text: str) -> list[tuple[int, int]]:
    """Return balanced quoted and explicit/reporting literal spans."""
    spans: list[tuple[int, int]] = []
    pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
    index = 0
    while index < len(text):
        opener = text[index]
        closer = pairs.get(opener)
        if closer is None or (opener == "'" and index and text[index - 1].isalnum()):
            index += 1
            continue
        end = text.find(closer, index + 1)
        if end >= 0:
            spans.append((index, end + 1))
            index = end + 1
        else:
            # An unclosed quote is uncertain literal content. Preserving the
            # remainder is safer than treating a cue inside it as destructive.
            spans.append((index, len(text)))
            break

    for match in re.finditer(r"[^.!?\n]*(?:[.!?]|$)", text):
        sentence = match.group(0)
        cue = CUE_PATTERN.search(sentence)
        if cue and (
            REPORTING_PREFIX.search(sentence[: cue.start()])
            or EXPLICIT_LITERAL_PREFIX.search(sentence[: cue.start()])
            or REPORTED_LITERAL_PREFIX.search(sentence[: cue.start()])
        ):
            spans.append((match.start(), match.end()))
    return _merge_ranges(spans)


def _inside(spans: Sequence[tuple[int, int]], position: int) -> bool:
    if not spans:
        return False
    index = bisect_right(spans, (position, float("inf"))) - 1
    return index >= 0 and spans[index][0] <= position < spans[index][1]


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def deterministic_protected_repairs(
    text: str, trigger_spans: Sequence[TriggerSpan]
) -> tuple[str, list[dict[str, object]]]:
    """Remove proven trigger-to-trigger alternatives before slot protection."""
    if len(trigger_spans) < 2:
        return text, []
    literal = literal_spans(text)
    removals: list[tuple[int, int]] = []
    edits: list[dict[str, object]] = []
    cues = [m for m in CUE_PATTERN.finditer(text) if not _inside(literal, m.start())]
    trigger_starts = [span.start for span in trigger_spans]
    trigger_ends = [span.end for span in trigger_spans]
    for cue in cues:
        left_index = bisect_right(trigger_ends, cue.start()) - 1
        right_index = bisect_left(trigger_starts, cue.end())
        if left_index < 0 or right_index >= len(trigger_spans):
            continue
        left, right = trigger_spans[left_index], trigger_spans[right_index]
        # Only punctuation/whitespace may separate the protected alternatives.
        if not re.fullmatch(r"[\s,.;:!?()\-–—]*", text[left.end : cue.start()]):
            continue
        if not re.fullmatch(r"[\s,.;:!?()\-–—]*", text[cue.end() : right.start]):
            continue
        if left.snippet_id == right.snippet_id and left.trigger.casefold() == right.trigger.casefold():
            continue
        removals.append((left.start, right.start))
        edits.append({
            "type": "protected_replacement",
            "removed": text[left.start : right.start],
            "retained_id": right.snippet_id,
            "source_start": left.start,
            "source_end": right.start,
        })
    merged = _merge_ranges(removals)
    if not merged:
        return text, []
    result = text
    for start, end in reversed(merged):
        result = result[:start] + result[end:]
    return _clean_edit_punctuation(result), edits


def deterministic_exact_repetitions(
    text: str, protected_spans: Sequence[tuple[int, int]] = ()
) -> tuple[str, list[dict[str, object]]]:
    """Remove only exact adjacent repeated phrases of two or more words."""
    pattern = re.compile(
        r"(?<!\w)(?P<phrase>[^\W_]+(?:[-'][^\W_]+)*(?:\s+[^\W_]+(?:[-'][^\W_]+)*){1,5})"
        r"\s*[,;:]\s*(?P=phrase)(?!\w)",
        re.IGNORECASE | re.UNICODE,
    )
    edits: list[dict[str, object]] = []
    protected = literal_spans(text)
    matches = [
        match
        for match in pattern.finditer(text)
        if not _inside(protected, match.start())
        and not any(
            match.start() < end and match.end() > start
            for start, end in protected_spans
        )
    ]
    result = text
    for match in reversed(matches):
        phrase = match.group("phrase")
        # Preserve common deliberate emphasis even if it has two words.
        words = [w.casefold() for w in WORD.findall(phrase)]
        if len(set(words)) == 1 or words[-1] in {"very", "really"}:
            continue
        # A complete phrase repeated for emphasis is ambiguous.  A repeated
        # fragment followed by new local wording is stronger evidence that the
        # speaker restarted the phrase and then continued it.
        local_tail = re.match(r"[^.!?\n]*", result[match.end() :])
        if local_tail is None or not WORD.search(local_tail.group(0)):
            continue
        edits.append({
            "type": "exact_repetition",
            "removed": result[match.start() : match.start("phrase") + len(phrase)],
            "retained": phrase,
            "source_start": match.start(),
            "source_end": match.end(),
        })
        result = result[: match.start()] + phrase + result[match.end() :]
    edits.reverse()
    return _clean_edit_punctuation(result), edits


def _clean_edit_punctuation(text: str) -> str:
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:]){2,}", r"\1", text)
    text = re.sub(r"(?<!\n)[ \t]{2,}", " ", text)
    return text.strip()


def _paragraph_bounds(text: str, position: int) -> tuple[int, int]:
    start = text.rfind("\n\n", 0, position)
    end = text.find("\n\n", position)
    return (0 if start < 0 else start + 2, len(text) if end < 0 else end)


def _replacement_bounds(text: str, cue: re.Match[str]) -> tuple[int, int]:
    paragraph_start, paragraph_end = _paragraph_bounds(text, cue.start())
    prefix = text[paragraph_start : cue.start()]
    # Prefer the current/previous sentence.  Keep question/exclamation ownership.
    sentence_marks = list(re.finditer(r"[.!?](?:[\"”’')\]]*)\s+", prefix))
    if sentence_marks:
        current_prefix = prefix[sentence_marks[-1].end() :].strip()
        if current_prefix:
            local_start = sentence_marks[-1].end()
        else:
            local_start = sentence_marks[-2].end() if len(sentence_marks) > 1 else 0
    else:
        local_start = 0
    start = paragraph_start + local_start
    suffix = text[cue.end() : paragraph_end]
    lead = re.match(r"[\s,;:\-–—]*[.!?]?[\s]*", suffix)
    repair_offset = lead.end() if lead else 0
    stop = re.search(
        r"[.!?](?:[\"”’')\]]*)(?=\s|$)", suffix[repair_offset:]
    )
    end = cue.end() + repair_offset + (
        stop.end() if stop else len(suffix) - repair_offset
    )
    return start, end


def _restart_bounds(text: str, cue: re.Match[str]) -> tuple[int, int]:
    paragraph_start, paragraph_end = _paragraph_bounds(text, cue.start())
    prefix = text[paragraph_start : cue.start()]
    marks = list(re.finditer(r"[.!?](?:[\"”’')\]]*)\s+", prefix))
    # Include the immediately preceding abandoned sentence. With one boundary
    # that means the paragraph start; with several, begin after the prior one.
    if marks and prefix[marks[-1].end() :].strip():
        local_start = marks[-1].end()
    else:
        local_start = marks[-2].end() if len(marks) > 1 else 0
    start = paragraph_start + local_start
    suffix = text[cue.end() : paragraph_end]
    lead = re.match(r"[\s,;:\-–—]*[.!?]?[\s]*", suffix)
    repair_offset = lead.end() if lead else 0
    stop = re.search(
        r"[.!?](?:[\"”’')\]]*)(?=\s|$)", suffix[repair_offset:]
    )
    end = cue.end() + repair_offset + (
        stop.end() if stop else len(suffix) - repair_offset
    )
    return start, end


def _suffix_after_cue(text: str, cue: re.Match[str], end: int) -> str:
    return text[cue.end() : end].lstrip(" \t,;:-–—.?!\n")


def _looks_natural_or_ambiguous(text: str, cue: re.Match[str], end: int) -> bool:
    prefix = text[: cue.start()].rstrip()
    suffix = _suffix_after_cue(text, cue, end)
    if not prefix or not suffix or len(WORD.findall(suffix)) > 80:
        return True
    phrase = cue.group(0).casefold()
    if phrase == "no" and prefix[-1] not in ",.;!?\n":
        return True
    prior_text = re.split(r"[.!?\n]+", prefix.rstrip(" \t,;:.!?"))[-1].strip()
    prior_words = _word_keys(prior_text)
    suffix_words = _word_keys(suffix)
    shared_prefix = 0
    for prior_word, suffix_word in zip(prior_words, suffix_words):
        if prior_word != suffix_word:
            break
        shared_prefix += 1
    discourse_clause = re.match(
        r"^(?:"
        r"the\s+(?:reason|problem|point|fact|question)\b|"
        r"(?:i|we|you|they|he|she|it|there|this|that)\s+"
        r"(?:think|believe|feel|know|wonder|mean|am|are|is|was|were|"
        r"have|has|do|does|did|can|could|would|should|might|may)\b|"
        r"because\b|however\b"
        r")",
        suffix,
        re.IGNORECASE,
    )
    if (
        phrase in {"no", "actually", "i mean", "i meant"}
        and discourse_clause
        and shared_prefix < 2
    ):
        return True
    if phrase == "actually" and cue.start() == 0:
        return True
    if phrase == "actually" and (not prefix or prefix[-1] not in ",.;!?\n"):
        return True
    if phrase in {"i mean", "i meant"} and re.match(
        r"^(?:that|what|when|where|why|how|like|for\s+example|in\s+other\s+words)\b",
        suffix,
        re.IGNORECASE,
    ):
        return True
    return False


def _restatement_candidates(text: str, protected: Sequence[tuple[int, int]]) -> list[dict[str, object]]:
    """Conservatively frame adjacent parallel prepositional constituents."""
    pattern = re.compile(
        r"(?<!\w)(?P<lead>as|to|for|with|from|in)\s+"
        r"(?P<first>[^,.;!?\n]{2,80}),\s*"
        r"(?P=lead)\s+(?P<second>[^,.;!?\n]{2,80})(?=[.!?,;:]|$)",
        re.IGNORECASE,
    )
    candidates = []
    for match in pattern.finditer(text):
        if _inside(protected, match.start()):
            continue
        first = WORD.findall(match.group("first"))
        second = WORD.findall(match.group("second"))
        if not first or not second or first == second:
            continue
        # Shared grammatical head/length is a conservative textual proxy for
        # structural parallelism; topical similarity alone is never enough.
        if abs(len(first) - len(second)) > 2:
            continue
        candidates.append({
            "start": match.start(),
            "end": match.end(),
            "type": "restatement",
            "cues": [],
        })
    # Shared-prefix adjacent clauses are a second strong textual shape. The
    # repeated grammatical frame must contain at least a subject and verb; a
    # merely related topic or one common word is insufficient.
    for comma in re.finditer(r"[,;]", text):
        if _inside(protected, comma.start()):
            continue
        left_start = max(
            text.rfind(".", 0, comma.start()),
            text.rfind("?", 0, comma.start()),
            text.rfind("!", 0, comma.start()),
            text.rfind("\n", 0, comma.start()),
        ) + 1
        right_stop = re.search(r"[.!?\n]", text[comma.end() :])
        right_end = (
            comma.end() + right_stop.start()
            if right_stop
            else len(text)
        )
        left = text[left_start : comma.start()].strip()
        right = text[comma.end() : right_end].strip()
        left_words, right_words = _word_keys(left), _word_keys(right)
        if not (3 <= len(left_words) <= 20 and 3 <= len(right_words) <= 20):
            continue
        common = 0
        for first, second in zip(left_words, right_words):
            if first != second:
                break
            common += 1
        if common < 2 or common >= min(len(left_words), len(right_words)):
            continue
        if left_words[0] not in {"i", "we", "you", "they", "he", "she", "it", "there"}:
            continue
        candidates.append(
            {
                "start": left_start,
                "end": right_end,
                "type": "restatement",
                "cues": [],
            }
        )
    return candidates


def _marker(kind: str, number: int, nonce: str, digest: str) -> str:
    return f"[[SPK_REPAIR_{number}_{kind}_{nonce}_{digest}]]"


def prepare_repairs(
    text: str,
    source_literals: Sequence[dict[str, object]] | None = None,
    protected_spans: Sequence[tuple[int, int]] = (),
) -> PreparedRepairs:
    """Detect Tier 2 regions and create collision-safe in-band framing."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n")
    if source_literals is None:
        collision_safe, source_literals = preserve_internal_literals(raw)
    else:
        collision_safe = raw
    # Most dictations contain neither repair cues nor adjacent restatement
    # punctuation. Avoid the heavier literal/repetition/region passes entirely.
    cue_probe = CUE_PATTERN.search(collision_safe)
    has_structural_separator = any(
        character in collision_safe for character in ",;:"
    )
    repeat_probe = SINGLE_WORD_REPEAT.search(collision_safe)
    if not cue_probe and not has_structural_separator and not repeat_probe:
        nonce = secrets.token_hex(8).upper()
        framed, shields = apply_literal_shields(
            collision_safe, source_literals, nonce
        )
        restored = restore_literal_placeholders(collision_safe, source_literals)
        return PreparedRepairs(raw, restored, framed, None, [], shields, [], [])
    if has_structural_separator:
        safe, repeat_edits = deterministic_exact_repetitions(
            collision_safe, protected_spans
        )
    else:
        safe, repeat_edits = collision_safe, []
    if any(character in safe for character in "\"'“”‘’") or re.search(
        r"\b(?:say|write|type|read|quote|mention|literal|verbatim|example|instruction|guide|test)\b",
        safe,
        re.IGNORECASE,
    ):
        protected = literal_spans(safe)
    else:
        protected = []
    safe_protected_spans: list[tuple[int, int]] = []
    protected_cursor = 0
    for protected_start, protected_end in sorted(protected_spans):
        value = collision_safe[protected_start:protected_end]
        if not value:
            continue
        relocated_start = safe.find(value, protected_cursor)
        if relocated_start < 0:
            continue
        relocated_end = relocated_start + len(value)
        safe_protected_spans.append((relocated_start, relocated_end))
        protected_cursor = relocated_end
    ambiguous: list[str] = [
        restore_literal_placeholders(safe[start:end], source_literals)
        for start, end in protected
    ]
    for repeat in SINGLE_WORD_REPEAT.finditer(safe):
        if not _inside(protected, repeat.start()):
            ambiguous.append(repeat.group(0))
    candidates: list[dict[str, object]] = []
    for cue in CUE_PATTERN.finditer(safe):
        if _inside(protected, cue.start()):
            continue
        cue_text = re.sub(r"\s+", " ", cue.group(0)).strip()
        immediate_suffix = safe[cue.end() :].lstrip(" \t,;:-–—.?!\n")
        if RESTART_CUE.fullmatch(cue_text) or (
            cue_text.casefold() == "no"
            and re.match(
                r"^(?:tell\s+me|let\s+me|let's|we\s+(?:need|should|will)|i\s+(?:need|want|will))\b",
                immediate_suffix,
                re.IGNORECASE,
            )
        ):
            repair_type = "restart"
        elif DISCARD_CUE.fullmatch(cue_text):
            repair_type = "explicit_discard"
        else:
            repair_type = "replacement"
        start, end = (
            _restart_bounds(safe, cue)
            if repair_type == "restart"
            else _replacement_bounds(safe, cue)
        )
        # A protected expansion earlier in the same clause is unrelated when
        # clear prose between it and the cue supplies the actual reparandum.
        # Starting after that expansion avoids spanning independent snippet
        # segments. With no intervening prose, keep the expansion in scope so
        # direct snippet corrections are not silently preserved.
        for protected_start, protected_end in reversed(safe_protected_spans):
            if protected_start < start or protected_end > cue.start():
                continue
            intervening = safe[protected_end : cue.start()].strip(
                " \t,;:-–—.?!\n"
            )
            if WORD.search(intervening):
                separator = re.match(r"[ \t\n]*", safe[protected_end : cue.start()])
                start = max(
                    start,
                    protected_end + (separator.end() if separator else 0),
                )
            break
        suffix = _suffix_after_cue(safe, cue, end)
        if repair_type == "explicit_discard":
            if cue_text.casefold() == "never mind" and re.match(
                r"[ \t]+[^,.;:!?\s]", safe[cue.end() :]
            ):
                ambiguous.append(safe[start:end])
                continue
            if not safe[start : cue.start()].strip(" \t,;:-–—.?!\n"):
                ambiguous.append(safe[start:end])
                continue
        elif ADDITIVE_START.match(suffix):
            ambiguous.append(safe[start:end])
            continue
        if repair_type != "explicit_discard" and _looks_natural_or_ambiguous(safe, cue, end):
            ambiguous.append(safe[max(0, cue.start() - 80) : min(len(safe), end)])
            continue
        if end - start > MAX_REGION_CHARACTERS:
            ambiguous.append(safe[start:end])
            continue
        candidates.append({
            "start": start,
            "end": end,
            "type": repair_type,
            "cues": [{"start": cue.start(), "end": cue.end(), "text": cue_text}],
        })
    if has_structural_separator:
        candidates.extend(_restatement_candidates(safe, protected))

    # Merge overlap and adjacency created by chained cues. Independent repairs
    # remain separate and retain textual order.
    merged: list[dict[str, object]] = []
    for candidate in sorted(candidates, key=lambda item: (int(item["start"]), int(item["end"]))):
        if merged and int(candidate["start"]) <= int(merged[-1]["end"]):
            previous = merged[-1]
            previous["end"] = max(int(previous["end"]), int(candidate["end"]))
            previous["type"] = "chain"
            previous["cues"] = sorted(
                list(previous["cues"]) + list(candidate["cues"]),
                key=lambda item: int(item["start"]),
            )
        else:
            merged.append(candidate)

    nonce = secrets.token_hex(8).upper()
    shielded_safe, shields = apply_literal_shields(safe, source_literals, nonce)
    restored_safe = restore_literal_placeholders(safe, source_literals)
    if not merged:
        return PreparedRepairs(raw, restored_safe, shielded_safe, None, [], shields, ambiguous, repeat_edits)

    framed = safe
    regions: list[dict[str, object]] = []
    replacements: list[tuple[int, int, str]] = []
    for number, candidate in enumerate(merged, 1):
        start, end = int(candidate["start"]), int(candidate["end"])
        region_type = str(candidate["type"])
        cues = list(candidate["cues"])
        integrity = _digest(number, region_type, start, end, cues, nonce)
        start_token = _marker("START", number, nonce, integrity)
        end_token = _marker("END", number, nonce, integrity)
        source_region = restore_literal_placeholders(safe[start:end], source_literals)
        cue_records: list[dict[str, object]] = []
        local = safe[start:end]
        for cue_number, cue in reversed(list(enumerate(cues, 1))):
            cue_start = int(cue["start"]) - start
            cue_end = int(cue["end"]) - start
            cue_digest = _digest(number, cue_number, cue["text"], nonce)
            cue_token = _marker(f"CUE_{cue_number}_{region_type.upper()}", number, nonce, cue_digest)
            trailing = re.match(r"[ \t]*[,;:]+[ \t]*", local[cue_end:])
            if trailing:
                cue_end += trailing.end()
            left = local[:cue_start].rstrip(" \t")
            right = local[cue_end:].lstrip(" \t")
            local = left + (" " if left else "") + cue_token
            if right:
                local += " " + right
            cue_records.append({
                "number": cue_number,
                "type": region_type,
                "text": cue["text"],
                "source_start": int(cue["start"]),
                "source_end": int(cue["end"]),
                "digest": cue_digest,
                "token": cue_token,
            })
        cue_records.reverse()
        local, _local_shields = apply_literal_shields(local, source_literals, nonce)
        replacements.append((start, end, start_token + local + end_token))
        regions.append({
            "number": number,
            "type": region_type,
            "source_start": start,
            "source_end": end,
            "source_text": source_region,
            "integrity": integrity,
            "start_token": start_token,
            "end_token": end_token,
            "cues": cue_records,
            "source_atoms": extract_protected_atoms(source_region),
        })
    for start, end, value in reversed(replacements):
        framed = framed[:start] + value + framed[end:]
    framed, _unused_shields = apply_literal_shields(framed, source_literals, nonce)
    return PreparedRepairs(raw, restored_safe, framed, nonce, regions, shields, ambiguous, repeat_edits)


def preserve_internal_literals(text: str) -> tuple[str, list[dict[str, object]]]:
    """Replace raw internal-looking text before any generated token exists."""
    literals: list[dict[str, object]] = []
    parts: list[str] = []
    position = 0
    for match in INTERNAL_LIKE_TOKEN.finditer(text):
        literal = match.group(0)
        number = len(literals) + 1
        placeholder = f"\ue000PARAQWEN_LITERAL_{number}\ue001"
        literals.append({"number": number, "literal": literal, "placeholder": placeholder})
        parts.extend((text[position : match.start()], placeholder))
        position = match.end()
    parts.append(text[position:])
    return "".join(parts), literals


def apply_literal_shields(
    text: str, literals: Sequence[dict[str, object]], nonce: str
) -> tuple[str, list[dict[str, object]]]:
    result = text
    shields: list[dict[str, object]] = []
    for item in literals:
        number, literal = int(item["number"]), str(item["literal"])
        placeholder = str(item["placeholder"])
        occurrence_count = result.count(placeholder)
        if occurrence_count == 0:
            # A completed deterministic edit may legitimately remove the
            # source span that contained this literal before a manifest exists.
            continue
        if occurrence_count != 1:
            raise ValueError("internal literal placeholder count mismatch")
        digest = _digest(number, literal, nonce)
        token = f"[[SPK_LITERAL_{number}__{nonce}__{digest}]]"
        result = result.replace(placeholder, token)
        shields.append({"number": number, "literal": literal, "token": token, "digest": digest})
    return result, shields


def restore_literal_placeholders(
    text: str, literals: Sequence[dict[str, object]]
) -> str:
    result = text
    for item in literals:
        result = result.replace(str(item["placeholder"]), str(item["literal"]))
    return result


def strip_repair_framing(text: str, manifest: dict[str, object] | None = None) -> str:
    """Remove generated structure for a persistence-degraded pre-AI run."""
    result = text
    if manifest:
        for region in manifest.get("repair_regions", []):
            if isinstance(region, dict):
                result = result.replace(str(region.get("start_token", "")), "")
                result = result.replace(str(region.get("end_token", "")), "")
                for cue in region.get("cues", []):
                    if isinstance(cue, dict):
                        result = result.replace(str(cue.get("token", "")), str(cue.get("text", "")))
        for shield in manifest.get("literal_shields", []):
            if isinstance(shield, dict):
                result = result.replace(str(shield.get("token", "")), str(shield.get("literal", "")))
    else:
        result = REPAIR_TOKEN.sub("", result)
    return result


def remove_semantic_commands(text: str) -> str:
    """Create validator source without model-consumed semantic directives."""
    return re.sub(r"[ \t]{2,}", " ", SEMANTIC_COMMAND_TOKEN.sub("", text)).strip()


def extract_protected_atoms(text: str) -> list[dict[str, object]]:
    occupied = bytearray(len(text))
    atoms: list[dict[str, object]] = []
    for kind, pattern in PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            if any(occupied[match.start() : match.end()]):
                continue
            value = match.group(0).rstrip(".,;:!?")
            if not value:
                continue
            end = match.start() + len(value)
            occupied[match.start() : end] = b"\x01" * (end - match.start())
            atoms.append({"kind": kind, "value": value, "start": match.start(), "end": end})
    return sorted(atoms, key=lambda item: int(item["start"]))


def _number_value(value: str) -> int | float | None:
    cleaned = value.casefold().strip(".,;:!? ")
    cleaned = re.sub(r"(?:ms|s|m|h|kb|mb|gb|%)$", "", cleaned)
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        pass
    words = [word for word in cleaned.replace("-", " ").split() if word != "and"]
    if not words or any(
        word not in NUMBER_WORDS and word not in NUMBER_SCALES for word in words
    ):
        return None
    if len(words) > 1 and not any(word in NUMBER_SCALES for word in words):
        if not (
            len(words) == 2
            and NUMBER_WORDS.get(words[0], 0) >= 20
            and NUMBER_WORDS.get(words[0], 0) % 10 == 0
            and 1 <= NUMBER_WORDS.get(words[1], 0) <= 9
        ):
            return None
    total = 0
    current = 0
    for word in words:
        if word in NUMBER_WORDS:
            current += NUMBER_WORDS[word]
        elif word == "hundred":
            if current == 0:
                return None
            current *= 100
        else:
            scale = NUMBER_SCALES[word]
            if current == 0:
                return None
            total += current * scale
            current = 0
    return total + current


def atom_key(atom: dict[str, object]) -> tuple[str, object]:
    kind, value = str(atom["kind"]), str(atom["value"])
    if kind == "number":
        numeric = _number_value(value)
        if numeric is not None:
            unit_match = re.fullmatch(
                r"-?\d+(?:\.\d+)?(?P<unit>%|ms|s|m|h|kb|mb|gb)?",
                value.casefold().strip(".,;:!? "),
            )
            unit = unit_match.group("unit") if unit_match else None
            return kind, (numeric, unit or "")
    if kind == "url":
        # URL schemes and hosts are case-insensitive; paths, queries, and
        # fragments can be case-sensitive and therefore remain exact.
        parsed = re.fullmatch(r"([^:]+://)([^/]+)(.*)", value)
        if parsed:
            return kind, (
                parsed.group(1).casefold()
                + parsed.group(2).casefold()
                + parsed.group(3)
            )
    if kind == "email" and "@" in value:
        local, domain = value.rsplit("@", 1)
        return kind, local + "@" + domain.casefold()
    if kind in {"version", "time"}:
        return kind, value.casefold()
    return kind, value


def _word_keys(text: str) -> list[str]:
    keys = []
    words = ALIGNMENT_TOKEN.findall(text)
    index = 0
    while index < len(words):
        word = words[index]
        key = word.casefold()
        consumed = 1
        if key in NUMBER_WORDS or key in NUMBER_SCALES:
            sequence_end = index + 1
            while sequence_end < len(words) and (
                words[sequence_end].casefold() in NUMBER_WORDS
                or words[sequence_end].casefold() in NUMBER_SCALES
                or words[sequence_end].casefold() == "and"
            ):
                sequence_end += 1
            for candidate_end in range(sequence_end, index, -1):
                candidate_words = words[index:candidate_end]
                if candidate_words[-1].casefold() == "and":
                    continue
                numeric = _number_value(" ".join(candidate_words))
                if numeric is None:
                    continue
                key = str(
                    int(numeric)
                    if isinstance(numeric, float) and numeric.is_integer()
                    else numeric
                )
                consumed = candidate_end - index
                break
        else:
            numeric = _number_value(key)
            if numeric is not None:
                key = str(
                    int(numeric)
                    if isinstance(numeric, float) and numeric.is_integer()
                    else numeric
                )
        key = INFLECTION_EQUIVALENTS.get(key, key)
        if len(key) > 4:
            for suffix in ("ing", "ed", "es", "s"):
                if key.endswith(suffix) and len(key) - len(suffix) >= 3:
                    key = key[: -len(suffix)]
                    break
        keys.append(key)
        index += consumed
    return keys


def _validate_structure(model_text: str, regions: Sequence[dict[str, object]], nonce: str) -> list[str]:
    _validate_region_manifest(regions, nonce)
    contents: list[str] = []
    cursor = 0
    for expected_number, region in enumerate(regions, 1):
        if region.get("number") != expected_number:
            raise RepairValidationError("repair manifest has non-sequential identifiers")
        start_token, end_token = str(region["start_token"]), str(region["end_token"])
        if nonce not in start_token or nonce not in end_token:
            raise RepairValidationError("repair manifest nonce mismatch")
        if model_text.count(start_token) != 1 or model_text.count(end_token) != 1:
            raise RepairValidationError(f"repair boundary count mismatch for region {expected_number}")
        start = model_text.find(start_token, cursor)
        end = model_text.find(end_token, start + len(start_token))
        if start < cursor or end < 0:
            raise RepairValidationError("repair regions are missing, nested, or reordered")
        content_start = start + len(start_token)
        if REPAIR_TOKEN.search(model_text[content_start:end]):
            raise RepairValidationError("semantic cue or nested repair token leaked")
        contents.append(model_text[content_start:end])
        cursor = end + len(end_token)
    remaining = REPAIR_TOKEN.search(model_text[: model_text.find(str(regions[0]["start_token"]))] if regions else model_text)
    if remaining:
        raise RepairValidationError("unexpected or forged repair token")
    known = {str(r["start_token"]) for r in regions} | {str(r["end_token"]) for r in regions}
    for token in REPAIR_TOKEN.findall(model_text):
        if token not in known:
            raise RepairValidationError("unexpected or forged repair token")
    return contents


def _validate_region_manifest(
    regions: Sequence[dict[str, object]], nonce: str
) -> None:
    previous_end = -1
    valid_types = {
        "replacement", "restart", "restatement", "chain", "explicit_discard"
    }
    for expected_number, region in enumerate(regions, 1):
        if region.get("number") != expected_number:
            raise RepairValidationError("repair manifest has non-sequential identifiers")
        region_type = region.get("type")
        start, end = region.get("source_start"), region.get("source_end")
        source_text = region.get("source_text")
        cues = region.get("cues")
        if (
            region_type not in valid_types
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or start < previous_end
            or end - start > MAX_REGION_CHARACTERS
            or not isinstance(source_text, str)
            or not isinstance(cues, list)
            or not all(isinstance(cue, dict) for cue in cues)
        ):
            raise RepairValidationError("invalid repair region metadata")
        if region_type == "restatement" and cues:
            raise RepairValidationError("restatement region unexpectedly contains cues")
        if region_type != "restatement" and not cues:
            raise RepairValidationError("repair region is missing its cue metadata")
        cue_basis: list[dict[str, object]] = []
        previous_cue_end = start
        for expected_cue_number, cue in enumerate(cues, 1):
            cue_number = cue.get("number")
            cue_type = cue.get("type")
            cue_text = cue.get("text")
            cue_start, cue_end = cue.get("source_start"), cue.get("source_end")
            if (
                cue_number != expected_cue_number
                or cue_type != region_type
                or not isinstance(cue_text, str)
                or not cue_text
                or not isinstance(cue_start, int)
                or not isinstance(cue_end, int)
                or cue_start < previous_cue_end
                or cue_end <= cue_start
                or cue_end > end
            ):
                raise RepairValidationError("invalid repair cue metadata")
            cue_digest = _digest(
                expected_number, expected_cue_number, cue_text, nonce
            )
            expected_cue_token = _marker(
                f"CUE_{expected_cue_number}_{str(region_type).upper()}",
                expected_number,
                nonce,
                cue_digest,
            )
            if cue.get("digest") != cue_digest or cue.get("token") != expected_cue_token:
                raise RepairValidationError("repair cue checksum mismatch")
            cue_basis.append(
                {"start": cue_start, "end": cue_end, "text": cue_text}
            )
            previous_cue_end = cue_end
        integrity = _digest(
            expected_number, region_type, start, end, cue_basis, nonce
        )
        if region.get("integrity") != integrity:
            raise RepairValidationError("repair region checksum mismatch")
        if region.get("start_token") != _marker(
            "START", expected_number, nonce, integrity
        ) or region.get("end_token") != _marker(
            "END", expected_number, nonce, integrity
        ):
            raise RepairValidationError("repair boundary checksum mismatch")
        if region.get("source_atoms") != extract_protected_atoms(source_text):
            raise RepairValidationError("repair protected-atom manifest mismatch")
        previous_end = end


def _outside_chunks(text: str, regions: Sequence[dict[str, object]]) -> list[str]:
    chunks: list[str] = []
    cursor = 0
    for region in regions:
        start_token, end_token = str(region["start_token"]), str(region["end_token"])
        start = text.find(start_token, cursor)
        end = text.find(end_token, start + len(start_token))
        chunks.append(text[cursor:start])
        cursor = end + len(end_token)
    chunks.append(text[cursor:])
    return chunks


def _expanded_validation_regions(
    framed_source: str, regions: Sequence[dict[str, object]]
) -> tuple[list[dict[str, object]], list[str]]:
    """Derive region atoms/grounding from the exact expanded source state."""
    validation_regions: list[dict[str, object]] = []
    grounding_sources: list[str] = []
    cursor = 0
    for region in regions:
        start_token = str(region["start_token"])
        end_token = str(region["end_token"])
        start = framed_source.find(start_token, cursor)
        content_start = start + len(start_token)
        end = framed_source.find(end_token, content_start)
        if start < cursor or end < content_start:
            raise RepairValidationError("expanded repair source structure is invalid")
        content = framed_source[content_start:end]
        clean_content = content
        validation_cues: list[dict[str, object]] = []
        for cue in region.get("cues", []):
            token = str(cue["token"])
            if clean_content.count(token) != 1:
                raise RepairValidationError(
                    "expanded repair source cue structure is invalid"
                )
            cue_start = clean_content.find(token)
            cue_end = cue_start + len(token)
            validation_cues.append(
                {
                    "source_start": cue_start,
                    "source_end": cue_end,
                }
            )
            # Preserve offsets while excluding internal marker words from both
            # grounding and protected-atom extraction.
            clean_content = (
                clean_content[:cue_start]
                + " " * len(token)
                + clean_content[cue_end:]
            )
        if REPAIR_TOKEN.search(clean_content):
            raise RepairValidationError("expanded repair source contains unknown tokens")
        validation_region = dict(region)
        validation_region.update(
            {
                "source_start": 0,
                "source_end": len(clean_content),
                "source_atoms": extract_protected_atoms(clean_content),
                "cues": validation_cues,
            }
        )
        validation_regions.append(validation_region)
        grounding_sources.append(clean_content)
        cursor = end + len(end_token)
    return validation_regions, grounding_sources


def _validate_alignment(source_chunks: Sequence[str], output_chunks: Sequence[str]) -> None:
    if len(source_chunks) != len(output_chunks):
        raise RepairValidationError("outside-region alignment structure changed")
    for source, output in zip(source_chunks, output_chunks):
        left, right = _word_keys(source), _word_keys(output)
        if not left and not right:
            continue
        delta = abs(len(left) - len(right))
        allowance = max(3, int(len(left) * 0.25))
        overlap = sum((Counter(left) & Counter(right)).values()) / max(
            1, len(left), len(right)
        )
        left_pairs = Counter(zip(left, left[1:]))
        right_pairs = Counter(zip(right, right[1:]))
        pair_overlap = sum((left_pairs & right_pairs).values()) / max(
            1, sum(left_pairs.values()), sum(right_pairs.values())
        )
        if overlap < 0.78 or (len(left) >= 5 and pair_overlap < 0.45) or delta > allowance:
            raise RepairValidationError("substantial prose insertion or deletion outside repair region")


def _validate_atom_order(
    source_chunks: Sequence[str], output_chunks: Sequence[str]
) -> None:
    """Protected atoms outside repairs cannot move across or within chunks."""
    if len(source_chunks) != len(output_chunks):
        raise RepairValidationError("protected atom chunk structure changed")
    for source, output in zip(source_chunks, output_chunks):
        source_order = [atom_key(atom) for atom in extract_protected_atoms(source)]
        output_order = [atom_key(atom) for atom in extract_protected_atoms(output)]
        if source_order != output_order:
            raise RepairValidationError("protected atom removed, changed, invented, or relocated")


def _validate_grounding(source: str, output: str) -> None:
    source_words = _word_keys(source)
    output_words = _word_keys(output)
    source_counts = Counter(source_words)
    output_counts = Counter(output_words)
    invented = {
        word: count - source_counts[word]
        for word, count in output_counts.items()
        if word not in GROUNDING_INSERTION_WORDS and count > source_counts[word]
    }
    if invented:
        raise RepairValidationError("repair output is not grounded in later source wording")
    # A repair must retain at least one meaningful word from the later half.
    later = [word for word in source_words[len(source_words) // 2 :] if word not in FUNCTION_WORDS]
    if later and not set(later).intersection(output_words):
        raise RepairValidationError("repair discarded all later source wording")


def _restore_shields(text: str, shields: Sequence[dict[str, object]]) -> str:
    result = text
    known = set()
    known_numbers = set()
    for shield in shields:
        if not isinstance(shield, dict):
            raise RepairValidationError("invalid literal-token shield metadata")
        token, literal = str(shield["token"]), str(shield["literal"])
        number = shield.get("number")
        parsed = LITERAL_TOKEN.fullmatch(token)
        if (
            not isinstance(number, int)
            or number <= 0
            or number in known_numbers
            or parsed is None
            or int(parsed.group(1)) != number
        ):
            raise RepairValidationError("invalid literal-token shield metadata")
        nonce, token_digest = parsed.group(2), parsed.group(3)
        expected_digest = _digest(number, literal, nonce)
        if shield.get("digest") != expected_digest or token_digest != expected_digest:
            raise RepairValidationError("literal-token shield checksum mismatch")
        known_numbers.add(number)
        known.add(token)
        if result.count(token) != 1:
            raise RepairValidationError("literal-token shield count mismatch")
        result = result.replace(token, literal)
    if LITERAL_TOKEN.search(result):
        raise RepairValidationError("unknown literal-token shield")
    return result


def _is_subsequence(
    values: Sequence[tuple[str, object]], source: Sequence[tuple[str, object]]
) -> bool:
    cursor = 0
    for value in values:
        while cursor < len(source) and source[cursor] != value:
            cursor += 1
        if cursor >= len(source):
            return False
        cursor += 1
    return True


def _region_removable_atom_indices(region: dict[str, object]) -> set[int]:
    """Return only atom occurrences locally superseded by an ordered cue."""
    atoms = [atom for atom in region.get("source_atoms", []) if isinstance(atom, dict)]
    cues = [cue for cue in region.get("cues", []) if isinstance(cue, dict)]
    region_start = int(region.get("source_start", 0))
    removable: set[int] = set()
    for cue_index, cue in enumerate(cues):
        cue_start = int(cue.get("source_start", region_start)) - region_start
        cue_end = int(cue.get("source_end", region_start)) - region_start
        next_cue_start = (
            int(cues[cue_index + 1].get("source_start", region_start))
            - region_start
            if cue_index + 1 < len(cues)
            else int(region.get("source_end", region_start)) - region_start
        )
        later_by_kind: dict[str, list[int]] = {}
        for index, atom in enumerate(atoms):
            if cue_end <= int(atom.get("start", 0)) < next_cue_start:
                later_by_kind.setdefault(str(atom["kind"]), []).append(index)

        for kind, later_indices in later_by_kind.items():
            before_indices = [
                index
                for index, atom in enumerate(atoms)
                if index not in removable
                and str(atom["kind"]) == kind
                and int(atom.get("end", 0)) <= cue_start
            ]
            if not before_indices:
                continue
            before_keys = [atom_key(atoms[index]) for index in before_indices]
            later_keys = [atom_key(atoms[index]) for index in later_indices]
            shared = Counter(before_keys) & Counter(later_keys)
            novel_later_count = sum((Counter(later_keys) - shared).values())
            if novel_later_count == 0:
                continue

            # Allocate unchanged values to their earliest prior occurrences so
            # the nearest unmatched occurrence is the only removal candidate.
            remaining_shared = shared.copy()
            unmatched_before: list[int] = []
            for index, key in zip(before_indices, before_keys):
                if remaining_shared[key] > 0:
                    remaining_shared[key] -= 1
                else:
                    unmatched_before.append(index)
            if unmatched_before:
                removable.add(unmatched_before[-1])
    return removable


def _validate_region_atom_order(
    regions: Sequence[dict[str, object]], outputs: Sequence[str]
) -> None:
    """Region atoms may be grounded deletions, but never inventions or moves."""
    for region, output in zip(regions, outputs):
        atoms = [
            atom for atom in region.get("source_atoms", []) if isinstance(atom, dict)
        ]
        source_order = [atom_key(atom) for atom in atoms]
        removable = _region_removable_atom_indices(region)
        mandatory_order = [
            atom_key(atom) for index, atom in enumerate(atoms) if index not in removable
        ]
        output_order = [atom_key(atom) for atom in extract_protected_atoms(output)]
        if not _is_subsequence(output_order, source_order) or not _is_subsequence(
            mandatory_order, output_order
        ):
            raise RepairValidationError(
                "protected atom invented, changed, or relocated inside repair region"
            )


def validate_model_output(
    model_text: str,
    manifest: dict[str, object],
) -> str:
    """Validate and unwrap one model output or raise for deterministic fallback."""
    nonce = manifest.get("repair_nonce")
    regions = manifest.get("repair_regions")
    safe_source = manifest.get("safe_source")
    raw_source = manifest.get("raw_source")
    if not isinstance(regions, list) or not all(isinstance(r, dict) for r in regions):
        raise RepairValidationError("invalid repair region manifest")
    if not isinstance(safe_source, str) or not isinstance(raw_source, str):
        raise RepairValidationError("missing repair source text")
    result = model_text
    validation_regions: list[dict[str, object]] = []
    if regions:
        if not isinstance(nonce, str) or not re.fullmatch(r"[A-F0-9]{16}", nonce):
            raise RepairValidationError("missing or invalid repair nonce")
        region_outputs = _validate_structure(model_text, regions, nonce)
        framed_source = manifest.get("framed_source")
        if not isinstance(framed_source, str):
            raise RepairValidationError("missing framed repair source")
        source_chunks = _outside_chunks(framed_source, regions)
        output_chunks = _outside_chunks(model_text, regions)
        validation_regions, grounding_sources = _expanded_validation_regions(
            framed_source, regions
        )
        _validate_atom_order(source_chunks, output_chunks)
        _validate_alignment(source_chunks, output_chunks)
        _validate_region_atom_order(validation_regions, region_outputs)
        for source, output in zip(grounding_sources, region_outputs):
            _validate_grounding(source, output)
        for region in reversed(regions):
            start_token, end_token = str(region["start_token"]), str(region["end_token"])
            result = result.replace(start_token, "").replace(end_token, "")
        # Segment reconstruction may insert a separator beside a repair
        # boundary that began at offset zero. The original Pre-AI source is
        # normalized without leading whitespace, so this is structural glue,
        # not dictated indentation.
        result = result.lstrip()
    elif REPAIR_TOKEN.search(result):
        raise RepairValidationError("unexpected repair token without a region manifest")

    shields = list(manifest.get("literal_shields", []))
    result = _restore_shields(result, shields)
    allowed_literals = Counter(
        str(item["literal"]) for item in shields if isinstance(item, dict)
    )
    hygiene_text = result
    for literal, count in allowed_literals.items():
        hygiene_text = hygiene_text.replace(literal, "", count)
    if INTERNAL_TOKEN_PREFIX.search(hygiene_text):
        raise RepairValidationError("invented, malformed, or leaked internal control token")

    validation_source = manifest.get("validation_source")
    verified_text = manifest.get("verified_text")
    atom_source = (
        validation_source
        if isinstance(validation_source, str)
        else verified_text if isinstance(verified_text, str) else safe_source
    )
    if not regions:
        _validate_atom_order([atom_source], [result])
        _validate_alignment([atom_source], [result])
    source_atoms = extract_protected_atoms(atom_source)
    output_atoms = extract_protected_atoms(result)
    source_keys, output_keys = Counter(map(atom_key, source_atoms)), Counter(map(atom_key, output_atoms))
    # Protected atoms inside a repair region may be removed only when a later
    # source atom grounds the change. Distinctive atoms outside regions remain mandatory.
    removable = Counter()
    for region in validation_regions:
        region_atoms = list(region.get("source_atoms", []))
        for index in _region_removable_atom_indices(region):
            atom = region_atoms[index]
            if isinstance(atom, dict):
                removable[atom_key(atom)] += 1
    for key, count in source_keys.items():
        if output_keys[key] < count - removable[key]:
            raise RepairValidationError(f"protected atom removed or changed: {key[0]}")
    for key, count in output_keys.items():
        if count > source_keys[key]:
            raise RepairValidationError(f"protected atom invented: {key[0]}")

    for span in manifest.get("ambiguous_spans", []):
        if not isinstance(span, str) or not span.strip():
            continue
        required = _word_keys(span)
        present = _word_keys(result)
        if required and not any(
            present[index : index + len(required)] == required
            for index in range(len(present) - len(required) + 1)
        ):
            raise RepairValidationError("ambiguous repair source was not preserved")
    return result.rstrip()


def manifest_digest(prompt_text: str, snippets_text: str) -> str:
    return _digest(prompt_text, snippets_text, SCHEMA_VERSION, size=16)


def build_state(
    prepared: PreparedRepairs,
    *,
    framed_source: str,
    verified_text: str,
    portable_text: str,
    file_nonce: str | None,
    expected_counts: dict[str, int],
    prompt_config_digest: str,
    diagnostic_trace_id: str | None = None,
    validation_source: str | None = None,
) -> dict[str, object]:
    state = {
        "version": SCHEMA_VERSION,
        "created_at": time.time(),
        "uid": os.getuid(),
        "raw_source": prepared.raw_source,
        "safe_source": prepared.safe_source,
        "validation_source": (
            validation_source
            if validation_source is not None
            else prepared.validation_source
        ),
        "framed_source": framed_source,
        "verified_text": verified_text.rstrip(),
        "portable_text": portable_text.rstrip(),
        "file_nonce": file_nonce,
        "expected_counts": expected_counts,
        "prompt_config_digest": prompt_config_digest,
        "diagnostic_trace_id": diagnostic_trace_id,
        "expansion_occurrences": [
            {"id": key, "count": value} for key, value in sorted(expected_counts.items())
        ],
    }
    state.update(prepared.manifest())
    # Long transcripts often have identical raw/safe/framed/expanded forms.
    # Persist one copy and explicit aliases to keep atomic state I/O bounded.
    source_fields = (
        "raw_source", "safe_source", "validation_source", "framed_source",
        "verified_text", "portable_text"
    )
    first_for_value: dict[str, str] = {}
    for field in source_fields:
        value = state.get(field)
        if not isinstance(value, str):
            continue
        original_field = first_for_value.get(value)
        if original_field is None:
            first_for_value[value] = field
        else:
            state[field] = {"same_as": original_field}
    return state


def resolve_state_sources(state: dict[str, object]) -> dict[str, object]:
    """Resolve compact same-as aliases after a one-shot state read."""
    fields = (
        "raw_source", "safe_source", "validation_source", "framed_source",
        "verified_text", "portable_text"
    )
    for field in fields:
        value = state.get(field)
        if isinstance(value, dict) and set(value) == {"same_as"}:
            target = value.get("same_as")
            if not isinstance(target, str) or target not in fields:
                raise ValueError("invalid recovery source alias")
            resolved = state.get(target)
            if not isinstance(resolved, str):
                raise ValueError("unresolved recovery source alias")
            state[field] = resolved
    return state
