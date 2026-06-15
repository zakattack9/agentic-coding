#!/usr/bin/env python3
"""Unit tests for Ralph Loop hook scripts.

Tests context_monitor.py and stop_loop_reminder.py against the full
verification matrix from the implementation checklist Phase 6.

Run: python3 -m pytest tests/test_hooks.py -v
  or: python3 tests/test_hooks.py
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil

# Resolve paths relative to the ralph plugin root
# Tests live at ralph/tests/, plugin lives at claude-code/plugins/ralph/
PLUGIN_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "claude-code", "plugins", "ralph")
CONTEXT_MONITOR = os.path.join(PLUGIN_ROOT, "hooks", "scripts", "context_monitor.py")
STOP_HOOK = os.path.join(PLUGIN_ROOT, "hooks", "scripts", "stop_loop_reminder.py")


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def run_hook(script_path: str, stdin_data: dict, cwd: str = None, env: dict = None) -> dict:
    """Run a hook script with JSON stdin and return parsed JSON output."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    result = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps(stdin_data),
        capture_output=True, text=True, timeout=10,
        cwd=cwd, env=run_env,
    )
    if result.stdout.strip():
        return json.loads(result.stdout)
    return {}


def make_story(**overrides) -> dict:
    """Create a valid story with sensible defaults."""
    story = {
        "id": "US-001",
        "title": "Test story",
        "description": "A test story",
        "acceptanceCriteria": ["It works"],
        "priority": 1,
        "passes": False,
        "reviewStatus": None,
        "reviewCount": 0,
        "reviewFeedback": "",
        "notes": "",
        "dependsOn": [],
    }
    story.update(overrides)
    return story


def make_tasks(stories: list = None, **top_overrides) -> dict:
    """Create a valid tasks.json structure."""
    tasks = {
        "project": "test",
        "branchName": "ralph/test",
        "description": "Test tasks",
        "verifyCommands": [],
        "userStories": stories or [make_story()],
    }
    tasks.update(top_overrides)
    return tasks


def make_ralph_active(**overrides) -> dict:
    """Create a .ralph-active marker."""
    active = {
        "timestamp": "2025-06-15T10:30:00Z",
        "pid": os.getpid(),
        "max_iterations": 15,
        "mode": "direct",
        "skipReview": False,
        "reviewCap": 5,
    }
    active.update(overrides)
    return active


class StopHookTestEnv:
    """Context manager for setting up stop hook test environment."""

    def __init__(self, tasks: dict = None, ralph_active: dict = None,
                 has_ralph_active: bool = True, git_clean: bool = True):
        self.tasks = tasks or make_tasks()
        self.ralph_active = ralph_active or make_ralph_active()
        self.has_ralph_active = has_ralph_active
        self.git_clean = git_clean
        self.tmpdir = None

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ralph-test-")

        # Create ralph/ directory with tasks.json
        ralph_dir = os.path.join(self.tmpdir, "ralph")
        os.makedirs(ralph_dir)
        with open(os.path.join(ralph_dir, "tasks.json"), "w") as f:
            json.dump(self.tasks, f, indent=2)

        # Create .ralph-active if needed
        if self.has_ralph_active:
            with open(os.path.join(self.tmpdir, ".ralph-active"), "w") as f:
                json.dump(self.ralph_active, f, indent=2)

        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=self.tmpdir,
                       capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=self.tmpdir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=self.tmpdir, capture_output=True, check=True)
        # Commit everything if clean
        subprocess.run(["git", "add", "-A"], cwd=self.tmpdir,
                       capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init", "--allow-empty"],
                       cwd=self.tmpdir, capture_output=True, check=True)

        if not self.git_clean:
            # Create uncommitted changes
            with open(os.path.join(self.tmpdir, "dirty.txt"), "w") as f:
                f.write("uncommitted")

        return self

    def __exit__(self, *args):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run(self, stdin_data: dict = None) -> dict:
        return run_hook(STOP_HOOK, stdin_data or {}, cwd=self.tmpdir)


# ────────────────────────────────────────────────────────────────────────────
# Context Monitor Tests (6.2)
# ────────────────────────────────────────────────────────────────────────────

class TestContextMonitor:
    """Tests for context_monitor.py."""

    def test_no_transcript_file_no_crash(self):
        """Missing transcript file should not crash."""
        result = run_hook(CONTEXT_MONITOR, {
            "transcript_path": "/nonexistent/file",
            "session_id": "test-session-1",
        })
        assert result == {}

    def test_empty_input_no_crash(self):
        """Empty/invalid stdin should not crash."""
        result = run_hook(CONTEXT_MONITOR, {})
        assert result == {}

    def test_alerts_fire_at_correct_thresholds(self):
        """Verify alerts fire at 50%, 60%, 70%, 80%, 90%."""
        session_id = f"test-threshold-{os.getpid()}"
        state_file = f"/tmp/claude-context-alerts-{session_id}"
        # Clean up any prior state
        if os.path.exists(state_file):
            os.remove(state_file)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as tf:
            transcript_path = tf.name

        try:
            # 200k tokens * 4 chars/token = 800k chars for 100%
            # So 50% = 400k chars, 60% = 480k, 70% = 560k, 80% = 640k, 90% = 720k

            thresholds_and_sizes = [
                (50, 400_001),  # Just over 50%
                (60, 480_001),  # Just over 60%
                (70, 560_001),  # Just over 70%
                (80, 640_001),  # Just over 80%
                (90, 720_001),  # Just over 90%
            ]

            fired_severities = []
            for threshold, size in thresholds_and_sizes:
                # Write a file of the exact size needed
                with open(transcript_path, "wb") as f:
                    f.write(b"x" * size)

                result = run_hook(CONTEXT_MONITOR, {
                    "transcript_path": transcript_path,
                    "session_id": session_id,
                })

                if result:
                    msg = result.get("hookSpecificOutput", {}).get("additionalContext", "")
                    fired_severities.append((threshold, msg))

            # Should have 5 alerts
            assert len(fired_severities) == 5, f"Expected 5 alerts, got {len(fired_severities)}"

            # Check severity levels
            assert "NOTICE" in fired_severities[0][1]   # 50%
            assert "NOTICE" in fired_severities[1][1]   # 60%
            assert "WARNING" in fired_severities[2][1]  # 70%
            assert "WARNING" in fired_severities[3][1]  # 80%
            assert "CRITICAL" in fired_severities[4][1] # 90%

        finally:
            os.unlink(transcript_path)
            if os.path.exists(state_file):
                os.remove(state_file)

    def test_each_threshold_fires_only_once(self):
        """Once a threshold fires, it should not fire again."""
        session_id = f"test-once-{os.getpid()}"
        state_file = f"/tmp/claude-context-alerts-{session_id}"
        if os.path.exists(state_file):
            os.remove(state_file)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as tf:
            transcript_path = tf.name

        try:
            # Write enough for 50%
            with open(transcript_path, "wb") as f:
                f.write(b"x" * 400_001)

            # First call should fire
            r1 = run_hook(CONTEXT_MONITOR, {
                "transcript_path": transcript_path,
                "session_id": session_id,
            })
            assert "additionalContext" in r1.get("hookSpecificOutput", {})

            # Second call with same size should NOT fire (50% already recorded)
            r2 = run_hook(CONTEXT_MONITOR, {
                "transcript_path": transcript_path,
                "session_id": session_id,
            })
            assert r2 == {}

        finally:
            os.unlink(transcript_path)
            if os.path.exists(state_file):
                os.remove(state_file)

    def test_below_threshold_no_alert(self):
        """Below 50% should produce no alert."""
        session_id = f"test-below-{os.getpid()}"
        state_file = f"/tmp/claude-context-alerts-{session_id}"
        if os.path.exists(state_file):
            os.remove(state_file)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as tf:
            transcript_path = tf.name

        try:
            # Write only 30% worth
            with open(transcript_path, "wb") as f:
                f.write(b"x" * 240_000)

            result = run_hook(CONTEXT_MONITOR, {
                "transcript_path": transcript_path,
                "session_id": session_id,
            })
            assert result == {}

        finally:
            os.unlink(transcript_path)
            if os.path.exists(state_file):
                os.remove(state_file)


# ────────────────────────────────────────────────────────────────────────────
# Stop Hook: Check 1 — Schema Validation (6.2)
# ────────────────────────────────────────────────────────────────────────────

class TestStopHookSchema:
    """Check 1: Task list schema validation."""

    def test_valid_tasks_passes(self):
        """Valid tasks.json passes Check 1."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved", reviewCount=1,
                       notes="Implemented feature X"),
        ])
        active = make_ralph_active(skipReview=True)  # skip review for schema-only test
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_missing_top_level_field_blocks(self):
        """Missing required top-level field blocks."""
        tasks = make_tasks()
        del tasks["branchName"]
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "branchName" in result["reason"]

    def test_missing_story_field_blocks(self):
        """Missing required story field blocks."""
        story = make_story()
        del story["acceptanceCriteria"]
        tasks = make_tasks([story])
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "acceptanceCriteria" in result["reason"]

    def test_duplicate_story_ids_blocks(self):
        """Duplicate story IDs block."""
        tasks = make_tasks([
            make_story(id="US-001"),
            make_story(id="US-001"),
        ])
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "Duplicate" in result["reason"]

    def test_passes_true_empty_notes_blocks(self):
        """passes: true with empty notes blocks."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved", reviewCount=1, notes=""),
        ])
        # Use skipReview to isolate Check 1
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "notes" in result["reason"]

    def test_invalid_review_status_blocks(self):
        """Invalid reviewStatus value blocks."""
        tasks = make_tasks([make_story(reviewStatus="invalid_status")])
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "reviewStatus" in result["reason"]

    def test_negative_review_count_blocks(self):
        """reviewCount: -1 blocks."""
        tasks = make_tasks([make_story(reviewCount=-1)])
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "non-negative" in result["reason"]

    def test_empty_acceptance_criteria_blocks(self):
        """Empty acceptanceCriteria blocks."""
        tasks = make_tasks([make_story(acceptanceCriteria=[])])
        with StopHookTestEnv(tasks=tasks, ralph_active=make_ralph_active(skipReview=True)) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "acceptanceCriteria" in result["reason"]

    def test_no_ralph_active_approves(self):
        """Without .ralph-active, hook approves (not activated)."""
        with StopHookTestEnv(has_ralph_active=False) as env:
            result = env.run()
            assert result["decision"] == "approve"


# ────────────────────────────────────────────────────────────────────────────
# Stop Hook: Check 2 — Review Integrity (6.2)
# ────────────────────────────────────────────────────────────────────────────

class TestStopHookReviewIntegrity:
    """Check 2: Review state invariants."""

    def test_passes_true_review_null_blocks(self):
        """passes: true + reviewStatus: null blocks."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus=None, notes="done"),
        ])
        with StopHookTestEnv(tasks=tasks) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "not 'approved'" in result["reason"]

    def test_passes_true_needs_review_blocks(self):
        """passes: true + reviewStatus: needs_review blocks."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="needs_review", notes="done"),
        ])
        with StopHookTestEnv(tasks=tasks) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "not 'approved'" in result["reason"]

    def test_passes_true_changes_requested_blocks(self):
        """passes: true + reviewStatus: changes_requested blocks."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="changes_requested",
                       reviewFeedback="fix this", notes="done"),
        ])
        with StopHookTestEnv(tasks=tasks) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "not 'approved'" in result["reason"]

    def test_passes_true_approved_passes(self):
        """passes: true + reviewStatus: approved passes."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved",
                       reviewCount=1, notes="done"),
        ])
        # Need snapshot where this was already approved to pass transition check
        active = make_ralph_active(
            iterationMode="review",
            preIterationSnapshot={
                "US-001": {"passes": False, "reviewStatus": "needs_review", "reviewCount": 0}
            }
        )
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_changes_requested_empty_feedback_blocks(self):
        """reviewStatus: changes_requested + empty reviewFeedback blocks."""
        tasks = make_tasks([
            make_story(reviewStatus="changes_requested", reviewFeedback=""),
        ])
        with StopHookTestEnv(tasks=tasks) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "reviewFeedback" in result["reason"]

    def test_approved_passes_false_blocks(self):
        """reviewStatus: approved + passes: false blocks."""
        tasks = make_tasks([
            make_story(passes=False, reviewStatus="approved"),
        ])
        with StopHookTestEnv(tasks=tasks) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "passes=false" in result["reason"]

    def test_skip_review_bypasses_check2(self):
        """skipReview: true skips Check 2 entirely."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus=None, notes="done in skip mode"),
        ])
        active = make_ralph_active(skipReview=True)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"


# ────────────────────────────────────────────────────────────────────────────
# Stop Hook: Check 2.5 — Transition Validation (6.2)
# ────────────────────────────────────────────────────────────────────────────

class TestStopHookTransitions:
    """Check 2.5: State transition validation."""

    # ── Implement mode ────────────────────────────────────────────────────

    def test_implement_passes_false_to_true_blocks(self):
        """Implement mode: passes false→true blocks."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved", reviewCount=1, notes="done"),
        ])
        active = make_ralph_active(iterationMode="implement", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "passes" in result["reason"].lower() or "implement" in result["reason"].lower()

    def test_implement_review_status_to_approved_blocks(self):
        """Implement mode: reviewStatus null→approved blocks."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(reviewStatus="approved", passes=True, reviewCount=1, notes="done"),
        ])
        active = make_ralph_active(iterationMode="implement", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"

    def test_implement_review_count_changed_blocks(self):
        """Implement mode: reviewCount 0→1 blocks."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(reviewCount=1),
        ])
        active = make_ralph_active(iterationMode="implement", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "reviewCount" in result["reason"]

    def test_implement_null_to_needs_review_passes(self):
        """Implement mode: reviewStatus null→needs_review passes (legal transition)."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(reviewStatus="needs_review"),
        ])
        active = make_ralph_active(iterationMode="implement", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_implement_new_story_valid_passes(self):
        """Implement mode: new story with valid initial state passes."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(id="US-001"),
            make_story(id="US-002", passes=False, reviewStatus=None, reviewCount=0),
        ])
        active = make_ralph_active(iterationMode="implement", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_implement_new_story_passes_true_blocks(self):
        """Implement mode: new story with passes: true blocks."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(id="US-001"),
            make_story(id="US-002", passes=True, reviewStatus=None, reviewCount=0, notes="nope"),
        ])
        active = make_ralph_active(iterationMode="implement", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "US-002" in result["reason"]

    # ── Review mode ───────────────────────────────────────────────────────

    def test_review_legal_approval_passes(self):
        """Review mode: legal approval (reviewCount+1, approved, passes=true) passes."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": "needs_review", "reviewCount": 0}}
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved", reviewCount=1, notes="done"),
        ])
        active = make_ralph_active(iterationMode="review", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_review_legal_rejection_passes(self):
        """Review mode: legal rejection (reviewCount+1, changes_requested, feedback) passes."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": "needs_review", "reviewCount": 0}}
        tasks = make_tasks([
            make_story(reviewStatus="changes_requested", reviewCount=1,
                       reviewFeedback="Fix the edge case in X"),
        ])
        active = make_ralph_active(iterationMode="review", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_review_count_unchanged_blocks(self):
        """Review mode: reviewCount unchanged blocks."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": "needs_review", "reviewCount": 1}}
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved", reviewCount=1, notes="done"),
        ])
        active = make_ralph_active(iterationMode="review", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "reviewCount" in result["reason"]

    def test_review_two_stories_changed_blocks(self):
        """Review mode: two stories' review fields changed blocks."""
        snapshot = {
            "US-001": {"passes": False, "reviewStatus": "needs_review", "reviewCount": 0},
            "US-002": {"passes": False, "reviewStatus": "needs_review", "reviewCount": 0},
        }
        tasks = make_tasks([
            make_story(id="US-001", passes=True, reviewStatus="approved",
                       reviewCount=1, notes="done"),
            make_story(id="US-002", passes=True, reviewStatus="approved",
                       reviewCount=1, notes="done too"),
        ])
        active = make_ralph_active(iterationMode="review", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "multiple stories" in result["reason"].lower()

    # ── Review-fix mode ───────────────────────────────────────────────────

    def test_review_fix_legal_resubmit_passes(self):
        """Review-fix mode: legal resubmit (changes_requested→needs_review, feedback cleared) passes."""
        snapshot = {
            "US-001": {"passes": False, "reviewStatus": "changes_requested", "reviewCount": 1},
        }
        tasks = make_tasks([
            make_story(reviewStatus="needs_review", reviewCount=1, reviewFeedback=""),
        ])
        active = make_ralph_active(iterationMode="review-fix", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_review_fix_passes_changed_blocks(self):
        """Review-fix mode: passes changed blocks."""
        snapshot = {
            "US-001": {"passes": False, "reviewStatus": "changes_requested", "reviewCount": 1},
        }
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="needs_review", reviewCount=1, notes="done"),
        ])
        active = make_ralph_active(iterationMode="review-fix", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "passes" in result["reason"].lower()

    def test_review_fix_review_count_changed_blocks(self):
        """Review-fix mode: reviewCount changed blocks."""
        snapshot = {
            "US-001": {"passes": False, "reviewStatus": "changes_requested", "reviewCount": 1},
        }
        tasks = make_tasks([
            make_story(reviewStatus="needs_review", reviewCount=2, reviewFeedback=""),
        ])
        active = make_ralph_active(iterationMode="review-fix", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "reviewCount" in result["reason"]

    def test_review_fix_to_approved_blocks(self):
        """Review-fix mode: reviewStatus → approved blocks."""
        snapshot = {
            "US-001": {"passes": False, "reviewStatus": "changes_requested", "reviewCount": 1},
        }
        tasks = make_tasks([
            make_story(reviewStatus="approved", passes=True, reviewCount=1, notes="done"),
        ])
        active = make_ralph_active(iterationMode="review-fix", preIterationSnapshot=snapshot)
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"

    # ── Snapshot missing (graceful degradation) ───────────────────────────

    def test_missing_snapshot_skips_check25(self):
        """Missing preIterationSnapshot → Check 2.5 skipped, Check 2 still runs."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus="approved", reviewCount=1, notes="done"),
        ])
        # No preIterationSnapshot in ralph_active
        active = make_ralph_active()
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            # Check 2 passes (passes=true + approved), Check 2.5 skipped
            assert result["decision"] == "approve", f"Expected approve, got: {result}"

    def test_missing_snapshot_check2_still_enforced(self):
        """Missing snapshot: Check 2 still catches invariant violations."""
        tasks = make_tasks([
            make_story(passes=True, reviewStatus=None, notes="done"),
        ])
        active = make_ralph_active()  # No snapshot
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "not 'approved'" in result["reason"]

    # ── Skip-review mode ──────────────────────────────────────────────────

    def test_skip_review_bypasses_check25(self):
        """skipReview: true skips Check 2.5 entirely."""
        snapshot = {"US-001": {"passes": False, "reviewStatus": None, "reviewCount": 0}}
        tasks = make_tasks([
            make_story(passes=True, reviewStatus=None, reviewCount=0, notes="done"),
        ])
        active = make_ralph_active(
            skipReview=True,
            iterationMode="implement",
            preIterationSnapshot=snapshot,
        )
        with StopHookTestEnv(tasks=tasks, ralph_active=active) as env:
            result = env.run()
            assert result["decision"] == "approve", f"Expected approve, got: {result}"


# ────────────────────────────────────────────────────────────────────────────
# Stop Hook: Check 3 — Uncommitted Changes (6.2)
# ────────────────────────────────────────────────────────────────────────────

class TestStopHookUncommittedChanges:
    """Check 3: Uncommitted changes."""

    def test_uncommitted_changes_blocks(self):
        """Uncommitted changes block with commit instructions."""
        tasks = make_tasks([make_story()])
        active = make_ralph_active(skipReview=True)
        with StopHookTestEnv(tasks=tasks, ralph_active=active, git_clean=False) as env:
            result = env.run()
            assert result["decision"] == "block"
            assert "uncommitted" in result["reason"].lower()

    def test_clean_working_tree_passes(self):
        """Clean working tree passes Check 3."""
        tasks = make_tasks([make_story()])
        active = make_ralph_active(skipReview=True)
        with StopHookTestEnv(tasks=tasks, ralph_active=active, git_clean=True) as env:
            result = env.run()
            assert result["decision"] == "approve"


# ────────────────────────────────────────────────────────────────────────────
# Entry point for running without pytest
# ────────────────────────────────────────────────────────────────────────────

def run_all_tests():
    """Simple test runner for running without pytest."""
    test_classes = [
        TestContextMonitor,
        TestStopHookSchema,
        TestStopHookReviewIntegrity,
        TestStopHookTransitions,
        TestStopHookUncommittedChanges,
    ]

    total = 0
    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in sorted(methods):
            total += 1
            test_func = getattr(instance, method_name)
            test_id = f"{cls.__name__}::{method_name}"
            try:
                test_func()
                passed += 1
                print(f"  PASS  {test_id}")
            except Exception as e:
                failed += 1
                errors.append((test_id, e))
                print(f"  FAIL  {test_id}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print(f"\nFailed tests:")
        for test_id, err in errors:
            print(f"  {test_id}: {err}")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
