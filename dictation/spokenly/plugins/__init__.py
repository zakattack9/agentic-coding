"""Opt-in extensions for the otherwise portable Spokenly processors."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
from types import ModuleType

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows portable mode
    fcntl = None  # type: ignore[assignment]


ITERM_FILE_REFERENCES_ENV = "SPOKENLY_ITERM_FILE_REFERENCES"
ITERM_FILE_REFERENCES_LOG_ENV = "SPOKENLY_ITERM_FILE_REFERENCE_LOG"
DEFAULT_ITERM_FILE_REFERENCES_LOG = (
    Path.home() / "Library" / "Logs" / "Spokenly" / "iterm-file-references.log"
)
MAX_LOG_BYTES = 512 * 1024
MAX_LOG_FIELD_LENGTH = 2_000


def _enabled(value: str | None) -> bool:
    return bool(value and value.strip().casefold() in {"1", "true", "yes", "on"})


def iterm_file_references_enabled() -> bool:
    """Require explicit opt-in and macOS before importing iTerm-specific code."""
    return sys.platform == "darwin" and _enabled(
        os.environ.get(ITERM_FILE_REFERENCES_ENV)
    )


def load_iterm_file_references() -> ModuleType | None:
    if not iterm_file_references_enabled():
        return None
    from plugins.iterm_file_references import plugin

    return plugin


def log_iterm_file_reference_event(
    stage: str,
    message: str,
    **fields: object,
) -> None:
    """Append a private diagnostic record without affecting dictation."""
    try:
        path = Path(
            os.environ.get(
                ITERM_FILE_REFERENCES_LOG_ENV,
                str(DEFAULT_ITERM_FILE_REFERENCES_LOG),
            )
        ).expanduser()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        lock_path = path.with_name(path.name + ".lock")
        lock_descriptor = os.open(lock_path, flags, 0o600)
        try:
            os.fchmod(lock_descriptor, 0o600)
            if fcntl is not None:
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            if path.is_symlink():
                return
            if path.exists():
                metadata = path.stat()
                if not stat.S_ISREG(metadata.st_mode):
                    return
                if metadata.st_size >= MAX_LOG_BYTES:
                    backup = path.with_name(path.name + ".1")
                    if backup.is_symlink():
                        return
                    if backup.exists():
                        backup.unlink()
                    path.replace(backup)

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "stage": str(stage)[:MAX_LOG_FIELD_LENGTH],
                "message": str(message)[:MAX_LOG_FIELD_LENGTH],
            }
            record.update(
                {
                    str(key)[:128]: str(value)[:MAX_LOG_FIELD_LENGTH]
                    for key, value in fields.items()
                }
            )
            append_flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            append_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, append_flags, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                os.write(
                    descriptor,
                    (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"),
                )
            finally:
                os.close(descriptor)
        finally:
            os.close(lock_descriptor)
    except Exception:
        # Diagnostics are optional and must never alter script exit status or
        # prevent transcript insertion.
        return
