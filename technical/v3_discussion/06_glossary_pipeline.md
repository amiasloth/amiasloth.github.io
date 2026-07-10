# Phase 06 — bundled glossary + emoji-map tooling

Goal, two halves:
(A) Build tooling (`tools/`) that generates per-book glossary JSON —
    rare words with short target→English glosses — from open offline
    datasets. No external API at build OR run time. Internet is used
    exactly once, to download open data files into `tools/vendor/`.
(B) v2 reader UI: glossed words get a subtle underline; tapping the
    underlined word (single tap, never long-press) shows the gloss
    inline. Plus a per-section "pre-study" word list. Toggleable.

Also: improve/extend `tools/emoji_map.py` coverage using the same vendor
data. Existing `docs/data/**` book JSONs are FROZEN — the emoji-map
improvements only apply to FUTURE regenerations, which are out of scope
here (do not run build_data.sh against existing books in this phase).

Read `00_overview.md` first. This phase touches `tools/` and adds NEW
files under `docs/data/` and `docs/v2/` only.

## (A) Build tooling

### Vendored data (downloaded once, committed or .gitignored+documented)

Put downloads under `tools/vendor/` with a `tools/vendor/README.md` that
records exact URLs, dates, and licenses. Sources (all open, no API keys):

1. **FreeDict deu-eng** dictionary (TEI or dictd format) — primary gloss
   source for German. https://freedict.org/downloads/ . For English books
   glosses can come from Wiktionary data instead (below) or be skipped in
   v1 of the pipeline (German first; the owner's main use).
2. **kaikki.org Wiktionary extract** (wiktextract JSON, per-language
   download) — richer fallback/alternative to FreeDict; large (hundreds
   of MB) so prefer .gitignore + README instructions over committing.
   Choose ONE of FreeDict/kaikki as primary after inspecting coverage on
   a sample book; document the choice.
3. **Unicode CLDR annotations** (en + de) — keyword→emoji, for
   emoji_map.py enrichment. https://github.com/unicode-org/cldr-json
   (annotations subset only).

### Python deps (add to tools/requirements.txt)

- `simplemma` — offline lemmatization (de, en). Handles "ging"→"gehen".
- `wordfreq` — offline frequency ranking, de + en.
(spaCy is already a dependency for chunk.py; simplemma is still preferred
here for lookup lemmas because it is dictionary-oriented, but using the
existing spaCy pipeline instead is an acceptable implementer choice —
document it.)

### New script: tools/gloss.py

CLI: `python gloss.py <book_json_path> [--out docs/data/gloss/] [--freq-threshold 3.5]`

Pipeline per book JSON (read from `docs/data/<lang>/<book>_<level>.json`):
1. Collect all chunk texts; tokenize into words (reuse chunk.py's
   tokenizer conventions if practical).
2. Lemmatize each token (simplemma, lang from the book JSON).
3. Rank by `wordfreq.zipf_frequency(lemma, lang)`; keep lemmas below the
   threshold (rare = worth glossing). Threshold default ~3.5 zipf,
   tunable per level (starter books may want a higher threshold).
4. Look up gloss in the vendored dictionary by lemma; normalize archaic
   spellings before lookup (ß/ss and th→t variants: try "Thür"→"Tür"
   style fallbacks — a small substitution list is fine). No hit → keep
   the word in a `misses` report, not in the output.
5. Emit `docs/data/gloss/<book>_<level>.json`:

```json
{
  "book": "grimm", "level": "beginner", "lang": "de",
  "words": { "holzhacker": {"g": "woodcutter", "l": "Holzhacker"} },
  "sections": [ {"title": "Marienkind", "study": ["holzhacker", "..."] } ]
}
```

   Keys are normalized lemmas (lowercase). `g` = short gloss (ONE line,
   truncate dictionary verbosity; first sense only). `l` = display lemma.
   `sections[].study` = the rare lemmas of that section in first-occurrence
   order (this is the pre-study list).
6. Print a summary: token count, glossed count, miss count; write misses
   to `tools/build/gloss_misses_<book>_<level>.txt` for manual review.

Deterministic (no AI, no network at runtime of the script beyond the
vendored files). Add a smoke test `tools/test_gloss.py` with a handful of
known words per language.

**Future hook (do not implement):** a later Mistral-powered step may
rewrite `g` values or fill misses. The JSON format above is the stable
contract; note this in a comment at the top of gloss.py.

### Emoji map enrichment: tools/emoji_map.py

Add a helper script `tools/emoji_suggest.py` that loads CLDR annotations
(de + en) and, given the lemma frequency list of a book, prints suggested
`lemma: emoji` entries NOT already covered by `_EN`/`_DE` maps, for human
review and manual merge into emoji_map.py. Suggestions only — never
auto-edit emoji_map.py, and never regenerate existing book data in this
phase.

## (B) v2 reader UI

1. **Pref**: `glossary` (bool, default false) — "Word hints" / "Rare words
   are underlined — tap one to see its meaning."
2. **Loading** (`docs/v2/js/reader.js`): on `loadLevel`, if the pref is
   on, fetch `../data/gloss/<book>_<level>.json`; 404 → silently disable
   for this book (no error UI). Cache in memory.
3. **Rendering**: in `chunkNode()` for the "now" chunk only, when glossary
   is active: split the chunk text into word tokens, lemma-lookup each
   against `words` (lowercase + the same ß/archaic normalization as the
   build side — keep a tiny shared normalizer; duplication of ~10 lines
   between Python and JS is acceptable, document both sides), and wrap
   hits in `<span class="gl">word</span>` with a dotted underline (CSS in
   `docs/v2/css/app.css`).
   IMPORTANT: runtime has no lemmatizer, so gloss.py must ALSO emit an
   `forms` map: inflected surface form → lemma key, for every surface form
   actually occurring in that book (build-time knows them all). Add
   `"forms": {"ging": "gehen"}` to the JSON schema above.
4. **Tap**: tapping a `.gl` span shows a small inline bubble (positioned
   above the word) with `l — g`; tapping elsewhere dismisses. Must NOT
   conflict with the swipe/tapzone navigation: stop propagation on the
   span tap. Never require long-press.
5. **Pre-study**: at a section boundary (first chunk of a section), show a
   small "study words" button/row that opens the existing sheet pattern
   listing `sections[].study` words with glosses. Keep it one screen,
   scrollable.
6. **Veil interaction**: underlines are part of the text; when `hideText`
   veils the chunk, glosses hide with it. Dismiss any open bubble on
   navigation, veil, or recording start.
7. **sw.js**: NO changes. Gloss files live under `/data/` so the existing
   stale-while-revalidate rule already covers them.

## Suggested commit split

1. `tools: vendor open dictionaries + CLDR annotations (docs in vendor/README)`
2. `tools: gloss.py offline glossary generator + tests`
3. `v2: phase 06 glossary UI (underline + tap gloss + pre-study list)`
4. `tools: emoji_suggest.py CLDR-based emoji suggestions` (optional, last)

## Acceptance criteria

- gloss.py runs offline (disconnect network after vendoring; it must
  still work) and produces valid JSON for at least one German and one
  English book; spot-check 10 glosses for sanity.
- Pref off (default): zero change in the reader, no gloss fetches.
- Pref on: rare words underlined in the current chunk; tap shows a
  correct gloss; tap-through does not navigate; swipe still navigates.
- Missing gloss file (a book you didn't generate): no errors, feature
  silently off for that book.
- Pre-study sheet shows the section's words.
- iPhone Safari: tap targets usable, bubble readable, no zoom weirdness.
- No modifications to existing `docs/data/**` book JSONs
  (`git diff --stat -- docs/data` shows only ADDED files under
  `docs/data/gloss/`).
- Regression check from `00_overview.md` passes.
