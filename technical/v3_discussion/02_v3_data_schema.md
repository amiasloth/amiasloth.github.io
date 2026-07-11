# v3 data schema (PINNED — 2026-07-11)

Status: PINNED. Owner-accepted after two clarifications folded in
(sense-override emoji layer; per-sentence study lists for daily mode).
This is the frozen contract that `tools/build3.py` fills and the v3 reader
consumes. Realises the SETTLED features in `00_v3_overview.md` (tokens
first-class, stable IDs, POS, NER, nested chunks, glossary, orthography,
stats, provenance). Nothing here requires AI or audio; AI/audio fields
are named but optional and absent until those passes run.

Design deltas from v2 worth stating up front:

- **One file per book**, not four. Tokens are stored once; every level
  is just a different set of cut positions into the same token list.
  This kills v2's ~4× duplication and is what makes "levels nest" and a
  future granularity dial (candidate C) free — the cuts are derivable
  from `breaks` by the DP, and baked here only so the reader needs zero
  parsing work at load.
- **Everything word-shaped is a token position**, never a substring:
  POS, NER, breaks, cuts, orthography. One parse serves every level.
- Chunk *text* is never stored; it is reconstructed by joining a token
  slice. The reconstruction invariant (join of all tokens == source
  sentence) is a build-time check.

## File layout

    docs/data3/
      books.json                 # library index + aggregate stats
      de/<book>.json             # one file per book (all levels)
      en/<book>.json
      gloss/<book>.json          # glossary + forms map + study lists
      # (later, out of this session)
      audio/<book>/<sid>.opus     # per-sentence audio, by sentence ID

localStorage namespace: `zzzpeak.v3` only. `docs/data/**` (v1/v2) stays
frozen and untouched.

## Provenance (every generated file)

Top-level keys on every file so "does this need regenerating?" is
answerable at a glance:

    "schema":      3,                       // schema version integer
    "generator":   "build3.py@<gitshort>",  // tool + version
    "source_hash": "sha256:<12hex>",         // hash of the source text
    "parse_model": "de_core_news_lg"          // model that produced pos/ner/breaks

`parse_model` is recorded because it changes POS/NER/break output.
Owner default is `de_core_news_lg` for German, `en_core_web_sm` for
English. Sandbox/test batches use the sm model for both (records
`de_core_news_sm`) — a rebuild on the build machine with lg supersedes
it, and the stamp makes that visible.

## Book file — `docs/data3/<lang>/<book>.json`

    {
      "schema": 3,
      "generator": "build3.py@0000000",
      "source_hash": "sha256:...",
      "parse_model": "de_core_news_sm",
      "id": "kafka",
      "title": "Die Verwandlung",
      "author": "Franz Kafka",
      "lang": "de",
      "levels": {                 // level presets = DP length targets
        "starter":      {"min":2,"target":2,"max":3,"pref":0},
        "beginner":     {"min":2,"target":3,"max":5,"pref":30},
        "intermediate": {"min":2,"target":5,"max":8,"pref":55},
        "advanced":     {"min":3,"target":8,"max":12,"pref":80}
      },
      "stats": { ... see below ... },
      "sections": [
        { "title": "I.", "sentences": [ <sentence>, <sentence>, ... ] }
      ]
    }

### Sentence object

Every field except `id`, `toks`, `sp` is omitted when empty, to keep
files small.

    {
      "id":   "e16b0a3a",       // content hash: sha256(NFC-normalised,
                                //   whitespace-collapsed text)[:8]
      "occ":  0,                 // occurrence counter; omitted when 0.
                                //   Distinguishes repeated identical
                                //   sentences so (id,occ) is unique.

      "toks": ["Sie","werden","ihn","gleich","sehen",",",
               "wenn","Gregor","aufmacht","."],
                                // tokens as tokenised at build time,
                                //   INCLUDING punctuation. Tokenisation
                                //   is model-independent, so sm/lg agree
                                //   and break indices stay valid.

      "sp":   "1111011100",     // per-token trailing-whitespace bit.
                                //   Reconstruct text = join tok + (sp?" ":"")

      "pos":  ["PRON","AUX","PRON","ADV","VERB","PUNCT",
               "SCONJ","PROPN","VERB","PUNCT"],
                                // per-token UPOS. Drives verb colouring
                                //   and any future grammar feature.

      "ents": [[7,8,"PER"]],     // named-entity spans [start,end,label],
                                //   end-exclusive, token offsets. Gloss
                                //   skips these; reader renders them
                                //   subtly; check-mode discounts them.

      "breaks": [[2,10],[6,85],[8,45]],
                                // candidate break BEFORE token k with
                                //   strength s: [k,s]. The full hierarchy;
                                //   levels/dial derive from this.

      "cuts": {                 // baked chunk boundaries per level =
        "advanced": [],          //   token indices to cut before. Derived
        "intermediate": [6],     //   from breaks by the DP; baked so the
        "beginner": [6],         //   reader needs no solver at load.
        "starter": [2,6]         //   [] = whole sentence is one chunk.
      },

      "rungs": [],               // progressive merge ladder (coarse→fine)
                                //   as lists of cut-index sets; adaptive
                                //   count (2 short / 3 long). [] when the
                                //   sentence is short enough for none.

      "orth": {},                // token index → modernised form, only
                                //   where it differs (e.g. {"3":"Tür"}).
                                //   Omitted when nothing differs. Check-
                                //   mode + gloss lookup use the modern
                                //   form; display is a user toggle.

      "d": null,                 // RESERVED (script): per-sentence
                                //   difficulty score. Consumer: v4 daily
                                //   ease-in. Omitted until computed.

      "rebus": null              // RESERVED (AI, absent now): 2–4 emoji
                                //   sentence summary for hide-text recall.
    }

Notes:

- **Chunk emoji is not stored on the sentence.** Per `00_overview`,
  emoji live on lemmas (in the gloss file) so the same word → same
  emoji everywhere; a chunk's emoji is computed at runtime as the emoji
  of its rarest word(s). This keeps emoji independent of which level's
  cuts are active. The optional sentence-level `rebus` is the one emoji
  field that lives here.
- **Sense overrides refine the emoji per occurrence.** "Same word →
  same emoji" is the default; the gloss file's `overrides` block (keyed
  by sentence `id`) is the exception layer for occurrences that use a
  different sense (Schloss 🏰 vs 🔒). When the reader renders sentence
  `X` it consults `overrides[X][lemma]` before the lemma default — for
  both the shown gloss and the emoji that feeds the chunk-emoji pick.
  Absent (the case now) → default everywhere; still functional.
- `cuts` and `rungs` index the **same** token list as `breaks`. A cut
  index is a legal break position; the reader slices `toks` there.

## Glossary file — `docs/data3/gloss/<book>.json`

Amends the 06 spec into the v3 layout (per book, not per level).

    {
      "schema": 3, "generator": "gloss.py@...", "lang": "de",
      "words": {                          // key = normalised lemma
        "aufmachen": {"l":"aufmachen","g_en":"to open","e":""},
        "gregor":    null                  // named entities excluded
      },
      "forms": {                          // runtime-critical: surface→lemma
        "aufmacht":"aufmachen","öffnet":"öffnen","thür":"tür"
      },
      "freq": {"aufmachen":3.8},          // RESERVED (script): lemma zipf,
                                          //   for "you know X% of this book"
      "study_by_sent": {                  // per-sentence study lemmas,
        "e16b0a3a": ["aufmachen"]          //   keyed by sentence id. Daily
      },                                   //   mode unions the window's ids;
                                          //   section study is derived from
                                          //   this.
      "overrides": {},                    // RESERVED (AI, absent now): sense
                                          //   exceptions keyed by sentence id,
                                          //   e.g. {"<sid>":{"schloss":
                                          //   {"g_en":"lock","e":"🔒"}}}
      "sections": [
        {"title":"I.","study":["aufmachen","..."]}  // pre-study list,
                                          //   first-occurrence order
                                          //   (derivable from study_by_sent)
      ]
    }

- `g_en`: offline dictionary gloss (deterministic, always present on a
  hit). `g_de` (AI learner definition) is an optional key added by the
  later AI pass; `overrides` (sense exceptions, incl. per-occurrence
  emoji) is the AI-filled exception layer — both absent now, reader
  falls back to `words[lemma]` / `g_en`.
- `study_by_sent[sid]` lists the worth-studying (rare, glossed) lemmas
  occurring in that sentence. **Daily session** (e.g. sentences 25–30):
  the client counts sentences in the book file to get the window's IDs,
  unions their `study_by_sent` entries in order, dedups, and subtracts
  the learner's already-known set (localStorage). Works for any window,
  including across section boundaries. No runtime lemmatiser needed.
- `e`: lemma emoji. No-AI fallback = curated `emoji_map.py` + CLDR
  suggestions; AI-drafted per-book map replaces it later. Empty allowed
  and preferred over a forced bad emoji.
- `forms` is book-complete (every surface form occurring in the book)
  because the browser has no lemmatiser. Same NFC/archaic normalisation
  on both build and runtime sides.

## books.json — library index + stats

    {
      "schema": 3,
      "books": [
        {
          "id":"kafka","title":"Die Verwandlung","author":"Franz Kafka",
          "lang":"de","levels":["starter","beginner","intermediate","advanced"],
          "source":"Project Gutenberg",
          "difficulty":"intermediate",       // derived label
          "stats":{                            // aggregate, for v4 daily mode
            "sentences": 1,
            "words": 8,
            "chunks": {"starter":3,"beginner":2,"intermediate":2,"advanced":1},
            "avg_sentence_len": 8.0,
            "vocab_below_zipf4": 0.12          // share of rare lemmas
          },
          "audio": null                        // set when audio exists
        }
      ]
    }

Per-book `stats` (counts per level/section, avg length, vocab profile,
difficulty) also live in each book file's `stats` header; `books.json`
carries the aggregate the library screen and daily-mode arithmetic need
without opening every book.

## Invariants the builder must check

1. **Reconstruction**: for each sentence, `join(toks, sp)` equals the
   source sentence exactly.
2. **Nesting**: `cuts[coarser] ⊆ cuts[finer]` for every level pair; each
   rung's cut-set ⊆ the next finer rung's.
3. **Legal cuts**: every index in `cuts` / `rungs` appears in `breaks`
   (or is a sentence boundary).
4. **ID uniqueness**: `(id, occ)` unique within a book.
5. **No punct-only chunk**: every chunk slice contains ≥1 alnum token.

## What is NOT in this schema yet (by design, this session)

- `g_de`, sense overrides, AI emoji map, `rebus`, paraphrases, section
  summaries — the external-AI passes.
- `audio` files and per-sentence durations — the Piper pass.

Both are additive: they fill reserved keys or add sibling files, never
reshape what is above. Provenance stamps + stable `(id,occ)` make the
one-time regeneration safe for user progress.
