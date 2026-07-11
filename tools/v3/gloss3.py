#!/usr/bin/env python3
"""
tools/v3/gloss3.py — offline glossary builder (v3 layout).

Realises the 06 glossary pipeline in the PINNED v3 schema
(technical/v3_discussion/02_v3_data_schema.md): reads a BOOK FILE
produced by build3.py (tokens + ents are the single source of truth) and
emits docs/data3/gloss/<book>.json with words / forms / freq /
study_by_sent / sections.  Deterministic, offline; the network is used
exactly once (--fetch) to vendor the FreeDict dictionary.

Stable contract note (06 spec): a later Mistral pass may add `g_de`
learner definitions and fill the `overrides` sense-exception layer; both
are additive keys, never a reshape.

Byproducts (small-batch review + the orthography pass):
  tools/v3/build/gloss_misses_<book>.txt    rare lemmas with no dict hit
  tools/v3/build/orth_candidates_<book>.txt archaic->modern proposals
      (dictionary-miss detection per 00_v3_overview; a human reviews
      these into an --orth-subst list for build3.py)

Usage:
  python3 gloss3.py --fetch                       # one-time vendoring
  python3 gloss3.py --book ../../docs/data3/de/kafka.json \
      [--out ../../docs/data3/gloss/kafka.json] [--threshold 3.5]

German only for now (owner's main use; en glossing needs a different
dictionary source and is not wired up).
"""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))        # tools/ (emoji_map.py, read-only)
from emoji_map import EMOJI                 # noqa: E402

import simplemma                            # noqa: E402
from wordfreq import zipf_frequency         # noqa: E402

SCHEMA = 3
VENDOR = HERE / "vendor"
DICT_URL = ("https://download.freedict.org/dictionaries/deu-eng/"
            "1.9-fd1/freedict-deu-eng-1.9-fd1.dictd.tar.xz")
DICT_VERSION = "freedict-deu-eng-1.9-fd1"
DICT_DIR = VENDOR / "deu-eng"

B64ALPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def git_short():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=HERE, capture_output=True, text=True,
                             check=True).stdout.strip()
        return out or "0000000"
    except Exception:
        return "0000000"


def nfc_lower(s):
    return unicodedata.normalize("NFC", s).lower()


def is_word(s):
    return any(ch.isalnum() for ch in s)


# ------------------------------------------------------------ vendoring

def fetch_vendor():
    import urllib.request
    VENDOR.mkdir(parents=True, exist_ok=True)
    tarball = VENDOR / f"{DICT_VERSION}.dictd.tar.xz"
    if not tarball.exists():
        print(f"downloading {DICT_URL} ...")
        urllib.request.urlretrieve(DICT_URL, tarball)
    import tarfile
    with tarfile.open(tarball) as tf:
        tf.extractall(VENDOR)
    print(f"vendored -> {DICT_DIR}")


# ------------------------------------------------------------ dictd access

def b64int(s):
    v = 0
    for c in s:
        v = v * 64 + B64ALPH.index(c)
    return v


def load_dict():
    """headword(lower) -> [(offset, length), ...] of ALL its entry blocks
    (homographs: FreeDict indexes 'Flimmern' the noun and 'flimmern' the
    verb under the same folded key — the caller picks by case).  Data =
    the whole decompressed .dict (dictzip is gzip-compatible)."""
    idx_path = DICT_DIR / "deu-eng.index"
    dict_path = DICT_DIR / "deu-eng.dict.dz"
    if not idx_path.exists():
        sys.exit(f"vendored dictionary missing — run: {sys.argv[0]} --fetch")
    index = {}
    with open(idx_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            hw = nfc_lower(parts[0].strip())
            if hw:
                index.setdefault(hw, []).append(
                    (b64int(parts[1]), b64int(parts[2])))
    data = gzip.open(dict_path).read()
    return index, data


TAG_RE = re.compile(r"<[^>]*>|\[[^\]]*\]|\{[^}]*\}")


def parse_entry(raw):
    """(display_headword, one_line_gloss) from a dictd entry block."""
    lines = raw.decode("utf-8").split("\n")
    head = lines[0].split("/")[0].strip() or lines[0].strip()
    for ln in lines[1:]:
        t = ln.strip()
        if not t or t.startswith(('"', "Note", "Synonym", "see:", "-")):
            continue
        t = TAG_RE.sub("", t)
        t = re.sub(r"^\d+[.)]\s*", "", t)
        t = " ".join(t.split()).strip(" ,;")
        if t:
            t = t.split(";")[0]
            syns = [p.strip() for p in t.split(",") if p.strip()]
            return head, ", ".join(syns[:3])[:80]
    return head, ""


# ------------------------------------------------------------ archaic forms

def _add(seen, out, x):
    if x not in seen:
        seen.add(x)
        out.append(x)


def variants(k):
    """SAFE archaic-orthography variants of a lowercase string, tried
    only after a dictionary miss and allowed to feed the LIVE gloss
    (Thür->Tür, daß->dass, sey->sei).  Safe = a false hit is next to
    impossible in German."""
    seen, out = {k}, []
    _add(seen, out, k.replace("th", "t"))
    _add(seen, out, k.replace("ey", "ei"))
    _add(seen, out, k.replace("th", "t").replace("ey", "ei"))
    _add(seen, out, k.replace("ß", "ss"))
    return out


def propose_variants(k):
    """AGGRESSIVE variants (gieng->ging, Waaren->Waren).  These can hit
    unrelated real words (beeilen -> "beilen" -> Beil!), so they are
    NEVER glossed from — they only feed the orth_candidates report,
    which a human reviews into build3.py's --orth-subst list."""
    seen, out = {k}, []
    _add(seen, out, k.replace("ie", "i"))           # gieng -> ging
    _add(seen, out, re.sub(r"([aeo])\1", r"\1", k))  # Waaren -> Waren
    return out


# ------------------------------------------------------------ main pass

def run(args):
    book = json.loads(Path(args.book).read_text("utf-8"))
    if book.get("lang") != "de":
        sys.exit("gloss3.py currently supports German books only")
    index, data = load_dict()

    def entry(key, lemma_display):
        """Among the key's homograph entries, prefer one whose headword
        matches the lemma's exact case (verb 'flimmern' over noun
        'Flimmern'); else the first entry with a usable gloss line."""
        parsed = [parse_entry(data[off:off + ln]) for off, ln in index[key]]
        usable = [(h, g) for h, g in parsed if g]
        if not usable:
            return None, None
        for h, g in usable:
            if h == lemma_display:
                return h, g
        return usable[0]

    zipf_cache = {}

    def zipf(k):
        if k not in zipf_cache:
            zipf_cache[k] = zipf_frequency(k, "de")
        return zipf_cache[k]

    lemma_cache = {}

    def lemmatize(tok):
        if tok not in lemma_cache:
            lemma_cache[tok] = simplemma.lemmatize(
                unicodedata.normalize("NFC", tok), lang="de")
        return lemma_cache[tok]

    resolve_cache = {}                       # surface_lower -> (key, archaic)

    def resolve(surface_lower, lemma_lower):
        """Final lemma KEY for a surface form.  Direct lemma when common
        or in the dictionary; otherwise archaic variants of the surface
        (re-lemmatised: gieng->ging->gehen) then of the lemma."""
        if surface_lower in resolve_cache:
            return resolve_cache[surface_lower]
        res = (lemma_lower, False)
        if lemma_lower not in index and zipf(lemma_lower) < args.threshold:
            found = False
            for v in variants(surface_lower):
                l2 = nfc_lower(lemmatize(v))
                if l2 in index:
                    res, found = (l2, True), True
                    break
            if not found:
                for v in variants(lemma_lower):
                    if v in index:
                        res = (v, True)
                        break
        resolve_cache[surface_lower] = res
        return res

    words, forms, freq = {}, {}, {}
    study_by_sent, sections_out = {}, []
    misses = {}                              # key -> set of surfaces
    orth_cand = {}                           # archaic surface -> (key, head)
    n_tokens = 0

    for sec in book["sections"]:
        sec_study, sec_seen = [], set()
        for sent in sec["sentences"]:
            ent_toks = set()
            for a, b, _ in sent.get("ents", []):
                ent_toks.update(range(a, b))
            sent_study, sent_seen = [], set()
            for i, tok in enumerate(sent["toks"]):
                if i in ent_toks or not is_word(tok):
                    continue
                n_tokens += 1
                surf = nfc_lower(tok)
                lemma = lemmatize(tok)
                key, archaic = resolve(surf, nfc_lower(lemma))
                forms[surf] = key
                if zipf(key) >= args.threshold:
                    continue                 # common word: not study material
                if key not in index:
                    misses.setdefault(key, set()).add(tok)
                    # report-only proposal from the aggressive variants —
                    # never glossed from (see propose_variants)
                    for v in propose_variants(surf):
                        l2 = nfc_lower(lemmatize(v))
                        if l2 in index:
                            h, g = entry(l2, lemmatize(v))
                            if g:
                                orth_cand[tok] = (l2, h + " [UNVERIFIED]")
                            break
                    continue
                if key not in words:
                    head, g_en = entry(key, lemmatize(tok))
                    if not g_en:             # no entry with a usable line
                        misses.setdefault(key, set()).add(tok)
                        continue
                    words[key] = {"l": head, "g_en": g_en,
                                  "e": EMOJI["de"].get(key, "")}
                    freq[key] = round(zipf(key), 2)
                if archaic:
                    orth_cand[tok] = (key, words[key]["l"])
                if key not in sent_seen:
                    sent_seen.add(key)
                    sent_study.append(key)
                if key not in sec_seen:
                    sec_seen.add(key)
                    sec_study.append(key)
            if sent_study:
                study_by_sent[sent["id"]] = sent_study
        sections_out.append({"title": sec["title"], "study": sec_study})

    out = {
        "schema": SCHEMA,
        "generator": f"gloss3.py@{git_short()}",
        "lang": "de",
        "source_hash": book["source_hash"],
        "dict_version": DICT_VERSION,
        "words": words,
        "forms": forms,
        "freq": freq,
        "study_by_sent": study_by_sent,
        "overrides": {},
        "sections": sections_out,
    }
    out_path = Path(args.out) if args.out else (
        Path(args.book).parent.parent / "gloss" / Path(args.book).name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False,
                                   separators=(",", ":")), encoding="utf-8")

    build_dir = HERE / "build"
    build_dir.mkdir(exist_ok=True)
    bid = book["id"]
    miss_path = build_dir / f"gloss_misses_{bid}.txt"
    miss_path.write_text(
        "".join(f"{k}\t{', '.join(sorted(v))}\n"
                for k, v in sorted(misses.items())), encoding="utf-8")
    orth_path = build_dir / f"orth_candidates_{bid}.txt"
    orth_path.write_text(
        "".join(f"{s}\t{h}\t(lemma key: {k})\n"
                for s, (k, h) in sorted(orth_cand.items())), encoding="utf-8")

    print(f"{bid}: word_tokens={n_tokens} forms={len(forms)} "
          f"glossed_lemmas={len(words)} misses={len(misses)} "
          f"archaic_hits={len(orth_cand)}")
    print(f"  -> {out_path}\n  -> {miss_path}\n  -> {orth_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", help="book file produced by build3.py")
    ap.add_argument("--out", default=None,
                    help="output path (default: sibling gloss/<book>.json)")
    ap.add_argument("--threshold", type=float, default=3.5,
                    help="zipf below which a lemma is glossed (default 3.5)")
    ap.add_argument("--fetch", action="store_true",
                    help="download + extract the FreeDict dictionary")
    args = ap.parse_args()
    if args.fetch:
        fetch_vendor()
        if not args.book:
            return
    if not args.book:
        ap.error("--book is required (or use --fetch alone)")
    run(args)


if __name__ == "__main__":
    main()
