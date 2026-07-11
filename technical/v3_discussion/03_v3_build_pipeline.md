# v3 build pipeline — status (2026-07-11, first small batch)

Implements the pinned schema (`02_v3_data_schema.md`, rev 2.1). All code
in `tools/v3/`; nothing in `tools/` top level was modified. No AI, no
audio (out of scope this session).

## What exists

- `tools/v3/chunk_hierarchy.py` — verbatim promotion of the ACCEPTED
  candidate-B chunker from `technical/v3_chunking_test/` (one sys.path
  line changed). Bug fixes land here from now on.
- `tools/v3/build3.py` — book file + `books.json`. Tokens/sp, 12-hex
  content-hash ids (+occ), paragraph flag `p`, UPOS, NER spans, breaks
  incl. strength-0 desperation cuts, per-level cuts, rungs, stats,
  provenance. Word-less spaCy "sentences" (stray quote marks) are
  absorbed at token level. `--orth-subst` accepts a reviewed
  substitution list (none exists yet → no `orth` fields baked).
- `tools/v3/gloss3.py` — glossary per schema (words/forms/freq/
  study_by_sent/sections, `overrides` empty). FreeDict deu-eng vendored
  under `tools/v3/vendor/` (gitignored; `--fetch` re-downloads; choice
  vs kaikki documented in `vendor/README.md`). German only.
- `tools/v3/validate3.py` — pure-JSON checker for all 5 schema
  invariants + gloss cross-checks; `--sample N` writes a human review
  file (`tools/v3/build/review_<book>.md`).

## First batch: Kafka, sm model (sandbox)

`parse_model: de_core_news_sm` is stamped in the output — **rebuild with
lg on the build machine before judging boundary/NER quality** (sm
over-tags entities; 450/870 sentences carry ents). Run:

    pip install -r tools/v3/requirements.txt
    python3 tools/v3/gloss3.py --fetch          # one-time
    cd tools/v3
    python3 build3.py --in ../build/kafka_utf8.txt --lang de --id kafka \
        --title "Die Verwandlung" --author "Franz Kafka" \
        --skip-until '^I\.$'
    python3 gloss3.py --book ../../docs/data3/de/kafka.json
    python3 validate3.py --book ../../docs/data3/de/kafka.json \
        --gloss ../../docs/data3/gloss/kafka.json --sample 25

Numbers (sm): 870 sentences, 19160 words, chunk-length CV 0.26–0.30 all
levels, hard caps respected, 389 desperation breaks (concentrated at
starter, as expected), 687 glossed lemmas, 284 misses (mostly OOV
compounds — report at `tools/v3/build/gloss_misses_kafka.txt`), all
invariants PASS.

## Decisions made in code (flag if you disagree)

- **Difficulty label** derivation is a provisional heuristic
  (`build3.py: difficulty_label()`); Kafka lands "advanced" (avg 22.0
  words/sentence, 51% rare lemmas). Tune after more books are built.
- **Gloss = first sense, ≤3 synonyms** from the entry's first usable
  line; homograph entries are picked by exact-case lemma match
  (verb `flimmern` over noun `Flimmern`).
- **Archaic fallbacks split by risk**: th→t / ey→ei / ß→ss may feed the
  live gloss (false hit ~impossible); ie→i and double-vowel collapse
  are REPORT-ONLY (`orth_candidates_<book>.txt`, "[UNVERIFIED]") after
  `beeilen→beilen→Beil` showed they can hit unrelated real words. The
  reviewed candidates become build3's `--orth-subst` input — that is
  the orthography pass of `00_v3_overview.md`.

## Next steps (in owner's preferred order: small batch → review → repeat)

1. Owner reviews `tools/v3/build/review_kafka.md` (+ misses/orth
   reports), then lg rebuild on the build machine.
2. More German books (Birnbaum will exercise the archaic-orthography
   path far more than Kafka).
3. v3 reader skeleton under `docs/v3/` consuming these files.
4. Later sessions: orth substitution lists, `d` difficulty scores,
   audio (Piper), AI passes (`g_de`, emoji map, overrides, rebus).
