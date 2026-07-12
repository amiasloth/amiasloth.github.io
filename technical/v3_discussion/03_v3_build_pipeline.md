# v3 build pipeline — status (2026-07-12; first pinned 2026-07-11)

Implements the pinned schema (`02_v3_data_schema.md` rev 3.1) and the
deterministic half of `00_v3_overview.md`. All code in `tools/v3/`;
`tools/` top level and `docs/data/` (v1/v2) untouched. No AI at build
time; audio is a separate additive pass (audio3.py, below).

## DONE — components (all in `tools/v3/`)

- **books_src.toml** — per-book source metadata (paths, titles, trim
  regexes, encoding): the single source of truth. The audio pipeline
  deliberately does NOT read it (audio consumes built book files only).
- **build_data3.py** — the driver: the whole flow per book (build →
  gloss → validate+sample → emoji map gen), looped over books_src.toml.
  `BOOKS="kafka" SAMPLE=25 MODEL_DE=de_core_news_sm` env overrides;
  picks up reviewed `maps/orth_<id>.json` / `maps/emoji_<id>.json`
  automatically when they exist; falls back to the GENERATED
  `build/emoji_map_<id>.json` with `--emoji-map-generated` otherwise.
  Setup commands in its docstring. **build_data3.sh** is a thin
  wrapper (same envs, same muscle memory).
- **chunk_hierarchy.py** — the ACCEPTED candidate-B chunker, verbatim
  promotion from `technical/v3_chunking_test/` (one sys.path line
  changed). Bug fixes land here; the experiment copy is the decision
  record.
- **build3.py** — book file + `books.json`: tokens/sp, content-hash ids
  (+occ), paragraph flag, UPOS, NER spans, breaks (incl. strength-0
  desperation), per-level cuts, rungs, stats, provenance. Absorbs
  word-less spaCy "sentences" at token level. `--orth-subst` bakes a
  reviewed archaic→modern list into `orth` fields.
- **gloss3.py** — glossary (words/forms/freq/emoji_common/
  study_by_sent/sections). de: FreeDict deu-eng; en: WordNet 3.0 dictd
  (eng-eng = same-language definitions). `--fetch` vendors both
  dictionaries. `--emoji-map` consumes a `{lemma: emoji}` JSON;
  `--emoji-map-generated` flags it as the CLDR stand-in (curated
  emoji_map.py then wins collisions). `emoji_common` (rev 3.1) is the
  common-word chunk-emoji fallback channel, POS-guarded against
  function words. Uses baked `orth` for lookup when present (both
  spellings stay tappable in `forms`).
- **emoji_map_gen3.py** — CLDR-keyword emoji candidates (evolved from
  emoji_suggest3.py): human review report + a full {lemma: emoji} map
  over ALL gloss lemmas (stable across rebuilds; single-pass
  convergence). The map stands in for the reviewed one until the
  CLDR → Mistral review pipeline lands. `--fetch` vendors CLDR.
- **validate3.py** — pure-JSON check of all schema invariants
  (incl. emoji_common: disjoint from words, non-empty, reachable) +
  gloss cross-checks; `--sample N` writes `build/review_<id>.md`.
- **audio3.py** — additive audio pass (runs in the ephemeral
  `container/Dockerfile.audio` image via `container/audio.sh`, never
  the dev image): per-sentence opus by sid into the separate
  zzzpeak-audio repo + `manifest.json` + `timing.json` (per-run end
  times from piper1-gpl's NATIVE phoneme alignments — no forced
  alignment tool). Voices pinned: de_DE-thorsten-medium,
  en_GB-alba-medium. Timing logic unit-tested piper-free in
  `test_audio3_timing.py`.

Built so far in `docs/data3/`: **all 8 books** (de = lg, en = sm
production model), gloss rebuilt with emoji_common 2026-07-12. All
invariants PASS (`node docs/v3/test_data3.js` is the runtime gate).

## Review artifacts (per book, in `tools/v3/build/`, gitignored)

`review_<id>.md` (all levels + rungs + ents + study words),
`gloss_misses_<id>.txt` (rare lemmas without dict hit),
`orth_candidates_<id>.txt` (archaic→modern proposals; UNVERIFIED =
from aggressive rules, never glossed from),
`emoji_suggestions_<id>.txt` (CLDR candidates for review).

## Decisions baked into code (and their reasons)

- **NER guard**: ent spans are trimmed to their maximal PROPN runs
  (junk spans — Teufel PER, Zeit MISC — contain none and vanish;
  padded spans shrink so the padding stays glossable). English
  additionally keeps only name-like labels {PERSON, GPE, LOC, FAC,
  NORP} of the 18-label OntoNotes set. Personified characters (Boy,
  Bunny → PERSON) are kept: they function as names. Ent *labels*
  remain unreliable — consumers should trust the span, not the label.
- **Glosses**: first sense, ≤3 synonyms, one line. Homograph pick: the
  occurrence's baked UPOS narrows entries (FreeDict `<n>/<v>/<adj>`
  headword tags; WordNet per-POS sense blocks), then exact-case lemma
  match. German ADV maps to adj (German adjectives adverbialise
  unmarked; "clownishly"-style glosses were worse vocabulary items).
- **Orthography, extremely conservative by owner instruction**:
  displayed text is NEVER changed by the pipeline. Only a
  human-reviewed `--orth-subst` list bakes `orth` fields (display
  stays a user toggle). Live lookup fallbacks are limited to
  near-lossless th→t / ey→ei / ß→ss; aggressive rules (ie→i,
  double-vowel) are report-only after `beeilen→Beil` proved they can
  hit real words.
- **Emoji** (updated 2026-07-12, see 00/02 for the full record): two
  channels — study-word `e` + common-word `emoji_common`. Precedence:
  reviewed map > curated emoji_map.py > generated CLDR map (the
  generated one currently stands in for reviewed, owner-approved;
  `--emoji-map-generated` demotes it below curated). Restored v1
  chunk-emoji density (grimm 6%/14% → 41%/67% beginner/advanced).
- **Difficulty label**: provisional heuristic
  (`build3.py: difficulty_label()`), tune after more books exist.

## Known limitations (deterministic ceiling — AI-pass territory)

- Dictionary sense order within one part of speech: WordNet "whisker =
  a very small distance"; FreeDict figurative-first "Besen = shrew".
  The planned `g_de` / sense-override AI pass is the real fix.
- sm-model NER noise survives the label filter when the label is
  name-like ("china" GPE in velveteen); try `--model en_core_web_lg`
  on the build machine if it bothers.
- `books.json` difficulty for Kafka says "advanced" (avg 22 w/sent,
  51% rare lemmas) — label derivation not yet owner-calibrated.

## TODO (small batch → review → repeat)

1. ~~lg builds for the remaining books~~ (done 2026-07-12). Still
   open: review `orth_candidates_birnbaum.txt` into
   `maps/orth_birnbaum.json` (birnbaum is the archaic-heavy one).
2. Owner reviews per-book review files; refine in small patches.
3. ~~v3 reader skeleton~~ (done — see 00 §reader status).
4. Audio rollout: `container/audio.sh <book>` per book (smoke with
   `--limit 20` first and check the "N/M timed" output line — piper
   alignments are model-dependent), push zzzpeak-audio to Pages, set
   books.json `audio` base URL.
5. Per-sentence difficulty scores `d` (formula TBD), difficulty-label
   calibration.
6. AI passes (owner, in progress separately): `g_de`, sense
   overrides, CLDR → Mistral emoji map review (drops into
   `maps/emoji_<id>.json`, replacing the generated stand-in), `rebus`,
   `para`, section `sum`.
