# Phase 07 — gloss/emoji flow rework (from-scratch redesign)

Owner decisions 2026-07-12, after real reading use and the
`tools/ai/experiment_unified.py` pilot on grimm + alice
(`tools/ai/build/experiment_{grimm,alice}.md` — read those first;
they justify every reversal below). Supersedes: 06's rare-words-only
bubble scope, 00 §5's three separate AI passes (gfill/gde/emoji), and
the "empty beats bad" emoji doctrine.

## Decisions (each reverses an earlier assumption)

1. **Approximate beats empty.** Only a MISLEADING emoji (points at a
   different sense) is worse than none. Rubric lives in
   `tools/ai/prompts/unified_gen_v1.txt`.
2. **Chunk emoji: length-scaled row.** `ceil(chunk_words/5)`, cap 3,
   rarest lemmas win the picks, displayed in WORD ORDER above the
   chunk (reads as a rebus — the reserved sentence `rebus` field is
   dead, remove the reservation note). Short/starter chunks naturally
   show one easy word's emoji; long/advanced chunks show more, harder
   ones.
3. **Bubble scope: ALL content words** (UPOS NOUN/VERB/ADJ/ADV; never
   function words, never ents). ~2.5k entries/book, gloss JSON
   roughly doubles — accepted.
4. **Bubble is same-language ONLY.** de books display `g_de`, en
   books `g_en`. `g_en` for de books stays in the data (cheap,
   stable contract) but is never rendered.
5. **Same treatment for en and de.** Both get emoji, bubbles, and the
   AI pass; only the archaic-orth machinery stays German-only.
6. **AI-first, dictionary never feeds the AI.** FreeDict poisoned
   emoji3 (grimm holzhacker "dirty player" → ⛹ shipped). The pilot
   shows lemma + first-occurrence sentence alone beats the dictionary
   (holzhacker, klafter; WordNet's "musteline mammal" vs the AI's
   learner line). Dictionaries are demoted to the no-API tier.
7. **No grade stage.** Pilot: grader rejected 7/100, ~4 real catches,
   missed the worst error (eren = dialect "hallway", model said
   "ihren"). Not worth 2x requests — deterministic sanity checks +
   spot-check review instead.
8. **Auto-bake + forced spot-check.** No hand review of 2.5k lemmas.
   ALL zipf-0 lemmas (dialect/garbled — where the model guesses:
   eren, doorna, teiten) + ~50 random land in a review report; the
   rest bakes straight in.
9. **Serial requests, rate limit baked in.** `mistral3._pace`: ≥2.2s
   between mistral-large requests (0.5 req/s tier; TPM is never the
   binder). No parallelism (owner choice — simplicity over the
   ~20 min/book cost).

## Data schema (rev 3.2 — additive/expansive, no reshape)

- `words` grows from rare-only to all content lemmas. Entry fields
  unchanged: `l`, `g_en`, `g_de` (de books), `e` (0–2 emoji).
- `freq` must cover EVERY `words` key (multi-pick needs it; today it
  covers rare lemmas only).
- `emoji_common` RETIRED: with full-coverage entries the common-word
  channel is subsumed. Reader keeps a tolerant `gloss.emoji_common`
  read for old files during transition, build stops emitting it.
- `study_by_sent` / `sections[].study` UNCHANGED — "study word"
  stays a rarity concept; bubble coverage is now independent of it.
- `forms` already book-complete; unchanged.

## Pipeline

New `tools/ai/unified3.py --book <id>` (replaces gfill3, gde3 and
emoji3 `--book`; emoji3 `--general` survives for the offline tier):

- Candidates: every content-POS, non-ent lemma in the book (via
  `forms`), first-occurrence sentence attached; INCLUDING current
  dictionary misses (subsumes gfill3).
- One generation stage, batches of 40, temperature 0.2 →
  `{lemma: {d, e}}`. de books: d→`g_de`; en books: d→`g_en`
  (overwrites the WordNet line — AI is strictly better for learners).
- Sanity v2 (fix pilot false-rejects): rejoin stripped ZWJ sequences
  (sippschaft 👨‍👩‍👧‍👦) instead of rejecting; allow multi-keycap
  runs (fourteenth 1️⃣4️⃣); keep headword-leak + length checks.
- Artifacts: `build/unified_<id>.json` (auto-loaded by gloss3 at
  rebuild, same mechanism as today's maps but NO review gate) +
  `build/unified_<id>_review.md` (zipf-0 + random sample, current
  vs AI side-by-side — owner skims, edits the json where wrong).
- Cache: committed JSONL per book as usual; reruns only ask new
  lemmas (re-chunking ≈ free).
- Cost: ~2.5k lemmas ÷ 40 ≈ 63 requests ≈ **20–25 min/book** serial,
  ~10k tokens/min — far inside 800k TPM.

Emoji precedence becomes: unified AI (`e`) > curated `emoji_map.py` >
reviewed general map > generated CLDR. Machine still never edits the
curated file.

## Offline tier (no MISTRAL_API_KEY) — same JSON contract

Per field, first hit wins; an API run OVERWRITES offline values,
never the reverse:

- `g_de`: vendored German Wiktionary (kaikki.org de-extract, ~1GB
  one-time download, new parser) — OWN LATER PHASE; until it exists,
  offline de bubbles fall back to `g_en` (marked as EN in the UI).
- `g_en`: FreeDict / WordNet as today.
- `e`: curated map > reviewed general > CLDR-generated, as today.

## Reader (docs/v3)

- `Data3.chunkEmoji` → `chunkEmojis(gloss, sent, a, b)`: collect
  distinct non-ent lemmas with non-empty `e`, sort by `freq` (OOV=0
  rarest), take `min(3, ceil(words/5))`, RE-SORT picks into token
  order, render as one row above the chunk. Dedupe repeated emoji.
- Bubble: entry now exists for common words — show `g_de` (de) /
  `g_en` (en) only; drop the lemma-only degraded path for content
  words; ents still gloss to "a name". No bilingual line.
- `test_data3.js`: extend the gate — multi-pick count/order cases,
  full-coverage lookup, tolerant emoji_common absence.

## Out of scope here

Wiktionary vendoring (own phase), sense overrides, section summaries,
audio. Old passes gfill3/gde3/emoji3-book stay in the tree until
unified3 has run on all 8 books, then get a removal commit.

## Acceptance

- unified3 --mock runs offline end-to-end; real run on one de + one
  en book in <30 min each, review report written.
- Rebuilt gloss JSON: every content lemma resolves to an entry with
  a same-language definition; validate3 green; size <600KB/book.
- Reader: chunk emoji rows scale with chunk length (1 on starter,
  up to 3 on advanced); tapping any content word gives a bubble in
  the book's language; no emoji_common regressions on old files.
- grimm holzhacker shows 🪵🪓 and a German definition. ⛹ is gone.
