"""Opt-in extensions for the otherwise portable Spokenly processors."""

from __future__ import annotations

import os
import sys
from types import ModuleType


ITERM_FILE_REFERENCES_ENV = "SPOKENLY_ITERM_FILE_REFERENCES"


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
