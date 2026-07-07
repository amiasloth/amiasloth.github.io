#!/usr/bin/env python3
"""Extended stress-test for chunk.py: harder constructions than the basic
self-test. Checks the reconstruction invariant + size limits, flags chunks
that END in a conjunction, preposition or article (bad for learners)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spacy
from chunk import (LANG_CFG, LEVELS, REL_PRON_TAGS, chunk_sentence,
                   word_count)

CASES = {
    "en": [
        # dialogue with quotes + inversion
        "“Well!” thought Alice to herself, “after such a fall as this, I "
        "shall think nothing of tumbling down stairs!”",
        # center-embedded relative clause
        "The house that the old man who lived by the river built last "
        "summer burned down during the night.",
        # long coordination chain of verbs
        "She opened the door, looked around the empty room, walked slowly "
        "to the window, and drew back the heavy curtains to let in the "
        "morning light.",
        # semicolon + list + subordination
        "The garden was full of roses, tulips and daffodils; the gardener, "
        "who had worked there for forty years, knew every plant by name.",
        # passive + agent + purpose clause
        "The old bridge was destroyed by the flood before the engineers "
        "could reinforce the ancient stone pillars that had stood for "
        "three hundred years.",
        # phrasal verbs and particles
        "He turned off the lights, picked up his coat, and set out into "
        "the cold night without looking back at the house.",
    ],
    "de": [
        # separable verb + time phrase
        "Der Zug fährt jeden Morgen um sieben Uhr vom kleinen Bahnhof ab.",
        # verb-final chain (modal + participle + auxiliary)
        "Er sagte, dass er das schwere Buch schon letzte Woche hätte "
        "zurückgeben müssen, aber es immer wieder vergessen hatte.",
        # center-embedded relative clause
        "Die Frau, die den Brief, den ihr Mann geschrieben hatte, niemals "
        "gelesen hat, wohnt noch heute in dem alten Haus am Fluss.",
        # long prepositional chains + genitive
        "Nach dem langen Spaziergang durch den dunklen Wald am Rande der "
        "kleinen Stadt kehrten die müden Wanderer in das warme Gasthaus ein.",
        # dialogue + subordinate clause
        "„Ich kann heute leider nicht kommen“, sagte der Arzt, „weil ich "
        "noch drei Patienten im Krankenhaus besuchen muss.“",
        # es-gibt + coordination
        "Es gab in dem kleinen Dorf weder einen Bäcker noch einen Metzger, "
        "und die Bewohner mussten jede Woche in die Stadt fahren.",
    ],
}

# a chunk must never END in one of these (they lean on what follows)
BAD_TAIL_POS = {"CCONJ", "SCONJ", "ADP", "DET"}

failures = warnings = 0

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
                    wc = word_count(span) if span is not None else \
                        len(r.strip().split())
                    flag = ""
                    if wc > max_w:
                        flag += " <-- OVER MAX"
                        failures += 1
                    if span is not None:
                        words = [t for t in span
                                 if not t.is_punct and not t.is_space]
                        if words and words[-1] is not words[0] \
                                and span.end < sent.end:
                            w = words[-1]
                            # verb particles ("set out") are fine tails
                            bad = (w.pos_ in BAD_TAIL_POS
                                   and w.dep_ not in ("prt", "svp")
                                   and not (w.pos_ == "ADP"
                                            and w.n_rights == 0))
                            if w.tag_ in REL_PRON_TAGS:
                                bad = True
                            if bad:
                                flag += f" <-- ENDS IN {w.pos_}"
                                warnings += 1
                    print(f"  [{wc:2d}] | {r.strip()}{flag}")
                print("  " + "-" * 60)

print(f"\nhard failures: {failures}   bad-tail warnings: {warnings}")
sys.exit(1 if failures else 0)
