# Fully local Spokenly setup for macOS

This guide configures Spokenly with Parakeet for transcription, a safe Pre-AI
processor for inline commands, Qwen through Ollama for cleanup, and a Post-AI
processor for exact snippets.

Spokenly documents this order as Pre-AI Script → AI Instructions → Post-AI
Script. Each script reads stdin, writes stdout, and must finish within 30
seconds. Use Spokenly's macOS sideload build for scripts that access repository
files or local processes; the App Store build is sandboxed.

The tested setup uses an Apple M3 Max and macOS Tahoe. Other Apple Silicon Macs
should work, with performance depending on available unified memory.

## 1. Install the local speech model

Install Spokenly, grant microphone and accessibility permissions, then download:

```text
NVIDIA Parakeet Unified EN 0.6B
```

Parakeet performs transcription only. Qwen and the scripts handle subsequent
cleanup, commands, and snippets.

## 2. Install Ollama and Qwen

Install and open the Ollama macOS app. Enable Ollama under **System Settings →
General → Login Items & Extensions → Allow in the Background**.

Verify the local server:

```bash
curl http://localhost:11434/api/tags
```

Download and test Qwen:

```bash
ollama pull qwen3.5:9b
ollama run qwen3.5:9b "Return exactly the word READY."
```

The first request is slower because the model must load into memory.

## 3. Create the derived Qwen model

From the repository root:

```bash
ollama stop spokenly-qwen9b
ollama rm spokenly-qwen9b
ollama create spokenly-qwen9b -f dictation/spokenly/ollama/Modelfile.spokenly-qwen9b
ollama show --modelfile spokenly-qwen9b
```

If the model does not exist yet, `ollama stop` or `ollama rm` may report an
error; continue with `ollama create`.

The profile uses:

```text
num_ctx: 32768
num_predict: 16384
temperature: 0.0
top_p: 0.8
top_k: 20
min_p: 0.0
repeat_penalty: 1.0
```

The 32K context accommodates the prompt, a long source transcript, and a cleaned
output. It consumes more memory than a smaller context. `Reasoning: None` is set
in Spokenly rather than the Modelfile.

## 4. Configure Ollama residency

Recommended macOS login-session settings:

```bash
launchctl setenv OLLAMA_KEEP_ALIVE "10m"
launchctl setenv OLLAMA_MAX_LOADED_MODELS "1"
launchctl setenv OLLAMA_NUM_PARALLEL "1"
```

Quit and reopen Ollama afterward. These settings keep Qwen warm for nearby
dictations while limiting concurrent memory use.

Inspect or unload the model with:

```bash
ollama ps
ollama stop spokenly-qwen9b
```

`ollama ps` lists resident models, not individual dictation sessions.

## 5. Configure snippets

Copy desired examples from [config/snippets.example.json](config/snippets.example.json)
into [config/snippets.json](config/snippets.json), then replace the sample text.
Read [INLINE_COMMANDS_AND_SNIPPETS.md](INLINE_COMMANDS_AND_SNIPPETS.md) before
choosing trigger phrases.

Leave the `snippets` array empty if snippets are not needed yet.

## 6. Configure the Spokenly mode

Create a mode named `Clean Local`:

| Setting | Value |
| --- | --- |
| Transcription model | NVIDIA Parakeet Unified EN 0.6B |
| Text provider | OpenAI-compatible or Custom |
| Base URL | `http://localhost:11434/v1` |
| API key | `ollama` |
| Text model | `spokenly-qwen9b` |
| Reasoning | **None** |
| Agentic Actions | Off |
| Focused-app context | Off initially |
| Clipboard context | Off |
| Cursor context | Off initially |
| Browser URL context | Off |
| Smart Spacing | On |
| Smart Paragraphs | Off |
| Output action | Auto-insert |

Smart Paragraphs remains off because Qwen and explicit paragraph directives
already control paragraph structure.

Paste the code block from [prompts/clean-local.md](prompts/clean-local.md) into
the mode's **AI Instructions** field.

## 7. Configure the Pre-AI script

Make the scripts executable once:

```bash
chmod +x dictation/spokenly/scripts/pre_ai.py \
  dictation/spokenly/scripts/post_ai.py \
  dictation/spokenly/scripts/pre_ai.sh \
  dictation/spokenly/scripts/post_ai.sh
```

In Spokenly's Pre-AI Script field, use this wrapper with the absolute path to
your checkout:

```bash
#!/usr/bin/env bash
exec "/absolute/path/to/agentic-coding/dictation/spokenly/scripts/pre_ai.sh"
```

The script reads Spokenly's raw transcript from standard input and writes the
transformed transcript to standard output.

It deterministically handles high-confidence operations:

- deleting the previous word, clearly bounded phrase, or sentence
- `scratch that`, `never mind`, and similar immediate discards
- new lines and new paragraphs
- detecting list requests and passing authoritative tokens to Qwen
- detecting likely self-corrections and passing conservative tokens to Qwen
- protecting snippet triggers from Qwen

Ambiguous deletions are not performed destructively. They are delegated to Qwen
with a bounded control token. On any script/configuration error, the processor
fails open and returns the original transcript.

## 8. Configure the Post-AI script

In Spokenly's Post-AI Script field, use:

```bash
#!/usr/bin/env bash
exec "/absolute/path/to/agentic-coding/dictation/spokenly/scripts/post_ai.sh"
```

This performs exact expansion after Qwen. It does not rewrite any other text.
It reconstructs snippets between protected numbered transcript segments. Each
following segment redundantly records the preceding snippet, so a standalone
snippet token moved or dropped by Qwen is restored to its original position. It
fails closed on missing segment metadata, conflicting, duplicated, unknown, or
malformed structural tokens, text outside the protected segments, or leaked
command tokens. Finally, it strips trailing whitespace so an inferred Return
cannot submit or execute the inserted text.

## 9. Run local tests

From the repository root:

```bash
python3 -m unittest discover -s dictation/spokenly/tests -v
```

Test preprocessing directly:

```bash
printf '%s' 'The old plan is Friday. Delete the last sentence. The new plan is Monday. New paragraph. The priorities are speed, privacy, and accuracy. Make those a numbered list.' \
  | dictation/spokenly/scripts/pre_ai.sh
```

Expected characteristics:

- the Friday sentence is absent
- a blank line appears before the priorities
- a numbered-list control token follows the enumeration

## 10. End-to-end acceptance test

Dictate:

```text
Hi Maria. I wanted to schedule the product review for Thursday at 2. I mean Friday at 3. The original agenda includes pricing and customer support. Delete the last sentence. The revised agenda includes onboarding, reporting, and integrations. New paragraph. The main priorities are reliability, ease of use, and performance. Make those a numbered list. What should we prepare before the meeting? Best, Taylor.
```

Expected final output:

```text
Hi Maria,

I wanted to schedule the product review for Friday at 3. The revised agenda includes onboarding, reporting, and integrations.

The main priorities are:

1. Reliability
2. Ease of use
3. Performance

What should we prepare before the meeting?

Best,
Taylor
```

For snippet testing, add a non-sensitive snippet and dictate its exact trigger.
Confirm the trigger is absent and the saved expansion is reproduced exactly.

## 11. Exact Local mode

Create a second mode named `Exact Local` for code, shell commands, URLs, paths,
and identifiers:

| Setting | Value |
| --- | --- |
| Transcription model | Parakeet Unified |
| Text model | None |
| AI Instructions | Blank |
| Pre/Post-AI scripts | Off |
| Smart Spacing | On |
| Smart Paragraphs | Off |
| Agentic Actions | Off |

This avoids semantic interpretation when literal fidelity matters most.

## 12. Enable offline enforcement

After verifying the mode:

1. Confirm Parakeet and Qwen are downloaded.
2. Confirm Spokenly can reach `localhost`.
3. Disable all cloud fallbacks.
4. Enable Spokenly's Local Only Mode.
5. Turn off Wi-Fi and repeat a dictation and snippet test.

## 13. Troubleshooting

Check the Ollama server and resident models:

```bash
curl http://localhost:11434/api/tags
ollama ps
```

Inspect the server log:

```bash
tail -f ~/.ollama/logs/server.log
```

Reset a stuck model:

```bash
ollama stop spokenly-qwen9b
```

Common failure boundaries:

- Wrong raw words: usually Parakeet recognition; Qwen can repair only obvious contextual errors.
- Correct Pre-AI output but wrong final prose: Qwen prompt/model behavior.
- Missing or altered snippet/segment token: confirm the protected-structure section is in the AI prompt.
- Token remains after final output: confirm the Post-AI script and snippet ID are configured.
- First request is slow: expected Qwen cold load; later requests within keep-alive should be faster.
- High memory while loaded: expected model weights plus the 32K context cache; unload with `ollama stop`.

## Current limitations

- There is no true Parakeet dictionary biasing in this package.
- Natural-language command parsing cannot safely cover every possible phrase.
- The finite command allowlist favors preserving text over risky deletion.
- Qwen is probabilistic and may not match a purpose-built dictation service on every input.
- Snippet triggers are exact case-insensitive phrases; use distinctive wording to prevent accidental expansion.

## References

- [Spokenly Bash Scripts](https://spokenly.app/docs/modes/bash-scripts)
- [Spokenly Modes](https://spokenly.app/docs/modes)
- [Ollama Modelfile reference](https://docs.ollama.com/modelfile)
