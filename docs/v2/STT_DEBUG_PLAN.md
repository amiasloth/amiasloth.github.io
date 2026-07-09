# STT Debug Plan — evidence before code

Rule: **no behavior change until a device trace says why.** Every step below is either
read-only, additive instrumentation, or serving an old commit.

---

## Step 0 — Bisect the regressions before deciding anything (30 min, zero code)

Serve `05b9a4d`'s parent state to the iPhone and run the fixed test script (below).
This one experiment decides the revert-vs-forward question with data instead of taste.

```sh
git worktree add /tmp/zz-old 05b9a4d~1   # bb5282e-era state, pre both fix commits
# point serve.sh / Caddy at /tmp/zz-old/docs and test on the phone
```

Test on the phone, same phone, same book, in this exact order — twice, once at old, once at HEAD:

| # | Test | Record |
|---|------|--------|
| T1 | Fresh load, check OFF, loop take, speak, pause 2s | does it auto-stop? |
| T2 | Same load: 5 check takes (check ON), then check OFF, loop take | does auto-stop still work? |
| T3 | Check ON, tap ✓, speak correctly | does your take replay? |
| T4 | Check ON, tap ✓, speak wrongly | replay? diff shown? |
| T5 | Check ON, after=next, pass a phrase, stay silent | does it re-arm / advance? |

Outcomes:

- **T1/T2 broken at old commit too** → loop regression is NOT from these commits
  (environmental / iOS-state). Reverting buys nothing; go forward with Step 1.
- **T3 works at old commit** → "concurrent replay worked before" is confirmed and the
  culprit is inside the two-commit diff (start-order / degrade logic). A revert+reapply
  plan (Step 4) becomes viable.
- **T3 broken at old commit too** → the memory of it working is from the probe pages,
  not the checker; forward-only, Step 1.

---

## Step 1 — Instrumentation (additive only, behind `?debug=1`)

A ring-buffer event trace rendered in a fixed overlay with a "copy" button
(pattern already exists in `probe_continuous.html` — reuse its log UI).
No control-flow change anywhere; only event listeners and log lines.

What to log, with `performance.now()` timestamps:

**Checker / SpeechRecognition**
- `start()` entry: which of the 3 branches taken (sync stream / recognition-only / ensureStream), `playbackEnabled`, `_ccFails`, `_degraded`, stream active?
- rec events: `audiostart`, `speechstart`, `result` (final? alt count), `error` (**the exact `e.error` string**), `end`
- `rec.start()` throw (currently swallowed → `_onError("generic")` hides the real exception)
- whether `_startRecognition` ran inside a user gesture (`navigator.userActivation.isActive` — supported in iOS 16.4+; log it at every start)

**MediaRecorder (checker)**
- constructor mime chosen, `start()` ok/throw
- every `dataavailable`: `e.data.size`
- `onstop`: chunk count, **blob size** (`0` vs `null` vs real — distinguishes "recorder never ran" from "recorder ran but iOS gave it silence/empty")
- MediaRecorder `onerror`

**getUserMedia / tracks**
- each acquire: resolve/reject with `err.name`
- on the persistent stream's track: `mute`, `unmute`, `ended` events + `readyState`/`muted` sampled at recognition start/stop (**H3 below — iOS muting the track while dictation runs would produce a silent-but-nonzero blob**)

**AudioContext (both engines)**
- every `new AudioContext()`: success/throw, `ctx.state`; every `close()` resolve/reject
- a running counter of created-vs-closed contexts (**H5**)

**Playback**
- `playTake`: url present?, `audio.play()` resolved or rejected with error name
  (currently a rejection is swallowed → `resolve(false)` → *silent* no-replay; the log will make this visible)

**Loop VAD**
- once per second while recording: `peak`, `_noise`, `thresh`, `tk.speech`
- meter start success/failure (the `catch (e)` in `_startMeter` currently eats everything)

**Reader**
- `startCheckTake(auto)`, `rearmOnSilence` (and why it returned false), `checkNext(passed)`, `go()`, every `status()` string

---

## Step 2 — Hypotheses the trace must confirm or kill

Ordered by how well they fit the reported symptoms. Each has a specific trace signature.

**H1 — recognition start outside gesture fails on iOS.**
HEAD's *first* take: `_ensureStream → recorder → 120ms setTimeout → rec.start()` — that
start is outside the tap. Signature: `error: not-allowed` with stream active, and
`userActivation.isActive === false` at start. (Round-2's theory, never verified.)

**H2 — MediaRecorder gets an empty blob while recognition runs (concurrency is a mirage).**
iOS dictation may own the audio session; MediaRecorder runs but captures nothing.
Signature: `dataavailable size 0` / `blob size 0` → `done(null)` → no `takeUrl` →
`onCheckResult` skips `playTake` **with no error anywhere** — exactly matches "no replay,
silently". Note: `_ccFails` never increments on this path (no error event), so it never
degrades and never recovers either.

**H3 — iOS mutes the getUserMedia track during recognition.**
Variant of H2: blob is nonzero but silent. Signature: `track.mute` event at recognition
start, `unmute` after end. Replay would "play" but be inaudible — user reports "no replay".

**H4 — `playTake`'s `audio.play()` rejected (unlock lost).**
Hands-free takes call `_unlock()` without a gesture; if the original unlock's silent-clip
play was itself rejected, `_unlocked` stays `true` (checker's `_unlock`, unlike the
recorder's, never resets on failure) but the element is *not* actually unlocked.
Signature: `play() rejected: NotAllowedError` in the trace.

**H5 — AudioContext exhaustion explains the loop regression.** ← the "unexplained" one
`checker._startMeter` creates a **new AudioContext per take** and closes it per take;
iOS Safari caps concurrent AudioContexts (~4) and `close()` there is flaky under load.
After several check takes, `new AudioContext()` can start throwing. Then in loop mode
`LoopRecorder._startMeter`'s `try { new Ctx() } catch {}` silently fails → **no analyser
→ no VAD → recording never auto-stops**, with `recorder.js` untouched — precisely the
symptom. Signature: created-minus-closed counter climbing, then a `new AudioContext`
throw. Desktop unaffected (no cap) — also matches.

**H6 — restart-after-abort race breaks the silence re-arm on iOS.**
`no-speech` → `_endTakeIdle` (abort + detach) → reader immediately calls
`checker.start()` → new `rec.start()` while iOS is still tearing the old session down.
Signature: `not-allowed` or `rec.start() threw` within ~0–100 ms of the previous abort.

**H7 — the regression is not in the code at all.**
Step 0's T1/T2-at-old-commit answers this directly.

Cheap targeted probes if the main trace is ambiguous:
- extend `probe_continuous.html` with a *concurrent MediaRecorder* variant (recognition +
  recorder on one stream, log blob sizes) — isolates H2/H3 in 20 lines, outside the app.
- a probe that loops `new AudioContext()` create/close 20× then checks VAD — isolates H5.

---## Step 3 — Decision tree after one device session

| Trace shows | Fix direction (later, separate commit each) |
|---|---|
| H1 confirmed | keep sync-start when stream already open (works from take 2 on); first take: accept recognition-only OR start recognition sync-in-tap and prime the stream between takes (that's what the stale comment in `_finalize` already claims the code does — code and comment currently disagree) |
| H2 confirmed | concurrency is impossible on iOS → make it *explicitly* unsupported there: recognition-only takes, no replay UI, honest capability flag. Stop chasing it. |
| H3 confirmed | same as H2 (can't record what iOS mutes) |
| H4 confirmed | surface the rejection: status "tap to hear your take" + make checker's `_unlock` reset on failure like the recorder's does |
| H5 confirmed | one shared AudioContext per Checker instance (create once, suspend/resume between takes) — mirrors LoopRecorder's per-session context |
| H6 confirmed | delay re-arm ~250 ms after `end` (not after `error`), gate on `onend` having fired |
| H7 confirmed | document the iOS-state trigger, stop treating it as a regression |

## Step 4 — Revert path (only if Step 0 says the diff broke T2/T3)

`git revert 08900e7 d84cb84`, then re-apply as **three separate, individually
device-tested commits** the desktop fixes that were actually verified:

1. silence re-arm (`checkSilent` + `rearmOnSilence` + no-speech routing) — reader only
2. replay-on-miss (unified `playTake → speakModel → checkNext` in `onCheckResult`) — reader only
3. diff persists until next speech (`clearCheckDiff` in `onSpeechStart`, removed from `startCheckTake`) — reader only

Explicitly also worth keeping from round 3 (they fix real bugs): config-driven TTS in
`startCheckTake` (double-TTS fix), `checker.endTake()` in `speakCurrent`, counter reset in
`checker.reset()`. Explicitly dropped: all checker.js start-order changes until H1/H2 data exists.

---

## Order of execution

1. Step 0 bisect tests (no code)
2. Step 1 overlay (additive commit, `?debug=1`, cannot affect normal runs)
3. One iPhone session running the T1–T5 script with the overlay → copy traces out
4. Read traces against H1–H7 → pick the row in Step 3 (or Step 4)
5. One fix per commit, each re-verified on the device before the next

## Bugs found while reading (file for later; do NOT fix now)

- `_finalize`'s "first take starts recognition-only" comment describes code that no longer exists — the stale comment is itself evidence of round-2/3 churn.
- `playTake` swallows autoplay rejection (`resolve(false)`, no user feedback).
- Checker `_unlock` never resets `_unlocked` on failure (LoopRecorder's does).
- H2's failure mode (empty blob) leaves `_ccFails` untouched — "3 fails → give up" logic can never trigger on the most likely iOS failure.
- `rec.start()` exceptions are reported as generic `_onError` with the real exception discarded.
