#!/usr/bin/env python3
"""Private, bounded, opt-in diagnostics for ParaQwen Dictation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time
from typing import Iterable


MAX_RECORDS = 20
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_DIRECTORY = Path.home() / ".local" / "state" / "paraqwen-dictation" / "diagnostics"
TRUTHY = {"1", "true", "yes", "on"}


def enabled() -> bool:
    return os.environ.get("PARAQWEN_DIAGNOSTICS", "").casefold() in TRUTHY


def directory() -> Path:
    return Path(
        os.environ.get("PARAQWEN_DIAGNOSTIC_DIR", str(DEFAULT_DIRECTORY))
    ).expanduser()


def _redact(text: str, expansion_values: Iterable[str] = ()) -> str:
    result = text
    for index, value in enumerate(sorted(set(expansion_values), key=len, reverse=True), 1):
        if not value:
            continue
        digest = hashlib.blake2s(value.encode(), digest_size=4).hexdigest()
        result = result.replace(value, f"[EXPANSION:{index}:{digest}]")
    home = str(Path.home())
    if home:
        result = result.replace(home, "~")
    # Do not retain obvious credentials embedded in URLs or environment-like text.
    result = re.sub(
        r"(?i)(token|secret|password|api[_-]?key)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        result,
    )
    return result


def _redact_value(value: object, expansion_values: Iterable[str]) -> object:
    if isinstance(value, str):
        return _redact(value, expansion_values)
    if isinstance(value, dict):
        return {
            str(key): (
                "[OMITTED]"
                if "audio" in str(key).casefold()
                else _redact_value(item, expansion_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, expansion_values) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[BINARY OMITTED]"
    return value


def _prepare_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("diagnostic path is not an owner directory")
    path.chmod(0o700)


def _rotate(path: Path) -> None:
    now = time.time()
    records = []
    for item in path.glob("*.json"):
        if not re.fullmatch(r"[a-f0-9]{24}\.json", item.name):
            continue
        try:
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                continue
            if now - info.st_mtime > MAX_AGE_SECONDS:
                item.unlink(missing_ok=True)
            else:
                records.append((info.st_mtime, item))
        except OSError:
            continue
    records.sort(reverse=True)
    for _modified, item in records[MAX_RECORDS - 1 :]:
        try:
            item.unlink(missing_ok=True)
        except OSError:
            pass


def new_trace_id() -> str | None:
    return secrets.token_hex(12) if enabled() else None


def write_trace(
    trace_id: str | None,
    *,
    stages: dict[str, str] | None = None,
    metadata: dict[str, object] | None = None,
    validators: dict[str, object] | None = None,
    failure_reason: str | None = None,
    expansion_values: Iterable[str] = (),
) -> None:
    """Create or update one trace. All failures are deliberately ignored."""
    if not enabled() or not trace_id or not re.fullmatch(r"[a-f0-9]{24}", trace_id):
        return
    try:
        expansion_values = tuple(expansion_values)
        path = directory()
        _prepare_directory(path)
        _rotate(path)
        target = path / f"{trace_id}.json"
        record: dict[str, object] = {
            "version": 1,
            "trace_id": trace_id,
            "updated_at": time.time(),
            "stages": {},
            "metadata": {},
            "validators": {},
        }
        if target.exists():
            info = target.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                return
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("trace_id") == trace_id:
                record.update(loaded)
                record["updated_at"] = time.time()
        stage_record = record.setdefault("stages", {})
        if isinstance(stage_record, dict):
            for name, value in (stages or {}).items():
                stage_record[name] = _redact(value, expansion_values)
        metadata_record = record.setdefault("metadata", {})
        if isinstance(metadata_record, dict):
            redacted_metadata = _redact_value(metadata or {}, expansion_values)
            if isinstance(redacted_metadata, dict):
                metadata_record.update(redacted_metadata)
        validator_record = record.setdefault("validators", {})
        if isinstance(validator_record, dict):
            redacted_validators = _redact_value(validators or {}, expansion_values)
            if isinstance(redacted_validators, dict):
                validator_record.update(redacted_validators)
        if failure_reason is not None:
            record["failure_reason"] = _redact(failure_reason, expansion_values)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{trace_id}.", suffix=".tmp", dir=path
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                descriptor = -1
                json.dump(record, output, ensure_ascii=False, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        return
