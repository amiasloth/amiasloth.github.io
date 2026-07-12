#!/usr/bin/env python3
"""
tools/ai/gde3.py — Mistral `g_de` pass: one-line simple-German learner
definitions (~A2) for a book's study lemmas (00_v3_overview §5, second
AI pass).  Shared plumbing in mistral3.py.

Why: the reader shows `g_de || g_en` in the gloss bubble (already
wired); a same-language definition keeps the learner inside German.
Side benefit: the model sees the first-occurrence SENTENCE and is told
to trust it over the dictionary gloss — this catches FreeDict's wrong
senses (grimm's Holzhacker = "dirty player") that the deterministic
pipeline cannot.

Flow (same shape as emoji3):
  gde3.py --book <id>  ->  build/g_de_<id>.json      {lemma: definition}
                           build/g_de_<id>_rejected.txt
  owner review         ->  tools/v3/maps/g_de_<id>.json
  rebuild              ->  gloss3 auto-loads the map and adds `g_de`
                           to words[lemma] (additive key per the
                           pinned schema; reader falls back to g_en
                           where absent).

Two-stage generate -> grade + deterministic pre-checks (headword leak,
length, emptiness).  German books only — for English books `g_en` is
already same-language.

Usage:
  export MISTRAL_API_KEY=...
  python3 tools/ai/gde3.py --book kafka
"""

import argparse

from mistral3 import (HERE, Cache, add_common_args, first_sentences,
                      load_book, meta, nfc_lower, out_path, run_stage,
                      write_map, write_rejected)

MAX_CHARS = 100          # one short line; grader enforces simplicity


def leaks_headword(lemma, definition):
    """True when the definition gives the word away: the lemma itself,
    or (for longer lemmas) its stem without the inflection ending,
    appears in the definition.  'aufmachen' -> stem 'aufmach' catches
    'aufmacht'; 'gehen' stays full-match only, so 'gehört' is fine."""
    d = nfc_lower(definition)
    k = nfc_lower(lemma)
    if k in d:
        return True
    stem = k[:-2] if len(k) > 6 else k
    return len(stem) >= 5 and stem in d


def sane(lemma, definition):
    d = definition.strip()
    if not d or len(d) > MAX_CHARS or "\n" in d:
        return False
    return not leaks_headword(lemma, d)


def MOCK_GEN(it, lang):
    return f"eine einfache Sache ({it['lemma'][:2]}…)" \
        if len(it["lemma"]) % 3 else ""


def MOCK_GRADE(it, lang):
    return True


def run(args):
    lang, book, gloss = load_book(args.book)
    if lang != "de":
        raise SystemExit(f"{args.book} is lang={lang!r}: g_de is for "
                         "German books (en books gloss en->en already)")
    words = gloss["words"]
    first_sent = first_sentences(book, gloss["study_by_sent"])

    items = [{"lemma": k, "gloss": w["g_en"],
              "sentence": first_sent.get(k, "")}
             for k, w in sorted(words.items())]
    if args.limit:
        items = items[:args.limit]
    print(f"{args.book} ({lang}): {len(items)} study lemmas")

    cache = Cache(HERE / "cache" / f"g_de_{args.book}.jsonl",
                  args.mock, archive=args.new_cache)
    rejected = []

    gen = run_stage(
        items, key_of=lambda it: it["lemma"],
        prompt_name="gde_gen_v1", cache=cache, args=args, lang=lang,
        temperature=0.3, mock_answer=MOCK_GEN, default="")

    to_grade = []
    for it in items:
        d = (gen.get(it["lemma"]) or "").strip().rstrip(".")
        if not d:
            continue
        if not sane(it["lemma"], d):
            rejected.append((it["lemma"], it["gloss"], d, "sanity"))
            continue
        to_grade.append({**it, "g_de": d})

    grade = run_stage(
        to_grade, key_of=lambda it: f"{it['lemma']}|{it['g_de']}",
        prompt_name="gde_grade_v1", cache=cache, args=args, lang=lang,
        temperature=0.0, mock_answer=MOCK_GRADE, default=False)

    kept = {}
    for it in to_grade:
        if grade.get(f"{it['lemma']}|{it['g_de']}") is True:
            kept[it["lemma"]] = it["g_de"]
        else:
            rejected.append((it["lemma"], it["gloss"], it["g_de"],
                             "grader"))

    write_map(out_path(args, f"g_de_{args.book}.json"),
              meta(args, {"kind": "g_de", "book": args.book, "lang": lang,
                          "source_hash": gloss["source_hash"],
                          "review_to":
                              f"tools/v3/maps/g_de_{args.book}.json"}),
              kept)
    write_rejected(out_path(args, f"g_de_{args.book}_rejected.txt"),
                   rejected)
    print(f"kept {len(kept)}/{len(items)} "
          f"(rejected fall back to g_en in the reader)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True, help="book id (books.json)")
    add_common_args(ap)
    run(ap.parse_args())


if __name__ == "__main__":
    main()
