#!/usr/bin/env python3
"""Tear down the mock test board created by seed_test_board.py — from its manifest.

DEV-ONLY (gitignored). Reads `manifest.json`, then:
  1. hard-deletes every mock issue it created (`gh issue delete --yes`)
  2. deletes the test Project (deleteProjectV2)
  3. removes the manifest

It only ever touches what the manifest recorded, so the golden template (#7), the
repo's labels, and any pre-existing issue are never affected. Safe to re-run: a
missing issue / already-deleted project is treated as already-gone.

    python3 teardown_test_board.py            # delete everything in the manifest
    python3 teardown_test_board.py --dry-run  # list what would be deleted
    python3 teardown_test_board.py --yes      # skip the confirmation prompt
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "manifest.json"


def run(args, stdin=None, check=True):
    proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    if proc.returncode != 0 and check:
        raise RuntimeError(f"gh {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.returncode, proc.stdout, proc.stderr


def gql(query, **variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    code, out, err = run(args, check=False)
    return code, out, err


def teardown(dry_run: bool, assume_yes: bool):
    if not MANIFEST.exists():
        sys.exit("no manifest.json — nothing to tear down.")
    m = json.loads(MANIFEST.read_text())
    repo = m["repo"]
    project = m.get("project", {})
    issues = m.get("issues", [])
    # Only milestones this seed CREATED (created=True) get deleted; reused ones are left.
    milestones = [ms for ms in m.get("milestones", []) if ms.get("created")]

    print(f"Repo      : {repo}")
    print(f"Project   : #{project.get('number')}  {project.get('url')}")
    print(f"Issues    : {len(issues)}")
    for it in issues:
        print(f"   - #{it['number']}  {it.get('title', '')}")
    print(f"Milestones: {len(milestones)}")
    for ms in milestones:
        print(f"   - #{ms['number']}  {ms.get('title', '')}")

    if dry_run:
        print("\n--dry-run: nothing deleted.")
        return

    if not assume_yes:
        resp = input(f"\nDelete the project, {len(issues)} issues and {len(milestones)} milestones? "
                     "[y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("aborted.")
            return

    # 1. issues (hard delete)
    deleted = 0
    for it in issues:
        code, _, err = run(["issue", "delete", str(it["number"]), "--repo", repo, "--yes"], check=False)
        if code == 0:
            deleted += 1
        elif "not found" in (err or "").lower() or "could not resolve" in (err or "").lower():
            print(f"   #{it['number']} already gone")
        else:
            print(f"   ! #{it['number']} delete failed: {err.strip()}")
    print(f"[issues] deleted {deleted}/{len(issues)}")

    # 2. project
    if project.get("id"):
        code, _, err = gql(
            "mutation($p:ID!){deleteProjectV2(input:{projectId:$p}){projectV2{id}}}",
            p=project["id"])
        if code == 0:
            print(f"[board] deleted #{project.get('number')}")
        else:
            print(f"[board] delete failed (may already be gone): {err.strip()}")

    # 3. milestones (only the ones we created)
    if milestones:
        owner, name = repo.split("/")
        ms_deleted = 0
        for ms in milestones:
            code, _, err = run(["api", "-X", "DELETE",
                                f"/repos/{owner}/{name}/milestones/{ms['number']}"], check=False)
            if code == 0:
                ms_deleted += 1
            elif "not found" in (err or "").lower():
                print(f"   milestone #{ms['number']} already gone")
            else:
                print(f"   ! milestone #{ms['number']} delete failed: {err.strip()}")
        print(f"[milestones] deleted {ms_deleted}/{len(milestones)}")

    # 4. manifest
    MANIFEST.unlink()
    print(f"[manifest] removed {MANIFEST.name}")
    print("\nTeardown complete.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)
    teardown(args.dry_run, args.yes)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)
