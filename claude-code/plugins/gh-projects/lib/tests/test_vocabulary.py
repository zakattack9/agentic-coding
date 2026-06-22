#!/usr/bin/env python3
"""Name-sync drift lock for rules/vocabulary.md — fully offline, stdlib only.

Three sources must agree on every field/option NAME so prose can never silently
drift from the schema or the code:

  1. templates/project/fields.json — the CANONICAL source of every field name and
     every single-select / issue-type option name.
  2. rules/vocabulary.md — the human-owned glossary. Every canonical name must
     appear in it VERBATIM (coverage + exact spelling — a typo'd term fails).
  3. templates/github/signals.py + lib/dag.py — the deterministic engine's name
     constants (HEALTH_* / SLIP_* / BLAST_* / BLOCKED_* in signals.py; BLAST_* in
     dag.py). Each constant VALUE must equal the matching fields.json option name
     (code <-> schema lock) AND appear verbatim in vocabulary.md.

It also asserts the staging-lifecycle terms (stub / drafting / ready / promoted),
which are prose-only (not fields.json fields), are documented.

Dash-glyph note: a few Slippage buckets are written with an en-dash in the engine
constants ("1<en-dash>2d") but a hyphen in fields.json ("1-2d"). The code <-> schema
comparison normalizes dash glyphs so the NAMES are locked without depending on which
dash character a given source happens to use; the vocabulary.md coverage check uses
the fields.json (hyphen) spelling, which is the canonical board option name.
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent
PLUGIN_ROOT = LIB.parent

FIELDS_JSON = PLUGIN_ROOT / "templates" / "project" / "fields.json"
VOCAB_MD = PLUGIN_ROOT / "rules" / "vocabulary.md"
SIGNALS_PY = PLUGIN_ROOT / "templates" / "github" / "signals.py"
DAG_PY = LIB / "dag.py"

# Structural / native field names that are intentionally NOT glossary terms. Kept
# deliberately minimal — every signal / triage / taxonomy / status / scheduling
# name is required to appear. "Title" is pinned-first by GitHub and is not a board
# concept the glossary defines.
NAME_SKIPLIST = {"Title"}

# Engine name-constant prefixes whose VALUES must lock to a fields.json option.
SIGNAL_CONST_PREFIXES = ("HEALTH_", "SLIP_", "BLAST_", "BLOCKED_")
DAG_CONST_PREFIXES = ("BLAST_",)

# Staging-lifecycle terms — prose-only (not fields.json fields), must be documented.
STAGING_TERMS = ("stub", "drafting", "ready", "promoted")

# Dash glyphs to normalize when comparing an engine constant value to a schema
# option name (en-dash, em-dash, figure-dash) -> ASCII hyphen.
_DASHES = {"–": "-", "—": "-", "‒": "-"}


def _normalize_dashes(s: str) -> str:
    for d, repl in _DASHES.items():
        s = s.replace(d, repl)
    return s


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_fields() -> dict:
    return json.loads(FIELDS_JSON.read_text(encoding="utf-8"))


def _field_names(schema: dict) -> list[str]:
    return [f["name"] for f in schema.get("fields", []) if f.get("name")]


def _option_names_by_field(schema: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in schema.get("fields", []):
        opts = [o["name"] for o in f.get("options", []) if o.get("name")]
        if opts:
            out[f["name"]] = opts
    return out


def _all_option_names(schema: dict) -> set[str]:
    out: set[str] = set()
    for opts in _option_names_by_field(schema).values():
        out.update(opts)
    return out


def _engine_name_constants(mod, prefixes: tuple[str, ...]) -> dict[str, str]:
    """Every UPPER constant whose name starts with one of `prefixes` and whose
    value is a str — {const_name: value}."""
    out: dict[str, str] = {}
    for name in dir(mod):
        if name.startswith(prefixes):
            val = getattr(mod, name)
            if isinstance(val, str):
                out[name] = val
    return out


class VocabularyNameSync(unittest.TestCase):
    """Locks rules/vocabulary.md to fields.json AND the engine name constants."""

    @classmethod
    def setUpClass(cls):
        cls.schema = _load_fields()
        cls.vocab = VOCAB_MD.read_text(encoding="utf-8")
        cls.vocab_norm = _normalize_dashes(cls.vocab)
        cls.field_names = _field_names(cls.schema)
        cls.options_by_field = _option_names_by_field(cls.schema)
        cls.all_options = _all_option_names(cls.schema)
        cls.signals = _load_module(SIGNALS_PY, "signals_under_test")
        cls.dag = _load_module(DAG_PY, "dag_under_test")

    # -- (a)/(b): every canonical fields.json NAME appears verbatim in the glossary.
    def test_every_field_name_in_vocabulary(self):
        for name in self.field_names:
            if name in NAME_SKIPLIST:
                continue
            self.assertIn(
                name, self.vocab,
                f"field name {name!r} (fields.json) is missing from vocabulary.md "
                f"(coverage + exact-spelling lock)",
            )

    def test_every_option_name_in_vocabulary(self):
        for field, opts in self.options_by_field.items():
            for opt in opts:
                # The hyphen-spelled option name is the canonical board option.
                self.assertIn(
                    opt, self.vocab,
                    f"option {opt!r} of field {field!r} (fields.json) is missing "
                    f"from vocabulary.md (coverage + exact-spelling lock)",
                )

    # -- (c): engine constant VALUES lock to a fields.json option AND appear in prose.
    def test_signals_constants_match_schema_and_vocabulary(self):
        consts = _engine_name_constants(self.signals, SIGNAL_CONST_PREFIXES)
        self.assertTrue(consts, "expected HEALTH_/SLIP_/BLAST_/BLOCKED_ constants in signals.py")
        normalized_options = {_normalize_dashes(o) for o in self.all_options}
        for cname, cval in consts.items():
            self.assertIn(
                _normalize_dashes(cval), normalized_options,
                f"signals.py {cname} = {cval!r} does not match any fields.json "
                f"option name (code <-> schema drift)",
            )
            self.assertIn(
                _normalize_dashes(cval), self.vocab_norm,
                f"signals.py {cname} = {cval!r} is missing from vocabulary.md",
            )

    def test_dag_constants_match_schema_and_vocabulary(self):
        consts = _engine_name_constants(self.dag, DAG_CONST_PREFIXES)
        self.assertTrue(consts, "expected BLAST_ constants in dag.py")
        normalized_options = {_normalize_dashes(o) for o in self.all_options}
        for cname, cval in consts.items():
            self.assertIn(
                _normalize_dashes(cval), normalized_options,
                f"dag.py {cname} = {cval!r} does not match any fields.json "
                f"option name (code <-> schema drift)",
            )
            self.assertIn(
                _normalize_dashes(cval), self.vocab_norm,
                f"dag.py {cname} = {cval!r} is missing from vocabulary.md",
            )

    # The two engines' BLAST_ constants must themselves agree (single dependency
    # vocabulary across signals.py and dag.py).
    def test_signals_and_dag_blast_constants_agree(self):
        s = _engine_name_constants(self.signals, ("BLAST_",))
        d = _engine_name_constants(self.dag, ("BLAST_",))
        shared = set(s) & set(d)
        self.assertTrue(shared, "signals.py and dag.py must share BLAST_ constants")
        for name in shared:
            self.assertEqual(
                _normalize_dashes(s[name]), _normalize_dashes(d[name]),
                f"BLAST constant {name} differs between signals.py and dag.py",
            )

    # -- (d): staging-lifecycle terms are documented in the glossary.
    def test_staging_lifecycle_terms_in_vocabulary(self):
        low = self.vocab.lower()
        for term in STAGING_TERMS:
            self.assertIn(
                term, low,
                f"staging-lifecycle term {term!r} is missing from vocabulary.md",
            )

    # A coverage backstop: the count of locked names, so a silent drop is visible.
    def test_locks_a_nontrivial_name_set(self):
        locked = (set(self.field_names) - NAME_SKIPLIST) | self.all_options
        self.assertGreaterEqual(
            len(locked), 40,
            f"expected to lock 40+ field/option names, got {len(locked)}",
        )


if __name__ == "__main__":
    unittest.main()
