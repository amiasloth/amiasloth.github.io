#!/usr/bin/env python3
"""
tools/ai/experiment_unified.py — A/B harness for the gloss/emoji flow
rework (owner discussion 2026-07-12).  Answers two questions on a real
sample BEFORE committing to the new pipeline:

  1. Is the UNIFIED no-dictionary pass good enough?  One request per
     lemma batch, input lemma + first-occurrence sentence ONLY (no
     FreeDict gloss — the gloss poisoned emoji3's Holzhacker ->
     "dirty player" -> wrong emoji), output {"d": same-language
     definition, "e": emoji hint} with the RELAXED rubric
     (approximate beats empty; only misleading is bad).

  2. Is the separate GRADE stage worth 2x requests?  Generation runs
     once; the grader runs over the SAME output and every verdict +
     reason lands in the report next to the answer it judged.  The
     owner reviews the REPORT, not the data: if the grader mostly
     rubber-stamps or, worse, rejects good picks, drop the stage; if
     it catches real junk the sanity checks missed, keep it.

Output: build/experiment_<book>.md — side-by-side per lemma:
current pipeline (FreeDict g_en + baked emoji) vs unified AI answer
vs deterministic sanity checks vs grader verdicts.  Two sections:
STUDY lemmas (rare) and COMMON lemmas (the new all-content-words
bubble scope), sampled across the frequency range.

Usage (build machine; ~4 requests total at the default sample size,
rate-limited in mistral3.api_call):
  export MISTRAL_API_KEY=...
  python3 tools/ai/experiment_unified.py --book grimm
  python3 tools/ai/experiment_unified.py --book grimm --mock   # plumbing
"""

import argparse
import sys

from emoji3 import EMOJI_FUNC_POS, emoji_sane, normalize_emoji
from gde3 import leaks_headword
from mistral3 import (HERE, Cache, add_common_args, first_sentences,
                      is_word, load_book, nfc_lower, run_stage,
                      sentence_text)

MAX_D = 90
CONTENT_POS = {"NOUN", "VERB", "ADJ", "ADV"}
# Known trouble-makers: always in the sample when the book has them.
TRICKY = {"holzhacker", "schloss", "panzerartig", "versteifung"}


def zipf(lemma, lang):
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(lemma, lang)
    except ImportError:            # sandbox/mock runs: crude proxy
        return max(0.0, 7.0 - len(lemma) * 0.4)


def stride_sample(pairs, n, keep=()):
    """pairs sorted rare->common; n spread across the range, forced
    keeps included."""
    forced = [p for p in pairs if p[0] in keep]
    rest = [p for p in pairs if p[0] not in keep]
    want = max(0, n - len(forced))
    if want and rest:
        step = max(1, len(rest) // want)
        rest = rest[::step][:want]
    else:
        rest = []
    return sorted(forced + rest, key=lambda p: p[1])


def collect_common(book, gloss, lang):
    """lemma -> (zipf, first sentence) for content-POS lemmas that have
    NO gloss entry today (the new bubble scope), first occurrence."""
    words, forms = gloss["words"], gloss["forms"]
    seen = {}
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
                if not key or key in words or key in seen:
                    continue
                text = text or sentence_text(sent)[:240]
                seen[key] = (zipf(key, lang), text)
    return seen


def mock_gen(it, lang):
    return {"d": f"einfache Erklärung für {it['lemma']}"
                 if lang == "de" else f"simple meaning of {it['lemma']}",
            "e": "🔧"}


def mock_grade(it, lang):
    return {"d": True, "e": True, "why": ""}


def sanity(lemma, ans):
    """Deterministic pre-grade checks; returns (d_ok, e_norm, notes)."""
    notes = []
    d = (ans.get("d") or "").strip()
    if not d or len(d) > MAX_D or "\n" in d:
        notes.append("d:len")
    if d and leaks_headword(lemma, d):
        notes.append("d:leak")
    e = normalize_emoji(ans.get("e") or "")
    if e and not emoji_sane(e):
        notes.append(f"e:sanity({e})")
        e = ""
    return ("d:" not in " ".join(notes) or not notes), e, notes


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def table(rows_in, gloss, gen, grade, lang):
    lines = ["| lemma | zipf | current (dict / emoji) | AI d | AI e | "
             "sanity | grader | why |",
             "|---|---|---|---|---|---|---|---|"]
    for lemma, z, sent in rows_in:
        cur = gloss["words"].get(lemma) or {}
        cur_txt = esc(cur.get("g_en", "—"))[:60]
        cur_e = cur.get("e") or (gloss.get("emoji_common") or {}) \
            .get(lemma, "")
        ans = gen.get(lemma) or {}
        if not isinstance(ans, dict):
            ans = {}
        d_ok, e, notes = sanity(lemma, ans)
        g = grade.get(lemma) or {}
        if not isinstance(g, dict):
            g = {}
        verdict = (("d✓" if g.get("d", True) else "d✗")
                   + (" e✓" if g.get("e", True) else " e✗")) \
            if (ans.get("d") or e) else "—"
        lines.append(
            f"| **{esc(lemma)}** | {z:.1f} "
            f"| {cur_txt} {cur_e} "
            f"| {esc((ans.get('d') or '')[:MAX_D + 10])} "
            f"| {e or '—'} "
            f"| {esc(' '.join(notes)) or 'ok'} "
            f"| {verdict} | {esc(g.get('why') or '')} |")
    return lines


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="grimm")
    ap.add_argument("--n", type=int, default=25,
                    help="sample size PER GROUP (study/common)")
    add_common_args(ap)
    args = ap.parse_args()

    lang, book, gloss = load_book(args.book)
    first = first_sentences(book, gloss["study_by_sent"])

    study_pool = sorted(
        ((k, gloss["freq"].get(k, 0.0)) for k in gloss["words"]),
        key=lambda p: p[1])
    study = [(k, z, first.get(k, "")) for k, z in
             stride_sample(study_pool, args.n, keep=TRICKY)]

    commons = collect_common(book, gloss, lang)
    common_pool = sorted(((k, v[0]) for k, v in commons.items()),
                         key=lambda p: p[1])
    common = [(k, z, commons[k][1]) for k, z in
              stride_sample(common_pool, args.n, keep=TRICKY)]

    print(f"{args.book} ({lang}): {len(study)} study + {len(common)} "
          f"common lemmas sampled (pools {len(study_pool)}/"
          f"{len(common_pool)})")

    items = [{"lemma": k, "sentence": s} for k, z, s in study + common]
    cache = Cache(HERE / "cache" / f"experiment_{args.book}.jsonl",
                  args.mock, archive=args.new_cache)
    gen = run_stage(items, key_of=lambda it: it["lemma"],
                    prompt_name="unified_gen_v1", cache=cache, args=args,
                    lang=lang, temperature=0.2, mock_answer=mock_gen,
                    default={"d": "", "e": ""})

    to_grade = []
    for it in items:
        ans = gen.get(it["lemma"]) or {}
        if not isinstance(ans, dict):
            continue
        _, e, _ = sanity(it["lemma"], ans)
        if ans.get("d") or e:
            to_grade.append({**it, "d": ans.get("d", ""), "e": e})
    grade = run_stage(to_grade, key_of=lambda it: it["lemma"],
                      prompt_name="unified_grade_v1", cache=cache,
                      args=args, lang=lang, temperature=0.0,
                      mock_answer=mock_grade,
                      default={"d": True, "e": True, "why": ""})

    rej_d = sum(1 for g in grade.values()
                if isinstance(g, dict) and g.get("d") is False)
    rej_e = sum(1 for g in grade.values()
                if isinstance(g, dict) and g.get("e") is False)
    out = ["# Unified-pass experiment — " + args.book,
           "",
           f"Model: {'mock' if args.mock else args.model} · sample "
           f"{len(study)} study + {len(common)} common · grader rejected "
           f"d:{rej_d} e:{rej_e} of {len(to_grade)} graded",
           "",
           "**What to look for:** (1) AI d vs current dict gloss — is the",
           "no-dictionary definition right where FreeDict was wrong",
           "(Holzhacker)? (2) grader column — does d✗/e✗ mark real junk,",
           "or does it reject good picks? If it only rubber-stamps, the",
           "grade stage is not worth 2x requests. (3) AI e under the",
           "relaxed rubric — approximate-but-helpful, or drifting into",
           "misleading?",
           "",
           "## Study lemmas (rare — today's bubble scope)",
           ""]
    out += table(study, gloss, gen, grade, lang)
    out += ["", "## Common lemmas (new scope — no gloss entry today)", ""]
    out += table(common, gloss, gen, grade, lang)
    name = f"experiment_{args.book}{'.mock' if args.mock else ''}.md"
    path = HERE / "build" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  -> {path}")


if __name__ == "__main__":
    main()
