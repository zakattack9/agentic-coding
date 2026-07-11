import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import post_ai  # noqa: E402
import pre_ai  # noqa: E402
from plugins import iterm_file_references_enabled  # noqa: E402
from plugins.iterm_file_references import plugin  # noqa: E402


class ItermFileReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.context_state = self.base / "iterm-context.json"
        self.pending_dir = self.base / "pending"
        self.snippets = self.base / "snippets.json"
        self.snippets.write_text("[]", encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def make_repo(self, name: str = "repo") -> Path:
        root = self.base / name
        root.mkdir()
        self.git(root, "init", "-q")
        return root

    def write_context(
        self,
        cwd: Path,
        *,
        session_id: str = "session-a",
        tab_id: str = "tab-a",
        window_id: str = "window-a",
        process_title: str = "codex",
        job_pid: int | None = None,
        ssh_level: int = 0,
    ) -> None:
        self.context_state.write_text(
            json.dumps(
                {
                    "version": 1,
                    "observed_at": time.time(),
                    "window_id": window_id,
                    "tab_id": tab_id,
                    "session_id": session_id,
                    "tty": f"/dev/ttys-{session_id}",
                    "job_pid": job_pid or os.getpid(),
                    "process_title": process_title,
                    "path": str(cwd),
                    "hostname": "local.test",
                    "ssh_integration_level": ssh_level,
                }
            ),
            encoding="utf-8",
        )
        self.context_state.chmod(0o600)

    def prepare(self, text: str) -> plugin.PreparedReferences:
        return plugin.prepare_file_references(
            text,
            "iTerm2",
            context_path=self.context_state,
            pending_dir=self.pending_dir,
            verify_process=False,
            max_context_age_seconds=60,
        )

    def load(self, model_output: str) -> plugin.PendingReferences | None:
        return plugin.load_pending_file_references(
            model_output,
            "iTerm2",
            context_path=self.context_state,
            pending_dir=self.pending_dir,
            verify_process=False,
            max_context_age_seconds=60,
        )

    def round_trip(self, text: str) -> str:
        prepared = self.prepare(text)
        protected = pre_ai.process(text, self.snippets, prepared.snippets)
        pending = self.load(protected)
        try:
            return post_ai.expand(
                protected,
                self.snippets,
                extra_expansions=pending.expansions if pending else None,
                expected_expansion_counts=(
                    pending.expected_counts if pending else None
                ),
            )
        finally:
            plugin.finish_pending_file_references(pending)

    def test_plugin_requires_explicit_opt_in_and_macos(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertFalse(iterm_file_references_enabled())
            with mock.patch.object(sys, "platform", "linux"):
                os.environ["SPOKENLY_ITERM_FILE_REFERENCES"] = "1"
                self.assertFalse(iterm_file_references_enabled())
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertTrue(iterm_file_references_enabled())

    def test_enabled_but_unconfigured_plugin_leaves_portable_pipeline_available(self):
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "1",
                "SPOKENLY_ACTIVE_APP": "iTerm2",
                "SPOKENLY_ITERM_CONTEXT_STATE": str(self.base / "missing.json"),
                "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR": str(self.pending_dir),
            }
        )
        source = "Review at file missing dot py."
        pre = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "pre_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input=source,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(pre.returncode, 0)
        self.assertEqual(pre.stdout, source)
        self.assertIn("unavailable", pre.stderr)

        post = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "post_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input=pre.stdout,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(post.returncode, 0)
        self.assertEqual(post.stdout, source)

    @unittest.skipUnless(sys.platform == "darwin", "macOS plugin integration")
    def test_portable_entry_points_load_enabled_plugin_end_to_end(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        foreground = subprocess.Popen(
            ["codex", "30"],
            executable="/bin/sleep",
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(foreground.wait)
        self.addCleanup(foreground.terminate)
        self.write_context(root, job_pid=foreground.pid)
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "1",
                "SPOKENLY_ACTIVE_APP": "iTerm2",
                "SPOKENLY_ITERM_CONTEXT_STATE": str(self.context_state),
                "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR": str(self.pending_dir),
            }
        )
        source = "Review at file main dot py now."
        pre = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "pre_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input=source,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(pre.returncode, 0, pre.stderr)
        self.assertIn("SPK_SNIPPET_FILE_REF_", pre.stdout)

        self.write_context(root, job_pid=foreground.pid)
        post = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "post_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input=pre.stdout,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(post.stdout, "Review @main.py now.")

    def test_nested_cwd_renders_localized_reference(self):
        root = self.make_repo()
        target = root / "src" / "components" / "Button.tsx"
        target.parent.mkdir(parents=True)
        target.write_text("export const Button = 1;", encoding="utf-8")
        cwd = root / "tests" / "integration"
        cwd.mkdir(parents=True)
        self.write_context(cwd)

        self.assertEqual(
            self.round_trip("Review at file button dot t s x before changing it."),
            "Review @../../src/components/Button.tsx before changing it.",
        )

    def test_literal_at_reference_is_supported(self):
        root = self.make_repo()
        (root / "README.md").write_text("read me", encoding="utf-8")
        self.write_context(root, process_title="claude")
        self.assertEqual(
            self.round_trip("Explain @README.md and keep the details."),
            "Explain @README.md and keep the details.",
        )

    def test_directory_qualifier_disambiguates_duplicate_basenames(self):
        root = self.make_repo()
        for directory in ("client", "server"):
            path = root / directory / "config.py"
            path.parent.mkdir()
            path.write_text(directory, encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Inspect at file server slash config dot pie first."),
            "Inspect @server/config.py first.",
        )

    def test_ambiguous_duplicate_basename_is_not_guessed(self):
        root = self.make_repo()
        for directory in ("client", "server"):
            path = root / directory / "config.py"
            path.parent.mkdir()
            path.write_text(directory, encoding="utf-8")
        self.write_context(root)
        prepared = self.prepare("Inspect at file config dot py first.")
        self.assertEqual(prepared.snippets, [])
        self.assertTrue(any("ambiguous" in warning for warning in prepared.warnings))

    def test_unique_candidate_under_cwd_breaks_project_wide_tie(self):
        root = self.make_repo()
        for directory in ("client", "server"):
            path = root / directory / "config.py"
            path.parent.mkdir()
            path.write_text(directory, encoding="utf-8")
        self.write_context(root / "server")
        self.assertEqual(
            self.round_trip("Inspect at file config dot py first."),
            "Inspect @config.py first.",
        )

    def test_untracked_nonignored_files_are_indexed_and_ignored_files_are_not(self):
        root = self.make_repo()
        (root / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        (root / "draft.py").write_text("draft", encoding="utf-8")
        (root / "secret.py").write_text("secret", encoding="utf-8")
        self.write_context(root)
        files = plugin.list_project_files(root)
        paths = {item.relative_path.as_posix() for item in files}
        self.assertIn("draft.py", paths)
        self.assertNotIn("secret.py", paths)

    def test_symlink_outside_worktree_is_not_referenceable(self):
        root = self.make_repo()
        outside = self.base / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (root / "outside-link.txt").symlink_to(outside)
        self.write_context(root)
        files = plugin.list_project_files(root)
        self.assertNotIn(
            "outside-link.txt",
            {item.relative_path.as_posix() for item in files},
        )

    def test_regular_branch_uses_current_checkout(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root)
        context = plugin.resolve_project_context(
            "iTerm2",
            self.context_state,
            verify_process=False,
            max_age_seconds=60,
        )
        self.assertEqual(context.project_root, root.resolve())

    def test_linked_worktree_is_scoped_to_linked_worktree_root(self):
        root = self.make_repo("primary")
        self.git(root, "config", "user.email", "test@example.com")
        self.git(root, "config", "user.name", "Test User")
        (root / "base.txt").write_text("base", encoding="utf-8")
        self.git(root, "add", "base.txt")
        self.git(root, "commit", "-qm", "base")
        self.git(root, "branch", "feature")
        worktree = self.base / "linked-worktree"
        self.git(root, "worktree", "add", "-q", str(worktree), "feature")
        nested = worktree / "nested"
        nested.mkdir()
        self.write_context(nested)

        context = plugin.resolve_project_context(
            "iTerm2",
            self.context_state,
            verify_process=False,
            max_age_seconds=60,
        )
        self.assertEqual(context.project_root, worktree.resolve())
        self.assertNotEqual(context.project_root, root.resolve())

    def test_multiple_panes_keep_independent_pending_state(self):
        repo_a = self.make_repo("repo-a")
        repo_b = self.make_repo("repo-b")
        (repo_a / "alpha.py").write_text("a", encoding="utf-8")
        (repo_b / "beta.py").write_text("b", encoding="utf-8")

        self.write_context(repo_a, session_id="pane-a")
        prepared_a = self.prepare("Review at file alpha dot py.")
        protected_a = pre_ai.process(
            "Review at file alpha dot py.", self.snippets, prepared_a.snippets
        )
        self.write_context(repo_b, session_id="pane-b", tab_id="tab-b")
        prepared_b = self.prepare("Review at file beta dot py.")
        protected_b = pre_ai.process(
            "Review at file beta dot py.", self.snippets, prepared_b.snippets
        )

        pending_b = self.load(protected_b)
        self.assertEqual(set(pending_b.expansions.values()), {"@beta.py"})
        plugin.finish_pending_file_references(pending_b)
        self.write_context(repo_a, session_id="pane-a")
        pending_a = self.load(protected_a)
        self.assertEqual(set(pending_a.expansions.values()), {"@alpha.py"})
        plugin.finish_pending_file_references(pending_a)

    def test_switching_panes_during_ai_fails_closed(self):
        repo_a = self.make_repo("repo-a")
        repo_b = self.make_repo("repo-b")
        (repo_a / "alpha.py").write_text("a", encoding="utf-8")
        (repo_b / "beta.py").write_text("b", encoding="utf-8")
        self.write_context(repo_a, session_id="pane-a")
        prepared = self.prepare("Review at file alpha dot py.")
        protected = pre_ai.process(
            "Review at file alpha dot py.", self.snippets, prepared.snippets
        )
        self.write_context(repo_b, session_id="pane-b", tab_id="tab-b")
        with self.assertRaisesRegex(ValueError, "pane|workspace"):
            self.load(protected)

    def test_switching_panes_fails_closed_even_if_model_drops_all_tokens(self):
        repo_a = self.make_repo("repo-a")
        repo_b = self.make_repo("repo-b")
        (repo_a / "alpha.py").write_text("a", encoding="utf-8")
        (repo_b / "beta.py").write_text("b", encoding="utf-8")
        self.write_context(repo_a, session_id="pane-a")
        self.prepare("Review at file alpha dot py.")
        self.write_context(repo_b, session_id="pane-b", tab_id="tab-b")
        with self.assertRaisesRegex(ValueError, "pane|workspace"):
            self.load("Review the file.")

    def test_restarting_harness_during_ai_fails_closed(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root, job_pid=111)
        prepared = self.prepare("Review at file main dot py.")
        protected = pre_ai.process(
            "Review at file main dot py.", self.snippets, prepared.snippets
        )
        self.write_context(root, job_pid=222)
        with self.assertRaisesRegex(ValueError, "pane|workspace"):
            self.load(protected)

    def test_missing_model_structure_fails_closed(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root)
        self.prepare("Review at file main dot py.")
        pending = self.load("Review the file.")
        try:
            with self.assertRaisesRegex(ValueError, "missing protected"):
                post_ai.expand(
                    "Review the file.",
                    self.snippets,
                    extra_expansions=pending.expansions,
                    expected_expansion_counts=pending.expected_counts,
                )
        finally:
            plugin.finish_pending_file_references(pending)

    def test_dropped_standalone_token_is_recovered_from_segment_metadata(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root)
        prepared = self.prepare("Review at file main dot py now.")
        protected = pre_ai.process(
            "Review at file main dot py now.", self.snippets, prepared.snippets
        )
        token = re_search_file_token(protected)
        damaged = protected.replace(token, "")
        pending = self.load(damaged)
        try:
            self.assertEqual(
                post_ai.expand(
                    damaged,
                    self.snippets,
                    extra_expansions=pending.expansions,
                    expected_expansion_counts=pending.expected_counts,
                ),
                "Review @main.py now.",
            )
        finally:
            plugin.finish_pending_file_references(pending)

    def test_static_snippet_and_file_reference_keep_textual_order(self):
        root = self.make_repo()
        (root / "README.md").write_text("read", encoding="utf-8")
        self.snippets.write_text(
            json.dumps(
                [
                    {
                        "id": "SIGNATURE",
                        "triggers": ["insert signature"],
                        "text": "Best,\nTester",
                        "consume_trailing_punctuation": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.write_context(root)
        self.assertEqual(
            self.round_trip(
                "Review at file readme dot markdown then insert signature."
            ),
            "Review @README.md then Best,\nTester",
        )

    def test_static_trigger_cannot_shadow_dynamic_reference(self):
        root = self.make_repo()
        (root / "README.md").write_text("read", encoding="utf-8")
        self.snippets.write_text(
            json.dumps(
                [
                    {
                        "id": "CONFLICT",
                        "triggers": ["at file readme dot markdown"],
                        "text": "wrong",
                    }
                ]
            ),
            encoding="utf-8",
        )
        self.write_context(root)
        prepared = self.prepare("Review at file readme dot markdown.")
        with self.assertRaisesRegex(ValueError, "duplicate protected trigger"):
            pre_ai.process(
                "Review at file readme dot markdown.",
                self.snippets,
                prepared.snippets,
            )
        plugin.finish_pending_file_references(prepared.pending)

    def test_repeated_reference_occurrences_are_counted(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Compare at file main dot py with at file main dot py."),
            "Compare @main.py with @main.py.",
        )

    def test_file_with_spaces_keeps_exact_relative_path(self):
        root = self.make_repo()
        (root / "My Config.json").write_text("{}", encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Review at file my config dot json carefully."),
            "Review @My Config.json carefully.",
        )

    def test_non_git_directory_is_not_treated_as_a_project(self):
        directory = self.base / "not-git"
        directory.mkdir()
        (directory / "main.py").write_text("main", encoding="utf-8")
        self.write_context(directory)
        with self.assertRaisesRegex(ValueError, "Git worktree"):
            self.prepare("Review at file main dot py.")

    def test_ssh_context_is_rejected(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root, ssh_level=1)
        with self.assertRaisesRegex(ValueError, "remote"):
            self.prepare("Review at file main dot py.")

    def test_unrelated_foreground_process_is_rejected(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root, process_title="vim")
        with self.assertRaisesRegex(ValueError, "Codex or Claude"):
            self.prepare("Review at file main dot py.")


def re_search_file_token(text: str) -> str:
    import re

    match = re.search(r"\[\[SPK_SNIPPET_FILE_REF_[^\]]+\]\]", text)
    if match is None:
        raise AssertionError("protected file-reference token not found")
    return match.group(0)


if __name__ == "__main__":
    unittest.main()
