# Local Spokenly dictation

This directory contains a reproducible, fully local dictation setup for macOS:

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

After downloading the models, the pipeline can run offline without API fees,
subscriptions, word limits, or transcription quotas.

## Files

- [SETUP.md](SETUP.md) — installation, Spokenly configuration, verification, and troubleshooting
- [prompts/clean-local.md](prompts/clean-local.md) — the prompt to paste into Spokenly
- [ollama/Modelfile.spokenly-qwen9b](ollama/Modelfile.spokenly-qwen9b) — the derived Ollama model configuration
- [INLINE_COMMANDS_AND_SNIPPETS.md](INLINE_COMMANDS_AND_SNIPPETS.md) — supported commands, snippets, and safety behavior
- [config/snippets.json](config/snippets.json) — local snippet definitions (empty by default)
- [config/snippets.example.json](config/snippets.example.json) — example snippet definitions
- [scripts/pre_ai.sh](scripts/pre_ai.sh) — portable Bash Pre-AI entry point
- [scripts/post_ai.sh](scripts/post_ai.sh) — portable Bash Post-AI entry point
- [plugins/iterm_file_references](plugins/iterm_file_references/README.md) — optional macOS/iTerm2 file references for local Codex and Claude Code panes
- [tests/test_processors.py](tests/test_processors.py) — regression tests for both processors

The core scripts remain portable and load no platform integration by default.
Optional plugins require an explicit environment opt-in and validate their own
runtime prerequisites before transforming text.

Dictionary biasing is intentionally out of scope for now. Parakeet remains the
speech model, and no list of speculative misrecognition variants is maintained.

## Quick verification

```bash
python3 -m unittest discover -s dictation/spokenly/tests -v
```

See [SETUP.md](SETUP.md) for the complete setup.

## Upstream references

- [Spokenly Bash Scripts](https://spokenly.app/docs/modes/bash-scripts)
- [Spokenly Modes](https://spokenly.app/docs/modes)
- [Spokenly Word Replacements](https://spokenly.app/docs/word-replacements)
- [Ollama Modelfile reference](https://docs.ollama.com/modelfile)
