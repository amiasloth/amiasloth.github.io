#!/usr/bin/env python3
"""
tools/ai/emoji3.py — Mistral emoji-map passes (first AI pass of
00_v3_overview §5).  Shared plumbing (API, cache, stages, artifacts)
lives in mistral3.py; this file is the emoji-specific logic only.

Two products, two strictness levels (owner decisions 2026-07-12):

  --book <id>   STUDY lemmas of one book -> build/emoji_ai_<id>.json.
                The book fixes the sense, so the model sees gloss +
                first-occurrence sentence and may be reasonably liberal.
                Owner review -> tools/v3/maps/emoji_<id>.json (the
                existing gloss3 --emoji-map entry point; replaces the
                CLDR stand-in).  COMMON lemmas encountered in the book
                are ALSO proposed (book context helps find them), but
                graded with the strict GENERAL rubric and routed into
                the general candidates file — the per-book map stays
                study-only.

  --general     Frequent lemmas (wordfreq top-N, simplemma-lemmatised)
                -> build/emoji_general_candidates_<lang>.json.  No
                context, so an emoji is kept only for the DOMINANT
                sense and only when unambiguous — conservative by
                prompt AND by grader.  Owner review ->
                tools/v3/maps/emoji_general_<lang>.json, a new gloss3
                layer BELOW the curated emoji_map.py (hand-picked wins
                collisions, machine never edits the curated file).

Both passes are two-stage generate -> grade; anything failing sanity
checks or the grader is dropped — "empty beats bad" end to end.
Rejections are listed in build/emoji_*_rejected.txt for owner review.
Kafka-pilot tunings (2026-07-12): sanity ranges widened (arrows,
clocks, keycap digits), gender-ZWJ variants normalised to the base
emoji, graders relaxed to _v2, and PAIRS of emoji allowed for
compounds (Holzhacker 🪵🪓; cap 2 — see emoji_sane).

Usage (build machine or anywhere with the key):
  export MISTRAL_API_KEY=...
  python3 tools/ai/emoji3.py --book kafka
  python3 tools/ai/emoji3.py --general --lang de --top 5000
"""

import argparse
import json
import re
import sys

from mistral3 import (HERE, ROOT, Cache, add_common_args, first_sentences,
                      is_word, load_book, meta, nfc_lower, out_path,
                      run_stage, write_map, write_rejected)

sys.path.insert(0, str(ROOT / "tools"))            # emoji_map.py (read-only)
from emoji_map import EMOJI                        # noqa: E402

# Same guard as gloss3.py (schema rev 3.1): function words never carry
# emoji — they would fire on nearly every chunk.
EMOJI_FUNC_POS = {"DET", "PRON", "ADP", "CCONJ", "SCONJ", "CONJ",
                  "PART", "AUX"}

KEYCAP = re.compile(r"^[0-9#*]️?⃣$")


def is_emoji(s):
    """Loose filter in the spirit of emoji_map_gen3.py (♪ counts; ∈, @,
    ≡ not) — WIDENED 2026-07-12 after the kafka pilot rejected good
    picks: arrows (⬇ ↕), technical/clocks (⏱ ⌛), geometric (▶) are in;
    math operators stay out."""
    return any(ord(c) >= 0x1F000
               or 0x2600 <= ord(c) <= 0x27BF          # misc symbols
               or 0x2190 <= ord(c) <= 0x21FF          # arrows
               or 0x2300 <= ord(c) <= 0x23FF          # technical, clocks
               or 0x25A0 <= ord(c) <= 0x25FF          # geometric
               or 0x2B00 <= ord(c) <= 0x2BFF          # arrows/stars
               for c in s) and not any(0x2200 <= ord(c) <= 0x22FF
                                       for c in s)


def normalize_emoji(e):
    """Strip gender ZWJ suffixes: 🏃‍♂️ -> 🏃, 🕵️‍♂️ -> 🕵️.
    The base emoji means the same, renders everywhere (old devices show
    un-joined sequences as split glyphs), and weighs less.  Multi-person
    ZWJ emoji (👨‍👩‍👧‍👦) are left alone."""
    return re.sub(r"‍[♀♂]️?", "", e.strip())


def emoji_sane(e):
    """Deterministic pre-grade check.  '' is valid (means: none).
    At most TWO emoji units (owner 2026-07-12: pairs earn their keep on
    German compounds — Holzhacker 🪵🪓; the reader renders the raw
    string everywhere, so nothing else changes).  A ZWJ-joined sequence
    counts as one unit (🐦‍⬛, 👨‍👩‍👧 fine).  Keycap digits (8️⃣ for
    'acht') are allowed — for number words the digit IS the meaning."""
    if e == "":
        return True
    if KEYCAP.match(e):
        return True
    if len(e) > 10 or any(c.isspace() for c in e):
        return False
    if any(c.isascii() and c.isalnum() for c in e):
        return False
    core = [c for c in e                     # drop presentation marks
            if not (c == "️" or "\U0001f3fb" <= c <= "\U0001f3ff"
                    or c == "⃣")]
    n_zwj = core.count("‍")
    if len(core) - 2 * n_zwj > 2:            # units = bases - zwj merges
        return False
    return is_emoji(e)


def MOCK_GEN(it, lang):    # echo the curated map: realistic sparsity
    return EMOJI[lang].get(it["lemma"], "")


def MOCK_GRADE(it, lang):
    return True


# ------------------------------------------------------------ pipeline

def two_stage(items, kind, lang, cache, args, rejected):
    """items: [{"lemma","gloss"?,"sentence"?}] -> {lemma: emoji} kept.
    kind: 'book' (liberal) or 'general' (strict) — picks the prompts."""
    gen = run_stage(
        items, key_of=lambda it: it["lemma"],
        prompt_name=f"{kind}_gen_v2", cache=cache, args=args, lang=lang,
        temperature=0.15, mock_answer=MOCK_GEN, default="")

    to_grade = []
    for it in items:
        e = normalize_emoji(gen.get(it["lemma"]) or "")
        if e == "":
            continue
        if not emoji_sane(e):
            rejected.append((it["lemma"], it.get("gloss", ""), e, "sanity"))
            continue
        to_grade.append({**it, "emoji": e})

    grade = run_stage(
        to_grade, key_of=lambda it: f"{it['lemma']}|{it['emoji']}",
        prompt_name=f"{kind}_grade_v2", cache=cache, args=args, lang=lang,
        temperature=0.0, mock_answer=MOCK_GRADE, default=False)

    kept = {}
    for it in to_grade:
        if grade.get(f"{it['lemma']}|{it['emoji']}") is True:
            kept[it["lemma"]] = it["emoji"]
        else:
            rejected.append((it["lemma"], it.get("gloss", ""),
                             it["emoji"], "grader"))
    return kept


def merge_general_candidates(lang, kept, args, provenance):
    """Common/general keepers accumulate in ONE candidates file per
    language (merged across --book and --general runs, sorted)."""
    path = out_path(args, f"emoji_general_candidates_{lang}.json")
    existing = {}
    if path.exists():
        existing = {k: v for k, v in
                    json.loads(path.read_text("utf-8")).items()
                    if not k.startswith("_")}
    existing.update(kept)
    write_map(path, meta(args, {"kind": "general-candidates",
                                "lang": lang, "last_source": provenance}),
              existing)


def load_general_covered(lang):
    """Lemmas already carrying an emoji in the curated map or the
    reviewed general map — no need to re-propose them."""
    covered = set(EMOJI.get(lang, {}))
    reviewed = ROOT / "tools" / "v3" / "maps" / f"emoji_general_{lang}.json"
    if reviewed.exists():
        covered |= {k for k, v in
                    json.loads(reviewed.read_text("utf-8")).items()
                    if v and not k.startswith("_")}
    return covered


# ------------------------------------------------------------ --book

def run_book(args):
    lang, book, gloss = load_book(args.book)
    words = gloss["words"]
    study_by_sent = gloss["study_by_sent"]
    forms = gloss["forms"]

    first_sent = first_sentences(book, study_by_sent)

    # common-lemma collection mirrors gloss3's emoji_common walk (forms
    # resolves surface->key, so no runtime lemmatiser is needed here).
    from wordfreq import zipf_frequency
    commons = {}
    covered = load_general_covered(lang)
    ec = set(gloss.get("emoji_common", {}))
    for sec in book["sections"]:
        for sent in sec["sentences"]:
            ent_toks = set()
            for a, b, _ in sent.get("ents", []):
                ent_toks.update(range(a, b))
            orth = sent.get("orth", {})
            for i, tok in enumerate(sent["toks"]):
                if i in ent_toks or not is_word(tok):
                    continue
                if sent["pos"][i] in EMOJI_FUNC_POS:
                    continue
                key = forms.get(nfc_lower(orth.get(str(i), tok)))
                if (not key or key in words or key in commons
                        or key in covered or key in ec):
                    continue
                if zipf_frequency(key, lang) >= args.threshold:
                    commons[key] = True

    study_items = [{"lemma": k, "gloss": w["g_en"],
                    "sentence": first_sent.get(k, "")}
                   for k, w in sorted(words.items())]
    common_items = [{"lemma": k} for k in sorted(commons)]
    if args.limit:
        study_items = study_items[:args.limit]
        common_items = common_items[:args.limit]
    print(f"{args.book} ({lang}): {len(study_items)} study lemmas, "
          f"{len(common_items)} common candidates")

    rejected = []
    cache = Cache(HERE / "cache" / f"emoji_book_{args.book}.jsonl",
                  args.mock, archive=args.new_cache)
    kept_study = two_stage(study_items, "book", lang, cache, args, rejected)
    write_map(out_path(args, f"emoji_ai_{args.book}.json"),
              meta(args, {"kind": "book-study", "book": args.book,
                          "lang": lang,
                          "source_hash": gloss["source_hash"],
                          "review_to": f"tools/v3/maps/emoji_{args.book}.json"}),
              kept_study)

    rejected_c = []
    cache_g = Cache(HERE / "cache" / f"emoji_general_{lang}.jsonl",
                    args.mock, archive=args.new_cache)
    kept_common = two_stage(common_items, "general", lang, cache_g, args,
                            rejected_c)
    merge_general_candidates(lang, kept_common, args,
                             f"--book {args.book}")
    write_rejected(out_path(args, f"emoji_ai_{args.book}_rejected.txt"),
                   rejected + rejected_c)
    print(f"study kept {len(kept_study)}/{len(study_items)}; "
          f"common kept {len(kept_common)}/{len(common_items)} "
          "(-> general candidates)")


# ------------------------------------------------------------ --general

def run_general(args):
    lang = args.lang
    import simplemma
    from wordfreq import top_n_list
    covered = load_general_covered(lang)
    path = HERE / "build" / f"emoji_general_candidates_{lang}.json"
    if path.exists():                     # already decided in earlier runs
        covered |= {k for k in json.loads(path.read_text("utf-8"))
                    if not k.startswith("_")}
    seen, items = set(), []
    for w in top_n_list(lang, args.top):
        if not w.isalpha() or len(w) < 2:
            continue
        lemma = nfc_lower(simplemma.lemmatize(w, lang=lang))
        if lemma in seen or lemma in covered or len(lemma) < 2:
            continue
        seen.add(lemma)
        items.append({"lemma": lemma})
    if args.limit:
        items = items[:args.limit]
    print(f"general ({lang}): {len(items)} candidate lemmas "
          f"from top {args.top}")

    rejected = []
    cache = Cache(HERE / "cache" / f"emoji_general_{lang}.jsonl",
                  args.mock, archive=args.new_cache)
    kept = two_stage(items, "general", lang, cache, args, rejected)
    merge_general_candidates(lang, kept, args, f"--general top{args.top}")
    write_rejected(out_path(args, f"emoji_general_{lang}_rejected.txt"),
                   rejected)
    print(f"kept {len(kept)}/{len(items)} "
          f"(review -> tools/v3/maps/emoji_general_{lang}.json)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", help="book id (per books.json)")
    ap.add_argument("--general", action="store_true",
                    help="frequent-lemma general map candidates")
    ap.add_argument("--lang", default="de", choices=("de", "en"),
                    help="--general language (default de)")
    ap.add_argument("--top", type=int, default=5000,
                    help="--general: wordfreq top-N pool (default 5000)")
    ap.add_argument("--threshold", type=float, default=3.5,
                    help="zipf split study/common — keep = gloss3's")
    add_common_args(ap)
    args = ap.parse_args()
    if bool(args.book) == args.general:
        ap.error("exactly one of --book / --general")
    if args.book:
        run_book(args)
    else:
        run_general(args)


if __name__ == "__main__":
    main()
