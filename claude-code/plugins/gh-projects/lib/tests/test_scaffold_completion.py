#!/usr/bin/env python3
"""Offline tests for the scaffold-COMPLETION duties — NO network, NO live org,
NO live mutation. Reuses the scaffold.py fake-RUN pattern (a canned-JSON runner
that records write round-trips). Covers:

  * link_repo / scaffold repo→Project link — a REAL
    linkProjectV2ToRepository(projectId, repositoryId) mutation, idempotent
    (reads the project's linked repositories; a re-run is a SKIP / no-op).
  * the per-repo add-to-project.yml is REGISTERED in INSTALL_FILES, installed
    by plan_file_install, SHA-PINNED (a 40-hex sha on actions/add-to-project),
    App-token auth (no GITHUB_TOKEN for the project write), NO metered AI.
  * team link planned when --team given via a REAL linkProjectV2ToTeam
    (the teamId is actually sent — distinguishing it from _LINK_PROJECT_APP),
    + base-role emitted as a MANUAL step in the manifest, + grant_app_access
    stays a confirmation (not a base-role grant, no base-role mutation).
  * the completions are dry-by-default, idempotent (a re-run manifest is
    empty for these duties), and diff-before-mutate (no blind re-PUT).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(HERE)
sys.path.insert(0, LIB)

import gh  # noqa: E402
import scaffold  # noqa: E402

# Reuse the proven scaffold fixture runner / ids so the copy resolves correctly.
# Import the sibling module by whichever package name it was loaded under (the
# project's `unittest discover -s lib/tests -t lib` loads it as `tests.test_scaffold`;
# a bare module run loads it as `test_scaffold`). Try both without forcing a
# second copy onto sys.path (which would double-load the whole suite).
try:
    from tests.test_scaffold import (  # noqa: E402
        ScaffoldRunner, ScaffoldTestBase, TEMPLATE_TITLE,
        COPY_PROJECT_ID, COPY_NUMBER, TEMPLATE_NUMBER,
    )
except ModuleNotFoundError:  # pragma: no cover — bare-module invocation
    sys.path.insert(0, HERE)
    from test_scaffold import (  # noqa: E402
        ScaffoldRunner, ScaffoldTestBase, TEMPLATE_TITLE,
        COPY_PROJECT_ID, COPY_NUMBER, TEMPLATE_NUMBER,
    )

REPO_NODE_ID = "R_repo1"
TEAM_NODE_ID = "T_team1"
SHA40 = re.compile(r"\b[0-9a-f]{40}\b")


class CompletionRunner(ScaffoldRunner):
    """Extends the scaffold runner with repo-node, team-node, and linked-repo
    reads + the two link mutations. `linked_repo_ids` lets a test pre-link a repo
    so the idempotent SKIP path is observable."""

    def __init__(self, *, linked_repo_ids=None, linked_team_ids=None, **kw):
        super().__init__(**kw)
        self.linked_repo_ids = set(linked_repo_ids or [])
        self.linked_team_ids = set(linked_team_ids or [])

    def __call__(self, args):
        body = " ".join(str(a) for a in args)
        # repo node-id resolve
        if "repository(owner:" in body and "name:" in body:
            self.calls.append(list(args))
            return json.dumps({"data": {"repository": {"id": REPO_NODE_ID}}})
        # team node-id resolve
        if "team(slug:" in body:
            self.calls.append(list(args))
            return json.dumps({"data": {"organization": {"team": {"id": TEAM_NODE_ID}}}})
        # the project's currently-linked repositories (idempotency read)
        if "repositories(first:100)" in body and "ProjectV2" in body:
            self.calls.append(list(args))
            return json.dumps({"data": {"node": {"repositories": {
                "nodes": [{"id": r} for r in sorted(self.linked_repo_ids)]}}}})
        # the project's currently-linked teams (idempotency read)
        if "teams(first:100)" in body and "ProjectV2" in body:
            self.calls.append(list(args))
            return json.dumps({"data": {"node": {"teams": {
                "nodes": [{"id": t} for t in sorted(self.linked_team_ids)]}}}})
        # linkProjectV2ToRepository — a WRITE
        if "linkProjectV2ToRepository" in body:
            self.calls.append(list(args))
            self.writes.append(("graphql", "linkProjectV2ToRepository"))
            return json.dumps({"data": {"linkProjectV2ToRepository": {
                "repository": {"id": REPO_NODE_ID}}}})
        # linkProjectV2ToTeam — a WRITE (the real write-to-team)
        if "linkProjectV2ToTeam(" in body:
            self.calls.append(list(args))
            self.writes.append(("graphql", "linkProjectV2ToTeam"))
            return json.dumps({"data": {"linkProjectV2ToTeam": {"team": {"id": TEAM_NODE_ID}}}})
        return super().__call__(args)


class CompletionBase(ScaffoldTestBase):
    def _plan(self, runner, repo_dir, *, repo="acme/web", title="Acme Board",
              team=None, do_copy=True):
        gh.RUN = runner
        return scaffold.build_plan(
            org="acme", template_title=TEMPLATE_TITLE, repo=repo,
            new_title=title, repo_dir=repo_dir, team=team, do_copy=do_copy,
        )


# --------------------------------------------------------------------------- #
# link_repo: real mutation + idempotency
# --------------------------------------------------------------------------- #
class TestLinkRepo(CompletionBase):
    def test_link_repo_is_real_linkprojectv2torepository(self):
        runner = CompletionRunner(linked_repo_ids=set())
        gh.RUN = runner
        res = gh.link_repo(COPY_PROJECT_ID, REPO_NODE_ID)
        self.assertTrue(res["changed"])
        call = next(c for c in runner.calls if "linkProjectV2ToRepository" in " ".join(map(str, c)))
        q = " ".join(map(str, call))
        # both the projectId and repositoryId are actually sent
        self.assertIn(f"project={COPY_PROJECT_ID}", q)
        self.assertIn(f"repo={REPO_NODE_ID}", q)

    def test_link_repo_skips_when_already_linked(self):
        runner = CompletionRunner(linked_repo_ids={REPO_NODE_ID})
        gh.RUN = runner
        res = gh.link_repo(COPY_PROJECT_ID, REPO_NODE_ID)
        self.assertFalse(res["changed"], "already-linked repo -> no write")
        self.assertNotIn(("graphql", "linkProjectV2ToRepository"), runner.writes)

    def test_link_repo_second_call_is_noop(self):
        # call 1: not linked -> writes; call 2: now linked -> no further write
        runner = CompletionRunner(linked_repo_ids=set())
        gh.RUN = runner
        gh.link_repo(COPY_PROJECT_ID, REPO_NODE_ID)
        runner.linked_repo_ids = {REPO_NODE_ID}  # the link took effect
        gh.link_repo(COPY_PROJECT_ID, REPO_NODE_ID)
        n = sum(1 for w in runner.writes if w == ("graphql", "linkProjectV2ToRepository"))
        self.assertEqual(n, 1, "second link of the same repo = one effective write total")

    def test_scaffold_plans_repo_link_when_repo_given(self):
        runner = CompletionRunner(linked_repo_ids=set())
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo="acme/web")
        rl = plan["repo_link"]
        self.assertIsNotNone(rl)
        self.assertEqual(rl["repo"], "acme/web")
        self.assertEqual(rl["repo_id"], REPO_NODE_ID)
        self.assertEqual(rl["action"], "link")

    def test_scaffold_repo_link_skip_on_rerun(self):
        # repo already linked on the copy -> the plan's repo_link is a SKIP (no-op)
        runner = CompletionRunner(linked_repo_ids={REPO_NODE_ID})
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo="acme/web")
        self.assertEqual(plan["repo_link"]["action"], "skip")

    def test_no_repo_means_no_repo_link(self):
        runner = CompletionRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo=None)
        self.assertIsNone(plan["repo_link"])


# --------------------------------------------------------------------------- #
# add-to-project.yml: registered, installed, SHA-pinned, App-token, no AI
# --------------------------------------------------------------------------- #
class TestAddToProjectWorkflow(CompletionBase):
    DEST = ".github/workflows/add-to-project.yml"
    SRC = "github/workflows/add-to-project.yml"

    def test_registered_in_install_files(self):
        srcs = {s for s, _ in scaffold.INSTALL_FILES}
        dests = {d for _, d in scaffold.INSTALL_FILES}
        self.assertIn(self.SRC, srcs)
        self.assertIn(self.DEST, dests)

    def test_template_file_exists_on_disk(self):
        self.assertTrue((scaffold.templates_dir() / self.SRC).is_file())

    def test_plan_file_install_installs_it(self):
        # planned as a fresh install into an empty repo, and actually written.
        with tempfile.TemporaryDirectory() as d:
            rows = scaffold.plan_file_install(d)
            row = next(r for r in rows if r["dest"] == self.DEST)
            self.assertEqual(row["action"], "install")
            written = scaffold.apply_file_install(d, rows)
            self.assertIn(self.DEST, written)
            self.assertTrue((Path(d) / self.DEST).is_file())

    def _template_text(self):
        return (scaffold.templates_dir() / self.SRC).read_text(encoding="utf-8")

    def test_add_to_project_action_is_sha_pinned(self):
        text = self._template_text()
        m = re.search(r"uses:\s*actions/add-to-project@(\S+)", text)
        self.assertIsNotNone(m, "the workflow must use actions/add-to-project")
        ref = m.group(1)
        self.assertRegex(ref, r"^[0-9a-f]{40}$",
                         f"actions/add-to-project must be pinned to a 40-hex SHA, got {ref!r}")

    def test_every_third_party_action_is_sha_pinned(self):
        # Pin ANY other third-party action by SHA too — no bare @vN tags.
        text = self._template_text()
        for m in re.finditer(r"uses:\s*(\S+)", text):
            ref = m.group(1)
            self.assertIn("@", ref)
            pin = ref.split("@", 1)[1]
            self.assertRegex(pin, r"^[0-9a-f]{40}$",
                             f"action {ref!r} must be SHA-pinned (40-hex), not a tag")

    def test_app_token_auth_not_github_token(self):
        # The project write must authenticate with the App installation token,
        # NEVER GITHUB_TOKEN (which cannot write org Projects v2).
        text = self._template_text()
        self.assertIn("create-github-app-token", text)
        self.assertIn("app-token.outputs.token", text)
        # No GITHUB_TOKEN wired as the add-to-project github-token.
        self.assertNotIn("github-token: ${{ secrets.GITHUB_TOKEN }}", text)
        self.assertNotIn("github-token: ${{ github.token }}", text)

    def test_no_metered_ai_in_template(self):
        # No metered AI/model call anywhere in the workflow.
        low = self._template_text().lower()
        for needle in ("anthropic", "openai", "claude", "gpt-", "inference",
                       "model:", "api.openai", "x-api-key"):
            self.assertNotIn(needle, low, f"metered-AI marker {needle!r} must not appear")


# --------------------------------------------------------------------------- #
# Team link (real linkProjectV2ToTeam) + base-role manual + app-access
#         stays a confirmation.
# --------------------------------------------------------------------------- #
class TestTeamLinkAndBaseRole(CompletionBase):
    def test_link_team_is_real_and_sends_teamid(self):
        runner = CompletionRunner()
        gh.RUN = runner
        res = gh.link_team(COPY_PROJECT_ID, TEAM_NODE_ID)
        self.assertTrue(res["linked"])
        call = next(c for c in runner.calls if "linkProjectV2ToTeam(" in " ".join(map(str, c)))
        q = " ".join(map(str, call))
        # the teamId is ACTUALLY in the mutation (distinguishes it from the
        # _LINK_PROJECT_APP confirmation, which sends no team id).
        self.assertIn("linkProjectV2ToTeam(", q)
        self.assertIn(f"team={TEAM_NODE_ID}", q)
        self.assertIn(f"project={COPY_PROJECT_ID}", q)

    def test_link_team_distinct_from_link_project_app_stub(self):
        # The scaffold _LINK_PROJECT_APP stub is an aliased updateProjectV2 with NO
        # team id; the real link_team mutation must carry teamId:$team.
        self.assertNotIn("teamId", scaffold._LINK_PROJECT_APP)
        self.assertIn("teamId:$team", gh._LINK_TEAM)

    def test_link_team_skips_when_already_linked(self):
        # A team already linked to the Project is detected and SKIPPED — no
        # write, never a 409/422 re-link (parity with link_repo).
        runner = CompletionRunner(linked_team_ids={TEAM_NODE_ID})
        gh.RUN = runner
        res = gh.link_team(COPY_PROJECT_ID, TEAM_NODE_ID)
        self.assertFalse(res["changed"], "already-linked team -> no write")
        self.assertNotIn(("graphql", "linkProjectV2ToTeam"), runner.writes)

    def test_link_team_second_call_is_noop(self):
        # Call 1 (not linked) writes; call 2 (now linked) makes no further
        # write — one effective write total across two calls.
        runner = CompletionRunner(linked_team_ids=set())
        gh.RUN = runner
        first = gh.link_team(COPY_PROJECT_ID, TEAM_NODE_ID)
        self.assertTrue(first["changed"])
        runner.linked_team_ids = {TEAM_NODE_ID}  # the link took effect
        second = gh.link_team(COPY_PROJECT_ID, TEAM_NODE_ID)
        self.assertFalse(second["changed"])
        n = sum(1 for w in runner.writes if w == ("graphql", "linkProjectV2ToTeam"))
        self.assertEqual(n, 1, "second link of the same team = one effective write total")

    def test_scaffold_plans_team_link_when_team_given(self):
        runner = CompletionRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, team="dev")
        tl = plan["team_link"]
        self.assertIsNotNone(tl)
        self.assertEqual(tl["team"], "dev")
        self.assertEqual(tl["team_id"], TEAM_NODE_ID)
        self.assertEqual(tl["action"], "link")

    def test_base_role_is_a_manual_step_in_the_manifest(self):
        runner = CompletionRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, team="dev")
        manual = plan["base_role_manual"]
        self.assertIsNotNone(manual)
        low = manual.lower()
        self.assertIn("base role", low)
        self.assertIn("ui-only", low)
        self.assertIn("manual", low)
        # it appears in the rendered manifest + the human checklist
        rendered = scaffold.render_manifest(plan)
        self.assertIn("Team link", rendered)
        self.assertIn(manual, rendered)
        self.assertIn(manual, plan["human_checklist"])

    def test_no_base_role_mutation_attempted(self):
        # There is NO base-role API; the scaffold must never emit a base-role
        # mutation anywhere (updateProjectV2 has no base-role field).
        runner = CompletionRunner()
        with tempfile.TemporaryDirectory() as d:
            self._plan(runner, d, team="dev")
            plan = scaffold.build_plan(org="acme", template_title=TEMPLATE_TITLE,
                                       repo="acme/web", new_title="Acme Board",
                                       repo_dir=d, team="dev", do_copy=True)
            scaffold.apply_plan(plan, repo_dir=d, force=True)
        for call in runner.calls:
            q = " ".join(map(str, call)).lower()
            self.assertNotIn("baserole", q.replace("_", "").replace("-", ""))

    def test_grant_app_access_stays_a_confirmation_not_a_grant(self):
        # grant_app_access must remain a confirmation touch (the App already has
        # org Projects-write via its installation) — NOT a bare no-op pretending
        # to be a grant, and NOT a base-role mutation.
        runner = CompletionRunner()
        gh.RUN = runner
        res = scaffold.grant_app_access(COPY_PROJECT_ID)
        self.assertTrue(res["confirmed"])
        self.assertNotIn("granted", res, "must be a confirmation, not a 'granted' grant")
        # it touches the project via the _LINK_PROJECT_APP confirmation (no team id)
        touch = next(c for c in runner.calls if "updateProjectV2" in " ".join(map(str, c))
                     and "fields(first:100)" not in " ".join(map(str, c)))
        q = " ".join(map(str, touch))
        self.assertNotIn("teamId", q)
        self.assertNotIn("baseRole", q)

    def test_no_team_means_no_team_link(self):
        runner = CompletionRunner()
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, team=None)
        self.assertIsNone(plan["team_link"])
        self.assertIsNone(plan["base_role_manual"])


# --------------------------------------------------------------------------- #
# Dry-by-default, idempotent, diff-before-mutate; re-run manifest empty.
# --------------------------------------------------------------------------- #
class TestCompletionsDryAndIdempotent(CompletionBase):
    def test_dry_run_makes_no_link_writes(self):
        runner = CompletionRunner(linked_repo_ids=set())
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo="acme/web", team="dev")
            writes_after_plan = list(runner.writes)
            actions = scaffold.apply_plan(plan, repo_dir=d, force=False)
        self.assertEqual(runner.writes, writes_after_plan,
                         "dry apply must add no link writes")
        self.assertIsNone(actions["repo_link"])
        self.assertIsNone(actions["team_link"])
        self.assertNotIn(("graphql", "linkProjectV2ToRepository"), runner.writes)
        self.assertNotIn(("graphql", "linkProjectV2ToTeam"), runner.writes)

    def test_force_applies_both_links(self):
        runner = CompletionRunner(linked_repo_ids=set())
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo="acme/web", team="dev")
            actions = scaffold.apply_plan(plan, repo_dir=d, force=True)
        self.assertTrue(actions["repo_link"]["changed"])
        self.assertTrue(actions["team_link"]["linked"])
        self.assertIn(("graphql", "linkProjectV2ToRepository"), runner.writes)
        self.assertIn(("graphql", "linkProjectV2ToTeam"), runner.writes)

    def test_rerun_repo_link_is_empty_no_blind_relink(self):
        # On a re-run where the repo is already linked, the plan's repo_link is a
        # SKIP and apply issues NO link mutation (diff-before-mutate).
        runner = CompletionRunner(linked_repo_ids={REPO_NODE_ID})
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo="acme/web")
            self.assertEqual(plan["repo_link"]["action"], "skip")
            actions = scaffold.apply_plan(plan, repo_dir=d, force=True)
        self.assertFalse(actions["repo_link"]["changed"])
        self.assertNotIn(("graphql", "linkProjectV2ToRepository"), runner.writes)

    def test_rerun_team_link_is_empty_no_blind_relink(self):
        # On a re-run where the team is already linked, the plan's team_link is a
        # SKIP and apply issues NO link mutation (diff-before-mutate).
        runner = CompletionRunner(linked_repo_ids={REPO_NODE_ID}, linked_team_ids={TEAM_NODE_ID})
        with tempfile.TemporaryDirectory() as d:
            plan = self._plan(runner, d, repo="acme/web", team="dev")
            self.assertEqual(plan["team_link"]["action"], "skip")
            actions = scaffold.apply_plan(plan, repo_dir=d, force=True)
        self.assertFalse(actions["team_link"]["changed"])
        self.assertNotIn(("graphql", "linkProjectV2ToTeam"), runner.writes)

    def test_rerun_install_manifest_empty_for_add_to_project(self):
        # After a first --force install, the add-to-project.yml is identical ->
        # the second run's install manifest SKIPs it (re-run no-op).
        runner = CompletionRunner()
        with tempfile.TemporaryDirectory() as d:
            plan1 = self._plan(runner, d, repo="acme/web")
            scaffold.apply_plan(plan1, repo_dir=d, force=True)
            plan2 = self._plan(runner, d, repo="acme/web")
            row = next(r for r in plan2["files"]
                       if r["dest"] == ".github/workflows/add-to-project.yml")
            self.assertEqual(row["action"], "skip",
                             "second run: add-to-project.yml already installed -> skip")


if __name__ == "__main__":
    unittest.main()
