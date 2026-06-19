#!/usr/bin/env python3
"""Cross-cutting invariants — offline, NO network, NO live org.

Each test is a runnable assertion behind an invariant that must hold across the plugin:

  - No workflow or skill makes a metered AI/model call.
  - Every Projects field write uses the App installation token; none use
    GITHUB_TOKEN.
  - Manifest carries only name+description (no version); root marketplace
    pins the gh-projects version and does not list pm-ops.
  - No schema mutation re-PUTs a single-select option list or
    iterationConfiguration without a prior diff (diff-gated, ID-stable).
  - Status writes from the three layers are idempotent + monotonic — a
    stale/replayed event never regresses Status; only reopen moves it back.

The metered-AI / App-token / diff-gate invariants are demonstrated by source greps
across templates + skills + lib. The monotonic-Status invariant is demonstrated by a
behavioral fixture exercising the real advance_status from all three layers (lib/gh,
board_sync, board_status).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(PLUGIN_ROOT)))
MARKETPLACE = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
MANIFEST = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _walk(root, exts):
    """Yield (path, text) for every file under root with one of `exts`."""
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath or "/tests" in dirpath.replace(os.sep, "/"):
            # Skip the test directory itself — tests legitimately name the
            # forbidden patterns to assert their absence.
            if "/tests" in dirpath.replace(os.sep, "/"):
                continue
        for f in files:
            if any(f.endswith(e) for e in exts):
                p = os.path.join(dirpath, f)
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        yield p, fh.read()
                except (UnicodeDecodeError, OSError):
                    continue


# Directories scanned for the "no metered AI" / "App token" invariants.
SCAN_DIRS = [
    os.path.join(PLUGIN_ROOT, "templates"),
    os.path.join(PLUGIN_ROOT, "skills"),
    os.path.join(PLUGIN_ROOT, "lib"),
]
CODE_EXTS = (".py", ".yml", ".yaml", ".sh")
ALL_EXTS = CODE_EXTS + (".md", ".json")


class AC26_NoMeteredAI(unittest.TestCase):
    """No workflow/skill makes a metered AI/model API call."""

    # Patterns that would indicate an actual metered model call wired in.
    FORBIDDEN = [
        re.compile(r"api\.anthropic\.com"),
        re.compile(r"/v1/messages"),
        re.compile(r"/v1/chat/completions"),
        re.compile(r"\bx-api-key\b", re.I),
        re.compile(r"\bANTHROPIC_API_KEY\b"),
        re.compile(r"\bimport\s+anthropic\b"),
        re.compile(r"\bfrom\s+anthropic\b"),
        re.compile(r"@anthropic-ai\b"),
        re.compile(r"\bmessages\.create\b"),
        re.compile(r"\bclaude-[0-9]"),
        re.compile(r"\bgpt-[0-9]"),
        re.compile(r"\bimport\s+openai\b"),
    ]

    def test_no_metered_ai_call_in_workflows_or_skills(self):
        hits = []
        for d in SCAN_DIRS:
            if not os.path.isdir(d):
                continue
            for path, text in _walk(d, CODE_EXTS):
                for pat in self.FORBIDDEN:
                    if pat.search(text):
                        hits.append(f"{path}: matched {pat.pattern}")
        self.assertEqual([], hits, "metered AI call found in plugin code:\n" + "\n".join(hits))


class AC27_AppTokenOnly(unittest.TestCase):
    """Every Projects field write uses the App token; none read GITHUB_TOKEN."""

    # A *write path* must never resolve a token from GITHUB_TOKEN.
    FORBIDDEN_TOKEN_READS = [
        'os.environ.get("GITHUB_TOKEN")',
        "os.environ['GITHUB_TOKEN']",
        'os.environ["GITHUB_TOKEN"]',
        "os.getenv('GITHUB_TOKEN')",
        'os.getenv("GITHUB_TOKEN")',
        # Wiring GITHUB_TOKEN into the action/script env as the auth value:
        "GH_APP_TOKEN: ${{ secrets.GITHUB_TOKEN",
        "gh_app_token: ${{ secrets.github_token",
    ]

    def test_no_code_reads_github_token_for_a_write(self):
        hits = []
        for d in SCAN_DIRS:
            if not os.path.isdir(d):
                continue
            for path, text in _walk(d, CODE_EXTS):
                low = text
                for bad in self.FORBIDDEN_TOKEN_READS:
                    if bad in low:
                        hits.append(f"{path}: wired GITHUB_TOKEN via `{bad}`")
                # case-insensitive check for the YAML env-wiring form
                for bad in ("GH_APP_TOKEN: ${{ secrets.GITHUB_TOKEN",):
                    if bad.lower() in low.lower():
                        hits.append(f"{path}: GITHUB_TOKEN wired as the App token")
        self.assertEqual([], hits, "GITHUB_TOKEN used for a write:\n" + "\n".join(hits))

    def test_app_token_is_the_documented_write_credential(self):
        # Sanity: the write surfaces reference the App installation token, proving
        # the positive side of the invariant (not merely the absence of the bad).
        found_app_token = False
        for d in SCAN_DIRS:
            if not os.path.isdir(d):
                continue
            for _path, text in _walk(d, CODE_EXTS):
                if "GH_APP_TOKEN" in text or "create-github-app-token" in text:
                    found_app_token = True
                    break
        self.assertTrue(found_app_token, "App installation token should be the write credential")


class AC30_DiffBeforeMutate(unittest.TestCase):
    """No blind re-PUT of an option list or iterationConfiguration."""

    def setUp(self):
        self.gh = _load("ghmod_inv", os.path.join(PLUGIN_ROOT, "lib", "gh.py"))

    def test_iterations_diff_gate_exists_and_skips_unchanged(self):
        self.assertTrue(hasattr(self.gh, "iterations_need_update"))
        same = [{"title": "S1", "startDate": "2026-01-01", "duration": 14}]
        self.assertFalse(self.gh.iterations_need_update(same, list(same)),
                         "identical iteration set must NOT trigger a re-PUT")

    def test_iterations_diff_detects_a_real_change(self):
        a = [{"title": "S1", "startDate": "2026-01-01", "duration": 14}]
        b = [{"title": "S1", "startDate": "2026-01-15", "duration": 14}]
        self.assertTrue(self.gh.iterations_need_update(a, b))

    def test_options_diff_gate_exists_and_skips_unchanged(self):
        self.assertTrue(hasattr(self.gh, "options_need_update"))
        same = [{"name": "S", "description": "small"}, {"name": "M", "description": "medium"}]
        self.assertFalse(self.gh.options_need_update(same, [dict(o) for o in same]),
                         "identical option set must NOT trigger a re-PUT (option-ID stability)")

    def test_options_diff_detects_a_real_change(self):
        a = [{"name": "S", "description": "small"}]
        b = [{"name": "S", "description": "small"}, {"name": "L", "description": "large"}]
        self.assertTrue(self.gh.options_need_update(a, b))

    def test_iteration_config_writes_are_diff_gated_in_source(self):
        # No source line should call updateProjectV2Field with iterationConfiguration
        # without the diff guard being the gate. We assert the guard is referenced
        # everywhere an iterationConfiguration mutation is mentioned in scaffold.
        scaffold = os.path.join(PLUGIN_ROOT, "lib", "scaffold.py")
        with open(scaffold, encoding="utf-8") as fh:
            src = fh.read()
        if "iterationConfiguration" in src or "iteration" in src.lower():
            self.assertIn("iterations_need_update", src,
                          "scaffold must diff via iterations_need_update before any re-PUT")


class AC29_Manifest(unittest.TestCase):
    """Manifest = name+description only; version + dep state live in marketplace."""

    def test_plugin_manifest_parses_and_has_no_version(self):
        with open(MANIFEST, encoding="utf-8") as fh:
            man = json.load(fh)
        self.assertIn("name", man)
        self.assertEqual(man["name"], "gh-projects")
        self.assertIn("description", man)
        self.assertNotIn("version", man, "version must live in marketplace.json, not the manifest")

    def test_marketplace_parses_and_pins_gh_projects(self):
        with open(MARKETPLACE, encoding="utf-8") as fh:
            mk = json.load(fh)
        plugins = {p["name"]: p for p in mk["plugins"]}
        self.assertIn("gh-projects", plugins, "gh-projects must be registered in marketplace.json")
        gp = plugins["gh-projects"]
        self.assertEqual(gp["version"], "0.2.6")
        self.assertEqual(gp["source"], "./claude-code/plugins/gh-projects")
        self.assertTrue(gp.get("description"))

    def test_marketplace_no_longer_lists_pm_ops(self):
        # pm-ops must not be registered in the marketplace.
        with open(MARKETPLACE, encoding="utf-8") as fh:
            mk = json.load(fh)
        plugins = {p["name"] for p in mk["plugins"]}
        self.assertNotIn("pm-ops", plugins, "pm-ops must not be in the marketplace")


class AC31_MonotonicStatus(unittest.TestCase):
    """All three layers advance Status monotonically; never regress except reopen."""

    LAYERS = [
        ("lib/gh", os.path.join(PLUGIN_ROOT, "lib", "gh.py")),
        ("board_sync", os.path.join(PLUGIN_ROOT, "templates", "github", "workflows", "board_sync.py")),
        ("board_status", os.path.join(PLUGIN_ROOT, "templates", "github", "actions", "board-status", "board_status.py")),
    ]

    def setUp(self):
        self.mods = {}
        for name, path in self.LAYERS:
            self.mods[name] = _load(f"layer_{name.replace('/', '_')}", path)

    def test_all_layers_share_the_same_status_order(self):
        expected = ["Backlog", "Ready", "In Progress", "In Review", "On Staging", "Done"]
        for name, mod in self.mods.items():
            self.assertEqual(list(mod.STATUS_ORDER), expected, f"{name} STATUS_ORDER mismatch")

    def test_advance_only_moves_forward(self):
        for name, mod in self.mods.items():
            adv = mod.advance_status
            # forward: In Progress -> In Review writes In Review
            self.assertEqual(adv("In Progress", "In Review"), "In Review", name)
            # idempotent: at target -> no-op (None)
            self.assertIsNone(adv("In Review", "In Review"), f"{name}: same-stage is a no-op")
            # backward (stale/replayed): On Staging asked back to In Progress -> no-op
            self.assertIsNone(adv("On Staging", "In Progress"),
                              f"{name}: a stale event must NOT regress Status")
            # Done asked back to In Review -> no-op
            self.assertIsNone(adv("Done", "In Review"), f"{name}: Done never flickers backward")

    def test_explicit_reopen_is_the_only_backward_move(self):
        for name, mod in self.mods.items():
            self.assertEqual(
                mod.advance_status("Done", "In Progress", reopen=True), "In Progress",
                f"{name}: explicit reopen moves Status back",
            )

    def test_replayed_event_sequence_is_deterministic(self):
        # Simulate a stream of out-of-order / replayed events hitting one item and
        # assert the final Status is the high-water mark, with no backward flicker.
        for name, mod in self.mods.items():
            adv = mod.advance_status
            order = list(mod.STATUS_ORDER)
            # A realistic churn: push (In Progress), PR (In Review), merge/staging
            # (On Staging), a REPLAYED push (In Progress), prod (Done), a stale PR
            # replay (In Review).
            events = ["In Progress", "In Review", "On Staging", "In Progress", "Done", "In Review"]
            current = "Backlog"
            for ev in events:
                writeto = adv(current, ev)
                if writeto is not None:
                    # monotonic invariant: a write never lowers the rank
                    self.assertGreaterEqual(
                        order.index(writeto), order.index(current),
                        f"{name}: write regressed {current} -> {writeto}",
                    )
                    current = writeto
            self.assertEqual(current, "Done", f"{name}: final Status must settle at the high-water mark")


if __name__ == "__main__":
    unittest.main()
