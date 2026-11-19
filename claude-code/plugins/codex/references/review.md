# Review and recheck prompt templates

review-codex composes one of these two prompts, fills the bracketed parts from the repo and
conversation, and sends it through the bridge (or to the fallback subagent). Keep each prompt
self-contained: the reviewer has no context from this session.

## Review template

```
You are reviewing code changes in this repository. Review only; do not modify files, run
formatters, or install dependencies, even if a fix looks obvious.

Target: [the working tree | the range <base>..<head> via `git diff <base>..<head>` | focus: <x>]
What the change is for: [one or two sentences from the conversation or commit messages]
Areas that matter most: [money, auth and permissions, data integrity, concurrency, tenant
isolation, migrations — only those the diff touches]

Report only these severities:
- P0: blocks release — data loss or corruption, money moved wrongly, auth or permission
  bypass, a crash or broken core flow, a security hole.
- P1: must fix before merge — a real bug a user will hit, a missed case in a changed flow, a
  regression of existing behaviour.
Do not report style, naming, formatting, speculative or theoretical issues, refactors, or
anything in code the change did not touch, unless it breaks because of the change.

List every P0 and P1 you find in this single pass; there will be no second review round.
For each finding give:
- id (F1, F2, ...), severity, file:line;
- what breaks, for whom, in one or two sentences;
- evidence: a concrete reproduction (input or steps and the wrong result), or the test that
  would fail (name it and say what it asserts), or the exact lines that prove it;
- if you cannot give evidence, label the finding UNPROVEN.
If you find nothing at P0 or P1, say "No P0 or P1 findings" and stop.
```

## Recheck template

```
You are rechecking specific findings from an earlier review in this repository, in a fresh
session. Review only; do not modify files, run formatters, or install dependencies.

Diff of the fixes: `git diff <base>..<head>` [or the working tree]
For each finding below you get the original finding and the author's evidence. Judge the
evidence and the code, not any argument.

[F1] <original finding text>
Evidence: <the test command, its failing output before the fix and passing output after> |
<dismissal evidence: file:line, or the test that could not be made to fail>
[F2] ...

For each finding answer RESOLVED, STILL OPEN or NOT REPRODUCED, with one line of evidence
(file:line or the test). Raise a new finding only if it is P0, with the same evidence rules.
Do not raise P1 or lower findings in a recheck.
```
