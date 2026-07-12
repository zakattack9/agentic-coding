import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


DAEMON_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "iterm_file_references"
    / "iterm_context_daemon.py"
)


def load_daemon_module():
    fake_iterm2 = types.SimpleNamespace(Connection=object)
    spec = importlib.util.spec_from_file_location(
        "spokenly_test_iterm_context_daemon", DAEMON_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load daemon module")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(
        sys.modules,
        {"iterm2": fake_iterm2, spec.name: module},
    ):
        spec.loader.exec_module(module)
    return module


class ItermContextDaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = load_daemon_module()

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_change_only_publication_with_periodic_heartbeat(self):
        value = {"version": 1, "observed_at": 100.0, "session_id": "pane-a"}
        state = self.daemon.PublicationState()
        self.assertTrue(self.daemon.should_publish(value, state, 10.0))
        state.payload_key = self.daemon.snapshot_key(value)
        state.written_at = 10.0
        self.assertFalse(self.daemon.should_publish(value, state, 11.0))
        self.assertTrue(self.daemon.should_publish(value, state, 13.0))
        changed = {**value, "session_id": "pane-b"}
        self.assertTrue(self.daemon.should_publish(changed, state, 11.0))

    def test_publish_skips_unchanged_snapshot_until_heartbeat(self):
        value = {"version": 1, "observed_at": 100.0, "session_id": "pane-a"}

        async def exercise():
            state = self.daemon.PublicationState()
            lock = asyncio.Lock()
            with mock.patch.object(
                self.daemon, "snapshot", new=mock.AsyncMock(return_value=dict(value))
            ), mock.patch.object(
                self.daemon, "atomic_write"
            ) as write, mock.patch.object(
                self.daemon.time,
                "monotonic",
                side_effect=[10.0, 11.0, 13.0],
            ):
                await self.daemon.publish(object(), lock, state)
                await self.daemon.publish(object(), lock, state)
                await self.daemon.publish(object(), lock, state)
            self.assertEqual(write.call_count, 2)

        asyncio.run(exercise())

    def test_repeated_daemon_errors_are_throttled(self):
        log_path = Path(self.tempdir.name) / "daemon.log"
        self.daemon.DAEMON_LOG = log_path
        self.daemon._last_error_message = None
        self.daemon._last_error_at = 0.0
        self.daemon.log_daemon_error(RuntimeError("boom"), now=1.0)
        self.daemon.log_daemon_error(RuntimeError("boom"), now=2.0)
        self.daemon.log_daemon_error(RuntimeError("different"), now=3.0)
        self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(log_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
