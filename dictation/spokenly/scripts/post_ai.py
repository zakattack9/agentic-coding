#!/usr/bin/env python3
"""Expand protected Spokenly snippet tokens after Qwen cleanup.

Input: Qwen output on stdin
Output: exact snippet-expanded text on stdout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from pre_ai import (
    DEFAULT_SLASH_STATE,
    DEFAULT_SNIPPETS,
    SLASH_COMMAND,
    clear_pending_slash_commands,
    load_snippets,
    snippet_checksum,
)


TOKEN = re.compile(
    r"\[\[SPK_SNIPPET_([A-Z][A-Z0-9_]*)__([1-9][0-9]*)__([A-F0-9]{8})\]\]"
)
ANY_SNIPPET_TOKEN = re.compile(r"\[\[SPK_SNIPPET_[^\]]+\]\]")
INTERNAL_TOKEN = re.compile(r"\[\[SPK_CMD_[A-Z0-9_]+\]\]")
SEGMENT = re.compile(
    r"\[\[SPK_SEGMENT_([0-9]+)_START"
    r"(?:_AFTER_([A-Z][A-Z0-9_]*)__([A-F0-9]{8}))?\]\](.*?)"
    r"\[\[SPK_SEGMENT_\1_END\]\]",
    re.DOTALL,
)
ANY_SEGMENT_TOKEN = re.compile(r"\[\[SPK_SEGMENT_[^\]]+\]\]")


def join_at_protected_boundary(left: str, right: str) -> str:
    """Join around an expansion even if the model trims boundary whitespace."""
    if not left or not right or left[-1].isspace() or right[0].isspace():
        return left + right
    if right[0] in ",.;:!?)]}" or left[-1] in "([{":
        return left + right
    return left + " " + right


def consume_boundary_punctuation(text: str) -> str:
    """Remove punctuation inferred immediately after an exact snippet."""
    return re.sub(r"^[ \t]*[.,!?;:]+[ \t]*", "", text, count=1)


def expand(text: str, snippets_path: Path) -> str:
    snippets = load_snippets(snippets_path)
    expansions = {str(item["id"]): str(item["text"]) for item in snippets}
    consume_punctuation = {
        str(item["id"]): bool(item.get("consume_trailing_punctuation", False))
        for item in snippets
    }

    tokens = list(TOKEN.finditer(text))
    segments = list(SEGMENT.finditer(text))

    if tokens and not segments:
        raise ValueError("unframed snippet token; snippet placement cannot be verified")

    if segments:
        by_index = {}
        for match in segments:
            index = int(match.group(1))
            if index in by_index:
                raise ValueError(f"duplicated transcript segment: {index}")
            by_index[index] = (match.group(2), match.group(3), match.group(4))

        expected_indices = list(range(len(segments)))
        if sorted(by_index) != expected_indices:
            raise ValueError("missing or non-contiguous transcript segment")

        snippet_by_position = {}
        for index in expected_indices:
            snippet_id, checksum, _content = by_index[index]
            if index == 0:
                if snippet_id is not None or checksum is not None:
                    raise ValueError("initial transcript segment has snippet metadata")
                continue
            if snippet_id is None or checksum is None:
                raise ValueError(f"missing snippet metadata before segment {index}")
            if snippet_id not in expansions:
                raise ValueError(f"unknown snippet token: {snippet_id}")
            if checksum != snippet_checksum(snippet_id, index):
                raise ValueError(f"invalid snippet metadata checksum at position {index}")
            snippet_by_position[index] = snippet_id

        token_by_position = {}
        for match in tokens:
            snippet_id = match.group(1)
            position = int(match.group(2))
            checksum = match.group(3)
            if position in token_by_position:
                raise ValueError(f"duplicated snippet position: {position}")
            if snippet_id not in expansions:
                raise ValueError(f"unknown snippet token: {snippet_id}")
            if checksum != snippet_checksum(snippet_id, position):
                raise ValueError(f"invalid snippet token checksum at position {position}")
            token_by_position[position] = snippet_id
        for position, snippet_id in token_by_position.items():
            if snippet_by_position.get(position) != snippet_id:
                raise ValueError(f"snippet token disagrees with segment {position}")

        # No model-generated prose may escape the protected segment frames.
        residue = SEGMENT.sub("", text)
        residue = TOKEN.sub("", residue)
        if residue.strip():
            raise ValueError("unexpected text outside protected transcript segments")

        result = ""
        for index in expected_indices:
            # Placement is reconstructed from indices, so a token moved by the
            # model is harmless. Remove tokens that were moved into a segment.
            snippet_id, _checksum, content = by_index[index]
            if index > 0:
                result = join_at_protected_boundary(
                    result, expansions[str(snippet_id)]
                )
                if consume_punctuation[str(snippet_id)]:
                    content = consume_boundary_punctuation(content)
            result = join_at_protected_boundary(result, TOKEN.sub("", content))
    else:
        result = text

    malformed = ANY_SNIPPET_TOKEN.search(result)
    if malformed:
        raise ValueError(f"malformed or unresolved snippet token: {malformed.group(0)}")
    unresolved = INTERNAL_TOKEN.search(result)
    if unresolved:
        raise ValueError(f"unresolved internal token: {unresolved.group(0)}")
    malformed_segment = ANY_SEGMENT_TOKEN.search(result)
    if malformed_segment:
        raise ValueError(
            f"malformed or unresolved segment token: {malformed_segment.group(0)}"
        )
    # The postprocessor is the last boundary before auto-insertion. Never emit
    # trailing spaces, tabs, or line breaks that could submit/execute text.
    return result.rstrip()


def process(text: str, snippets_path: Path) -> str:
    return expand(text, snippets_path)


def consume_pending_slash_commands(
    state_path: Path = DEFAULT_SLASH_STATE,
    max_age_seconds: float = 120.0,
) -> list[dict[str, object]]:
    """Consume recent one-shot slash snippets, if any exist."""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return []
    finally:
        # A state record belongs to one Post-AI invocation only.
        clear_pending_slash_commands(state_path)

    if not isinstance(data, dict):
        return []
    commands = data.get("commands")
    created_at = data.get("created_at")
    if not isinstance(commands, list):
        return []
    if not isinstance(created_at, (int, float)):
        return []
    age = time.time() - created_at
    if age < 0 or age > max_age_seconds:
        return []

    validated = []
    for item in commands:
        if not isinstance(item, dict):
            return []
        command = item.get("text")
        leading = item.get("leading")
        consume = item.get("consume_trailing_punctuation")
        left_anchor = item.get("left_anchor", [])
        right_anchor = item.get("right_anchor", [])
        if not isinstance(command, str) or not SLASH_COMMAND.fullmatch(command):
            return []
        if not isinstance(leading, bool) or not isinstance(consume, bool):
            return []
        if not isinstance(left_anchor, list) or not all(
            isinstance(word, str) and word for word in left_anchor
        ):
            return []
        if not isinstance(right_anchor, list) or not all(
            isinstance(word, str) and word for word in right_anchor
        ):
            return []
        validated.append(
            {
                "text": command,
                "leading": leading,
                "consume_trailing_punctuation": consume,
                "left_anchor": left_anchor,
                "right_anchor": right_anchor,
            }
        )
    return validated


SLASH_LIKE = re.compile(
    r"(?<!\S)/(?:[A-Za-z][A-Za-z0-9_:\-]*)?(?=\s|[.,!?;:]|$)"
)


def slash_command_key(command: str) -> str:
    return re.sub(r"[-_:]", "", command.casefold())


def find_recoverable_slash(
    text: str, position: int, known_keys: set[str]
) -> re.Match[str] | None:
    for match in SLASH_LIKE.finditer(text, position):
        if match.group(0) == "/" or slash_command_key(match.group(0)) in known_keys:
            return match
    return None


def consume_recovered_punctuation(text: str, command_end: int) -> str:
    tail = text[command_end:]
    cleaned = consume_boundary_punctuation(tail)
    if cleaned == tail:
        return text
    return join_at_protected_boundary(text[:command_end], cleaned)


def find_word_anchor(
    text: str, words: list[str], position: int
) -> re.Match[str] | None:
    if not words:
        return None
    separator = r"(?:[\W_]+)"
    pattern = re.compile(
        r"(?<!\w)" + separator.join(re.escape(word) for word in words) + r"(?!\w)",
        re.IGNORECASE,
    )
    return pattern.search(text, position)


def insert_before_anchor(
    text: str, command: str, anchor: re.Match[str]
) -> tuple[str, int]:
    left = text[: anchor.start()].rstrip()
    right = text[anchor.start() :].lstrip()
    result = join_at_protected_boundary(left, command)
    command_end = len(result)
    return join_at_protected_boundary(result, right), command_end


def insert_after_anchor(
    text: str, command: str, anchor: re.Match[str]
) -> tuple[str, int]:
    left = text[: anchor.end()].rstrip()
    right = text[anchor.end() :].lstrip()
    result = join_at_protected_boundary(left, command)
    command_end = len(result)
    return join_at_protected_boundary(result, right), command_end


def restore_pending_slash_commands(
    text: str, commands: list[dict[str, object]]
) -> str:
    """Restore ordered slash commands that Qwen reduced to bare slashes."""
    if not commands:
        return text
    result = text
    cursor = 0
    known_keys = {slash_command_key(str(item["text"])) for item in commands}
    for item in commands:
        command = str(item["text"])
        consume = bool(item["consume_trailing_punctuation"])
        if bool(item["leading"]):
            content_start = len(result) - len(result.lstrip())
            leading_placeholder = find_recoverable_slash(
                result, content_start, known_keys
            )
            if leading_placeholder and leading_placeholder.start() == content_start:
                start, end = leading_placeholder.span()
                result = result[:start] + command + result[end:]
                cursor = start + len(command)
                if consume:
                    result = consume_recovered_punctuation(result, cursor)
                continue
            result = join_at_protected_boundary(command, result.lstrip())
            cursor = len(command)
            continue

        placeholder = find_recoverable_slash(result, cursor, known_keys)
        if placeholder:
            start, end = placeholder.span()
            result = result[:start] + command + result[end:]
            cursor = start + len(command)
            if consume:
                result = consume_recovered_punctuation(result, cursor)
            continue

        right_anchor = find_word_anchor(
            result, list(item.get("right_anchor", [])), cursor
        )
        if right_anchor:
            result, cursor = insert_before_anchor(result, command, right_anchor)
            continue

        left_anchor = find_word_anchor(
            result, list(item.get("left_anchor", [])), cursor
        )
        if left_anchor:
            result, cursor = insert_after_anchor(result, command, left_anchor)
            continue

        raise ValueError(f"missing recoverable slash command: {command}")

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippets", type=Path, default=DEFAULT_SNIPPETS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = sys.stdin.read()
    pending_commands = consume_pending_slash_commands()
    try:
        expanded = expand(original, args.snippets)
        sys.stdout.write(restore_pending_slash_commands(expanded, pending_commands))
    except Exception as error:
        print(f"Spokenly postprocessor failed closed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
