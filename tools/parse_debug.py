#!/usr/bin/env python3
"""Diagnostic: verify which chunk.py is loaded and dump the real
dependency parses for the two problem sentences."""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spacy
import chunk
from chunk import LANG_CFG, fuse_dir, conjunct_of, candidate_cuts

src = inspect.getsource(chunk)
print("chunk.py loaded from:", chunk.__file__)
print("has quote-aware fallback:", "right after one" in src)
print("has generic coordinator fallback:", "fuses onto inside material" in src)
print("has ADP head-right rule:", "or t.head.i > t.i" in src)
print()

CASES = {
    "en": "Alice was beginning to get very tired of sitting by her sister "
          "on the bank, and of having nothing to do: once or twice she had "
          "peeped into the book her sister was reading, but it had no "
          "pictures or conversations in it, “and what is the use of a "
          "book,” thought Alice, “without pictures or conversations?”",
    "de": "Als es nun Abend wurde und der Wolf noch immer vor der Tür des "
          "kleinen Hauses saß, fürchteten sich die sieben Geißlein sehr.",
}

for lang, text in CASES.items():
    cfg = LANG_CFG[lang]
    nlp = spacy.load(cfg["model"], disable=["ner"])
    doc = nlp(text)
    print(f"=== {lang} ===")
    for sent in doc.sents:
        cands = candidate_cuts(sent, cfg)
        for t in sent:
            i = t.i - sent.start
            cut = f"CUT r{cands[i]}" if i in cands else ""
            fd = fuse_dir(t, cfg) or "-"
            conj = ""
            if t.pos_ in ("CCONJ", "SCONJ") or t.dep_ in cfg["coord_deps"]:
                c = conjunct_of(t, cfg)
                conj = f"conjunct={c.text if c is not None else 'NONE'}"
            print(f"  {i:3d} {t.text:15s} {t.pos_:6s} {t.tag_:7s} "
                  f"{t.dep_:10s} head={t.head.text:12s}({t.head.i - sent.start:3d}) "
                  f"nr={t.n_rights} fuse={fd:2s} {cut:7s} {conj}")
        print("  " + "-" * 70)
print("done")
