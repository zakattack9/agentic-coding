#!/usr/bin/env python3
"""Deterministic helpers for the study-session skill: AnkiConnect probe, due count,
EPUB table of contents and text, card validation, and pushing approved cards.

Standard library only. Exit codes:
  0  ok
  1  usage or file error
  2  cards file invalid (every problem is printed)
  3  AnkiConnect unreachable, or a required note type or deck call failed
  4  some cards failed to add (the rest were added)
"""
import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import sys
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

ANKI_URL = os.environ.get("STUDY_ANKICONNECT_URL", "http://127.0.0.1:8765")
MAX_CARDS = 8
ID_TAG = "study-id::"
CARD_KEYS = {"type", "front", "back", "text", "extra", "source", "quote", "gap", "tags", "approved"}
TOP_KEYS = {"book", "deck", "cards"}
SCHEMA_HINT = (
    'expected {"book": str, "deck"?: str, "cards": [ {"type": "basic", "front": str, "back": str, '
    '"source": str, "quote": str, "gap"?: str, "tags"?: [str], "approved": bool} | '
    '{"type": "cloze", "text": "...{{c1::...}}...", "extra"?: str, "source": str, "quote": str, '
    '"gap"?: str, "tags"?: [str], "approved": bool} ]}'
)


class AnkiError(Exception):
    pass


# --------------------------------------------------------------------------- AnkiConnect

def anki(action, **params):
    body = json.dumps({"action": action, "version": 6, "params": params}).encode()
    req = urllib.request.Request(ANKI_URL, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AnkiError(f"AnkiConnect not reachable at {ANKI_URL} ({e})")
    if out.get("error"):
        raise AnkiError(f"AnkiConnect {action}: {out['error']}")
    return out.get("result")


def cmd_probe(_a):
    try:
        v = anki("version")
        print(f"ankiconnect: ok (api {v})")
    except AnkiError as e:
        print(f"ankiconnect: missing. Open Anki with the AnkiConnect add-on (code 2055492159) installed. {e}")
    return 0


def cmd_due(a):
    try:
        due = anki("findCards", query=f'"deck:{a.deck}" is:due')
        new = anki("findCards", query=f'"deck:{a.deck}" is:new')
    except AnkiError as e:
        print(e, file=sys.stderr)
        return 3
    print(json.dumps({"deck": a.deck, "due": len(due or []), "new": len(new or [])}))
    return 0


# --------------------------------------------------------------------------- EPUB

_MARK = "\x00"


class _Text(HTMLParser):
    """HTML to plain text. A start tag whose id or name is in `anchors` drops a marker
    so one file can be split at table-of-contents fragments."""
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "blockquote", "pre", "dd", "dt"}

    def __init__(self, anchors=()):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.anchors = [], 0, set(anchors)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
            return
        for k, v in attrs:
            if k in ("id", "name") and v in self.anchors:
                self.parts.append(f"{_MARK}{v}{_MARK}")
                self.anchors.discard(v)
                break
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data.replace(_MARK, ""))

    @staticmethod
    def clean(t):
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()

    def pieces(self):
        """[(anchor or None, text)] in document order."""
        raw = "".join(self.parts).split(_MARK)
        out = [(None, self.clean(raw[0]))]
        for i in range(1, len(raw) - 1, 2):
            out.append((raw[i], self.clean(raw[i + 1])))
        return out


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _need(value, what):
    if value is None:
        raise ValueError(f"EPUB has no {what}")
    return value


def _toc(z, manifest, join):
    """Table of contents as [(file path, fragment or "", title)] in TOC order (EPUB 3 nav, else EPUB 2 NCX)."""
    entries = []
    nav = next((i for i in manifest.values() if "nav" in (i.get("properties") or "").split()), None)
    ncx = next((i for i in manifest.values() if i.get("media-type") == "application/x-dtbncx+xml"), None)
    if nav is not None:
        path = join(nav.get("href"))
        for a in _strip_ns(ET.fromstring(z.read(path))).iter("a"):
            href, _, frag = (a.get("href") or "").partition("#")
            if href:
                entries.append((posixpath.normpath(posixpath.join(posixpath.dirname(path), href)), frag,
                                " ".join("".join(a.itertext()).split())))
    elif ncx is not None:
        path = join(ncx.get("href"))
        for np in _strip_ns(ET.fromstring(z.read(path))).iter("navPoint"):
            label, content = np.find("navLabel/text"), np.find("content")
            if label is not None and content is not None:
                href, _, frag = content.get("src", "").partition("#")
                entries.append((posixpath.normpath(posixpath.join(posixpath.dirname(path), href)), frag,
                                " ".join((label.text or "").split())))
    return entries


def epub_sections(path):
    """Reading-order sections: [{"index", "href", "title", "text"}]. Files follow the spine; a file
    that holds several table-of-contents entries is split at their anchors. Empty sections are dropped."""
    with zipfile.ZipFile(path) as z:
        container = _strip_ns(ET.fromstring(z.read("META-INF/container.xml")))
        opf_path = _need(_need(container.find(".//rootfile"), "rootfile").get("full-path"), "package path")
        base = posixpath.dirname(opf_path)
        opf = _strip_ns(ET.fromstring(z.read(opf_path)))
        manifest = {i.get("id"): i for i in _need(opf.find("manifest"), "manifest")}
        join = lambda h: posixpath.normpath(posixpath.join(base, _need(h, "href")))
        toc = _toc(z, manifest, join)

        out = []
        for ref in _need(opf.find("spine"), "spine"):
            item = manifest.get(ref.get("idref"))
            if item is None:
                continue
            href = join(_need(item.get("href"), "href on a spine item"))
            file_title = next((t for h, f, t in toc if h == href and not f), None)
            frag_titles = {}
            for h, f, t in toc:
                if h == href and f:
                    frag_titles.setdefault(f, t)
            p = _Text(frag_titles)
            p.feed(z.read(href).decode("utf-8", "replace"))
            # A fragment the file never defines (often "#top") names the file's opening text.
            file_title = file_title or next((t for f, t in frag_titles.items() if f in p.anchors), None)
            for anchor, text in p.pieces():
                if not text:
                    continue
                title = frag_titles.get(anchor) if anchor else file_title
                title = title or next((ln for ln in text.splitlines() if ln.strip()), posixpath.basename(href))
                out.append({"index": len(out), "href": href + (f"#{anchor}" if anchor else ""), "title": title[:120], "text": text})
        return out


def cmd_epub_toc(a):
    try:
        for s in epub_sections(a.file):
            print(f"{s['index']:>3}  {len(s['text'].split()):>6} words  {s['title']}")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        print(f"cannot read EPUB: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_epub_text(a):
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", a.range)
    if not m:
        print("range must be N or N-M (section indexes from epub-toc)", file=sys.stderr)
        return 1
    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    try:
        secs = epub_sections(a.file)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        print(f"cannot read EPUB: {e}", file=sys.stderr)
        return 1
    for s in secs[lo:hi + 1]:
        print(f"=== [{s['index']}] {s['title']}\n{s['text']}\n")
    return 0


# --------------------------------------------------------------------------- cards

def _norm(s):
    return " ".join(str(s or "").split()).lower()


def card_id(book, card):
    """Identity from the source and the content, never the card's position in a run."""
    body = card.get("front", "") + "\x1f" + card.get("back", "") if card["type"] == "basic" else card.get("text", "")
    raw = "\x1e".join([_norm(book), _norm(card.get("source")), card["type"], _norm(body)])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def sanitize_tag(t):
    t = re.sub(r"\s+", "-", str(t).strip().lower())
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9:_-]", "", t)).strip("-")


def validate(doc, max_cards=MAX_CARDS):
    errs = []
    if not isinstance(doc, dict):
        return [f"top level must be an object; {SCHEMA_HINT}"]
    for k in set(doc) - TOP_KEYS:
        errs.append(f"unknown top-level key {k!r}")
    if not isinstance(doc.get("book"), str) or not doc["book"].strip():
        errs.append("book: required non-empty string")
    if "deck" in doc and (not isinstance(doc["deck"], str) or not doc["deck"].strip()):
        errs.append("deck: must be a non-empty string when given")
    cards = doc.get("cards")
    if not isinstance(cards, list) or not cards:
        errs.append("cards: required non-empty list")
        cards = []
    if len(cards) > max_cards:
        errs.append(f"cards: {len(cards)} cards, the limit is {max_cards} per session")
    seen = {}
    for i, c in enumerate(cards):
        w = f"cards[{i}]"
        if not isinstance(c, dict):
            errs.append(f"{w}: must be an object")
            continue
        for k in set(c) - CARD_KEYS:
            errs.append(f"{w}: unknown key {k!r}")
        t = c.get("type")
        if t == "basic":
            for k in ("front", "back"):
                if not isinstance(c.get(k), str) or not c[k].strip():
                    errs.append(f"{w}: {k} required for a basic card")
        elif t == "cloze":
            if not isinstance(c.get("text"), str) or not re.search(r"\{\{c\d+::.+?\}\}", c["text"]):
                errs.append(f"{w}: text must contain a cloze deletion like {{{{c1::answer}}}}")
        else:
            errs.append(f"{w}: type must be 'basic' or 'cloze'")
            continue
        for k in ("source", "quote"):
            if not isinstance(c.get(k), str) or not c[k].strip():
                errs.append(f"{w}: {k} required (every card cites where it came from)")
        if not isinstance(c.get("approved"), bool):
            errs.append(f"{w}: approved must be true or false")
        if "tags" in c and not (isinstance(c["tags"], list) and all(isinstance(x, str) for x in c["tags"])):
            errs.append(f"{w}: tags must be a list of strings")
        if isinstance(doc.get("book"), str) and not any(e.startswith(w + ":") for e in errs):
            cid = card_id(doc["book"], c)
            if cid in seen:
                errs.append(f"{w}: duplicate of cards[{seen[cid]}]")
            seen[cid] = i
    if errs:
        errs.append(SCHEMA_HINT)
    return errs


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read cards file: {e}")


def cmd_check(a):
    doc = load(a.cards)
    errs = validate(doc, a.max)
    if errs:
        print("\n".join(errs))
        return 2
    approved = [c for c in doc["cards"] if c["approved"]]
    print(json.dumps({"cards": len(doc["cards"]), "approved": len(approved),
                      "ids": [card_id(doc["book"], c) for c in doc["cards"]]}))
    return 0


def deck_for(doc):
    return doc.get("deck") or f"Books::{doc['book'].replace('::', ' ').strip()}"


def note_for(doc, deck, c):
    cite = f"<br><br><small>Source: {html.escape(doc['book'])}, {html.escape(c['source'])}</small>"
    tags = [sanitize_tag(t) for t in c.get("tags") or []] + ["study", ID_TAG + card_id(doc["book"], c)]
    if c["type"] == "basic":
        model, fields = "Basic", {"Front": c["front"], "Back": c["back"] + cite}
    else:
        model, fields = "Cloze", {"Text": c["text"], "Back Extra": (c.get("extra") or "") + cite}
    return {"deckName": deck, "modelName": model, "fields": fields, "tags": [t for t in tags if t],
            "options": {"allowDuplicate": True}}


def cmd_push(a):
    doc = load(a.cards)
    errs = validate(doc, a.max)
    if errs:
        print("\n".join(errs))
        return 2
    cards = [c for c in doc["cards"] if c["approved"]]
    if not cards:
        print(json.dumps({"added": 0, "skipped": 0, "failed": 0, "note": "no approved cards"}))
        return 0
    deck = deck_for(doc)
    try:
        models = set(anki("modelNames") or [])
        need = {"Basic" if c["type"] == "basic" else "Cloze" for c in cards}
        if need - models:
            print(f"Anki has no note type named {sorted(need - models)}; rename or add it, then push again.", file=sys.stderr)
            return 3
        anki("createDeck", deck=deck)
        added = skipped = failed = 0
        results = []
        for c in cards:
            cid = card_id(doc["book"], c)
            if anki("findNotes", query=f'"tag:{ID_TAG}{cid}"'):
                skipped += 1
                results.append({"id": cid, "status": "already in Anki"})
                continue
            try:
                nid = anki("addNote", note=note_for(doc, deck, c))
                added += 1
                results.append({"id": cid, "status": "added", "note": nid})
            except AnkiError as e:
                failed += 1
                results.append({"id": cid, "status": "failed", "error": str(e)})
    except AnkiError as e:
        print(e, file=sys.stderr)
        return 3
    print(json.dumps({"deck": deck, "added": added, "skipped": skipped, "failed": failed, "cards": results}))
    return 4 if failed else 0


# --------------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog="study.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="report whether AnkiConnect answers").set_defaults(fn=cmd_probe)
    d = sub.add_parser("due", help="due and new card counts for a deck")
    d.add_argument("deck")
    d.set_defaults(fn=cmd_due)
    t = sub.add_parser("epub-toc", help="list EPUB sections in reading order")
    t.add_argument("file")
    t.set_defaults(fn=cmd_epub_toc)
    x = sub.add_parser("epub-text", help="print the text of EPUB sections N or N-M")
    x.add_argument("file")
    x.add_argument("range")
    x.set_defaults(fn=cmd_epub_text)
    for name, fn, hlp in (("check", cmd_check, "validate a cards file and print card ids"),
                          ("push", cmd_push, "add approved cards to Anki through AnkiConnect")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("cards")
        s.add_argument("--max", type=int, default=MAX_CARDS)
        s.set_defaults(fn=fn)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
