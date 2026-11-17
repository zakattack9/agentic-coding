import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import study  # noqa: E402


def card(**kw):
    c = {"type": "basic", "front": "Why do leaders fail over?", "back": "Because the old leader stopped answering.",
         "source": "ch. 5, p. 156", "quote": "the leader has failed", "approved": True}
    c.update(kw)
    return c


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = study.main(argv)
    return code, out.getvalue(), err.getvalue()


class FakeAnki:
    """A minimal AnkiConnect: notes are kept in memory, findNotes matches one tag."""

    def __init__(self, models=("Basic", "Cloze")):
        self.notes, self.decks, self.models = [], set(), list(models)
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                p, act, result = req.get("params", {}), req["action"], None
                if act == "version":
                    result = 6
                elif act == "modelNames":
                    result = fake.models
                elif act == "createDeck":
                    fake.decks.add(p["deck"])
                elif act == "findNotes":
                    tag = p["query"].strip('"').split("tag:", 1)[1]
                    result = [i for i, n in enumerate(fake.notes) if tag in n["tags"]]
                elif act == "addNote":
                    fake.notes.append(p["note"])
                    result = len(fake.notes)
                elif act == "findCards":
                    result = [1, 2]
                body = json.dumps({"result": result, "error": None}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class CardIdTest(unittest.TestCase):
    def test_same_content_same_id_regardless_of_position(self):
        a, b = card(), card(front="Another question?")
        self.assertEqual(study.card_id("DDIA", a), study.card_id("DDIA", dict(a)))
        ids_run1 = [study.card_id("DDIA", c) for c in (a, b)]
        ids_run2 = [study.card_id("DDIA", c) for c in (b, a)]
        self.assertEqual(sorted(ids_run1), sorted(ids_run2))

    def test_different_content_or_source_gets_a_different_id(self):
        base = study.card_id("DDIA", card())
        self.assertNotEqual(base, study.card_id("DDIA", card(back="Something else.")))
        self.assertNotEqual(base, study.card_id("DDIA", card(source="ch. 6, p. 200")))
        self.assertNotEqual(base, study.card_id("Other book", card()))

    def test_whitespace_and_case_do_not_change_the_id(self):
        self.assertEqual(study.card_id("DDIA", card()), study.card_id("ddia", card(front="  why do leaders   FAIL over? ")))


class ValidateTest(unittest.TestCase):
    def doc(self, cards):
        return {"book": "DDIA", "cards": cards}

    def test_valid_basic_and_cloze(self):
        cloze = card(type="cloze", text="Raft elects a {{c1::leader}}.", front=None, back=None)
        del cloze["front"], cloze["back"]
        self.assertEqual(study.validate(self.doc([card(), cloze])), [])

    def test_source_and_quote_required(self):
        errs = study.validate(self.doc([card(source=""), card(front="Q2?", quote=None)]))
        self.assertTrue(any("cards[0]: source required" in e for e in errs))
        self.assertTrue(any("cards[1]: quote required" in e for e in errs))

    def test_more_than_eight_cards_rejected(self):
        errs = study.validate(self.doc([card(front=f"Q{i}?") for i in range(9)]))
        self.assertTrue(any("limit is 8" in e for e in errs))

    def test_cloze_needs_a_deletion_and_unknown_keys_are_rejected(self):
        bad = {"type": "cloze", "text": "no deletion here", "source": "p. 1", "quote": "q", "approved": True, "page": 3}
        errs = study.validate(self.doc([bad]))
        self.assertTrue(any("cloze deletion" in e for e in errs))
        self.assertTrue(any("unknown key 'page'" in e for e in errs))

    def test_duplicate_cards_rejected(self):
        errs = study.validate(self.doc([card(), card()]))
        self.assertTrue(any("duplicate of cards[0]" in e for e in errs))

    def test_errors_end_with_the_schema(self):
        errs = study.validate(self.doc([card(type="essay")]))
        self.assertTrue(errs[-1].startswith("expected {"))


class PushTest(unittest.TestCase):
    def setUp(self):
        self.anki = FakeAnki()
        study.ANKI_URL = self.anki.url
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.anki.close()
        self.tmp.cleanup()

    def write(self, doc):
        path = os.path.join(self.tmp.name, "cards.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        return path

    def test_push_adds_only_approved_cards_with_citation_and_id_tag(self):
        path = self.write({"book": "DDIA", "cards": [card(), card(front="Unapproved?", approved=False)]})
        code, out, _ = run(["push", path])
        self.assertEqual(code, 0)
        res = json.loads(out)
        self.assertEqual((res["added"], res["skipped"]), (1, 0))
        note = self.anki.notes[0]
        self.assertEqual(note["deckName"], "Books::DDIA")
        self.assertIn("Source: DDIA, ch. 5, p. 156", note["fields"]["Back"])
        self.assertIn(study.ID_TAG + study.card_id("DDIA", card()), note["tags"])

    def test_second_push_skips_cards_already_in_anki(self):
        path = self.write({"book": "DDIA", "cards": [card()]})
        run(["push", path])
        code, out, _ = run(["push", path])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["skipped"], 1)
        self.assertEqual(len(self.anki.notes), 1)

    def test_invalid_file_is_not_pushed(self):
        path = self.write({"book": "DDIA", "cards": [card(source="")]})
        code, _, _ = run(["push", path])
        self.assertEqual(code, 2)
        self.assertEqual(self.anki.notes, [])

    def test_missing_note_type_stops_before_adding(self):
        self.anki.models = ["Basic"]
        cloze = {"type": "cloze", "text": "A {{c1::b}}", "source": "p. 1", "quote": "q", "approved": True}
        code, _, err = run(["push", self.write({"book": "DDIA", "cards": [cloze]})])
        self.assertEqual(code, 3)
        self.assertIn("Cloze", err)
        self.assertEqual(self.anki.notes, [])

    def test_unreachable_ankiconnect_exits_3(self):
        self.anki.close()
        code, _, err = run(["push", self.write({"book": "DDIA", "cards": [card()]})])
        self.assertEqual(code, 3)
        self.assertIn("not reachable", err)
        self.anki = FakeAnki()  # tearDown closes it

    def test_probe_reports_missing_without_failing(self):
        study.ANKI_URL = "http://127.0.0.1:9"
        code, out, _ = run(["probe"])
        self.assertEqual(code, 0)
        self.assertIn("missing", out)


class EpubTest(unittest.TestCase):
    def make_epub(self, path):
        opf = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
 <manifest>
  <item id="c2" href="text/ch2.xhtml" media-type="application/xhtml+xml"/>
  <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  <item id="c1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
 </manifest>
 <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""
        nav = """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
<li><a href="text/ch1.xhtml">Reliable Systems</a></li><li><a href="text/ch2.xhtml#top">Data Models</a></li>
</ol></nav></body></html>"""
        ch = '<html xmlns="http://www.w3.org/1999/xhtml"><head><style>p{}</style></head><body><h1>{t}</h1><p>{b}</p></body></html>'
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
            z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                       '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
            z.writestr("OEBPS/content.opf", opf)
            z.writestr("OEBPS/nav.xhtml", nav)
            z.writestr("OEBPS/text/ch1.xhtml", ch.replace("{t}", "One").replace("{b}", "Faults are not failures."))
            z.writestr("OEBPS/text/ch2.xhtml", ch.replace("{t}", "Two").replace("{b}", "Documents &amp; relations."))

    def test_sections_follow_the_spine_with_toc_titles(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.epub")
            self.make_epub(path)
            secs = study.epub_sections(path)
        self.assertEqual([s["title"] for s in secs], ["Reliable Systems", "Data Models"])
        self.assertIn("Faults are not failures.", secs[0]["text"])
        self.assertIn("Documents & relations.", secs[1]["text"])
        self.assertNotIn("p{}", secs[0]["text"])

    def test_one_file_book_is_split_at_toc_anchors(self):
        opf = """<package xmlns="http://www.idpf.org/2007/opf"><manifest>
  <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  <item id="all" href="book.html" media-type="application/xhtml+xml"/>
 </manifest><spine><itemref idref="all"/></spine></package>"""
        ncx = """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
<navPoint><navLabel><text>CHAPTER 1</text></navLabel><content src="book.html#c1"/></navPoint>
<navPoint><navLabel><text>CHAPTER 2</text></navLabel><content src="book.html#c2"/></navPoint>
</navMap></ncx>"""
        body = ('<html><body><p>Front matter.</p><h1 id="c1">Chapter one</h1><p>Alpha text.</p>'
                '<h1><a name="c2"></a>Chapter two</h1><p>Beta text.</p></body></html>')
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "one.epub")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>')
                z.writestr("content.opf", opf)
                z.writestr("toc.ncx", ncx)
                z.writestr("book.html", body)
            secs = study.epub_sections(path)
        self.assertEqual([s["title"] for s in secs], ["Front matter.", "CHAPTER 1", "CHAPTER 2"])
        self.assertIn("Alpha text.", secs[1]["text"])
        self.assertNotIn("Beta text.", secs[1]["text"])
        self.assertIn("Beta text.", secs[2]["text"])

    def test_epub_text_prints_a_range(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.epub")
            self.make_epub(path)
            code, out, _ = run(["epub-text", path, "0-1"])
        self.assertEqual(code, 0)
        self.assertIn("=== [0] Reliable Systems", out)
        self.assertIn("=== [1] Data Models", out)


if __name__ == "__main__":
    unittest.main()
