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
    DEFAULT_PREFIX_STATE,
    DEFAULT_SNIPPETS,
    SLASH_COMMAND,
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


def consume_pending_prefix(
    state_path: Path = DEFAULT_PREFIX_STATE,
    max_age_seconds: float = 120.0,
) -> str:
    """Consume a recent one-shot leading slash snippet, if one exists."""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError):
        state_path.unlink(missing_ok=True)
        return ""
    finally:
        # A state record belongs to one Post-AI invocation only.
        state_path.unlink(missing_ok=True)

    if not isinstance(data, dict):
        return ""
    prefix = data.get("prefix")
    created_at = data.get("created_at")
    if not isinstance(prefix, str) or not SLASH_COMMAND.fullmatch(prefix):
        return ""
    if not isinstance(created_at, (int, float)):
        return ""
    age = time.time() - created_at
    if age < 0 or age > max_age_seconds:
        return ""
    return prefix


def restore_pending_prefix(text: str, prefix: str) -> str:
    if not prefix:
        return text
    cleaned = text.lstrip()
    if cleaned == prefix or cleaned.startswith(prefix + " "):
        return text
    return join_at_protected_boundary(prefix, cleaned)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippets", type=Path, default=DEFAULT_SNIPPETS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = sys.stdin.read()
    pending_prefix = consume_pending_prefix()
    try:
        expanded = expand(original, args.snippets)
        sys.stdout.write(restore_pending_prefix(expanded, pending_prefix))
    except Exception as error:
        print(f"Spokenly postprocessor failed closed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
