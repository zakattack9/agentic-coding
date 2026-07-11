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
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Match, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SNIPPETS = SCRIPT_DIR.parent / "config" / "snippets.json"
DEFAULT_PREFIX_STATE = (
    Path(tempfile.gettempdir()) / f"spokenly-prefix-snippet-{os.getuid()}.json"
)

TOKENS = {
    "delete_sentence": "[[SPK_CMD_DELETE_SENTENCE]]",
    "delete_phrase": "[[SPK_CMD_DELETE_PHRASE]]",
    "discard": "[[SPK_CMD_DISCARD_THOUGHT]]",
    "bullets": "[[SPK_CMD_BULLET_LIST]]",
    "numbers": "[[SPK_CMD_NUMBERED_LIST]]",
    "correction": "[[SPK_CMD_SELF_CORRECTION]]",
}

SNIPPET_ID = re.compile(r"^[A-Z][A-Z0-9_]*$")
SNIPPET_TOKEN = re.compile(
    r"\[\[SPK_SNIPPET_([A-Z][A-Z0-9_]*)__([1-9][0-9]*)__([A-F0-9]{8})\]\]"
)
LEADING_SNIPPET = re.compile(
    r"^\[\[SPK_SEGMENT_0_START\]\]\[\[SPK_SEGMENT_0_END\]\]"
    r"\[\[SPK_SNIPPET_([A-Z][A-Z0-9_]*)__1__[A-F0-9]{8}\]\]"
)
SLASH_COMMAND = re.compile(r"/[A-Za-z][A-Za-z0-9_-]*")

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
        \b{POLITE}(?:delete|remove|erase|drop|take\s+out)\s+
        (?:(?:(?:the|my)\s+)?(?:last|previous|prior|most\s+recent)\s+(?:word|term)|that\s+(?:word|term))\b
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
    r"\b(?:sorry\s*,?\s*i\s+(?:mean|meant)|oops\s*,?\s*i\s+(?:mean|meant)|no\s*,?\s*actually|correction\s*[:,])",
    re.IGNORECASE,
)
PLAIN_I_MEAN = re.compile(r"\bi\s+(?:mean|meant)\b", re.IGNORECASE)
REPORTING_CONTEXT = re.compile(
    r"\b(?:say|says|said|tell|tells|told|ask|asks|asked|write|writes|wrote|read|reads|quote|quotes|quoted|call|calls|called|mention|mentions|mentioned)\b(?:\s+(?:the|this|a))?(?:\s+(?:phrase|command|instruction|word|words|example))?\b[\s:\"'“”‘’,-]*$",
    re.IGNORECASE,
)
NON_CORRECTION_START = re.compile(
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
        if not isinstance(triggers, list) or not triggers or not all(isinstance(t, str) and t.strip() for t in triggers):
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


def protect_snippets(text: str, snippets: Iterable[Dict[str, object]]) -> str:
    pairs = []
    for snippet in snippets:
        for trigger in snippet["triggers"]:  # type: ignore[index]
            pairs.append(
                (
                    str(trigger),
                    str(snippet["id"]),
                    bool(snippet.get("consume_trailing_punctuation", False)),
                )
            )
    if not pairs:
        return text

    # Match all triggers in one left-to-right pass. Repeated per-trigger
    # substitutions can number tokens by configuration order rather than by
    # their actual position in the transcript.
    alternatives = []
    trigger_metadata: Dict[str, Tuple[str, bool]] = {}
    for index, (trigger, snippet_id, consume_punctuation) in enumerate(
        sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)
    ):
        group = f"trigger_{index}"
        spaced_trigger = r"\s+".join(re.escape(part) for part in trigger.split())
        alternatives.append(rf"(?P<{group}>(?<!\w){spaced_trigger}(?!\w))")
        trigger_metadata[group] = (snippet_id, consume_punctuation)

    pattern = re.compile("|".join(alternatives), re.IGNORECASE)
    parts: List[str] = []
    position = 0
    occurrence = 0
    for match in pattern.finditer(text):
        group = match.lastgroup
        if group is None:
            continue
        snippet_id, consume_punctuation = trigger_metadata[group]
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
    return bool(REPORTING_CONTEXT.search(prefix[-120:]))


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
    sentence_boundary = max(value.rfind("."), value.rfind("?"), value.rfind("!"), value.rfind("\n"))
    phrase_boundaries = [
        index
        for index, character in enumerate(value)
        if character in ",;:" and index > sentence_boundary
    ]
    if value and phrase_boundaries:
        # When the transcript already ends with a delimiter, that delimiter
        # closes the target phrase. Delete back to the preceding delimiter.
        if value[-1] in ",;:":
            cutoff = phrase_boundaries[-2] if len(phrase_boundaries) >= 2 else sentence_boundary
        else:
            cutoff = phrase_boundaries[-1]
        retained = value[: max(cutoff, 0)].rstrip(" ,;:")
        return True, retained
    return False, value


def delete_last_word(value: str) -> Tuple[bool, str]:
    value = value.rstrip()
    changed = re.sub(r"(?:\s+|^)[^\W_]+(?:[-'][^\W_]+)*[.,;:!?]*$", "", value, flags=re.UNICODE).rstrip()
    return changed != value, changed


def add_token(value: str, token: str) -> str:
    return value.rstrip() + (" " if value.rstrip() else "") + token + " "


def apply_directives(text: str) -> str:
    output = ""
    position = 0
    for match in DIRECTIVES.finditer(text):
        candidate = output + text[position : match.start()]
        if discussed_as_text(candidate):
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
        if kind in {"delete_sentence", "delete_phrase", "delete_word", "discard"} and output and not output.endswith((" ", "\n")):
            output += " "
        position = match.end()
        trailing = re.match(r"\s*[,.!?;:]?\s*", text[position:])
        if trailing:
            position += trailing.end()

    return output + text[position:]


def should_mark_plain_i_mean(text: str, match: Match[str]) -> bool:
    prefix = text[: match.start()].rstrip()
    if not prefix or discussed_as_text(prefix):
        return False
    suffix = text[match.end() :].lstrip(" ,:;-")
    local_suffix = re.split(r"[.!?\n]", suffix, maxsplit=1)[0].strip()
    if not local_suffix or NON_CORRECTION_START.match(local_suffix):
        return False
    words = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", local_suffix, flags=re.UNICODE)
    return 1 <= len(words) <= 10


def add_correction_hints(text: str) -> str:
    text = EXPLICIT_CORRECTIONS.sub(f" {TOKENS['correction']} ", text)
    parts: List[str] = []
    position = 0
    for match in PLAIN_I_MEAN.finditer(text):
        if should_mark_plain_i_mean(text, match):
            parts.append(text[position : match.start()])
            parts.append(f" {TOKENS['correction']} ")
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


def process(text: str, snippets_path: Path) -> str:
    snippets = load_snippets(snippets_path)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = protect_snippets(text, snippets)
    text = apply_directives(text)
    text = add_correction_hints(text)
    return frame_snippet_segments(normalize(text))


def clear_pending_prefix(state_path: Path = DEFAULT_PREFIX_STATE) -> None:
    state_path.unlink(missing_ok=True)


def record_pending_prefix(
    processed: str,
    snippets_path: Path,
    state_path: Path = DEFAULT_PREFIX_STATE,
) -> None:
    """Record a leading slash snippet for one-shot post-AI recovery."""
    clear_pending_prefix(state_path)
    match = LEADING_SNIPPET.match(processed)
    if not match:
        return
    expansions = {
        str(item["id"]): str(item["text"])
        for item in load_snippets(snippets_path)
    }
    prefix = expansions.get(match.group(1), "")
    if not SLASH_COMMAND.fullmatch(prefix):
        return

    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"prefix": prefix, "created_at": time.time()}),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, state_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippets", type=Path, default=DEFAULT_SNIPPETS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = sys.stdin.read()
    clear_pending_prefix()
    try:
        processed = process(original, args.snippets)
        record_pending_prefix(processed, args.snippets)
        sys.stdout.write(processed)
    except Exception as error:
        print(f"Spokenly preprocessor failed open: {error}", file=sys.stderr)
        sys.stdout.write(original)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
