#!/usr/bin/env python3
"""Self-test for chunk.py: chunks tricky sentences at every level, checks
the reconstruction invariant + size limits, prints results for eyeball
review."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spacy
from chunk import LANG_CFG, LEVELS, chunk_sentence, emoji_for, word_count

CASES = {
    "en": [
        # long multi-clause monster (Alice, opening sentence)
        "Alice was beginning to get very tired of sitting by her sister on "
        "the bank, and of having nothing to do: once or twice she had peeped "
        "into the book her sister was reading, but it had no pictures or "
        "conversations in it, “and what is the use of a book,” thought Alice, "
        "“without pictures or conversations?”",
        # list-comma trap: keep the list together when the level allows
        "The farmer bought apples, pears, plums and cherries at the market "
        "because his wife wanted to bake a large cake for the wedding.",
        # participial + coordinated infinitives
        "A Wolf, meeting with a Lamb astray from the fold, resolved not to "
        "lay violent hands on him, but to find some plea to justify to the "
        "Lamb the Wolf's right to eat him.",
        "There was nothing so very remarkable in that; nor did Alice think "
        "it so very much out of the way to hear the Rabbit say to itself, "
        "“Oh dear! Oh dear! I shall be late!”",
        # short sentence: must stay whole
        "The Dog ran away.",
    ],
    "de": [
        "Es war einmal ein kleines Mädchen, das ging in den großen Wald, "
        "weil seine Mutter ihm gesagt hatte, dass die Großmutter krank sei "
        "und dringend Hilfe brauche.",
        "Der König hatte drei Töchter, die alle schön waren, aber die "
        "jüngste war so schön, dass die Sonne selber sich verwunderte, "
        "sooft sie ihr ins Gesicht schien.",
        "Als es nun Abend wurde und der Wolf noch immer vor der Tür des "
        "kleinen Hauses saß, fürchteten sich die sieben Geißlein sehr.",
        "Der Hund lief weg.",
    ],
}

failures = 0

for lang, sents in CASES.items():
    cfg = LANG_CFG[lang]
    nlp = spacy.load(cfg["model"], disable=["ner"])
    for level, lv in LEVELS.items():
        min_w, target_w, max_w = (lv["min_words"], lv["target_words"],
                                  lv["max_words"])
        print(f"\n=== {lang} / {level} "
              f"(min {min_w} / target {target_w} / max {max_w}) ===")
        for s in sents:
            doc = nlp(s)
            for sent in doc.sents:
                try:
                    raws = chunk_sentence(sent, cfg, min_w, target_w, max_w)
                except AssertionError as e:
                    print("  INVARIANT FAIL:", e)
                    failures += 1
                    continue
                assert "".join(raws) == doc.text[sent.start_char:sent.end_char]
                pos = sent.start_char
                for r in raws:
                    span = doc.char_span(pos, pos + len(r),
                                         alignment_mode="expand")
                    pos += len(r)
                    e = emoji_for(span, lang) if span is not None else None
                    wc = word_count(span) if span is not None else \
                        len(r.strip().split())
                    flag = ""
                    if wc > max_w:
                        flag = " <-- OVER MAX"
                        failures += 1
                    print(f"  [{wc:2d}] {(e or '  ')} | {r.strip()}{flag}")
                print("  " + "-" * 60)

print(f"\nfailures: {failures}")
sys.exit(1 if failures else 0)
