# v3 data schema (PINNED — 2026-07-11, rev 2)

Status: PINNED. Owner-accepted after two clarifications folded in
(sense-override emoji layer; per-sentence study lists for daily mode).
Rev 2 (same day, post-review): desperation cuts surfaced in `breaks`
with strength 0; sentence ids widened to 12 hex + uniqueness invariant;
`freq` promoted from reserved to required (chunk-emoji pick needs it);
rungs⊆advanced invariant stated; paragraph flag `p` added (consumer:
daily-mode paragraph quota); reserved fields `para`/`sum` named; audio
manifest located; provenance completed for gloss/books.json.
Rev 2.1 (2026-07-11, first implementation — clarifications only, no
reshape): (a) the omit-when-empty rule is also applied INSIDE `cuts`:
empty per-level lists are dropped, and `cuts` itself is dropped when all
levels are empty — reader rule: missing level/missing `cuts` = whole
sentence is one chunk (reason: ~2% of sentences have no cuts anywhere
and short sentences rarely cut above beginner; spelling out empty lists
is pure weight). (b) gloss `sections[].study` is deduped per section
only, NOT across sections (a lemma can appear in several sections'
pre-study lists) — matches the 06 wording "the rare lemmas of that
section", and cross-section dedup stays derivable client-side from
`study_by_sent` order. Builder lives in `tools/v3/` (build3.py /
gloss3.py / validate3.py), NOT `tools/build3.py` as written below —
tools/ top level stays untouched per owner instruction.
This is the frozen contract that `tools/v3/build3.py` fills and the v3 reader
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
      audio/<book>/manifest.json  # voice, version, coverage, per-sid
                                  #   durations (v4 session time estimate)

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
      "id":   "e16b0a3a91c4",   // content hash: sha256(NFC-normalised,
                                //   whitespace-collapsed text)[:12].
                                //   12 hex (48 bits): 8 hex gave ~1%
                                //   odds per 10k-sentence book that two
                                //   DIFFERENT sentences collide (wrong
                                //   audio file, wrong study list).
      "occ":  0,                 // occurrence counter; omitted when 0.
                                //   Repeated IDENTICAL sentences share
                                //   id BY DESIGN (and share audio —
                                //   same words, same file); occ makes
                                //   (id,occ) unique for progress keys.

      "p":    1,                 // sentence starts a new paragraph
                                //   (from the source's blank-line
                                //   breaks); omitted otherwise.
                                //   Consumer: daily mode "one paragraph
                                //   per day" quota; display grouping.

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
                                //   INCLUDES strength-0 entries: forced
                                //   ("desperation") cuts the level
                                //   derivation had to place where the
                                //   target length is below the break
                                //   density (starter mostly: ~17-30% of
                                //   sentences; ~0 above beginner). s=0
                                //   marks them as forced, not
                                //   linguistically motivated; a client
                                //   dial treats them as last-resort
                                //   positions. (It cannot re-derive
                                //   them — that needs the dep parse —
                                //   which is why they are baked here.)

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
                                //   Every rung ⊆ cuts.advanced; since
                                //   levels nest, the ladder is therefore
                                //   valid starting from ANY level.

      "orth": {},                // token index → modernised form, only
                                //   where it differs (e.g. {"3":"Tür"}).
                                //   Omitted when nothing differs. Check-
                                //   mode + gloss lookup use the modern
                                //   form; display is a user toggle.

      "d": null,                 // RESERVED (script): per-sentence
                                //   difficulty score. Consumer: v4 daily
                                //   ease-in. Omitted until computed.

      "rebus": null,             // RESERVED (AI, absent now): 2–4 emoji
                                //   sentence summary for hide-text recall.

      "para": null               // RESERVED (AI, absent now): simplified-
                                //   German paraphrase. Consumer: same-
                                //   language comprehension hint.
    }

Section objects likewise reserve `"sum"` (AI, absent now): one-line
section summary; consumer: "previously on…" recap in daily mode.

Notes:

- **Chunk emoji is not stored on the sentence.** Per `00_overview`,
  emoji live on lemmas (in the gloss file) so the same word → same
  emoji everywhere; a chunk's emoji is computed at runtime as the emoji
  of its rarest word(s). This keeps emoji independent of which level's
  cuts are active. The optional sentence-level `rebus` is the one emoji
  field that lives here. Pick rule + intent: candidates are the chunk's
  glossed non-entity words (all already rare by the gloss threshold);
  take the lowest-zipf one(s) via the gloss `freq` map — rarity is the
  measurable proxy for "the word the learner most likely does not
  know", which is the emoji's job. v4 refinement (client policy, no
  data change): subtract the learner's known-word set first, then take
  the rarest. This makes `freq` runtime-REQUIRED, not reserved.
  Two rules that make the pick well-defined:
  - **Rarest word WITH a non-empty emoji.** Since empty-`e` is allowed
    and preferred over a bad emoji, the rarest word often has none —
    fall through to the next rarest with `e` set; show nothing if no
    candidate has one. Otherwise the empty-allowed policy would kill
    chunk emoji exactly on the hardest chunks.
  - **zipf-0 tie-break.** wordfreq returns 0 for OOV words, and rare
    German compounds are mostly OOV, so they tie as "maximally rare"
    (correct for the intent — compounds ARE the hard words). Break the
    tie deterministically by word order within the chunk. Deduplicate
    repeated lemmas before picking.
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
      "source_hash": "sha256:...",        // same book-text hash as the
                                          //   book file (regen check)
      "dict_version": "freedict-deu-eng-1.9",
                                          // vendored dictionary snapshot —
                                          //   changes output like
                                          //   parse_model does
      "words": {                          // key = normalised lemma.
                                          //   Named entities simply
                                          //   OMITTED (the book file's
                                          //   `ents` is the single
                                          //   source of truth; no null
                                          //   placeholders)
        "aufmachen": {"l":"aufmachen","g_en":"to open","e":""}
      },
      "forms": {                          // runtime-critical: surface→lemma
        "aufmacht":"aufmachen","öffnet":"öffnen","thür":"tür"
      },
      "freq": {"aufmachen":3.8},          // REQUIRED (script): lemma zipf.
                                          //   Runtime consumer NOW: the
                                          //   chunk-emoji rarest-word pick.
                                          //   Also v4 "you know X% of
                                          //   this book"
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
      "generator": "build3.py@0000000",   // provenance rule applies here too
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

Per-book `stats` (counts per level, avg length, vocab profile,
difficulty) also live in each book file's `stats` header; `books.json`
carries the aggregate the library screen and daily-mode arithmetic need
without opening every book. Per-SECTION counts (promised in
`00_v3_overview`) are NOT stored: the client has the whole book file
loaded and counts sentences/cuts per section trivially at load —
derivable, not baked.

## Invariants the builder must check

1. **Reconstruction**: for each sentence, `join(toks, sp)` equals the
   NORMALISED source sentence (NFC, whitespace-collapsed — same
   normalisation the id hashes; `sp` cannot encode in-sentence
   newlines and must not have to).
2. **Nesting**: `cuts[coarser] ⊆ cuts[finer]` for every level pair; each
   rung's cut-set ⊆ the next finer rung's; every rung ⊆ `cuts.advanced`.
3. **Legal cuts**: every index in `cuts` / `rungs` appears in `breaks`
   (or is a sentence boundary). Desperation cuts satisfy this because
   the builder records them in `breaks` with strength 0.
4. **ID uniqueness**: `(id, occ)` unique within a book, AND two
   sentences with DIFFERENT normalised text never share an `id`
   (true hash collision → build fails loudly; at 48 bits this is
   ~2e-7 per 10k-sentence book, but sure is sure).
5. **No punct-only chunk**: every chunk slice contains ≥1 alnum token.

## What is NOT in this schema yet (by design, this session)

- `g_de`, sense overrides, AI emoji map, `rebus`, `para` (paraphrase),
  `sum` (section summary) — the external-AI passes.
- `audio/<book>/*.opus` + `audio/<book>/manifest.json` (incl.
  per-sentence durations) — the Piper pass.

Both are additive: they fill reserved keys or add sibling files, never
reshape what is above. Provenance stamps + stable `(id,occ)` make the
one-time regeneration safe for user progress.
