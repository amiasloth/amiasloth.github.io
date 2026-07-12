#!/usr/bin/env python3
"""
tools/ai/gfill3.py — Mistral gloss-miss fill pass (00_v3_overview §5,
third AI pass).  Shared plumbing in mistral3.py.

The offline dictionary misses ~200-300 lemmas per book — mostly German
compounds (Abendschläfchen), archaic spellings and dialect: exactly the
words a learner cannot look up anywhere else.  gloss3 lists them in
tools/v3/build/gloss_misses_<id>.txt; this pass glosses them from word
formation + the first-occurrence sentence.

Flow (same shape as the other passes):
  gfill3.py --book <id> -> build/gloss_fill_<id>.json
                           {lemma: {"g_en":..., "g_de":...}}
                           + build/gloss_fill_<id>_rejected.txt
  owner review          -> tools/v3/maps/gloss_fill_<id>.json
  rebuild               -> gloss3 auto-loads the map: filled misses
                           become FULL study entries (words + freq +
                           study lists + emoji via the usual
                           precedence) instead of silent gaps.

Both fields graded independently: a kept g_en with a rejected g_de is
fine (entry ships without g_de).  Entries whose g_en fails are dropped
entirely — g_en is the required gloss field.  Proper names are refused
by prompt AND grader (ents are the reader's name channel, not the
glossary).

After baking fills, a later emoji3.py --book rerun sees the new words
as study lemmas and proposes emoji for them — run gfill first.

Usage:
  export MISTRAL_API_KEY=...
  python3 tools/ai/gfill3.py --book kafka
"""

import argparse

from gde3 import leaks_headword
from mistral3 import (HERE, ROOT, Cache, add_common_args, load_book,
                      meta, nfc_lower, out_path, run_stage, sentence_text,
                      write_map, write_rejected)

MAX_GEN = 60             # g_en: dictionary-style, short
MAX_GDE = 100            # g_de: one line


def read_misses(book_id):
    """lemma -> [surfaces] from tools/v3/build/gloss_misses_<id>.txt."""
    path = ROOT / "tools" / "v3" / "build" / f"gloss_misses_{book_id}.txt"
    if not path.is_file():
        raise SystemExit(f"{path} missing — build the book first")
    out = {}
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            lemma, _, surfaces = line.partition("\t")
            out[lemma] = [s.strip() for s in surfaces.split(",") if s.strip()]
    return out


def find_sentences(book, misses, cap=240):
    """lemma -> first sentence containing one of its surfaces.  Misses
    are not in study_by_sent (gloss3 skips them), so scan the tokens."""
    want = {}                                # surface_lower -> lemma
    for lemma, surfaces in misses.items():
        for s in surfaces:
            want.setdefault(nfc_lower(s), lemma)
    found = {}
    for sec in book["sections"]:
        for sent in sec["sentences"]:
            hit = [want[nfc_lower(t)] for t in sent["toks"]
                   if nfc_lower(t) in want]
            for lemma in hit:
                if lemma not in found:
                    found[lemma] = sentence_text(sent)[:cap]
    return found


def MOCK_GEN(it, lang):
    if len(it["lemma"]) % 3 == 0:
        return {"g_en": "", "g_de": ""}
    return {"g_en": "a mock gloss",
            "g_de": "eine einfache Sache" if lang == "de" else ""}


def MOCK_GRADE(it, lang):
    return {"g_en": True, "g_de": bool(it.get("g_de"))}


def run(args):
    lang, book, gloss = load_book(args.book)
    misses = read_misses(args.book)
    sents = find_sentences(book, misses)
    items = [{"lemma": k, "surfaces": ", ".join(v),
              "sentence": sents.get(k, "")}
             for k, v in sorted(misses.items())]
    if args.limit:
        items = items[:args.limit]
    print(f"{args.book} ({lang}): {len(items)} dictionary misses")

    cache = Cache(HERE / "cache" / f"gloss_fill_{args.book}.jsonl",
                  args.mock, archive=args.new_cache)
    rejected = []

    gen = run_stage(
        items, key_of=lambda it: it["lemma"],
        prompt_name="gfill_gen_v1", cache=cache, args=args, lang=lang,
        temperature=0.3, mock_answer=MOCK_GEN, default={})

    to_grade = []
    for it in items:
        r = gen.get(it["lemma"]) or {}
        g_en = (r.get("g_en") or "").strip().rstrip(".")
        g_de = (r.get("g_de") or "").strip().rstrip(".")
        if not g_en:
            continue                          # model passed — fine
        if len(g_en) > MAX_GEN or "\n" in g_en:
            rejected.append((it["lemma"], g_en, g_de, "sanity g_en"))
            continue
        if g_de and (len(g_de) > MAX_GDE or "\n" in g_de
                     or leaks_headword(it["lemma"], g_de)):
            rejected.append((it["lemma"], g_en, g_de, "sanity g_de"))
            g_de = ""                         # keep the entry, drop g_de
        to_grade.append({**it, "g_en": g_en, "g_de": g_de})

    grade = run_stage(
        to_grade, key_of=lambda it: f"{it['lemma']}|{it['g_en']}",
        prompt_name="gfill_grade_v1", cache=cache, args=args, lang=lang,
        temperature=0.0, mock_answer=MOCK_GRADE, default={})

    kept = {}
    for it in to_grade:
        g = grade.get(f"{it['lemma']}|{it['g_en']}") or {}
        if g.get("g_en") is True:
            entry = {"g_en": it["g_en"]}
            if it["g_de"] and g.get("g_de") is True:
                entry["g_de"] = it["g_de"]
            kept[it["lemma"]] = entry
        else:
            rejected.append((it["lemma"], it["g_en"], it["g_de"],
                             "grader"))

    write_map(out_path(args, f"gloss_fill_{args.book}.json"),
              meta(args, {"kind": "gloss-fill", "book": args.book,
                          "lang": lang,
                          "source_hash": gloss["source_hash"],
                          "review_to":
                              f"tools/v3/maps/gloss_fill_{args.book}.json"}),
              kept)
    write_rejected(out_path(args, f"gloss_fill_{args.book}_rejected.txt"),
                   rejected)
    print(f"kept {len(kept)}/{len(items)} "
          "(unfilled misses stay unglossed, as now)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True, help="book id (books.json)")
    add_common_args(ap)
    run(ap.parse_args())


if __name__ == "__main__":
    main()
