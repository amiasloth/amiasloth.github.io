#!/usr/bin/env bash
# Build all Zzzpeak book data into docs/data/.
#
# One-time setup:
#   pip install spacy
#   python -m spacy download en_core_web_sm
#   python -m spacy download de_core_news_lg
#
# Then:  bash tools/build_data.sh
set -euo pipefail
cd "$(dirname "$0")"

OUT=../docs/data
mkdir -p "$OUT/en" "$OUT/de" build

LEVELS="starter beginner intermediate advanced"

# ---- Alice's Adventures in Wonderland (en)
for level in $LEVELS; do
  python3 chunk.py --in sources/Alice_en.txt --lang en \
    --id alice --title "Alice's Adventures in Wonderland" \
    --skip-until '^CHAPTER I\.' \
    --level "$level" --out "$OUT/en/alice_${level}.json"
done

# ---- Die Verwandlung (de): Gutenberg file is ISO-8859-1 -> convert
iconv -f ISO-8859-1 -t UTF-8 sources/kafka.txt > build/kafka_utf8.txt
for level in $LEVELS; do
  python3 chunk.py --in build/kafka_utf8.txt --lang de \
    --id kafka --title "Die Verwandlung" \
    --skip-until '^I\.$' \
    --level "$level" --out "$OUT/de/kafka_${level}.json"
done

# ---- Grimms Märchen (de): each tale becomes a section
for level in $LEVELS; do
  python3 chunk.py --in sources/grimm_de.txt --lang de \
    --id grimm --title "Grimms Märchen" \
    --skip-until '^\s+Marienkind\s*$' --stop-at '^\s+Inhalt\s*$' \
    --level "$level" --out "$OUT/de/grimm_${level}.json"
done

# ---- Unterm Birnbaum (de)
for level in $LEVELS; do
  python3 chunk.py --in sources/Unterm_Birnbaum_de.txt --lang de \
    --id birnbaum --title "Unterm Birnbaum" \
    --skip-until '^\s+I\.\s*$' --stop-at '^\s+Grote.{0,2}sche Sammlung' \
    --level "$level" --out "$OUT/de/birnbaum_${level}.json"
done

# ---- library index
cat > "$OUT/books.json" <<'JSON'
{
  "books": [
    {
      "id": "alice",
      "title": "Alice's Adventures in Wonderland",
      "author": "Lewis Carroll",
      "lang": "en",
      "levels": ["starter", "beginner", "intermediate", "advanced"],
      "source": "Project Gutenberg"
    },
    {
      "id": "grimm",
      "title": "Grimms Märchen",
      "author": "Brüder Grimm",
      "lang": "de",
      "levels": ["starter", "beginner", "intermediate", "advanced"],
      "source": "Project Gutenberg"
    },
    {
      "id": "kafka",
      "title": "Die Verwandlung",
      "author": "Franz Kafka",
      "lang": "de",
      "levels": ["starter", "beginner", "intermediate", "advanced"],
      "source": "Project Gutenberg"
    },
    {
      "id": "birnbaum",
      "title": "Unterm Birnbaum",
      "author": "Theodor Fontane",
      "lang": "de",
      "levels": ["starter", "beginner", "intermediate", "advanced"],
      "source": "Project Gutenberg"
    }
  ]
}
JSON

echo "done -> $OUT"
