#!/usr/bin/env python3
"""
Before/after comparison for the two round-4 suggestions, on real
sentences (owner request: "what is the current, what is the suggested,
and will it affect other sentences?").

Case 1 — crossing-aware desperation (ADOPTED, default on):
    legacy desperation balanced lengths only; now it prefers the cut
    the fewest dependency edges cross (port of tools/chunk.py
    fallback_split).  This report shows every sentence it changes.

Case 2 — cheap strong cuts (SUGGESTION, default off):
    cuts at/above the level's pref strength cost 30%, so intermediate
    stops shadowing advanced on long sentences.  This report shows the
    formerly-identical sentences it separates, plus everything else it
    touches.

Run on the build machine (lg) for the real picture:
    python3 test_improvements.py --in ../../tools/build/kafka_utf8.txt \
        --skip-until '^I\\.$'
Add --sections 1 / --model de_core_news_sm for a quick smoke run.
"""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunk_hierarchy as ch

base = ch.base
LEVELS = ["starter", "beginner", "intermediate", "advanced"]

CASE1_TARGETS = ["vor Befriedigung tränenden",
                 "nutzlos meine Zeit versäumen"]


def wc(t):
    return sum(1 for w in t.split() if any(c.isalnum() for c in w))


def derive(sent, strengths, cfg, desp_crossings, cheap_strong):
    ch.DESP_CROSSINGS = desp_crossings
    ch.CHEAP_STRONG_CUTS = cheap_strong
    try:
        cuts = ch.derive_levels(sent, strengths, cfg)
        return {lvl: ch.spans_to_text(sent, cuts[lvl]) for lvl in LEVELS}
    finally:
        ch.DESP_CROSSINGS = True
        ch.CHEAP_STRONG_CUTS = False


def show(tag, levels, only=None):
    for lvl in LEVELS:
        if only and lvl not in only:
            continue
        print(f"    {tag}/{lvl[:5]}: " + " | ".join(levels[lvl]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--lang", default="de")
    ap.add_argument("--skip-until", default=None)
    ap.add_argument("--stop-at", default=None)
    ap.add_argument("--sections", type=int, default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--examples", type=int, default=3,
                    help="extra changed-sentence samples per case")
    args = ap.parse_args()

    import spacy
    cfg = base.LANG_CFG[args.lang]
    nlp = spacy.load(args.model or cfg["model"], disable=["ner"])
    text = base.clean(base.strip_gutenberg(
        Path(args.infile).read_text(encoding="utf-8")))
    secs = base.sections_of(text, args.skip_until, args.stop_at)
    if args.sections:
        secs = secs[:args.sections]

    case1, case2, n_sents = [], [], 0
    resolved_shadow = 0
    for _, paras in secs:
        for doc in nlp.pipe(paras):
            for sent in doc.sents:
                if not sent.text.strip():
                    continue
                n_sents += 1
                strengths = ch.break_strengths(sent, cfg)
                cur = derive(sent, strengths, cfg, True, False)
                old = derive(sent, strengths, cfg, False, False)
                cheap = derive(sent, strengths, cfg, True, True)
                stext = " ".join(sent.text.split())
                if old != cur:
                    case1.append((stext, old, cur))
                if cheap != cur:
                    was_shadow = (cur["intermediate"] == cur["advanced"]
                                  and wc(stext) > 12)
                    if was_shadow and \
                            cheap["intermediate"] != cheap["advanced"]:
                        resolved_shadow += 1
                    case2.append((stext, cur, cheap, was_shadow))

    # ---------------- case 1
    print("=" * 72)
    print(f"CASE 1 — crossing-aware desperation (adopted)")
    print(f"  sentences changed: {len(case1)} of {n_sents}")
    per = {lvl: sum(1 for _, o, c in case1 if o[lvl] != c[lvl])
           for lvl in LEVELS}
    print("  per level: " + ", ".join(f"{l}: {n}" for l, n in per.items()))
    shown = 0
    for stext, o, c in case1:
        target = any(t in stext for t in CASE1_TARGETS)
        if not target and shown >= args.examples:
            continue
        if not target:
            shown += 1
        print(f"\n  {'[referenced example] ' if target else ''}"
              f"({wc(stext)}w) {stext[:90]}")
        diff = [l for l in LEVELS if o[l] != c[l]]
        show("OLD", o, diff)
        show("NEW", c, diff)

    # ---------------- case 2
    print("\n" + "=" * 72)
    print("CASE 2 — cheap strong cuts (suggestion, NOT adopted)")
    print(f"  sentences changed: {len(case2)} of {n_sents}")
    per = {lvl: sum(1 for _, c, ch_, _ in case2 if c[lvl] != ch_[lvl])
           for lvl in LEVELS}
    print("  per level: " + ", ".join(f"{l}: {n}" for l, n in per.items()))
    print(f"  intermediate==advanced (>12w) cases separated: "
          f"{resolved_shadow}")
    shown_s = shown_o = 0
    for stext, c, ch_, was_shadow in case2:
        if was_shadow and shown_s < args.examples:
            shown_s += 1
        elif not was_shadow and shown_o < args.examples:
            shown_o += 1
        else:
            continue
        kind = "shadow resolved" if was_shadow else "side effect"
        print(f"\n  [{kind}] ({wc(stext)}w) {stext[:90]}")
        diff = [l for l in LEVELS if c[l] != ch_[l]]
        show("CUR", c, diff)
        show("SUG", ch_, diff)


if __name__ == "__main__":
    main()
