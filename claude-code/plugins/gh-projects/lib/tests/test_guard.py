#!/usr/bin/env python3
"""Offline unit tests for hooks/guard.sh — the skill-scoped PreToolUse guard.

NO network, NO live gh, NO real org. Each test feeds a PreToolUse event JSON on
stdin to the bash guard and asserts its exit code + stderr. Convention:
  exit 0 -> ALLOW (fail-open or green-gated)
  exit 2 -> BLOCK (explicit policy violation, message on stderr)

Coverage:
  * blocks `gh pr merge --squash`
  * blocks a PROD deploy / release action without provably-green checks
  * fails OPEN (allow) on unrelated, malformed, empty, or non-matching input
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
GUARD = os.path.join(PLUGIN_ROOT, "hooks", "guard.sh")


def run_guard(stdin_text: str):
    """Invoke the guard with stdin_text on stdin; return (exit_code, stderr)."""
    proc = subprocess.run(
        ["bash", GUARD],
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stderr


def event(command: str) -> str:
    """A PreToolUse event JSON whose tool_input.command is `command`."""
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


class GuardExists(unittest.TestCase):
    def test_guard_is_executable_and_parses(self):
        self.assertTrue(os.path.isfile(GUARD), "hooks/guard.sh must exist")
        self.assertTrue(os.access(GUARD, os.X_OK), "guard.sh must be executable")
        # bash -n: syntax check, no execution.
        r = subprocess.run(["bash", "-n", GUARD], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class BlocksSquash(unittest.TestCase):
    def test_blocks_squash_merge(self):
        code, err = run_guard(event("gh pr merge 42 --squash"))
        self.assertEqual(code, 2, "squash merge must be blocked")
        self.assertIn("--squash", err)

    def test_blocks_squash_with_equals_form(self):
        code, err = run_guard(event("gh pr merge 42 --squash=true --delete-branch"))
        self.assertEqual(code, 2)

    def test_blocks_squash_with_extra_flags_and_repo(self):
        code, _ = run_guard(event("gh pr merge --repo o/r 42 --squash --admin"))
        self.assertEqual(code, 2)

    def test_allows_merge_commit(self):
        code, _ = run_guard(event("gh pr merge 42 --merge"))
        self.assertEqual(code, 0, "a real --merge must be allowed")

    def test_allows_rebase_merge(self):
        code, _ = run_guard(event("gh pr merge 42 --rebase"))
        self.assertEqual(code, 0)

    def test_squash_substring_not_in_merge_does_not_block(self):
        # `--squashfoo` is not the squash flag; a branch literally named in text
        # must not trip the guard when it isn't a `gh pr merge --squash`.
        code, _ = run_guard(event("git commit -m 'note: we never squash here'"))
        self.assertEqual(code, 0)


class BlocksProdWithoutGreen(unittest.TestCase):
    def test_blocks_prod_workflow_run_without_green(self):
        code, err = run_guard(event("gh workflow run deploy-prod.yml --ref main -f tag=v1.2.3"))
        self.assertEqual(code, 2, "prod deploy without green checks must be blocked")
        self.assertIn("green", err.lower())

    def test_blocks_production_workflow_run(self):
        code, _ = run_guard(event("gh workflow run production.yml --ref main"))
        self.assertEqual(code, 2)

    def test_blocks_prod_release_publish_without_green(self):
        code, _ = run_guard(event("gh release create v1.2.3 --target main --notes deploy-prod"))
        self.assertEqual(code, 2)

    def test_blocks_api_prod_dispatch_without_green(self):
        code, _ = run_guard(
            event("gh api repos/o/r/actions/workflows/deploy-prod.yml/dispatches -f ref=main")
        )
        self.assertEqual(code, 2)

    def test_allows_prod_deploy_chained_after_pr_checks(self):
        code, _ = run_guard(
            event("gh pr checks 42 --watch && gh workflow run deploy-prod.yml --ref main")
        )
        self.assertEqual(code, 0, "prod after a green-checks gate must be allowed")

    def test_allows_prod_deploy_chained_after_run_watch(self):
        code, _ = run_guard(
            event("gh run watch 99 --exit-status && gh workflow run deploy-prod.yml --ref main")
        )
        self.assertEqual(code, 0)

    def test_allows_prod_deploy_with_checks_green_marker(self):
        code, _ = run_guard(
            event("CHECKS_GREEN=1 gh workflow run deploy-prod.yml --ref main")
        )
        self.assertEqual(code, 0)

    def test_allows_non_prod_workflow_run(self):
        # A staging or unrelated workflow run carries no prod signal -> fail open.
        code, _ = run_guard(event("gh workflow run deploy-staging.yml --ref main"))
        self.assertEqual(code, 0)
        code, _ = run_guard(event("gh workflow run ci.yml --ref feature"))
        self.assertEqual(code, 0)


class FailsOpenOnUnrelated(unittest.TestCase):
    def test_allows_empty_stdin(self):
        code, _ = run_guard("")
        self.assertEqual(code, 0)

    def test_allows_garbage_non_json(self):
        code, _ = run_guard("this is not json at all")
        self.assertEqual(code, 0)

    def test_allows_json_without_command(self):
        code, _ = run_guard(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}}))
        self.assertEqual(code, 0)

    def test_allows_unrelated_bash(self):
        for cmd in (
            "git status",
            "ls -la",
            "python3 lib/scaffold.py plan",
            "gh issue list",
            "gh pr list",
            "gh pr view 42",
            "git push origin HEAD",
        ):
            code, _ = run_guard(event(cmd))
            self.assertEqual(code, 0, f"unrelated command must fail open: {cmd}")

    def test_allows_gh_release_without_prod_signal(self):
        # A release publish that does NOT front a prod cut is not a guarded prod
        # action -> fail open. (board-status owns prod release publishing.)
        code, _ = run_guard(event("gh release create v0.1.0 --notes 'draft notes'"))
        self.assertEqual(code, 0)


class PrintsNoSecret(unittest.TestCase):
    def test_never_echoes_a_token_value(self):
        # Even when a token-looking value rides along in the command, the guard's
        # stderr must not echo it back (it only ever prints fixed policy text).
        secret = "ghs_FAKEinstallationTOKENvalue000000000000"
        code, err = run_guard(event(f"gh workflow run deploy-prod.yml -f token={secret}"))
        self.assertEqual(code, 2)
        self.assertNotIn(secret, err)


if __name__ == "__main__":
    unittest.main()
