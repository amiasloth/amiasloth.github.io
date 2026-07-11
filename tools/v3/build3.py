#!/usr/bin/env python3
"""
tools/v3/build3.py — v3 book-file builder.

Fills the PINNED schema (technical/v3_discussion/02_v3_data_schema.md,
rev 2): emits docs/data3/<lang>/<book>.json and updates
docs/data3/books.json.  Deterministic, offline, no AI, no audio.

Reuses (read-only):
  tools/chunk.py            — text prep (clean/strip_gutenberg/sections_of)
                              + language config
  tools/v3/chunk_hierarchy.py — the ACCEPTED candidate-B chunker
                              (breaks + strengths, DP level derivation,
                              progressive rungs)

Adds on top of the chunker: tokens-first-class storage (toks/sp), stable
content-hash sentence ids (+occ), paragraph-start flag `p`, per-token
UPOS, NER spans, strength-0 desperation breaks, per-book stats, and
provenance stamps.

Field omission (per pinned schema): every sentence field except
id/toks/sp is omitted when empty.  Additionally, empty per-level lists
inside `cuts` are omitted; missing `cuts`/level = whole sentence is one
chunk.  `orth` is only emitted when a reviewed substitution list is
passed via --orth-subst (none exists yet; gloss3.py's
orth_candidates report is the input for producing one).

Model default is base.LANG_CFG[lang]["model"] (German: de_core_news_lg).
Sandbox smoke runs pass --model de_core_news_sm; the `parse_model`
provenance stamp records this so a later lg rebuild visibly supersedes it.

Usage (German book, small batch):
  python3 build3.py --in ../build/kafka_utf8.txt --lang de --id kafka \
      --title "Die Verwandlung" --author "Franz Kafka" \
      --source "Project Gutenberg" --skip-until '^I\\.$' \
      [--model de_core_news_sm] [--sections N] \
      [--data-dir ../../docs/data3]

The difficulty label derivation is PROVISIONAL (documented at
difficulty_label()); tune thresholds once several books are built.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))        # tools/   (chunk.py)
sys.path.insert(0, str(HERE))               # tools/v3 (chunk_hierarchy.py)
import chunk as base                        # noqa: E402
import chunk_hierarchy as hier              # noqa: E402

SCHEMA = 3
LEVEL_ORDER_FINE = ["starter", "beginner", "intermediate", "advanced"]


# ------------------------------------------------------------ small helpers

def git_short():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=HERE, capture_output=True, text=True,
                             check=True).stdout.strip()
        return out or "0000000"
    except Exception:
        return "0000000"


def norm_text(s):
    """The schema's normalisation: NFC + whitespace-collapsed."""
    return " ".join(unicodedata.normalize("NFC", s).split())


def sent_id(normed):
    return hashlib.sha256(normed.encode("utf-8")).hexdigest()[:12]


def is_word(s):
    return any(ch.isalnum() for ch in s)


def reconstruct(toks, sp):
    return "".join(t + (" " if b == "1" else "")
                   for t, b in zip(toks, sp))


# ------------------------------------------------------------ per sentence

def sentence_unit(sent, cfg):
    """Raw per-sentence facts (pre-merge, pre-id).  Token positions are
    relative to the sentence start, as everywhere in the schema."""
    toks = list(sent)
    for t in toks:
        if t.is_space:
            raise ValueError(f"space token survived cleaning: {sent.text!r}")
        if t.whitespace_ not in ("", " "):
            raise ValueError(f"non-space whitespace after {t.text!r}")
    words = [t.text for t in toks]
    sp = ["1" if t.whitespace_ else "0" for t in toks]
    sp[-1] = "0"                            # sentence-final

    strengths = hier.break_strengths(sent, cfg)
    cuts = hier.derive_levels(sent, strengths, cfg)
    wcount = hier.make_wcount(sent)
    rungs = hier.progressive_rungs(sent, cuts["advanced"], strengths, wcount)

    # desperation cuts: in cuts but not in strengths -> baked as strength 0.
    # Levels nest, so cuts["starter"] is the union of all levels' cuts.
    forced = sorted(set(cuts["starter"]) - set(strengths))
    breaks = sorted([[k, s] for k, s in strengths.items()]
                    + [[k, 0] for k in forced])

    return {
        "toks": words,
        "sp": sp,                           # list of "0"/"1", joined later
        "pos": [t.pos_ for t in toks],
        "ents": [[e.start - sent.start, e.end - sent.start, e.label_]
                 for e in sent.ents],
        "breaks": breaks,
        "cuts": {lvl: list(cuts[lvl]) for lvl in LEVEL_ORDER_FINE},
        "rungs": [list(r) for r in rungs],
        "para_start": False,                # set by caller
    }


def shift_unit(u, k):
    """Shift all token indices in u by +k (word-less prefix was glued on)."""
    u["breaks"] = [[p + k, s] for p, s in u["breaks"]]
    u["cuts"] = {lvl: [p + k for p in ps] for lvl, ps in u["cuts"].items()}
    u["rungs"] = [[p + k for p in r] for r in u["rungs"]]
    u["ents"] = [[a + k, b + k, lab] for a, b, lab in u["ents"]]


def absorb_wordless(units):
    """spaCy sometimes emits a stray quote mark as its own 'sentence'
    (same artifact tools/chunk.py + chunk_hierarchy.py absorb at their
    levels).  Token-level version: glue a word-less unit onto the END of
    the previous unit (closing mark), or as a PREFIX of the next one.
    Appending never invalidates indices; prefixing shifts them."""
    out, prefix = [], None

    def glue_prefix(v, u):
        k = len(u["toks"])
        v["toks"] = u["toks"] + v["toks"]
        v["pos"] = u["pos"] + v["pos"]
        v["sp"] = u["sp"][:-1] + ["1"] + v["sp"]
        shift_unit(v, k)
        v["para_start"] = v["para_start"] or u["para_start"]

    for u in units:
        if not any(is_word(w) for w in u["toks"]):
            if out:                          # closing mark: ends what precedes
                p = out[-1]
                p["sp"] = p["sp"][:-1] + ["1"] + u["sp"]
                p["toks"] += u["toks"]
                p["pos"] += u["pos"]
            elif prefix is None:
                prefix = u
            else:                            # two in a row: merge them
                glue_prefix(u, prefix)
                prefix = u
            continue
        if prefix is not None:
            glue_prefix(u, prefix)
            prefix = None
        out.append(u)
    return out


def finalize(u, orth_subst):
    """Unit -> schema sentence object (occ added later, book-wide)."""
    recon = reconstruct(u["toks"], u["sp"])
    normed = norm_text(recon)
    if recon != normed:                      # invariant 1, build side
        raise AssertionError(f"reconstruction not normalised: {recon!r}")

    d = {"id": sent_id(normed)}
    if u["para_start"]:
        d["p"] = 1
    d["toks"] = u["toks"]
    d["sp"] = "".join(u["sp"])
    d["pos"] = u["pos"]
    if u["ents"]:
        d["ents"] = u["ents"]
    if u["breaks"]:
        d["breaks"] = u["breaks"]
    cuts = {lvl: ps for lvl, ps in u["cuts"].items() if ps}
    if cuts:
        d["cuts"] = cuts
    if u["rungs"]:
        d["rungs"] = u["rungs"]
    if orth_subst:
        orth = {str(i): orth_subst[t] for i, t in enumerate(u["toks"])
                if t in orth_subst}
        if orth:
            d["orth"] = orth
    d["_text"] = normed                      # internal, stripped before write
    d["_words"] = sum(1 for w in recon.split() if is_word(w))
    return d


# ------------------------------------------------------------ stats

def vocab_profile(sent_dicts, lang):
    """Share of unique non-entity lemmas below zipf 4.0 (simplemma +
    wordfreq — same stack as gloss3.py)."""
    import simplemma
    from wordfreq import zipf_frequency
    lemmas = set()
    for d in sent_dicts:
        ent_toks = set()
        for a, b, _ in d.get("ents", []):
            ent_toks.update(range(a, b))
        for i, t in enumerate(d["toks"]):
            if i in ent_toks or not is_word(t):
                continue
            lemmas.add(simplemma.lemmatize(t, lang=lang).lower())
    if not lemmas:
        return 0.0
    rare = sum(1 for l in lemmas if zipf_frequency(l, lang) < 4.0)
    return round(rare / len(lemmas), 3)


def difficulty_label(avg_len, rare_share):
    """PROVISIONAL derivation — tune once several books are built.
    Long sentences and rare vocabulary each push the label up."""
    score = avg_len / 8.0 + rare_share / 0.15   # ~1.0 each at "easy" refs
    if score >= 4.5:
        return "advanced"
    if score >= 3.0:
        return "intermediate"
    return "beginner"


# ------------------------------------------------------------ driver

def build(args):
    cfg = hier.build_cfg(args.lang)
    model = args.model or base.LANG_CFG[args.lang]["model"]

    import spacy
    nlp = spacy.load(model)                  # full pipeline: parser + NER

    raw = Path(args.infile).read_text(encoding="utf-8")
    source_hash = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    text = base.clean(base.strip_gutenberg(raw))
    secs = base.sections_of(text, args.skip_until, args.stop_at)
    if args.sections:
        secs = secs[: args.sections]
    if not secs:
        sys.exit("no sections found")

    orth_subst = {}
    if args.orth_subst:
        orth_subst = json.loads(Path(args.orth_subst).read_text("utf-8"))

    out_secs = []
    for title, paras in secs:
        units = []
        for doc in nlp.pipe(paras):
            first = True
            for sent in doc.sents:
                if not sent.text.strip():
                    continue
                u = sentence_unit(sent, cfg)
                u["para_start"] = first
                first = False
                units.append(u)
        sents = [finalize(u, orth_subst) for u in absorb_wordless(units)]
        out_secs.append({"title": title or "", "sentences": sents})

    # occ + invariant 4 (id uniqueness / loud collision)
    seen = {}                                # id -> (text, count)
    for sec in out_secs:
        for d in sec["sentences"]:
            t, c = seen.get(d["id"], (d["_text"], 0))
            if t != d["_text"]:
                sys.exit(f"HASH COLLISION on {d['id']}: {t!r} vs {d['_text']!r}")
            if c:
                d["occ"] = c
            seen[d["id"]] = (t, c + 1)

    # stats
    all_sents = [d for sec in out_secs for d in sec["sentences"]]
    n_sents = len(all_sents)
    n_words = sum(d["_words"] for d in all_sents)
    chunks = {lvl: sum(len(d.get("cuts", {}).get(lvl, [])) + 1
                       for d in all_sents) for lvl in LEVEL_ORDER_FINE}
    avg_len = round(n_words / n_sents, 1) if n_sents else 0.0
    rare_share = vocab_profile(all_sents, args.lang)
    stats = {"sentences": n_sents, "words": n_words, "chunks": chunks,
             "avg_sentence_len": avg_len, "vocab_below_zipf4": rare_share}
    difficulty = difficulty_label(avg_len, rare_share)

    for d in all_sents:
        del d["_text"], d["_words"]

    levels_hdr = {lvl: {"min": hier.LEVELS[lvl]["min"],
                        "target": hier.LEVELS[lvl]["target"],
                        "max": hier.LEVELS[lvl]["max"],
                        "pref": hier.LEVELS[lvl]["pref"]}
                  for lvl in LEVEL_ORDER_FINE}

    generator = f"build3.py@{git_short()}"
    book = {
        "schema": SCHEMA, "generator": generator,
        "source_hash": source_hash, "parse_model": model,
        "id": args.book_id, "title": args.title, "author": args.author,
        "lang": args.lang, "levels": levels_hdr, "stats": stats,
        "sections": out_secs,
    }

    data_dir = Path(args.data_dir)
    book_path = data_dir / args.lang / f"{args.book_id}.json"
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text(json.dumps(book, ensure_ascii=False,
                                    separators=(",", ":")), encoding="utf-8")

    # books.json — update-or-insert this book's entry, keep the rest
    idx_path = data_dir / "books.json"
    if idx_path.exists():
        index = json.loads(idx_path.read_text("utf-8"))
    else:
        index = {"schema": SCHEMA, "generator": generator, "books": []}
    index["schema"] = SCHEMA
    index["generator"] = generator
    entry = {"id": args.book_id, "title": args.title, "author": args.author,
             "lang": args.lang, "levels": LEVEL_ORDER_FINE,
             "source": args.source, "difficulty": difficulty,
             "stats": stats, "audio": None}
    index["books"] = [b for b in index["books"] if b["id"] != args.book_id]
    index["books"].append(entry)
    index["books"].sort(key=lambda b: (b["lang"], b["id"]))
    idx_path.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    n_desp = sum(1 for d in all_sents for _, s in d.get("breaks", []) if s == 0)
    print(f"{args.book_id}: sections={len(out_secs)} sentences={n_sents} "
          f"words={n_words} desperation_breaks={n_desp} "
          f"difficulty={difficulty} model={model}")
    print(f"  -> {book_path}\n  -> {idx_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--lang", choices=["de", "en"], default="de")
    ap.add_argument("--id", dest="book_id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--author", default="")
    ap.add_argument("--source", default="Project Gutenberg")
    ap.add_argument("--skip-until", default=None)
    ap.add_argument("--stop-at", default=None)
    ap.add_argument("--sections", type=int, default=None,
                    help="only the first N sections (small-batch runs)")
    ap.add_argument("--model", default=None,
                    help="spaCy model override (default: lang's lg default)")
    ap.add_argument("--orth-subst", default=None,
                    help="reviewed JSON substitution list {archaic: modern}")
    ap.add_argument("--data-dir",
                    default=str(HERE.parent.parent / "docs" / "data3"))
    build(ap.parse_args())


if __name__ == "__main__":
    main()
