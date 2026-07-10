# v3 — pre-processing overhaul (discussion outcome, 2026-07)

Status: DISCUSSION RESULT, not an implementation handoff. Settled items
are marked SETTLED; the chunking strategy is OPEN pending an experiment.
No code has been written. `06_glossary_pipeline.md` (carried over from
v2) is the base spec for the glossary and is amended by this document.

App goal check: every feature below exists to help people learn a
language by reading. Anything that doesn't serve that is out.

## Isolation (same rules as v2)

- v3 is a separate app under `docs/v3/`. v1 and v2 stay byte-identical.
- v3 gets its own data dir `docs/data3/` + `docs/data3/books.json`.
  `docs/data/**` stays frozen forever for v1/v2. (~16 MB duplication,
  irrelevant.) Regeneration is required anyway by sentence IDs, POS
  tags, and NER — independent of the chunking outcome.
- localStorage key `zzzpeak.v3`; never write v1/v2 keys.

## Design principles (SETTLED)

1. **Facts vs policy.** Data files carry facts about the text (tokens,
   IDs, lemmas, glosses, senses, orthography, audio, stats). The client
   carries pedagogy (session shapes, SRS, streaks, level presets). If
   the line holds, v4+ features are JS-only — books are never
   reprocessed again.
2. **AI is optional, never load-bearing.** AI never runs inside the
   build pipeline. It produces either
   (a) optional fields the UI hides when absent (`g_de`, sense
       overrides, paraphrases, rebus emoji), or
   (b) reviewable artifacts committed to the repo (lemma→emoji map,
       break-hierarchy refinements, orthography substitution list),
       which the deterministic pipeline then consumes.
   Consequence: rebuilding a book never calls an API. Without AI,
   everything still works via script fallbacks — worse quality, never
   broken. AI is only ever invoked when adding/upgrading a book, and
   even then optionally.
3. **Stable IDs.** Every sentence gets a content-hash ID (+ occurrence
   counter for repeated sentences). Chunk position is ephemeral,
   keyed within the sentence. This is what keeps v4 progress, daily
   mode, starred decks, and export/import alive across any future data
   regeneration (graceful ID churn instead of total index corruption).
4. **Provenance.** Every generated file carries `schema` version,
   generator version, and source-text hash, so "does this need
   regenerating?" is always answerable at a glance.

## SETTLED features

### Core data representation: tokens are first-class
Each sentence stores its token list (as tokenized at build time), and
everything word-shaped references **token positions**, not substrings:
POS tags, NER marks, orthography substitutions, chunk/break boundaries,
and (later) audio word-timestamps are all per-token or between-token
facts. This is what lets one alignment pass serve any chunking, lets
tap-a-word work without a runtime tokenizer, and keeps every annotation
layer consistent with every other. The browser has no lemmatizer, so
the gloss pipeline's `forms` map (inflected surface form → lemma key,
covering every surface form occurring in the book — see 06 spec) is
runtime-critical and must be kept.

### Glossary + word list (amends 06 spec)
- Base pipeline as in `06_glossary_pipeline.md` (FreeDict/kaikki +
  simplemma + wordfreq, offline, deterministic), emitting into the v3
  data layout with sentence-ID linkage.
- `g_en`: offline dictionary gloss (deterministic fallback, always
  present when lookup hits).
- `g_de` (optional, AI): one-line *learner* definition in simple
  German (~A2 vocabulary), Mistral at build time, two-pass:
  generate → second cheap pass grades each definition → failures fall
  back to `g_en` only. Display language is a user setting.
  (Offline German-German dictionaries — kaikki de-Wiktionary — were
  considered and rejected as primary: definitions are written for
  natives, verbose, and circular; AI learner-definitions are the
  workable same-language route. Owner prefers same-language over
  de→en.)
- Usage example per gloss = the book's own sentence (free, correct
  sense by construction).
- **Sense overrides** (optional, AI): default gloss per lemma plus an
  exception list keyed by sentence ID where the occurrence uses a
  different sense (Schloss 🏰 vs 🔒, Gericht, Absatz, umziehen…).
  Absent → default gloss shown; still functional. v4's starred deck
  quizzes the sense actually used at the starred occurrence.
- Glossing **skips named entities** (see NER below) — names are not
  rare words.

### Emoji (two units, two jobs)
- **Word/chunk level — meaning** (primary use per owner experience):
  an AI-drafted per-book `lemma → emoji` map, committed to the repo,
  human-skimmable, applied deterministically. Same word → same emoji
  everywhere (emoji become a small learned symbol vocabulary). Chunk
  emoji = emoji of its rarest word(s), 1–3 emoji as one string
  (backward-compatible: still a string), ordered to follow the chunk's
  word order. Empty is allowed and preferred over a forced bad emoji.
  Gloss entries carry the same emoji ("Holzhacker 🪓") so word hint and
  chunk hint reinforce each other. No-AI fallback: current curated
  emoji_map.py + CLDR-annotation suggestions. Starter-level caution:
  with 1–3-word chunks, per-word emoji risk becoming a translation
  crutch — the empty-allowed rule matters most there.
- **Sentence level — recall** (optional field): free-form 2–4 emoji
  rebus summarizing the sentence, for hide-text practice with longer
  chunks. Generated in the same Mistral batch; UI may ignore it.

### Per-token POS tags (script-only)
Baked into the data at build time from the spaCy parse. Enables verb
coloring and any future grammar feature (highlight cases, find-the-
subject drills) with zero reprocessing. Small size cost, big option
value.

### Named entities (script-only, spaCy NER)
Marked in the data. Three consumers: gloss pipeline skips them; reader
renders them subtly distinct (learner knows it's a name — "Hradscheck"
is not vocabulary); check mode discounts them when scoring (STT will
never transcribe them right; the reader shouldn't lose points).

### Orthography: parallel modernized text
- Store the original text plus a modernized variant *where it
  differs* (Thür→Tür, daß→dass, Waaren→Waren, sey→sei…). Display is a
  user toggle — owner keeps reading the old orthography by choice.
- Build: dictionary-miss detection flags archaic tokens; AI (or hand)
  proposes modern forms; output is a flat per-book substitution list,
  reviewed once, committed; application is deterministic.
- Check mode always grades against the modernized form regardless of
  display (STT outputs modern spelling — fixes false mismatches).
  Gloss lookup also uses the modernized form.
- TTS benefit is modest (archaic German is still mostly phonetic);
  that is not the motivation.

### Book stats / difficulty (script-only)
Computed at build time into `books.json` and per-book files:
word/sentence/chunk counts per level, per-section counts, average
sentence length, vocabulary profile (share of lemmas below zipf 4.0),
derived difficulty label, per-sentence difficulty score. The counts
are exactly what v4's "N sentences/day → M days" needs.

### Audio (optional per book, script-only — no AI API)
- Piper (thorsten-medium, ~60 MB model; owner judged it clearly better
  than built-in TTS) on the MacBook Air; roughly real-time synthesis —
  an evening for Kafka, days unattended for the full German set.
- **One opus file per sentence, named by sentence ID.** All levels and
  any future chunking share the same files. ~250–370 MB for the full
  German set at 16–24 kbps mono; ~25 MB for Kafka alone.
- Playback: sentence replay uses the audio file when present; 404 (or
  manifest says absent) → Web Speech fallback. Partial coverage is
  fine by construction. `books.json` gets an `audio` field per book
  (voice, version, coverage) to avoid probing.
- Rollout: shortest books first (velveteen / kafka), judge on device,
  then decide scope. If repo size ever matters, audio can move to a
  second GitHub Pages repo without touching the app.
- **Chunk-level playback is deferred, not precluded**: a later forced-
  alignment pass (aeneas or faster-whisper word timestamps) over the
  *same* audio yields per-word times; any chunk boundary is a word
  position, so one alignment serves every level and any future cut.
  Slice playback via Web Audio with tiny fades. No audio regeneration
  ever needed for this.

### Small reader features (UI-only, no data impact beyond the above)
- Tap/long-press word → external dictionary (Wiktionary/dict.cc) in a
  new tab.
- Chapter/section jump (table of contents) — sections already exist in
  the data.

### Reserved fields (cheap now, named consumer in v4)
- Per-sentence simplified-German paraphrase (optional, AI; same batch
  as emoji). Consumer: same-language comprehension hint — owner
  prefers this over EN translation.
- Per-book lemma frequency table (script). Consumers: "you know X% of
  this book", cross-book "seen this word in Kafka".
- Per-section one-line summaries (optional, AI). Consumer: "previously
  on…" recap when daily mode resumes after a gap.
- Per-sentence audio duration (trivially recorded when audio is
  generated). Consumer: daily-session time estimate ("today ≈ 4 min").
- Rule: no field without a nameable consumer.

## OPEN — chunking strategy (experiment before deciding)

Owner verdict on current chunker: acceptable, hard-won, but
intermediate/advanced lengths fluctuate badly (2–6–2 words), some
sentences run very long, starter≈beginner and intermediate≈advanced
feel similar. Improvement is wanted but NOT at the risk of regression;
owner is **skeptical of the nested/gradual chunking until proven**.

Candidate designs, to be judged by experiment:

A. **Keep current chunker** (baseline). Optionally add the DP length
   rebalancer as a post-pass (merge runts / split oversized toward a
   target, cuts only at allowed boundaries — Knuth-Plass style). This
   alone may fix the 2–6–2 fluctuation. No nesting benefits.

B. **Break-point hierarchy, baked levels.** Compute per-sentence break
   points once with strengths derived from the dependency parse
   (clause > coordination > PP > modifier…), derive the levels as
   strength thresholds + length balancing at build time. Levels nest:
   moving up = merging familiar pieces. Enables adaptive progressive
   rungs (short sentence: chunk→sentence; long: chunk→halves→sentence,
   halved at the strongest break). Risk: nesting is a constraint that
   can force locally worse cuts than independently tuned levels.

C. **Hierarchy shipped to client + granularity dial.** Same data as B
   but the client cuts at runtime; named levels become presets on a
   continuous dial. Maximum flexibility; most JS work; requires a
   shared cutting spec (Python/JS duplication). Owner is skeptical —
   only on the table if B's data representation makes it nearly free.

Optional AI refinement (applies to B/C): LLM proposes break positions
only — never text — validator enforces exact reconstruction + length
bounds, any failure falls back to the script's hierarchy. Worst case =
script quality. Hierarchy variant: one hierarchical annotation per
sentence derives all levels consistently.

**Experiment status (2026-07-10): implemented, awaiting lg run.**
Candidate B + side-by-side comparison live in
`technical/v3_chunking_test/` (`README.md` there; run
`run_experiment.sh` on the build machine — needs `de_core_news_lg`).
Smoke run (sm model) verified the machinery (0 reconstruction
failures, levels nest by construction) and already shows the
parse-independent wins: intermediate/advanced length CV 0.27/0.24 vs
current 0.38/0.38, hard cap never exceeded beyond max+1, levels
actually reach their target lengths. Boundary-quality judgment (and
whether nesting visibly hurts) still requires the lg run — see
`RESULTS.md` there.

**Experiment plan (afternoon-sized, before any commitment):**
run candidate B (script-only) on a few Kafka sections; produce a
side-by-side diff against the current four chunkings; owner reads and
judges: (1) boundary quality vs current, (2) length variance at
intermediate/advanced, (3) long-sentence behavior under a hard cap,
(4) whether nesting visibly hurts any level. Decide A/B/C from
evidence. Whatever the outcome, sentence IDs, POS tags, NER, and all
other settled features above are unaffected — only the chunk
representation changes.

Progressive-rung note (owner feedback): all four levels as rungs is
too many. Rung count should adapt to sentence length (2 rungs for
short sentences, 3 for long). Contingent on B/C; under A, progressive
mode stays two-rung.

## Build environment notes

- Build machine: MacBook Air (Intel Ivy Bridge, 2c/4t, 7.7 GB, Debian
  13). Piper, spaCy, aeneas all run there; everything is unattended
  batch work.
- Mistral (subscription) for the optional AI passes; the entire German
  corpus is ~500 k tokens — minutes against the rate limits
  (mistral-small-2506: 10 M TPM / 41 RPS; medium: 1 M TPM). Model
  choice per task is a quality decision, not a cost one. Google AI
  Studio free tier exists as backup; Google/Mistral TTS APIs were
  evaluated and rejected (rate limits / no German).
