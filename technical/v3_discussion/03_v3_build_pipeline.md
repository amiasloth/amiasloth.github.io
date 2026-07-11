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

## Round 2 (2026-07-11, after owner review of the lg run)

- **NER guard**: build3 now trims every entity span to its maximal
  PROPN runs and drops spans without one. On the owner's lg Kafka this
  removes all 124 junk spans (Teufel PER, Pelzmuff MISC, Zeit MISC…)
  and shrinks padded ones ("Gregor das Kriechen" → "Gregor"), keeping
  the padding glossable. Needs a lg rebuild to take effect in
  `docs/data3`. Note: sm/lg still mislabel the *label* (Gregor LOC);
  consumers should trust the span ("is a name"), not the label.
- **Orthography flow confirmed conservative**: displayed text is never
  changed by the pipeline. A human-reviewed `--orth-subst` list bakes
  `orth` fields; gloss3 then looks up the modern form (and maps BOTH
  surfaces in `forms`), check mode grades against it. Without a list,
  only the near-lossless th/ey/ß lookup fallbacks are live; aggressive
  rules stay report-only.
- **Emoji**: `emoji_suggest3.py` generates CLDR-based suggestions
  (report-only, `build/emoji_suggestions_<book>.txt`; de-keyword +
  en-gloss-keyword matches, stopword/symbol-filtered; Kafka: 249/699
  empty lemmas get candidates, quality mixed — English polysemy like
  Türflügel="leaf"→🌿 is why nothing is auto-applied). Reviewed picks
  go into a `{lemma: emoji}` JSON consumed by `gloss3.py --emoji-map`
  — the same entry point the future AI-drafted map will use.

## Round 3 (2026-07-11, English + emoji-map flow)

- **English glossing**: gloss3 now handles `lang: en` books using
  WordNet 3.0 (dictd build, vendored via `--fetch` alongside FreeDict)
  — eng-eng, i.e. same-language definitions, matching the owner's
  same-language preference. Archaic-orthography machinery stays
  German-only. Velveteen built end-to-end (en_core_web_sm IS the
  production en model): 226 sentences, 72 glossed lemmas, all
  invariants PASS. Limitation: WordNet sense order isn't frequency
  order ("whisker = a very small distance").
- **emoji_suggest3 --fetch + en mode**: for en gloss files the lemma is
  matched against en CLDR keywords directly (definition text is too
  noisy); precision is high (🐾 paw, 🧑‍🌾 gardener, 🧸 plaything).
- **Emoji-map flow demonstrated** (`build/emoji_map_demo_kafka.json`):
  review `emoji_suggestions_<book>.txt` → keep good lines in a
  `{lemma: emoji}` JSON → `gloss3.py --emoji-map map.json` → study
  lists render "aufsperren = unlock 🔓". The demo file is Claude-picked,
  NOT owner-reviewed; replace before shipping.
- FreeDict first-sense weakness noted for later: "Besen = shrew,
  hellcat" (figurative sense first), "Schwenk = panning shot". The
  planned AI `g_de`/sense pass is the real fix.

## Round 4 (2026-07-11, English NER labels + WordNet senses)

- **en label whitelist** (build3): English models use the 18-label
  OntoNotes set; only name-like labels {PERSON, GPE, LOC, FAC, NORP}
  are kept as ents now (Christmas TIME, Rabbit WORK_OF_ART, Aunts ORG
  → gone). German's 4-label set stays whole. Personified characters
  (Boy, Bunny, Fairy → PERSON) are kept deliberately — they function
  as names. Residual sm noise remains ("china" GPE, "Rabbit" FAC);
  try `--model en_core_web_lg` on the build machine if it bothers.
- **POS-aware WordNet senses** (gloss3): the occurrence's baked UPOS
  picks the sense block — "peep" (verb) now glosses "look furtively",
  not the bird cry. Sense order WITHIN one part of speech is still
  WordNet's ("whisker" n 1 = "a very small distance"); that residue is
  AI-pass territory, not deterministic.

## Round 5 (2026-07-11, POS-aware German lookup)

FreeDict headword lines carry `<n>/<v>/<adj>/<adv>` tags; gloss3 now
narrows homograph entries to the tag matching the occurrence's baked
UPOS before the exact-case tiebreak (Leben the noun vs leben the verb).
German twist discovered on the first diff: German adjectives work as
unmarked adverbs, so spaCy tags them ADV and the `<adv>` entries gave
awkward English ("clownishly", fake "unhurtly") — de maps ADV→adj (the
base adjective IS the vocabulary item; true adverbs like "gern" reach
their adv entry via pool fallback). Kafka diff: 43/713 glosses changed,
mostly upgrades ("hungern = fast" → "Hungern = fasting", "führend =
going" → "leading", "zumachen = cap a pen" → "seal sth.",
"augenblicklich = at the moment" → "immediate"). `docs/data3/gloss/`
regenerated (kafka); book files unchanged.

## Next steps (in owner's preferred order: small batch → review → repeat)

1. Owner reviews `tools/v3/build/review_kafka.md` (+ misses/orth
   reports), then lg rebuild on the build machine.
2. More German books (Birnbaum will exercise the archaic-orthography
   path far more than Kafka).
3. v3 reader skeleton under `docs/v3/` consuming these files.
4. Later sessions: orth substitution lists, `d` difficulty scores,
   audio (Piper), AI passes (`g_de`, emoji map, overrides, rebus).
