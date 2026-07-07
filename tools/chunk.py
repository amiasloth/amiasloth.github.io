#!/usr/bin/env python3
"""
Deterministic phrase chunker for Zzzpeak.

Splits a Project Gutenberg plain-text book into bite-size, grammatically
meaningful phrases using spaCy dependency parsing (local, pinned model —
same input always yields the same output; no AI service involved).

The goal: every chunk is a piece of the dependency tree that hangs
together — a constituent, or a head with its function words — so that
the chunk sequence mirrors the grammatical skeleton of the sentence.

Three structural principles (instead of many positional special cases):

1. FUSION — function words never stand alone; each fuses in a direction
   read off the tree. Articles, attributive modifiers, prepositions,
   conjunctions, subordinators, relative pronouns, pre-verbal
   auxiliaries and infinitive markers fuse RIGHT (they open chunks,
   never close them). Verb particles ("set out", "fährt ... ab") and
   post-verbal material fuse LEFT. A cut inside a fusion is invalid —
   for ranked candidates and for the fallback splitter alike.

2. VERB CLUSTERS — a contiguous run of verbs/auxiliaries is atomic:
   "hätte zurückgeben müssen", "geschrieben hatte", "could reinforce".

3. COHERENCE — a bounded preference, not an absolute constraint
   (in a verb-final clause EVERY pre-verb chunk points at the distant
   verb; multi-root is normal). A fragment — an atom that is neither
   a complete subtree nor an anchored clause piece nor a coordination
   continuation — merges toward the ADJACENT atom that contains its
   head, and only if the result stays within the level's max.
   "und dringend" + "Hilfe brauche." (4 ≤ 5) merges; "und der Wolf
   noch immer" + a 7-word PP (12 > 5) stays; "but it had", whose head
   ("thought") is not adjacent, stays.

4. MERGE GATES — a merged chunk must still read as a slice of ONE
   phrase.  (a) Single anchor: every token whose head lies outside
   the chunk must point at the SAME external head — "with pink eyes
   ran close" mixes a piece of the subject NP with the verb and is
   never created.  (b) No severed complement: a merge must not end
   the chunk on a verb whose complements follow — "for the hot day
   made | her feel …" keeps the verb with what it governs instead.
   Gates constrain MERGES only; atoms produced by cutting are always
   legitimate output ("so bekam er" in a verb-second clause is fine).

Chunking then works bottom-up:

  ATOMIZE  cut at every valid boundary found in the tree, ranked:
             rank 0  after ; : — (strong punctuation)
             rank 1  clause boundaries (both edges of adverbial /
                     relative / complement clauses, subordinators,
                     verbal coordination)
             rank 2  phrase boundaries (verb-attached prepositional
                     phrases, infinitive "to"/"zu", appositions)
             rank 3  weak boundaries (subject/object noun phrases,
                     verb groups, bare commas, noun coordination)
             rank 4  tight-binding cuts (noun-attached infinitives
                     and noun-attached PPs: "a pair | of gloves" —
                     mergeable up to the hard max, not just the target)
  MERGE    coherence first, then glue atoms weakest-boundary-first
           while the result fits the level's target size (rank-4
           boundaries: the hard max) and passes the merge gates;
           fragments below the minimum are absorbed by a neighbour
           (leaning right: conjunctions and quotes belong to what
           follows; preferring the direction the gates allow)
  FALLBACK anything still over the hard maximum is split at the valid
           boundary nearest its midpoint; if fusion must be sacrificed,
           prefer the start of an embedded phrase ("Vor dem | in dem
           großen und reichen Oderbruchdorfe") over a blind mid cut

Chunk size comes from --level:

  beginner       min 2 / target 3 / max 5     "of sitting | by her sister"
  intermediate   min 2 / target 5 / max 8
  advanced       min 3 / target 8 / max 12

Hard invariant, asserted for every sentence:
  "".join(raw_chunks) == raw_sentence_text
so the chunking provably never loses or alters a character.

Usage:
  python chunk.py --in sources/alice_part01.txt --lang en \
      --id alice --title "Alice's Adventures in Wonderland" \
      --level beginner --skip-until "^CHAPTER I\\." --out ../data/en/alice.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from emoji_map import EMOJI

# ---------------------------------------------------------------- language config

LANG_CFG = {
    "en": {
        "model": "en_core_web_sm",
        # deps whose subtree marks a clause (cut at both edges)
        "clause_deps": {"advcl", "ccomp", "relcl", "acl", "parataxis", "csubj"},
        # subordinator token itself ("that", "because", "when", ...)
        "marker_deps": {"mark"},
        # coordination token ("and", "but") — strong cut when it joins verbs
        "coord_deps": {"cc"},
        "conj_deps": {"conj"},
        "phrase_deps": {"appos"},
        # weak boundaries: noun-phrase and verb-group left edges
        "subj_deps": {"nsubj", "nsubjpass", "csubj", "expl"},
        "obj_deps": {"dobj", "obj", "attr", "dative", "oprd"},
        "aux_deps": {"aux", "auxpass", "neg"},
        "inf_tags": {"TO"},             # infinitive marker "to"
        # function relations: token fuses with its head's side
        "fused_deps": {"det", "poss", "predet", "amod", "compound",
                       "nummod", "quantmod", "aux", "auxpass", "neg",
                       "prt", "case", "expl"},
        "open_quotes": {"“", "‘", '"', "'", "("},
        "pull_quotes": {"“", "‘", "("},
    },
    "de": {
        "model": "de_core_news_lg",
        # TIGER-style labels used by the de_core_news models
        "clause_deps": {"rc", "oc", "par", "re"},
        "marker_deps": {"cp"},          # "dass", "weil", "wenn", ...
        "coord_deps": {"cd"},           # "und", "aber", "oder"
        "conj_deps": {"cj"},
        "phrase_deps": {"app"},
        "subj_deps": {"sb", "sbp"},
        "obj_deps": {"oa", "da", "og"},
        "aux_deps": set(),              # German verb bracket: skip verb groups
        "inf_tags": {"PTKZU"},          # infinitive marker "zu"
        "fused_deps": {"nk", "pm", "ng", "svp", "nmc", "ac", "adc",
                       "cm", "avc", "pnc"},   # pnc: never cut inside
                                              # a proper name
        # German book style: „low“ or »guillemets pointing inward«
        "open_quotes": {"„", "‚", "»", '"', "'", "("},
        "pull_quotes": {"„", "‚", "»", "("},
    },
}

LEVELS = {
    "starter":      {"min_words": 1, "target_words": 2, "max_words": 3},
    "beginner":     {"min_words": 2, "target_words": 3, "max_words": 5},
    "intermediate": {"min_words": 2, "target_words": 5, "max_words": 8},
    "advanced":     {"min_words": 3, "target_words": 8, "max_words": 12},
}

STRONG_PUNCT = {";", ":", "—", "–", "--"}

# relative / interrogative pronouns (en: who, which; de: der/die/das, wer)
REL_PRON_TAGS = {"WDT", "WP", "WP$", "PRELS", "PRELAT", "PWS", "PWAT", "PWAV"}


# ---------------------------------------------------------------- gutenberg + structure

def strip_gutenberg(text):
    """Keep only the text between the *** START and *** END markers."""
    m = re.search(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    if m:
        text = text[m.end():]
    m = re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    if m:
        text = text[: m.start()]
    return text


def clean(text):
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\[Illustration:?[^\]]*\]", " ", text)
    text = text.replace("_", "")                # gutenberg italics markers
    text = text.replace("~", "")                # gesperrt/emphasis markers
    text = text.replace("=", "")                # gutenberg bold markers
    text = text.replace("·", " ")               # decorative mid-dots (1920s
    text = re.sub(r" {2,}", " ", text)          # typesetting: Der·treue·Johannes)
    text = re.sub(r"(\w)--(\w)", r"\1 — \2", text)
    text = text.replace("--", "—")
    return text


def paragraphs(text):
    """Yield paragraphs with hard line-wraps unwrapped."""
    for block in re.split(r"\n\s*\n", text):
        p = re.sub(r"\s+", " ", block).strip()
        if p:
            yield p


HEADING_RE = re.compile(r"^(CHAPTER|KAPITEL|BOOK|BUCH)\b", re.IGNORECASE)

# lowercase function words don't count against a title's capitalization
# ("Der Wolf und die sieben jungen Geisslein" is a title)
TITLE_STOP = {
    "der", "die", "das", "und", "oder", "von", "vom", "dem", "den", "des",
    "im", "in", "an", "auf", "zu", "zur", "zum", "mit", "bei", "um", "für",
    "aus", "nach", "vor", "über", "unter", "un", "syner", "einem", "einer",
    "ein", "eine",
    "the", "and", "of", "in", "a", "an", "or", "to", "at", "on", "for",
}


def looks_like_title(p):
    """Short paragraph, no sentence-final punctuation -> section title."""
    if HEADING_RE.match(p):
        return True
    if re.fullmatch(r"[IVXLC]+\.", p):   # bare roman-numeral chapter: "II."
        return True
    words = p.split()
    if len(words) > 8 or len(p) > 60:
        return False
    if p[-1] in ".!?…,;:”’\"'«»‹›":
        return False
    if not p[0].isupper():
        return False
    letters = [w for w in words if any(c.isalpha() for c in w)]
    if not letters:
        return False
    content = [w for w in letters if w.lower() not in TITLE_STOP]
    if not content:
        return False
    caps = sum(1 for w in content if w[0].isupper())
    # German titles capitalize only nouns ("Das tapfere Schneiderlein"):
    # accept half-capitalized content words if the final noun is capitalized
    if content[-1][0].isupper() and caps / len(content) >= 0.5:
        return True
    return caps / len(content) >= 0.7


def sections_of(text, skip_until, stop_at):
    """Split cleaned text into (title, [paragraphs]) sections."""
    if skip_until:
        m = re.search(skip_until, text, re.MULTILINE)
        if m:
            text = text[m.start():]
    if stop_at:
        m = re.search(stop_at, text, re.MULTILINE)
        if m:
            text = text[: m.start()]

    secs, title, buf = [], None, []
    for p in paragraphs(text):
        if looks_like_title(p):
            if buf:
                secs.append((title, buf))
            title, buf = p, []
        else:
            buf.append(p)
    if buf:
        secs.append((title, buf))
    return secs


# ---------------------------------------------------------------- fusion + validity

def word_count(tokens):
    """Words as a reader sees them: a hyphenated compound
    ("Jack-in-the-box") is ONE word, not four."""
    n = 0
    for t in tokens:
        if t.is_punct or t.is_space:
            continue
        d = t.doc
        if (t.i >= 2 and d[t.i - 1].text == "-"
                and d[t.i - 1].whitespace_ == ""
                and d[t.i - 2].whitespace_ == ""):
            continue                # glued continuation: …-of, …-box
        n += 1
    return n


def fuse_dir(t, cfg):
    """Direction a function word fuses: 'R' (with what follows), 'L'
    (with what precedes), None (free content word). Read off the tree."""
    if t.is_punct or t.is_space:
        return None
    # conjunctions, subordinators, relative pronouns open chunks —
    # they never close them
    if (t.pos_ in ("CCONJ", "SCONJ") or t.dep_ in cfg["coord_deps"]
            or t.dep_ in cfg["marker_deps"] or t.tag_ in REL_PRON_TAGS):
        return "R"
    # function relations fuse toward their head
    if t.dep_ in cfg["fused_deps"]:
        return "R" if t.head.i > t.i else "L"
    # tagger-proof: articles always lean on the coming noun
    if t.pos_ == "DET":
        return "R" if t.head.i > t.i else None
    if t.pos_ == "ADP":
        if t.n_rights > 0 or t.head.i > t.i:
            return "R"                  # preposition: keep what it governs
        if t.head.i < t.i:              # bare verb particle: "set out"
            return "L"
        return None
    # pronoun subject leans on its verb: "I shall", "she had"
    if t.pos_ == "PRON" and t.dep_ in cfg["subj_deps"] and t.head.i > t.i:
        return "R"
    # modifier directly before what it modifies: "noch immer", "very much"
    if t.pos_ in ("ADV", "NUM") and t.head.i == t.i + 1:
        return "R"
    return None


def good_cut(toks, i, cfg):
    """True if a cut before toks[i] is structurally valid."""
    p, t = toks[i - 1], toks[i]
    # never split a hyphenated compound ("out-of-the-way")
    if p.text == "-" or t.text == "-":
        return False
    if not (p.is_punct or p.is_space):
        if fuse_dir(p, cfg) == "R":
            return False
        # verb clusters are atomic: "hätte zurückgeben müssen"
        if p.pos_ in ("VERB", "AUX") and t.pos_ in ("VERB", "AUX"):
            return False
    if fuse_dir(t, cfg) == "L":
        return False
    return True


def conjunct_of(t, cfg):
    """The conjunct a coordination token introduces (its true fusion
    target): de attaches it below the conjunction, en beside it."""
    for c in t.children:
        if c.dep_ in cfg["conj_deps"]:
            return c
    for c in t.head.children:
        if c.dep_ in cfg["conj_deps"] and c.i > t.i:
            return c
    return None


def fragment_heads(toks, lo, hi, cfg):
    """Classify span [lo,hi). Returns [] if it hangs together: it is
    anchored (contains its own root), is a complete subtree, or is a
    coordination continuation ("pears, plums"). Otherwise it's a
    fragment ("und dringend", "weil seine Mutter") and the returned
    list holds the local indices of the external heads that would
    satisfy it — merge toward one of them, size permitting.

    NOTE: multiple siblings sharing a distant head are NORMAL (German
    verb-final clauses); a fragment is only mergeable, never invalid."""
    base = toks[0].i
    ext = []
    for k in range(lo, hi):
        t = toks[k]
        if t.is_punct or t.is_space:
            continue
        h = t.head.i - base
        if lo <= h < hi:
            continue                    # attached inside the span
        if t.dep_ in cfg["conj_deps"]:
            continue                    # coordination continuation: fine
        d = fuse_dir(t, cfg)
        if d == "R" and k < hi - 1:
            continue                    # fuses onto inside material
        if d == "L" and k > lo:
            continue
        ext.append((k, h))
    if not ext:
        return []                       # anchored or fully discounted
    if len(ext) >= 2:
        return [h for _, h in ext]      # several independent pieces
    # single root: complete iff its subtree covers the span's content
    rk, rh = ext[0]
    covered = {x.i - base for x in toks[rk].subtree}
    for k in range(lo, hi):
        t = toks[k]
        if k in covered or t.is_punct or t.is_space:
            continue
        if t.dep_ in cfg["conj_deps"]:
            continue
        # a coordinator/subordinator is excused if its conjunct is here
        c = conjunct_of(t, cfg)
        if c is not None and lo <= c.i - base < hi:
            continue
        return [rh]                     # stray material -> fragment
    return []                           # complete constituent


def merge_ok(toks, lo, hi):
    """May a MERGED chunk span [lo,hi)?  Two display-quality gates.

    A. Single anchor: every token whose head lies outside the span must
       point at the SAME external head.  Two different external heads
       mean the span mixes pieces of two different constituents —
       "with pink eyes ran close" (PP hangs off the subject noun, the
       verb off the main clause) must never be created by a merge.
       One external head is normal and fine: "for the hot day" (both
       "for" and "day" point at "made") is a perfect chunk.

    B. No severed complement: the span must not END on a verb that has
       dependents further right — "for the hot day made" tears "made"
       from "her feel …"; the verb belongs with what it governs.

    Gates constrain merges only.  Atoms produced by cutting are always
    legitimate output, so a verb-second clause piece like "so bekam er"
    can still appear — it just isn't manufactured by gluing."""
    base = toks[0].i
    exits = set()
    for k in range(lo, hi):
        t = toks[k]
        if t.is_punct or t.is_space:
            continue
        h = t.head.i - base
        if not (lo <= h < hi):
            exits.add(h)
    if len(exits) > 1:
        return False
    for k in range(hi - 1, lo - 1, -1):
        t = toks[k]
        if t.is_punct or t.is_space:
            continue
        if t.pos_ in ("VERB", "AUX") and any(
                not c.is_punct and c.i - base >= hi for c in t.children):
            return False
        break                           # only the last content token
    return True


# ---------------------------------------------------------------- chunking core

def candidate_cuts(sent, cfg):
    """Return {local_cut_index: best_rank}. A cut at i splits before token i."""
    toks = list(sent)
    n = len(toks)
    cands = {}

    def add(i, rank):
        # never start a chunk on punctuation: push the cut past it —
        # except an opening quote, which belongs to the chunk it opens
        while (i < n and (toks[i].is_punct or toks[i].is_space)
               and toks[i].text not in cfg["open_quotes"]):
            i += 1
        # pull the cut back over an opening quote so the quote starts
        # the new chunk instead of dangling off the previous one
        while i > 1 and (toks[i - 1].text in cfg["pull_quotes"]
                         or toks[i - 1].is_space):
            i -= 1
        if i <= 0 or i >= n:
            return
        if not good_cut(toks, i, cfg):
            return
        if rank < cands.get(i, 99):
            cands[i] = rank

    for t in toks:
        i = t.i - sent.start
        # rank 0: after strong punctuation
        if t.text in STRONG_PUNCT:
            add(i + 1, 0)
        # rank 1: clause subtree — both edges, so relative clauses don't
        # leak into the main verb; fusion/cluster rules veto edges that
        # land inside a verb complex ("geschrieben | hatte")
        if t.dep_ in cfg["clause_deps"]:
            add(t.left_edge.i - sent.start, 1)
            add(t.right_edge.i - sent.start + 1, 1)
        # rank 1: subordinator token starts the new chunk
        if t.dep_ in cfg["marker_deps"]:
            add(i, 1)
        # rank 1 / 3: coordination — strong between verbs, weak in lists
        if t.dep_ in cfg["coord_deps"]:
            head = t.head
            verbal = head.pos_ in ("VERB", "AUX") or any(
                c.dep_ in cfg["conj_deps"] and c.pos_ in ("VERB", "AUX")
                for c in head.children
            )
            add(i, 1 if verbal else 3)
        # rank 1: verbal conjunct left edge
        if t.dep_ in cfg["conj_deps"] and t.pos_ in ("VERB", "AUX"):
            add(t.left_edge.i - sent.start, 1)
        # rank 2 / 4: prepositional phrase (true preposition, not a
        # particle); binds tight when it modifies a noun — "a pair
        # of white kid gloves" wants to stay together up to the max
        if (t.pos_ == "ADP" and t.left_edge.i == t.i
                and t.n_rights > 0 and t.dep_ not in ("prt", "svp")):
            add(i, 4 if t.head.pos_ in ("NOUN", "PROPN", "PRON", "NUM")
                else 2)
        # rank 2 / 4: infinitive marker; binds tight when it modifies a
        # noun ("nothing to do", "some plea to justify")
        if t.tag_ in cfg["inf_tags"]:
            add(i, 4 if t.head.dep_ in ("acl", "relcl") else 2)
        # rank 2: apposition
        if t.dep_ in cfg["phrase_deps"]:
            add(t.left_edge.i - sent.start, 2)
        # rank 3: subject / object noun phrase left edge
        if t.dep_ in cfg["subj_deps"] or t.dep_ in cfg["obj_deps"]:
            add(t.left_edge.i - sent.start, 3)
        # rank 3: verb group left edge ("had peeped", "was reading")
        if (cfg["aux_deps"] and t.pos_ in ("VERB", "AUX")
                and t.dep_ not in cfg["aux_deps"]):
            vleft = min([c.i for c in t.children
                         if c.dep_ in cfg["aux_deps"] and c.i < t.i] + [t.i])
            add(vleft - sent.start, 3)
        # rank 3: after a bare comma
        if t.text == ",":
            add(i + 1, 3)

    return cands


def coherence_merge(toks, atoms, ranks, cfg, max_w):
    """Bounded coherence: a fragment merges toward the ADJACENT atom
    that contains one of its external heads, and only if the combined
    atom stays within max_w. A fragment whose head is not adjacent, or
    whose merge would overshoot, simply stays — it is a preference,
    never an obligation, so no unbounded merging and no giant atoms."""
    while len(atoms) > 1:
        merged = False
        for k, (lo, hi) in enumerate(atoms):
            heads = fragment_heads(toks, lo, hi, cfg)
            if not heads:
                continue
            for j in (k - 1, k + 1):    # adjacent atoms only
                if not 0 <= j < len(atoms):
                    continue
                jlo, jhi = atoms[j]
                if not any(jlo <= h < jhi for h in heads):
                    continue
                if word_count(toks[lo:hi]) \
                        + word_count(toks[jlo:jhi]) > max_w:
                    continue
                a = min(j, k)
                atoms[a] = (atoms[a][0], atoms[a + 1][1])
                del atoms[a + 1]
                del ranks[a]
                merged = True
                break
            if merged:
                break
        if not merged:
            break
    return atoms, ranks


def merge_atoms(wcs, ranks, min_w, target_w, max_w, span_ok=None):
    """Group adjacent atoms into chunks.

    wcs[i]      word count of atom i
    ranks[k]    rank of the boundary between atom k and k+1 (0 strongest)
    span_ok(a, b)  optional merge gate: may atoms [a,b) become ONE chunk?
                (chunk_sentence passes merge_ok over the token span)

    Pure function of plain lists — unit-testable without spaCy.
    Returns a list of (first_atom, last_atom_exclusive) groups.
    """
    groups = [[i, i + 1, wc] for i, wc in enumerate(wcs)]
    bounds = list(ranks)          # bounds[k] sits between groups[k], groups[k+1]

    def merge(k):
        groups[k] = [groups[k][0], groups[k + 1][1],
                     groups[k][2] + groups[k + 1][2]]
        del groups[k + 1]
        del bounds[k]

    def gated(k):
        return span_ok is not None and \
            not span_ok(groups[k][0], groups[k + 1][1])

    def joinable(k):
        r = bounds[k]
        if r <= 1:                # never merge over punctuation / clause
            return False          # boundaries here (pass 2 may, to rescue)
        # tight boundaries (rank 4: noun-attached PPs/infinitives) may
        # fill up to the hard max; everything else stops at the target
        limit = max_w if r >= 4 else target_w
        if groups[k][2] + groups[k + 1][2] > limit:
            return False
        return not gated(k)

    # pass 1: merge weakest boundaries first while the result fits
    while True:
        best = None
        for k, r in enumerate(bounds):
            if not joinable(k):
                continue
            # never merge across a boundary while an adjacent, even weaker
            # one is still JOINABLE — else weak cuts survive strong ones
            # (a neighbour that can never merge doesn't hold us hostage)
            if k > 0 and bounds[k - 1] > r and joinable(k - 1):
                continue
            if k + 1 < len(bounds) and bounds[k + 1] > r and joinable(k + 1):
                continue
            combined = groups[k][2] + groups[k + 1][2]
            key = (-r, combined, k)   # weakest rank, then smallest result
            if best is None or key < best[1]:
                best = (k, key)
        if best is None:
            break
        merge(best[0])

    # pass 2: absorb undersized fragments (may exceed the target and
    # ignore the gates if it must; prefers staying under max, then a
    # gate-clean result, then crossing the weakest boundary)
    while len(groups) > 1:
        k = next((k for k, g in enumerate(groups) if g[2] < min_w), None)
        if k is None:
            break
        options = []
        if k < len(groups) - 1:
            options.append(k)        # rightward first: conjunctions,
        if k > 0:                    # subordinators and quotes lean
            options.append(k - 1)    # onto what FOLLOWS them

        def score(j):
            combined = groups[j][2] + groups[j + 1][2]
            return (0 if combined <= max_w else 1,
                    1 if gated(j) else 0, -bounds[j])

        merge(min(options, key=score))

    return [(g[0], g[1]) for g in groups]


def fallback_split(toks, lo, hi, min_w, max_w, cfg):
    """Last resort for spans with no internal boundary: cut near the
    midpoint — at a structurally valid position if any exists."""
    if word_count(toks[lo:hi]) <= max_w:
        return [(lo, hi)]
    mid = (lo + hi) // 2

    def pick(fuse_ok, coherent, floor):
        best = None
        for i in range(lo + 1, hi):
            # a cut may land ON an opening quote, never right after one
            if (toks[i].is_punct or toks[i].is_space) \
                    and toks[i].text not in cfg["open_quotes"]:
                continue
            if toks[i - 1].text == "-":   # inside "out-of-the-way"
                continue
            if fuse_ok:
                if toks[i - 1].text in cfg["pull_quotes"]:
                    continue
                if not good_cut(toks, i, cfg):
                    continue
            if coherent and fragment_heads(toks, lo, i, cfg):
                continue            # would strand an incoherent fragment
            if word_count(toks[lo:i]) < floor \
                    or word_count(toks[i:hi]) < floor:
                continue
            if best is None or abs(i - mid) < abs(best - mid):
                best = i
        return best

    def pick_start(floor):
        """Fusion must be sacrificed (extended German NPs: 'Vor dem in
        dem großen und reichen Oderbruchdorfe Tschechin gelegenen …'
        has no valid interior cut).  Cut where a NEW embedded phrase
        begins — before a preposition, subordinator or coordinator —
        biggest phrase first, so the pieces are prefixes of ONE phrase
        ('Vor dem | in dem großen und reichen …') instead of a blind
        midpoint cut gluing two danglers ('Vor dem in dem | …')."""
        best = None
        for i in range(lo + 1, hi):
            t = toks[i]
            if t.is_punct or t.is_space:
                continue
            if toks[i - 1].text == "-":
                continue
            if not (t.pos_ in ("ADP", "SCONJ", "CCONJ")
                    or t.dep_ in cfg["marker_deps"]
                    or t.dep_ in cfg["coord_deps"]):
                continue
            if word_count(toks[lo:i]) < floor \
                    or word_count(toks[i:hi]) < floor:
                continue
            key = (-word_count(list(t.subtree)), abs(i - mid))
            if best is None or key < best[1]:
                best = (i, key)
        return best[0] if best else None

    # tiers: coherent cut > fusion-respecting cut (verb-final clauses
    # have no coherent prefix — normal, not an error) > fusion-
    # respecting with the size floor sacrificed (a 1-word chunk beats
    # a cut inside "a very | little way") > phrase-start cut >
    # any boundary at all
    best = (pick(True, True, min_w) or pick(True, False, min_w)
            or pick(True, False, 1)
            or pick_start(min_w) or pick_start(1)
            or pick(False, False, min_w) or pick(False, False, 1))
    if best is None:
        return [(lo, hi)]
    return (fallback_split(toks, lo, best, min_w, max_w, cfg)
            + fallback_split(toks, best, hi, min_w, max_w, cfg))


def chunk_sentence(sent, cfg, min_w, target_w, max_w):
    """Return list of raw text chunks that concatenate to the sentence."""
    toks = list(sent)
    n = len(toks)
    if n == 0:
        return []

    if word_count(toks) <= max_w:
        spans = [(0, n)]                       # short sentence stays whole
    else:
        cands = candidate_cuts(sent, cfg)
        cuts = sorted(cands)
        edges = [0] + cuts + [n]
        atoms = [(edges[k], edges[k + 1]) for k in range(len(edges) - 1)]
        ranks = [cands[c] for c in cuts]
        atoms, ranks = coherence_merge(toks, atoms, ranks, cfg, max_w)
        wcs = [word_count(toks[lo:hi]) for lo, hi in atoms]

        def span_ok(a, b):          # gate for merging atoms [a,b)
            return merge_ok(toks, atoms[a][0], atoms[b - 1][1])

        groups = merge_atoms(wcs, ranks, min_w, target_w, max_w, span_ok)
        spans = [(atoms[a][0], atoms[b - 1][1]) for a, b in groups]
        # anything still oversized had no internal boundary: cut by tokens
        spans = [s for lo, hi in spans
                 for s in fallback_split(toks, lo, hi, min_w, max_w, cfg)]

    doc = sent.doc
    raw = []
    for lo, hi in spans:
        start = toks[lo].idx
        end = toks[hi].idx if hi < n else sent.end_char
        raw.append(doc.text[start:end])

    # ---- hard invariant: nothing lost, nothing altered
    assert "".join(raw) == doc.text[sent.start_char:sent.end_char], \
        f"reconstruction failed: {sent.text!r}"
    return raw


def absorb_punct_chunks(chunks, cfg):
    """A chunk with no letters (a stray « or » that spaCy split into its
    own sentence) would render as a baffling lone-punctuation card.
    Glue opening quotes onto the following chunk, everything else onto
    the preceding one."""
    out = []
    prefix = ""
    for c in chunks:
        if not any(ch.isalnum() for ch in c["t"]):
            if all(ch in cfg["open_quotes"] for ch in c["t"]):
                prefix += c["t"]                # » opens what follows
            elif out:
                out[-1]["t"] += c["t"]          # « closes what precedes
                if not c.get("cont"):
                    out[-1].pop("cont", None)
            else:
                prefix += c["t"]
            continue
        if prefix:
            c["t"] = prefix + c["t"]
            prefix = ""
        out.append(c)
    if prefix and out:
        out[-1]["t"] += prefix
    return out


def emoji_for(span_tokens, lang):
    table = EMOJI.get(lang, {})
    for t in span_tokens:
        e = table.get(t.lemma_.lower()) or table.get(t.text.lower())
        if e:
            return e
    return None


# ---------------------------------------------------------------- driver

def build_book(args):
    import spacy

    cfg = LANG_CFG[args.lang]
    nlp = spacy.load(cfg["model"], disable=["ner"])

    lv = LEVELS[args.level]
    min_w = args.min_words or lv["min_words"]
    target_w = args.target_words or lv["target_words"]
    max_w = args.max_words or lv["max_words"]

    text = clean(strip_gutenberg(Path(args.infile).read_text(encoding="utf-8")))
    secs = sections_of(text, args.skip_until, args.stop_at)
    if not secs:
        sys.exit("no sections found — check --skip-until / --stop-at")

    out_secs, hist, n_sents, fails = [], {}, 0, 0
    for title, paras in secs:
        chunks = []
        for doc in nlp.pipe(paras):
            for sent in doc.sents:
                if not sent.text.strip():
                    continue
                n_sents += 1
                try:
                    raws = chunk_sentence(sent, cfg, min_w, target_w, max_w)
                except AssertionError:
                    fails += 1
                    raws = [sent.text]
                # map raw chunks back to token spans for emoji lookup
                pos = sent.start_char
                for j, r in enumerate(raws):
                    span = doc.char_span(pos, pos + len(r),
                                         alignment_mode="expand")
                    pos += len(r)
                    t = r.strip()
                    if not t:
                        continue
                    wc = len(t.split())
                    hist[wc] = hist.get(wc, 0) + 1
                    c = {"t": t}
                    if j < len(raws) - 1:
                        c["cont"] = 1          # sentence continues
                    e = emoji_for(span, args.lang) if span is not None else None
                    if e:
                        c["e"] = e
                    chunks.append(c)
        chunks = absorb_punct_chunks(chunks, cfg)
        if chunks:
            out_secs.append({"title": title or "", "chunks": chunks})

    book = {
        "id": args.id,
        "title": args.title,
        "lang": args.lang,
        "level": args.level,
        "source": args.source,
        "sections": out_secs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(book, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    # ---- report
    total = sum(hist.values())
    over = sum(v for k, v in hist.items() if k > max_w)
    print(f"[{args.id}/{args.level}] sections={len(out_secs)} "
          f"sentences={n_sents} chunks={total} reconstruction_failures={fails}")
    print(f"  words/chunk: " + " ".join(
        f"{k}:{hist[k]}" for k in sorted(hist)))
    print(f"  chunks over max_words ({max_w}): {over} "
          f"({100 * over / max(total, 1):.1f}%)  -> {out} "
          f"({out.stat().st_size // 1024} KB)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--lang", choices=list(LANG_CFG), required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--source", default="Project Gutenberg")
    ap.add_argument("--skip-until", default=None,
                    help="regex; drop everything before first match (TOC etc.)")
    ap.add_argument("--stop-at", default=None,
                    help="regex; drop everything from first match")
    ap.add_argument("--level", choices=list(LEVELS), default="beginner",
                    help="learner level; sets chunk size (default: beginner)")
    ap.add_argument("--min-words", type=int, default=None,
                    help="override level minimum")
    ap.add_argument("--target-words", type=int, default=None,
                    help="override level target")
    ap.add_argument("--max-words", type=int, default=None,
                    help="override level hard maximum")
    ap.add_argument("--model", default=None,
                    help="override the spaCy model for --lang")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.model:
        LANG_CFG[args.lang]["model"] = args.model
    build_book(args)


if __name__ == "__main__":
    main()
