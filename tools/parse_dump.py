#!/usr/bin/env python3
"""
Parse + chunk-path diagnostic for the 2026-07 problem sentences.
RUN THIS ON THE MACHINE WITH THE SPACY MODELS (they can't be
downloaded in the sandbox) and paste the output back for analysis.

For each case it shows:
  1. the TOKENIZATION after chunk.py's clean() — glued tokens like
     'Herz,—und' are flagged, because a cut inside a token is
     impossible and a glued token poisons the parse around it
  2. the full dependency parse with fuse direction and cut candidates
  3. the pipeline INTERMEDIATES: atoms after cutting, after
     coherence_merge, groups after merge_atoms, spans after
     fallback_split — so every final chunk is attributable to the
     path that produced it (atom / coherence / merge / absorb /
     fallback)

Usage:
  python parse_dump.py            # built-in problem cases
  python parse_dump.py --lang de --text "..."   # any sentence
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spacy
from chunk import (LANG_CFG, LEVELS, clean, fuse_dir, candidate_cuts,
                   coherence_merge, merge_atoms, fallback_split,
                   merge_ok, fragment_heads, word_count)

CASES = [
    # (lang, level, text)
    ("de", "starter",
     "Endlich aber verwandelte sich sein Herz,--und eines Morgens stand "
     "er mit der Morgenröthe auf, trat vor die Sonne hin und sprach zu "
     "ihr also:"),
    ("de", "beginner",
     "Endlich aber verwandelte sich sein Herz,--und eines Morgens stand "
     "er mit der Morgenröthe auf, trat vor die Sonne hin und sprach zu "
     "ihr also:"),
    ("de", "beginner",
     "Säcke, Citronen- und Apfelsinenkisten standen hier an der einen "
     "Wand entlang, während an der andern übereinandergeschichtete "
     "Fässer lagen, Ölfässer, deren stattliche Reihe nur durch eine zum "
     "Keller hinunterführende Fallthür unterbrochen war."),
    # systematic 'Und wenn |' / 'und als |' stranding — is the
    # subordinator mis-tagged, or does pass-2 absorb create it?
    ("de", "beginner",
     "Und wenn es ein Gitter wird, so ist es gut, und wenn dieser durch "
     "die Weinstube ging, wollen wir wenigstens eine Rabatte ziehen."),
]

NLP = {}


def get_nlp(lang):
    if lang not in NLP:
        NLP[lang] = spacy.load(LANG_CFG[lang]["model"], disable=["ner"])
    return NLP[lang]


def show_spans(tag, toks, spans):
    print(f"  {tag}:")
    for lo, hi in spans:
        txt = "".join(t.text_with_ws for t in toks[lo:hi]).strip()
        print(f"    [{lo:3d},{hi:3d}) w={word_count(toks[lo:hi]):2d}  {txt!r}")


def dump(lang, level, text):
    cfg = LANG_CFG[lang]
    lv = LEVELS[level]
    min_w, target_w, max_w = (lv["min_words"], lv["target_words"],
                              lv["max_words"])
    doc = get_nlp(lang)(clean(text))

    for sent in doc.sents:
        toks = list(sent)
        print(f"\n=== {lang}/{level}: {sent.text[:70]!r}")

        glued = [t.text for t in toks
                 if any(c.isalnum() for c in t.text)
                 and any(not c.isalnum() and c not in "’'-" for c in t.text)]
        if glued:
            print(f"  !! GLUED TOKENS (uncuttable, parse-poisoning): {glued}")

        cands = candidate_cuts(sent, cfg)
        print(f"  {'i':>3s} {'text':18s} {'pos':6s} {'tag':8s} {'dep':8s} "
              f"{'head':>18s} {'fuse':4s} cut")
        for t in toks:
            i = t.i - sent.start
            print(f"  {i:3d} {t.text[:18]:18s} {t.pos_:6s} {t.tag_:8s} "
                  f"{t.dep_:8s} {t.head.text[:14]:>14s}({t.head.i - sent.start:3d}) "
                  f"{str(fuse_dir(t, cfg) or '-'):4s} "
                  f"{'r' + str(cands[i]) if i in cands else ''}")

        n = len(toks)
        if word_count(toks) <= max_w:
            print("  (sentence fits whole — no cutting)")
            continue

        cuts = sorted(cands)
        edges = [0] + cuts + [n]
        atoms = [(edges[k], edges[k + 1]) for k in range(len(edges) - 1)]
        ranks = [cands[c] for c in cuts]
        show_spans("ATOMS after cutting", toks, atoms)

        # annotate fragments before coherence
        for lo, hi in atoms:
            fh = fragment_heads(toks, lo, hi, cfg)
            if fh:
                print(f"    fragment [{lo},{hi}) -> external heads at {fh}")

        atoms, ranks = coherence_merge(toks, list(atoms), list(ranks),
                                       cfg, max_w)
        show_spans("after COHERENCE merge", toks, atoms)

        wcs = [word_count(toks[lo:hi]) for lo, hi in atoms]

        def span_ok(a, b):
            return merge_ok(toks, atoms[a][0], atoms[b - 1][1])

        groups = merge_atoms(wcs, ranks, min_w, target_w, max_w, span_ok)
        spans = [(atoms[a][0], atoms[b - 1][1]) for a, b in groups]
        show_spans("after MERGE_ATOMS", toks, spans)

        final = [s for lo, hi in spans
                 for s in fallback_split(toks, lo, hi, min_w, max_w, cfg)]
        if final != spans:
            show_spans("after FALLBACK split", toks, final)

        # flag every final chunk that ends on a fuse-R content word
        for lo, hi in final:
            for k in range(hi - 1, lo - 1, -1):
                t = toks[k]
                if t.is_punct or t.is_space:
                    continue
                if fuse_dir(t, cfg) == "R":
                    txt = "".join(x.text_with_ws for x in toks[lo:hi]).strip()
                    print(f"    !! ends on fuse-R word {t.text!r}: {txt!r}")
                break


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", choices=("en", "de"))
    ap.add_argument("--level", default="beginner", choices=list(LEVELS))
    ap.add_argument("--text")
    args = ap.parse_args()
    if args.text:
        dump(args.lang or "de", args.level, args.text)
    else:
        for lang, level, text in CASES:
            dump(lang, level, text)


if __name__ == "__main__":
    main()
