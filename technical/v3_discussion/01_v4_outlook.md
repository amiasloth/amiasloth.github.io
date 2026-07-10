# v4 outlook — what future features need from v3 data

Status: PLANNING NOTES ONLY. v4 is not being built now. Purpose: verify
that the v3 data schema (see `00_v3_overview.md`) already carries every
fact v4 will need, so books are never reprocessed again. The governing
rule: **if v3 data holds, every v4 feature is client-side JS only.**

## v4 feature list (owner's intent) → data requirements

### Daily mode
Set N sentences/day; show days remaining per book; multiple books
ongoing at once.
- Needs: per-book/level sentence & chunk counts, per-section counts,
  stable ordering, sentence IDs. → all in v3 stats + IDs. ✓
- Optional nicety: per-sentence difficulty scores (v3 reserved) let
  daily mode ease in or sort within a day. ✓
- Optional nicety: per-sentence audio durations (v3 reserved) give a
  session time estimate. ✓
- "Days remaining" = pure arithmetic in the client.

### Activity calendar / streaks (green marks)
- Pure localStorage. No data requirements. ✓

### Daily session shape
Words of today's sentences → phrases (if possible) → chunks → full
sentence (v2-style at the end).
- Words: derivable from the gloss `forms` map (surface form → lemma)
  per sentence. ✓
- Phrases as an intermediate step: this is exactly the nested-chunk /
  break-hierarchy representation, if the chunking experiment lands on
  B or C. Under outcome A (current chunker kept), "phrases" have no
  cross-level correspondence and this step degrades to chunks only.
  ← the main v4 stake in the chunking experiment.
- Chunks and sentence: core data. ✓
- Sentence audio in the session: optional per-book audio files by
  sentence ID, Web Speech fallback. ✓

### Starred deck + spaced repetition
- Cards addressable by lemma key into the gloss file. ✓
- The card teaches the sense actually used at the starred occurrence
  (sense-override list keyed by sentence ID). ✓
- Example sentence on the card = the book sentence (by ID). ✓
- Optional audio on the card = sentence audio file. ✓
- SRS scheduling itself: pure client policy, localStorage.

### Export / import progress
No accounts; localStorage is the single point of loss. "Copy progress
code / paste on new device."
- Needs: stable sentence IDs (content hash + occurrence counter) so a
  progress blob survives data regeneration with graceful degradation
  instead of corruption. ✓
- Export blob carries its own `schema` version; importer refuses or
  migrates on mismatch. Data files already carry schema + provenance
  stamps. ✓

### Level switching mid-book
- At sentence granularity: works with sentence IDs alone, under any
  chunking outcome. ✓
- Continuous/smooth (chunk correspondence across levels, mid-sentence
  switch, granularity dial): requires hierarchy (B/C). Open with the
  chunking experiment.

## Plausible v4+ features already covered by v3 fields

- **Listening / chunk-level audio playback**: one forced-alignment
  pass (word timestamps) over existing sentence audio; any chunk cut
  is a word position, so alignment survives level changes and even a
  future re-chunking. No audio regeneration. Deferred by design.
- **Grammar features** (color verbs, case highlighting, find-the-
  subject): per-token POS tags. ✓
- **"You know X% of this book" / book recommendations by known
  vocabulary**: per-book lemma frequency table + client-side known-
  lemma set. ✓
- **Cross-book vocabulary carryover** ("you met this word in Kafka"):
  lemma frequency tables across books; global index derivable
  client-side. ✓
- **Resume recap** ("previously on…" after days away): per-section
  one-line summaries (reserved, AI-generated once). ✓
- **Same-language comprehension hint** for a hard sentence: reserved
  per-sentence simplified-German paraphrase field. ✓
- **Check-mode fairness**: named-entity marks (don't penalize
  "Hradscheck"), modernized-orthography forms for STT comparison. ✓

## Explicitly NOT data concerns (client-only, no schema impact)

Session composition and ordering, SRS intervals and ease factors,
daily quotas, streak rules, level presets / dial policy, progressive-
rung selection, UI for calendars and trackers, notification/reminder
logic.

## Residual risks to schema stability

1. **Chunking experiment outcome** — the only open item that touches
   the data representation. Mitigation: sentence IDs, tokens, POS,
   NER, glosses, audio are all keyed to sentences/words, not chunks;
   every settled feature survives any A/B/C outcome.
2. A v4 feature nobody imagined that needs a new *text fact*. Rule of
   thumb applied in v3: fields were only reserved with a nameable
   consumer; anything truly new would mean one additive regeneration —
   provenance stamps make that safe, and stable IDs make it painless
   for user progress.
3. Audio coverage will be partial (owner will not generate all books).
   By design: per-book manifest + runtime fallback; no feature may
   hard-require audio.
