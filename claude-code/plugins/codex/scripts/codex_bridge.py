#!/usr/bin/env python3
"""codex_bridge.py — the single, deterministic wrapper that hands a one-off task to the
OpenAI Codex CLI and returns Codex's raw answer.

This is the ONLY component that ever invokes `codex`. The review/ask/delegate skills
shell out to THIS script and branch on its exit code alone — so every provider-specific
flag, config key, and failure mode lives in one place and a caller never has to know how
Codex is spawned.

Design contract (why it is shaped this way):

  * Fail-open, always. Codex is an optional second model, never a dependency. An absent
    CLI, missing auth, a non-OpenAI provider, a timeout, an error, or an unrecoverable
    reply ALL resolve to a non-zero exit that means "proceed without me" — the caller
    surfaces one diagnostic line and stops, and NEVER substitutes Claude's own answer.

  * Read-only by construction. The review/ask paths must not be able to touch the repo,
    so their sandbox is `read-only` and this file never builds an escalating flag
    (`--dangerously-bypass-*`, a writable `--add-dir`, `danger-full-access`). The sandbox
    is a pure function of the run mode, so a read-only entrypoint cannot reach the
    `workspace-write` argv — the write path is a separate, explicitly-selected mode used
    only by delegate-codex.

  * Raw text out, metadata on stderr. On success stdout carries ONLY Codex's verbatim
    payload; the resumable session id and every diagnostic go to stderr, so the payload
    the caller surfaces is never polluted. There is no JSON-schema validation and no
    return-contract gate — the answer is markdown to surface, not a verdict to parse.

  * Web search hard-on, repo grounded natively. Every call passes `-c tools.web_search=true`
    and forces AGENTS.md loading with a non-zero `-c project_doc_max_bytes`, and never
    passes `--ignore-user-config`. Grounding is Codex's own read-only file access under
    `-C <repo>` plus AGENTS.md — not Claude pre-assembling context into the prompt.

Provenance: this engine was modeled on spec-ops's `codex_bridge.py` but is an INDEPENDENT
copy this plugin owns — no shared import, no symlink, no drift test. It returns raw text
instead of contract-validated JSON, adds a `workspace-write` path, runs `codex debug
models` to pick the latest model, and uses its own `CODEX_PLUGIN_*` env namespace. When a
Codex CLI fact (a flag, a config key, the `--json` event shape) changes, re-check it here
AND in spec-ops's copy — they share an origin but evolve separately.

Usage:
    codex_bridge.py --probe
        One availability line — `CODEX: YES …` / `CODEX: NO — <reason>` — exit 0, no turn.
    codex_bridge.py --resolve-defaults
        Latest model + default effort + selectable-model catalog, exit 0, no turn.
    codex_bridge.py --prompt-file <f> [--cd <repo>] [--model <m>] [--effort <e>] [--timeout <s>]
        Read-only `codex exec` (used by ask-codex; review-codex's branch/commit case).
    codex_bridge.py --review --prompt-file <f> [--cd <repo>] [--model …] [--effort …]
        Read-only `codex exec review` on the uncommitted working tree (used by review-codex).
    codex_bridge.py --write --prompt-file <f> [--cd <repo>] [--model …] [--effort …]
        `workspace-write` `codex exec` (used by delegate-codex; Codex may edit the tree).

    `--prompt-file -` reads the prompt from THIS bridge's stdin (so a caller with no
    file-write tool can pipe a composed prompt via a heredoc). `--cd` defaults to the
    current directory, so `-C` is always emitted to Codex.

Exit codes (the caller branches on the code alone; every non-zero is fail-open):
    0   valid, non-empty raw output on stdout — surface it verbatim
    10  skipped — Codex absent / unauthenticated / non-OpenAI provider / disabled by env
    11  Codex error / timeout / turn.failed
    12  reply unrecoverable through all three channels (incl. empty output)

Env switches (disjoint from spec-ops's SPEC_OPS_* namespace):
    CODEX_PLUGIN=0          disable ALL Codex calls (any run ⇒ exit 10; off = 0/false/no/off)
    CODEX_PLUGIN_TIMEOUT    per-call timeout in seconds (an explicit --timeout still wins)
    OPENAI_API_KEY / CODEX_API_KEY   counted as usable auth (in addition to a logged-in CLI)
    CODEX_HOME              respected when locating the user's config.toml
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover — older interpreters skip the provider check
    tomllib = None

# Exit taxonomy — named so callers and tests never hard-code the integers.
OK = 0
SKIP = 10
ERROR = 11
UNRECOVERABLE = 12

# Last-resort model when `codex debug models` can't be reached at all (Codex broken/absent).
# The real default is DISCOVERED at runtime (resolve_model) — this constant is only the
# floor so a degraded run still names a model rather than crashing. Version-sensitive:
# revisit when `codex debug models` advances.
FALLBACK_MODEL = "gpt-5.6-sol"

# Default reasoning effort — overrides each model's own default (low for gpt-5.6-sol) with a
# high tier, since a cross-model second opinion is worth the extra reasoning. `high` (not
# `xhigh`) per operator preference: gpt-5.6-sol is highly capable at lower efforts.
DEFAULT_EFFORT = "high"

# Per-call ceiling so a hung turn can never stall the skill's foreground Bash call. Set 30s
# under 20min: a skill dispatches this bridge as a foreground Bash call the harness hard-
# kills at BASH_MAX_TIMEOUT_MS (1_200_000ms / 20min by default). Keeping the bridge's own
# timeout 30s below that cap lets it fail open cleanly instead of being hard-killed mid-stream.
# Overridable via CODEX_PLUGIN_TIMEOUT (seconds); an explicit --timeout arg still wins.
DEFAULT_TIMEOUT = 1170

# Force AGENTS.md loading regardless of the user's config.toml: a user value of 0 would
# silently defeat native repo grounding, so we set a generous non-zero cap on every call
# rather than merely not disabling it.
PROJECT_DOC_MAX_BYTES = 1048576

# Run modes. The sandbox is a pure function of the mode (sandbox_for_mode), so the read-only
# entrypoints can never reach the workspace-write argv.
MODE_EXEC = "exec"      # read-only `codex exec` (ask-codex; review-codex branch/commit case)
MODE_REVIEW = "review"  # read-only `codex exec review` on the uncommitted working tree
MODE_WRITE = "write"    # `workspace-write` `codex exec` (delegate-codex)
READ_ONLY_MODES = (MODE_EXEC, MODE_REVIEW)


def _is_off(val):
    """An env toggle reads as 'off' for the usual falsey spellings."""
    return isinstance(val, str) and val.strip().lower() in ("0", "false", "no", "off")


def disabled_by_env(environ):
    """True when CODEX_PLUGIN turns every call off (→ skip, byte-identical to no-Codex)."""
    return _is_off(environ.get("CODEX_PLUGIN"))


def resolve_timeout(environ, override=None):
    """Per-call timeout (seconds). An explicit --timeout (`override`) wins; else
    CODEX_PLUGIN_TIMEOUT; else the default. A missing / invalid / non-positive value
    anywhere falls back — a bad env var or arg never crashes the bridge."""
    if override is not None:
        return override if override > 0 else DEFAULT_TIMEOUT
    raw = environ.get("CODEX_PLUGIN_TIMEOUT")
    if raw is None:
        return DEFAULT_TIMEOUT
    try:
        val = int(str(raw).strip())
    except (ValueError, TypeError):
        return DEFAULT_TIMEOUT
    return val if val > 0 else DEFAULT_TIMEOUT


def codex_available():
    """Codex CLI on PATH?"""
    return shutil.which("codex") is not None


def codex_authenticated(environ):
    """Usable auth WITHOUT any interactive login, browser, or network call: an API key in
    the env, or a CLI that already reports logged-in. We probe `codex login status` (a local
    check) but NEVER run `codex login` — an absent auth is a skip, not a prompt."""
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


def _config_path(environ):
    home = environ.get("CODEX_HOME")
    base = Path(home) if home else Path.home() / ".codex"
    return base / "config.toml"


def configured_provider(environ):
    """The user's selected `model_provider` from config.toml, lowercased, or None when
    unset / unreadable. Unset means the default OpenAI provider."""
    if tomllib is None:
        return None
    path = _config_path(environ)
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as fh:
            cfg = tomllib.load(fh)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return None
    provider = cfg.get("model_provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip().lower()
    return None


def non_openai_provider(environ):
    """The provider name when config.toml explicitly selects a NON-OpenAI provider, else
    None. Web search and the gpt-5.x model default both require Codex's OpenAI provider, so
    a non-OpenAI `model_provider` is a precondition failure we surface rather than silently
    claiming search is on. Unset / default config ⇒ OpenAI ⇒ None (the common case)."""
    provider = configured_provider(environ)
    if provider is None or provider == "openai":
        return None
    return provider


def probe_line(environ):
    """One-line, read-only availability verdict for a skill's `!`-injection at load.
    Mirrors run()'s guard order and never invokes Codex — the caller skips its Codex call on
    NO and dispatches the bridge on YES. Always exit 0. Echoes no env values or secrets."""
    if disabled_by_env(environ):
        return "CODEX: NO — disabled by CODEX_PLUGIN"
    if not codex_available():
        return "CODEX: NO — codex CLI not on PATH"
    if not codex_authenticated(environ):
        return ("CODEX: NO — codex not authenticated "
                "(set OPENAI_API_KEY/CODEX_API_KEY or run `codex login`)")
    provider = non_openai_provider(environ)
    if provider:
        return (f"CODEX: NO — config.toml model_provider is '{provider}', not the OpenAI "
                "provider (web search and the model default require it)")
    return "CODEX: YES — available and authenticated"


# ---- model discovery: `codex debug models` ----------------------------------------------

def run_debug_models(timeout=20):
    """Run `codex debug models` and return its raw stdout, or None on any failure. Local
    catalog query — no Codex turn, no network dependency assumed."""
    try:
        res = subprocess.run(
            ["codex", "debug", "models"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def parse_models(json_text):
    """Parse `codex debug models` JSON into (latest_slug, catalog):

      * latest_slug — the selectable frontier model: among `visibility == "list"` models
        that are NOT superseded (falsy `upgrade` — note the field is present-but-`null` for
        current models, not absent), the one with the LOWEST `priority` (a preference rank,
        lower = more preferred). None if nothing qualifies.
      * catalog — [(slug, [efforts])] for every `visibility == "list"` model, in catalog
        order; the source for the override picker.

    Returns (None, []) on any structural surprise — the caller treats that as "unavailable"
    and falls back, never crashes."""
    try:
        data = json.loads(json_text)
        models = data.get("models")
    except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
        return None, []
    if not isinstance(models, list):
        return None, []

    catalog = []
    latest_slug = None
    latest_priority = None
    for m in models:
        if not isinstance(m, dict):
            continue
        if m.get("visibility") != "list":
            continue
        slug = m.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        levels = m.get("supported_reasoning_levels")
        efforts = []
        if isinstance(levels, list):
            efforts = [l.get("effort") for l in levels
                       if isinstance(l, dict) and isinstance(l.get("effort"), str)]
        catalog.append((slug, efforts))

        if m.get("upgrade"):  # superseded → not a candidate for "latest"
            continue
        priority = m.get("priority")
        if not isinstance(priority, (int, float)):
            continue
        if latest_priority is None or priority < latest_priority:
            latest_priority = priority
            latest_slug = slug
    return latest_slug, catalog


def resolve_defaults_output(environ):
    """Deterministic defaults/catalog block for a skill's `!`-injection at load — the single
    source for the default model/effort AND the override picker. Like --probe it is fail-open:
    if Codex is off, absent, or `codex debug models` fails, it prints one 'unavailable' marker
    and exits 0 (no skill-load pollution); the real run then fails open per the exit taxonomy."""
    if disabled_by_env(environ):
        return "CODEX_DEFAULTS: unavailable — disabled by CODEX_PLUGIN"
    if not codex_available():
        return "CODEX_DEFAULTS: unavailable — codex CLI not on PATH"
    raw = run_debug_models()
    if raw is None:
        return "CODEX_DEFAULTS: unavailable — `codex debug models` failed"
    latest, catalog = parse_models(raw)
    if not latest or not catalog:
        return "CODEX_DEFAULTS: unavailable — model catalog not parseable"
    lines = [
        f"CODEX_DEFAULTS_MODEL: {latest}",
        f"CODEX_DEFAULTS_EFFORT: {DEFAULT_EFFORT}",
        "CODEX_DEFAULTS_CATALOG:",
    ]
    for slug, efforts in catalog:
        lines.append(f"- {slug} | {','.join(efforts) if efforts else '(none reported)'}")
    return "\n".join(lines)


def resolve_model(arg_model, environ):
    """Explicit --model arg → the DISCOVERED latest model → the last-resort constant. The
    default is the discovered frontier model (NOT the user's config.toml `model`); the
    constant only catches a fully broken `codex debug models`."""
    if arg_model:
        return arg_model
    raw = run_debug_models()
    if raw is not None:
        latest, _catalog = parse_models(raw)
        if latest:
            return latest
    return FALLBACK_MODEL


# ---- answer & session-id recovery from the run ------------------------------------------

def parse_stream(stdout):
    """Walk the `--json` JSONL event stream. Returns (last_agent_message, thread_id, failed):

      * last_agent_message — text of the LAST `item.completed` whose `item.type ==
        "agent_message"` (`.item.text`); there is no top-level agent_message event.
      * thread_id — from the `thread.started` event; the ONLY source for the resumable
        session id (it is `thread_id`, never `session_id`/`conversation_id`).
      * failed — True if a `turn.failed` / `error` event appeared."""
    last_msg = None
    thread_id = None
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
        elif etype == "thread.started":
            tid = event.get("thread_id")
            if isinstance(tid, str) and tid:
                thread_id = tid
        elif etype == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    last_msg = text
    return last_msg, thread_id, failed


def _fenced_text(stdout):
    """Last-resort channel 3: a fenced ```…``` block embedded in raw stdout, or None. Never
    returns the raw JSONL dump as an 'answer' — only a genuine fenced text block — so an
    empty/structured stream resolves to UNRECOVERABLE rather than surfacing event noise."""
    if not isinstance(stdout, str):
        return None
    start = stdout.find("```")
    if start == -1:
        return None
    rest = stdout[start + 3:]
    nl = rest.find("\n")
    if nl == -1:
        return None
    body = rest[nl + 1:]
    end = body.find("```")
    if end == -1:
        return None
    inner = body[:end].strip()
    return inner or None


def recover_text(last_message_file_text, stdout):
    """Recover Codex's answer through three channels in fixed precedence — the
    `--output-last-message` file is the most version-robust, so it wins:
      1. the `--output-last-message` file,
      2. the last `agent_message` in the `--json` stream,
      3. a fenced text block in raw stdout.
    Returns the first non-empty candidate verbatim, or None if every channel is empty."""
    stream_msg, _tid, _failed = parse_stream(stdout)
    for candidate in (last_message_file_text, stream_msg, _fenced_text(stdout)):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


# ---- Codex invocation -------------------------------------------------------------------

class Invocation:
    """Result of one `codex exec` run."""

    __slots__ = ("stdout", "stderr", "last_message", "timed_out", "returncode")

    def __init__(self, stdout="", stderr="", last_message="", timed_out=False, returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.last_message = last_message
        self.timed_out = timed_out
        self.returncode = returncode


def sandbox_for_mode(mode):
    """The sandbox is a pure function of the mode — the only place a sandbox is chosen — so a
    read-only entrypoint structurally cannot emit a `workspace-write` argv."""
    return "workspace-write" if mode == MODE_WRITE else "read-only"


def build_argv(mode, model, effort, cd, last_message_file):
    """The fixed `codex exec` command line for a run mode. By construction it carries NO
    escalating flag (`--dangerously-bypass-*`, a writable `--add-dir`, `danger-full-access`)
    and NO `--ignore-user-config`; web search and AGENTS.md loading are forced on every mode.

    For MODE_REVIEW the global flags (`-s`, `-C`, the `-c` overrides, `-o`, `--json`) MUST
    precede the `review` subcommand — they belong to `codex exec`, not `review`, which errors
    if they follow it. The composed instructions arrive on stdin via `review -` (codex exec
    review: "If `-` is used, read from stdin"), with NO scope flag (`--uncommitted`/`--base`/
    `--commit`), which Codex rejects alongside a prompt; the default scope is the uncommitted
    working tree. EVERY mode feeds the prompt on stdin (exec/write via the `-` positional,
    review via `review -`), so adversarial caller text — a leading dash, quotes, newlines —
    is never an argv element that Codex's option parser could read as a flag."""
    sandbox = sandbox_for_mode(mode)
    globals_ = [
        "--sandbox", sandbox,
        "--skip-git-repo-check",
        "--json",
        "-o", last_message_file,
        # `--model=<v>` / `model_reasoning_effort=<v>` use the `=`-attached form ON PURPOSE:
        # a caller override value that begins with `-` stays BOUND to its flag and can never be
        # re-parsed by Codex's option parser as a standalone flag (e.g. an injected
        # `--dangerously-bypass-…`). A bogus value is then just an unknown model/effort Codex
        # rejects → the bridge fails open, never an escalation.
        f"--model={model}",
        "-c", f"model_reasoning_effort={effort}",
        "-c", "tools.web_search=true",
        "-c", f"project_doc_max_bytes={PROJECT_DOC_MAX_BYTES}",
        "-C", cd,
    ]
    if mode == MODE_REVIEW:
        # `review -` reads the composed instructions from stdin — same argv-safe channel as
        # the exec path, so a leading-dash review instruction can never be parsed as a flag.
        return ["codex", "exec"] + globals_ + ["review", "-"]
    # `-` tells codex to read the prompt from stdin.
    return ["codex", "exec", "-"] + globals_


def invoke_codex(mode, prompt, model, effort, cd, timeout):
    """Run one `codex exec`, non-interactively, with a per-call timeout and a process-GROUP
    kill on timeout (codex spawns children; killing only the parent leaks orphans). Each call
    gets a unique 0700 temp dir for its last-message file, removed on success and failure, so
    two concurrent skill runs never collide. stdin is always fed/closed — no TTY, no approval
    wait, so any condition that would block for input resolves to a timeout, never a hang."""
    tmpdir = tempfile.mkdtemp(prefix="codex_bridge_")
    last_file = os.path.join(tmpdir, "last_message.txt")
    try:
        argv = build_argv(mode, model, effort, cd, last_file)
        # Every mode reads the prompt from stdin (exec/write via `-`, review via `review -`),
        # so caller text is never an argv element Codex's option parser could read as a flag.
        stdin_text = prompt
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,  # own process group → killpg reaches every child
            )
        except OSError:
            # Spawn failed despite the PATH probe (e.g. a race) — treat as an error.
            return Invocation(returncode=1)
        try:
            stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            try:
                proc.communicate(timeout=10)
            except (subprocess.SubprocessError, OSError):
                pass
            return Invocation(timed_out=True)
        try:
            last_message = Path(last_file).read_text(encoding="utf-8")
        except OSError:
            last_message = ""
        return Invocation(
            stdout=stdout or "",
            stderr=stderr or "",
            last_message=last_message,
            returncode=proc.returncode,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _kill_group(proc):
    """Signal the child's whole process group, falling back to the bare process."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _log(message):
    """Exactly one stderr line per non-zero outcome (skip / error / unrecoverable). Echoes no
    env values, auth tokens, or other secrets."""
    sys.stderr.write("codex_bridge: " + message + "\n")


def _emit_session_id(thread_id):
    """Emit the resumable session id on stderr (never stdout, so the payload stays clean).
    The id is `thread_id`; if it couldn't be recovered, say so rather than invent one."""
    if thread_id:
        sys.stderr.write(f"SESSION_ID: {thread_id}\n")
    else:
        sys.stderr.write("SESSION_ID: unavailable\n")


def _excerpt(text, limit=800):
    """A bounded, single-line excerpt of Codex's stderr for a failure diagnostic."""
    if not text:
        return ""
    flat = " ".join(text.split())
    return flat[:limit]


def run(mode, prompt, cd, model, effort, timeout, environ, invoke=invoke_codex):
    """Core flow, separated from argv parsing for testability. Returns an exit code and, on
    success, writes ONLY Codex's raw payload to stdout (session id + diagnostics on stderr).
    `invoke` is injected so tests drive the exit taxonomy without a real Codex."""
    if disabled_by_env(environ):
        _log("skipped (disabled by CODEX_PLUGIN) — proceeding without Codex")
        return SKIP
    if not codex_available():
        _log("skipped (codex not on PATH) — proceeding without Codex")
        return SKIP
    if not codex_authenticated(environ):
        _log("skipped (codex not authenticated) — proceeding without Codex")
        return SKIP
    provider = non_openai_provider(environ)
    if provider:
        _log(f"skipped (config.toml model_provider '{provider}' is not OpenAI; web search "
             "and the model default require it) — proceeding without Codex")
        return SKIP

    resolved_model = resolve_model(model, environ)
    # Wall-clock across the Codex turn, surfaced for tracking. Folded into the existing single
    # diagnostic on a non-zero exit (preserves the one-line fail-open invariant the tests pin)
    # and emitted as its own line on success (where the session id already makes stderr multi-line).
    started = time.perf_counter()
    result = invoke(mode, prompt, resolved_model, effort, cd, timeout)
    elapsed = f"{time.perf_counter() - started:.1f}s"

    if result.timed_out:
        _log(f"timed out after {timeout}s ({elapsed} elapsed, process group killed) — proceeding without Codex")
        return ERROR
    _stream_msg, thread_id, failed = parse_stream(result.stdout)
    if failed:
        _log(f"codex reported turn.failed/error after {elapsed} — proceeding without Codex"
             + (f": {_excerpt(result.stderr)}" if result.stderr.strip() else ""))
        return ERROR
    if result.returncode != 0:
        _log(f"codex exited {result.returncode} after {elapsed} — proceeding without Codex"
             + (f": {_excerpt(result.stderr)}" if result.stderr.strip() else ""))
        return ERROR

    text = recover_text(result.last_message, result.stdout)
    if text is None:
        _log(f"reply unrecoverable through all channels ({elapsed}) — proceeding without Codex")
        return UNRECOVERABLE

    # Success: raw payload to stdout ONLY; session id + timing to stderr.
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    _emit_session_id(thread_id)
    _log(f"completed in {elapsed}")
    return OK


def main(argv):
    prompt_file = cd = model = None
    effort = DEFAULT_EFFORT
    timeout_override = None
    do_probe = False
    do_defaults = False
    review = False
    write = False
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
        if a == "--probe":
            do_probe = True
        elif a == "--resolve-defaults":
            do_defaults = True
        elif a == "--review":
            review = True
        elif a == "--write":
            write = True
        elif a == "--prompt-file":
            prompt_file = nextval(a)
        elif a == "--cd":
            cd = nextval(a)
        elif a == "--model":
            model = nextval(a)
        elif a == "--effort":
            effort = nextval(a)
        elif a == "--timeout":
            raw = nextval(a)
            try:
                timeout_override = int(raw)
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

    if do_probe:
        sys.stdout.write(probe_line(os.environ) + "\n")
        return 0
    if do_defaults:
        sys.stdout.write(resolve_defaults_output(os.environ) + "\n")
        return 0

    if review and write:
        sys.stderr.write("codex_bridge: --review and --write are mutually exclusive\n")
        return 3
    mode = MODE_WRITE if write else MODE_REVIEW if review else MODE_EXEC

    if not prompt_file:
        sys.stderr.write("codex_bridge: --prompt-file is required for a run\n")
        return 3
    if not (isinstance(effort, str) and effort.strip()):
        effort = DEFAULT_EFFORT
    if prompt_file == "-":
        prompt = sys.stdin.read()  # caller piped the composed prompt on the bridge's stdin
    else:
        try:
            prompt = open(prompt_file, "r", encoding="utf-8").read()
        except OSError as e:
            sys.stderr.write(f"codex_bridge: cannot read --prompt-file: {e}\n")
            return 3

    cd = cd or os.getcwd()  # -C is always emitted; codex resets cwd mid-run, so never rely on it
    timeout = resolve_timeout(os.environ, timeout_override)
    return run(mode, prompt, cd, model, effort, timeout, os.environ)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
