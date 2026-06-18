#!/usr/bin/env python3
"""drift_baseline.py — durable, single-machine drift baseline for verify-spec.

A *drift baseline* records the per-AC verdicts of the last clean verification of a
spec, so a later `verify-spec` run can re-check cheaply: detect which acceptance
criteria have **stale** evidence (their grounding source moved since) and which have
**drifted** (a previously-`confirmed` AC now `contradicted` — a regression).

It lives in `/tmp`, keyed on the spec's absolute path. It is the ONLY state
verify-spec keeps between runs, and it is deliberately single-machine and
ephemeral — `/tmp` survives across runs/sessions but the OS cleans it (≈3 days on
macOS; sooner on tmpfs Linux). It is NOT committed; verify-spec still writes
nothing into the repo. If the baseline is missing, the skill announces a full
verification (loud fallback) rather than silently skipping the regression check.

Path: ``/tmp/claude-verify-baseline-<abs-spec-path, non-alphanumerics → _>.json``

This module is the single source of truth for that path and its IO, used by both:
  - ``stop_verify_spec.py`` (the Stop hook): writes/refreshes the baseline when the
    verification gate passes, deterministically from the validated ledger.
  - the ``verify-spec`` skill (the model): at the START of a run, loads the baseline
    (``python3 drift_baseline.py load <spec>``) to drive drift mode.

CLI:
  ``drift_baseline.py path <spec>``           → prints the baseline file path.
  ``drift_baseline.py load <spec>``           → prints the baseline JSON, or nothing if none.
  ``drift_baseline.py write <spec> <ledger>`` → materialize the baseline from a saved
      verify-spec ledger file, emitting the IDENTICAL artifact the Stop hook's
      ``write_drift_baseline`` helper would (used by orchestrate-spec, which persists
      the workflow's returned ledger and can't rely on the verify hook firing).
"""

import json
import os
import re
import subprocess
import sys

BASELINE_PREFIX = "/tmp/claude-verify-baseline-"


def baseline_path(spec_path: str) -> str:
    """The /tmp path for a spec's drift baseline — keyed on its absolute path with
    every non-alphanumeric character replaced by `_`. Deterministic, so the hook
    (writer) and the skill (reader) always resolve the same file."""
    key = re.sub(r"[^A-Za-z0-9]", "_", os.path.abspath(spec_path))
    return f"{BASELINE_PREFIX}{key}.json"


def current_head_sha(cwd=None):
    """Resolved HEAD sha of the repo at `cwd` (or the process cwd), or None if this
    is not a git repo / git is unavailable. Never raises."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def criteria_from_claims(claims):
    """Project the ledger's grounded claims (confirmed/contradicted only) into the
    baseline's criteria shape. `unchecked`/`unverifiable` carry no verdict worth
    drifting against, so they are dropped."""
    out = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        if c.get("verdict") not in ("confirmed", "contradicted"):
            continue
        out.append(
            {
                "ac": str(c.get("claim", "")).strip(),
                "verdict": c.get("verdict"),
                "method": str(c.get("method", "")).strip(),
                "evidence": str(c.get("evidence", "")).strip(),
            }
        )
    return out


def write_baseline(spec_path, head_sha, criteria):
    """Write/refresh the baseline for `spec_path`. Best-effort: returns the path on
    success, or None if anything is missing or the write fails. Never raises."""
    if not spec_path or not head_sha or not criteria:
        return None
    payload = {
        "spec": os.path.abspath(spec_path),
        "verifiedAtSHA": head_sha,
        "criteria": criteria,
    }
    path = baseline_path(spec_path)
    try:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        return None
    return path


def load_baseline(spec_path):
    """The parsed baseline for `spec_path`, or None if absent/unreadable/malformed."""
    try:
        with open(baseline_path(spec_path)) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def write_from_ledger(spec_path, ledger_path):
    """Materialize the drift baseline from a saved verify-spec ledger file, reusing
    the SAME module functions the Stop hook's ``write_drift_baseline`` uses
    (``criteria_from_claims`` + ``current_head_sha`` → ``write_baseline``) so it emits
    the IDENTICAL artifact — no logic is duplicated. The ledger is the one
    orchestrate-spec persists from the build⇄verify workflow's returned result.
    Returns (code, detail):
      0 written · 1 nothing-to-write (no HEAD / no grounded criteria) · 3 ledger unreadable."""
    try:
        with open(ledger_path) as f:
            marker = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return 3, f"ledger not readable JSON: {e}"
    if not isinstance(marker, dict):
        return 3, "ledger is not a JSON object"
    criteria = criteria_from_claims(marker.get("claims") or [])
    head = current_head_sha()
    path = write_baseline(spec_path, head, criteria)
    if path:
        return 0, path
    return 1, "no baseline written (not a git repo, or no grounded confirmed/contradicted criteria)"


def main(argv):
    if len(argv) >= 3 and argv[1] == "path":
        print(baseline_path(argv[2]))
        return 0
    if len(argv) >= 3 and argv[1] == "load":
        b = load_baseline(argv[2])
        print(json.dumps(b, indent=2) if b is not None else "")
        return 0
    if len(argv) >= 4 and argv[1] == "write":
        code, detail = write_from_ledger(argv[2], argv[3])
        print(detail)
        return code
    sys.stderr.write("usage: drift_baseline.py {path <spec> | load <spec> | write <spec> <ledger>}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
