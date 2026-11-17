# study

Study a book, paper or lecture deck with Claude as a coach. You read a few pages and write down what you remember. Claude reads the same pages, tells you what you recalled, missed or got wrong with page references, asks a few follow-up questions, and drafts flashcards for the gaps. Approved cards go straight into Anki.

## What you need

- Anki desktop, open while you study.
- The AnkiConnect add-on: in Anki, open Tools > Add-ons > Get Add-ons, enter `2055492159`, then restart Anki.
- The book as a PDF or EPUB file.
- Python 3 (the helper script uses only the standard library).

## Start a session

```text
/study:study-session ~/Books/ddia.pdf pages 150-160
```

Run it with no arguments to continue a book you studied before.

## How a session goes

1. If Anki has cards due for this book, Claude suggests reviewing them first.
2. On a new book you set 3 outcomes and 5 questions of your own.
3. For each chunk of 5 to 10 pages: you read, predict how much you will remember, then write what you remember and explain the main idea in your own words. Claude grades it against the pages and asks 2 or 3 questions.
4. At the end you keep 2 to 5 notes in your own words. Claude drafts up to 8 cards for what you missed; you approve, edit or drop each one, and the approved ones go to Anki.

Claude does not summarize pages before you have read and recalled them. Every grade, question and card cites the page it comes from.

## Where things are saved

A session saves its work in four places:

- `study/<book>.md` in your working folder: outcomes, questions, and a line per chunk with your prediction, score and gaps. This is how the next session picks up.
- `study/cards/<book>-<date>.json`: the cards from each session. Pushing the same file twice adds nothing new.
- Your permanent notes go wherever your project's instructions say; if they say nothing, Claude asks once and remembers the answer in the study log.
- Cards go to the Anki deck `Books::<book title>`, tagged `study`.

## Helper script

`scripts/study.py` does the parts that must be exact: reading EPUB chapters in order, checking cards files, and talking to AnkiConnect. Run `python3 scripts/study.py -h` for its commands, and `python3 -m unittest discover -s tests` from this folder for its tests.
