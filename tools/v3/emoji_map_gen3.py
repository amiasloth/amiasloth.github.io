#!/usr/bin/env python3
"""
tools/v3/emoji_map_gen3.py — CLDR-based emoji suggestions for a book's
gloss file.  Writes two outputs: the human-readable report (as
emoji_suggest3.py did) and a {lemma: emoji} JSON map taking the top
candidate per lemma (all lemmas — stable across rebuilds).  The map
STANDS IN for the reviewed map (owner decision 2026-07-12: manual
review doesn't scale) until the CLDR -> Mistral review pipeline lands;
gloss3 is told via --emoji-map-generated so the curated emoji_map.py
wins collisions.  The Mistral map will use the same gloss3.py
--emoji-map entry point and format, without that flag.

Matching (deterministic):
  1. the German lemma against German CLDR keywords + emoji names
  2. the words of the English gloss against English CLDR keywords/names
     (weaker signal: listed after the German hits)

Only single-word keywords are indexed; generic keywords that label
hundreds of emoji (Tier, Gesicht, ...) are skipped via a fan-out cap.

English gloss files (lang "en"): the lemma IS English, so it is matched
against the en keywords directly; the g_en field is a WordNet definition
sentence there, far too noisy for keyword matching, so it is skipped.

Vendored data (gitignored; --fetch downloads; see vendor/README.md):
  tools/v3/vendor/cldr/annotations_{de,en}.json

Usage:
  python3 emoji_map_gen3.py --fetch                # one-time vendoring
  python3 emoji_map_gen3.py --gloss ../../docs/data3/gloss/kafka.json
  -> tools/v3/build/emoji_suggestions_<book>.txt
  -> tools/v3/build/emoji_map_<book>.json
"""

import argparse
import json
import unicodedata
from pathlib import Path

CLDR_URL = ("https://raw.githubusercontent.com/unicode-org/cldr-json/"
            "main/cldr-json/cldr-annotations-full/annotations/{lang}/"
            "annotations.json")

HERE = Path(__file__).resolve().parent
CLDR = HERE / "vendor" / "cldr"
MAX_FANOUT = 8          # keyword shared by more emoji than this = generic
MAX_CAND = 3            # suggestions per lemma

# gloss words that carry no meaning of their own — matching them only
# produces junk ("shout at" -> @, "worked off" -> 📴)
EN_STOP = {
    "a", "an", "the", "to", "of", "at", "on", "in", "off", "up", "out",
    "down", "away", "again", "with", "for", "into", "onto", "over",
    "and", "or", "be", "do", "make", "get", "go", "one", "so", "this",
    "sb", "sth", "sb.", "sth.", "jdn", "jdm", "etw",
}


def is_emoji(s):
    """Pictograph or symbol worth suggesting (♪ counts; ∈, @, ≡ not).
    Deliberately loose: a non-emoji symbol is fine if the meaning fits."""
    return any(ord(c) >= 0x1F000 or 0x2600 <= ord(c) <= 0x27BF
               for c in s) and not any(0x2200 <= ord(c) <= 0x22FF
                                       for c in s)


def nfc_lower(s):
    return unicodedata.normalize("NFC", s).lower()


def keyword_index(lang):
    path = CLDR / f"annotations_{lang}.json"
    ann = json.loads(path.read_text("utf-8"))["annotations"]["annotations"]
    idx = {}
    for emoji, entry in ann.items():
        names = entry.get("tts", [])
        if not is_emoji(emoji):
            continue
        for kw in names + entry.get("default", []):
            kw = nfc_lower(kw)
            if " " in kw or not kw:
                continue                    # single-word keywords only
            idx.setdefault(kw, [])
            # tts name first: it is the emoji's identity, not a facet
            if emoji not in idx[kw]:
                if kw in (nfc_lower(n) for n in names):
                    idx[kw].insert(0, emoji)
                else:
                    idx[kw].append(emoji)
    return {k: v for k, v in idx.items() if len(v) <= MAX_FANOUT}


def fetch_vendor():
    import urllib.request
    CLDR.mkdir(parents=True, exist_ok=True)
    for lang in ("de", "en"):
        dest = CLDR / f"annotations_{lang}.json"
        if dest.exists():
            print(f"{lang}: already vendored")
            continue
        url = CLDR_URL.format(lang=lang)
        print(f"downloading {url} ...")
        urllib.request.urlretrieve(url, dest)
    print(f"vendored -> {CLDR}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gloss")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fetch", action="store_true",
                    help="download the CLDR annotation files")
    args = ap.parse_args()
    if args.fetch:
        fetch_vendor()
        if not args.gloss:
            return
    if not args.gloss:
        ap.error("--gloss is required (or use --fetch alone)")

    gloss = json.loads(Path(args.gloss).read_text("utf-8"))
    lang = gloss.get("lang", "de")
    en_idx = keyword_index("en")
    de_idx = keyword_index("de") if lang == "de" else {}

    lines, n_hit = [], 0
    emoji_map = {}
    # The JSON map covers ALL gloss lemmas, not only currently-empty
    # ones: it then depends only on the lemma set, so it is stable
    # across rebuilds (2026-07-12 fix — the old empty-only map collapsed
    # to {} once a bake succeeded, and every fresh rebuild oscillated,
    # needing two passes to converge).  The REPORT still lists only
    # lemmas whose gloss emoji is empty: it is the human gap review.
    for key, w in sorted(gloss["words"].items()):
        cands, seen = [], set()

        def add(emoji, via):
            if emoji not in seen and len(cands) < MAX_CAND:
                seen.add(emoji)
                cands.append((emoji, via))

        if lang == "de":
            for e in de_idx.get(key, []):
                add(e, f"de:{key}")
            for word in nfc_lower(w["g_en"]).replace(",", " ").split():
                if word in EN_STOP or len(word) < 3:
                    continue
                for e in en_idx.get(word, []):
                    add(e, f"en:{word}")
        else:                               # en: lemma-only (see docstring)
            for e in en_idx.get(key, []):
                add(e, f"en:{key}")
        if cands:
            emoji_map[key] = cands[0][0]
            if not w.get("e"):
                n_hit += 1
                lines.append(f"{key}\t{w['l']} = {w['g_en']}\t"
                             + "  ".join(f"{e} ({v})" for e, v in cands))

    book_id = Path(args.gloss).stem
    json_out = HERE / "build" / f"emoji_map_{book_id}.json"

    out = Path(args.out) if args.out else (
        HERE / "build" / f"emoji_suggestions_{book_id}.txt")
    out.parent.mkdir(exist_ok=True)
    header = ("# CLDR emoji suggestions — REVIEW BEFORE USE, never "
              "auto-apply.\n# Keep a line by adding  \"<lemma>\": "
              "\"<emoji>\"  to a JSON map for gloss3.py --emoji-map.\n"
              "# Empty beats bad: when in doubt, leave the lemma out.\n")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    json_out.parent.mkdir(exist_ok=True)
    json_out.write_text(
        json.dumps(emoji_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    empty = sum(1 for w in gloss["words"].values() if not w.get("e"))
    print(f"{book_id}: {n_hit}/{empty} empty-emoji lemmas got suggestions "
          f"-> {out}\n"
          f"JSON map -> {json_out}"
    )


if __name__ == "__main__":
    main()
