#!/usr/bin/env python3
"""Publish the currently focused iTerm2 pane for the Spokenly plugin.

Install this as an iTerm2 AutoLaunch Python script. It uses iTerm2's supported
Python API and writes only pane identity and process metadata to a private local
state file. Transcript text and project file contents are never read.
"""

from __future__ import annotations

import asyncio
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
VARIABLES = (
    "tty",
    "jobPid",
    "processTitle",
    "path",
    "hostname",
    "sshIntegrationLevel",
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


async def snapshot(connection: iterm2.Connection) -> dict[str, object]:
    app = await iterm2.async_get_app(connection)
    window = app.current_terminal_window
    if window is None or window.current_tab is None:
        return {"version": STATE_VERSION, "observed_at": time.time()}
    tab = window.current_tab
    session = tab.current_session
    if session is None:
        return {"version": STATE_VERSION, "observed_at": time.time()}

    values = await asyncio.gather(
        *(session.async_get_variable(name) for name in VARIABLES)
    )
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


async def publish(connection: iterm2.Connection, lock: asyncio.Lock) -> None:
    async with lock:
        try:
            atomic_write(await snapshot(connection))
        except Exception:
            # A partial or stale state is more dangerous than no state. The
            # resolver rejects a missing/stale file and leaves dictation alone.
            CONTEXT_STATE.unlink(missing_ok=True)


async def monitor_focus(connection: iterm2.Connection, lock: asyncio.Lock) -> None:
    async with iterm2.FocusMonitor(connection) as monitor:
        while True:
            await monitor.async_get_next_update()
            await publish(connection, lock)


async def poll_context(connection: iterm2.Connection, lock: asyncio.Lock) -> None:
    while True:
        await publish(connection, lock)
        await asyncio.sleep(POLL_SECONDS)


async def main(connection: iterm2.Connection) -> None:
    lock = asyncio.Lock()
    try:
        await asyncio.gather(
            monitor_focus(connection, lock),
            poll_context(connection, lock),
        )
    finally:
        CONTEXT_STATE.unlink(missing_ok=True)


iterm2.run_forever(main)
