#!/usr/bin/env python3
"""Cross-cutting invariants over the six skills + template + marketplace — offline, no network.

Holistic assertions over the six gh-projects skills + the add-to-project template
+ the root marketplace, behind the invariants that must hold across the plugin:

  - start-issue and create-pr frontmatter carry the PreToolUse / matcher
    "Bash" guard hooks block pointing at hooks/guard.sh; plan-sprint does NOT
    (it neither deploys nor merges). The guard's behavior (squash / prod /
    fail-open) is exercised separately in test_guard.py.
  - No metered AI/model call in the three side-effecting skills or the
    add-to-project template (the SKILL.md `model:` selector is NOT a metered call).
  - add-to-project.yml SHA-pins its third-party actions and authenticates the
    project write with a GitHub App token, never GITHUB_TOKEN.
  - Root marketplace.json pins gh-projects to >= 0.2.0.
  - All six skills declare disable-model-invocation + model: claude-opus-4-8
    with the deliberate per-skill effort (start-issue medium · plan-sprint
    high · create-pr high · scaffold-repo medium · create-issues high ·
    sync-signals low).
"""
from __future__ import annotations

import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(HERE))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(PLUGIN_ROOT)))
SKILLS_DIR = os.path.join(PLUGIN_ROOT, "skills")
MARKETPLACE = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
ADD_TO_PROJECT = os.path.join(
    PLUGIN_ROOT, "templates", "github", "workflows", "add-to-project.yml"
)

SIDE_EFFECTING_SKILLS = ["start-issue", "plan-sprint", "create-pr"]
ALL_SKILLS = SIDE_EFFECTING_SKILLS + ["scaffold-repo", "create-issues", "sync-signals"]
# Deliberate per-skill effort.
EXPECTED_EFFORT = {
    "start-issue": "medium", "plan-sprint": "high", "create-pr": "high",
    "scaffold-repo": "medium", "create-issues": "high", "sync-signals": "low",
}
# The guard is scoped ONLY to the deploy/merge-capable skills.
GUARD_SKILLS = {"start-issue", "create-pr"}


def _read_skill(name: str) -> str:
    with open(os.path.join(SKILLS_DIR, name, "SKILL.md"), encoding="utf-8") as fh:
        return fh.read()


def _frontmatter(text: str) -> str:
    """Return the YAML frontmatter block (between the first two '---' fences)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return m.group(1) if m else ""


class AC34_ModelAndEffort(unittest.TestCase):
    """All six skills are Explicit, opus, with the deliberate effort."""

    def test_all_six_skills_are_opus_with_expected_effort(self):
        # Model + effort across ALL six skills.
        for name in ALL_SKILLS:
            fm = _frontmatter(_read_skill(name))
            self.assertTrue(fm, f"{name}: no frontmatter block found")
            self.assertRegex(
                fm, r"(?m)^model:\s*claude-opus-4-8\s*$",
                f"{name}: must declare model: claude-opus-4-8",
            )
            self.assertRegex(
                fm, rf"(?m)^effort:\s*{EXPECTED_EFFORT[name]}\s*$",
                f"{name}: effort must be {EXPECTED_EFFORT[name]}",
            )

    def test_side_effecting_skills_are_explicit(self):
        # The three side-effecting skills must be Explicit (user-invoked only).
        # Existing skills' Explicit-ness is out of scope here (assert-don't-change).
        for name in SIDE_EFFECTING_SKILLS:
            fm = _frontmatter(_read_skill(name))
            self.assertRegex(
                fm, r"(?m)^disable-model-invocation:\s*true\s*$",
                f"{name}: a new side-effecting skill must set disable-model-invocation: true",
            )

    def test_no_skill_remains_on_sonnet_or_haiku(self):
        for name in ALL_SKILLS:
            fm = _frontmatter(_read_skill(name))
            self.assertNotIn("claude-sonnet", fm, f"{name}: on sonnet")
            self.assertNotIn("claude-haiku", fm, f"{name}: on haiku")


class AC25_GuardFrontmatter(unittest.TestCase):
    """start-issue + create-pr wire the guard; plan-sprint does not."""

    def _has_guard_block(self, fm: str) -> bool:
        return (
            re.search(r"(?m)^hooks:\s*$", fm) is not None
            and "PreToolUse:" in fm
            and re.search(r'matcher:\s*"?Bash"?', fm) is not None
            and "guard.sh" in fm
            and "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh" in fm
        )

    def test_guard_wired_into_route_issue_and_promote_pr(self):
        for name in sorted(GUARD_SKILLS):
            fm = _frontmatter(_read_skill(name))
            self.assertTrue(
                self._has_guard_block(fm),
                f"{name}: must carry the PreToolUse/Bash guard hooks block "
                "pointing at ${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh",
            )

    def test_plan_sprint_does_not_wire_the_guard(self):
        fm = _frontmatter(_read_skill("plan-sprint"))
        self.assertNotIn(
            "guard.sh", fm,
            "plan-sprint neither deploys nor merges — it must NOT wire the guard",
        )

    def test_guard_script_exists_and_is_executable(self):
        guard = os.path.join(PLUGIN_ROOT, "hooks", "guard.sh")
        self.assertTrue(os.path.isfile(guard), "hooks/guard.sh must exist")
        self.assertTrue(os.access(guard, os.X_OK), "hooks/guard.sh must be executable")


class AC32_MarketplaceVersion(unittest.TestCase):
    """gh-projects is pinned to >= 0.2.0 in the root marketplace."""

    def test_gh_projects_version_at_least_0_2_0(self):
        with open(MARKETPLACE, encoding="utf-8") as fh:
            mk = json.load(fh)
        gp = {p["name"]: p for p in mk["plugins"]}.get("gh-projects")
        self.assertIsNotNone(gp, "gh-projects must be registered in marketplace.json")
        parts = tuple(int(x) for x in str(gp["version"]).split("."))
        self.assertGreaterEqual(parts, (0, 2, 0), f"gh-projects must be >= 0.2.0 (got {gp['version']})")


class AC27_NoMeteredAI(unittest.TestCase):
    """No metered AI/model API call in the side-effecting skills or the add-to-project template."""

    # An actual metered call — NOT the Claude Code skill `model:` selector.
    METERED = re.compile(
        r"api\.anthropic|/v1/messages|messages\.create|anthropic\.(messages|completions)"
        r"|openai|ANTHROPIC_API_KEY|OPENAI_API_KEY|chat/completions",
        re.IGNORECASE,
    )

    def test_side_effecting_skills_make_no_metered_call(self):
        for name in ("start-issue", "plan-sprint", "create-pr"):
            body = _read_skill(name)
            self.assertIsNone(
                self.METERED.search(body), f"{name}: contains a metered-AI reference"
            )

    def test_add_to_project_template_makes_no_metered_call(self):
        with open(ADD_TO_PROJECT, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIsNone(self.METERED.search(body), "add-to-project.yml metered-AI")


class AC22_AddToProjectSupplyChain(unittest.TestCase):
    """add-to-project.yml is SHA-pinned + App-token authed, never GITHUB_TOKEN."""

    def setUp(self):
        with open(ADD_TO_PROJECT, encoding="utf-8") as fh:
            self.body = fh.read()

    def test_third_party_actions_are_sha_pinned(self):
        # actions/add-to-project must be pinned to a full 40-hex commit SHA.
        self.assertRegex(
            self.body, r"actions/add-to-project@[0-9a-f]{40}\b",
            "actions/add-to-project must be SHA-pinned (40-hex), stricter than tag pins",
        )
        # Every `uses:` of a non-local action must carry a 40-hex SHA.
        for line in self.body.splitlines():
            m = re.search(r"uses:\s*([^@\s]+)@(\S+)", line)
            if not m or m.group(1).startswith("./"):
                continue
            self.assertRegex(
                m.group(2), r"^[0-9a-f]{40}",
                f"third-party action {m.group(1)} must be SHA-pinned: {line.strip()}",
            )

    def test_project_write_uses_app_token_not_github_token(self):
        # The App installation token is minted in-workflow and passed as the
        # add-to-project github-token; GITHUB_TOKEN is never the project-write cred.
        self.assertIn("create-github-app-token", self.body,
                      "must mint a GitHub App installation token")
        self.assertNotRegex(
            self.body, r"github-token:\s*\$\{\{\s*secrets\.GITHUB_TOKEN",
            "the add-to-project write must NOT authenticate with GITHUB_TOKEN",
        )


if __name__ == "__main__":
    unittest.main()
