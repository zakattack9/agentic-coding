#!/usr/bin/env python3
"""Preprocess a Spokenly transcript before Qwen.

The processor deliberately recognizes a finite set of high-confidence editing
commands. Ambiguous semantic work is represented by control tokens for Qwen.
Snippet triggers are replaced with protected tokens and expanded only after AI.

Input: transcript on stdin
Output: transformed transcript on stdout
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Match, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
SPOKENLY_DIR = SCRIPT_DIR.parent
if str(SPOKENLY_DIR) not in sys.path:
    sys.path.insert(0, str(SPOKENLY_DIR))

from plugins import (  # noqa: E402
    load_iterm_file_references,
    log_iterm_file_reference_event,
)

DEFAULT_SNIPPETS = SCRIPT_DIR.parent / "config" / "snippets.json"
DEFAULT_SLASH_STATE = (
    Path(tempfile.gettempdir()) / f"spokenly-slash-snippets-{os.getuid()}.json"
)
DEFAULT_SOURCE_RECOVERY_STATE = (
    Path(tempfile.gettempdir()) / f"spokenly-source-recovery-{os.getuid()}.json"
)

TOKENS = {
    "delete_sentence": "[[SPK_CMD_DELETE_SENTENCE]]",
    "delete_phrase": "[[SPK_CMD_DELETE_PHRASE]]",
    "discard": "[[SPK_CMD_DISCARD_THOUGHT]]",
    "bullets": "[[SPK_CMD_BULLET_LIST]]",
    "numbers": "[[SPK_CMD_NUMBERED_LIST]]",
    "correction": "[[SPK_CMD_REPLACE_NEAREST]]",
}

SNIPPET_ID = re.compile(r"^[A-Z][A-Z0-9_]*$")
SNIPPET_TOKEN = re.compile(
    r"\[\[SPK_SNIPPET_([A-Z][A-Z0-9_]*)__([1-9][0-9]*)__([A-F0-9]{8})\]\]"
)
LEADING_SNIPPET = re.compile(
    r"^\[\[SPK_SEGMENT_0_START\]\]\[\[SPK_SEGMENT_0_END\]\]"
    r"\[\[SPK_SNIPPET_([A-Z][A-Z0-9_]*)__1__[A-F0-9]{8}\]\]"
)
SLASH_COMMAND = re.compile(r"/[A-Za-z][A-Za-z0-9_-]*(?::[A-Za-z][A-Za-z0-9_-]*)?")
FRAMED_SEGMENT = re.compile(
    r"\[\[SPK_SEGMENT_([0-9]+)_START(?:_AFTER_[^\]]+)?\]\](.*?)"
    r"\[\[SPK_SEGMENT_\1_END\]\]",
    re.DOTALL,
)
STRUCTURAL_TOKEN = re.compile(r"\[\[[^\]]+\]\]")

POLITE = r"(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
DIRECTIVES = re.compile(
    rf"""
    (?P<delete_sentence>
        \b{POLITE}(?:delete|remove|erase|drop|take\s+out)\s+
        (?:(?:(?:the|my)\s+)?(?:last|previous|prior|most\s+recent)\s+sentence|that\s+sentence)\b
    )
    |
    (?P<delete_phrase>
        \b{POLITE}(?:delete|remove|erase|drop|take\s+out)\s+
        (?:(?:(?:the|my)\s+)?(?:last|previous|prior|most\s+recent)\s+(?:phrase|clause)|that\s+(?:phrase|clause))\b
    )
    |
    (?P<delete_word>
        \b{POLITE}(?:
            (?:delete|remove|erase|drop|take\s+out)\s+
            (?:(?:(?:the|my)\s+)?(?:last|previous|prior|most\s+recent)\s+(?:word|term)|that\s+(?:word|term))
          | scratch\s+(?:(?:the\s+)?(?:last|previous)\s+)?word
        )\b
    )
    |
    (?P<discard>
        \b{POLITE}(?:
            scratch\s+(?:that|the\s+last\s+(?:part|thing|thought))
          | never\s*mind(?:\s+that)?
          | forget\s+(?:that|the\s+last\s+(?:part|thing|thought))
          | ignore\s+(?:that|the\s+last\s+(?:part|thing|thought))
          | undo\s+(?:that|the\s+last\s+(?:part|thing|thought))
          | cancel\s+(?:that|the\s+last\s+(?:part|thing|thought))
          | (?:delete|remove)\s+what\s+i\s+just\s+said
          | delete\s+that(?=\s*(?:[,.!?;:]|$))
        )\b
    )
    |
    (?P<new_paragraph>
        \b{POLITE}(?:new\s+paragraph|paragraph\s+break|start\s+(?:a\s+)?new\s+paragraph|next\s+paragraph)\b
    )
    |
    (?P<new_line>
        \b{POLITE}(?:new\s+line|line\s+break|start\s+(?:a\s+)?new\s+line|next\s+line)\b
    )
    |
    (?P<bullet_list>
        \b{POLITE}(?:
            make\s+(?:those|these|this|that|it|the\s+previous\s+items?)\s+(?:into\s+)?(?:a\s+)?(?:bullet(?:ed)?\s+)?list
          | format\s+(?:(?:those|these|this|that|it|the\s+previous\s+items?)\s+)?as\s+(?:a\s+)?(?:bullet(?:ed)?\s+)?list
          | turn\s+(?:those|these|this|that|it|the\s+previous\s+items?)\s+into\s+(?:a\s+)?(?:bullet(?:ed)?\s+)?list
          | turn\s+(?:those|these|this|that|it|the\s+previous\s+items?)\s+into\s+bullet\s+points
          | bullet\s+(?:those|these|the\s+previous)\s+items?
          | put\s+(?:those|these|this|that|it|the\s+previous\s+items?)\s+in\s+(?:a\s+)?list
        )\b
    )
    |
    (?P<numbered_list>
        \b{POLITE}(?:
            number\s+(?:those|these|the\s+previous)\s+items?
          | make\s+(?:those|these|this|that|it|the\s+previous\s+items?)\s+(?:into\s+)?(?:a\s+)?numbered\s+list
          | format\s+(?:(?:those|these|this|that|it|the\s+previous\s+items?)\s+)?as\s+(?:a\s+)?numbered\s+list
          | turn\s+(?:those|these|this|that|it|the\s+previous\s+items?)\s+into\s+(?:a\s+)?numbered\s+list
        )\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

EXPLICIT_CORRECTIONS = re.compile(
    r"\b(?:"
    r"sorry\s*,?\s*i\s+(?:mean|meant)|"
    r"oops\s*,?\s*i\s+(?:mean|meant)|"
    r"no\s*,?\s*(?:actually|wait)|"
    r"correction(?:\s+is)?\s*[:,]|"
    r"or\s+rather|"
    r"what\s+i\s+(?:really\s+)?meant\s+(?:was|is)|"
    r"let\s+me\s+(?:rephrase|correct\s+that)"
    r")",
    re.IGNORECASE,
)
PLAIN_I_MEAN = re.compile(r"\bi\s+(?:mean|meant)\b", re.IGNORECASE)
DELIMITED_REPAIR = re.compile(
    r"\b(?:actually|no|sorry|correct\s+that)\b", re.IGNORECASE
)
REPORTING_CONTEXT = re.compile(
    r"\b(?:say|says|said|tell|tells|told|ask|asks|asked|write|writes|wrote|read|reads|quote|quotes|quoted|call|calls|called|mention|mentions|mentioned)\b(?:\s+(?:the|this|a))?(?:\s+(?:phrase|command|instruction|word|words|example))?\b[\s:\"'“”‘’,-]*$",
    re.IGNORECASE,
)
REPORTING_SPAN = re.compile(
    r"\b(?:say|write|type|read|quote|mention)\s+"
    r"(?:(?:the|this|a)\s+)?(?:phrase|command|instruction|words?|example)\b"
    r"[^.!?\n]{0,120}$",
    re.IGNORECASE,
)
NON_CORRECTION_START = re.compile(
    r"^(?:that|this|what|when|where|why|how|like|for\s+example|in\s+other\s+words)\b",
    re.IGNORECASE,
)
AMBIGUOUS_REPAIR_START = re.compile(
    r"^(?:that|this|it|what|when|where|why|how|to|we|you|i|there|like|for\s+example|in\s+other\s+words)\b",
    re.IGNORECASE,
)


def load_snippets(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("snippets")
    if not isinstance(data, list):
        raise ValueError("snippet configuration must contain a snippets array")

    snippets: List[Dict[str, object]] = []
    seen_ids = set()
    seen_triggers = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"snippet {index} must be an object")
        snippet_id = item.get("id")
        triggers = item.get("triggers")
        text = item.get("text")
        consume_trailing_punctuation = item.get("consume_trailing_punctuation", False)
        if not isinstance(snippet_id, str) or not SNIPPET_ID.fullmatch(snippet_id):
            raise ValueError(f"snippet {index} has an invalid id")
        if snippet_id in seen_ids:
            raise ValueError(f"duplicate snippet id: {snippet_id}")
        if (
            not isinstance(triggers, list)
            or not triggers
            or not all(isinstance(t, str) and t.strip() for t in triggers)
        ):
            raise ValueError(f"snippet {snippet_id} needs non-empty triggers")
        if not isinstance(text, str):
            raise ValueError(f"snippet {snippet_id} text must be a string")
        if not isinstance(consume_trailing_punctuation, bool):
            raise ValueError(
                f"snippet {snippet_id} consume_trailing_punctuation must be boolean"
            )
        for trigger in triggers:
            normalized = " ".join(trigger.strip().split()).casefold()
            if len(normalized) < 4:
                raise ValueError(f"snippet trigger is too short: {trigger}")
            if normalized in seen_triggers:
                raise ValueError(f"duplicate snippet trigger: {trigger}")
            seen_triggers.add(normalized)
        seen_ids.add(snippet_id)
        snippets.append(
            {
                "id": snippet_id,
                "triggers": [" ".join(t.strip().split()) for t in triggers],
                "text": text,
                "consume_trailing_punctuation": consume_trailing_punctuation,
            }
        )
    return snippets


def merge_snippets(
    snippets_path: Path,
    extra_snippets: Iterable[Dict[str, object]] = (),
) -> List[Dict[str, object]]:
    snippets = load_snippets(snippets_path)
    seen_ids = {str(item["id"]) for item in snippets}
    seen_triggers = {
        " ".join(str(trigger).strip().split()).casefold()
        for item in snippets
        for trigger in item["triggers"]  # type: ignore[index]
    }
    for item in extra_snippets:
        snippet_id = str(item.get("id", ""))
        triggers = item.get("triggers")
        if snippet_id in seen_ids:
            raise ValueError(f"duplicate protected expansion id: {snippet_id}")
        if not isinstance(triggers, list):
            raise ValueError(f"protected expansion {snippet_id} has invalid triggers")
        for trigger in triggers:
            normalized = " ".join(str(trigger).strip().split()).casefold()
            if normalized in seen_triggers:
                raise ValueError(f"duplicate protected trigger: {trigger}")
            seen_triggers.add(normalized)
        seen_ids.add(snippet_id)
        snippets.append(item)
    return snippets


def snippet_matcher(
    snippets: Iterable[Dict[str, object]],
) -> tuple[re.Pattern[str] | None, Dict[str, Dict[str, object]]]:
    pairs = []
    for snippet in snippets:
        for trigger in snippet["triggers"]:  # type: ignore[index]
            pairs.append(
                (
                    str(trigger),
                    str(snippet["id"]),
                    str(snippet["text"]),
                    bool(snippet.get("consume_trailing_punctuation", False)),
                )
            )
    if not pairs:
        return None, {}

    # Match all triggers in one left-to-right pass. Repeated per-trigger
    # substitutions can number tokens by configuration order rather than by
    # their actual position in the transcript.
    alternatives = []
    trigger_metadata: Dict[str, Dict[str, object]] = {}
    for index, (trigger, snippet_id, expansion, consume_punctuation) in enumerate(
        sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)
    ):
        group = f"trigger_{index}"
        spaced_trigger = r"\s+".join(re.escape(part) for part in trigger.split())
        alternatives.append(rf"(?P<{group}>(?<!\w){spaced_trigger}(?!\w))")
        trigger_metadata[group] = {
            "id": snippet_id,
            "text": expansion,
            "consume_trailing_punctuation": consume_punctuation,
        }

    return re.compile("|".join(alternatives), re.IGNORECASE), trigger_metadata


def protect_snippets(text: str, snippets: Iterable[Dict[str, object]]) -> str:
    pattern, trigger_metadata = snippet_matcher(snippets)
    if pattern is None:
        return text

    parts: List[str] = []
    position = 0
    occurrence = 0
    for match in pattern.finditer(text):
        group = match.lastgroup
        if group is None:
            continue
        metadata = trigger_metadata[group]
        snippet_id = str(metadata["id"])
        consume_punctuation = bool(metadata["consume_trailing_punctuation"])
        end = match.end()
        if consume_punctuation and end < len(text) and text[end] in ".!?":
            end += 1
        occurrence += 1
        checksum = snippet_checksum(snippet_id, occurrence)
        parts.append(text[position : match.start()])
        parts.append(f"[[SPK_SNIPPET_{snippet_id}__{occurrence}__{checksum}]]")
        position = end
    parts.append(text[position:])
    return "".join(parts)


def expand_snippets_in_source(
    text: str,
    snippets: Iterable[Dict[str, object]],
) -> str:
    """Expand exact snippet spans without involving the cleanup model."""
    pattern, trigger_metadata = snippet_matcher(snippets)
    if pattern is None:
        return text.rstrip()

    parts: List[str] = []
    position = 0
    for match in pattern.finditer(text):
        group = match.lastgroup
        if group is None:
            continue
        metadata = trigger_metadata[group]
        end = match.end()
        if (
            bool(metadata["consume_trailing_punctuation"])
            and end < len(text)
            and text[end] in ".!?"
        ):
            end += 1
        parts.extend((text[position : match.start()], str(metadata["text"])))
        position = end
    parts.append(text[position:])
    return "".join(parts).rstrip()


def snippet_checksum(snippet_id: str, position: int) -> str:
    """Detect accidental model edits to a snippet's identity or position."""
    value = f"spokenly-snippet-v1:{position}:{snippet_id}".encode("ascii")
    return hashlib.blake2s(value, digest_size=4).hexdigest().upper()


def frame_snippet_segments(text: str) -> str:
    """Frame editable spans so post-AI can restore every snippet's position."""
    matches = list(SNIPPET_TOKEN.finditer(text))
    if not matches:
        return text

    parts: List[str] = []
    position = 0
    for segment, match in enumerate(matches):
        if segment == 0:
            parts.append("[[SPK_SEGMENT_0_START]]")
        else:
            previous = matches[segment - 1]
            parts.append(
                f"[[SPK_SEGMENT_{segment}_START_AFTER_"
                f"{previous.group(1)}__{previous.group(3)}]]"
            )
        parts.append(text[position : match.start()])
        parts.append(f"[[SPK_SEGMENT_{segment}_END]]")
        parts.append(match.group(0))
        position = match.end()
    final_segment = len(matches)
    final_match = matches[-1]
    parts.append(
        f"[[SPK_SEGMENT_{final_segment}_START_AFTER_"
        f"{final_match.group(1)}__{final_match.group(3)}]]"
    )
    parts.append(text[position:])
    parts.append(f"[[SPK_SEGMENT_{final_segment}_END]]")
    return "".join(parts)


def discussed_as_text(prefix: str) -> bool:
    return bool(
        REPORTING_CONTEXT.search(prefix[-160:]) or REPORTING_SPAN.search(prefix[-160:])
    )


def inside_quoted_text(text: str, position: int) -> bool:
    prefix = text[:position]
    return (
        prefix.count('"') % 2 == 1
        or prefix.rfind("“") > prefix.rfind("”")
        or prefix.rfind("‘") > prefix.rfind("’")
    )


def sentence_boundaries(value: str) -> List[Match[str]]:
    return list(re.finditer(r"[.!?](?:[\"”’')\]]*)", value.rstrip()))


def delete_last_sentence(value: str) -> Tuple[bool, str]:
    value = value.rstrip()
    boundaries = sentence_boundaries(value)
    if not value or not boundaries:
        return False, value
    last = boundaries[-1]
    if last.end() < len(value):
        return True, value[: last.end()].rstrip()
    previous_end = boundaries[-2].end() if len(boundaries) >= 2 else 0
    return True, value[:previous_end].rstrip()


def delete_last_phrase(value: str) -> Tuple[bool, str]:
    value = value.rstrip()
    sentence_boundary = max(
        value.rfind("."), value.rfind("?"), value.rfind("!"), value.rfind("\n")
    )
    phrase_boundaries = [
        index
        for index, character in enumerate(value)
        if character in ",;:" and index > sentence_boundary
    ]
    if value and phrase_boundaries:
        # When the transcript already ends with a delimiter, that delimiter
        # closes the target phrase. Delete back to the preceding delimiter.
        if value[-1] in ",;:":
            cutoff = (
                phrase_boundaries[-2]
                if len(phrase_boundaries) >= 2
                else sentence_boundary
            )
        else:
            cutoff = phrase_boundaries[-1]
        retained = value[: max(cutoff, 0)].rstrip(" ,;:")
        return True, retained
    return False, value


def delete_last_word(value: str) -> Tuple[bool, str]:
    value = value.rstrip()
    changed = re.sub(
        r"(?:\s+|^)[^\W_]+(?:[-'][^\W_]+)*[.,;:!?]*$", "", value, flags=re.UNICODE
    ).rstrip()
    return changed != value, changed


def add_token(value: str, token: str) -> str:
    return value.rstrip() + (" " if value.rstrip() else "") + token + " "


def apply_directives(text: str) -> str:
    output = ""
    position = 0
    for match in DIRECTIVES.finditer(text):
        candidate = output + text[position : match.start()]
        if discussed_as_text(candidate) or inside_quoted_text(text, match.start()):
            continue

        kind = match.lastgroup
        new_output = candidate
        success = True
        if kind == "delete_sentence":
            success, new_output = delete_last_sentence(candidate)
            if not success:
                new_output = add_token(candidate, TOKENS["delete_sentence"])
        elif kind == "delete_phrase":
            success, new_output = delete_last_phrase(candidate)
            if not success:
                new_output = add_token(candidate, TOKENS["delete_phrase"])
        elif kind == "delete_word":
            success, new_output = delete_last_word(candidate)
            if not success:
                continue
        elif kind == "discard":
            success, new_output = delete_last_sentence(candidate)
            if not success:
                new_output = add_token(candidate, TOKENS["discard"])
        elif kind == "new_paragraph":
            new_output = candidate.rstrip() + "\n\n"
        elif kind == "new_line":
            new_output = candidate.rstrip() + "\n"
        elif kind == "bullet_list":
            new_output = add_token(candidate, TOKENS["bullets"])
        elif kind == "numbered_list":
            new_output = add_token(candidate, TOKENS["numbers"])

        output = new_output
        if (
            kind in {"delete_sentence", "delete_phrase", "delete_word", "discard"}
            and output
            and not output.endswith((" ", "\n"))
        ):
            output += " "
        position = match.end()
        trailing = re.match(r"\s*[,.!?;:]?\s*", text[position:])
        if trailing:
            position += trailing.end()

    return output + text[position:]


def correction_suffix(text: str, match: Match[str]) -> Tuple[str, List[str]]:
    suffix = text[match.end() :].lstrip(" ,:;-.!?")
    local_suffix = re.split(r"[.!?\n]", suffix, maxsplit=1)[0].strip()
    words = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", local_suffix, flags=re.UNICODE)
    return local_suffix, words


def should_mark_plain_i_mean(text: str, match: Match[str]) -> bool:
    prefix = text[: match.start()].rstrip()
    if (
        not prefix
        or discussed_as_text(prefix)
        or inside_quoted_text(text, match.start())
    ):
        return False
    local_suffix, words = correction_suffix(text, match)
    if not local_suffix or NON_CORRECTION_START.match(local_suffix):
        return False
    return 1 <= len(words) <= 24


def should_mark_delimited_repair(text: str, match: Match[str]) -> bool:
    prefix = text[: match.start()].rstrip()
    if (
        not prefix
        or prefix[-1] not in ",.;!?-—"
        or discussed_as_text(prefix)
        or inside_quoted_text(text, match.start())
    ):
        return False
    local_suffix, words = correction_suffix(text, match)
    if not local_suffix or AMBIGUOUS_REPAIR_START.match(local_suffix):
        return False
    return 1 <= len(words) <= 12


def append_correction_hint(parts: List[str], prefix: str) -> None:
    # ASR commonly inserts a sentence boundary before "I mean" and similar
    # repairs. A comma makes the replacement relationship local and explicit
    # to the cleanup model without changing question/exclamation boundaries.
    prefix = re.sub(r"\.\s*$", ", ", prefix)
    parts.append(prefix)
    if prefix and not prefix.endswith((" ", "\n")):
        parts.append(" ")
    parts.append(f"{TOKENS['correction']} ")


def add_correction_hints(text: str) -> str:
    explicit_parts: List[str] = []
    explicit_position = 0
    for match in EXPLICIT_CORRECTIONS.finditer(text):
        prefix = text[: match.start()].rstrip()
        _local_suffix, words = correction_suffix(text, match)
        if (
            not prefix
            or not words
            or discussed_as_text(prefix)
            or inside_quoted_text(text, match.start())
        ):
            continue
        append_correction_hint(explicit_parts, text[explicit_position : match.start()])
        explicit_position = match.end()
    explicit_parts.append(text[explicit_position:])
    text = "".join(explicit_parts)

    repair_parts: List[str] = []
    repair_position = 0
    for match in DELIMITED_REPAIR.finditer(text):
        if should_mark_delimited_repair(text, match):
            append_correction_hint(repair_parts, text[repair_position : match.start()])
            repair_position = match.end()
    repair_parts.append(text[repair_position:])
    text = "".join(repair_parts)

    parts: List[str] = []
    position = 0
    for match in PLAIN_I_MEAN.finditer(text):
        if should_mark_plain_i_mean(text, match):
            append_correction_hint(parts, text[position : match.start()])
            position = match.end()
    parts.append(text[position:])
    return "".join(parts)


def normalize(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    return text.strip()


def process(
    text: str,
    snippets_path: Path,
    extra_snippets: Iterable[Dict[str, object]] = (),
) -> str:
    snippets = merge_snippets(snippets_path, extra_snippets)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = protect_snippets(text, snippets)
    text = apply_directives(text)
    text = add_correction_hints(text)
    return frame_snippet_segments(normalize(text))


def clear_pending_slash_commands(state_path: Path = DEFAULT_SLASH_STATE) -> None:
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        # Recovery state is optional; it must never break preprocessing.
        pass


def clear_source_recovery_state(
    state_path: Path = DEFAULT_SOURCE_RECOVERY_STATE,
) -> None:
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        pass


def record_source_recovery_state(
    verified_text: str,
    portable_text: str,
    file_nonce: str | None,
    expected_counts: dict[str, int],
    state_path: Path = DEFAULT_SOURCE_RECOVERY_STATE,
) -> None:
    clear_source_recovery_state(state_path)
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{state_path.name}.",
        suffix=".tmp",
        dir=state_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            json.dump(
                {
                    "version": 1,
                    "created_at": time.time(),
                    "file_nonce": file_nonce,
                    "expected_counts": expected_counts,
                    "verified_text": verified_text.rstrip(),
                    "portable_text": portable_text.rstrip(),
                },
                output,
                ensure_ascii=False,
            )
        os.replace(temporary, state_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def consume_source_recovery_state(
    state_path: Path = DEFAULT_SOURCE_RECOVERY_STATE,
    max_age_seconds: float = 120.0,
) -> dict[str, object] | None:
    try:
        info = state_path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            return None
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    finally:
        clear_source_recovery_state(state_path)

    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    created_at = data.get("created_at")
    if not isinstance(created_at, (int, float)):
        return None
    age = time.time() - float(created_at)
    if age < -1 or age > max_age_seconds:
        return None
    if not isinstance(data.get("verified_text"), str) or not isinstance(
        data.get("portable_text"), str
    ):
        return None
    expected_counts = data.get("expected_counts")
    if not isinstance(expected_counts, dict) or not all(
        isinstance(key, str) and isinstance(value, int) and value > 0
        for key, value in expected_counts.items()
    ):
        return None
    file_nonce = data.get("file_nonce")
    if file_nonce is not None and not isinstance(file_nonce, str):
        return None
    return data


def record_pending_slash_commands(
    processed: str,
    snippets_path: Path,
    state_path: Path = DEFAULT_SLASH_STATE,
) -> None:
    """Record ordered slash snippets for one-shot post-AI recovery."""
    clear_pending_slash_commands(state_path)
    snippets = load_snippets(snippets_path)
    settings = {str(item["id"]): item for item in snippets}
    segments = {
        int(match.group(1)): match.group(2)
        for match in FRAMED_SEGMENT.finditer(processed)
    }
    leading = LEADING_SNIPPET.match(processed)
    commands = []
    for match in SNIPPET_TOKEN.finditer(processed):
        snippet = settings.get(match.group(1))
        if snippet is None:
            continue
        command = str(snippet["text"])
        if not SLASH_COMMAND.fullmatch(command):
            continue
        commands.append(
            {
                "text": command,
                "leading": bool(
                    leading
                    and leading.group(1) == match.group(1)
                    and int(match.group(2)) == 1
                ),
                "consume_trailing_punctuation": bool(
                    snippet.get("consume_trailing_punctuation", False)
                ),
                "left_anchor": anchor_words(
                    segments.get(int(match.group(2)) - 1, ""), from_end=True
                ),
                "right_anchor": anchor_words(
                    segments.get(int(match.group(2)), ""), from_end=False
                ),
            }
        )
    if not commands:
        return

    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps({"commands": commands, "created_at": time.time()}),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, state_path)
    except OSError:
        # The in-band framing remains authoritative when recovery state cannot
        # be persisted.
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def anchor_words(text: str, from_end: bool, limit: int = 6) -> List[str]:
    text = STRUCTURAL_TOKEN.sub(" ", text)
    words = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", text, flags=re.UNICODE)
    return words[-limit:] if from_end else words[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippets", type=Path, default=DEFAULT_SNIPPETS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = sys.stdin.read()
    source_recovery_path = Path(
        os.environ.get(
            "SPOKENLY_SOURCE_RECOVERY_STATE",
            str(DEFAULT_SOURCE_RECOVERY_STATE),
        )
    ).expanduser()
    clear_pending_slash_commands()
    clear_source_recovery_state(source_recovery_path)
    try:
        file_reference_plugin = load_iterm_file_references()
    except Exception as error:
        file_reference_plugin = None
        log_iterm_file_reference_event("pre.load", str(error))
    prepared_references = None
    extra_snippets: Iterable[Dict[str, object]] = ()
    if file_reference_plugin is not None:
        try:
            context_path = Path(
                os.environ.get(
                    "SPOKENLY_ITERM_CONTEXT_STATE",
                    str(file_reference_plugin.DEFAULT_CONTEXT_STATE),
                )
            ).expanduser()
            pending_dir = Path(
                os.environ.get(
                    "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR",
                    str(file_reference_plugin.DEFAULT_PENDING_DIR),
                )
            ).expanduser()
            prepared_references = file_reference_plugin.prepare_file_references(
                original,
                os.environ.get("SPOKENLY_ACTIVE_APP", ""),
                context_path=context_path,
                pending_dir=pending_dir,
            )
            extra_snippets = prepared_references.snippets
            for warning in prepared_references.warnings:
                log_iterm_file_reference_event(
                    "pre.resolve",
                    warning,
                    active_app=os.environ.get("SPOKENLY_ACTIVE_APP", ""),
                )
        except Exception as error:
            # The plugin is opt-in enrichment. Before it creates a protected
            # reference, any missing prerequisite leaves portable dictation intact.
            log_iterm_file_reference_event("pre.prepare", str(error))
    try:
        processed = process(original, args.snippets, extra_snippets)
    except Exception as error:
        if prepared_references is not None:
            try:
                file_reference_plugin.finish_pending_file_references(
                    prepared_references.pending
                )
            except Exception as cleanup_error:
                log_iterm_file_reference_event("pre.cleanup", str(cleanup_error))
        log_iterm_file_reference_event("pre.core_fallback", str(error))
        try:
            record_source_recovery_state(
                original,
                original,
                None,
                {},
                state_path=source_recovery_path,
            )
        except Exception as recovery_error:
            log_iterm_file_reference_event("pre.source_recovery", str(recovery_error))
        sys.stdout.write(original)
        return 0
    try:
        portable_snippets = load_snippets(args.snippets)
        verified_snippets = merge_snippets(args.snippets, extra_snippets)
        file_nonce = (
            prepared_references.pending.nonce
            if prepared_references is not None
            and prepared_references.pending is not None
            else None
        )
        expected_counts: dict[str, int] = {}
        for match in SNIPPET_TOKEN.finditer(processed):
            snippet_id = match.group(1)
            expected_counts[snippet_id] = expected_counts.get(snippet_id, 0) + 1
        record_source_recovery_state(
            expand_snippets_in_source(original, verified_snippets),
            expand_snippets_in_source(original, portable_snippets),
            file_nonce,
            expected_counts,
            state_path=source_recovery_path,
        )
    except Exception as error:
        log_iterm_file_reference_event("pre.source_recovery", str(error))
    # Optional recovery-state I/O must not discard successful preprocessing.
    try:
        record_pending_slash_commands(processed, args.snippets)
    except Exception as error:
        log_iterm_file_reference_event("pre.slash_recovery", str(error))
    sys.stdout.write(processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
