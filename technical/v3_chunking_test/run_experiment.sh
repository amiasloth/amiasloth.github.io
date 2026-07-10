#!/usr/bin/env bash
# Candidate B chunking experiment (see README.md).
# Run from anywhere; needs the same env as tools/build_data.sh:
#   pip install -r tools/requirements.txt
#   python -m spacy download de_core_news_lg
#
# Optional: MODEL=de_core_news_sm bash run_experiment.sh   (smoke test only —
# judge boundary quality ONLY on the lg run, same model the shipped data used)
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${MODEL:-de_core_news_lg}"
KAFKA=../../tools/build/kafka_utf8.txt

if [ ! -f "$KAFKA" ]; then
  iconv -f ISO-8859-1 -t UTF-8 ../../tools/sources/kafka.txt > /tmp/kafka_utf8.txt
  KAFKA=/tmp/kafka_utf8.txt
fi

python3 chunk_hierarchy.py --in "$KAFKA" --lang de \
  --skip-until '^I\.$' --model "$MODEL" \
  --out out/hierarchy_kafka.json

python3 compare_report.py

echo
echo "Read these, in order:"
echo "  out/compare_section_1.html   (side-by-side, section I)"
echo "  out/compare_section_2.html"
echo "  out/compare_section_3.html"
echo "  out/metrics.md               (variance / long sentences / nesting)"
