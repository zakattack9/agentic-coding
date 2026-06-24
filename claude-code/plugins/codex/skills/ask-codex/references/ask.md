# ask-codex — composing the question

## No-argument path — suggesting questions

Open one `AskUserQuestion` with **2–4** concrete, context-derived questions as options. Derive
them from what the conversation has been about — the file/feature in focus, a decision being
weighed, an error being chased. The tool auto-adds **"Other"** for a freeform question, so do
**not** add your own "Something else" option (it duplicates the built-in and burns a slot).

When the conversation is **sparse** — there is no real basis for repo-specific suggestions —
don't invent plausible-but-misleading questions. Instead ask the user to type the question
they want Codex to answer.

## Prompt template (fill, then pipe to the bridge on stdin)

```
You are answering a question as a second-opinion model, with read-only access to this
repository (<repo name / cwd>). Ground your answer in the actual code where relevant — read
the files you need.

Question: <the user's question, composed into a clear, self-contained ask>

<Optional context the user gave or the conversation established — the file/feature in focus,
the constraint, the approach being weighed. Keep it brief; rely on Codex reading the repo.>

Answer directly and concretely. If the answer depends on code, cite the file:line you relied
on. This is READ-ONLY: do not modify any files, run formatters, or install dependencies.
```

The free-form question can be an explanation ("how does X work"), a plan/approach review
("is this migration plan sound"), a repo question ("where is Y handled"), or an opinion on a
diff ("any problems with these changes") — one template covers all of them; shape the
`Question` line to fit.

## Surfacing

Surface Codex's answer verbatim and in full, then the session-id / diagnostic metadata block
from the shared rules. Don't summarize or paraphrase it.
