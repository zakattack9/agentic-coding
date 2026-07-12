import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "iterm_file_references"
INSTALL = PLUGIN_DIR / "install.sh"
UNINSTALL = PLUGIN_DIR / "uninstall.sh"
SOURCE = PLUGIN_DIR / "iterm_context_daemon.py"


@unittest.skipUnless(
    sys.platform == "darwin" and (Path("/Applications/iTerm.app").is_dir()),
    "macOS iTerm installation",
)
class ItermFileReferenceInstallTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)
        self.environment = os.environ.copy()
        self.environment["HOME"] = str(self.home)
        self.target_dir = (
            self.home
            / "Library"
            / "Application Support"
            / "iTerm2"
            / "Scripts"
            / "AutoLaunch"
        )
        self.target = self.target_dir / "spokenly_iterm_context.py"
        self.marker = self.target_dir / ".spokenly_iterm_context.managed"

    def tearDown(self):
        self.tempdir.cleanup()

    def run_script(self, script: Path, *arguments: str):
        return subprocess.run(
            [str(script), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.environment,
        )

    def test_repair_updates_unmarked_stale_repository_symlink(self):
        first = self.run_script(INSTALL)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.target.resolve(), SOURCE.resolve())
        self.target.unlink()
        self.marker.unlink()
        stale = Path(
            "/old/repository/dictation/spokenly/plugins/"
            "iterm_file_references/iterm_context_daemon.py"
        )
        self.target.symlink_to(stale)

        refused = self.run_script(INSTALL)
        self.assertNotEqual(refused.returncode, 0)
        repaired = self.run_script(INSTALL, "--repair")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(self.target.resolve(), SOURCE.resolve())
        self.assertEqual(self.marker.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            self.marker.read_text(encoding="utf-8").splitlines()[1], str(SOURCE)
        )

    def test_repair_refuses_unrelated_symlink(self):
        self.target_dir.mkdir(parents=True)
        self.target.symlink_to("/unrelated/tool.py")
        repaired = self.run_script(INSTALL, "--repair")
        self.assertNotEqual(repaired.returncode, 0)
        self.assertEqual(os.readlink(self.target), "/unrelated/tool.py")

    def test_marker_does_not_authorize_replacing_an_unrelated_symlink(self):
        installed = self.run_script(INSTALL)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.target.unlink()
        self.target.symlink_to("/unrelated/tool.py")
        repaired = self.run_script(INSTALL)
        self.assertNotEqual(repaired.returncode, 0)
        self.assertEqual(os.readlink(self.target), "/unrelated/tool.py")

    def test_uninstall_accepts_marked_relocated_symlink(self):
        installed = self.run_script(INSTALL)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.target.unlink()
        stale = Path(
            "/old/repository/dictation/spokenly/plugins/"
            "iterm_file_references/iterm_context_daemon.py"
        )
        self.target.symlink_to(stale)
        self.marker.write_text(
            f"spokenly-iterm-file-references-v1\n{stale}\n",
            encoding="utf-8",
        )
        removed = self.run_script(UNINSTALL)
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.is_symlink())
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
