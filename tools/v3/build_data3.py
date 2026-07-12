#!/usr/bin/env python3
"""build_data3.py — v3 build driver: all book data into docs/data3/.

Per-book metadata (source, title, trim regexes, encoding) lives in
books_src.toml — the single source of truth; this driver is just the
loop.  v3 counterpart of tools/build_data.sh (which stays untouched,
like all of docs/data/).  bash tools/v3/build_data3.sh still works and
simply execs this file.

One-time setup (build machine):
  pip install -r tools/v3/requirements.txt
  python -m spacy download de_core_news_lg    # German default
  python -m spacy download en_core_web_sm     # English default
  python3 tools/v3/gloss3.py --fetch          # vendor dictionaries
  python3 tools/v3/emoji_map_gen3.py --fetch  # vendor CLDR (optional)

Then:             python3 tools/v3/build_data3.py
Some books only:  BOOKS="kafka velveteen" python3 tools/v3/build_data3.py
Sandbox smoke:    MODEL_DE=de_core_news_sm python3 tools/v3/build_data3.py
  (parse_model is stamped in the output; a later lg run supersedes it)

Env vars (unchanged from the old script): BOOKS, MODEL_DE, MODEL_EN,
SAMPLE.

Per-book outputs:
  docs/data3/<lang>/<id>.json      book file (schema 3)
  docs/data3/gloss/<id>.json       glossary
  docs/data3/books.json            updated in place by build3.py
  tools/v3/build/review_<id>.md    owner review sample
  tools/v3/build/gloss_misses_<id>.txt, orth_candidates_<id>.txt,
  tools/v3/build/emoji_suggestions_<id>.txt and
  tools/v3/build/emoji_map_<id>.json (if CLDR vendored)

Optional per-book inputs (used automatically when present):
  tools/v3/maps/orth_<id>.json     reviewed archaic->modern list
  tools/v3/maps/emoji_<id>.json    reviewed lemma->emoji map
                                   (later: the Mistral-reviewed map)

Emoji-map fallback (owner-approved): when no reviewed
maps/emoji_<id>.json exists, gloss3 is fed the GENERATED
build/emoji_map_<id>.json from the previous run — Klaus's 2026-07-12
decision: the generated CLDR map serves as the reviewed map until the
CLDR -> Mistral review pipeline lands (manual review doesn't scale, and
UI density can't be judged without emoji).  The generator reads the
gloss file, so it runs after gloss3 — but the map depends only on the
lemma set, which the emoji map does not change, so the previous run's
map is always valid (a fresh tree just needs one bootstrap run).  The
curated emoji_map.py stays the per-lemma fallback inside gloss3.
"""

import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib                     # py >= 3.11
except ModuleNotFoundError:            # py 3.10: pip install tomli
    import tomli as tomllib

HERE = Path(__file__).resolve().parent          # tools/v3
ROOT = HERE.parent.parent                       # repo root
DATA = ROOT / "docs" / "data3"


def run(script, *args):
    cmd = [sys.executable, str(HERE / script), *map(str, args)]
    subprocess.run(cmd, cwd=HERE, check=True)


def ensure_utf8(book_id, src, encoding):
    """One-time source re-encode into tools/build/<id>_utf8.txt
    (same location/behaviour as the old iconv step)."""
    out = ROOT / "tools" / "build" / f"{book_id}_utf8.txt"
    if not out.is_file():
        out.write_text(src.read_text(encoding=encoding), encoding="utf-8")
    return out


def build_one(book_id, meta, sample):
    lang = meta["lang"]
    src = ROOT / meta["source"]
    if meta.get("encoding"):
        src = ensure_utf8(book_id, src, meta["encoding"])

    args = ["--in", src, "--lang", lang, "--id", book_id,
            "--title", meta["title"], "--author", meta["author"],
            "--data-dir", DATA]
    if meta.get("skip_until"):
        args += ["--skip-until", meta["skip_until"]]
    if meta.get("stop_at"):
        args += ["--stop-at", meta["stop_at"]]
    if meta.get("audio"):
        args += ["--audio", meta["audio"]]
    model = os.environ.get(f"MODEL_{lang.upper()}", "")
    if model:
        args += ["--model", model]
    orth = HERE / "maps" / f"orth_{book_id}.json"
    if orth.is_file():
        args += ["--orth-subst", orth.relative_to(HERE)]

    print(f"==== {book_id} ({lang})", flush=True)
    run("build3.py", *args)

    book = DATA / lang / f"{book_id}.json"
    gargs = ["--book", book]
    reviewed = HERE / "maps" / f"emoji_{book_id}.json"
    generated = HERE / "build" / f"emoji_map_{book_id}.json"
    if reviewed.is_file():
        print(f"     emoji map: maps/emoji_{book_id}.json (reviewed)")
        gargs += ["--emoji-map", reviewed]
    elif generated.is_file():
        print(f"     emoji map: build/emoji_map_{book_id}.json "
              "(GENERATED, stands in for reviewed)")
        gargs += ["--emoji-map", generated, "--emoji-map-generated"]
    run("gloss3.py", *gargs)

    gloss = DATA / "gloss" / f"{book_id}.json"
    run("validate3.py", "--book", book, "--gloss", gloss,
        "--sample", sample)

    if (HERE / "vendor" / "cldr" / "annotations_de.json").is_file():
        run("emoji_map_gen3.py", "--gloss", gloss)
    print(flush=True)


def main():
    books = tomllib.loads(
        (HERE / "books_src.toml").read_text(encoding="utf-8"))
    sample = os.environ.get("SAMPLE", "25")
    wanted = os.environ.get("BOOKS", "").split() or list(books)

    unknown = [b for b in wanted if b not in books]
    if unknown:
        sys.exit(f"unknown book id(s) {unknown}; "
                 f"books_src.toml has: {' '.join(books)}")

    for d in ("en", "de", "gloss"):
        (DATA / d).mkdir(parents=True, exist_ok=True)
    (HERE / "build").mkdir(exist_ok=True)
    (ROOT / "tools" / "build").mkdir(exist_ok=True)

    for book_id in books:                # manifest order, filtered
        if book_id in wanted:
            build_one(book_id, books[book_id], sample)
    print(f"done -> {DATA}")


if __name__ == "__main__":
    main()
