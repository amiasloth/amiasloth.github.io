# Phase 03 — A/B compare (your take, then hear the model)

> **Implemented — order reversed from the original plan.** During build the
> sequence was deliberately flipped to play the user's take FIRST, then the
> TTS model, so the learner hears their own attempt and can immediately
> notice what they got wrong against the correct reading before moving on.
> This doc has been updated to describe what shipped. (History: commits
> "replay first then tts" / "flip order for chunks".)

Goal: optional playback sequence after a take — the user's recording plays
first (the imitation), then TTS speaks the phrase (the model).
Toggleable, default OFF. Also valuable for users who cannot see the text.

All work in `docs/v2/` only. Read `00_overview.md` first.

## Design

Today the loop is: record → auto-stop → playback(take) → (after-pref).
With A/B on it becomes: record → auto-stop → playback(take) → TTS(phrase)
→ (after-pref). The after-playback behavior (`repeat` / `next` / `stop`)
is unchanged and now keys off the END of the TTS model reading (the last
step of the sequence) rather than the take playback.

## Implementation

1. **Pref** (`docs/v2/js/reader.js`): `abCompare` (bool, default false).
   Settings sheet entry under the "Listening (on-device voice)" heading —
   only render when `TTS.available()`; label "Compare with the voice" /
   "After each take: hear your own recording, then the phrase spoken, back
   to back."

2. **Hook point.** Because the take now plays BEFORE the model, the extra
   TTS step happens AFTER the take playback ends, not before it. So this is
   wired through the existing `onPlayEnd` callback in `docs/v2/js/reader.js`
   rather than a pre-playback gate. When the take finishes playing,
   `onPlayEnd` speaks the model and only calls `runAfter()` once TTS
   resolves. recorder.js stays generic — no TTS knowledge in it.

   Note: recorder.js still carries an unused `beforePlay` async-gate option
   (the original TTS-first hook). It is currently dead code — harmless, and
   left in place as the seam for any future pre-playback gate. If you prefer
   a clean surface you may remove it, but it is not required.

3. **Wire-up in reader.js (`onPlayEnd`):** after the take playback ends, if
   `sentenceStep || prefs.abCompare`, snapshot the current step/idx, call
   `speakCurrent()` (which uses `curText()` at `prefs.ttsRate`), and on its
   resolution bail if the user navigated away, else call `runAfter()`.
   Notes:
   - `TTS.speak` already resolves on end/error/cancel (see tts.js), so a
     failed TTS never blocks the after-pref.
   - Uses the same `curText()` helper from Phase 02 so A/B works on sentence
     steps too. The sentence step always does compare-after regardless of
     the `abCompare` toggle; normal chunks only when `abCompare` is on.
   - The after-pref (`repeat`/`next`/`stop`) fires when the TTS model
     reading ends.

4. **iOS audio-session caution:** TTS while the mic stream is open already
   happens in the app (`ttsFirst` shadowing pref does TTS → record), so
   this sequence (record stopped → TTS → audio element play) introduces no
   new session pattern. The audio element is already unlocked by the tap
   that started the take. No new unlock needed.

## Acceptance criteria

- Toggle off (and not on a sentence step): behavior identical to before
  (record → own playback).
- Toggle on: after auto-stop, the take plays, then the phrase is spoken by
  TTS, then the after-pref runs (verify all three: repeat / next / stop).
- Toggle on + `ttsFirst` on: TTS → record → playback → TTS works and does
  not double-trigger.
- Interrupting during the TTS model part (tap record / next / prev) cancels
  cleanly, no orphaned playback or stray after-pref.
- Works with Phase 02 sentence steps if that phase is merged.
- iPhone Safari on-device test of the full loop.
- Regression check from `00_overview.md` passes.

Commit: `v2: phase 03 A/B compare toggle`
