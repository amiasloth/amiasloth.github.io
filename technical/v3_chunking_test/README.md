# v3 chunking experiment — candidate B (break-point hierarchy)

Implements the OPEN experiment from
`technical/v3_discussion/00_v3_overview.md` → "OPEN — chunking strategy".
Throwaway experiment code; nothing here ships. `tools/` and `docs/` are
untouched.

## What it does

`chunk_hierarchy.py` — candidate B, script-only:

1. Per sentence, computes **break points once**, each with a strength
   read off the dependency parse (strong punct 100 > clause 80 >
   verb-attached PP 65 > comma 55 > NP edges 45 > modifier 30 > other
   subtree edge 20 > desperation 5). Fusion rules mirror
   `tools/chunk.py` (no cut after articles/preps/conjunctions/relative
   pronouns, verb clusters atomic, punctuation never stranded).
2. Derives the four levels **top-down** (advanced → starter) with a DP
   length balancer (Knuth-Plass style: squared deviation from target +
   cost for weak breaks + level strength preference). Because finer
   levels only add cuts inside coarser chunks, **levels nest by
   construction** — moving up a level = merging familiar pieces.
3. Emits per sentence: all break points + strengths, per-level cuts and
   chunk texts, and the adaptive "halves" rung (strongest break nearest
   the middle) for the progressive-rung idea.
4. Same hard invariant as the current chunker: chunks concatenate back
   to the exact sentence text.

`compare_report.py` — loads the shipped `docs/data/de/kafka_*.json`
(current chunker, all four levels), aligns them sentence-by-sentence
with candidate B, and writes:

- `out/compare_section_N.html` — side-by-side reading view per section,
  every sentence × every level, word counts on each chunk, over-max /
  under-min highlighted, halves rung shown for long sentences.
- `out/metrics.md` — the numbers for the four judgment questions:
  length variance + adjacent-length fluctuation (the "2–6–2"
  complaint), % runts / % over cap, long-sentence worst chunks,
  nesting-violation counts (candidate must be 0; current is expected
  non-zero — that's what blocks adaptive rungs today).

## Run it (build machine)

Same env as `tools/build_data.sh` (spacy 3.8.14 + `de_core_news_lg`):

    bash technical/v3_chunking_test/run_experiment.sh

Then read `out/compare_section_1.html` first and judge:

1. boundary quality vs current
2. length variance at intermediate/advanced
3. long-sentence behavior under the hard cap
4. whether nesting visibly hurts any level

`MODEL=de_core_news_sm bash run_experiment.sh` works as a smoke test,
but boundary-quality judgment only counts on the lg run — the shipped
baseline was parsed with lg, and sm's parse differences would be unfair
to both sides.

## What this deliberately does NOT do

- No AI break refinement (that's the optional add-on for B/C, only
  worth wiring up if script-only B wins).
- No changes to `tools/chunk.py`, no v3 data emission, no decision —
  the point is evidence for choosing A vs B vs C.

## Files

    chunk_hierarchy.py   candidate B implementation
    compare_report.py    side-by-side HTML + metrics vs shipped data
    run_experiment.sh    driver
    RESULTS.md           what a smoke run shows + how to read the output
    out/                 generated (kept out of the repo's app dirs)
