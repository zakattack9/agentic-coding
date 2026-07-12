# ParaQwen Dictation

ParaQwen Dictation is a reproducible, fully local voice-dictation setup for
macOS. Spokenly uses NVIDIA Parakeet for speech recognition, deterministic
Python processors for safe commands and exact snippets, and Qwen through
Ollama for conservative transcript cleanup.

After downloading the models, the entire pipeline can run offline without API
fees, subscriptions, word limits, or transcription quotas.

## What it can do

- Clean up capitalization, punctuation, grammar, filler words, repetitions,
  and clear false starts without turning the transcript into a rewritten answer.
- Resolve common spoken self-corrections such as “I mean,” “no, actually,”
  “sorry, I meant,” and “or rather.”
- Apply bounded inline editing commands such as deleting the last word,
  sentence, phrase, or abandoned thought.
- Insert new lines and paragraphs deterministically, or format dictated items
  as bulleted and numbered lists.
- Expand configurable phrases into exact signatures, URLs, addresses,
  disclaimers, slash commands, and other multiline text.
- Preserve each snippet's original position even if the cleanup model moves or
  drops its protected placeholder.
- Remove trailing spaces and newlines so inserted terminal text cannot carry a
  final Return and execute automatically.
- Optionally resolve spoken file names into verified, project-local `@path`
  references for Codex and Claude Code CLI sessions in iTerm2.

## Examples

These examples show representative final output after the complete pipeline.
The cleanup model remains conservative, so ordinary prose may receive slightly
different punctuation when more than one rendering is valid.

### Cleanup and self-correction

| Spoken dictation | Final text |
| --- | --- |
| `um tomorrow i want to send the onboarding guide to the sales team i mean the support team` | `Tomorrow, I want to send the onboarding guide to the support team.` |
| `are you available friday at three no actually four` | `Are you available Friday at four?` |
| `we should ship friday i mean we should ship monday after the release review` | `We should ship Monday after the release review.` |

Clear replacements keep only the speaker's final intent. If a correction is
ambiguous or the repair phrase is being quoted or discussed, the source is
preserved instead of being destructively guessed.

### Inline editing and formatting

| Spoken dictation | Result |
| --- | --- |
| `the old meeting is friday delete the last sentence the new meeting is monday` | Removes the preceding Friday sentence and keeps the Monday sentence. |
| `keep this extra delete the last word` | Removes `extra`. |
| `first topic new paragraph second topic` | Inserts a blank line between the two topics. |
| `the priorities are speed privacy and accuracy make those a numbered list` | Preserves the introduction and formats the three priorities as a numbered list. |
| `scratch that` / `never mind` / `undo that` | Discards only the nearest clear abandoned thought. |

The preprocessor recognizes a deliberately finite set of nearby, reversible
edits. Ambiguous scope is preserved or handed to Qwen rather than guessed.
See [Inline commands and snippets](INLINE_COMMANDS_AND_SNIPPETS.md) for the
complete command table and behavior.

### Exact snippets

After defining a snippet in [config/snippets.json](config/snippets.json), a
spoken phrase can insert exact text:

```json
{
  "id": "EMAIL_SIGNATURE",
  "triggers": ["insert my email signature"],
  "text": "Best,\nYour Name",
  "consume_trailing_punctuation": true
}
```

| Spoken dictation | Final text |
| --- | --- |
| `please reply and insert my email signature` | `Please reply and Best,` followed by `Your Name` on the next line. |
| `open slash goal and continue` | Can insert an exact `/goal` command when a matching snippet is configured. |
| `insert my booking link` | Can insert an exact URL without allowing Qwen to rewrite it. |

Snippet expansions can contain multiple lines, URLs, punctuation, commands, or
standard text. Qwen sees only protected, checksummed placeholders—not the
expansion itself. Post-AI reconstructs the original snippet slots, validates
their structure, expands the configured text exactly, and can recover a moved,
dropped, or final snippet from redundant segment metadata.

### Optional iTerm2 file references

The opt-in [iTerm2 file-reference plugin](plugins/iterm_file_references/README.md)
adds deterministic file lookup for local Codex and Claude Code CLI sessions in
iTerm2 on macOS.

| Spoken dictation | Example result |
| --- | --- |
| `read at file readme dot markdown` | `Read @README.md` |
| `read add file snippets dot json` | `Read @dictation/spokenly/config/snippets.json` when that is the selected project match. |
| `mention file pre AI dot pie` | `@scripts/pre_ai.py` |
| `inspect at file server slash config dot pie` | `@server/config.py` |
| `review at file button dot tee ess ex` | A verified path such as `@../../src/components/Button.tsx` from a nested CWD. |
| `read at file foo underscore bar dot pie` | Selects `foo_bar.py` when both underscore and dash variants exist. |

The plugin:

- Detects the exact focused iTerm2 window, tab, and split pane, including setups
  with several simultaneous terminal sessions.
- Binds the focused foreground process to its owning Codex or Claude Code CLI
  process and discovers that session's Git working tree or linked worktree.
- Searches tracked, untracked non-ignored, and individually ignored files while
  avoiding recursively indexed ignored directories.
- Prefers candidates beneath the active harness working directory. Duplicate
  names use the first deterministic Git-enumerated result unless spoken parent
  directories identify another match.
- Understands natural extension names, spelled letters and digits, compound
  suffixes, omitted dashes and underscores, and explicit `dash`, `hyphen`, or
  `underscore` disambiguation.
- Treats `add file` as a common transcription of `at file` and also tolerates a
  missing word boundary such as `at filesnippets.json`.
- Renders the inserted reference relative to the foreground process's OS CWD
  and verifies that it resolves back to the same canonical file.
- Revalidates the pane, process, CWD, worktree, and file after AI cleanup. Any
  plugin failure restores safe transcript text and never blocks dictation.

The core setup stays portable: this integration is disabled by default and
loads only after explicit environment opt-in and runtime validation. See the
plugin README for its supported environment, installation, diagnostics, and
known CWD boundary.

## How the pipeline works

```text
Spokenly
  -> NVIDIA Parakeet Unified EN 0.6B
  -> scripts/pre_ai.py
       - applies safe inline editing commands
       - protects snippet triggers with tokens
       - optionally loads explicitly enabled platform plugins
  -> Qwen 3.5 9B through Ollama
       - cleans and formats the transcript
  -> scripts/post_ai.py
       - restores snippet placement and expands snippets exactly
       - strips trailing whitespace before insertion
  -> active application
```

The deterministic processors handle operations that should not depend on a
language model. Qwen handles grammar, capitalization, number formatting, email
layout, recognition repair, list segmentation, and contextual decisions about
self-corrections. Protected segment boundaries prevent it from relocating
snippet slots or adding text outside the transcript structure.

## Safety and portability

- The processors have no network access and never execute transcript text as
  shell code.
- Snippet expansions are JSON data, not executable commands.
- Unknown, malformed, duplicated, conflicting, or unframed protected tokens
  are rejected instead of being guessed.
- Model-generated text outside protected transcript segments is rejected.
- Any unresolved internal command token causes post-processing to fail rather
  than paste control syntax into the active application.
- A missing snippet file disables snippets. Invalid snippet JSON preserves the
  original transcript instead of inserting a partially transformed result.
- The core scripts remain portable and load no platform integration by default.
  Optional plugins require an explicit environment opt-in and validate their
  own runtime prerequisites before transforming text.

Dictionary biasing is intentionally out of scope for now. Parakeet remains the
speech model, and no list of speculative misrecognition variants is maintained.

## Setup and verification

Follow [SETUP.md](SETUP.md) for complete installation, Spokenly configuration,
model setup, verification, and troubleshooting.

Run the complete local regression suite from the repository root:

```bash
python3 -m unittest discover -s dictation/spokenly/tests -v
```

## Project map

- [SETUP.md](SETUP.md) — installation, Spokenly configuration, verification, and troubleshooting
- [prompts/qwen-prompt.md](prompts/qwen-prompt.md) — the complete prompt to paste into Spokenly
- [ollama/Modelfile.spokenly-qwen9b](ollama/Modelfile.spokenly-qwen9b) — the derived Ollama model configuration
- [INLINE_COMMANDS_AND_SNIPPETS.md](INLINE_COMMANDS_AND_SNIPPETS.md) — supported commands, snippets, and safety behavior
- [config/snippets.json](config/snippets.json) — local snippet definitions (empty by default)
- [config/snippets.example.json](config/snippets.example.json) — example snippet definitions
- [scripts/pre_ai.sh](scripts/pre_ai.sh) — portable Bash Pre-AI entry point
- [scripts/post_ai.sh](scripts/post_ai.sh) — portable Bash Post-AI entry point
- [plugins/iterm_file_references](plugins/iterm_file_references/README.md) — optional macOS/iTerm2 file references for local Codex and Claude Code panes
- [tests/test_processors.py](tests/test_processors.py) — regression tests for both processors

## Upstream references

- [Spokenly Bash Scripts](https://spokenly.app/docs/modes/bash-scripts)
- [Spokenly Modes](https://spokenly.app/docs/modes)
- [Spokenly Word Replacements](https://spokenly.app/docs/word-replacements)
- [Ollama Modelfile reference](https://docs.ollama.com/modelfile)
