---
paths:
  - "**/SKILL.md"
  - "**plugins/**/hooks/**"
---

# Writing Skills for This Project

Patterns distilled from the strongest plugins here (`spec-ops`, `worktree-ops`, `skill-manager`). Use the `skill-creator` skill to scaffold or revise any skill — don't hand-roll structure.

## Frontmatter

- Always set `name` + a trigger-oriented `description`. Add `argument-hint` when the skill takes positional args; omit it otherwise. Hard caps (the skill fails to load if exceeded): `name` ≤ 64 chars, lowercase letters / numbers / hyphens only, no `anthropic` / `claude`; `description` non-empty, ≤ 1024 chars, no XML tags — this project's descriptions are deliberately trigger-rich, so watch the 1024 ceiling.
- Scope `allowed-tools` to least privilege — only what the skill actually calls. See `claude-code/plugins/skill-manager/skills/status/SKILL.md:4`; `pull-worktree` deliberately omits `gh`.
- Descriptions say WHEN to trigger: front-load the action, list concrete quoted user phrasings, and in a multi-skill plugin state what the skill does NOT do and whose job that is. See `claude-code/plugins/spec-ops/skills/verify-spec/SKILL.md:3`.
- Pin `model` + `effort` deliberately — high for reasoning/orchestration skills, cheap/low for mechanical wrappers; don't leave high-stakes skills on the session default. See `claude-code/plugins/spec-ops/skills/write-spec/SKILL.md`.
- Set `disable-model-invocation: true` on any side-effecting / destructive / git-writing skill (user-invoked only); leave it off for read-only skills. Use this exact field — never `user-invocable`.
- Don't add `context: fork` / `agent` to a skill that owns a user-interaction or multi-pass loop: both are ignored when the skill is invoked via the Skill tool, and a fork strips the conversation history plus the main-session `AskUserQuestion` path. Delegate the heavy read-only work to `Task` subagents instead — finer-grained (N parallel agents) than a whole-skill fork. See `claude-code/plugins/spec-ops/skills/verify-spec/SKILL.md`.

## Determinism: code over prose

- Thin skill over a deterministic engine: put every load-bearing or destructive operation in a checked-in script/CLI that returns distinct exit codes; the SKILL.md orchestrates and renders. Leave no decision logic in prose. See `claude-code/plugins/skill-manager/bin/skillctl` and `claude-code/plugins/worktree-ops/scripts/wt-merge.sh` (codes branched on in `merge-worktree/SKILL.md:39`).
- Enforce hard invariants with hooks, not prose: a `Stop` hook to gate turn-end until validated state proves the gate passed; a `PreToolUse` hook to block forbidden actions. Reference the hook from the SKILL.md so the model knows the rail exists. See `claude-code/plugins/spec-ops/skills/refine-spec/stop_refine_spec.py` and `claude-code/plugins/worktree-ops/hooks/guard.sh`.
- Inject a deterministic up-front fact with `` !`<command>` `` — it runs at skill **load** (preprocessing, before the model acts) and replaces the line with the command's stdout, so the model branches on a fact instead of reasoning it out, and skips dead work on the common path. Works in `SKILL.md` (not just slash commands); needs `Bash` in `allowed-tools`. Use **only** for facts that are **argument-independent** (it fires before the model resolves a `@`-mention / freeform arg) and **stable for the run** (once per invocation, even in a looping skill) — an availability / env probe fits; anything needing a model-resolved path or mid-run state does not. See the `--probe` mode of `claude-code/plugins/spec-ops/scripts/codex_bridge.py`, `!`-injected atop each cross-model section in `skills/verify-spec/SKILL.md`.

## Subagents & delegation

- Specialize a subagent (ship `agents/<name>.md`) only when you keep dispatching the **same worker with the same fixed instructions** — e.g. an adversarial judge or completeness gate: the agent carries the rubric as its system prompt (one source, no inline drift, plus a `model`/`effort` lever the built-in agents can't give). Keep the built-in `Explore` for per-run, claim-list-driven read-only lookups — a custom agent there is upkeep for no gain. See `claude-code/plugins/spec-ops/agents/spec-verify-judge.md`, dispatched from `skills/verify-spec/SKILL.md`.
- Pin a gate/judge agent's `model` + `effort` explicitly and restrict its `tools` to read-only — a quality gate must be deterministic, not session-inherited. Plugin agents support `model` / `effort` / `tools` / `maxTurns` / `disallowedTools` / `skills` / `memory` / `isolation` but NOT `hooks` / `mcpServers` / `permissionMode`; they're namespaced `plugin:agent` and auto-discovered from `agents/` (no `plugin.json` entry).
- A subagent **cannot call `AskUserQuestion`** — keep every user question in the main session: a delegated stage returns a structured `blocked` result, main asks, then re-dispatches. See `claude-code/plugins/spec-ops/skills/orchestrate-spec/SKILL.md`.
- Treat a subagent's return as untrusted model input: require **strict JSON in an explicit shape** and validate the fields you depend on before using them — never treat its prose as ground truth. See the grounder / judge return contracts in `claude-code/plugins/spec-ops/skills/verify-spec/SKILL.md`.

## Defensive programming

- Treat all model-authored input (ledgers, slugs, labels, args) as untrusted: validate type/enum/shape and reject with a message that echoes the canonical schema so the model self-corrects. See `claude-code/plugins/spec-ops/skills/refine-spec/stop_refine_spec.py`.
- Hooks fail-safe on a real violation (block); fail-open only when they genuinely can't tell a run is active, so they never brick an unrelated session. See `claude-code/plugins/worktree-ops/hooks/guard.sh`.
- Harden shell helpers: `set -euo pipefail` (drop `-e` only for structured-output scripts that must survive a failing subcommand), `command -v` dependency guards, regex-validate any model value used in a path or branch name, and avoid BSD-only constructs like `sed -i ''`. Good: `claude-code/plugins/worktree-ops/scripts/wt-create.sh`. Avoid: `claude-code/plugins/ralph/scripts/ralph-init.sh:79`.
- Destructive commands are dry-by-default: without `--force`, print what would change; require `--force` to mutate. See `skillctl remove-*` and `claude-code/plugins/worktree-ops/scripts/wt-teardown.sh`.

## Output consistency

- Ship a fill-in skeleton for any structured output: embed a literal skeleton with placeholders and instruct the model to copy values verbatim from tool output, drop lines that don't apply, and never invent a value. Treat script output (documented columns/keys) as ground truth. See `claude-code/plugins/skill-manager/skills/status/SKILL.md:35` and `claude-code/plugins/worktree-ops/skills/list-worktrees/SKILL.md:16`.

## Hygiene

- One naming scheme per plugin: kebab-case directories matching frontmatter `name`, a uniform verb/prefix pattern, and helper scripts named to map back to the skills they serve.
- Resolve bundled paths via `${CLAUDE_PLUGIN_ROOT}` (or `Path(__file__).parent`) — never a hardcoded `~/.claude` path.
- Instructions only: cut history, theory, measurement tables, and rationale the model doesn't need to act. State the rule, not the justification; keep background in one source (README or template comment).
- Define each shared skill in exactly one plugin and reference it — never copy a skill verbatim into another plugin.
- Single-source a shared convention or schema in **one** place — a `references/<topic>.md` that each skill points to, or the validating hook / producer script — instead of restating it per skill; where a literal must be mirrored across code and docs, add a mirror-anchor comment so the copies can't silently drift. See `claude-code/plugins/spec-ops/references/ac-contract.md` and the `METHODS` / `PATTERN_TYPES` constants in `skills/verify-spec/stop_verify_spec.py`.
- Budget `SKILL.md` size, and disclose to protect it. The body loads on trigger and competes with conversation context — keep it lean (official guidance: under ~500 lines / ~5k tokens; the Read tool **hard-errors past 10k tokens**, so an over-budget skill silently fails to load). When a skill nears the budget, push on-demand reference into a `references/<topic>.md` behind a pointer **one level deep** from `SKILL.md` (Claude only partial-reads a reference that points to another reference); inline what every run needs, disclose what only some branches reach. Within the body, collapse a constraint restated across sites into a single repeated leading word rather than re-explaining it each time. See `claude-code/plugins/spec-ops/references/` and verify-spec's `report-only` sweeps + cross-model pointer.
- **Decompose a multi-rule paragraph into a reasoned list — don't bury independent rules in prose.** A block that crams several independent rules (or an ordered set — an authority / priority / sequence) into one paragraph invites the model to honor some and silently drop the rest at run time (decoherence). Split it into one item per rule, each `**imperative.** why`; number it only when the order is itself load-bearing (ground-truth authority, build sequence). **Keep each rule's *operative* why** — the consequence that makes it stick (what breaks if it's ignored), which is load-bearing and distinct from the history / theory the *Instructions only* bullet cuts — so this is the opposite of stripping to a bare `ALWAYS` / `NEVER` wall. Don't fragment coherent single-concept prose, or an already-itemized set, just to list it. See the "Constant across all three rigors" list in `claude-code/plugins/spec-ops/skills/write-spec/SKILL.md` and the hook-enforcement + Handoff lists in `claude-code/plugins/spec-ops/skills/verify-spec/SKILL.md`.
- Add a per-plugin `.gitignore` (`__pycache__/`, `*.pyc`) to any plugin that ships scripts.
