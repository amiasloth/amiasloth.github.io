#!/usr/bin/env python3
"""Pure-logic tests for merge_ok + merge_atoms — runs WITHOUT spaCy
models (fake tokens), so it can run anywhere. The model-based checks
live in test_chunker.py / test_chunker_extended.py.

The two English cases are the real Alice failures this logic fixes:

  bad:  for the hot day made | her feel very sleepy | and stupid
  good: for the hot day | made her feel very sleepy | and stupid

  bad:  when suddenly a White Rabbit | with pink eyes ran close | by her
  good: when suddenly | a White Rabbit with pink eyes | ran close by her
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chunk import (LANG_CFG, fallback_split, merge_atoms, merge_ok,
                   shift_trailing_openers)


class Tok:
    """Just enough of spaCy's Token API for merge_ok."""

    def __init__(self, i, text, pos):
        self.i, self.text, self.pos_ = i, text, pos
        self.is_punct = pos == "PUNCT"
        self.is_space = False
        self.head = self
        self.children = []

    def __repr__(self):
        return self.text


def tree(words, heads):
    toks = [Tok(i, w, p) for i, (w, p) in enumerate(words)]
    for i, h in enumerate(heads):
        if h != i:
            toks[i].head = toks[h]
            toks[h].children.append(toks[i])
    return toks


# --- "…, when suddenly a White Rabbit with pink eyes ran close by her."
# token 0 stands in for the external main-clause verb ("considering")
RABBIT = tree(
    [("considering", "VERB"), ("when", "SCONJ"), ("suddenly", "ADV"),
     ("a", "DET"), ("White", "ADJ"), ("Rabbit", "NOUN"),
     ("with", "ADP"), ("pink", "ADJ"), ("eyes", "NOUN"),
     ("ran", "VERB"), ("close", "ADV"), ("by", "ADP"),
     ("her", "PRON"), (".", "PUNCT")],
    #  0  1  2  3  4  5  6  7  8  9 10 11 12 13
    [0, 9, 9, 5, 5, 9, 5, 8, 6, 0, 9, 9, 11, 9])

# --- "…, for the hot day made her feel very sleepy and stupid …"
# token 0 stands in for the external head of "made" ("could")
HOTDAY = tree(
    [("could", "VERB"), ("for", "SCONJ"), ("the", "DET"), ("hot", "ADJ"),
     ("day", "NOUN"), ("made", "VERB"), ("her", "PRON"), ("feel", "VERB"),
     ("very", "ADV"), ("sleepy", "ADJ"), ("and", "CCONJ"),
     ("stupid", "ADJ")],
    #  0  1  2  3  4  5  6  7  8  9 10 11
    [0, 5, 4, 4, 5, 0, 7, 5, 9, 7, 9, 9])

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"  {'ok ' if ok else 'FAIL'} {name}: {got!r}"
          + ("" if ok else f" != {want!r}"))


print("merge_ok gates")
# gate A: mixes subject-NP material with the verb -> two external heads
check("straddler 'with pink eyes ran close' blocked",
      merge_ok(RABBIT, 6, 11), False)
# one external head is normal (pre-verb dependents of a distant verb)
check("'when suddenly a White Rabbit' allowed",
      merge_ok(RABBIT, 1, 6), True)
check("'a White Rabbit with pink eyes' allowed",
      merge_ok(RABBIT, 3, 9), True)
check("'ran close by her.' allowed",
      merge_ok(RABBIT, 9, 14), True)
# gate B: chunk must not end on a verb whose complements follow
check("'the hot day made' blocked (severs made|her feel)",
      merge_ok(HOTDAY, 2, 6), False)
check("'for the hot day' allowed",
      merge_ok(HOTDAY, 1, 5), True)
check("'made her feel very sleepy' allowed",
      merge_ok(HOTDAY, 5, 10), True)
check("span containing its own root allowed",
      merge_ok(RABBIT, 0, 14), True)

print("merge_atoms end-to-end (intermediate: min 2 / target 5 / max 8)")


def oracle(toks, atoms):
    return lambda a, b: merge_ok(toks, atoms[a][0], atoms[b - 1][1])


# when suddenly | a White Rabbit | with pink eyes | ran close | by her.
atoms = [(1, 3), (3, 6), (6, 9), (9, 11), (11, 14)]
groups = merge_atoms([2, 3, 3, 2, 2], [3, 4, 3, 2], 2, 5, 8,
                     oracle(RABBIT, atoms))
check("Rabbit -> when suddenly | a White Rabbit with pink eyes "
      "| ran close by her.",
      groups, [(0, 1), (1, 3), (3, 5)])

# for | the hot day | made | her feel very sleepy | and stupid
atoms = [(1, 2), (2, 5), (5, 6), (6, 10), (10, 12)]
groups = merge_atoms([1, 3, 1, 4, 2], [3, 3, 1, 3], 2, 5, 8,
                     oracle(HOTDAY, atoms))
check("hot day -> for the hot day | made her feel very sleepy "
      "| and stupid",
      groups, [(0, 2), (2, 4), (4, 5)])

print("merge_atoms plain-list behavior")
# rank-4 (tight) boundaries may exceed the target, up to the hard max
check("rank-4 merges past target up to max",
      merge_atoms([3, 4], [4], 2, 5, 8), [(0, 2)])
check("rank-3 still stops at target",
      merge_atoms([3, 4], [3], 2, 5, 8), [(0, 1), (1, 2)])
# an unmergeable weak neighbour no longer deadlocks the whole sentence:
# rank-2 boundary at the end merges although its rank-3 neighbour is
# weaker — that neighbour can never merge (6+2 > target)
check("no guard deadlock behind an unmergeable weaker boundary",
      merge_atoms([2, 3, 6, 2, 2], [3, 4, 3, 2], 2, 5, 8),
      [(0, 2), (2, 3), (3, 5)])
# unchanged basics: weakest-first, size-bounded, pass-2 rescue
check("basic merge unchanged",
      merge_atoms([2, 2, 2], [3, 3], 2, 5, 8), [(0, 2), (2, 3)])
# pass 2 rescues an undersized atom in the direction the gate allows
check("pass 2 rescues undersized toward the gate-clean side",
      merge_atoms([4, 1, 4], [3, 1], 2, 5, 8,
                  span_ok=lambda a, b: (a, b) != (0, 2)),
      [(0, 1), (1, 3)])

print("fallback_split cuts at branch seams (fewest crossing edges)")


class Tok2(Tok):
    """Fuller fake for fallback_split (fuse_dir / good_cut / word_count)."""

    def __init__(self, i, text, pos, dep):
        super().__init__(i, text, pos)
        self.dep_, self.tag_, self.whitespace_ = dep, "", " "

    @property
    def n_rights(self):
        return sum(1 for c in self.children if c.i > self.i)


def de_tree(spec):
    doc = [Tok2(i, w, p, d) for i, (w, p, d, _) in enumerate(spec)]
    for tok, (_, _, _, h) in zip(doc, spec):
        tok.doc = doc
        if h != tok.i:
            tok.head = doc[h]
            doc[h].children.append(tok)
    return doc


DE = LANG_CFG["de"]

# "wurden … auf einen mit zwei magern Schimmeln bespannten Bauerwagen
# geladen." — extended attribute; no candidate boundary inside the PP
SCHIMMELN = de_tree([
    ("wurden", "AUX", "ROOT", 0), ("auf", "ADP", "mo", 9),
    ("einen", "DET", "nk", 8), ("mit", "ADP", "mo", 7),
    ("zwei", "NUM", "nk", 6), ("magern", "ADJ", "nk", 6),
    ("Schimmeln", "NOUN", "nk", 3), ("bespannten", "ADJ", "nk", 8),
    ("Bauerwagen", "NOUN", "nk", 1), ("geladen", "VERB", "oc", 0),
    (".", "PUNCT", "punct", 0)])

check("intermediate: auf einen | mit zwei magern Schimmeln "
      "bespannten Bauerwagen geladen.",
      fallback_split(SCHIMMELN, 1, 11, 2, 8, DE), [(1, 3), (3, 11)])
check("beginner adds: mit zwei magern Schimmeln | bespannten "
      "Bauerwagen geladen.",
      fallback_split(SCHIMMELN, 1, 11, 2, 5, DE),
      [(1, 3), (3, 7), (7, 11)])

# "Vor dem in dem großen und reichen Oderbruchdorfe Tschechin
# (um Michaeli 20) eröffneten Gasthaus" — tokens 9,10 external
ODERBRUCH = de_tree([
    ("Vor", "ADP", "mo", 10), ("dem", "DET", "nk", 10),
    ("in", "ADP", "mo", 9), ("dem", "DET", "nk", 7),
    ("großen", "ADJ", "nk", 7), ("und", "CCONJ", "cd", 4),
    ("reichen", "ADJ", "cj", 5), ("Oderbruchdorfe", "NOUN", "nk", 2),
    ("Tschechin", "PROPN", "nk", 7),
    ("eröffneten", "ADJ", "nk", 10), ("Gasthaus", "NOUN", "ROOT", 10)])

check("intermediate: Vor dem | in dem großen und reichen "
      "Oderbruchdorfe Tschechin (0-crossing seam beats midpoint)",
      fallback_split(ODERBRUCH, 0, 9, 2, 8, DE), [(0, 2), (2, 9)])
check("beginner: Vor dem | in dem | großen und reichen "
      "Oderbruchdorfe Tschechin (adjectives stay with their noun)",
      fallback_split(ODERBRUCH, 0, 9, 2, 5, DE),
      [(0, 2), (2, 4), (4, 9)])

print("shift_trailing_openers")
ch = [{"t": "auf die Deichsel steigenden Knecht: »", "cont": 1},
      {"t": "Und nun vorwärts,"}]
shift_trailing_openers(ch, DE)
check("dangling » moves onto the speech it opens",
      [c["t"] for c in ch],
      ["auf die Deichsel steigenden Knecht:", "»Und nun vorwärts,"])
ch = [{"t": "sagte er.«"}, {"t": "Dann ging er."}]
shift_trailing_openers(ch, DE)
check("closing « stays put",
      [c["t"] for c in ch], ["sagte er.«", "Dann ging er."])

print(f"\nfailures: {failures}")
sys.exit(1 if failures else 0)
