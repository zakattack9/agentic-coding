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
if os.environ.get("PARAQWEN_DIAGNOSTICS", "").casefold() in {"1", "true", "yes", "on"}:
    from diagnostics import new_trace_id, write_trace  # noqa: E402
else:
    def new_trace_id() -> None:
        return None

    def write_trace(*_args, **_kwargs) -> None:
        return None
from repair_protocol import (  # noqa: E402
    PreparedRepairs,
    TriggerSpan,
    build_state,
    deterministic_protected_repairs,
    manifest_digest,
    prepare_repairs,
    preserve_internal_literals,
    remove_semantic_commands,
    resolve_state_sources,
    strip_repair_framing,
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
          | never\s*mind(?:\s+that)?(?=\s*(?:[,.!?;:]|$))
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
DIRECTIVE_PROBE = re.compile(
    r"\b(?:delete|remove|erase|drop|take|scratch|never|forget|ignore|undo|"
    r"cancel|new|paragraph|line|start|next|make|format|turn|bullet|put|number)\b",
    re.IGNORECASE,
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


def apply_directives(text: str, *, emit_semantic_tokens: bool = True) -> str:
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
                if not emit_semantic_tokens:
                    continue
                new_output = add_token(candidate, TOKENS["delete_sentence"])
        elif kind == "delete_phrase":
            success, new_output = delete_last_phrase(candidate)
            if not success:
                if not emit_semantic_tokens:
                    continue
                new_output = add_token(candidate, TOKENS["delete_phrase"])
        elif kind == "delete_word":
            success, new_output = delete_last_word(candidate)
            if not success:
                continue
        elif kind == "discard":
            success, new_output = delete_last_sentence(candidate)
            if not success:
                # Preserve the spoken cue so the typed repair planner can
                # bound a phrase-level discard. A targetless cue stays literal.
                continue
        elif kind == "new_paragraph":
            new_output = candidate.rstrip() + "\n\n"
        elif kind == "new_line":
            new_output = candidate.rstrip() + "\n"
        elif kind == "bullet_list":
            if not emit_semantic_tokens:
                continue
            new_output = add_token(candidate, TOKENS["bullets"])
        elif kind == "numbered_list":
            if not emit_semantic_tokens:
                continue
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


def normalize(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    return text.strip()


def find_trigger_spans(
    text: str, snippets: Iterable[Dict[str, object]]
) -> list[TriggerSpan]:
    pattern, metadata = snippet_matcher(snippets)
    if pattern is None:
        return []
    spans = []
    for match in pattern.finditer(text):
        group = match.lastgroup
        if group is None:
            continue
        item = metadata[group]
        spans.append(
            TriggerSpan(
                match.start(), match.end(), str(item["id"]), match.group(0)
            )
        )
    return spans


def prepare_process(
    text: str,
    snippets_path: Path,
    extra_snippets: Iterable[Dict[str, object]] = (),
) -> tuple[str, PreparedRepairs, list[Dict[str, object]]]:
    snippets = merge_snippets(snippets_path, extra_snippets)
    original = text.replace("\r\n", "\n").replace("\r", "\n")
    trigger_spans = find_trigger_spans(original, snippets)
    text, protected_edits = deterministic_protected_repairs(
        original, trigger_spans
    )
    text, source_literals = preserve_internal_literals(text)
    if DIRECTIVE_PROBE.search(text):
        model_text = apply_directives(text)
        safe_text = apply_directives(text, emit_semantic_tokens=False)
    else:
        model_text = safe_text = text
    model_trigger_spans = find_trigger_spans(model_text, snippets)
    prepared = prepare_repairs(
        model_text,
        source_literals,
        [(span.start, span.end) for span in model_trigger_spans],
    )
    safe_prepared = (
        prepared
        if safe_text == model_text
        else prepare_repairs(
            safe_text,
            source_literals,
            [
                (span.start, span.end)
                for span in find_trigger_spans(safe_text, snippets)
            ],
        )
    )
    prepared.raw_source = original
    prepared.validation_source = remove_semantic_commands(prepared.safe_source)
    prepared.safe_source = safe_prepared.safe_source
    prepared.deterministic_edits = (
        protected_edits + safe_prepared.deterministic_edits
    )
    if trigger_spans or model_text != text or prepared.deterministic_edits:
        protected = protect_snippets(prepared.framed_source, snippets)
        processed = frame_snippet_segments(normalize(protected))
    else:
        processed = normalize(prepared.framed_source)
    return processed, prepared, snippets


def process(
    text: str,
    snippets_path: Path,
    extra_snippets: Iterable[Dict[str, object]] = (),
) -> str:
    processed, _prepared, _snippets = prepare_process(
        text, snippets_path, extra_snippets
    )
    return processed


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
    repair_state: dict[str, object] | None = None,
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
            payload = {
                    "version": 1,
                    "created_at": time.time(),
                    "file_nonce": file_nonce,
                    "expected_counts": expected_counts,
                    "verified_text": verified_text.rstrip(),
                    "portable_text": portable_text.rstrip(),
                }
            if repair_state is not None:
                payload = repair_state
            json.dump(payload, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, state_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def consume_source_recovery_state(
    state_path: Path = DEFAULT_SOURCE_RECOVERY_STATE,
    max_age_seconds: float = 120.0,
) -> dict[str, object] | None:
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(state_path, flags)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            return None
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            descriptor = -1
            data = json.load(source)
    except (FileNotFoundError, OSError, ValueError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        clear_source_recovery_state(state_path)

    if not isinstance(data, dict) or data.get("version") not in {1, 2}:
        return None
    if data.get("version") == 2:
        try:
            data = resolve_state_sources(data)
        except ValueError:
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
    if data.get("version") == 2:
        if data.get("uid") != os.getuid():
            return None
        if not all(
            isinstance(data.get(field), str)
            for field in (
                "raw_source",
                "safe_source",
                "validation_source",
                "framed_source",
                "prompt_config_digest",
            )
        ):
            return None
        repair_nonce = data.get("repair_nonce")
        regions = data.get("repair_regions")
        if data.get("repair_schema") != 2 or not isinstance(regions, list):
            return None
        if repair_nonce is None and regions:
            return None
        if repair_nonce is not None and (
            not isinstance(repair_nonce, str)
            or not re.fullmatch(r"[A-F0-9]{16}", repair_nonce)
            or not regions
        ):
            return None
        expansion_occurrences = data.get("expansion_occurrences")
        if not isinstance(expansion_occurrences, list) or not all(
            isinstance(item, dict)
            and set(item) == {"id", "count"}
            and isinstance(item["id"], str)
            and isinstance(item["count"], int)
            and item["count"] > 0
            for item in expansion_occurrences
        ):
            return None
        occurrence_counts = {
            str(item["id"]): int(item["count"])
            for item in expansion_occurrences
        }
        if occurrence_counts != expected_counts:
            return None
    return data


def record_pending_slash_commands(
    processed: str,
    snippets_path: Path,
    state_path: Path = DEFAULT_SLASH_STATE,
) -> None:
    """Record ordered slash snippets for one-shot post-AI recovery."""
    clear_pending_slash_commands(state_path)
    if not SNIPPET_TOKEN.search(processed):
        return
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

    descriptor = -1
    temporary: Path | None = None
    try:
        state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.", suffix=".tmp", dir=state_path.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            json.dump({"commands": commands, "created_at": time.time()}, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, state_path)
    except OSError:
        # The in-band framing remains authoritative when recovery state cannot
        # be persisted.
        pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if temporary is not None:
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
    started_at = time.perf_counter()
    args = parse_args()
    original = sys.stdin.read()
    diagnostic_trace_id = new_trace_id()
    source_recovery_path = Path(
        os.environ.get(
            "SPOKENLY_SOURCE_RECOVERY_STATE",
            str(DEFAULT_SOURCE_RECOVERY_STATE),
        )
    ).expanduser()
    slash_state_path = Path(
        os.environ.get("SPOKENLY_SLASH_SNIPPET_STATE", str(DEFAULT_SLASH_STATE))
    ).expanduser()
    clear_pending_slash_commands(slash_state_path)
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
        processed, prepared_repairs, all_snippets = prepare_process(
            original, args.snippets, extra_snippets
        )
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
        sys.stdout.write(original.rstrip())
        return 0
    try:
        verified_snippets = all_snippets
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
        prompt_path = SPOKENLY_DIR / "prompts" / "qwen-prompt.md"
        prompt_text = (
            prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        )
        snippets_text = (
            args.snippets.read_text(encoding="utf-8")
            if args.snippets.exists()
            else ""
        )
        if expected_counts:
            portable_snippets = load_snippets(args.snippets)
            verified_text = expand_snippets_in_source(
                prepared_repairs.safe_source, verified_snippets
            )
            portable_text = expand_snippets_in_source(
                prepared_repairs.safe_source, portable_snippets
            )
            framed_source = remove_semantic_commands(
                expand_snippets_in_source(
                    prepared_repairs.framed_source, verified_snippets
                )
            )
            validation_source = expand_snippets_in_source(
                prepared_repairs.validation_source, verified_snippets
            )
        else:
            verified_text = portable_text = prepared_repairs.safe_source.rstrip()
            framed_source = remove_semantic_commands(
                prepared_repairs.framed_source
            )
            validation_source = prepared_repairs.validation_source.rstrip()
        repair_state = build_state(
            prepared_repairs,
            framed_source=framed_source,
            verified_text=verified_text,
            portable_text=portable_text,
            file_nonce=file_nonce,
            expected_counts=expected_counts,
            prompt_config_digest=manifest_digest(prompt_text, snippets_text),
            diagnostic_trace_id=diagnostic_trace_id,
            validation_source=validation_source,
        )
        record_source_recovery_state(
            verified_text,
            portable_text,
            file_nonce,
            expected_counts,
            state_path=source_recovery_path,
            repair_state=repair_state,
        )
        write_trace(
            diagnostic_trace_id,
            stages={"raw": original, "pre": processed},
            metadata={
                "pre_ms": round((time.perf_counter() - started_at) * 1000, 3),
                "repair_nonce": prepared_repairs.nonce,
                "regions": [
                    {
                        "number": item["number"],
                        "type": item["type"],
                        "source_start": item["source_start"],
                        "source_end": item["source_end"],
                    }
                    for item in prepared_repairs.regions
                ],
                "prompt_config_digest": repair_state["prompt_config_digest"],
            },
            expansion_values=[str(item["text"]) for item in verified_snippets],
        )
    except Exception as error:
        log_iterm_file_reference_event("pre.source_recovery", str(error))
        # Never emit model-assisted regions without a committed manifest.
        if "prepared_repairs" in locals() and (
            prepared_repairs.has_model_regions or prepared_repairs.literal_shields
        ):
            processed = strip_repair_framing(processed, prepared_repairs.manifest())
        write_trace(
            diagnostic_trace_id,
            stages={"raw": original, "pre": processed},
            failure_reason=f"state persistence degraded: {error}",
        )
    # Optional recovery-state I/O must not discard successful preprocessing.
    try:
        record_pending_slash_commands(processed, args.snippets, slash_state_path)
    except Exception as error:
        log_iterm_file_reference_event("pre.slash_recovery", str(error))
    sys.stdout.write(processed.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
