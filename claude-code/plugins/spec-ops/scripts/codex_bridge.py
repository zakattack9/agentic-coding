#!/usr/bin/env python3
"""codex_bridge.py — the single, deterministic wrapper that lets spec-ops borrow a
second, different-provider model (OpenAI Codex CLI) as an adversarial reviewer.

This is the ONLY component that ever invokes `codex`. Every skill, agent, and hook
that wants a Codex opinion shells out to THIS script and branches on its exit code —
so all the provider-specific facts, flags, and failure modes live in one place and a
caller never has to know how Codex is spawned.

Design contract (why it is shaped this way):

  * Fail-open, always. Codex is a graceful enhancement, never a dependency. Absent
    CLI, no auth, a timeout, an error, or an unparseable reply ALL resolve to a
    non-zero exit that means "proceed without me" — the caller runs exactly as it
    would have with no second model. The bridge can only ever ADD findings to a
    review; it can never block or weaken a gate.

  * Read-only by construction. A review/judge must not be able to touch the repo, so
    every invocation pins `--sandbox read-only` and NEVER passes an escalating flag
    (`--dangerously-bypass-*`, a writable `--add-dir`, or a non-read-only sandbox).
    `codex exec` is inherently non-interactive — it has no approval prompt to bypass —
    so the read-only sandbox is the whole guarantee. The absence of any escalation is
    structural: this file simply never builds those args.

  * Validated output is the real gate. `--output-schema` is supplied to SHAPE the
    reply, but it is known to silently degrade (dropped on some model slugs, leaked
    into intermediate messages). So the bridge extracts the verdict through three
    fallback channels, then validates it against the named contract with
    validate_return.py — and re-dispatches once with the schema appended before
    giving up. The schema is best-effort; validate_return.py is authoritative.

  * Writes nothing the caller owns. The bridge prints validated JSON to stdout and
    nothing else; it never writes a spec-ops ledger or any repo file. Its only scratch
    file is a private temp for Codex's last-message channel, cleaned up on exit.

Usage:
    codex_bridge.py --kind <judge-verify|judge-refine|write-requirements> \
                    --prompt-file <f> [--schema-file <f>] [--cd <repo>] \
                    [--model <m>] [--effort xhigh|medium] [--timeout 180]
    codex_bridge.py --probe --kind <kind>    # one-line availability verdict, no Codex call

The `--probe` mode prints a single deterministic line — `CODEX: YES …` or
`CODEX: NO — <reason>` — and exits 0. It is meant for a skill's `!`-injection at
load: the caller skips its cross-model section on NO and dispatches the judge on
YES, instead of constructing a prompt only to learn Codex is absent.

Exit codes (the caller branches on the code alone):
    0   valid, contract-checked JSON on stdout — fold it into the ledger / disposition
    10  skipped — Codex not installed, not authenticated, or switched off by env
    11  Codex error / timeout / turn-failed
    12  reply unparseable after one re-dispatch
Every non-zero code is fail-open: the caller proceeds with its own (Claude) review only.

Env switches:
    SPEC_OPS_CODEX=0        disable ALL Codex cross-model checks (any kind → exit 10)
    SPEC_OPS_CODEX_WRITE=0  disable ONLY the write-requirements reviewer, independently
                            of the verify/refine judges (kind write-requirements → 10)
    OPENAI_API_KEY / CODEX_API_KEY   counted as usable auth (in addition to a logged-in CLI)
    CODEX_HOME             respected when locating the user's config.toml
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover — older interpreters fall back to default model
    tomllib = None

# Reuse the contract definitions — single source of the return shapes (also the manual CLI).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_return  # noqa: E402

# Exit taxonomy — named so callers and tests never hard-code the integers.
OK = 0
SKIP = 10
ERROR = 11
UNPARSEABLE = 12

# Default Codex model, used only when neither an explicit arg nor the user's config
# names one. Version-sensitive: revisit when `codex --version` advances — retired
# slugs (gpt-5, gpt-5-codex) are blocked for new requests and `latest` is not valid.
# Prefer a plain gpt-5.x (non-`-codex`) slug, since `--output-schema` is dropped on
# `-codex` slugs. Keep this in sync with references/codex-bridge.md (model resolution).
DEFAULT_MODEL = "gpt-5.5"

# Per-call ceiling so a hung turn can never stall the loop the caller is waiting on.
DEFAULT_TIMEOUT = 180

VALID_EFFORTS = ("xhigh", "medium", "high", "low", "minimal")


def _is_off(val):
    """An env toggle reads as 'off' for the usual falsey spellings."""
    return isinstance(val, str) and val.strip().lower() in ("0", "false", "no", "off")


def disabled_by_env(kind, environ):
    """True when an env switch turns this call off (→ skip, byte-identical to no-Codex)."""
    if _is_off(environ.get("SPEC_OPS_CODEX")):
        return True
    if kind == "write-requirements" and _is_off(environ.get("SPEC_OPS_CODEX_WRITE")):
        return True
    return False


def codex_available():
    """Codex CLI on PATH?"""
    return shutil.which("codex") is not None


def codex_authenticated(environ):
    """Usable auth WITHOUT any interactive login or network call: an API key in the
    env, or a CLI that already reports logged-in. We probe `codex login status` (a
    local check) but NEVER run `codex login` — an absent auth is a skip, not a prompt."""
    if environ.get("OPENAI_API_KEY") or environ.get("CODEX_API_KEY"):
        return True
    try:
        res = subprocess.run(
            ["codex", "login", "status"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def probe_line(kind, environ):
    """One-line, read-only availability verdict for a skill's `!`-injection at load.
    Mirrors run()'s guard order and never invokes Codex — the caller skips its
    cross-model section on NO and dispatches the judge on YES. Always exit 0."""
    if disabled_by_env(kind, environ):
        flag = ("SPEC_OPS_CODEX_WRITE"
                if kind == "write-requirements" and not _is_off(environ.get("SPEC_OPS_CODEX"))
                else "SPEC_OPS_CODEX")
        return f"CODEX: NO — disabled by {flag}"
    if not codex_available():
        return "CODEX: NO — codex CLI not on PATH"
    if not codex_authenticated(environ):
        return "CODEX: NO — codex not authenticated (set OPENAI_API_KEY/CODEX_API_KEY or run `codex login`)"
    return "CODEX: YES — available and authenticated"


def _config_path(environ):
    home = environ.get("CODEX_HOME")
    base = Path(home) if home else Path.home() / ".codex"
    return base / "config.toml"


def resolve_model(arg_model, environ):
    """Explicit arg → the user's config.toml `model` → the documented default constant.
    Never hard-coded at a call site; the constant is the last resort, not the norm."""
    if arg_model:
        return arg_model
    path = _config_path(environ)
    if tomllib is not None and path.is_file():
        try:
            with open(path, "rb") as fh:
                cfg = tomllib.load(fh)
            model = cfg.get("model")
            if isinstance(model, str) and model.strip():
                return model.strip()
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            pass  # unreadable / malformed config → fall through to the default
    return DEFAULT_MODEL


# ---- verdict extraction: three fallback channels (defense in depth) ----------------

def _strip_json_fence(text):
    """Strip a ```json … ``` (or bare ```) fence, returning the inner text."""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return s


def _loads(text):
    """Parse JSON, tolerating a code fence or surrounding prose. Returns the value or None."""
    s = _strip_json_fence(text)
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to the outermost {...} / [...] span embedded in noise.
    starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    end = max(s.rfind("}"), s.rfind("]"))
    if end <= start:
        return None
    try:
        return json.loads(s[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def parse_stream(stdout):
    """Walk the `--json` JSONL event stream. Returns (last_agent_message, failed):

      * last_agent_message — the text of the LAST `item.completed` agent_message event.
        LAST, not first: a known gpt-5.x quirk leaks schema/scratch into earlier
        agent messages, so an intermediate message can be junk while the final one
        carries the real verdict.
      * failed — True if a `turn.failed` / `error` event appeared (→ the run errored)."""
    last_msg = None
    failed = False
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype in ("turn.failed", "error"):
            failed = True
            continue
        if etype == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    last_msg = text
    return last_msg, failed


def extract_verdict(stdout, last_message_text):
    """Recover the verdict JSON through three channels in priority order, returning the
    first that parses to a JSON value (None if every channel fails):
      1. the JSONL stream's last agent_message,
      2. the `--output-last-message` file text,
      3. fenced/embedded JSON in raw stdout."""
    last_msg, _failed = parse_stream(stdout)
    for candidate in (last_msg, last_message_text, stdout):
        data = _loads(candidate)
        if data is not None:
            return data
    return None


# ---- Codex invocation --------------------------------------------------------------

class Invocation:
    """Result of one `codex exec` run."""

    __slots__ = ("stdout", "last_message", "timed_out", "failed", "returncode")

    def __init__(self, stdout="", last_message="", timed_out=False, failed=False, returncode=0):
        self.stdout = stdout
        self.last_message = last_message
        self.timed_out = timed_out
        self.failed = failed
        self.returncode = returncode


def build_argv(model, effort, cd, schema_file, last_message_file):
    """The fixed, read-only `codex exec` command line. By construction it carries NO
    escalating flag and NO writable scope — `--sandbox read-only` is the only sandbox
    setting and nothing here ever adds `--dangerously-bypass-*` or `--add-dir`."""
    argv = [
        "codex", "exec", "-",            # prompt arrives on stdin
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--json",
        "-o", last_message_file,
        "-m", model,
        "-c", f"model_reasoning_effort={effort}",
    ]
    if cd:
        argv += ["-C", cd]
    if schema_file:
        argv += ["--output-schema", schema_file]
    return argv


def invoke_codex(prompt, model, effort, cd, schema_file, timeout):
    """Run one read-only `codex exec`, feeding the prompt on stdin and collecting the
    JSONL stream plus the last-message file. Kills the subprocess and reports a timeout
    rather than letting a hung turn stall the caller."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w+", suffix=".txt", prefix="codex_last_", delete=False
    )
    last_file = tmp.name
    tmp.close()
    try:
        argv = build_argv(model, effort, cd, schema_file, last_file)
        try:
            proc = subprocess.run(
                argv,
                input=prompt,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return Invocation(timed_out=True)
        except OSError:
            # Spawn failed despite the PATH probe (e.g. race) — treat as an error.
            return Invocation(failed=True, returncode=1)
        _last_msg, failed = parse_stream(proc.stdout)
        try:
            last_message = Path(last_file).read_text(encoding="utf-8")
        except OSError:
            last_message = ""
        return Invocation(
            stdout=proc.stdout or "",
            last_message=last_message,
            failed=failed,
            returncode=proc.returncode,
        )
    finally:
        try:
            os.unlink(last_file)
        except OSError:
            pass


def _log(message):
    """Exactly one line to stderr per non-zero outcome (skip / error / unparseable)."""
    sys.stderr.write("codex_bridge: " + message + "\n")


def run(kind, prompt, schema_file, cd, model, effort, timeout, environ,
        invoke=invoke_codex):
    """Core flow, separated from argv parsing for testability. Returns an exit code and,
    on success, writes the validated JSON to stdout. `invoke` is injected so tests can
    drive the exit taxonomy without a real Codex."""
    if disabled_by_env(kind, environ):
        _log("skipped (disabled by env switch) — proceeding without Codex")
        return SKIP
    if not codex_available():
        _log("skipped (codex not on PATH) — proceeding without Codex")
        return SKIP
    if not codex_authenticated(environ):
        _log("skipped (codex not authenticated) — proceeding without Codex")
        return SKIP

    resolved_model = resolve_model(model, environ)

    # Attempt 1, then exactly one re-dispatch with the canonical schema appended if the
    # shape is wrong. An explicit error/timeout never retries (that is code 11, not a
    # shape problem); only a parseable-but-invalid or unparseable reply earns the retry.
    schema_appendix = (
        "\n\nReturn ONLY strict JSON matching this exact shape, with no prose:\n\n"
        + validate_return.SCHEMAS[kind] + "\n"
    )
    for attempt in (1, 2):
        attempt_prompt = prompt if attempt == 1 else prompt + schema_appendix
        result = invoke(attempt_prompt, resolved_model, effort, cd, schema_file, timeout)
        if result.timed_out:
            _log(f"timed out after {timeout}s — proceeding without Codex")
            return ERROR
        if result.failed:
            _log("codex reported an error/turn-failure — proceeding without Codex")
            return ERROR
        data = extract_verdict(result.stdout, result.last_message)
        if data is not None and not validate_return.validate(kind, data):
            sys.stdout.write(json.dumps(data) + "\n")
            return OK
        # else: fall through to one re-dispatch, then give up

    _log("reply unparseable / wrong-shape after one re-dispatch — proceeding without Codex")
    return UNPARSEABLE


def main(argv):
    kind = prompt_file = schema_file = cd = model = None
    effort = "xhigh"
    timeout = DEFAULT_TIMEOUT
    do_probe = False
    i = 0

    def nextval(flag):
        nonlocal i
        i += 1
        if i >= len(argv):
            sys.stderr.write(f"codex_bridge: {flag} needs a value\n")
            sys.exit(3)
        return argv[i]

    while i < len(argv):
        a = argv[i]
        if a == "--kind":
            kind = nextval(a)
        elif a == "--prompt-file":
            prompt_file = nextval(a)
        elif a == "--schema-file":
            schema_file = nextval(a)
        elif a == "--probe":
            do_probe = True
        elif a == "--cd":
            cd = nextval(a)
        elif a == "--model":
            model = nextval(a)
        elif a == "--effort":
            effort = nextval(a)
        elif a == "--timeout":
            raw = nextval(a)
            try:
                timeout = int(raw)
            except ValueError:
                sys.stderr.write(f"codex_bridge: --timeout must be an integer (got {raw!r})\n")
                return 3
        elif a in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return 0
        else:
            sys.stderr.write(f"codex_bridge: unknown argument {a!r}\n")
            return 3
        i += 1

    if kind not in validate_return.VALIDATORS:
        sys.stderr.write(
            "codex_bridge: --kind must be one of judge-verify, judge-refine, write-requirements\n"
        )
        return 3
    if do_probe:
        sys.stdout.write(probe_line(kind, os.environ) + "\n")
        return 0
    if not prompt_file:
        sys.stderr.write("codex_bridge: --prompt-file is required\n")
        return 3
    if effort not in VALID_EFFORTS:
        sys.stderr.write(
            f"codex_bridge: --effort must be one of {', '.join(VALID_EFFORTS)} (got {effort!r})\n"
        )
        return 3
    try:
        prompt = open(prompt_file, "r", encoding="utf-8").read()
    except OSError as e:
        sys.stderr.write(f"codex_bridge: cannot read --prompt-file: {e}\n")
        return 3
    if schema_file and not Path(schema_file).is_file():
        sys.stderr.write(f"codex_bridge: --schema-file not found: {schema_file}\n")
        return 3

    return run(kind, prompt, schema_file, cd, model, effort, timeout, os.environ)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
