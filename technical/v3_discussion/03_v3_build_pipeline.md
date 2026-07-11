# v3 build pipeline — status (2026-07-11, after 5 review rounds)

Implements the pinned schema (`02_v3_data_schema.md` rev 2.1) and the
deterministic half of `00_v3_overview.md`. All code in `tools/v3/`;
`tools/` top level and `docs/data/` (v1/v2) untouched. No AI, no audio
— both remain future additive passes.

## DONE — components (all in `tools/v3/`)

- **build_data3.sh** — the whole flow per book (build → gloss →
  validate+sample → emoji suggestions). `BOOKS="kafka" SAMPLE=25
  MODEL_DE=de_core_news_sm` env overrides; picks up reviewed
  `maps/orth_<id>.json` / `maps/emoji_<id>.json` automatically when
  they exist. Setup commands in its header.
- **chunk_hierarchy.py** — the ACCEPTED candidate-B chunker, verbatim
  promotion from `technical/v3_chunking_test/` (one sys.path line
  changed). Bug fixes land here; the experiment copy is the decision
  record.
- **build3.py** — book file + `books.json`: tokens/sp, content-hash ids
  (+occ), paragraph flag, UPOS, NER spans, breaks (incl. strength-0
  desperation), per-level cuts, rungs, stats, provenance. Absorbs
  word-less spaCy "sentences" at token level. `--orth-subst` bakes a
  reviewed archaic→modern list into `orth` fields.
- **gloss3.py** — glossary (words/forms/freq/study_by_sent/sections).
  de: FreeDict deu-eng; en: WordNet 3.0 dictd (eng-eng = same-language
  definitions). `--fetch` vendors both dictionaries. `--emoji-map`
  consumes a reviewed `{lemma: emoji}` JSON. Uses baked `orth` for
  lookup when present (both spellings stay tappable in `forms`).
- **emoji_suggest3.py** — CLDR-keyword emoji suggestions, report-only
  (`--fetch` vendors the CLDR files).
- **validate3.py** — pure-JSON check of all 5 schema invariants +
  gloss cross-checks; `--sample N` writes `build/review_<id>.md`.

Built so far in `docs/data3/`: **kafka** (lg book, POS-aware gloss),
**velveteen** (en, production model). All invariants PASS.

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
- **Emoji**: `e` filled from curated emoji_map.py, overridden by a
  reviewed `--emoji-map` JSON — the identical entry point the future
  AI-drafted per-book map will use. CLDR suggestions are never
  auto-applied (empty beats bad).
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

1. `bash tools/v3/build_data3.sh` on the build machine (lg) for the
   remaining books: grimm, birnbaum, heidi, zarathustra, alice,
   frankenstein. Birnbaum will exercise the archaic-orthography
   reports far more than Kafka; review `orth_candidates_birnbaum.txt`
   into `maps/orth_birnbaum.json`.
2. Owner reviews per-book review files; refine in small patches.
3. Reviewed emoji maps (`maps/emoji_<id>.json`) from the suggestion
   reports — or wait for the AI map pass.
4. **v3 reader skeleton under `docs/v3/`** consuming these files
   (localStorage `zzzpeak.v3`) — the next big piece.
5. Per-sentence difficulty scores `d` (formula TBD), difficulty-label
   calibration.
6. Out of scope until their sessions: audio (Piper, per-sentence opus
   by sid), AI passes (`g_de`, sense overrides, emoji map, `rebus`,
   `para`, section `sum`).
