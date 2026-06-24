#!/usr/bin/env python3
"""Offline unit tests for codex_bridge.py — the fail-open Codex wrapper.

No real `codex` CLI is ever spawned: the subprocess seam is replaced with a fake, the
availability guards are stubbed, and model discovery is fed a fixture. Covered:

  * read-only argv pins `--sandbox read-only` and builds NO escalation flag;
  * the write argv uses `--sandbox workspace-write` via the separate, mode-derived path,
    unreachable from the read-only entrypoints;
  * argv is always a list and every caller value (prompt / model / effort) is injection-safe
    for leading dashes (prompt on stdin; model/effort `=`-bound);
  * the exit taxonomy 0/10/11/12, including empty-output -> 12 and every non-zero fail-open;
  * `--probe` line parsing (presence + usable auth);
  * web-search-on and grounding-on for BOTH the read-only and the write argv;
  * the default model = discovered latest, effort = xhigh, and the `--model`/`--effort`
    translation to Codex's real flags;
  * on success stdout carries ONLY the raw payload while the session id + diagnostics go to
    stderr;
  * every invocation passes an explicit `-C <repo>`, and the review argv places the global
    flags before the `review` subcommand and never combines a scope flag with a prompt;
  * two invocations produce distinct temp paths (no collision);
  * fail-open paths emit one clear diagnostic with the right non-zero code.

Run: python3 -m pytest tests/test_codex_bridge.py   (or)   python3 tests/test_codex_bridge.py
"""

import io
import json
import os
import sys
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import codex_bridge as cb  # noqa: E402


# ---- fixtures & helpers ----------------------------------------------------------------

# The real `codex debug models` shape (codex-cli 0.142.0): gpt-5.5 is the latest selectable
# model (visibility list, no upgrade, lowest priority); gpt-5.4 is superseded; codex-auto-review
# is hidden.
DEBUG_MODELS_JSON = json.dumps({"models": [
    {"slug": "gpt-5.5", "priority": 9, "visibility": "list", "upgrade": None,
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"},
                                    {"effort": "high"}, {"effort": "xhigh"}]},
    {"slug": "gpt-5.4", "priority": 16, "visibility": "list",
     "upgrade": {"model": "gpt-5.5"},
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"},
                                    {"effort": "high"}, {"effort": "xhigh"}]},
    {"slug": "gpt-5.4-mini", "priority": 23, "visibility": "list", "upgrade": None,
     "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}]},
    {"slug": "codex-auto-review", "priority": 43, "visibility": "hide", "upgrade": None,
     "supported_reasoning_levels": [{"effort": "low"}]},
]})

ESCALATION_TOKENS = ("--dangerously-bypass-approvals-and-sandbox", "danger-full-access",
                     "--add-dir", "--ignore-user-config", "--oss", "--ephemeral")


def _jsonl(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"

def _agent_msg(text):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}

def _thread_started(tid):
    return {"type": "thread.started", "thread_id": tid}


@contextmanager
def _saved(obj, name):
    """Temporarily replace an attribute, restoring it on exit (works under pytest or bare)."""
    original = getattr(obj, name)
    try:
        yield lambda value: setattr(obj, name, value)
    finally:
        setattr(obj, name, original)


@contextmanager
def _available():
    """Make the availability guards pass without touching PATH, auth, or config."""
    with _saved(cb, "codex_available") as a, _saved(cb, "codex_authenticated") as b, \
         _saved(cb, "non_openai_provider") as c:
        a(lambda: True)
        b(lambda environ: True)
        c(lambda environ: None)
        yield


def _fake_invoke(stdout="", stderr="", last_message="", timed_out=False, returncode=0):
    """Build an `invoke` stand-in returning a fixed Invocation, for the run() taxonomy."""
    def _invoke(mode, prompt, model, effort, cd, timeout):
        return cb.Invocation(stdout=stdout, stderr=stderr, last_message=last_message,
                             timed_out=timed_out, returncode=returncode)
    return _invoke


def _run(mode, invoke, prompt="do the thing", cd="/repo", model=None, effort="xhigh",
         environ=None):
    """Drive run() under stubbed availability, capturing (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with _available(), redirect_stdout(out), redirect_stderr(err):
        code = cb.run(mode, prompt, cd, model, effort, 5, environ or {}, invoke=invoke)
    return code, out.getvalue(), err.getvalue()


class _FakePopen:
    """A stand-in for subprocess.Popen that records argv/stdin and returns canned output."""
    instances = []

    def __init__(self, argv, stdin=None, stdout=None, stderr=None, text=None,
                 start_new_session=None):
        self.argv = argv
        self.pid = 4321
        self.returncode = _FakePopen.returncode
        _FakePopen.instances.append(self)

    def communicate(self, input=None, timeout=None):
        self.input = input
        if _FakePopen.timed_out:
            raise cb.subprocess.TimeoutExpired(self.argv, timeout)
        return (_FakePopen.stdout, _FakePopen.stderr)

    def kill(self):
        self.killed = True


@contextmanager
def _fake_popen(stdout="", stderr="", returncode=0, timed_out=False):
    _FakePopen.instances = []
    _FakePopen.stdout, _FakePopen.stderr = stdout, stderr
    _FakePopen.returncode, _FakePopen.timed_out = returncode, timed_out
    with _saved(cb.subprocess, "Popen") as setp:
        setp(_FakePopen)
        yield _FakePopen


# ---- argv: sandbox pin, no escalation, web-search, grounding, explicit -C ----

def test_readonly_argv_pins_read_only_and_no_escalation():
    for mode in (cb.MODE_EXEC, cb.MODE_REVIEW):
        argv = cb.build_argv(mode, "gpt-5.5", "xhigh", "/repo", "/t/last.txt")
        assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
        assert "workspace-write" not in argv
        for tok in ESCALATION_TOKENS:
            assert tok not in argv, f"{mode} argv leaked {tok}"


def test_write_argv_workspace_write_and_separate_path():
    argv = cb.build_argv(cb.MODE_WRITE, "gpt-5.5", "xhigh", "/repo", "/t/last.txt")
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    # sandbox is a pure function of mode: read-only modes can never yield workspace-write
    assert cb.sandbox_for_mode(cb.MODE_EXEC) == "read-only"
    assert cb.sandbox_for_mode(cb.MODE_REVIEW) == "read-only"
    assert cb.sandbox_for_mode(cb.MODE_WRITE) == "workspace-write"


def test_web_search_and_grounding_on_every_mode():
    for mode in (cb.MODE_EXEC, cb.MODE_REVIEW, cb.MODE_WRITE):
        argv = cb.build_argv(mode, "gpt-5.5", "xhigh", "/repo", "/t/last.txt")
        assert "tools.web_search=true" in argv
        assert "web_search_mode=live" not in argv  # the wrong key for this CLI version
        grounding = [t for t in argv if t.startswith("project_doc_max_bytes=")]
        assert grounding and grounding[0] != "project_doc_max_bytes=0"
        assert "--ignore-user-config" not in argv


def test_every_invocation_passes_explicit_C():
    for mode in (cb.MODE_EXEC, cb.MODE_REVIEW, cb.MODE_WRITE):
        argv = cb.build_argv(mode, "gpt-5.5", "xhigh", "/repo", "/t/last.txt")
        assert "-C" in argv and argv[argv.index("-C") + 1] == "/repo"


def test_review_argv_globals_before_subcommand_no_scope_flag():
    argv = cb.build_argv(cb.MODE_REVIEW, "gpt-5.5", "xhigh", "/repo", "/t/last.txt")
    assert argv[-2:] == ["review", "-"]  # prompt arrives on stdin via `review -`
    i = argv.index("review")
    # the global flags belong to `codex exec`, so they precede `review`
    assert "--sandbox" in argv[:i] and "-C" in argv[:i] and "--json" in argv[:i]
    # a scope flag is never combined with the prompt
    for scope in ("--uncommitted", "--base", "--commit"):
        assert scope not in argv


# ---- argv: injection-safety for adversarial caller values ----

def test_argv_is_a_list_and_caller_values_are_injection_safe():
    evil = "--dangerously-bypass-approvals-and-sandbox"
    for mode in (cb.MODE_EXEC, cb.MODE_REVIEW, cb.MODE_WRITE):
        argv = cb.build_argv(mode, evil, "--oss", "/repo", "/t/last.txt")
        assert isinstance(argv, list)
        # a leading-dash model/effort stays BOUND to its flag, never a standalone token
        assert evil not in argv and "--oss" not in argv
        assert f"--model={evil}" in argv
        assert "model_reasoning_effort=--oss" in argv
        for tok in ESCALATION_TOKENS:
            assert tok not in argv
    # the prompt is never an argv element at all — it goes on stdin
    argv = cb.build_argv(cb.MODE_EXEC, "gpt-5.5", "xhigh", "/repo", "/t/last.txt")
    assert "do the thing" not in argv


# ---- model discovery + default effort + model/effort flag translation ----

def test_parse_models_picks_latest_and_lists_catalog():
    latest, catalog = cb.parse_models(DEBUG_MODELS_JSON)
    assert latest == "gpt-5.5"  # lowest priority among visibility:list with no upgrade
    slugs = [s for s, _ in catalog]
    assert slugs == ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]  # hidden model excluded
    assert ("codex-auto-review" not in slugs)
    efforts = dict(catalog)["gpt-5.5"]
    assert efforts == ["low", "medium", "high", "xhigh"]


def test_resolve_model_prefers_arg_then_discovered_then_fallback():
    with _saved(cb, "run_debug_models") as setd:
        setd(lambda timeout=20: DEBUG_MODELS_JSON)
        assert cb.resolve_model("gpt-x", {}) == "gpt-x"       # explicit arg wins
        assert cb.resolve_model(None, {}) == "gpt-5.5"        # else discovered latest
        setd(lambda timeout=20: None)                          # discovery broken
        assert cb.resolve_model(None, {}) == cb.FALLBACK_MODEL


def test_default_effort_is_xhigh():
    assert cb.DEFAULT_EFFORT == "xhigh"


def test_effort_and_model_translation():
    argv = cb.build_argv(cb.MODE_EXEC, "gpt-5.5", "high", "/repo", "/t/last.txt")
    assert "--model=gpt-5.5" in argv                                   # --model -> codex model flag
    assert "-c" in argv and "model_reasoning_effort=high" in argv      # --effort -> -c override


# ---- exit taxonomy + fail-open + stdout/stderr split ----

def test_exit_zero_valid_payload_on_stdout_only():
    stream = _jsonl(_thread_started("th_1"), _agent_msg("the answer"))
    code, out, err = _run(cb.MODE_EXEC, _fake_invoke(stdout=stream, last_message="the answer"))
    assert code == cb.OK
    assert out == "the answer\n"                # payload alone on stdout
    assert "SESSION_ID: th_1" in err            # session id on stderr
    assert "th_1" not in out and "the answer" not in err  # streams never cross


def test_empty_output_maps_to_unrecoverable_not_blank_success():
    # codex exits 0 but recovered nothing through any channel -> 12, never a blank exit 0
    stream = _jsonl(_thread_started("th_2"))
    code, out, err = _run(cb.MODE_EXEC, _fake_invoke(stdout=stream, last_message="   "))
    assert code == cb.UNRECOVERABLE
    assert out == ""
    assert err.count("codex_bridge:") == 1


def test_timeout_and_failure_and_nonzero_map_to_error():
    for inv in (_fake_invoke(timed_out=True),
                _fake_invoke(stdout=_jsonl({"type": "turn.failed"}), last_message="x"),
                _fake_invoke(returncode=2, stderr="boom", last_message="partial")):
        code, out, err = _run(cb.MODE_EXEC, inv)
        assert code == cb.ERROR
        assert out == ""                        # partial/streamed content never surfaced
        assert err.count("codex_bridge:") == 1  # exactly one diagnostic


def test_disabled_by_env_skips_with_exit_10():
    code, out, err = _run(cb.MODE_EXEC, _fake_invoke(last_message="x"),
                          environ={"CODEX_PLUGIN": "0"})
    assert code == cb.SKIP and out == "" and err.count("codex_bridge:") == 1


def test_every_nonzero_exit_emits_one_diagnostic():
    cases = {
        cb.SKIP: ({"CODEX_PLUGIN": "off"}, _fake_invoke(last_message="x")),
        cb.ERROR: ({}, _fake_invoke(timed_out=True)),
        cb.UNRECOVERABLE: ({}, _fake_invoke(stdout="", last_message="")),
    }
    for expected, (env, inv) in cases.items():
        code, out, err = _run(cb.MODE_EXEC, inv, environ=env)
        assert code == expected
        assert out == "" and err.strip().count("\n") == 0 and err.startswith("codex_bridge:")


# ---- probe: presence + usable auth, one-line output ----

def test_probe_yes_when_available_authed_openai():
    with _available():
        line = cb.probe_line({})
    assert line.startswith("CODEX: YES")


def test_probe_no_reasons():
    with _saved(cb, "codex_available") as a, _saved(cb, "codex_authenticated") as b, \
         _saved(cb, "non_openai_provider") as c:
        a(lambda: True); b(lambda e: True); c(lambda e: None)
        assert cb.probe_line({"CODEX_PLUGIN": "0"}).startswith("CODEX: NO — disabled")
        a(lambda: False)
        assert "not on PATH" in cb.probe_line({})
        a(lambda: True); b(lambda e: False)
        assert "not authenticated" in cb.probe_line({})
        b(lambda e: True); c(lambda e: "azure")
        assert "not the OpenAI provider" in cb.probe_line({})


def test_probe_via_main_prints_one_line_exit_0_no_turn():
    with _available():
        out = io.StringIO()
        with redirect_stdout(out):
            code = cb.main(["--probe"])
    assert code == 0
    assert out.getvalue().count("\n") == 1 and out.getvalue().startswith("CODEX:")


# ---- answer-recovery precedence + thread_id ----

def test_recover_text_precedence_file_then_stream_then_fenced():
    stream = _jsonl(_agent_msg("from-stream"))
    assert cb.recover_text("from-file", stream) == "from-file"          # file wins
    assert cb.recover_text("   ", stream) == "from-stream"              # then stream
    fenced = "noise\n```\nfrom-fence\n```\n"
    assert cb.recover_text("", fenced) == "from-fence"                 # then fenced stdout
    assert cb.recover_text("", _jsonl({"type": "turn.started"})) is None  # nothing recoverable


def test_thread_id_only_from_thread_started():
    _msg, tid, failed = cb.parse_stream(_jsonl(_thread_started("th_9"), _agent_msg("a")))
    assert tid == "th_9" and not failed
    _msg, tid, failed = cb.parse_stream(_jsonl({"type": "error"}))
    assert tid is None and failed


def test_session_id_unavailable_note_when_missing():
    # success payload but no thread.started -> explicit unavailable note, never invented
    code, out, err = _run(cb.MODE_EXEC, _fake_invoke(stdout=_jsonl(_agent_msg("a")),
                                                     last_message="a"))
    assert code == cb.OK and "SESSION_ID: unavailable" in err


# ---- temp-path uniqueness + stdin wiring (real invoke_codex via a fake Popen) ----

def test_two_invocations_use_distinct_temp_paths():
    paths = []
    with _fake_popen(stdout="", stderr=""):
        for _ in range(2):
            cb.invoke_codex(cb.MODE_EXEC, "p", "gpt-5.5", "xhigh", "/repo", 5)
        for inst in _FakePopen.instances:
            paths.append(inst.argv[inst.argv.index("-o") + 1])
    assert len(paths) == 2 and paths[0] != paths[1]
    # each temp file sits under a unique 0700 codex_bridge_ dir, removed after the run
    for p in paths:
        assert "codex_bridge_" in p and not Path(p).exists()


def test_invoke_feeds_prompt_on_stdin_for_every_mode():
    for mode in (cb.MODE_EXEC, cb.MODE_REVIEW, cb.MODE_WRITE):
        with _fake_popen(stdout=_jsonl(_agent_msg("a")), stderr=""):
            cb.invoke_codex(mode, "PROMPT-TEXT", "gpt-5.5", "xhigh", "/repo", 5)
            inst = _FakePopen.instances[-1]
            assert inst.input == "PROMPT-TEXT"            # prompt fed on stdin, not argv
            assert "PROMPT-TEXT" not in inst.argv


def test_timeout_kills_whole_process_group_and_reports_timed_out():
    killed = []
    # patch the OS calls so the kill targets the fake's group, never a real process
    with _fake_popen(timed_out=True), \
         _saved(cb.os, "getpgid") as setg, _saved(cb.os, "killpg") as setk:
        setg(lambda pid: ("pgid", pid))
        setk(lambda pgid, sig: killed.append((pgid, sig)))
        result = cb.invoke_codex(cb.MODE_EXEC, "p", "gpt-5.5", "xhigh", "/repo", 5)
    assert result.timed_out is True
    # the whole process GROUP (getpgid of the child) was signalled with SIGKILL
    assert killed and killed[0][0] == ("pgid", 4321) and killed[0][1] == cb.signal.SIGKILL


# ---- env namespace, off-spellings, secret no-leak, timeout bounds ----

def test_env_off_spellings_and_namespace():
    for val in ("0", "false", "no", "off", "OFF", "False"):
        assert cb._is_off(val)
    for val in ("1", "true", "yes", "on", ""):
        assert not cb._is_off(val)
    assert cb.disabled_by_env({"CODEX_PLUGIN": "no"})
    assert not cb.disabled_by_env({"CODEX_PLUGIN": "1"})


def test_diagnostics_never_echo_secrets():
    # a token in the env must never appear in the one diagnostic line
    env = {"CODEX_PLUGIN": "0", "OPENAI_API_KEY": "sk-SECRET-TOKEN"}
    code, out, err = _run(cb.MODE_EXEC, _fake_invoke(last_message="x"), environ=env)
    assert "sk-SECRET-TOKEN" not in err and "sk-SECRET-TOKEN" not in out


def test_default_timeout_in_bounds():
    assert 30 <= cb.DEFAULT_TIMEOUT < 1200            # >=30s, under the 20-min Bash cap
    assert cb.resolve_timeout({"CODEX_PLUGIN_TIMEOUT": "55"}) == 55
    assert cb.resolve_timeout({"CODEX_PLUGIN_TIMEOUT": "abc"}) == cb.DEFAULT_TIMEOUT
    assert cb.resolve_timeout({}, override=99) == 99


# ---- bare runner (also runs under pytest) ----------------------------------------------

if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"FAIL  {name}: {e!r}")
    print(f"\n{'PASS' if not failures else 'FAIL'} — {failures} failure(s)")
    sys.exit(1 if failures else 0)
