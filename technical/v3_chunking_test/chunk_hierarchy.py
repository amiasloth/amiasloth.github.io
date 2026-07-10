#!/usr/bin/env python3
"""
Candidate B experiment: break-point hierarchy, baked levels.

This is the OPEN-question experiment from
technical/v3_discussion/00_v3_overview.md ("OPEN — chunking strategy").
It is throwaway experiment code — NOT a replacement for tools/chunk.py.

Idea
----
Instead of chunking each level independently (current chunker), compute
per-sentence BREAK POINTS once, each with a STRENGTH derived from the
dependency parse:

    100  strong punctuation  ; : — –   (parse-independent)
     90  closing quote followed by narration
     80  clause boundaries (rc/oc/par/re subtree edges, subordinator,
         verbal coordination)
     65  verb-attached prepositional phrase, infinitive zu
     60  apposition
     55  bare comma
     45  subject / object NP left edge
     40  noun coordination
     30  adverbial modifier edge
     20  any other complete-subtree left edge
      5  merely valid (fusion-clean) position — desperation only

Fusion rules mirror tools/chunk.py: no break after articles /
prepositions / conjunctions / subordinators / relative pronouns /
infinitive zu, none inside verb clusters, none that strands
punctuation, none before a separable-verb prefix.

Levels are then derived by thresholding + a DP length balancer
(Knuth-Plass style: minimize squared deviation from the target length
plus a cost for using weak breaks), TOP-DOWN so levels NEST by
construction:

    advanced cuts  ⊆  intermediate cuts  ⊆  beginner cuts  ⊆  starter cuts

Moving up a level = merging familiar pieces, never re-cutting.

The same hierarchy also yields adaptive progressive rungs: the
strongest break nearest the middle halves a long sentence.

Hard invariant (same as tools/chunk.py):
    "".join(raw_chunks) == raw_sentence_text     for every level.

Usage:
    python3 chunk_hierarchy.py --in <kafka_utf8.txt> --lang de \
        --skip-until '^I\\.$' --out out/hierarchy_kafka.json \
        [--sections 3]
"""

import argparse
import bisect
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True                      # keep tools/ untouched
TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
import chunk as base                                # reuse text prep + cfg

STRONG_PUNCT = base.STRONG_PUNCT
REL_PRON_TAGS = base.REL_PRON_TAGS

# top-down order: coarsest first (nesting by construction)
LEVEL_ORDER = ["advanced", "intermediate", "beginner", "starter"]
LEVELS = {
    #                min  target  max   strength preference
    "advanced":     dict(min=3, target=8, max=12, pref=80),
    "intermediate": dict(min=2, target=5, max=8,  pref=55),
    "beginner":     dict(min=2, target=3, max=5,  pref=30),
    "starter":      dict(min=2, target=2, max=3,  pref=0),
}

VERBISH = {"VERB", "AUX"}

# DP cost weights
W_LEN = 10.0          # squared relative deviation from target
W_CUT = 8.0           # weak-break usage
W_PREF = 6.0          # break below the level's preferred strength
W_RUNT = 50.0         # per word below min
W_OVER = 1e5          # per word above max (soft-hard: DP avoids at all cost)


# --------------------------------------------------------------- break points

def fuses_right(t, cfg):
    """Token must not end a chunk (it opens what follows)."""
    if t.pos_ in ("ADP", "SCONJ", "CCONJ", "DET"):
        return True
    if t.tag_ in REL_PRON_TAGS or t.tag_ in cfg["inf_tags"]:
        return True
    if t.dep_ in cfg["fused_deps"] and t.head.i > t.i:
        return True
    # adverb/adjective modifying a following adjective:
    # "panzerartig harten Rücken", "kläglich dünnen Beine"
    if t.pos_ in ("ADV", "ADJ") and t.head.i > t.i and t.head.pos_ == "ADJ":
        return True
    return False


def fuses_left(t, cfg):
    """Token must not start a chunk (it belongs to what precedes)."""
    return t.dep_ in cfg["fused_deps"] and t.head.i < t.i


def valid_break(toks, k, cfg):
    """Is a cut between toks[k-1] and toks[k] fusion-clean?"""
    prev, cur = toks[k - 1], toks[k]
    if cur.is_space:
        return False
    # chunk may not start with closing/neutral punctuation
    if cur.is_punct and cur.text not in cfg["open_quotes"]:
        return False
    # an opening quote/paren stays with what follows
    if prev.is_punct and prev.text in cfg["open_quotes"]:
        return False
    if not prev.is_punct and fuses_right(prev, cfg):
        return False
    if not cur.is_punct and fuses_left(cur, cfg):
        return False
    # verb clusters are atomic ("hätte zurückgeben müssen")
    if prev.pos_ in VERBISH and cur.pos_ in VERBISH:
        return False
    return True


def subtree_span(t, base_i):
    idx = [x.i - base_i for x in t.subtree]
    return min(idx), max(idx)


def break_strengths(sent, cfg):
    """{position k: strength} for every fusion-clean break point.
    Position k = cut before sentence-token k (1..n-1)."""
    toks = list(sent)
    n = len(toks)
    b0 = sent.start

    # precompute subtree left/right edges by dependency label
    clause_edges, left_edges = set(), {}   # left_edges: k -> best dep signal
    for t in toks:
        if t.is_punct or t.is_space:
            continue
        lo, hi = subtree_span(t, b0)
        if t.dep_ in cfg["clause_deps"]:
            clause_edges.add(lo)
            clause_edges.add(hi + 1)
        sig = None
        if t.dep_ in cfg["subj_deps"] or t.dep_ in cfg["obj_deps"]:
            sig = 45
        elif t.dep_ == "mo" and t.pos_ != "ADP" and t.head.pos_ in VERBISH:
            sig = 30
        elif t.dep_ not in cfg["fused_deps"]:
            sig = 20
        if sig and 0 < lo < n:
            left_edges[lo] = max(left_edges.get(lo, 0), sig)

    out = {}
    for k in range(1, n):
        if not valid_break(toks, k, cfg):
            continue
        prev, cur = toks[k - 1], toks[k]
        s = 5
        if prev.is_punct and prev.text in STRONG_PUNCT:
            s = 100
        elif cur.text in ("—", "–"):
            s = 100
        elif prev.is_punct and prev.text in cfg["close_quotes"]:
            s = 90
        if k in clause_edges:
            s = max(s, 80)
        if cur.dep_ in cfg["marker_deps"]:
            s = max(s, 80)
        if cur.dep_ in cfg["coord_deps"]:
            conj_verbal = (cur.head.pos_ in VERBISH
                           or any(c.dep_ in cfg["conj_deps"]
                                  and c.pos_ in VERBISH
                                  for c in cur.children))
            s = max(s, 80 if conj_verbal else 40)
        if cur.pos_ == "ADP" and not cur.is_punct:
            if cur.dep_ in ("mo", "op", "pg", "cvc") \
                    and cur.head.pos_ in VERBISH:
                s = max(s, 65)
            elif cur.dep_ in ("mnr", "pg", "ag"):
                s = max(s, 10)
            else:
                s = max(s, 25)
        if cur.tag_ in cfg["inf_tags"]:
            s = max(s, 65)
        if cur.dep_ in cfg["phrase_deps"]:
            s = max(s, 60)
        if prev.text == ",":
            s = max(s, 55)
        s = max(s, left_edges.get(k, 0))
        out[k] = s
    return out


# --------------------------------------------------------------- DP balancer

def word_count(text):
    return len(text.split())


def dp_segment(positions, strengths, wcount, lo, hi, lv):
    """Choose cuts inside token-span [lo, hi) from candidate `positions`
    (sorted, all in (lo, hi)), minimizing length badness + cut cost.
    Returns chosen cut positions (possibly empty)."""
    pts = [lo] + positions + [hi]
    m = len(pts)
    tgt, mn, mx, pref = lv["target"], lv["min"], lv["max"], lv["pref"]

    def chunk_cost(a, b):
        w = wcount(pts[a], pts[b])
        if w == 0:
            return 0.0
        c = W_LEN * ((w - tgt) / tgt) ** 2
        if w < mn:
            c += W_RUNT * (mn - w)
        if w == mx + 1:
            # like tools/chunk.py: max may stretch by one word when
            # fusion leaves no clean cut — cheaper than emitting a runt
            c += 30.0
        elif w > mx + 1:
            c += W_OVER * (w - mx - 1) + 30.0
        return c

    def cut_cost(j):                      # cost of cutting AT pts[j]
        s = strengths[pts[j]]
        c = W_CUT * (100 - s) / 100.0
        if s < pref:
            c += W_PREF * (pref - s) / 100.0
        return c

    INF = float("inf")
    best = [INF] * m
    back = [0] * m
    best[0] = 0.0
    for j in range(1, m):
        for i in range(j):
            c = best[i] + chunk_cost(i, j) + (cut_cost(j) if j < m - 1 else 0)
            if c < best[j] - 1e-12:
                best[j], back[j] = c, i
    cuts, j = [], m - 1
    while j > 0:
        i = back[j]
        if i > 0:
            cuts.append(pts[i])
        j = i
    return sorted(cuts)


def desperation_cuts(toks, wcount, a, b, mx, cfg):
    """A span with NO fusion-clean break inside that still exceeds
    max+1 words: demote fusion to a tiebreak (mirrors tools/chunk.py's
    desperation).  Cut at word-boundary positions, balancing halves."""
    if wcount(a, b) <= mx + 1:
        return []
    cands = []
    for k in range(a + 1, b):
        cur, prev = toks[k], toks[k - 1]
        if cur.is_punct and cur.text not in cfg["open_quotes"]:
            continue
        if prev.is_punct and prev.text in cfg["open_quotes"]:
            continue
        if prev.idx + len(prev.text) == cur.idx:
            continue                    # not a whitespace word boundary
        cands.append(k)
    if not cands:
        return []
    k = min(cands, key=lambda k: abs(wcount(a, k) - wcount(k, b)))
    return sorted([k]
                  + desperation_cuts(toks, wcount, a, k, mx, cfg)
                  + desperation_cuts(toks, wcount, k, b, mx, cfg))


def derive_levels(sent, strengths, cfg):
    """Top-down nested cuts per level. Returns {level: sorted cut list}."""
    n = len(list(sent))
    text = sent.doc.text
    toks = list(sent)

    def char_of(k):
        return toks[k].idx if k < n else sent.end_char

    def wcount(a, b):
        return word_count(text[char_of(a):char_of(b)])

    all_pos = sorted(strengths)
    prev_cuts = []
    out = {}
    for level in LEVEL_ORDER:
        lv = LEVELS[level]
        new_cuts = list(prev_cuts)
        bounds = [0] + prev_cuts + [n]
        for a, b in zip(bounds, bounds[1:]):
            inside = [p for p in all_pos if a < p < b]
            new_cuts += dp_segment(inside, strengths, wcount, a, b, lv)
        # anything still over max+1 had no candidate inside: desperation
        forced = []
        ncs = sorted(new_cuts)
        for a, b in zip([0] + ncs, ncs + [n]):
            forced += desperation_cuts(toks, wcount, a, b, lv["max"], cfg)
        prev_cuts = sorted(new_cuts + forced)
        out[level] = prev_cuts
    return out


def halving_break(strengths, sent):
    """Strongest break nearest the sentence middle (progressive rung)."""
    if not strengths:
        return None
    n = len(list(sent))
    return max(strengths, key=lambda k: (strengths[k], -abs(k - n / 2)))


# --------------------------------------------------------------- driver

def spans_to_text(sent, cuts):
    toks = list(sent)
    n = len(toks)
    bounds = [0] + cuts + [n]
    doc = sent.doc
    raw = []
    for a, b in zip(bounds, bounds[1:]):
        start = toks[a].idx
        end = toks[b].idx if b < n else sent.end_char
        raw.append(doc.text[start:end])
    assert "".join(raw) == doc.text[sent.start_char:sent.end_char], \
        f"reconstruction failed: {sent.text!r}"
    return [r.strip() for r in raw if r.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--lang", choices=["de", "en"], default="de")
    ap.add_argument("--skip-until", default=None)
    ap.add_argument("--stop-at", default=None)
    ap.add_argument("--sections", type=int, default=None,
                    help="only process the first N sections")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import spacy
    cfg = base.LANG_CFG[args.lang]
    nlp = spacy.load(args.model or cfg["model"], disable=["ner"])

    text = base.clean(base.strip_gutenberg(
        Path(args.infile).read_text(encoding="utf-8")))
    secs = base.sections_of(text, args.skip_until, args.stop_at)
    if args.sections:
        secs = secs[:args.sections]
    if not secs:
        sys.exit("no sections found")

    out_secs, fails = [], 0
    for title, paras in secs:
        sents_out = []
        for doc in nlp.pipe(paras):
            for sent in doc.sents:
                if not sent.text.strip():
                    continue
                strengths = break_strengths(sent, cfg)
                try:
                    cuts = derive_levels(sent, strengths, cfg)
                    levels = {lvl: spans_to_text(sent, cuts[lvl])
                              for lvl in LEVEL_ORDER}
                except AssertionError:
                    fails += 1
                    levels = {lvl: [sent.text.strip()] for lvl in LEVEL_ORDER}
                    cuts = {lvl: [] for lvl in LEVEL_ORDER}
                half = halving_break(strengths, sent)
                sents_out.append({
                    "text": " ".join(sent.text.split()),
                    "breaks": sorted(
                        [[k, v] for k, v in strengths.items()]),
                    "cuts": {lvl: cuts[lvl] for lvl in LEVEL_ORDER},
                    "levels": levels,
                    "half": half,
                    "halves": (spans_to_text(sent, [half]) if half else None),
                })
        out_secs.append({"title": title or "", "sentences": sents_out})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"lang": args.lang, "source": args.infile,
         "levels": {k: {kk: vv for kk, vv in v.items()}
                    for k, v in LEVELS.items()},
         "sections": out_secs},
        ensure_ascii=False, indent=1), encoding="utf-8")

    n_sents = sum(len(s["sentences"]) for s in out_secs)
    print(f"sections={len(out_secs)} sentences={n_sents} "
          f"reconstruction_failures={fails} -> {out}")


if __name__ == "__main__":
    main()
