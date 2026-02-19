#!/usr/bin/env python3
"""stop_loop_reminder.py — Stop hook for Ralph Loop.

Runs three checks (plus a transition validation sub-check) before allowing Claude to stop:
  Check 1: Task list schema validation
  Check 2: Review integrity enforcement (state invariants)
  Check 2.5: Transition validation (state transitions)
  Check 3: Uncommitted changes

All checks must pass or the stop is blocked.
Only activates when .ralph-active exists.

Input: JSON on stdin (hook metadata)
Output: JSON with decision: "approve" or "block" + reason
"""

import json
import os
import subprocess
import sys

VALID_REVIEW_STATUSES = {None, "needs_review", "changes_requested", "approved"}
REQUIRED_STORY_FIELDS = {
    "id": str,
    "title": str,
    "passes": bool,
    "priority": (int, float),
    "acceptanceCriteria": list,
    "reviewStatus": (str, type(None)),
    "reviewCount": int,
    "reviewFeedback": str,
}


def block(reason: str):
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(0)


def approve():
    json.dump({"decision": "approve"}, sys.stdout)
    sys.exit(0)


def find_ralph_dir() -> str:
    """Find the ralph/ directory relative to cwd."""
    if os.path.isdir("ralph"):
        return "ralph"
    return ""


def load_json_file(path: str) -> dict | None:
    """Load and parse a JSON file, returning None on failure."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def check_schema(tasks: dict, ralph_dir: str) -> str | None:
    """Check 1: Validate tasks.json schema. Returns error message or None."""
    # Top-level fields
    for field in ("project", "branchName", "description"):
        if field not in tasks:
            return f"tasks.json missing required top-level field: '{field}'"

    if "userStories" not in tasks:
        return "tasks.json missing required field: 'userStories'"
    if not isinstance(tasks["userStories"], list):
        return "tasks.json 'userStories' must be an array"

    seen_ids = set()
    for i, story in enumerate(tasks["userStories"]):
        story_label = story.get("id", f"story[{i}]")

        # Required fields and types
        for field, expected_type in REQUIRED_STORY_FIELDS.items():
            if field not in story:
                return f"Story {story_label}: missing required field '{field}'"
            if not isinstance(story[field], expected_type if isinstance(expected_type, tuple) else (expected_type,)):
                return f"Story {story_label}: field '{field}' has wrong type (expected {expected_type.__name__ if not isinstance(expected_type, tuple) else '/'.join(t.__name__ for t in expected_type)})"

        # id must be string
        if not isinstance(story["id"], str):
            return f"Story at index {i}: 'id' must be a string"

        # Unique IDs
        if story["id"] in seen_ids:
            return f"Duplicate story ID: '{story['id']}'"
        seen_ids.add(story["id"])

        # acceptanceCriteria must be non-empty
        if len(story["acceptanceCriteria"]) == 0:
            return f"Story {story_label}: 'acceptanceCriteria' must not be empty"

        # reviewStatus must be a valid value
        if story["reviewStatus"] not in VALID_REVIEW_STATUSES:
            return f"Story {story_label}: 'reviewStatus' is '{story['reviewStatus']}', must be null or one of: needs_review, changes_requested, approved"

        # reviewCount must be non-negative
        if story["reviewCount"] < 0:
            return f"Story {story_label}: 'reviewCount' must be non-negative (got {story['reviewCount']})"

        # passes: true requires non-empty notes
        if story["passes"] and not story.get("notes", "").strip():
            return f"Story {story_label}: has passes=true but empty 'notes' — document what was done"

    return None


def check_review_integrity(tasks: dict, ralph_active: dict) -> str | None:
    """Check 2: Review state invariants. Returns error message or None.
    Skipped entirely when skipReview is true."""
    if ralph_active.get("skipReview", False):
        return None

    review_cap = ralph_active.get("reviewCap", 5)

    for story in tasks["userStories"]:
        sid = story["id"]
        passes = story["passes"]
        review_status = story["reviewStatus"]
        review_count = story["reviewCount"]
        review_feedback = story.get("reviewFeedback", "")

        # passes: true requires reviewStatus: "approved"
        if passes and review_status != "approved":
            return (
                f"Story {sid} has passes=true but reviewStatus is "
                f"'{review_status}', not 'approved'. Only review iterations "
                f"may approve stories. Set passes back to false or complete "
                f"the review cycle."
            )

        # reviewStatus: "approved" requires passes: true
        if review_status == "approved" and not passes:
            return (
                f"Story {sid} has reviewStatus='approved' but passes=false. "
                f"These fields must be in sync."
            )

        # changes_requested requires non-empty reviewFeedback
        if review_status == "changes_requested" and not review_feedback.strip():
            return (
                f"Story {sid} has reviewStatus='changes_requested' but empty "
                f"reviewFeedback. Review must explain what needs fixing."
            )

        # reviewCount sanity check
        if review_count > review_cap + 1:
            return (
                f"Story {sid} has reviewCount={review_count} which exceeds "
                f"reviewCap+1 ({review_cap + 1}). Possible corruption."
            )

    return None


def check_transitions(tasks: dict, ralph_active: dict) -> str | None:
    """Check 2.5: Transition validation against pre-iteration snapshot.
    Returns error message or None. Skipped when skipReview is true or snapshot is missing."""
    if ralph_active.get("skipReview", False):
        return None

    iteration_mode = ralph_active.get("iterationMode")
    snapshot = ralph_active.get("preIterationSnapshot")

    if not iteration_mode or not snapshot:
        # Graceful degradation — Check 2 still runs
        return None

    # Build current state map
    current = {}
    for story in tasks["userStories"]:
        current[story["id"]] = {
            "passes": story["passes"],
            "reviewStatus": story["reviewStatus"],
            "reviewCount": story["reviewCount"],
        }

    if iteration_mode == "implement":
        return _check_implement_transitions(current, snapshot)
    elif iteration_mode == "review":
        return _check_review_transitions(current, snapshot)
    elif iteration_mode == "review-fix":
        return _check_review_fix_transitions(current, snapshot)

    return None


def _check_implement_transitions(current: dict, snapshot: dict) -> str | None:
    """Implement mode: no passes/reviewCount changes. At most one null -> needs_review."""
    needs_review_transitions = 0

    for sid, snap in snapshot.items():
        if sid not in current:
            continue  # Story was removed (unusual but not a transition violation)
        cur = current[sid]

        # passes must not change to true
        if not snap["passes"] and cur["passes"]:
            return (
                f"Implement iterations cannot set passes=true or approve stories. "
                f"Only review iterations may approve. Story {sid} had illegal "
                f"transition: passes false -> true."
            )

        # reviewStatus must not change to "approved"
        if snap["reviewStatus"] != "approved" and cur["reviewStatus"] == "approved":
            return (
                f"Implement iterations cannot set passes=true or approve stories. "
                f"Only review iterations may approve. Story {sid} had illegal "
                f"transition: reviewStatus '{snap['reviewStatus']}' -> 'approved'."
            )

        # reviewCount must not change
        if snap["reviewCount"] != cur["reviewCount"]:
            return (
                f"Implement iterations cannot set passes=true or approve stories. "
                f"Only review iterations may approve. Story {sid} had illegal "
                f"transition: reviewCount {snap['reviewCount']} -> {cur['reviewCount']}."
            )

        # Track null -> needs_review transitions
        if snap["reviewStatus"] is None and cur["reviewStatus"] == "needs_review":
            needs_review_transitions += 1

        # Other reviewStatus changes (that aren't null -> needs_review) are illegal
        if snap["reviewStatus"] != cur["reviewStatus"]:
            if not (snap["reviewStatus"] is None and cur["reviewStatus"] == "needs_review"):
                return (
                    f"Implement iterations cannot change reviewStatus from "
                    f"'{snap['reviewStatus']}' to '{cur['reviewStatus']}' on story {sid}."
                )

    # Check new stories (in current but not in snapshot)
    for sid, cur in current.items():
        if sid not in snapshot:
            if cur["passes"]:
                return (
                    f"New story {sid} must start with passes=false "
                    f"(got passes=true)."
                )
            if cur["reviewStatus"] is not None:
                return (
                    f"New story {sid} must start with reviewStatus=null "
                    f"(got '{cur['reviewStatus']}')."
                )
            if cur["reviewCount"] != 0:
                return (
                    f"New story {sid} must start with reviewCount=0 "
                    f"(got {cur['reviewCount']})."
                )

    return None


def _check_review_transitions(current: dict, snapshot: dict) -> str | None:
    """Review mode: exactly one story's review fields change. reviewCount increments by 1."""
    changed_stories = []

    for sid, snap in snapshot.items():
        if sid not in current:
            continue
        cur = current[sid]

        review_fields_changed = (
            snap["passes"] != cur["passes"]
            or snap["reviewStatus"] != cur["reviewStatus"]
            or snap["reviewCount"] != cur["reviewCount"]
        )

        if review_fields_changed:
            changed_stories.append(sid)

    if len(changed_stories) == 0:
        # No review fields changed — that's fine if the review found nothing to do
        # (though unusual, not illegal)
        return None

    if len(changed_stories) > 1:
        return (
            f"Review iteration made illegal transition: modified review fields "
            f"on multiple stories ({', '.join(changed_stories)}). "
            f"Review may only modify one story per iteration."
        )

    sid = changed_stories[0]
    snap = snapshot[sid]
    cur = current[sid]

    # reviewCount must increment by exactly 1
    if cur["reviewCount"] != snap["reviewCount"] + 1:
        return (
            f"Review iteration made illegal transition on story {sid}: "
            f"reviewCount must increment by exactly 1 "
            f"(was {snap['reviewCount']}, now {cur['reviewCount']})."
        )

    # Two legal outcomes: approved or changes_requested
    if cur["reviewStatus"] == "approved":
        if not cur["passes"]:
            return (
                f"Review iteration made illegal transition on story {sid}: "
                f"set reviewStatus='approved' but passes is still false."
            )
    elif cur["reviewStatus"] == "changes_requested":
        if cur["passes"]:
            return (
                f"Review iteration made illegal transition on story {sid}: "
                f"set reviewStatus='changes_requested' but passes is true."
            )
    else:
        return (
            f"Review iteration made illegal transition on story {sid}: "
            f"reviewStatus changed to '{cur['reviewStatus']}' — must be "
            f"'approved' or 'changes_requested' after a review."
        )

    return None


def _check_review_fix_transitions(current: dict, snapshot: dict) -> str | None:
    """Review-fix mode: one story changes_requested -> needs_review. No other review field changes."""
    changed_stories = []

    for sid, snap in snapshot.items():
        if sid not in current:
            continue
        cur = current[sid]

        review_fields_changed = (
            snap["passes"] != cur["passes"]
            or snap["reviewStatus"] != cur["reviewStatus"]
            or snap["reviewCount"] != cur["reviewCount"]
        )

        if review_fields_changed:
            changed_stories.append(sid)

    if len(changed_stories) > 1:
        return (
            f"Review-fix iteration made illegal transition: modified review fields "
            f"on multiple stories ({', '.join(changed_stories)}). "
            f"Review-fix may only modify one story per iteration."
        )

    if len(changed_stories) == 0:
        return None

    sid = changed_stories[0]
    snap = snapshot[sid]
    cur = current[sid]

    # passes must not change
    if snap["passes"] != cur["passes"]:
        return (
            f"Review-fix iterations cannot approve stories. Story {sid} "
            f"must go back to needs_review for re-review. Illegal transition: "
            f"passes {snap['passes']} -> {cur['passes']}."
        )

    # reviewStatus must go changes_requested -> needs_review
    if cur["reviewStatus"] != "needs_review":
        return (
            f"Review-fix iterations cannot approve stories. Story {sid} "
            f"must go back to needs_review for re-review. Illegal transition: "
            f"reviewStatus '{snap['reviewStatus']}' -> '{cur['reviewStatus']}'."
        )

    # reviewCount must not change
    if snap["reviewCount"] != cur["reviewCount"]:
        return (
            f"Review-fix iterations cannot approve stories. Story {sid} "
            f"had illegal transition: reviewCount {snap['reviewCount']} -> {cur['reviewCount']}."
        )

    return None


def check_uncommitted_changes() -> str | None:
    """Check 3: Uncommitted changes. Returns error message or None."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return None  # Can't check — don't block

        if result.stdout.strip():
            return (
                "You have uncommitted changes. Before stopping, you must:\n"
                "1. Update ralph/progress.txt with what was accomplished + learnings\n"
                "2. Consider if any lasting patterns belong in CLAUDE.md or .claude/rules/\n"
                "3. Commit ALL changes including progress.txt and tasks.json updates"
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None  # Can't check — don't block

    return None


def main():
    # Only activate when .ralph-active exists
    if not os.path.isfile(".ralph-active"):
        approve()
        return

    # Load .ralph-active
    ralph_active = load_json_file(".ralph-active") or {}

    # Find ralph directory
    ralph_dir = find_ralph_dir()
    if not ralph_dir:
        block("Cannot find ralph/ directory")
        return

    tasks_path = os.path.join(ralph_dir, "tasks.json")

    # Load tasks.json
    tasks = load_json_file(tasks_path)
    if tasks is None:
        block(f"Cannot read or parse {tasks_path}")
        return

    # Check 1: Schema validation
    error = check_schema(tasks, ralph_dir)
    if error:
        block(f"Task list validation failed: {error}")
        return

    # Check 2: Review integrity (state invariants)
    error = check_review_integrity(tasks, ralph_active)
    if error:
        block(f"Review integrity check failed: {error}")
        return

    # Check 2.5: Transition validation
    error = check_transitions(tasks, ralph_active)
    if error:
        block(f"Transition validation failed: {error}")
        return

    # Check 3: Uncommitted changes
    error = check_uncommitted_changes()
    if error:
        block(error)
        return

    approve()


if __name__ == "__main__":
    main()
