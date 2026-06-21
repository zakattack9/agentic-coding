#!/usr/bin/env python3
"""Unit tests for codex_bridge.py — the fail-open Codex wrapper.

Covered:
  * the exit-code taxonomy (0 / 10 / 11 / 12) driven through an injected fake Codex;
  * verdict extraction taking the LAST agent_message from the JSONL stream;
  * fail-open paths — Codex absent, timeout, and a malformed reply.

Run: python3 -m pytest tests/test_codex_bridge.py   (or)   python3 tests/test_codex_bridge.py
No real Codex CLI is ever spawned: the subprocess seam is replaced with a fake.
"""

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codex_bridge as cb  # noqa: E402


# ---- helpers -----------------------------------------------------------------------

def _jsonl(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"

def _agent_msg(text):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}

VALID_JUDGE_VERIFY = {"verdict": "complete", "missed": [], "weakEvidence": []}

def _fake_invoke(stdout="", last_message="", timed_out=False, failed=False, returncode=0):
    """Build an `invoke` stand-in that always returns the given Invocation."""
    def _invoke(prompt, model, effort, cd, schema_file, timeout):
        return cb.Invocation(
            stdout=stdout, last_message=last_message,
            timed_out=timed_out, failed=failed, returncode=returncode,
        )
    return _invoke

def _run(kind, invoke, environ=None):
    """Call cb.run with a fake invoke, forcing availability+auth on, capturing stdout."""
    environ = environ or {}
    out = io.StringIO()
    err = io.StringIO()
    orig_avail, orig_auth = cb.codex_available, cb.codex_authenticated
    cb.codex_available = lambda: True
    cb.codex_authenticated = lambda env: True
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cb.run(kind, "PROMPT", None, None, "gpt-5.5", "xhigh", 180,
                          environ, invoke=invoke)
    finally:
        cb.codex_available, cb.codex_authenticated = orig_avail, orig_auth
    return code, out.getvalue(), err.getvalue()


# ---- extraction: take the LAST agent_message ---------------------------------------

def test_extract_takes_last_agent_message():
    # An earlier agent_message leaks junk (the known gpt-5.x quirk); the LAST one is the
    # real verdict. Extraction must pick the last.
    stream = _jsonl(
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        _agent_msg('{"verdict": "gaps", "missed": ["leaked-schema-noise"]}'),
        _agent_msg(json.dumps(VALID_JUDGE_VERIFY)),
        {"type": "turn.completed"},
    )
    data = cb.extract_verdict(stream, last_message_text="")
    assert data == VALID_JUDGE_VERIFY, data

def test_parse_stream_detects_failure_event():
    stream = _jsonl({"type": "turn.started"}, {"type": "turn.failed"})
    last, failed = cb.parse_stream(stream)
    assert failed is True and last is None

def test_extract_falls_back_to_last_message_file():
    # Stream carries no agent_message; the --output-last-message file does.
    stream = _jsonl({"type": "turn.started"}, {"type": "turn.completed"})
    data = cb.extract_verdict(stream, last_message_text=json.dumps(VALID_JUDGE_VERIFY))
    assert data == VALID_JUDGE_VERIFY

def test_extract_strips_json_fence_from_stdout():
    fenced = "```json\n" + json.dumps(VALID_JUDGE_VERIFY) + "\n```"
    data = cb.extract_verdict(fenced, last_message_text="")
    assert data == VALID_JUDGE_VERIFY

def test_extract_returns_none_on_garbage():
    assert cb.extract_verdict("not json at all", last_message_text="") is None


# ---- exit taxonomy -----------------------------------------------------------------

def test_exit_0_on_valid_verdict():
    stream = _jsonl(_agent_msg(json.dumps(VALID_JUDGE_VERIFY)), {"type": "turn.completed"})
    code, out, _ = _run("judge-verify", _fake_invoke(stdout=stream))
    assert code == cb.OK
    assert json.loads(out) == VALID_JUDGE_VERIFY

def test_exit_10_when_codex_absent():
    # Don't force availability on here — simulate absence directly.
    orig = cb.codex_available
    cb.codex_available = lambda: False
    try:
        out = io.StringIO(); err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cb.run("judge-verify", "P", None, None, "m", "xhigh", 180, {},
                          invoke=_fake_invoke(stdout="x"))
    finally:
        cb.codex_available = orig
    log = err.getvalue()
    assert code == cb.SKIP
    assert log.strip().count("\n") == 0 and "codex_bridge:" in log  # exactly one log line

def test_exit_10_when_env_disables_all():
    code, _, err = _run("judge-verify", _fake_invoke(stdout="x"), environ={"SPEC_OPS_CODEX": "0"})
    assert code == cb.SKIP

def test_exit_10_when_write_toggle_disables_only_write():
    env = {"SPEC_OPS_CODEX_WRITE": "0"}
    # write-requirements is skipped...
    code_w, _, _ = _run("write-requirements", _fake_invoke(stdout="x"), environ=env)
    assert code_w == cb.SKIP
    # ...but the verify judge is unaffected by the write toggle.
    stream = _jsonl(_agent_msg(json.dumps(VALID_JUDGE_VERIFY)))
    code_v, _, _ = _run("judge-verify", _fake_invoke(stdout=stream), environ=env)
    assert code_v == cb.OK

def test_exit_11_on_timeout():
    code, _, err = _run("judge-verify", _fake_invoke(timed_out=True))
    assert code == cb.ERROR
    assert "timed out" in err

def test_exit_11_on_turn_failed():
    code, _, _ = _run("judge-verify", _fake_invoke(failed=True))
    assert code == cb.ERROR

def test_exit_12_on_malformed_after_retry():
    # Always returns unparseable output → one re-dispatch → still bad → 12.
    code, out, err = _run("judge-verify", _fake_invoke(stdout="totally not json"))
    assert code == cb.UNPARSEABLE
    assert out == ""

def test_exit_12_on_valid_json_wrong_shape():
    # Parses as JSON but violates the contract (missing required arrays) → 12.
    bad = _jsonl(_agent_msg('{"verdict": "complete"}'))
    code, _, _ = _run("judge-verify", _fake_invoke(stdout=bad))
    assert code == cb.UNPARSEABLE

def test_retry_recovers_when_second_attempt_is_valid():
    # First attempt malformed, second attempt valid → exit 0 (the re-dispatch worked).
    calls = {"n": 0}
    valid = _jsonl(_agent_msg(json.dumps(VALID_JUDGE_VERIFY)))
    def _invoke(prompt, model, effort, cd, schema_file, timeout):
        calls["n"] += 1
        return cb.Invocation(stdout="garbage" if calls["n"] == 1 else valid)
    code, out, _ = _run("judge-verify", _invoke)
    assert code == cb.OK and calls["n"] == 2


# ---- read-only / no-escalation invariants ------------------------------------------

def test_argv_is_read_only_with_no_escalation():
    argv = cb.build_argv("gpt-5.5", "xhigh", "/repo", "/s.json", "/tmp/last.txt")
    assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
    joined = " ".join(argv)
    for forbidden in (
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--add-dir",
        "workspace-write",
        "danger-full-access",
    ):
        assert forbidden not in joined, f"escalating flag leaked: {forbidden}"

def test_model_resolution_prefers_explicit_then_default(tmp_path=None):
    # Explicit arg wins.
    assert cb.resolve_model("gpt-5.4", {}) == "gpt-5.4"
    # No arg + no config → documented default constant.
    assert cb.resolve_model(None, {"CODEX_HOME": "/nonexistent-dir-xyz"}) == cb.DEFAULT_MODEL


# ---- runner ------------------------------------------------------------------------

def _main():
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in funcs:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  ERR  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(funcs) - failures}/{len(funcs)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
