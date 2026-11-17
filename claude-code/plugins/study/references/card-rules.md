# Card rules

Cards target what the learner missed or got wrong in this session, so each one fixes a real gap rather than restating the chapter.

## Source fidelity

1. **Use only what the pages state.** No outside facts, no completion of fragmentary text. A card that adds facts teaches something the learner cannot check against the book.
2. **Every card has `source` and `quote`.** `source` is chapter and page, or `sec. <N> <title>` for an EPUB. `quote` is the exact text from that place that supports the answer: one short span, or several joined with ` … ` when the answer has parts. Copy it as printed, but join words split by a line-break hyphen and remove soft hyphens. If no span supports it, drop the card.
3. **Zero cards is fine.** A session with no real gaps produces no cards and no cards file.

## Choosing the type

- **cloze** for numbers, dates, names, terms inside a definition, and lists that form one concept (`{{c1::...}}`, `{{c2::...}}` for each item). Never put unrelated facts in one cloze card; split them.
- **basic** for why and how questions, comparisons, cause and effect, and processes with reasoning. If the answer is a single word or number, use cloze instead.

## Writing the card

1. **One idea per card**, understandable without reading another card.
2. **Prefer application and discrimination over definitions:** "When would X fail?" or "X or Y: which applies here, and why?" teaches more than "What is X?".
3. **Word the front differently from the book's sentence** where you can do so without changing the meaning, so the card tests recall and not phrase matching.
4. **`extra` on a cloze card** gives context from the same pages ("one of the three causes the chapter lists"), never a bare label such as "Date" or "Term", and never outside knowledge.
5. **Formatting:** HTML only (`<b>`, `<i>`, `<br>`); no raw newlines inside a field. Math as `\( ... \)`.
6. **Tags:** 1 to 3 lowercase hyphenated topic words.
7. **`gap`:** one line naming the missed or wrong point the card fixes. It is kept in the file, not sent to Anki.

## Cards file

The values below show the shape only; the book and quotes are placeholders.

```json
{
  "book": "Example Book",
  "deck": "Books::Example Book",
  "cards": [
    {"type": "basic",
     "front": "Why can a former leader still accept writes after failover?",
     "back": "It may not know it was replaced, so two nodes believe they are leader (split brain).",
     "source": "ch. 5, p. 157",
     "quote": "two nodes both believe that they are the leader",
     "gap": "missed: split brain during failover",
     "tags": ["replication", "failover"],
     "approved": false},
    {"type": "cloze",
     "text": "Single-leader replication sends every write through the {{c1::leader}}.",
     "extra": "One of the three replication approaches the chapter compares",
     "source": "ch. 5, p. 152",
     "quote": "all writes are sent to the leader",
     "gap": "partly: thought any replica accepts writes",
     "tags": ["replication"],
     "approved": false}
  ]
}
```

`deck` is optional. Each card's identity in Anki comes from the book, source and content, so pushing the same file twice adds nothing new, and an edited card becomes a new note. Edit cards that are already pushed in Anki itself.
