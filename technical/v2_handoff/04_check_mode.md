# Phase 04 — Check mode (speech-to-text transcript diff)

Goal: a separate practice mode ("Check mode") where the user speaks the
phrase and the app checks WHAT was said against the text — word-recall
feedback, not pronunciation grading. Wrong/missed words are revealed via a
transcript diff; up to 3 retries, then reveal and move on. Uses the Web
Speech API `SpeechRecognition` — free, no backend, no key. Playback of the
user's own voice is included where the platform allows recording and
recognition simultaneously, with graceful degradation where it does not.

All work in `docs/v2/` only. Read `00_overview.md` first.

## MILESTONE 0 — device probe (do this FIRST, commit separately)

iOS Safari's SpeechRecognition is the risk. Before building the feature,
build `docs/v2/probe.html`: a bare test page (not linked from anywhere)
that, on a tap:
1. Feature-detects `window.SpeechRecognition || window.webkitSpeechRecognition`.
2. Runs a recognition session alone (lang from a `?lang=de-DE` param,
   `interimResults = true`), printing every event (`result`, `error`,
   `end`, `nomatch`) with timestamps to the page.
3. Second button: opens `getUserMedia` + `MediaRecorder` FIRST, keeps them
   running, then starts recognition — prints whether both survive
   (recorder produces a playable blob AND recognition produces results).

The owner runs this on their iPhone and reports results. Outcomes:
- Both survive → implement Check mode WITH playback (design below).
- Recognition alone works, concurrency fails → implement with the
  `sttPlayback` capability flag off on that platform (diff-only feedback);
  the code below already supports this.
- Recognition unavailable/broken → Check mode hides itself on that
  platform; still worth shipping for desktop.
Record the observed iOS behavior in a short note appended to this file.

Known iOS prerequisites to document in the UI error message: Settings →
Siri & Search → dictation must be enabled; mic permission required; page
must be HTTPS (GitHub Pages is).

## Architecture

Check mode is deliberately SEPARATE from the LoopRecorder flow:
- New file `docs/v2/js/checker.js` — owns SpeechRecognition lifecycle and
  (if capable) a minimal concurrent MediaRecorder capture. Do NOT reuse or
  subclass LoopRecorder; write fresh, but follow the same iOS rules
  (user-gesture start, negotiated mime via the same `pickMime` approach,
  one unlocked audio element for playback).
- New file `docs/v2/js/match.js` — pure text functions, no DOM, unit-testable.
- Reader integration: a mode switch in the reader (e.g. a `✓` toolbar
  button or a settings entry "Check mode"), default off. When Check mode
  is active the record button starts a CHECK TAKE instead of a loop take;
  LoopRecorder must be fully `reset()` (stream released) before the first
  recognition start, and vice versa when leaving Check mode — the two
  systems never hold the mic at the same time.

## checker.js

States: `idle → listening → scoring → (pass | retry | reveal)`.

- Start (from user tap): if capability probe says concurrency works,
  start MediaRecorder first, then `recognition.start()`. Else recognition
  only.
- `recognition.lang`: map book lang → BCP tag (`de` → `de-DE`,
  `en` → `en-US`).
- `continuous = false`, `interimResults = true` (interim text can be shown
  live, greyed), `maxAlternatives = 3` (score against best-matching
  alternative).
- Collect final transcript on `result` events; a session ends on `end` or
  after a safety timeout (~12 s, mirror `VAD.noSpeechMs` spirit).
- On end: stop MediaRecorder (if running), score transcript (match.js),
  then callback with `{transcript, score, wordMarks, takeUrl|null}`.
- Errors: `not-allowed` → mic-permission message; `no-speech` → "Didn't
  hear anything"; `network`/`service-not-allowed` → "Speech recognition
  isn't available here" and set a session flag to hide Check mode UI.
  If recognition errors while the recorder is open, retry ONCE without
  the recorder (auto-degrade), and persist the degraded capability for
  the session.

## match.js (scoring)

Owner-agreed semantics: forgiving. This checks recall, not pronunciation.

1. Normalize both sides: lowercase; strip punctuation/quotes; collapse
   whitespace; `ß → ss`; NFC normalize. Keep umlauts.
2. Tokenize to words. Align hypothesis to reference with word-level
   dynamic programming (standard WER alignment).
3. A word pair "matches" if equal OR within edit distance 1 for words ≤5
   chars, distance 2 for longer words. (Handles archaic spellings:
   Thür/Tür, daß/dass, gieng/ging — dictation outputs modern forms.
   Perfection is explicitly NOT required.)
4. Score = matched reference words / total reference words.
   Pass threshold 0.75. Return per-reference-word marks
   (`match | miss`) for the diff display.
5. Numbers: dictation may emit digits ("3") for spoken words ("drei").
   Add a small equivalence table for 0–12 in de/en; beyond that, accept
   the miss.

Keep match.js pure so it can be tested in Node:
`node -e 'require assertions'` or a tiny `tools/test_match.html` — either
is fine; include at least a dozen cases (umlauts, ß, Thür/Tür, digits,
word order slip, total mismatch).

## Reader UX

- Check take flow: tap record → listening indicator (reuse the level ring)
  → recognition ends → diff renders in the chunk zone: reference text with
  matched words normal and missed words highlighted (e.g. red underline).
  If `hideText` is on, text stays hidden DURING listening (that is the
  point — recall), and the diff reveal shows it after.
- Pass (≥0.75): brief "✓" status; after-pref applies (repeat/next/stop).
  If playback is available, play the take back on pass (A/B pref applies
  too if Phase 03 is merged).
- Fail: status "Try again (2 left)" → next tap retries. After the 3rd
  fail: reveal full text + diff, status "Revealed — moving on", allow
  next. NEVER an infinite gate; next/prev always work regardless.
- Retry count resets on navigation.
- Feature-detect at init: no SpeechRecognition → the Check mode toggle is
  not rendered at all.

## Storage

Prefs under the v2 store: `checkMode` (bool, default false). Optionally
record per-chunk pass/fail counts later — NOT in this phase.

## Acceptance criteria

- Probe page committed first with iOS findings noted.
- Desktop Chrome: full flow — listen, diff, retry×3 cap, reveal, pass
  path, playback of take (Chrome supports concurrency).
- iPhone Safari: whichever tier the probe established works cleanly; if
  degraded, no broken playback button appears.
- Leaving Check mode returns to the classic loop; mic handoff both ways
  without permission re-prompts or dead recordings (test: loop take →
  enable check → check take → disable → loop take).
- German book with archaic spelling (grimm/kafka): Thür-style words pass
  when spoken correctly.
- match.js test cases pass.
- Check mode off: v2 behaves exactly as before this phase.
- Regression check from `00_overview.md` passes.

Commits: `v2: phase 04 milestone 0 — STT probe page` then
`v2: phase 04 check mode (STT transcript diff, retry cap 3)`

## Milestone 0 findings — iOS Safari (recorded 2026-07-09)

Ran `docs/v2/probe.html?lang=de-DE` on a physical iPhone (Safari, over
HTTPS, dictation enabled, built-in mic). Result:

- **Recognition alone:** works. `interimResults` stream fine; final
  transcript "Ist das funktioniert" at confidence 0.98.
- **Concurrency (recorder + recognition):** **BOTH SURVIVE.** MediaRecorder
  produced a playable `audio/mp4` blob (~96 KB) while SpeechRecognition
  produced a final result — zero errors. Event order observed: recorder
  `start` → recognition `start`/`audiostart` → `speechstart` → interim
  results → `result FINAL` (conf 0.98) → `speechend` → recognition `end`
  → recorder final `dataavailable` → blob.

**Decision: ship Check mode WITH take playback on iOS** (`sttPlayback`
capability ON). The auto-degrade path (retry recognition without the
recorder) is kept as a safety net but is not expected to fire on iOS or
desktop Chrome.

Caveat noted during testing: playback was unreliable **only** when routed
through a Bluetooth mic/headset (audio-session routing quirk, not a code
bug); on the built-in mic/speaker record + playback worked cleanly. Not a
blocker; worth a one-line UI hint if Bluetooth issues recur.

## Settings behaviour (Check mode follows the practice config)

Check mode honours the same settings as the loop:

- **Hide text while you speak** — the phrase stays readable until you
  actually start speaking (blurs on the recognizer's `speechstart`, like
  the loop's VAD), then the diff reveals it. It does NOT blur the instant
  listening begins.
- **Hear the phrase first** (`ttsFirst`) — TTS speaks the phrase, then the
  check take begins.
- **Compare with the voice** (`abCompare`) — on a pass, your take plays then
  the phrase is spoken; on a miss, the correct phrase is spoken so you hear
  the target.
- **After playback** drives the hands-free flow:
  - `stop` → fully manual (tap for every take, pass or miss).
  - `repeat` → pass: listen to the same phrase again; miss: auto-retry until
    the 3-try cap, then reveal and wait for a tap.
  - `next` → pass: advance and listen to the next phrase; miss: auto-retry,
    and after the 3rd miss reveal + advance to keep moving.
- **Record when you go to the next phrase** — a manual next tap auto-starts
  the next check take.

### iOS hands-free — persistent mic session

Earlier we assumed iOS gated every `recognition.start()` on a user gesture,
which would block hands-free. A follow-up probe (`docs/v2/probe_continuous.html`)
disproved that on the target iPhone: **both** a continuous session (mode A)
**and** a no-gesture recognition restart on an already-open mic session
(mode B) captured multiple phrases from a single tap.

So the checker keeps the getUserMedia **mic stream open across phrases**
(the same trick `recorder.js` uses for the loop) — opened once from the
first ✓ tap, released only on leaving Check mode or when the page is hidden.
Each phrase reuses the open stream with a fresh recorder + recognition; no
re-acquiring the mic, no per-phrase gesture. Result: the after-pref flow
(auto-retry on a miss, auto-advance-and-listen on a pass) runs fully
hands-free on iOS as well as desktop.

`checker.endTake()` ends a take but keeps the stream (used on navigation);
`checker.reset()` releases the stream (leaving Check mode / page hidden).
The "Tap ✓ to continue" path remains only as a genuine fallback if a start
ever fails (e.g. a real permission error), not as the expected iOS flow.
