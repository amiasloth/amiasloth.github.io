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
- **Emoji**: two channels (2026-07-12). Rare/study words: emoji on the
  gloss entry, rarest-with-emoji wins the chunk pick. Common words:
  `gloss.emoji_common` fallback (schema rev 3.1) — restores v1 density
  (grimm: 6%/14% → 41%/67% of beginner/advanced chunks); function
  words excluded by UPOS guard. Precedence: reviewed map (planned:
  CLDR → Mistral review → `maps/emoji_<id>.json`) beats curated
  `emoji_map.py`; curated beats the GENERATED CLDR map that currently
  stands in for reviewed (`--emoji-map-generated`; owner decision —
  manual review doesn't scale, and UI density can't be judged
  emoji-less). Empty beats bad. `emoji_map_gen3.py` now maps ALL gloss
  lemmas, so the generated map is stable across rebuilds (the old
  empty-only map oscillated with the bake, needing two passes).
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
   Study lists: "Aa" header button → sheet with the current sentence's
   study words (study_by_sent[sid]) + the section pre-study list
   (sections[].study), lemma/emoji/gloss rows, display-only (known-word
   tracking is v4). Tested: section lists equal the first-occurrence
   derivation from study_by_sent on ALL 8 built books (test now runs
   the full library; heidi's merged-chapter issue shows as a 563-word
   section list — data, not reader).
   Study-word marks: faint accent underline on focus-line words whose
   lemma is in the sentence's study list; settings toggle ("Mark study
   words", default on). v3 entry link added to the v1 landing page
   (owner-approved touch of docs/index.html).
   Chunk emoji at runtime: Data3.chunkEmoji implements the 02 pick
   (rarest glossed non-entity lemma with non-empty `e`, OOV=0 rarest,
   word-order tie-break, dedup, overrides honoured), cached on the flat
   item so stars/veil hint reuse it; sentence step included. Unit-tested
   + estimated on grimm with the generated test map: ~6% of beginner /
   14% of advanced chunks get an emoji.
   Settings sheet is tabbed (Reading / Practice / Voice; tabs hidden
   when their feature is unavailable).
   Orthography + check grading: "Modernised spelling" display toggle
   (Reading tab, auto-hidden until a book carries orth); check mode
   grades against the MODERNISED reference with entities discounted
   (Match.score grew an optional per-token discount vector — missed
   names cost nothing, spoken names still count; diff renders the
   display form with marks from the modern scoring, all aligned via
   Data3.displayRuns). Node-tested incl. runs invariant on 13k real
   chunks. TTS keeps speaking the display text.
   TOC: the section-title line (now with ▾) opens a Contents sheet —
   every section with client-counted sentence count, current marked;
   tap jumps to the section's first chunk (current section = restart
   chapter) with clean mic/TTS handover. Hidden in review mode.
   Progressive rungs: v2's sentenceReplay generalised into a virtual-
   step QUEUE — after a sentence's last chunk, "After each sentence" =
   Keep reading / Read the whole sentence (old behavior) / Climb the
   ladder (each rung fine→coarse via Data3.ladderRanges, whole sentence
   last; rung equal to the level's cuts skipped). Old boolean pref seeds
   the new sentenceMode once. Back-swipe bails out of the ladder. Rung
   data invariants (⊆ advanced, nesting, ≠ advanced) now tested on all
   8 books; ladder tiling/order/dedup unit-tested.
   No-repeat guarantee (owner question, confirmed): a chunking is never
   shown twice in a row — builder never emits a rung equal to the
   advanced cuts or the whole sentence; the app skips a rung equal to
   the CURRENT level's cuts; single-chunk sentences never enter the
   ladder at all.

   SESSION CLOSE 2026-07-11. The v3 reader is feature-complete except
   two small items: (a) tap/long-press → external dictionary,
   (b) library-screen stats/difficulty polish. Regression check:
   `node docs/v3/test_data3.js` (no deps) validates the derivation
   layer + all data invariants against whatever is in docs/data3 —
   run it after any rebuild; it doubles as a data-review gate.
   On-device review still pending for: gloss bubble taps vs nav zones,
   study-word mark subtlety, ladder feel (no rung 2/3 indicator yet —
   five-minute add if disorienting), emoji density on device (the
   common-word channel landed 2026-07-12: sm-tested at grimm 41%/67%
   beginner/advanced; needs the lg rebuild + a look on the phone).
   Emoji-map phase (updated 2026-07-12): build_data3 falls back to the
   GENERATED build/emoji_map_<id>.json when no reviewed
   maps/emoji_<id>.json exists, passing --emoji-map-generated so the
   curated map wins collisions; the generated map now covers ALL gloss
   lemmas (stable across rebuilds, single-pass converge). Owner
   decision: the generated map STANDS IN for reviewed until the
   CLDR → Mistral pipeline; manual review of full maps doesn't scale.
   Build tooling (2026-07-12): per-book source metadata (paths, titles,
   trim regexes, encoding) moved to tools/v3/books_src.toml — single
   source of truth read by the new build_data3.py driver;
   build_data3.sh is a thin wrapper (same BOOKS/MODEL_*/SAMPLE envs).
   The audio pipeline deliberately never reads it: audio consumes only
   built book files + books.json.
   Feature list still to add (all data-ready):
   - ~~level selection + nested chunk stepping; progressive-rung mode
     (rungs ⊆ advanced; ladder valid from any level)~~ (done);
   - ~~tap a word → gloss bubble (`forms` → `words`, no runtime
     lemmatizer)~~ (done); ~~per-section pre-study list; per-sentence
     study words~~ (done);
   - ~~verb coloring from POS; subtle name rendering from ents~~ (done);
   - ~~orthography display toggle (orth field)~~ (done);
   - ~~chunk emoji at runtime: rarest glossed word with non-empty `e`
     (zipf-0 tie-break by word order, dedup lemmas, skip ents)~~ (done);
   - ~~check mode: grade against modernized form, discount entities~~
     (done);
   - ~~chapter/section jump (TOC)~~ (done); tap/long-press → external
     dictionary;
   - library screen from `books.json` (stats, difficulty);
   - localStorage `zzzpeak.v3` progress keyed by (id, occ).

2. **Build the remaining books on the build machine (lg)**:
   grimm, birnbaum, heidi, zarathustra, alice, frankenstein —
   `bash tools/v3/build_data3.sh`; owner-review each (small batches).

3. **Orthography lists** (first real one: birnbaum — 1885 text) —
   review `orth_candidates_<id>.txt` → `maps/orth_<id>.json` → rebuild.

4. **Audio pass (script-only, no AI)** — Piper thorsten-medium on the
   build machine; one opus per sentence named by sentence id (all
   levels share files); `manifest.json` with voice, coverage, per-sid
   durations; `books.json` audio field. Reader: sentence replay with
   Web Speech fallback; partial coverage fine. Rollout shortest-first
   (velveteen/kafka), judge on device.
   Decisions 2026-07-12:
   - Voices PINNED: `de_DE-thorsten-medium`, `en_GB-alba-medium`
     (owner auditioned rhasspy piper-samples; cori-high rejected for
     2–3× synth cost, southern_english_female ships low-only).
     Switching later = full resynthesis, so pinned before batch runs.
   - Chunk-level playback CONFIRMED via per-RUN timestamps on the
     sentence audio, sidecar `timing.json` (NOT in the manifest).
     IMPLEMENTED (2026-07-12) with piper1-gpl's NATIVE phoneme
     alignments (`include_alignments=True`; space phonemes delimit
     words) — no forced-alignment tool at all, timing extracted
     during synthesis in audio3.py (supersedes the aeneas plan; no
     new container deps). Granularity = display runs (whitespace
     units); reader maps token→run via sp bits (Data3.audioSlice),
     chunk = seek t0, stop t1 (rAF loop; Web Audio sample-accurate
     slicing is the upgrade path — Pages sends CORS *). Never
     per-chunk files: the chunker still evolves and would invalidate
     them; run timestamps survive chunker changes with zero
     recompute. Sentences where espeak's word count disagrees with
     the run count get no timing (partial timing OK, like partial
     coverage; those chunks fall back to Web Speech).
   - Reader integration (IMPLEMENTED 2026-07-12): js/audio3.js
     (BookAudio) slots BEHIND speakCurrent() — book audio first, Web
     Speech fallback per sentence — so ttsFirst shadowing, check
     mode's "hear it first", A/B compare and the 🔊 button all get
     real audio with no flow changes. Activated by `audio` base URL
     in books.json (absolute; files at <base>/<id>/<sid>.opus).
     Existing "Voice speed" pref maps onto audio.playbackRate
     (pitch-preserving). Offline audio deferred — online-only v1
     (cross-origin SW caching is the ugly part, not playback).
   Decisions 2026-07-11:
   - Per-sentence files CONFIRMED over one whole-book file +
     timestamps. Whole-book loses for a sentence-replay reader: a
     long book at 24 kbps exceeds GitHub's 100 MB per-file limit;
     playing one sentence means HTTP-range seeking into Ogg (fragile
     on mobile) or downloading the whole book vs ~15 KB fetches; no
     incremental regeneration; identical sentences can't share a
     file. Whole-book + forced alignment (aeneas) only makes sense
     if a human-read audiobook (LibriVox) is ever aligned — v4+
     idea, and even then it gets sliced to per-sentence files.
   - Hosting: SEPARATE repo (`zzzpeak-audio`) with its own GitHub
     Pages site. Keeps the app repo small, gets its own ~1 GB Pages
     budget (whole corpus ≈ 350–450 MB at 24 kbps; 16 kbps mono is
     the fallback lever, judge on device). github.io serves
     `Access-Control-Allow-Origin: *`, so cross-origin fetch works.
     `books.json` `audio` = absolute base URL; manifests live with
     the audio. Audio is write-once (sid-named), so no git churn.
   - Build: NOT in the dev image (at its size budget — spaCy trf
     already didn't fit). Ephemeral second image
     `container/Dockerfile.audio`: debian-slim + `pip piper-tts`
     (piper1-gpl, ONNX — no torch, ~300 MB total) + `opus-tools`
     (opusenc); voice `.onnx` bind-mounted from the host, run with
     `--rm` writing into the audio repo checkout. piper1-gpl is
     GPL-3.0: no impact — generated audio is ours, no piper code is
     vendored. Stamp voice name + model card/license in the
     manifest provenance.

5. **AI passes (optional, additive, Mistral; reviewable artifacts)**
   All AI tooling lives in `tools/ai/` (owner 2026-07-12): versioned
   prompt files, COMMITTED JSONL response cache keyed by prompt
   version, unreviewed artifacts in `tools/ai/build/`, `--mock`
   plumbing mode; MISTRAL_API_KEY env; never runs inside the build.
   - `g_de` one-line learner definitions (~A2), two-pass
     generate→grade, fallback `g_en`;
     TOOL BUILT 2026-07-12 (`tools/ai/gde3.py`; shared plumbing
     extracted to `tools/ai/mistral3.py` when it became the second
     consumer): study lemmas + first-occurrence sentence → simple
     German one-liners; the prompt trusts the SENTENCE over the
     dictionary gloss, so this pass also catches FreeDict's wrong
     senses (grimm's Holzhacker = "dirty player"). Pre-checks
     (headword-leak stem match, length) before the grader; rejects
     fall back to `g_en`. `build/g_de_<id>.json` → review →
     `maps/g_de_<id>.json`, auto-baked by gloss3 into
     `words[].g_de` (reader already prefers g_de). German books
     only. Awaiting first real run.
   - sense overrides keyed by sentence id (Schloss 🏰/🔒) incl.
     per-occurrence emoji;
   - per-book lemma→emoji map (replaces curated fallback);
     TOOL BUILT 2026-07-12 (`tools/ai/emoji3.py`, generate→grade,
     both stages Mistral, empty-beats-bad end to end): `--book <id>`
     covers STUDY lemmas only (gloss + first-occurrence sentence fix
     the sense → liberal rubric) → `build/emoji_ai_<id>.json`, review
     → `maps/emoji_<id>.json` (existing gloss3 entry point). Second
     product split off (owner 2026-07-12): the GENERAL map — common
     lemmas from each book's text plus `--general` (wordfreq top-N,
     lemmatised), graded with a stricter NO-context rubric (dominant
     sense only) — accumulates in
     `build/emoji_general_candidates_<lang>.json`, review →
     `maps/emoji_general_<lang>.json`, a new gloss3 layer BELOW the
     curated emoji_map.py. Precedence: reviewed-book > emoji_map.py >
     general > CLDR-generated; the machine never edits or outranks
     the hand-picked file. Kafka pilot RAN 2026-07-12
     (mistral-large-latest) and tuned the pipeline: sanity filter
     widened (arrows/clocks/keycap digits — 8️⃣ for "acht" is right),
     gender-ZWJ variants normalised to the base (🏃‍♂️→🏃), graders
     relaxed to _v2 ("when torn, keep"), and PAIRS allowed (≤2 emoji
     for compounds: Holzhacker → 🪵🪓; the reader renders the raw
     string in all three surfaces — chunk hint, gloss bubble, study
     sheet — so pairs are UI-free). `--new-cache` moves the cache
     aside for model A/B (mistral-medium-latest = Medium 3.5 is the
     current frontier pick). Dictionary-sense errors the pilot
     surfaced (FreeDict Holzhacker = "dirty player") are NOT an
     emoji problem — the g_de pass fixes those (it trusts the book
     sentence over the gloss).
   - `rebus` (2–4 emoji sentence recall), `para` (simple-German
     paraphrase), section `sum` ("previously on…") — all reserved
     fields already in the schema;
   - optional gloss-miss fills (OOV compounds from
     `gloss_misses_<id>.txt`).
     TOOL BUILT 2026-07-12 (`tools/ai/gfill3.py`): misses + surfaces
     + first-occurrence sentence (token scan — misses have no
     study_by_sent entry) → `g_en` (+ `g_de`, de books), the two
     fields graded independently; g_en fails = entry dropped, g_de
     fails = ships without. Proper names refused by prompt and
     grader. `build/gloss_fill_<id>.json` → review →
     `maps/gloss_fill_<id>.json`; gloss3 turns a filled miss into a
     FULL study entry (words/freq/study lists/emoji precedence) —
     kafka test: 713→715 glossed, validate3 green. Run order: gfill
     → rebuild → emoji3 rerun sees the new words as study lemmas.
     Awaiting first real run.

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
