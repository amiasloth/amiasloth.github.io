#!/usr/bin/env python3
"""
tools/v3/validate3.py — checks a built v3 book file (+ optional gloss)
against the PINNED schema's invariants (02_v3_data_schema.md §Invariants)
and prints review metrics.  Pure JSON consumer: no spaCy, no dictionary —
it verifies what a reader would load, independent of how it was built.

Invariants:
  1  reconstruction: join(toks,sp) is NFC+collapsed AND re-hashes to `id`
  2  nesting: cuts[coarser] ⊆ cuts[finer]; rungs chain-nest; rungs ⊆ advanced
  3  legal cuts: every cut/rung index appears in `breaks`
  4  (id,occ) unique; same id ⇒ same reconstructed text
  5  no punct-only chunk at any level or rung

Plus structural checks (lengths agree, spans in range, provenance keys)
and gloss cross-checks (forms→words? no: forms is book-complete, so
forms values must each be a words key OR a common/unglossed lemma —
checked loosely; study/freq keys strictly).

--sample N writes tools/v3/build/review_<book>.md: the first N sentences
chunked at every level + rungs + study words, for owner small-batch
review.

Usage:
  python3 validate3.py --book ../../docs/data3/de/kafka.json \
      [--gloss ../../docs/data3/gloss/kafka.json] [--sample 25]
"""

import argparse
import hashlib
import json
import statistics
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEVELS_FINE = ["starter", "beginner", "intermediate", "advanced"]

errors = []


def err(msg):
    errors.append(msg)


def is_word(s):
    return any(ch.isalnum() for ch in s)


def reconstruct(toks, sp):
    return "".join(t + (" " if b == "1" else "") for t, b in zip(toks, sp))


def chunk_slices(n, cuts):
    bounds = [0] + list(cuts) + [n]
    return list(zip(bounds, bounds[1:]))


def check_book(book):
    for key in ("schema", "generator", "source_hash", "parse_model",
                "id", "title", "lang", "levels", "stats", "sections"):
        if key not in book:
            err(f"book: missing top-level key {key!r}")

    seen = {}                                # (id,occ) -> None; id -> text
    id_text = {}
    n_sents = n_desp = 0
    lens = {lvl: [] for lvl in LEVELS_FINE}

    for si, sec in enumerate(book.get("sections", [])):
        for d in sec["sentences"]:
            n_sents += 1
            tag = f"sec{si} id={d.get('id')}"
            toks, sp = d["toks"], d["sp"]
            if len(sp) != len(toks):
                err(f"{tag}: sp length {len(sp)} != toks {len(toks)}")
                continue
            if len(d.get("pos", [])) != len(toks):
                err(f"{tag}: pos length mismatch")
            n = len(toks)

            # 1 — reconstruction + id
            recon = reconstruct(toks, sp)
            if recon != " ".join(unicodedata.normalize("NFC", recon).split()):
                err(f"{tag}: reconstruction not normalised: {recon!r}")
            rid = hashlib.sha256(recon.encode("utf-8")).hexdigest()[:12]
            if rid != d["id"]:
                err(f"{tag}: id mismatch (recomputed {rid})")

            # 4 — uniqueness
            key = (d["id"], d.get("occ", 0))
            if key in seen:
                err(f"{tag}: duplicate (id,occ) {key}")
            seen[key] = None
            if d["id"] in id_text and id_text[d["id"]] != recon:
                err(f"{tag}: id collision with different text")
            id_text[d["id"]] = recon

            breaks = d.get("breaks", [])
            bpos = [k for k, _ in breaks]
            if bpos != sorted(set(bpos)):
                err(f"{tag}: breaks not sorted/unique")
            if any(not (0 < k < n) for k in bpos):
                err(f"{tag}: break position out of range")
            n_desp += sum(1 for _, s in breaks if s == 0)
            bset = set(bpos)

            cuts = {lvl: d.get("cuts", {}).get(lvl, []) for lvl in LEVELS_FINE}
            rungs = d.get("rungs", [])

            # 2 — nesting
            for coarse, fine in zip(reversed(LEVELS_FINE),
                                    list(reversed(LEVELS_FINE))[1:]):
                if not set(cuts[coarse]) <= set(cuts[fine]):
                    err(f"{tag}: cuts[{coarse}] ⊄ cuts[{fine}]")
            for r in rungs:
                if not set(r) <= set(cuts["advanced"]):
                    err(f"{tag}: rung ⊄ cuts.advanced")
            for a, b in zip(rungs, rungs[1:]):
                if not set(a) <= set(b):
                    err(f"{tag}: rungs do not chain-nest")

            # 3 — legal cuts
            for lvl in LEVELS_FINE:
                if not set(cuts[lvl]) <= bset:
                    err(f"{tag}: cuts[{lvl}] not all in breaks")
            for r in rungs:
                if not set(r) <= bset:
                    err(f"{tag}: rung cut not in breaks")

            # 5 — no punct-only chunk; collect lengths
            for lvl in LEVELS_FINE:
                for a, b in chunk_slices(n, cuts[lvl]):
                    w = sum(1 for t in toks[a:b] if is_word(t))
                    if w == 0:
                        err(f"{tag}: punct-only chunk at {lvl} [{a}:{b}]")
                    lens[lvl].append(w)
            for r in rungs:
                for a, b in chunk_slices(n, r):
                    if not any(is_word(t) for t in toks[a:b]):
                        err(f"{tag}: punct-only rung chunk [{a}:{b}]")

            for a, b, _ in d.get("ents", []):
                if not (0 <= a < b <= n):
                    err(f"{tag}: ent span out of range")

    print(f"sentences={n_sents} desperation_breaks={n_desp}")
    for lvl in LEVELS_FINE:
        ls = lens[lvl]
        if not ls:
            continue
        mean = statistics.mean(ls)
        cv = statistics.pstdev(ls) / mean if mean else 0
        print(f"  {lvl:13s} chunks={len(ls):5d} mean_words={mean:4.1f} "
              f"cv={cv:.2f} max={max(ls)}")
    return id_text


def check_gloss(gloss, book, book_ids):
    for key in ("schema", "generator", "source_hash", "dict_version",
                "words", "forms", "freq", "study_by_sent", "sections"):
        if key not in gloss:
            err(f"gloss: missing key {key!r}")
    if gloss["source_hash"] != book["source_hash"]:
        err("gloss: source_hash differs from book (stale?)")
    w = set(gloss["words"])
    if set(gloss["freq"]) != w:
        err("gloss: freq keys != words keys")
    for sid, lemmas in gloss["study_by_sent"].items():
        if sid not in book_ids:
            err(f"gloss: study_by_sent id {sid} not in book")
        for l in lemmas:
            if l not in w:
                err(f"gloss: study lemma {l!r} not in words")
    for sec in gloss["sections"]:
        for l in sec["study"]:
            if l not in w:
                err(f"gloss: section study lemma {l!r} not in words")
    if len(gloss["sections"]) != len(book["sections"]):
        err("gloss: section count differs from book")
    # emoji_common (schema rev 3.1, optional): common-lemma fallback
    # channel for the chunk-emoji pick.  Keys must be disjoint from
    # words (a lemma is rare or common, never both), values non-empty
    # (empty beats bad: omit instead), and every key reachable through
    # forms (otherwise it is dead weight the reader can never hit).
    ec = gloss.get("emoji_common", {})
    fvals = set(gloss["forms"].values())
    for k, v in ec.items():
        if k in w:
            err(f"gloss: emoji_common key {k!r} shadows a glossed word")
        if not v:
            err(f"gloss: emoji_common[{k!r}] is empty — omit the key")
        if k not in fvals:
            err(f"gloss: emoji_common key {k!r} unreachable via forms")
    hits = sum(1 for v in gloss["forms"].values() if v in w)
    print(f"gloss: words={len(w)} forms={len(gloss['forms'])} "
          f"(→glossed: {hits}) study_sents={len(gloss['study_by_sent'])} "
          f"emoji_common={len(ec)}")


def write_sample(book, gloss, n, out_path):
    lines = [f"# review sample — {book['id']} "
             f"({book['parse_model']}, {book['generator']})", ""]
    count = 0
    for sec in book["sections"]:
        if count >= n:
            break
        lines += [f"## {sec['title']}", ""]
        for d in sec["sentences"]:
            if count >= n:
                break
            count += 1
            toks, sp = d["toks"], d["sp"]
            recon = reconstruct(toks, sp)
            lines.append(f"**{count}. {recon}**  `{d['id']}`"
                         + (" ¶" if d.get("p") else ""))
            for lvl in LEVELS_FINE:
                cuts = d.get("cuts", {}).get(lvl, [])
                parts = [reconstruct(toks[a:b], sp[a:b]).strip()
                         for a, b in chunk_slices(len(toks), cuts)]
                lines.append(f"- {lvl}: " + " | ".join(parts))
            for i, r in enumerate(d.get("rungs", [])):
                parts = [reconstruct(toks[a:b], sp[a:b]).strip()
                         for a, b in chunk_slices(len(toks), r)]
                lines.append(f"- rung {i + 1}: " + " | ".join(parts))
            if d.get("ents"):
                lines.append("- ents: " + ", ".join(
                    f"{' '.join(toks[a:b])} ({lab})"
                    for a, b, lab in d["ents"]))
            if gloss:
                study = gloss["study_by_sent"].get(d["id"], [])
                if study:
                    lines.append("- study: " + "; ".join(
                        f"{gloss['words'][l]['l']} = {gloss['words'][l]['g_en']}"
                        + (f" {gloss['words'][l]['e']}"
                           if gloss['words'][l]['e'] else "")
                        for l in study))
            lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"sample -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", required=True)
    ap.add_argument("--gloss", default=None)
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()

    book = json.loads(Path(args.book).read_text("utf-8"))
    id_text = check_book(book)
    gloss = None
    if args.gloss:
        gloss = json.loads(Path(args.gloss).read_text("utf-8"))
        check_gloss(gloss, book, id_text)
    if args.sample:
        build_dir = HERE / "build"
        build_dir.mkdir(exist_ok=True)
        write_sample(book, gloss, args.sample,
                     build_dir / f"review_{book['id']}.md")

    if errors:
        print(f"\nFAIL — {len(errors)} problem(s):")
        for e in errors[:40]:
            print("  " + e)
        if len(errors) > 40:
            print(f"  ... and {len(errors) - 40} more")
        sys.exit(1)
    print("\nPASS — all invariants hold")


if __name__ == "__main__":
    main()
