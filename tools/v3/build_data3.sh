#!/usr/bin/env bash
# Build all v3 book data into docs/data3/: book file + glossary +
# invariant validation + review sample, per book.  v3 counterpart of
# tools/build_data.sh (which stays untouched, like all of docs/data/).
#
# One-time setup (build machine):
#   pip install -r tools/v3/requirements.txt
#   python -m spacy download de_core_news_lg    # German default
#   python -m spacy download en_core_web_sm     # English default
#   python3 tools/v3/gloss3.py --fetch          # vendor dictionaries
#   python3 tools/v3/emoji_map_gen3.py --fetch  # vendor CLDR (optional)
#
# Then:            bash tools/v3/build_data3.sh
# Some books only: BOOKS="kafka velveteen" bash tools/v3/build_data3.sh
# Sandbox smoke:   MODEL_DE=de_core_news_sm bash tools/v3/build_data3.sh
#   (parse_model is stamped in the output; a later lg run supersedes it)
#
# Per-book outputs:
#   docs/data3/<lang>/<id>.json      book file (schema 3)
#   docs/data3/gloss/<id>.json       glossary
#   docs/data3/books.json            updated in place by build3.py
#   tools/v3/build/review_<id>.md    owner review sample
#   tools/v3/build/gloss_misses_<id>.txt, orth_candidates_<id>.txt,
#   tools/v3/build/emoji_suggestions_<id>.txt and
#   tools/v3/build/emoji_map_<id>.json (if CLDR vendored; map is for
#   testing only, superseded by the reviewed/AI map in tools/v3/maps/)
#
# Optional per-book inputs (used automatically when present):
#   tools/v3/maps/orth_<id>.json     reviewed archaic->modern list
#   tools/v3/maps/emoji_<id>.json    reviewed lemma->emoji map
set -euo pipefail
cd "$(dirname "$0")"

DATA=../../docs/data3
SAMPLE="${SAMPLE:-25}"
MODEL_DE="${MODEL_DE:-}"        # empty = build3 default (de_core_news_lg)
MODEL_EN="${MODEL_EN:-}"        # empty = build3 default (en_core_web_sm)
BOOKS="${BOOKS:-kafka grimm birnbaum heidi zarathustra alice velveteen frankenstein}"

build_one() {                   # id lang infile title author extra-args...
  local id="$1" lang="$2" infile="$3" title="$4" author="$5"; shift 5
  local args=(--in "$infile" --lang "$lang" --id "$id"
              --title "$title" --author "$author" --data-dir "$DATA" "$@")
  local model_var="MODEL_${lang^^}"
  [ -n "${!model_var}" ] && args+=(--model "${!model_var}")
  [ -f "maps/orth_${id}.json" ] && args+=(--orth-subst "maps/orth_${id}.json")

  echo "==== $id ($lang)"
  python3 build3.py "${args[@]}"

  local gargs=(--book "$DATA/$lang/$id.json")
  [ -f "maps/emoji_${id}.json" ] && gargs+=(--emoji-map "maps/emoji_${id}.json")
  python3 gloss3.py "${gargs[@]}"

  python3 validate3.py --book "$DATA/$lang/$id.json" \
    --gloss "$DATA/gloss/$id.json" --sample "$SAMPLE"

  if [ -f vendor/cldr/annotations_de.json ]; then
    python3 emoji_map_gen3.py --gloss "$DATA/gloss/$id.json"
  fi
  echo
}

want() { case " $BOOKS " in *" $1 "*) return 0;; *) return 1;; esac; }

mkdir -p "$DATA/en" "$DATA/de" "$DATA/gloss" build ../build

# ---- German -------------------------------------------------------------
if want kafka; then
  [ -f ../build/kafka_utf8.txt ] || \
    iconv -f ISO-8859-1 -t UTF-8 ../sources/kafka.txt > ../build/kafka_utf8.txt
  build_one kafka de ../build/kafka_utf8.txt \
    "Die Verwandlung" "Franz Kafka" --skip-until '^I\.$'
fi
want grimm && build_one grimm de ../sources/grimm_de.txt \
  "Grimms Märchen" "Brüder Grimm" \
  --skip-until '^\s+Marienkind\s*$' --stop-at '^\s+Inhalt\s*$'
want birnbaum && build_one birnbaum de ../sources/Unterm_Birnbaum_de.txt \
  "Unterm Birnbaum" "Theodor Fontane" \
  --skip-until '^\s+I\.\s*$' --stop-at '^\s+Grote.{0,2}sche Sammlung'
want heidi && build_one heidi de ../sources/heidi_kann_brauchen_de.txt \
  "Heidi kann brauchen, was es gelernt hat" "Johanna Spyri" \
  --skip-until '^Reisezurüstungen\n\nDer freundliche'
want zarathustra && build_one zarathustra de ../sources/zarathustra_de.txt \
  "Also sprach Zarathustra" "Friedrich Wilhelm Nietzsche" \
  --skip-until '^Erster Theil\s*$'

# ---- English ------------------------------------------------------------
want alice && build_one alice en ../sources/Alice_en.txt \
  "Alice's Adventures in Wonderland" "Lewis Carroll" \
  --skip-until '^CHAPTER I\.'
want velveteen && build_one velveteen en ../sources/velveteen_rabbit_en.txt \
  "The Velveteen Rabbit" "Margery Williams" \
  --skip-until '^HERE was once a velveteen rabbit'
want frankenstein && build_one frankenstein en ../sources/frankenstein_en.txt \
  "Frankenstein; or, The Modern Prometheus" "Mary Wollstonecraft Shelley" \
  --skip-until '^Letter 1\s*$'

echo "done -> $DATA"
