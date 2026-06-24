# codex

Run the OpenAI Codex CLI from inside Claude Code as a **cross-model escape hatch** — hand a
one-off task to a different provider's model for a second opinion, without leaving your
session. Three skills, all routed through one deterministic, **fail-open** bridge:

| Skill | What it does | Touches the repo? |
| ----- | ------------ | ----------------- |
| **`review-codex`** | A read-only cross-model **code review** of your uncommitted work or a named target. Surfaces Codex's review verbatim, in Codex's own severity order, then stops. | No (read-only) |
| **`ask-codex`** | A read-only free-form **question** answered by Codex — explain, review a plan, repo Q&A, opinion on a diff. | No (read-only) |
| **`delegate-codex`** | Hand Codex a **write task** and let it edit the working tree, then shows you the diff. User-invoked only. | **Yes** (`workspace-write`) |

Every call runs with **web search on** and Codex grounding itself natively in your repo
(AGENTS.md + read-only file reads). Codex's output is surfaced **verbatim as untrusted
external text** — it is never followed as instructions or auto-executed. If Codex is absent,
unauthenticated, disabled, slow, or broken, a skill **reports and stops** — it never answers
or edits as Claude in Codex's place.

## Requirements & setup

- **Codex CLI**, on your `PATH`. Install it from OpenAI's `codex` distribution and confirm
  with `codex --version`.
- **An OpenAI-authenticated Codex setup** — either log in (`codex login`) or set
  `OPENAI_API_KEY` (or `CODEX_API_KEY`) in your environment. The plugin checks auth locally
  (`codex login status`); it never logs you in, opens a browser, or makes a network call to
  probe availability.
- This plugin assumes the **default OpenAI provider**. Web search and the default model
  (the latest `gpt-5.x` frontier model, discovered automatically) both require it; if your
  `~/.codex/config.toml` selects a non-OpenAI `model_provider`, the skills report that and
  stop rather than silently running without web search.

Install the plugin from this marketplace and enable it for your project. The skills then
appear as `/review-codex`, `/ask-codex`, and `/delegate-codex`, or trigger by intent
("have Codex review this", "ask Codex how X works", "delegate this to Codex").

Optional per-call overrides: `--model <slug>` and `--effort <low|medium|high|xhigh>`. Absent
an override the latest model at `xhigh` is used. Each run prints the Codex **session id** so
you can continue the thread with `codex exec resume <id>`.

## Data sent to OpenAI and the web

**Web search is always on, with no opt-out.** That means your composed prompt and the
repo-derived context Codex reads to answer it **may be transmitted to OpenAI and to the web**
on every call. Don't use these skills on a repository whose contents must not leave your
machine. (This is the same exposure as running `codex exec` yourself.)

## Read-only vs. write exposure

- `review-codex` and `ask-codex` run Codex under `--sandbox read-only`: Codex can read your
  repo but **cannot modify it**. The read-only guarantee is structural — those skills only
  ever invoke the bridge's read-only path, which pins the read-only sandbox and constructs no
  escalation flag.
- `delegate-codex` runs under `--sandbox workspace-write`: Codex **edits your working tree**.
  The skill records what was already dirty, then shows you Codex's output plus the resulting
  `git diff` (attributing Codex's changes vs. anything pre-existing). It leaves the edits
  **uncommitted and unstaged** — it never commits, stages, or branches — so you review before
  keeping. If a write run errors partway, any partial edits are left in place and shown in the
  diff (not rolled back).

## Long runs and the Bash timeout

Each skill dispatches the bridge as a single foreground `Bash` call, which the harness hard-
kills at `BASH_MAX_TIMEOUT_MS` (default 20 minutes / `1200000`). The bridge's own per-call
timeout sits just under that cap so a slow Codex turn **fails open cleanly** (the skill
reports the timeout and stops) instead of being hard-killed mid-stream. For genuinely long
delegate tasks, raise `BASH_MAX_TIMEOUT_MS` to at least `1200000` (or higher) in your Claude
Code settings; if you leave it lower, a long run is killed at that cap and fails open.

## Environment switches

| Variable | Effect |
| -------- | ------ |
| `CODEX_PLUGIN=0` | Disable all Codex calls (any run is skipped and the skill reports it). Off is recognized as `0` / `false` / `no` / `off`. |
| `CODEX_PLUGIN_TIMEOUT` | Per-call bridge timeout in seconds (default 1170; keep it under your `BASH_MAX_TIMEOUT_MS`). |
| `OPENAI_API_KEY` / `CODEX_API_KEY` | Counted as usable auth (in addition to a logged-in CLI). |
| `CODEX_HOME` | Where the bridge looks for your Codex `config.toml` (default `~/.codex`). |

The bridge never echoes these values, your auth token, or any other secret into prompts,
output, or logs.

## How it works

`scripts/codex_bridge.py` is the single component that ever invokes `codex` — the skills only
compose a prompt, shell out to it, and branch on its exit code (`0` success · `10` skipped ·
`11` error/timeout · `12` unrecoverable reply). On success the raw Codex payload is the only
thing on stdout; the session id and any diagnostic go to stderr. The bridge feeds the prompt
on stdin and passes every caller value as a discrete argument, so a target/question/task
containing quotes, newlines, or leading dashes can't break or inject the command.

`tests/test_codex_bridge.py` is an offline test suite (no live `codex` call) covering the
sandbox/argv invariants, the exit taxonomy, output recovery, model discovery, and the
fail-open paths. Run it with `python3 tests/test_codex_bridge.py` or
`python3 -m pytest tests/test_codex_bridge.py`.
