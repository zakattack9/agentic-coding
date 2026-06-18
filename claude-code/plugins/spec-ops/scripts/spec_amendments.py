#!/usr/bin/env python3
"""spec_amendments.py — the verify→refine spec-amendment handoff (single-machine).

When verify-spec's backward sweep finds delivered behavior that maps to NO
acceptance criterion, it proposes an AC + triage per finding. Those proposals are
a *spec* change (a missed requirement) owned by refine-spec — but verify-spec is
read-only and never touches the spec. This module carries the proposals across:
verify-spec's Stop hook writes them to /tmp on a clean pass; refine-spec loads and
ingests them at the start of its next run (the human confirms which to add), so a
verify finding flows into a spec amendment without manual re-keying.

Single-machine + ephemeral, keyed on the spec's absolute path (impl / verify /
refine run on the same machine). NOT committed; verify-spec still writes only /tmp.

Path: /tmp/claude-spec-amendments-<abs-spec-path, non-alphanumerics → _>.json

This module is the single source of truth for that path and IO, used by both:
  - stop_verify_spec.py (the Stop hook): writes/clears the handoff from the ledger.
  - the refine-spec skill (the model): loads (`load`) it at run start, then clears
    (`clear`) once the proposals are dispositioned.

CLI:
  spec_amendments.py load <spec>   → prints the amendments JSON, or nothing if none
  spec_amendments.py clear <spec>  → removes the amendments file (idempotent)
"""

import json
import os
import re
import sys

PREFIX = "/tmp/claude-spec-amendments-"


def amendments_path(spec_path):
    """The /tmp handoff file for a spec — keyed on its realpath (symlink-resolved)
    so the verify hook (writer) and the refine skill (reader) resolve the same file."""
    key = re.sub(r"[^A-Za-z0-9]", "_", os.path.realpath(spec_path))
    return f"{PREFIX}{key}.json"


def clear_amendments(spec_path):
    """Remove the handoff file for `spec_path` (idempotent)."""
    try:
        os.remove(amendments_path(spec_path))
    except OSError:
        pass


def write_amendments(spec_path, findings):
    """Write proposed amendments for `spec_path`. `findings` = list of
    {proposedAC, disposition, evidence, hunk}. Empty/falsey findings CLEARS any
    prior file (the backward sweep came back clean). Returns the path, or None."""
    if not findings:
        clear_amendments(spec_path)
        return None
    payload = {"spec": os.path.realpath(spec_path), "findings": findings}
    path = amendments_path(spec_path)
    try:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        return None
    return path


def load_amendments(spec_path):
    """The parsed handoff for `spec_path`, or None if absent/unreadable/malformed."""
    try:
        with open(amendments_path(spec_path)) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def findings_from_ledger(marker):
    """Project a verify-spec ledger's backwardSweep into amendment findings — every
    finding that carries a `proposedAC`. `disposition` is preserved so refine can
    present `intended`/`unsure` as adds and flag `unintended` as scope-creep."""
    sweep = marker.get("backwardSweep") if isinstance(marker, dict) else None
    if not isinstance(sweep, dict):
        return []
    out = []
    for f in sweep.get("findings") or []:
        if not isinstance(f, dict):
            continue
        proposed = str(f.get("proposedAC", "")).strip()
        if not proposed:
            continue
        out.append(
            {
                "proposedAC": proposed,
                "disposition": str(f.get("disposition", "")).strip(),
                "evidence": str(f.get("evidence", "")).strip(),
                "hunk": str(f.get("hunk", "")).strip(),
            }
        )
    return out


def main(argv):
    if len(argv) >= 3 and argv[1] == "load":
        a = load_amendments(argv[2])
        print(json.dumps(a, indent=2) if a else "")
        return 0
    if len(argv) >= 3 and argv[1] == "clear":
        clear_amendments(argv[2])
        print("cleared")
        return 0
    sys.stderr.write("usage: spec_amendments.py {load <path> | clear <path>}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
