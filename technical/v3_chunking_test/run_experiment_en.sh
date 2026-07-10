#!/usr/bin/env bash
# Candidate B chunking experiment — ENGLISH (see DIAGNOSIS_ENGLISH.md).
# English SHIPS on en_core_web_sm (tools/build_data.sh), so unlike German
# the sm run here is judgement-grade, not just a smoke test.
#   pip install -r ../../tools/requirements.txt
#   python -m spacy download en_core_web_sm
set -euo pipefail
cd "$(dirname "$0")"
MODEL="${MODEL:-en_core_web_sm}"
SRC=../../tools/sources

python3 chunk_hierarchy.py --in "$SRC/Alice_en.txt" --lang en \
  --skip-until '^CHAPTER I\.' --model "$MODEL" --out out/hierarchy_alice.json
python3 compare_report.py --hierarchy out/hierarchy_alice.json \
  --data ../../docs/data/en --book alice

echo
echo "Read these, in order:"
echo "  out/compare_section_1.html   (side-by-side, chapter I)"
echo "  out/metrics.md               (variance / long sentences / nesting)"
echo "  DIAGNOSIS_ENGLISH.md         (what was ported / diagnosed / fixed)"
