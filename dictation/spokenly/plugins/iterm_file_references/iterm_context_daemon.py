#!/usr/bin/env python3
"""Publish the currently focused iTerm2 pane for the Spokenly plugin.

Install this as an iTerm2 AutoLaunch Python script. It uses iTerm2's supported
Python API and writes only pane identity and process metadata to a private local
state file. Transcript text and project file contents are never read.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import secrets
import tempfile
import time
from pathlib import Path

import iterm2


STATE_VERSION = 1
DEFAULT_CONTEXT_STATE = (
    Path(tempfile.gettempdir()) / f"spokenly-iterm-context-{os.getuid()}.json"
)
CONTEXT_STATE = Path(
    os.environ.get("SPOKENLY_ITERM_CONTEXT_STATE", str(DEFAULT_CONTEXT_STATE))
).expanduser()
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 3.0
ERROR_LOG_INTERVAL_SECONDS = 60.0
DAEMON_LOG = Path.home() / "Library" / "Logs" / "Spokenly" / "iterm-context-daemon.log"
VARIABLES = (
    "tty",
    "jobPid",
    "processTitle",
    "path",
    "hostname",
    "sshIntegrationLevel",
)


@dataclass
class PublicationState:
    payload_key: str | None = None
    written_at: float = 0.0


_last_error_message: str | None = None
_last_error_at = 0.0


def log_daemon_error(error: Exception, now: float | None = None) -> None:
    """Log changed or periodic daemon failures without flooding the disk."""
    global _last_error_at, _last_error_message
    monotonic_now = time.monotonic() if now is None else now
    message = f"{type(error).__name__}: {error}"
    if (
        message == _last_error_message
        and monotonic_now - _last_error_at < ERROR_LOG_INTERVAL_SECONDS
    ):
        return
    _last_error_message = message
    _last_error_at = monotonic_now
    try:
        DAEMON_LOG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(
            DAEMON_LOG,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "message": message[:2000],
            }
            os.write(
                descriptor,
                (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"),
            )
        finally:
            os.close(descriptor)
    except Exception:
        return


def snapshot_key(value: dict[str, object]) -> str:
    return json.dumps(
        {key: item for key, item in value.items() if key != "observed_at"},
        sort_keys=True,
    )


def should_publish(
    value: dict[str, object],
    state: PublicationState,
    now: float,
) -> bool:
    return (
        snapshot_key(value) != state.payload_key
        or now - state.written_at >= HEARTBEAT_SECONDS
    )


def atomic_write(value: dict[str, object]) -> None:
    CONTEXT_STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONTEXT_STATE.with_name(
        f".{CONTEXT_STATE.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, CONTEXT_STATE)
    finally:
        temporary.unlink(missing_ok=True)


def empty_snapshot() -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "observed_at": time.time(),
    }


async def snapshot(connection: iterm2.Connection) -> dict[str, object]:
    # Focus can change while session variables are being fetched. Re-read the
    # active chain before publishing so a pane ID can never be paired with a
    # different pane's PID or working directory.
    for _attempt in range(3):
        app = await iterm2.async_get_app(connection)
        window = app.current_terminal_window
        if window is None or window.current_tab is None:
            return empty_snapshot()
        tab = window.current_tab
        session = tab.current_session
        if session is None:
            return empty_snapshot()

        values = await asyncio.gather(
            *(session.async_get_variable(name) for name in VARIABLES)
        )
        refreshed_app = await iterm2.async_get_app(connection)
        refreshed_window = refreshed_app.current_terminal_window
        refreshed_tab = refreshed_window.current_tab if refreshed_window else None
        refreshed_session = refreshed_tab.current_session if refreshed_tab else None
        if (
            refreshed_window is not None
            and refreshed_tab is not None
            and refreshed_session is not None
            and refreshed_window.window_id == window.window_id
            and refreshed_tab.tab_id == tab.tab_id
            and refreshed_session.session_id == session.session_id
        ):
            break
    else:
        return empty_snapshot()

    variables = dict(zip(VARIABLES, values))

    job_pid = variables.get("jobPid")
    try:
        job_pid = int(job_pid)
    except (TypeError, ValueError):
        job_pid = 0
    ssh_level = variables.get("sshIntegrationLevel")
    try:
        ssh_level = int(ssh_level or 0)
    except (TypeError, ValueError):
        ssh_level = 0

    return {
        "version": STATE_VERSION,
        "observed_at": time.time(),
        "window_id": window.window_id,
        "tab_id": tab.tab_id,
        "session_id": session.session_id,
        "tty": str(variables.get("tty") or ""),
        "job_pid": job_pid,
        "process_title": str(variables.get("processTitle") or ""),
        "path": str(variables.get("path") or ""),
        "hostname": str(variables.get("hostname") or ""),
        "ssh_integration_level": ssh_level,
    }


async def publish(
    connection: iterm2.Connection,
    lock: asyncio.Lock,
    state: PublicationState,
) -> None:
    async with lock:
        try:
            value = await snapshot(connection)
            now = time.monotonic()
            if should_publish(value, state, now):
                value["observed_at"] = time.time()
                atomic_write(value)
                state.payload_key = snapshot_key(value)
                state.written_at = now
        except Exception as error:
            # Never unlink the shared state here: a newly started daemon may
            # have replaced it already. Any prior snapshot expires within the
            # resolver's short freshness window and is then rejected.
            log_daemon_error(error)


async def monitor_focus(
    connection: iterm2.Connection,
    lock: asyncio.Lock,
    state: PublicationState,
) -> None:
    async with iterm2.FocusMonitor(connection) as monitor:
        while True:
            await monitor.async_get_next_update()
            await publish(connection, lock, state)


async def poll_context(
    connection: iterm2.Connection,
    lock: asyncio.Lock,
    state: PublicationState,
) -> None:
    while True:
        await publish(connection, lock, state)
        await asyncio.sleep(POLL_SECONDS)


async def main(connection: iterm2.Connection) -> None:
    lock = asyncio.Lock()
    state = PublicationState()
    await asyncio.gather(
        monitor_focus(connection, lock, state),
        poll_context(connection, lock, state),
    )


if __name__ == "__main__":
    iterm2.run_forever(main)
