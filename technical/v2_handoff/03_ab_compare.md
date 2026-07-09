# Phase 03 — A/B compare (hear the model, then your take)

Goal: optional playback sequence after a take — first TTS speaks the
phrase (the model), then the user's recording plays (the imitation).
Toggleable, default OFF. Also valuable for users who cannot see the text.

All work in `docs/v2/` only. Read `00_overview.md` first.

## Design

Today the loop is: record → auto-stop → playback(take) → (after-pref).
With A/B on it becomes: record → auto-stop → TTS(phrase) → playback(take)
→ (after-pref). The after-playback behavior (`repeat` / `next` / `stop`)
is unchanged and still keys off the END of the user's take playback.

## Implementation

1. **Pref** (`docs/v2/js/reader.js`): `abCompare` (bool, default false).
   Settings sheet entry under the "Listening (on-device voice)" heading —
   only render when `TTS.available()`; label e.g. "Compare with the
   voice" / "After each take: hear the phrase spoken, then your own
   recording, back to back."

2. **Hook point.** The transition take→playback lives in
   `docs/v2/js/recorder.js` (`stopAndPlay` → `finish` → `_play`). Do NOT
   put TTS knowledge inside recorder.js — keep the recorder generic. Add
   an optional async gate instead: a `beforePlay` callback option (like
   `onPlayEnd`). In `finish()`, if `this.beforePlay` is set, await
   `beforePlay()` (a Promise) before calling `this._play()`. Guard: if
   state changed away (user reset/halted) while the gate ran, skip play.

3. **Wire-up in reader.js:** when constructing `LoopRecorder`, pass
   `beforePlay: () => (prefs.abCompare && TTS.available())
     ? TTS.speak(curText(), meta.lang, prefs.ttsRate) : Promise.resolve()`.
   Notes:
   - `TTS.speak` already resolves on end/error/cancel (see tts.js), so a
     failed TTS never blocks playback.
   - Use the same `curText()` helper from Phase 02 if present so A/B works
     on sentence steps too; otherwise `flat[idx].t`.
   - The status line during the TTS part: set "Listen…" then let the
     existing playing-state status take over.

4. **iOS audio-session caution:** TTS while the mic stream is open already
   happens in the app (`ttsFirst` shadowing pref does TTS → record), so
   this sequence (record stopped → TTS → audio element play) introduces no
   new session pattern. The audio element is already unlocked by the tap
   that started the take. No new unlock needed.

## Acceptance criteria

- Toggle off: behavior identical to before (record → own playback).
- Toggle on: after auto-stop, the phrase is spoken by TTS, then the take
  plays, then the after-pref runs (verify all three: repeat / next /
  stop).
- Toggle on + `ttsFirst` on: TTS → record → TTS → playback works and does
  not double-trigger.
- Interrupting during the TTS part (tap record / next / prev) cancels
  cleanly, no orphaned playback.
- Works with Phase 02 sentence steps if that phase is merged.
- iPhone Safari on-device test of the full loop.
- Regression check from `00_overview.md` passes.

Commit: `v2: phase 03 A/B compare toggle`
