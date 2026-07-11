# v3 — pre-processing overhaul (design record + status)

Cleaned up 2026-07-11 after the build pipeline was accepted. This is
the WHAT/WHY record; schema = `02_v3_data_schema.md` (pinned), build
HOW/status = `03_v3_build_pipeline.md`, v4 ideas = `01_v4_outlook.md`.
The original chunking deliberation (candidates A/B/C, four review
rounds) is preserved in `technical/v3_chunking_test/`.

App goal check: every feature exists to help people learn a language
by reading. Anything that doesn't serve that is out.

## Isolation (same rules as v2)

- v3 is a separate app under `docs/v3/`. v1 and v2 stay byte-identical;
  `docs/data/**` stays frozen forever.
- v3 data lives in `docs/data3/` (+ `books.json` there).
- localStorage key `zzzpeak.v3`; never write v1/v2 keys.

## Design principles (SETTLED, all honored by the implementation)

1. **Facts vs policy.** Data files carry facts about the text; the
   client carries pedagogy (session shapes, SRS, streaks, presets).
   If the line holds, v4+ features are JS-only — books are never
   reprocessed again.
2. **AI is optional, never load-bearing.** AI never runs inside the
   build; it produces optional fields the UI hides when absent, or
   reviewable artifacts the deterministic pipeline consumes.
   Rebuilding a book never calls an API.
3. **Stable IDs.** Content-hash sentence ids (+occ). Chunk position is
   ephemeral, keyed within the sentence.
4. **Provenance.** Every generated file: schema version, generator,
   source hash, parse model / dict version.

## The v3 data (DONE — tools/v3/, deterministic, offline)

Accepted this session; per-owner verdict the current build iteration
is satisfactory. One file per book; tokens first-class; everything
word-shaped is a token position.

- **Chunking**: nested break-point hierarchy (candidate B, accepted
  2026-07-11): per-sentence breaks + strengths (incl. strength-0 forced
  cuts), DP-derived nesting levels, adaptive progressive rungs. A
  client granularity dial (old candidate C) remains possible from the
  same data — UI decision, not data decision.
- **Glossary**: FreeDict (de→en) / WordNet (en→en, same-language),
  simplemma + wordfreq, POS-aware homograph/sense picks, book-complete
  `forms` map, `freq`, per-sentence study lists.
- **POS tags, NER spans** (PROPN-trimmed, en label-whitelisted),
  paragraph flags, per-book stats, review reports per book
  (misses / orth candidates / emoji suggestions / review sample).
- **Emoji**: curated map fallback; reviewed per-book
  `maps/emoji_<id>.json` via `--emoji-map`; CLDR suggestions
  report-only. Empty beats bad. While testing will use python script to generate emoji-map.
- **Orthography**: NOTHING changes displayed text. Reviewed
  `maps/orth_<id>.json` bakes per-token `orth` (display = user
  toggle; check mode and gloss lookup use the modern form).

## WHAT IS LEFT for v3

In rough order; 1–3 are the v3 core, 4–6 make it complete.

1. **The v3 reader app (`docs/v3/`) — the main remaining piece.**
   STARTED 2026-07-11: v2 app copied to `docs/v3/` and rewired to data3
   (per-owner approach: v2 behavior first, then features one by one).
   Wiring = `js/data3.js` derivation layer (toks/sp/cuts → flat chunks;
   Node-tested by `test_data3.js`: counts match books.json, reconstruction
   holds for all 3 books × 4 levels), one fetch per book, level switch
   without refetch (stays on the same sentence), progress sentence-keyed
   (id, occ) under `zzzpeak.v3`. Recorder/checker/TTS untouched.
   DONE so far: verb colouring (UPOS VERB+AUX → `--verb`) and subtle
   name rendering (ents → dotted underline), incl. the sentence-replay
   step; span join tested against chunk text in `test_data3.js`.
   Tap-word gloss bubble: focus-line word taps (focus chunk raised above
   the nav tap zones) → surface → lemma via forms, g_de-else-g_en from
   words, lemma emoji, `overrides[sid]` merge layer, orth-modernised
   lookup; entities gloss to "a name"; bubble dismissed on any other
   tap / nav / veil. Lookup lives in js/data3.js (glossLookup) and is
   node-tested: 100% lemma coverage of non-entity word tokens on all
   three built books.
   Feature list still to add (all data-ready):
   - level selection + nested chunk stepping; progressive-rung mode
     (rungs ⊆ advanced; ladder valid from any level);
   - ~~tap a word → gloss bubble (`forms` → `words`, no runtime
     lemmatizer)~~ (done); per-section pre-study list; per-sentence
     study words;
   - ~~verb coloring from POS; subtle name rendering from ents~~ (done);
   - orthography display toggle (orth field);
   - chunk emoji at runtime: rarest glossed word with non-empty `e`
     (zipf-0 tie-break by word order, dedup lemmas, skip ents);
   - check mode: grade against modernized form, discount entities;
   - chapter/section jump (TOC); tap/long-press → external dictionary;
   - library screen from `books.json` (stats, difficulty);
   - localStorage `zzzpeak.v3` progress keyed by (id, occ).

2. **Build the remaining books on the build machine (lg)**:
   grimm, birnbaum, heidi, zarathustra, alice, frankenstein —
   `bash tools/v3/build_data3.sh`; owner-review each (small batches).

3. **Orthography lists** (first real one: birnbaum — 1885 text) —
   review `orth_candidates_<id>.txt` → `maps/orth_<id>.json` → rebuild.

4. **Audio pass (script-only, no AI)** — Piper thorsten-medium on the
   build machine; one opus per sentence named by sentence id (all
   levels share files); `audio/<book>/manifest.json` with voice,
   coverage, per-sid durations; `books.json` audio field. Reader:
   sentence replay with Web Speech fallback; partial coverage fine.
   Rollout shortest-first (velveteen/kafka), judge on device.
   Chunk-level playback stays deferred (word timestamps via later
   forced alignment; no audio regeneration needed).

5. **AI passes (optional, additive, Mistral; reviewable artifacts)**
   - `g_de` one-line learner definitions (~A2), two-pass
     generate→grade, fallback `g_en`;
   - sense overrides keyed by sentence id (Schloss 🏰/🔒) incl.
     per-occurrence emoji;
   - per-book lemma→emoji map (replaces curated fallback);
   - `rebus` (2–4 emoji sentence recall), `para` (simple-German
     paraphrase), section `sum` ("previously on…") — all reserved
     fields already in the schema;
   - optional gloss-miss fills (OOV compounds from
     `gloss_misses_<id>.txt`).

6. Not gonna do: **Difficulty**: per-sentence `d` score (reserved field, formula
   TBD) + calibrate the provisional book-level difficulty label once
   several books are built.

Chunking itself: frozen except bug fixes / small patches, per owner.

## Build environment notes

- Build machine: MacBook Air (Intel 2c/4t, 7.7 GB, Debian 13); spaCy
  lg, Piper, aeneas all run there; unattended batch work.
- Mistral subscription for the AI passes; whole German corpus ~500k
  tokens — minutes against rate limits; model choice is a quality
  decision, not a cost one. Google AI Studio free tier as backup;
  Google/Mistral TTS rejected (rate limits / no German).
- Sandbox sessions: sm spaCy models only (lg download fails there);
  `parse_model` stamp keeps sm output distinguishable; German default
  stays lg.
