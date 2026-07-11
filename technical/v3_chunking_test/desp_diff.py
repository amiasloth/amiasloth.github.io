#!/usr/bin/env python3
"""Before/after diff of ONLY desperation-affected cuts: old lexicographic
key vs weighted score (DESP_WEIGHTED, round 5).  Review gate for the
desperation rework — prints just the sentences whose starter/beginner
cuts changed, side by side.

    python3 desp_diff.py [--model de_core_news_lg] [--chars 0]

--chars N caps the text length (0 = whole book; sandbox smoke runs used
60000).  Judge boundary quality on the lg run only.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunk_hierarchy as ch

import spacy


def chunks_of(sent, cuts):
    toks = list(sent)
    bounds = [0] + cuts + [len(toks)]
    return [''.join(t.text_with_ws for t in toks[a:b]).strip()
            for a, b in zip(bounds, bounds[1:])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="de_core_news_lg")
    ap.add_argument("--chars", type=int, default=0)
    ap.add_argument("--src", default=str(Path(__file__).resolve()
                    .parents[2] / "tools" / "sources" / "kafka.txt"))
    args = ap.parse_args()

    nlp = spacy.load(args.model)
    text = Path(args.src).read_bytes().decode("iso-8859-1")
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines)
                 if re.match(r"^I\.$", l.strip()))
    body = " ".join(l.strip() for l in lines[start + 1:] if l.strip())
    if args.chars:
        body = body[:args.chars]

    cfg = ch.build_cfg("de")
    doc = nlp(body)

    total, report = 0, []
    for sent in doc.sents:
        if len(list(sent)) < 4:
            continue
        strengths = ch.break_strengths(sent, cfg)
        ch.DESP_WEIGHTED = False
        old = ch.derive_levels(sent, strengths, cfg)
        ch.DESP_WEIGHTED = True
        new = ch.derive_levels(sent, strengths, cfg)
        total += 1
        for lv in ("starter", "beginner"):
            if old[lv] != new[lv]:
                report.append((lv,
                               " | ".join(chunks_of(sent, old[lv])),
                               " | ".join(chunks_of(sent, new[lv]))))
                break

    print(f"sentences: {total}, changed (starter/beginner): {len(report)}")
    for lv, o, n in report:
        print(f"\n[{lv}]\n  OLD: {o}\n  NEW: {n}")


if __name__ == "__main__":
    main()
