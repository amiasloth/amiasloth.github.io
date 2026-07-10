#!/usr/bin/env python3
"""
Candidate B experiment: break-point hierarchy, baked levels — v2.

v2 after owner review (see DIAGNOSIS.md): the DP + nesting machinery
was validated, the STRENGTH SCORING was naive.  This version ports the
intent of tools/chunk.py's German rule layer into the scoring — not
verbatim, improved where the diagnosis showed gaps in either design:

ported from tools/chunk.py (same intent):
  - full fuse_dir: pronoun-after-verb ("stand er", "verwandelte sich"),
    pronoun-before-its-verb, PTKNEG before verb, ADV/NUM directly
    before head, ADP direction, hyphen compounds, look-through-punct
    for stranded coordinators ("und, | weil …")
  - modal bracket: "kann … kommen" (oc under VMFIN) is ONE predicate,
    never a clause boundary
  - closing-quote → narration seam; opening quotes pull the cut back
  - severed-verb penalty (merge gate B, as a DP cost not a hard gate)
  - punctuation-only chunks are impossible (word-less span = ∞ cost)
  - PP binds tight when noun-attached, loose when verb-attached

improved beyond tools/chunk.py (diagnosis findings):
  - clause detection covers TIGER mo-clauses (Als/wenn/weil/daß …):
    any verb-headed non-root subtree with its own subordinator/finite
    verb is a clause — both edges strong.  tools/chunk.py only knew
    {rc, oc, par, re} and leaned on comma rank-3 to compensate.
  - commas are CLASSIFIED, not flat: clause comma ≈ strong (incl. the
    verb-second resumption ", fand er sich"), apposition comma mid,
    list comma inside an NP weak ("gewölbten, braunen, … Bauch" must
    not be severed from its noun).
  - subject/object NPs contribute BOTH edges (the NP|verb seam existed
    only as desperation before: "… dünnen Beine | flimmerten").
  - paired em-dashes: opening dash cuts BEFORE, closing dash cuts
    AFTER (incl. trailing punct) — no more "—," chunks.
  - words = tokens containing a letter/digit ("—," is 0 words).
  - progressive rungs are a MERGE LADDER over the advanced chunks
    (round-2 fix): rung cuts ⊆ advanced cuts, successive rungs nest,
    targets total/2, total/3, … so rung count adapts to sentence
    length; only distinct intermediate steps are emitted (the app
    appends the level's own chunks and the whole sentence, so nothing
    ever repeats).

Levels still derive top-down (advanced → starter) via the DP length
balancer, so levels NEST by construction, and the reconstruction
invariant still holds per level.

Usage:
    python3 chunk_hierarchy.py --in <kafka_utf8.txt> --lang de \
        --skip-until '^I\\.$' --out out/hierarchy_kafka.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True                      # keep tools/ untouched
TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
import chunk as base                                # reuse text prep + cfg

STRONG_PUNCT = base.STRONG_PUNCT
REL_PRON_TAGS = base.REL_PRON_TAGS

LEVEL_ORDER = ["advanced", "intermediate", "beginner", "starter"]
LEVELS = {
    #                min  target  max   strength preference
    "advanced":     dict(min=3, target=8, max=12, pref=80),
    "intermediate": dict(min=2, target=5, max=8,  pref=55),
    "beginner":     dict(min=2, target=3, max=5,  pref=30),
    "starter":      dict(min=2, target=2, max=3,  pref=0),
}

VERBISH = {"VERB", "AUX"}
FINITE_TAGS = {"VVFIN", "VAFIN", "VMFIN", "VBD", "VBZ", "VBP", "MD"}

# DP cost weights
W_LEN = 10.0          # squared relative deviation from target
W_CUT = 8.0           # weak-break usage
W_PREF = 6.0          # break below the level's preferred strength
W_RUNT = 50.0         # per word below min
W_OVER = 1e5          # per word above max+1
W_STRETCH = 30.0      # flat cost for the max+1 stretch (fusion-locked)
SEVER_PENALTY = 35    # strength malus for cutting a verb from its
                      # rightward complements (merge gate B as a cost)

RUNG_MAX = 14         # sentences ≤ this get no progressive rung


# --------------------------------------------------------------- fusion

def fuse_dir(t, cfg):
    """Port of tools/chunk.py fuse_dir (de-relevant parts, same intent):
    'R' = token opens what follows (may not end a chunk),
    'L' = token belongs to what precedes (may not start a chunk)."""
    if t.is_punct or t.is_space:
        return None
    if (t.pos_ in ("CCONJ", "SCONJ") or t.dep_ in cfg["coord_deps"]
            or t.dep_ in cfg["marker_deps"] or t.tag_ in REL_PRON_TAGS
            or t.tag_ in cfg["inf_tags"]):
        return "R"
    # negation belongs to the verb it negates: "nicht | kommen" never
    if (t.tag_ == "PTKNEG" and t.i + 1 < len(t.doc)
            and t.doc[t.i + 1].pos_ in VERBISH):
        return "R"
    if t.dep_ in cfg["fused_deps"]:
        return "R" if t.head.i > t.i else "L"
    if t.pos_ == "DET":
        return "R" if t.head.i > t.i else None
    if t.pos_ == "ADP":
        if t.n_rights > 0 or t.head.i > t.i:
            return "R"                  # preposition keeps what it governs
        if t.head.i < t.i:
            return "L"                  # bare verb particle
        return None
    # pronoun before its verb leans forward ("aber es | vergessen hatte")
    if (t.pos_ == "PRON" and t.head.i > t.i
            and (t.dep_ in cfg["subj_deps"] or t.dep_ in cfg["obj_deps"])):
        return "R"
    # pronoun directly AFTER its verb hugs it: V2 inversion ("stand er")
    # and clitic reflexives ("verwandelte sich")
    if (t.pos_ == "PRON" and t.head.i == t.i - 1
            and t.head.pos_ in VERBISH
            and (t.dep_ in cfg["subj_deps"] or t.dep_ in cfg["obj_deps"])):
        return "L"
    # right bracket of an analytic verb form leans on its clause:
    # "… diese Plage des Reisens auferlegt," must not be cut before
    # "auferlegt" — the participle closes the "ist … auferlegt" bracket
    if (t.dep_ == "oc" and t.tag_ in BRACKET_TAGS and t.head.i < t.i
            and not any(c.dep_ == "pm" or c.tag_ == "PTKZU"
                        for c in t.children)):
        return "L"
    # modifier directly before what it modifies: "noch immer",
    # "panzerartig harten", "ein wenig"
    if t.pos_ in ("ADV", "NUM") and t.head.i == t.i + 1:
        return "R"
    if t.pos_ in ("ADV", "ADJ") and t.head.i > t.i and t.head.pos_ == "ADJ":
        return "R"
    return None


def prev_content(toks, k):
    """Last non-punct/space token strictly before k (or None)."""
    j = k - 1
    while j >= 0 and (toks[j].is_punct or toks[j].is_space):
        j -= 1
    return toks[j] if j >= 0 else None


def valid_break(toks, k, cfg, dash_role):
    """Is a cut between toks[k-1] and toks[k] fusion-clean?"""
    prev, cur = toks[k - 1], toks[k]
    if cur.is_space:
        return False
    # hyphenated compounds are atomic
    if prev.text == "-" or cur.text == "-":
        return False
    # chunk may not start with punctuation, except an opening quote or
    # an OPENING dash (paired-dash logic)
    if cur.is_punct:
        if cur.text in ("—", "–"):
            if dash_role.get(k) != "open":
                return False
        elif cur.text not in cfg["open_quotes"]:
            return False
    # an opening quote/paren/dash stays with what follows
    if prev.is_punct and prev.text in cfg["open_quotes"] \
            and (prev.text not in ("—", "–") or dash_role.get(k - 1) == "open"):
        return False
    # fusion: look through punctuation to the last content token, so a
    # comma can't smuggle a stranded coordinator ("und, | weil …")
    pc = prev if not (prev.is_punct or prev.is_space) \
        else prev_content(toks, k)
    if pc is not None and fuse_dir(pc, cfg) == "R" \
            and (pc is prev or pc.pos_ in ("CCONJ", "SCONJ")):
        return False
    if not cur.is_punct and fuse_dir(cur, cfg) == "L":
        return False
    # verb clusters are atomic
    if prev.pos_ in VERBISH and cur.pos_ in VERBISH:
        return False
    return True


# --------------------------------------------------------------- clauses

BRACKET_TAGS = {"VVPP", "VAPP", "VMPP", "VVINF", "VAINF", "VMINF"}


def is_verb_bracket(t):
    """oc participle/bare infinitive under a finite verb: an analytic
    verb form ("kann … kommen", "hat … gesehen", "ist … auferlegt",
    "wird … geöffnet") — ONE predicate, not a clause.  zu-infinitives
    (VVIZU / with a pm child) stay clauses: cutting before "auf der
    rechten Seite zu schlafen" is good.  Generalizes tools/chunk.py's
    modal-only exception — its merge gates caught the non-modal cases;
    the DP has no gates, so the scoring must know."""
    return (t.dep_ == "oc" and t.tag_ in BRACKET_TAGS
            and t.head.pos_ in VERBISH
            and not any(c.dep_ == "pm" or c.tag_ == "PTKZU"
                        for c in t.children))


def is_clause_root(t, cfg):
    """A token heading a clause-like subtree (improved beyond
    tools/chunk.py: TIGER hangs adverbial clauses as plain `mo`)."""
    if t.dep_ in cfg["clause_deps"]:
        return not is_verb_bracket(t)
    # verb-headed non-root subtree with its own subordinator or its own
    # finite verb = an embedded clause the label didn't announce
    if t.pos_ in VERBISH and t.dep_ not in ("ROOT",) \
            and t.head.i != t.i and not is_verb_bracket(t):
        if any(c.dep_ in cfg["marker_deps"] for c in t.children):
            return True                 # "Als … erwachte", "wenn … hob"
        if t.tag_ in FINITE_TAGS and t.dep_ == "cj":
            return True                 # coordinated finite clause
    return False


def severs_verb_tail(toks, k, cfg):
    """Would a cut at k part a verb from rightward complements it
    governs (merge gate B)?  Benign relations (PPs, adverbs, particles,
    coordination) don't count — "ging | zum Fenster" is normal."""
    pc = prev_content(toks, k)
    if pc is None or pc.pos_ not in VERBISH:
        return False
    benign = cfg["benign_tail"]
    return any(not c.is_punct and c.i >= toks[k].i
               and c.dep_ not in benign for c in pc.children)


def dash_roles(toks):
    """Pair em-dashes within the sentence: alternating open/close.
    A trailing unpaired dash acts as an opener (mid-sentence colon-ish
    dash: "sein Herz, — und eines Morgens …")."""
    roles, open_ = {}, None
    for i, t in enumerate(toks):
        if t.text in ("—", "–"):
            if open_ is None:
                roles[i], open_ = "open", i
            else:
                roles[i], open_ = "close", None
    return roles


# --------------------------------------------------------------- strengths

def comma_class(toks, k, cfg, clause_edge):
    """Strength of a cut right after a comma (position k)."""
    cur = toks[k]
    # verb-second resumption: ", fand er sich" — the fronted clause
    # ends, the main clause verb resumes.  Always a real seam.
    if cur.tag_ in FINITE_TAGS and cur.pos_ in VERBISH:
        return 85
    if k in clause_edge:
        return 85
    # finite verb immediately BEFORE the comma: German verb-final
    # clause just ended ("… ein wenig hob," / "… Träumen erwachte,").
    # Parse-independent — protects the canonical cut even when the
    # parser mis-hangs material on that verb.
    pc = prev_content(toks, k)
    if pc is not None and pc.i == toks[k - 1].i - 1 \
            and pc.pos_ in VERBISH and pc.tag_ in FINITE_TAGS:
        return 85
    # list comma inside a noun phrase: next content word is another
    # attributive adjective or a coordinated nominal — severing it from
    # its noun confuses ("gewölbten, braunen, | … Bauch")
    if cur.pos_ in ("ADJ",) and cur.head.pos_ in ("NOUN", "PROPN", "ADJ"):
        return 15
    if cur.dep_ in cfg["conj_deps"] and cur.pos_ in ("NOUN", "PROPN",
                                                     "ADJ", "NUM"):
        return 15
    # apposition and everything else: usable, mid-strength
    if cur.dep_ in cfg["phrase_deps"]:
        return 60
    return 50


def break_strengths(sent, cfg):
    """{position k: strength} for every fusion-clean break point."""
    toks = list(sent)
    n = len(toks)
    b0 = sent.start
    droles = dash_roles(toks)

    def span_of(t):
        return t.left_edge.i - b0, t.right_edge.i - b0

    def push(k):
        """Normalize an after-the-subtree edge past trailing punctuation
        (tools/chunk.py add() does the same): the clause ends at 'hob'
        but the CUT goes after 'hob,' — never before the comma."""
        while k < n and toks[k].is_punct and not (
                toks[k].text in cfg["open_quotes"]
                and (toks[k].text not in ("—", "–")
                     or droles.get(k) == "open")):
            k += 1
        return k

    clause_edge, left_edges, right_edges = set(), {}, {}
    for t in toks:
        if t.is_punct or t.is_space:
            continue
        lo, hi = span_of(t)
        if is_clause_root(t, cfg):
            clause_edge.add(lo)
            clause_edge.add(push(hi + 1))
        sig = None
        if t.dep_ in cfg["subj_deps"] or t.dep_ in cfg["obj_deps"]:
            sig = 45
            re_ = push(hi + 1)          # NP right edge: the NP|verb seam
            if 0 < re_ < n:
                right_edges[re_] = max(right_edges.get(re_, 0), 45)
        elif t.dep_ == "mo" and t.pos_ != "ADP" and t.head.pos_ in VERBISH:
            sig = 30
        elif t.dep_ not in cfg["fused_deps"]:
            sig = 20
        if sig and 0 < lo < n:
            left_edges[lo] = max(left_edges.get(lo, 0), sig)

    out = {}
    for k in range(1, n):
        if not valid_break(toks, k, cfg, droles):
            continue
        prev, cur = toks[k - 1], toks[k]
        s = 5
        # ---- parse-independent punctuation, strongest first
        if prev.is_punct and prev.text in STRONG_PUNCT \
                and prev.text not in ("—", "–"):
            s = 100
        if cur.text in ("—", "–") and droles.get(k) == "open":
            s = 100                     # cut BEFORE an opening dash
        if prev.text in ("—", "–") and droles.get(k - 1) == "close":
            s = 100                     # cut AFTER a closing dash
        if prev.text == "(" or cur.text == "(":
            s = max(s, 100 if cur.text == "(" else s)
        if prev.text == ")":
            s = max(s, 100)
        # closing quote (looking through trailing punct) = speech seam
        j = k - 1
        while j > 0 and toks[j].is_punct and \
                toks[j].text not in cfg["close_quotes"]:
            j -= 1
        if toks[j].is_punct and toks[j].text in cfg["close_quotes"]:
            s = max(s, 90)
        # ---- clauses
        if k in clause_edge:
            s = max(s, 85)
        if cur.dep_ in cfg["marker_deps"]:
            s = max(s, 80)
        if cur.dep_ in cfg["coord_deps"]:
            verbal = (cur.head.pos_ in VERBISH
                      or any(c.dep_ in cfg["conj_deps"]
                             and c.pos_ in VERBISH
                             for c in cur.head.children)
                      or any(c.dep_ in cfg["conj_deps"]
                             and c.pos_ in VERBISH
                             for c in cur.children))
            s = max(s, 80 if verbal else 40)
        if cur.dep_ in cfg["conj_deps"] and cur.pos_ in VERBISH:
            s = max(s, 80)
        # ---- commas, classified
        list_comma = False
        if prev.text == ",":
            cc = comma_class(toks, k, cfg, clause_edge)
            list_comma = cc <= 15
            s = max(s, cc)
        # ---- phrases
        if cur.pos_ == "ADP" and cur.left_edge.i == cur.i \
                and cur.n_rights > 0 and cur.dep_ not in ("svp",):
            noun_attached = cur.head.pos_ in ("NOUN", "PROPN", "PRON", "NUM")
            s = max(s, 10 if noun_attached else 65)
        if cur.tag_ in cfg["inf_tags"]:
            s = max(s, 10 if cur.head.dep_ in ("rc", "acl", "relcl") else 65)
        if cur.dep_ in cfg["phrase_deps"]:
            s = max(s, 60)
        # ---- NP / modifier / subtree edges
        s = max(s, left_edges.get(k, 0), right_edges.get(k, 0))
        # a list comma inside an NP stays weak no matter what generic
        # edge signals say — severing "braunen," from its noun confuses
        if list_comma and s < 80:
            s = 15
        # ---- gate B as a cost: cutting a verb from its complements —
        # but clause edges / clause commas / strong punctuation are
        # canonical seams; the parser sometimes mis-hangs material on a
        # clause-final verb, so seams ≥ 85 are exempt
        if k not in clause_edge and s < 85 \
                and severs_verb_tail(toks, k, cfg):
            s = max(1, s - SEVER_PENALTY)
        out[k] = s
    return out


# --------------------------------------------------------------- DP balancer

def dp_segment(positions, strengths, wcount, lo, hi, lv):
    """Choose cuts inside token-span [lo, hi) minimizing length badness
    + cut cost.  Returns chosen cut positions (possibly empty)."""
    pts = [lo] + positions + [hi]
    m = len(pts)
    tgt, mn, mx, pref = lv["target"], lv["min"], lv["max"], lv["pref"]

    def chunk_cost(a, b):
        w = wcount(pts[a], pts[b])
        if w == 0:
            return 1e9                  # punct-only chunk: never
        c = W_LEN * ((w - tgt) / tgt) ** 2
        if w < mn:
            c += W_RUNT * (mn - w)
        if w == mx + 1:
            c += W_STRETCH              # fusion-locked stretch, like
        elif w > mx + 1:                # tools/chunk.py's max+1 rule
            c += W_OVER * (w - mx - 1) + W_STRETCH
        return c

    def cut_cost(j):
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
    """Span with NO fusion-clean break inside exceeding max+1: demote
    fusion to a tiebreak (tools/chunk.py desperation).  Prefer not to
    sever a verb from its complements; balance halves."""
    if wcount(a, b) <= mx + 1:
        return []
    cands = []
    for k in range(a + 1, b):
        cur, prev = toks[k], toks[k - 1]
        if cur.is_punct or cur.is_space:
            continue
        if prev.text == "-" or cur.text == "-":
            continue
        if prev.idx + len(prev.text) == cur.idx:
            continue                    # not a whitespace word boundary
        cands.append(k)
    if not cands:
        return []
    k = min(cands, key=lambda k: (severs_verb_tail(toks, k, cfg),
                                  abs(wcount(a, k) - wcount(k, b))))
    return sorted([k]
                  + desperation_cuts(toks, wcount, a, k, mx, cfg)
                  + desperation_cuts(toks, wcount, k, b, mx, cfg))


def derive_levels(sent, strengths, cfg):
    """Top-down nested cuts per level. Returns {level: sorted cut list}."""
    toks = list(sent)
    n = len(toks)
    wcount = make_wcount(sent)

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
        forced = []
        ncs = sorted(new_cuts)
        for a, b in zip([0] + ncs, ncs + [n]):
            forced += desperation_cuts(toks, wcount, a, b, lv["max"], cfg)
        prev_cuts = sorted(new_cuts + forced)
        out[level] = prev_cuts
    return out


# --------------------------------------------------------------- rungs

def dp_rung(positions, strengths, wcount, lo, hi, target):
    """Light DP for one rung segment: choose cuts from `positions`
    (all of them advanced cuts) minimizing squared deviation from the
    target part size + a small preference for strong seams.  No hard
    caps — the advanced level already enforced those."""
    pts = [lo] + positions + [hi]
    m = len(pts)

    def chunk_cost(a, b):
        w = wcount(pts[a], pts[b])
        return W_LEN * ((w - target) / target) ** 2

    def cut_cost(j):
        return W_CUT * (100 - strengths.get(pts[j], 50)) / 100.0

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


def progressive_rungs(sent, adv_cuts, strengths, wcount):
    """Merge ladder OVER the advanced chunks (see DIAGNOSIS.md round 2):
    every rung's cuts are a subset of the advanced cuts, successive
    rungs nest, and only DISTINCT intermediate steps are emitted —
    never the whole sentence, never the advanced chunking itself (the
    app appends those ends of the ladder and dedups by cut set).

    Rung r targets parts of ~total/(r+1) words (halves, thirds,
    quarters, …), so rung count adapts to sentence length: short
    sentences get no rung, monsters get several."""
    n = len(list(sent))
    total = wcount(0, n)
    if not adv_cuts or total <= RUNG_MAX:
        return []

    rungs = []
    prev = []
    for denom in range(2, len(adv_cuts) + 2):
        target = total / denom
        if target < LEVELS["advanced"]["target"]:
            break
        cuts = list(prev)
        bounds = [0] + prev + [n]
        for a, b in zip(bounds, bounds[1:]):
            inside = [p for p in adv_cuts if a < p < b]
            cuts += dp_rung(inside, strengths, wcount, a, b, target)
        cuts = sorted(cuts)
        if cuts == list(adv_cuts):
            break                       # ladder reached the level itself
        if cuts and cuts != prev:
            rungs.append(cuts)
        prev = cuts
    return collapse_ladder(adv_cuts, rungs, n)


def collapse_ladder(adv_cuts, rungs, n):
    """Drop rungs whose merges are INDEPENDENT of the next coarser
    step's merges (owner feedback round 3): climbing the ladder,
    step F→M and step M→C commute when no chunk C merges contains a
    boundary that F→M removed — then M teaches nothing on the way to C
    and the learner can jump straight from F to C.  A rung survives
    only if the next step merges something it built."""
    seq = [set(adv_cuts)] + [set(r) for r in reversed(rungs)] + [set()]
    i = 1
    while i < len(seq) - 1:
        F, M, C = seq[i - 1], seq[i], seq[i + 1]
        removed_1 = F - M               # boundaries dissolved by F→M
        removed_2 = M - C               # boundaries dissolved by M→C
        cbounds = [0] + sorted(C) + [n]
        interacts = False
        for a, b in zip(cbounds, cbounds[1:]):
            if any(a < k < b for k in removed_2) \
                    and any(a < k < b for k in removed_1):
                interacts = True        # C merges a chunk M's step built
                break
        if interacts:
            i += 1
        else:
            del seq[i]                  # independent: jump F → C
    return [sorted(c) for c in reversed(seq[1:-1])]


# --------------------------------------------------------------- driver

def absorb_punct_sentences(sents):
    """spaCy sometimes splits a stray « or » into its own 'sentence'
    (tools/chunk.py absorb_punct_chunks handles the same artifact at
    chunk level).  Glue a word-less sentence onto its neighbour: a
    closing mark onto the END of the previous sentence, anything else
    as a PREFIX of the next one."""
    out = []
    prefix = ""
    for s in sents:
        if not any(ch.isalnum() for ch in s["text"]):
            if out:                     # closing mark: ends what precedes
                out[-1]["text"] += " " + s["text"]
                for lvl in out[-1]["levels"]:
                    out[-1]["levels"][lvl][-1] += s["text"]
                for r in out[-1]["rungs"]:
                    r[-1] += s["text"]
            else:
                prefix += s["text"]
            continue
        if prefix:
            s["text"] = prefix + s["text"]
            for lvl in s["levels"]:
                s["levels"][lvl][0] = prefix + s["levels"][lvl][0]
            for r in s["rungs"]:
                r[0] = prefix + r[0]
            prefix = ""
        out.append(s)
    return out


def make_wcount(sent):
    toks = list(sent)
    n = len(toks)
    text = sent.doc.text

    def char_of(k):
        return toks[k].idx if k < n else sent.end_char

    def wcount(a, b):
        return sum(1 for w in text[char_of(a):char_of(b)].split()
                   if any(ch.isalnum() for ch in w))
    return wcount


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
    ap.add_argument("--sections", type=int, default=None)
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
                wcount = make_wcount(sent)
                try:
                    cuts = derive_levels(sent, strengths, cfg)
                    levels = {lvl: spans_to_text(sent, cuts[lvl])
                              for lvl in LEVEL_ORDER}
                    rungs = [spans_to_text(sent, r)
                             for r in progressive_rungs(
                                 sent, cuts["advanced"], strengths,
                                 wcount)]
                except AssertionError:
                    fails += 1
                    levels = {lvl: [sent.text.strip()] for lvl in LEVEL_ORDER}
                    cuts = {lvl: [] for lvl in LEVEL_ORDER}
                    rungs = []
                sents_out.append({
                    "text": " ".join(sent.text.split()),
                    "breaks": sorted(
                        [[k, v] for k, v in strengths.items()]),
                    "cuts": {lvl: cuts[lvl] for lvl in LEVEL_ORDER},
                    "levels": levels,
                    "rungs": rungs,
                })
        sents_out = absorb_punct_sentences(sents_out)
        out_secs.append({"title": title or "", "sentences": sents_out})

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"lang": args.lang, "source": args.infile, "version": 2,
         "levels": {k: dict(v) for k, v in LEVELS.items()},
         "sections": out_secs},
        ensure_ascii=False, indent=1), encoding="utf-8")

    n_sents = sum(len(s["sentences"]) for s in out_secs)
    print(f"sections={len(out_secs)} sentences={n_sents} "
          f"reconstruction_failures={fails} -> {out}")


if __name__ == "__main__":
    main()
