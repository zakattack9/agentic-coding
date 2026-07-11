# Inline commands and snippets

The mode uses a three-stage pipeline:

```text
Parakeet transcript
  -> pre_ai.py (safe commands and snippet protection)
  -> Qwen (semantic cleanup)
  -> post_ai.py (exact snippet expansion)
  -> inserted text
```

This follows Spokenly's documented script order. Scripts read stdin, print stdout, and must finish within 30 seconds. A non-zero exit shows stderr as an error instead of silently inserting a damaged result.

## Supported inline commands

The preprocessor deliberately recognizes a finite set of nearby, reversible transcript edits. Natural variants such as “please remove the previous sentence” are supported, but the parser is intentionally not a general command executor.

| Spoken command | Behavior |
| --- | --- |
| Delete/remove the last word | Deletes the immediately preceding word |
| Delete/remove the last phrase | Deletes a clearly comma-, colon-, or semicolon-delimited phrase; otherwise Qwen receives a control token |
| Delete/remove the last sentence | Deletes the nearest punctuated sentence; otherwise Qwen receives a control token |
| Scratch that / never mind / undo that | Discards the nearest clear thought or asks Qwen to resolve ambiguous scope |
| New line / new paragraph | Inserts the requested break deterministically |
| Make/format those as a list | Gives Qwen an explicit protected list-formatting command |
| Number those items | Gives Qwen an explicit numbered-list command |
| I mean / sorry, I meant / no, actually | Gives Qwen a conservative self-correction hint |

The script avoids acting when a command is obviously being discussed, as in “write the phrase delete the last sentence.” Ambiguous language is preserved or handed to Qwen rather than destructively guessed.

## Configure snippets

Copy the example once:

```bash
cp dictation/spokenly/config/snippets.example.json \
  dictation/spokenly/config/snippets.json
```

Edit `snippets.json` and use explicit spoken triggers:

```json
[
  {
    "id": "EMAIL_SIGNATURE",
    "triggers": ["insert my email signature"],
    "text": "Best,\nYour Name",
    "consume_trailing_punctuation": true
  }
]
```

Rules:

- IDs must begin with a letter and contain only uppercase letters, digits, and underscores.
- Triggers match case-insensitively and tolerate repeated spaces.
- Longer triggers are checked first.
- Every trigger must be unique and at least four characters.
- Prefer phrases such as “insert my booking link”; avoid common words such as “signature,” “address,” or “thanks.”
- Expansions may contain multiple lines, URLs, punctuation, or standard text.
- Set `consume_trailing_punctuation` to `true` for signatures, URLs, addresses, and other exact snippets when a period inferred after the spoken trigger should not be appended to the expansion. It defaults to `false`.

When a trigger is recognized, the preprocessor replaces it with an occurrence-specific token such as `[[SPK_SNIPPET_EMAIL_SIGNATURE__1]]`. Qwen must preserve that token. The postprocessor replaces it with the exact configured text. Qwen never receives the expansion itself, so it cannot rewrite a signature, URL, disclaimer, or address. If Qwen duplicates a token, the postprocessor stops instead of inserting the snippet twice.

## Script safety behavior

- A missing snippet file disables snippets. Invalid JSON makes the preprocessor report an error and preserve the original transcript.
- An unknown snippet token causes the postprocessor to fail instead of guessing.
- Any command token left behind by Qwen also causes the postprocessor to fail. This prevents internal control text from being pasted into an application.
- The processors have no network access and never execute transcript text as shell code.
- Snippet expansions are data loaded from JSON, not commands.

## Direct tests

Test preprocessing:

```bash
printf '%s' 'The old meeting is Friday. Delete the last sentence. The new meeting is Monday. New paragraph. Insert my email signature.' \
  | dictation/spokenly/scripts/pre_ai.sh
```

Test a protected snippet round trip without Qwen:

```bash
printf '%s' 'Message body. [[SPK_SNIPPET_EMAIL_SIGNATURE__1]]' \
  | dictation/spokenly/scripts/post_ai.sh
```

Use Spokenly's **Test Script** button to confirm the actual app environment can access the repository scripts and configuration.

## Responsibility boundary

Qwen still handles grammar, capitalization, number formatting, email layout,
recognition repair, list item segmentation, and deciding whether a hinted
self-correction is truly a replacement. Keeping semantic decisions out of the
regex parser avoids dangerously broad deletion behavior.
