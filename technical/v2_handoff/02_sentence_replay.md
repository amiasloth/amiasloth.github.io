# Phase 02 — whole-sentence replay

Goal: after the user finishes the last chunk of a sentence, insert an
optional integration step — the complete sentence as one extra "virtual
chunk" to read/record. Toggleable, default OFF.

All work in `docs/v2/` only. Read `00_overview.md` first.

## Background / data model

Book JSON chunks look like `{"t": "...", "cont": 1, "e": "🐘"}`.
`cont: 1` means "this chunk continues into the next one". A SENTENCE is a
maximal run of consecutive chunks ending at the first chunk WITHOUT
`cont`. `reader.js` flattens chunks into `flat[]` preserving `cont`.

Decision already made with the owner (do not redesign):
- Two-state toggle only: **off / sentence**. No intermediate merged rungs
  (no "halves", no pairs) — mechanical merges can cross semantic
  boundaries and confuse learners. Sentence is the only safe merge unit.
- The sentence step may SHOW its text even when the "hide text while you
  speak" pref is on — controlled by a separate sub-setting (see below).
- Emoji trail: the sentence step shows the concatenated emoji hints of its
  chunks, in order.

## Implementation (docs/v2/js/reader.js)

1. **Prefs.** Add to the `prefs` object + settings sheet
   (`buildSettingsSheet`):
   - `sentenceReplay` (bool, default false) — "Read the whole sentence" /
     "After the last piece of a sentence, read the complete sentence once."
   - `sentenceShowText` (bool, default true) — "Show text for full
     sentences" / "Even when chunk text is hidden, the complete-sentence
     step stays visible." Render this sub-option only when
     `sentenceReplay` is on (rebuild the sheet on toggle, as the existing
     code already does).

2. **Sentence detection at load.** After building `flat[]` in
   `loadLevel()`, compute for each index its sentence span: walk `flat`,
   group runs of `cont` chunks + the terminating non-`cont` chunk. Store
   on each flat item: `sentStart`, `sentEnd` (indices). Skip in review
   mode (starred deck has no reliable `cont` context — the feature is
   disabled there).

3. **Virtual sentence step.** Do NOT splice merged items into `flat[]`
   (that would corrupt progress indices, stars keyed by `i`, and the
   progress bar). Instead give the reader a small mode flag, e.g.
   `sentenceStep = null | {start, end, t, e}`:
   - In `go(+1)`: if `sentenceReplay` is on, we are leaving index `idx`,
     `idx === flat[idx].sentEnd`, and the sentence has ≥2 chunks
     (`sentEnd > sentStart`), then instead of advancing, set
     `sentenceStep = {start, end, t: joined text, e: joined emojis}` and
     render it. Joining text: `chunks.map(c => c.t).join(" ")` then
     collapse multiple spaces.
   - While `sentenceStep` is active: `render()` shows the sentence as the
     "now" chunk (context rows show the individual chunks dimmed, or
     blanks — simplest: blanks). Show the emoji trail where the single
     emoji normally goes. The star button applies to the LAST chunk of
     the sentence (or hide it during the step — hiding is simpler and
     fine).
   - Record / TTS / A-B all operate on `sentenceStep.t` — route through
     the existing "current text" accessor: refactor `flat[idx].t` reads
     into a helper `curText()` / `curEmoji()` that returns the sentence
     values when the step is active. Keep the refactor minimal.
   - **Playback order — own take, then TTS.** For a normal chunk,
     `ttsFirst` (if on) speaks TTS *before* recording (shadowing), and
     `onPlayEnd` runs the `after` pref (repeat/next/stop) right after the
     user's take plays back. The sentence step inverts this deliberately —
     the goal here is recall + self-correction, not shadowing:
     - `ttsFirst` is ignored for the sentence step; always start the take
       directly (`rec.record()`), never TTS-before-record here.
     - When the user's take finishes playing back (`onPlayEnd` fires
       while `sentenceStep` is active), do NOT immediately run the
       `after` pref. Instead call `speakCurrent()` (TTS of the sentence
       text) once, and only run the normal `after` (repeat/next/stop)
       logic once that TTS playback resolves.
     - Net order for the sentence step: record → hear your own take →
       hear the correct TTS → then repeat/next/stop as configured. This
       lets the learner notice what they got wrong by comparing their
       own playback against the correct reading right after.
     - This override applies only while `sentenceStep` is active; regular
       chunks keep existing `ttsFirst` / `after` behavior unchanged.
   - Any navigation (next/prev/swipe) from the step clears it: next goes
     to `end + 1`, prev returns to `end` (the last chunk, normal mode).
   - `hideText` veil: apply the veil during the step only if
     `sentenceShowText` is false.
   - Progress save (`Store.setProgress`) is NOT called for the step (it
     is virtual); position stays at `end` until the user moves on.

4. **VAD cap.** `recorder.js` `VAD.maxTakeMs` is 30000 — long enough for
   any sentence in the data; no change needed.

5. **Hands-free flow.** The `after: "next"` / `onPlayEnd` path calls
   `go(1, {keepMic: true})`; the sentence step must trigger there too
   (i.e. the interception lives inside `go()`, not in the button handler,
   so all advance paths hit it).

## Acceptance criteria

- Toggle off (default): behavior identical to Phase 01. Verify by reading
  through a full section.
- Toggle on: finishing a multi-chunk sentence and tapping next shows the
  full sentence with emoji trail; record loop and TTS work on it; next
  again proceeds to the following sentence's first chunk; prev returns to
  the last chunk.
- Sentence step playback order: record the sentence, hear your own take
  play back, then hear the TTS reading immediately after (own take always
  first, TTS always second — `ttsFirst` has no effect here); only then
  does the `after` pref (repeat/next/stop) take over.
- Single-chunk sentences produce NO extra step.
- With `hideText` on and `sentenceShowText` on: chunk text hides on
  speech, sentence text stays visible.
- With both hiding: sentence text veils on speech too.
- Stars, progress bar, saved position, level switching, review mode: all
  unaffected (compare against toggle-off behavior).
- Works on iPhone Safari (record + TTS on the sentence step).
- Regression check from `00_overview.md` passes.

Commit: `v2: phase 02 whole-sentence replay (off/sentence toggle, emoji trail)`
