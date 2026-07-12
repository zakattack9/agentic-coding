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
from plugins import (  # noqa: E402
    iterm_file_references_enabled,
    log_iterm_file_reference_event,
)
from plugins.iterm_file_references import plugin  # noqa: E402


class ItermFileReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.context_state = self.base / "iterm-context.json"
        self.pending_dir = self.base / "pending"
        self.log_path = self.base / "iterm-file-references.log"
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

    def test_diagnostic_log_is_private_and_structured(self):
        with mock.patch.dict(
            os.environ,
            {"SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path)},
            clear=False,
        ):
            log_iterm_file_reference_event(
                "test.stage", "diagnostic message", detail="context"
            )
        record = json.loads(self.log_path.read_text(encoding="utf-8"))
        self.assertEqual(record["stage"], "test.stage")
        self.assertEqual(record["message"], "diagnostic message")
        self.assertEqual(record["detail"], "context")
        self.assertEqual(self.log_path.stat().st_mode & 0o777, 0o600)

    def test_postprocessor_main_fails_forward_without_internal_tokens(self):
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "0",
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path),
            }
        )
        post = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "post_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input="Text [[SPK_CMD_BULLET_LIST]]",
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(post.stdout, "Text")
        self.assertEqual(post.stderr, "")
        self.assertIn("post.core_fallback", self.log_path.read_text(encoding="utf-8"))

    def test_iterm_application_name_variants_are_accepted(self):
        for application_name in (
            "iTerm",
            "iTerm2",
            "iTerm.app",
            "iTerm2.app",
            "com.googlecode.iterm2",
            "/Applications/iTerm.app",
        ):
            with self.subTest(application_name=application_name):
                self.assertTrue(plugin.is_iterm_app(application_name))

    def test_non_iterm_focus_is_a_silent_noop(self):
        prepared = plugin.prepare_file_references(
            "Review at file main dot py.",
            "Spokenly",
            context_path=self.base / "missing.json",
            pending_dir=self.pending_dir,
        )
        self.assertEqual(prepared.snippets, [])
        self.assertIsNone(prepared.pending)
        self.assertEqual(prepared.warnings, [])

        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "1",
                "SPOKENLY_ACTIVE_APP": "Spokenly",
                "SPOKENLY_ITERM_CONTEXT_STATE": str(self.base / "missing.json"),
                "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR": str(self.pending_dir),
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path),
            }
        )
        source = "Review at file main dot py."
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
        self.assertEqual(pre.stdout, source)
        self.assertNotIn("file references unavailable", pre.stderr)

    def test_enabled_but_unconfigured_plugin_leaves_portable_pipeline_available(self):
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "1",
                "SPOKENLY_ACTIVE_APP": "iTerm2",
                "SPOKENLY_ITERM_CONTEXT_STATE": str(self.base / "missing.json"),
                "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR": str(self.pending_dir),
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path),
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
        self.assertEqual(pre.stderr, "")
        self.assertIn("pre.prepare", self.log_path.read_text(encoding="utf-8"))

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
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path),
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

    def test_duplicate_basename_selects_first_project_file(self):
        root = self.make_repo()
        for directory in ("client", "server"):
            path = root / directory / "config.py"
            path.parent.mkdir()
            path.write_text(directory, encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Inspect at file config dot py first."),
            "Inspect @client/config.py first.",
        )

    def test_root_file_is_first_duplicate_basename(self):
        root = self.make_repo()
        (root / "config.py").write_text("root", encoding="utf-8")
        nested = root / "server" / "config.py"
        nested.parent.mkdir()
        nested.write_text("server", encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Inspect at file config dot py first."),
            "Inspect @config.py first.",
        )

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

    def test_untracked_and_individually_ignored_files_are_indexed(self):
        root = self.make_repo()
        (root / ".gitignore").write_text(
            "secret.py\nignored-cache/\n", encoding="utf-8"
        )
        (root / "draft.py").write_text("draft", encoding="utf-8")
        (root / "secret.py").write_text("secret", encoding="utf-8")
        ignored_cache = root / "ignored-cache"
        ignored_cache.mkdir()
        (ignored_cache / "generated.py").write_text("generated", encoding="utf-8")
        self.write_context(root)
        files = plugin.list_project_files(root)
        paths = {item.relative_path.as_posix() for item in files}
        self.assertIn("draft.py", paths)
        self.assertIn("secret.py", paths)
        self.assertNotIn("ignored-cache/generated.py", paths)
        self.assertEqual(
            self.round_trip("Read at file secret dot py."),
            "Read @secret.py.",
        )
        self.assertEqual(
            self.round_trip("Read at filesecret dot py."),
            "Read @secret.py.",
        )
        self.assertEqual(
            self.round_trip("Read at filesecret.py."),
            "Read @secret.py.",
        )

    def test_ignored_file_query_is_lazy_and_does_not_repeat_standard_index(self):
        root = self.make_repo()
        (root / ".gitignore").write_text("secret.py\n", encoding="utf-8")
        (root / "secret.py").write_text("secret", encoding="utf-8")
        self.write_context(root)
        real_run = subprocess.run
        with mock.patch.object(plugin.subprocess, "run", wraps=real_run) as run:
            prepared = self.prepare("Read at file secret dot py.")
        ls_files_calls = [
            call for call in run.call_args_list if "ls-files" in call.args[0]
        ]
        self.assertEqual(len(ls_files_calls), 2)
        self.assertIn("--exclude-standard", ls_files_calls[0].args[0])
        self.assertNotIn("--ignored", ls_files_calls[0].args[0])
        self.assertIn("--ignored", ls_files_calls[1].args[0])
        self.assertEqual(
            {str(item["text"]) for item in prepared.snippets}, {"@secret.py"}
        )

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

    def test_failed_old_pane_post_does_not_delete_new_pane_state(self):
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
        with self.assertRaisesRegex(ValueError, "focused pane"):
            self.load(protected_a)

        pending_b = self.load(protected_b)
        self.assertEqual(set(pending_b.expansions.values()), {"@beta.py"})
        plugin.finish_pending_file_references(pending_b)

    def test_finishing_old_run_does_not_remove_newer_session_pointer(self):
        root = self.make_repo()
        (root / "alpha.py").write_text("a", encoding="utf-8")
        (root / "beta.py").write_text("b", encoding="utf-8")
        self.write_context(root)
        prepared_a = self.prepare("Review at file alpha dot py.")
        prepared_b = self.prepare("Review at file beta dot py.")
        protected_b = pre_ai.process(
            "Review at file beta dot py.", self.snippets, prepared_b.snippets
        )

        plugin.finish_pending_file_references(prepared_a.pending)
        pending_b = self.load(protected_b)
        self.assertEqual(set(pending_b.expansions.values()), {"@beta.py"})
        plugin.finish_pending_file_references(pending_b)

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

    def test_missing_context_with_tokenless_output_does_not_block_dictation(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root)
        self.prepare("Review at file main dot py.")
        self.context_state.unlink()
        self.assertIsNone(self.load("Review the file."))

    def test_fallback_manifest_restores_original_spoken_reference(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        source = "Review at file main dot pie carefully."
        self.write_context(root)
        prepared = self.prepare(source)
        protected = pre_ai.process(source, self.snippets, prepared.snippets)
        self.context_state.unlink()

        with self.assertRaisesRegex(ValueError, "cannot verify"):
            self.load(protected)
        fallback = plugin.load_fallback_file_references(
            protected,
            pending_dir=self.pending_dir,
        )
        try:
            self.assertEqual(
                post_ai.expand(
                    protected,
                    self.snippets,
                    extra_expansions=fallback.expansions,
                    expected_expansion_counts=fallback.expected_counts,
                ),
                source,
            )
        finally:
            plugin.finish_pending_file_references(fallback)

    def test_tokenless_fallback_uses_only_recent_manifest(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        source = "Review at file main dot pie carefully."
        self.write_context(root)
        self.prepare(source)
        fallback = plugin.load_fallback_file_references(
            "Review the file.",
            pending_dir=self.pending_dir,
        )
        try:
            self.assertIsNotNone(fallback)
            self.assertEqual(fallback.original_transcript, source)
            self.assertEqual(
                set(fallback.expansions.values()), {"at file main dot pie"}
            )
        finally:
            plugin.finish_pending_file_references(fallback)

    def test_main_manifest_recovers_when_fallback_file_is_missing(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        source = "Review at file main dot pie carefully."
        self.write_context(root)
        prepared = self.prepare(source)
        protected = pre_ai.process(source, self.snippets, prepared.snippets)
        prepared.pending.manifest_path.with_suffix(".fallback").unlink()
        fallback = plugin.load_fallback_file_references(
            protected,
            pending_dir=self.pending_dir,
        )
        try:
            self.assertEqual(
                set(fallback.expansions.values()), {"at file main dot pie"}
            )
            self.assertEqual(fallback.original_transcript, source)
        finally:
            plugin.finish_pending_file_references(fallback)

    def test_post_ai_focus_change_restores_original_phrase_and_succeeds(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        source = "Review at file main dot pie carefully."
        self.write_context(root)
        prepared = self.prepare(source)
        protected = pre_ai.process(source, self.snippets, prepared.snippets)
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "1",
                "SPOKENLY_ACTIVE_APP": "Spokenly",
                "SPOKENLY_ITERM_CONTEXT_STATE": str(self.context_state),
                "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR": str(self.pending_dir),
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path),
            }
        )
        post = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "post_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input=protected,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(post.stdout, source)
        self.assertEqual(post.stderr, "")
        self.assertIn("post.fallback_phrase", self.log_path.read_text(encoding="utf-8"))
        self.assertFalse(prepared.pending.manifest_path.exists())
        self.assertFalse(
            prepared.pending.manifest_path.with_suffix(".fallback").exists()
        )

    def test_post_ai_damaged_structure_uses_verified_source_expansion(self):
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
        source = "Review at file main dot pie carefully."
        self.write_context(root, job_pid=foreground.pid)
        self.prepare(source)
        environment = os.environ.copy()
        environment.update(
            {
                "SPOKENLY_ITERM_FILE_REFERENCES": "1",
                "SPOKENLY_ACTIVE_APP": "iTerm2",
                "SPOKENLY_ITERM_CONTEXT_STATE": str(self.context_state),
                "SPOKENLY_ITERM_FILE_REFERENCE_STATE_DIR": str(self.pending_dir),
                "SPOKENLY_ITERM_FILE_REFERENCE_LOG": str(self.log_path),
            }
        )
        post = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "post_ai.py"),
                "--snippets",
                str(self.snippets),
            ],
            input="Review the file.",
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.assertEqual(post.returncode, 0, post.stderr)
        self.assertEqual(post.stdout, "Review @main.py carefully.")
        self.assertEqual(post.stderr, "")
        self.assertIn(
            "post.deterministic_recovery",
            self.log_path.read_text(encoding="utf-8"),
        )

    def test_tokenless_output_uses_focused_pane_pointer(self):
        repo_a = self.make_repo("repo-a")
        repo_b = self.make_repo("repo-b")
        (repo_a / "alpha.py").write_text("a", encoding="utf-8")
        (repo_b / "beta.py").write_text("b", encoding="utf-8")
        self.write_context(repo_a, session_id="pane-a")
        self.prepare("Review at file alpha dot py.")
        self.write_context(repo_b, session_id="pane-b", tab_id="tab-b")
        prepared_b = self.prepare("Review at file beta dot py.")

        pending_b = self.load("Review the file.")
        self.assertEqual(set(pending_b.expansions.values()), {"@beta.py"})
        plugin.finish_pending_file_references(pending_b)

        self.write_context(repo_b, session_id="pane-b", tab_id="tab-b")
        prepared_b = self.prepare("Review at file beta dot py.")
        protected_b = pre_ai.process(
            "Review at file beta dot py.", self.snippets, prepared_b.snippets
        )
        pending_b = self.load(protected_b)
        self.assertEqual(set(pending_b.expansions.values()), {"@beta.py"})
        plugin.finish_pending_file_references(pending_b)

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

    def test_hidden_multi_dot_file_preserves_spoken_leading_dot(self):
        root = self.make_repo()
        (root / ".env.local").write_text("LOCAL=1", encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Review at file dot env dot local carefully."),
            "Review @.env.local carefully.",
        )

    def test_multi_dot_filename_accepts_each_spoken_dot(self):
        root = self.make_repo()
        (root / "button.test.ts").write_text("test", encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Review at file button dot test dot tee ess."),
            "Review @button.test.ts.",
        )

    def test_internal_multi_dot_suffixes_accept_spoken_extension_aliases(self):
        root = self.make_repo()
        (root / "types.d.ts").write_text("types", encoding="utf-8")
        (root / "phpunit.xml.dist").write_text("xml", encoding="utf-8")
        (root / "image.pkr.hcl").write_text("packer", encoding="utf-8")
        (root / "module.tftest.hcl").write_text("terraform", encoding="utf-8")
        self.write_context(root)
        self.assertEqual(
            self.round_trip("Review at file types dot dee dot type script."),
            "Review @types.d.ts.",
        )
        self.assertEqual(
            self.round_trip("Review at file phpunit dot ex em el dot distribution."),
            "Review @phpunit.xml.dist.",
        )
        self.assertEqual(
            self.round_trip(
                "Review at file image dot packer dot hashicorp configuration language."
            ),
            "Review @image.pkr.hcl.",
        )
        self.assertEqual(
            self.round_trip(
                "Review at file module dot terraform test dot aitch see el."
            ),
            "Review @module.tftest.hcl.",
        )

    def test_cars_bdv_extension_families_have_natural_spoken_aliases(self):
        expected = {
            "php": ("hypertext", "preprocessor"),
            "svg": ("scalable", "vector", "graphic"),
            "js": ("javascript",),
            "jpg": ("jay", "peg"),
            "css": ("cascading", "style", "sheet"),
            "html": ("hypertext", "markup", "language"),
            "map": ("source", "map"),
            "md": ("markdown",),
            "png": ("portable", "network", "graphic"),
            "tf": ("terraform",),
            "tftest": ("terraform", "test"),
            "json": ("jason",),
            "webp": ("web", "pee"),
            "gif": ("jif",),
            "sh": ("shell",),
            "mjs": ("module", "javascript"),
            "hcl": ("hashicorp", "configuration", "language"),
            "pkr": ("packer",),
            "csv": ("comma", "separated", "values"),
            "ts": ("typescript",),
            "txt": ("plain", "text"),
            "tpl": ("template",),
            "service": ("systemd", "service"),
            "py": ("python",),
            "drawio": ("draw", "eye", "oh"),
            "woff2": ("woff", "two"),
            "woff": ("web", "open", "font", "format"),
            "ttf": ("true", "type", "font"),
            "eot": ("embedded", "open", "type"),
            "conf": ("configuration",),
            "path": ("systemd", "path"),
            "ico": ("icon",),
            "tfvars": ("terraform", "variables"),
            "pdf": ("portable", "document", "format"),
            "neon": ("neon",),
            "swf": ("shockwave", "flash"),
            "ps1": ("power", "shell"),
            "lock": ("lock", "file"),
            "fla": ("flash", "authoring"),
            "dist": ("distribution",),
        }
        for extension, spoken_alias in expected.items():
            with self.subTest(extension=extension):
                self.assertIn(spoken_alias, plugin._extension_variants(extension))

    def test_spelled_extensions_accept_transcribed_letter_names_and_digits(self):
        expected = {
            "php": ("pee", "aitch", "pee"),
            "svg": ("ess", "vee", "gee"),
            "json": ("jay", "ess", "oh", "en"),
            "woff2": ("double", "you", "oh", "eff", "eff", "two"),
            "7z": ("seven", "zee"),
        }
        for extension, spoken_alias in expected.items():
            with self.subTest(extension=extension):
                self.assertIn(spoken_alias, plugin._extension_variants(extension))

    def test_representative_verbose_extension_aliases_expand_end_to_end(self):
        root = self.make_repo()
        cases = {
            "Controller.php": "controller dot pee aitch pee",
            "logo.svg": "logo dot ess vee gee",
            "main.tf": "main dot terraform",
            "variables.tfvars": "variables dot terraform variables",
            "worker.service": "worker dot system d service",
            "font.woff2": "font dot woff two",
            "diagram.drawio": "diagram dot draw eye oh",
            "setup.ps1": "setup dot power shell",
            "inventory.csv": "inventory dot comma separated values",
            "photo.jpg": "photo dot jay peg",
        }
        for filename in cases:
            (root / filename).write_text(filename, encoding="utf-8")
        self.write_context(root)
        for filename, spoken_name in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(
                    self.round_trip(f"Review at file {spoken_name}."),
                    f"Review @{filename}.",
                )

    def test_non_git_directory_is_not_treated_as_a_project(self):
        directory = self.base / "not-git"
        directory.mkdir()
        (directory / "main.py").write_text("main", encoding="utf-8")
        self.write_context(directory)
        with self.assertRaisesRegex(ValueError, "Git worktree"):
            self.prepare("Review at file main dot py.")

    def test_symlinked_context_state_is_rejected(self):
        root = self.make_repo()
        real_state = self.base / "real-context.json"
        self.context_state = real_state
        self.write_context(root)
        linked_state = self.base / "linked-context.json"
        linked_state.symlink_to(real_state)
        with self.assertRaisesRegex(ValueError, "regular file"):
            plugin.read_iterm_context(linked_state, max_age_seconds=60)

    def test_symlinked_pending_directory_is_rejected(self):
        root = self.make_repo()
        (root / "main.py").write_text("main", encoding="utf-8")
        self.write_context(root)
        real_pending = self.base / "real-pending"
        real_pending.mkdir()
        self.pending_dir.symlink_to(real_pending, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "not a directory"):
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

    def test_mcp_child_process_resolves_to_claude_ancestor(self):
        context = plugin.ItermContext(
            window_id="window-a",
            tab_id="tab-a",
            session_id="session-a",
            tty="/dev/ttys023",
            job_pid=300,
            process_title="node",
            path=self.base,
            hostname="local.test",
            ssh_integration_level=0,
            observed_at=time.time(),
        )
        snapshot = {
            300: (200, "ttys023", "node mcp-server-postgres"),
            200: (100, "ttys023", "npm exec @modelcontextprotocol/server-postgres"),
            100: (1, "ttys023", "claude"),
        }
        with mock.patch("os.kill"), mock.patch.object(
            plugin, "_process_record", side_effect=lambda pid: snapshot.get(pid)
        ):
            self.assertEqual(plugin.detect_harness(context), ("claude", 100))

    def test_process_ancestry_cannot_cross_to_another_tty(self):
        context = plugin.ItermContext(
            window_id="window-a",
            tab_id="tab-a",
            session_id="session-a",
            tty="/dev/ttys023",
            job_pid=300,
            process_title="node",
            path=self.base,
            hostname="local.test",
            ssh_integration_level=0,
            observed_at=time.time(),
        )
        snapshot = {
            300: (100, "ttys023", "node mcp-server"),
            100: (1, "ttys999", "claude"),
        }
        with mock.patch("os.kill"), mock.patch.object(
            plugin, "_process_record", side_effect=lambda pid: snapshot.get(pid)
        ):
            with self.assertRaisesRegex(ValueError, "Codex or Claude"):
                plugin.detect_harness(context)


def re_search_file_token(text: str) -> str:
    import re

    match = re.search(r"\[\[SPK_SNIPPET_FILE_REF_[^\]]+\]\]", text)
    if match is None:
        raise AssertionError("protected file-reference token not found")
    return match.group(0)


if __name__ == "__main__":
    unittest.main()
