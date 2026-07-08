#!/usr/bin/env python3
"""
Static quality lint for built chunk data (docs/data/*/*.json).

Needs NO spaCy and no source text — it checks the OUTPUT against the
project's own quality bar ("every chunk reads as a slice of one
phrase") using closed-class word lists. Run it after every build; the
counts are the regression metric.

Violation classes (all = "chunk ends on a word that grammatically
opens what follows", i.e. a fuse-RIGHT word stranded at a chunk end):

  glued_dash    an em-dash INSIDE the chunk with no space around it
                ("Herz,—und ... stand"): the tokenizer kept it as one
                token, so no cut was ever possible there and the parse
                around it is garbage — a cleaning bug, not a merge bug
  end_art       ends on a bare article and the next chunk starts
                lowercase ("in dem | immer bereit stehenden Kaffee-
                topfe"); article directly before a comma is excluded —
                that is a demonstrative pronoun ("und der, | den du")
  end_sub       ends on a subordinator ("Und wenn | es ein Gitter
                wird") — the clause it opens starts in the NEXT chunk
  conj_comma    ends on coordinator+comma ("sprang und, | gegen alle
                seine Gäste gewendet") — good_cut only looks at the
                comma and never checks the 'und' behind it
  end_prep      ends on a preposition that can NEVER be a separable
                verb particle ("nur durch | eine ... Fallthür");
                ambiguous ones (an/auf/aus/zu/...) are only counted
                when the next chunk starts with an article — a real
                particle is never followed by the NP it governs
  lone_func     the whole chunk is a single function word ("sich",
                "er", "auf,") — mostly a starter-level disease

Usage:
  python chunk_lint.py ../docs/data/de/*.json           # summary table
  python chunk_lint.py -v ../docs/data/de/birnbaum_beginner.json
                                                        # + examples
"""

import argparse
import collections
import json
import re
import sys

WORD = re.compile(r"[\wäöüßÄÖÜéèáà’'-]+")

DE = {
    "art": set("der die das den dem des ein eine einen einem einer eines".split()),
    "sub": set("dass daß weil wenn obwohl während bevor nachdem indem "
               "als ob falls sodass".split()),
    # 'aber'/'denn' excluded: usually adverb/particle when comma-final
    "conj": set("und oder sondern".split()),
    # prepositions that can never be separable-verb particles
    "prep_strict": set("durch für gegen ohne zwischen bei seit trotz "
                       "während wegen".split()),
    # ambiguous prep/particle: bad only when the governed NP follows
    "prep_ambig": set("an auf aus in mit nach um unter über von vor zu "
                      "zur zum vom beim im am ins ans hinter neben".split()),
    "pron": set("er sie es ich du wir ihr man sich mich dich uns euch".split()),
}
EN = {
    "art": set("the a an".split()),
    "sub": set("that because although while if when since unless whether".split()),
    "conj": set("and or but nor".split()),
    "prep_strict": set("of from into onto during towards toward between "
                       "against without within upon".split()),
    "prep_ambig": set("in on at by with to over under through about "
                      "off out up down".split()),
    "pron": set("he she it i you we they him her them his its their".split()),
}

CLASSES = ["glued_dash", "end_art", "end_sub", "conj_comma",
           "end_prep", "lone_func"]


def tokens(t):
    return re.findall(r"[\wäöüßÄÖÜéèáà’'-]+|[^\w\s]", t)


def lint_book(path, verbose=0):
    d = json.load(open(path, encoding="utf-8"))
    L = DE if d["lang"] == "de" else EN
    counts = collections.Counter()
    examples = collections.defaultdict(list)
    n = 0

    def hit(cls, ctx):
        counts[cls] += 1
        if len(examples[cls]) < 40:
            examples[cls].append(ctx)

    for sec in d["sections"]:
        ch = [c["t"] for c in sec["chunks"]]
        for i, t in enumerate(ch):
            n += 1
            tk = tokens(t)
            if not tk:
                continue
            words = [w for w in tk if WORD.fullmatch(w)]
            last = tk[-1].lower()
            nxt = ch[i + 1] if i + 1 < len(ch) else ""
            nxt_words = WORD.findall(nxt)
            nxt_first = nxt_words[0] if nxt_words else ""
            ctx = " | ".join(ch[max(0, i - 1):i + 2])

            if re.search(r"\S[—–]\S", t):
                hit("glued_dash", ctx)
            if last in L["art"] and nxt_first and nxt_first[0].islower():
                hit("end_art", ctx)
            if last in L["sub"]:
                hit("end_sub", ctx)
            if (len(tk) >= 2 and tk[-1] == "," and tk[-2].lower() in L["conj"]
                    and tk[-2].islower()):    # 'Oder' the river is not 'oder'
                hit("conj_comma", ctx)
            if last in L["prep_strict"] and last not in L["sub"]:
                hit("end_prep", ctx)
            elif last in L["prep_ambig"] and nxt_first.lower() in L["art"]:
                hit("end_prep", ctx)
            if len(words) == 1 and words[0].lower() in (
                    L["art"] | L["conj"] | L["sub"]
                    | L["prep_strict"] | L["prep_ambig"] | L["pron"]):
                hit("lone_func", ctx)

    return n, counts, examples


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+")
    ap.add_argument("-v", "--verbose", action="count", default=0,
                    help="print example contexts per class")
    args = ap.parse_args()

    hdr = f"{'file':44s}{'chunks':>7s}" + "".join(f"{c:>11s}" for c in CLASSES) \
        + f"{'total%':>8s}"
    print(hdr)
    grand = collections.Counter()
    grand_n = 0
    for f in args.files:
        n, counts, examples = lint_book(f, args.verbose)
        total = sum(counts.values())
        print(f"{f:44s}{n:7d}"
              + "".join(f"{counts[c]:11d}" for c in CLASSES)
              + f"{100 * total / max(n, 1):8.2f}")
        grand.update(counts)
        grand_n += n
        if args.verbose:
            for c in CLASSES:
                if examples[c]:
                    print(f"  -- {c}:")
                    for e in examples[c][: 6 * args.verbose]:
                        print(f"     {e}")
    if len(args.files) > 1:
        total = sum(grand.values())
        print(f"{'ALL':44s}{grand_n:7d}"
              + "".join(f"{grand[c]:11d}" for c in CLASSES)
              + f"{100 * total / max(grand_n, 1):8.2f}")


if __name__ == "__main__":
    main()
