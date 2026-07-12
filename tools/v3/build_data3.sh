#!/usr/bin/env bash
# Thin wrapper kept for muscle memory / docs: the v3 build driver is
# build_data3.py, per-book metadata lives in books_src.toml.
# Same env vars as always: BOOKS, MODEL_DE, MODEL_EN, SAMPLE.
#
#   bash tools/v3/build_data3.sh
#   BOOKS="kafka velveteen" bash tools/v3/build_data3.sh
#   MODEL_DE=de_core_news_sm bash tools/v3/build_data3.sh
set -euo pipefail
cd "$(dirname "$0")"
exec python3 build_data3.py "$@"
