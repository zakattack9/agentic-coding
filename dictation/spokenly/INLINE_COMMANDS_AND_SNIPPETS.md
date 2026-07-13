# ParaQwen Dictation: inline commands and snippets

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
| Delete/remove the last word; scratch word | Deletes the immediately preceding word |
| Delete/remove the last phrase | Deletes a clearly comma-, colon-, or semicolon-delimited phrase; otherwise Qwen receives a control token |
| Delete/remove the last sentence | Deletes the nearest punctuated sentence; otherwise Qwen receives a control token |
| Scratch that / delete that / never mind / undo that | Discards the nearest clear thought or asks Qwen to resolve ambiguous scope |
| New line / new paragraph | Inserts the requested break deterministically |
| Make/format those as a list | Gives Qwen an explicit protected list-formatting command |
| Number those items | Gives Qwen an explicit numbered-list command |
| I mean / I meant / sorry, I meant / no, actually / no, wait / or rather / make that / I should say / what I meant was / let me rephrase / let me start over | Creates a typed, numbered, bounded repair region when the local relationship is clear |

The script avoids acting when a command is quoted, dictated literally, reported,
or obviously being discussed. Overlapping correction cues become one ordered
chain region; unrelated regions keep distinct source positions. Conservative
cue-free parallel restatements may also be framed. Additive clarification,
targetless cues, weak similarity, and other ambiguity are explicitly preserved
rather than destructively guessed.

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

When a trigger is recognized, the preprocessor replaces it with a position-specific, checksummed token such as `[[SPK_SNIPPET_EMAIL_SIGNATURE__1__A1B2C3D4]]`. It also wraps every editable span before, between, and after snippets in numbered `SPK_SEGMENT` boundaries. The segment following a snippet redundantly records its identity and checksum in a `START_AFTER` marker. Qwen must preserve these structural tokens. The postprocessor verifies the metadata, reconstructs the numbered spans and snippet slots in their original order, then inserts the exact configured text. A snippet moved to the end or even dropped by Qwen is therefore restored from the segment metadata, and a final snippet is followed by a protected empty segment so it cannot be lost accidentally.

Qwen never receives the expansion itself, so it cannot rewrite a signature, URL, disclaimer, command, or address. A missing standalone snippet token is recovered from redundant segment metadata. Missing or malformed segment metadata, conflicting or duplicated tokens, and unframed tokens fail closed instead of producing damaged text.

## Script safety behavior

- A missing snippet file disables snippets. Invalid JSON makes the preprocessor report an error and preserve the original transcript.
- An unknown snippet token causes the postprocessor to fail instead of guessing.
- Missing or malformed segment metadata and duplicated, conflicting, or malformed snippet tokens cause the postprocessor to fail closed.
- Model-generated text outside protected transcript segments causes the postprocessor to fail closed.
- Any command token left behind by Qwen also causes the postprocessor to fail. This prevents internal control text from being pasted into an application.
- The postprocessor removes all trailing whitespace, including newlines, so auto-inserted output cannot submit a form or execute a command by carrying a final Return.
- The processors have no network access and never execute transcript text as shell code.
- Snippet expansions are data loaded from JSON, not commands.

## Optional plugins

The core processors are platform-independent and do not import platform plugins
unless explicitly enabled. The
[iTerm2 file-reference plugin](plugins/iterm_file_references/README.md) is an
opt-in macOS extension for local Codex and Claude Code CLI panes. It reuses the
same protected segment protocol for dynamic `@path` expansions, but resolves
paths deterministically from the focused iTerm2 session and active Git worktree.

Qwen never selects, sees, repairs, or rewrites a resolved path. Pre-AI stores it
in private per-session state, and Post-AI verifies the same pane, process, CWD,
worktree, and canonical file before insertion. Ambiguous names are left alone;
context or structural failures after protection fail closed.

## Direct tests

Test preprocessing:

```bash
printf '%s' 'The old meeting is Friday. Delete the last sentence. The new meeting is Monday. New paragraph. Insert my email signature.' \
  | dictation/spokenly/scripts/pre_ai.sh
```

Test a protected snippet round trip without Qwen by piping through both scripts:

```bash
printf '%s' 'Message body. Insert my email signature.' \
  | dictation/spokenly/scripts/pre_ai.sh \
  | dictation/spokenly/scripts/post_ai.sh
```

Use Spokenly's **Test Script** button to confirm the actual app environment can access the repository scripts and configuration.

## Repair validation and responsibility boundary

Qwen still handles grammar, capitalization, number formatting, email layout,
list item segmentation, and the precise reparandum inside a bounded
model-assisted region. It receives each region's cues in order and may retain
only later source wording for a confirmed repair; it may not invent a
replacement or move content across boundaries.

Post-AI validates region identity/order/checksums, cue consumption, literal
shields, snippet/file-reference structure, protected URLs, emails, commands,
references, paths, filenames, identifiers, hashes, versions, dates, times and
numbers, later-source grounding, and meaningful prose outside repairs. A
failure discards the model result and silently reconstructs safe deterministic
source text with exact expansions. There is one Qwen pass per dictation,
Reasoning is **None**, and no retry or background correction occurs. All final
branches remove trailing whitespace.

Backtracking sees only the current transcript. It cannot change earlier text in
the application and has no acoustic pause or word-timestamp awareness.
