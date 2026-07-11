#!/usr/bin/env python3
"""Expand protected Spokenly snippet tokens after Qwen cleanup.

Input: Qwen output on stdin
Output: exact snippet-expanded text on stdout
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pre_ai import DEFAULT_SNIPPETS, load_snippets


TOKEN = re.compile(r"\[\[SPK_SNIPPET_([A-Z][A-Z0-9_]*)__([1-9][0-9]*)\]\]")
ANY_SNIPPET_TOKEN = re.compile(r"\[\[SPK_SNIPPET_[^\]]+\]\]")
INTERNAL_TOKEN = re.compile(r"\[\[SPK_CMD_[A-Z0-9_]+\]\]")


def expand(text: str, snippets_path: Path) -> str:
    snippets = load_snippets(snippets_path)
    expansions = {str(item["id"]): str(item["text"]) for item in snippets}

    seen_tokens = set()

    def replace(match: re.Match[str]) -> str:
        snippet_id = match.group(1)
        full_token = match.group(0)
        if full_token in seen_tokens:
            raise ValueError(f"duplicated snippet token: {full_token}")
        seen_tokens.add(full_token)
        if snippet_id not in expansions:
            raise ValueError(f"unknown snippet token: {snippet_id}")
        return expansions[snippet_id]

    result = TOKEN.sub(replace, text)
    malformed = ANY_SNIPPET_TOKEN.search(result)
    if malformed:
        raise ValueError(f"malformed or unresolved snippet token: {malformed.group(0)}")
    unresolved = INTERNAL_TOKEN.search(result)
    if unresolved:
        raise ValueError(f"unresolved internal token: {unresolved.group(0)}")
    return result


def process(text: str, snippets_path: Path) -> str:
    return expand(text, snippets_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snippets", type=Path, default=DEFAULT_SNIPPETS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = sys.stdin.read()
    try:
        sys.stdout.write(expand(original, args.snippets))
    except Exception as error:
        print(f"Spokenly postprocessor failed closed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
