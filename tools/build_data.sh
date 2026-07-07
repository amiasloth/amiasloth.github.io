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

# ---- Alice (en): the source is one book split into 3 consecutive files
cat sources/alice_part01.txt sources/alice_part02.txt sources/alice_part03.txt \
  > build/alice_full.txt

for level in starter beginner intermediate advanced; do
  python3 chunk.py --in build/alice_full.txt --lang en \
    --id alice --title "Alice's Adventures in Wonderland" \
    --skip-until '^CHAPTER I\.' \
    --level "$level" --out "$OUT/en/alice_${level}.json"
done

# ---- Die Verwandlung (de): Gutenberg file is ISO-8859-1 -> convert
iconv -f ISO-8859-1 -t UTF-8 sources/kafka.txt > build/kafka_utf8.txt

for level in starter beginner intermediate advanced; do
  python3 chunk.py --in build/kafka_utf8.txt --lang de \
    --id kafka --title "Die Verwandlung" \
    --skip-until '^I\.$' \
    --level "$level" --out "$OUT/de/kafka_${level}.json"
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
      "id": "kafka",
      "title": "Die Verwandlung",
      "author": "Franz Kafka",
      "lang": "de",
      "levels": ["starter", "beginner", "intermediate", "advanced"],
      "source": "Project Gutenberg"
    }
  ]
}
JSON

echo "done -> $OUT"
