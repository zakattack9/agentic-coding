---
name: study-session
description: Runs a study session on a book, chapter, paper or lecture deck (PDF or EPUB) with retrieval practice. The learner reads a few pages, recalls them from memory, the AI grades that recall against the actual pages, asks follow-up questions, and drafts at most 8 cited flashcards aimed at what was missed. Cards reach Anki through AnkiConnect only after the learner approves each one. Use when the user says "study session", "let's study chapter 3", "quiz me on what I just read", "I read pages 40-52", "make Anki cards from my reading", "continue studying <book>". It does NOT summarize a book the learner has not read, and it does NOT bulk-generate a deck from a whole book with no recall step.
argument-hint: "[book file] [pages or chapter]"
allowed-tools: Bash(python3 *), Read, Write, Edit, Glob, AskUserQuestion
disable-model-invocation: true
model: opus
effort: high
---

# study-session

Coach one study session: the learner reads, recalls from memory, and gets graded against the source. Only proven recall counts as progress. Cards cover what the learner missed, cite the page, and go to Anki only after the learner approves them.

Anki status (checked at load):
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/study.py" probe`

Arguments: $ARGUMENTS

## Ground rules

1. **The learner's attempt comes first.** Do not summarize, outline or explain pages the learner has not yet read and recalled. Retrieval only strengthens memory when the learner does the retrieving; a summary beforehand turns recall into recognition.
2. **Every claim you make about the book cites it.** Use book, chapter and page (or EPUB section). If you cannot find the support on the page, say so rather than filling in from general knowledge. The learner trusts the grade, so an invented "you missed X" teaches something false.
3. **Grade against the pages, not against your knowledge of the subject.** Read the pages before grading. Points the book does not make are not gaps.
4. **The learner's questions come before yours.** When setting guiding questions, ask for theirs first and add at most two.
5. **Nothing reaches Anki without approval.** Only cards marked `approved: true` in the cards file are pushed, and only after the learner has seen them.

## Files

- **Study log:** `study/<book-slug>.md` in the working directory, unless the project's instructions name another place. Read it at the start to resume and append to it as you go. On the first session, create it with a header holding the book title (as the learner names it, without the author), the slug (that title lowercased, with each run of other characters turned into one hyphen), the file path, the deck (`Books::<title>`), the citation format, and where permanent notes go. Every later step takes the title, slug and deck from this header, because the cards file's `book` and the `due` deck must match it exactly.
- **Cards file:** `study/cards/<book-slug>-<YYYY-MM-DD>.json`, checked and pushed by the script. A session with no cards writes no file.
- **Permanent notes:** wherever the project's instructions say, one Markdown file per note named after its claim, linked with the project's link style (`[[note-name]]` if it has none). Fields: claim, applies when, fails when, example, source, links. Write "not stated in the source" for a field the pages do not support rather than filling it from general knowledge.

## Reading the source

- **PDF:** use Read on the file with `pages` (at most 20 pages per call). Cite printed page numbers. On the first session, read one body page, compare its printed number with its file page, and record the offset (file page = printed page + offset) in the log header; front matter often has a different offset, so take it from body pages.
- **EPUB:** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/study.py" epub-toc <file>` lists sections in reading order with word counts; `epub-text <file> <N>` or `<N-M>` prints them. EPUBs have no page numbers, so cite `sec. <N> <section title>` wherever this skill says page.

Ask in plain text when the answer is free-form (outcomes, questions, a prediction, recall, notes). Use AskUserQuestion when the learner picks between options.

## Session flow

### 1. Start or resume

1. Find the book file and the study log. If the arguments do not name the book, check `study/` for logs and ask which to continue.
2. **Resumed book:** if Anki is reachable, run `study.py due "<deck from the log header>"`. If cards are due, suggest reviewing them in Anki first. Spaced review of old material beats reading new pages, so new reading waits until the learner has decided.
3. **First session on this book:** ask where permanent notes should go if the project's instructions do not say, write the log header, then ask for 3 outcomes (what the learner wants to be able to do after the book) and 5 of their own curiosity questions after a skim of the contents. Offer a 6-question baseline quiz drawn from the table of contents; record the score but do not reveal the answers, which would summarize the book before it is read. Skip the quiz if they decline.

### 2. Micro-loop (repeat per chunk of 5 to 10 pages, or one EPUB section of up to about 3,000 words)

1. **Set the chunk.** Agree on the pages or sections. Show the learner's open questions from the log and ask which 1 to 3 they are reading for (or a new one).
2. **The learner reads.** Wait. Do not read ahead aloud.
3. **Predict.** Ask how much they expect to recall, as a percentage.
4. **Recall.** The learner writes, book closed, everything they remember, then explains the main idea in their own words as if to a beginner. Accept rough notes or a voice transcript as they are.
5. **Grade.** Now read the pages. List the key points the agreed chunk makes (usually 4 to 10); text on a shared page that belongs to the next section is out of scope. Mark each one as recalled, partly recalled, missed, or wrong (a misconception), each with its page and a short quote. The score is the share of key points recalled, rounded to a whole percent, with partly recalled counting as half (so the count can end in .5). Show it next to their prediction; the gap is their calibration.
6. **Tutor.** Ask 2 or 3 questions in this order: recall of a missed point, application to a new case, transfer to something outside the book. Word them differently from the book's sentences, so the learner cannot answer by matching phrasing. Correct each answer, with a page cite.
7. **Log the loop:** date, pages, prediction, score, missed and wrong points with pages, and the learner's guiding questions with whether the pages answered them.

### 3. Close the session

1. **Permanent notes (up to 5; fewer is fine).** Ask which ideas from today the learner wants to keep. For each, the learner states the claim in their own words; help shape it into the note fields from the Files section and write it there.
2. **Cards (at most 8).** Read `${CLAUDE_PLUGIN_ROOT}/references/card-rules.md`, then draft cards for the wrong and missed points first (including those the tutor questions exposed), then partly recalled ones, stopping at 8. Never pad to reach 8. If there are no real gaps, say so and skip to step 5: no cards file, no push. Before showing a card, re-read its page and confirm its quote spans support every word of the answer. Write the cards file with `approved: false`.
3. **Approval.** Show the cards as a numbered list (front and back, or cloze text, plus source). Ask with AskUserQuestion: approve all, or approve with changes (the learner types edits or numbers to drop in "Other"). Apply edits, delete dropped cards from the file, set `approved: true` on the rest, and run `study.py check <cards file>` until it exits 0. If every card was dropped, delete the file and skip the push.
4. **Push.** Run `study.py push <cards file>`.
   - Exit 0: report added and skipped counts and the deck name. Skipped cards were already in Anki from an earlier push.
   - Exit 2: the file is invalid; fix what it lists and rerun.
   - Exit 3: Anki is closed, AnkiConnect is missing, or a note type is missing. Tell the learner what the message says (install AnkiConnect with add-on code 2055492159, then restart Anki), keep the cards file, and push again once it is fixed.
   - Exit 4: some cards failed; show which and why.
5. **Log the close:** cards added and skipped (the card ids from the `push` output), notes written, and where to start next time.

### 4. Weekly (when the learner asks, or 7 days after the last weekly entry in the log)

Run a short mixed quiz across the books in `study/` (interleaving), have the learner predict their score first, and log prediction against result. Suggest a short synthesis note linking ideas across books.

## Output skeleton for a graded loop

```
<pages or sections> · predicted <p>% · scored <s>% (<n> of <m> key points)

Recalled:  <point> (<cite>)
Partly:    <point>: you had <what>, the book adds <what> (<cite>)
Missed:    <point> (<cite>, "<short quote>")
Wrong:     you said <claim>; the book says <claim> (<cite>, "<short quote>")

Questions:
1. <recall question>
2. <application question>
3. <transfer question>
```

Write one line per key point, repeating the label. Drop labels that have no entries. `<cite>` is `p. <x>` or `pp. <x>-<y>` for a PDF and `sec. <N> <title>` for an EPUB. Copy citations and quotes from the source you just read; never invent one.
