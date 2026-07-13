#!/usr/bin/env python3
"""
tools/ai/unified3.py — THE one AI pass per book (07 rework, owner
decisions 2026-07-12).  Replaces gfill3, gde3 and emoji3 --book;
emoji3 --general survives for the offline tier.  Shared plumbing in
mistral3.py.

What it does, in one generation stage (no grade stage — the pilot's
grader rejected 7/100 with ~4 real catches and missed the worst error;
deterministic sanity + the review report replace it):

- Candidates: EVERY content-POS (NOUN/VERB/ADJ/ADV), non-entity lemma
  in the book, via the gloss `forms` map — including current dictionary
  misses (subsumes gfill3).  First-occurrence sentence attached; the
  model gets NO dictionary input (FreeDict poisoned emoji3: grimm
  Holzhacker "dirty player" -> ⛹ shipped).
- Batches of 40, temperature 0.2, prompt prompts/unified_gen_v1.txt ->
  {lemma: {"d": same-language definition, "e": emoji or ""}}.
- Sanity v2 (fixes the pilot's false-rejects): rejoin stripped ZWJ
  people sequences (sippschaft 👨👩👧👦 -> 👨‍👩‍👧‍👦) instead of
  rejecting; allow multi-keycap runs (fourteenth 1️⃣4️⃣); keep the
  headword-leak and length checks on `d`.

Artifacts (NO review gate — auto-bake + forced spot-check):
  build/unified_<id>.json        {lemma: {d, e}} — gloss3 auto-loads
                                 this at rebuild, like today's maps.
  build/unified_<id>_review.md   ALL zipf-0 lemmas (dialect/garbled —
                                 where the model guesses) + ~50 random,
                                 current entry vs AI side-by-side.
                                 Owner skims, edits the json where wrong.

Cache: cache/unified_<id>.jsonl, committed as usual; reruns only ask
new lemmas (re-chunking ≈ free).  Requests are serial with the rate
limit baked into mistral3._pace (≥2.2s between mistral-large calls);
~2.5k lemmas ÷ 40 ≈ 63 requests ≈ 20–25 min/book.

Usage:
  export MISTRAL_API_KEY=...
  python3 tools/ai/unified3.py --book grimm
  python3 tools/ai/unified3.py --book grimm --mock   # offline plumbing
"""

import argparse
import random
import re
import sys

from emoji3 import emoji_sane, normalize_emoji
from gde3 import leaks_headword
from mistral3 import (HERE, Cache, add_common_args, is_word, load_book,
                      meta, nfc_lower, out_path, run_stage, sentence_text,
                      write_map)

MAX_D = 90
N_RANDOM_REVIEW = 50
CONTENT_POS = {"NOUN", "VERB", "ADJ", "ADV"}
ZWJ = "‍"

# multi-keycap runs: 1️⃣4️⃣ for "fourteenth" — sanity v2 allows them
# (emoji_sane's single-keycap rule rejected the pilot's good pick)
KEYCAP_RUN = re.compile(r"^(?:[0-9#*]️?⃣){1,4}$")

# people bases that occur in family/couple ZWJ sequences — used only to
# REJOIN a sequence the model returned with the joiners stripped
PEOPLE = {0x1F466, 0x1F467, 0x1F468, 0x1F469, 0x1F476, 0x1F9D1, 0x1F9D2}
STRIP_MARKS = {"️"} | {chr(c) for c in range(0x1F3FB, 0x1F400)}


def zipf(lemma, lang):
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(lemma, lang)
    except ImportError:            # sandbox/mock runs: crude proxy
        return max(0.0, 7.0 - len(lemma) * 0.4)


def rejoin_zwj(e):
    """Sanity v2: the model sometimes returns a family/people sequence
    with the joiners stripped (👨👩👧👦, 3+ bases -> emoji_sane rejects).
    When every base is a person and there are 3+, rejoin with ZWJ —
    the intended single emoji — instead of rejecting."""
    if ZWJ in e:
        return e
    core = [c for c in e if c not in STRIP_MARKS]
    if len(core) >= 3 and all(ord(c) in PEOPLE for c in core):
        return ZWJ.join(core)
    return e


def emoji_sane_v2(e):
    return bool(KEYCAP_RUN.match(e)) or emoji_sane(e)


def sanity(lemma, ans):
    """Deterministic checks -> (d, e, notes); failing field -> ''."""
    notes = []
    d = (ans.get("d") or "").strip().rstrip(".")
    if d and (len(d) > MAX_D or "\n" in d):
        notes.append("d:len")
        d = ""
    if d and leaks_headword(lemma, d):
        notes.append("d:leak")
        d = ""
    e = rejoin_zwj(normalize_emoji(ans.get("e") or ""))
    if e and not emoji_sane_v2(e):
        notes.append(f"e:sanity({e})")
        e = ""
    return d, e, notes


def collect_candidates(book, gloss):
    """lemma -> first-occurrence sentence for EVERY content-POS,
    non-entity lemma (via `forms`, which is book-complete — dictionary
    misses included, so this subsumes gfill3's candidate set)."""
    forms = gloss["forms"]
    out = {}
    for sec in book["sections"]:
        for sent in sec["sentences"]:
            ent_toks = set()
            for a, b, _ in sent.get("ents", []):
                ent_toks.update(range(a, b))
            orth = sent.get("orth", {})
            text = None
            for i, tok in enumerate(sent["toks"]):
                if i in ent_toks or not is_word(tok):
                    continue
                if sent["pos"][i] not in CONTENT_POS:
                    continue
                key = forms.get(nfc_lower(orth.get(str(i), tok)))
                if not key or key in out:
                    continue
                text = text or sentence_text(sent)[:240]
                out[key] = text
    return out


def MOCK_GEN(it, lang):
    return {"d": f"einfache Erklärung für dieses Wort"
                 if lang == "de" else "a simple meaning of this word",
            "e": "🔧" if len(it["lemma"]) % 3 else ""}


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def review_report(path, book_id, lang, items, zipfs, gloss, kept, notes,
                  model):
    """ALL zipf-0 lemmas + N_RANDOM_REVIEW random others, current
    pipeline entry vs AI answer side-by-side."""
    zero = [it for it in items if zipfs[it["lemma"]] <= 0.0]
    rest = [it for it in items if zipfs[it["lemma"]] > 0.0]
    sample = random.Random(0).sample(rest, min(N_RANDOM_REVIEW, len(rest)))

    def table(rows):
        out = ["| lemma | zipf | current d | current e | AI d | AI e | "
               "notes |", "|---|---|---|---|---|---|---|"]
        for it in sorted(rows, key=lambda r: zipfs[r["lemma"]]):
            k = it["lemma"]
            cur = gloss["words"].get(k) or {}
            cur_d = cur.get("g_de") or cur.get("g_en") or "—"
            cur_e = cur.get("e") \
                or (gloss.get("emoji_common") or {}).get(k, "") or "—"
            ans = kept.get(k) or {}
            out.append(f"| **{esc(k)}** | {zipfs[k]:.1f} "
                       f"| {esc(cur_d[:70])} | {cur_e} "
                       f"| {esc(ans.get('d') or '—')} "
                       f"| {ans.get('e') or '—'} "
                       f"| {esc(' '.join(notes.get(k, []))) or ''} |")
        return out

    lines = [f"# unified3 review — {book_id} ({lang}, {model})", "",
             "Auto-baked into the gloss at next rebuild — NO review "
             "gate.  Skim this, fix wrong lines directly in "
             f"build/unified_{book_id}.json.", "",
             f"## zipf-0 lemmas — the model is guessing here "
             f"({len(zero)})", ""]
    lines += table(zero)
    lines += ["", f"## random sample ({len(sample)} of {len(rest)})", ""]
    lines += table(sample)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  -> {path}")


def run(args):
    lang, book, gloss = load_book(args.book)
    cands = collect_candidates(book, gloss)
    items = [{"lemma": k, "sentence": s} for k, s in sorted(cands.items())]
    if args.limit:
        items = items[:args.limit]
    est = (len(items) + 39) // 40
    print(f"{args.book} ({lang}): {len(items)} content lemmas "
          f"(~{est} requests, ~{est * 2.2 / 60:.0f}+ min serial)")

    cache = Cache(HERE / "cache" / f"unified_{args.book}.jsonl",
                  args.mock, archive=args.new_cache)
    gen = run_stage(items, key_of=lambda it: it["lemma"],
                    prompt_name="unified_gen_v1", cache=cache, args=args,
                    lang=lang, temperature=0.2, mock_answer=MOCK_GEN,
                    default={"d": "", "e": ""})

    kept, notes, n_d, n_e = {}, {}, 0, 0
    for it in items:
        k = it["lemma"]
        ans = gen.get(k)
        if not isinstance(ans, dict):
            ans = {}
        d, e, why = sanity(k, ans)
        if why:
            notes[k] = why
        if d or e:
            kept[k] = {"d": d, "e": e}
            n_d += bool(d)
            n_e += bool(e)

    write_map(out_path(args, f"unified_{args.book}.json"),
              meta(args, {"kind": "unified", "book": args.book,
                          "lang": lang,
                          "source_hash": gloss["source_hash"],
                          "baked_by": "gloss3 at rebuild — no review "
                                      "gate; spot-check the review.md"}),
              kept)

    zipfs = {it["lemma"]: zipf(it["lemma"], lang) for it in items}
    rev = out_path(args, f"unified_{args.book}_review.md".replace(
        ".md", ".mock.md" if args.mock else ".md"))
    review_report(rev, args.book, lang, items, zipfs, gloss, kept, notes,
                  "mock" if args.mock else args.model)
    print(f"kept d:{n_d} e:{n_e} of {len(items)} lemmas "
          f"({sum(1 for n in notes.values() if n)} sanity notes)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True, help="book id (books.json)")
    add_common_args(ap)
    run(ap.parse_args())


if __name__ == "__main__":
    main()
