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

## Device session 1 — 2026-07-09, iPhone, **at `05b9a4d` (pre-fix baseline)**, no overlay

**Step 0 is answered: the take-2 failure exists at the baseline, BEFORE both fix
commits. The revert path (Step 4) is dead for the iPhone symptoms — forward only.**

Results:

- **T1** (fresh, check off, loop): auto-stop works.
- **T2** (same load, check toggled on→off, no check takes, loop): auto-stop works.
- **T3** (fresh, check on, after=repeat): take 1 fully works — 100%, replay plays.
  Take 2 (auto-started): interims print correctly, but never finalizes; pause →
  "Listening… say the phrase" (re-arm); long silence → cap-out, check button returns,
  no playback. Once this happens, even a manual ✓ tap never restores scoring/playback.
- **T4** (fresh load, same config): first take doesn't pick up at all. **The wedge
  survives page reload** → OS-level dictation/audio-session state, not JS state.
- **T5**: abandoned; behavior inconsistent.

What this kills / confirms (baseline code, so version-independent conclusions only):

- **Revert is pointless** — take 2 breaks identically before the two commits.
- **"Concurrent replay worked before" = take 1 only.** Take 1 at baseline scores AND
  replays, so concurrent recorder+recognition CAN work on iPhone — H2/H3 not blanket-true.
- **H1 dead** — take 2 auto-started without a gesture and heard speech (interims printed).
- **Gesture-rescue dead** — a real ✓ tap doesn't fix a wedged session (rounds 2–3 assumption).
- **Loop regression not reproduced** (T1/T2) — but T2 had zero check takes, so H5
  (AudioContext churn) is untested, not killed. Retest: ≥6 check takes, THEN loop.

**H8 (front-runner): from take 2 on, iOS delivers interims but never `isFinal`.**
Take 1 (fresh stream, recognition 120 ms after recorder, inside the tap) finalizes;
take 2 (reused persistent stream, no gesture) doesn't. No final → no score → no
playback → apparent "no auto-stop".

**Open contradiction to settle:** at `05b9a4d` there is no silence re-arm — an empty
take prints "Tap ✓ to continue" and stops. The observed repeated "Listening… say the
phrase" at that commit can only come from `checkNext`'s miss-auto-retry, which requires
a FINAL that scored as a miss. So either (a) finals never come (H8) and the observed
loop was something else (e.g. one long never-ending session with the status text
misread), or (b) finals DO come but are garbled vs the correct-looking interims
(H8b: bad finals, not missing finals), or **(c) finals come and PASS, and the broken
piece is playback**: on a pass, baseline runs `playTake → speakModel → checkNext`; if
`audio.play()` rejects (H4 — unlock lost on gestureless takes) `playTake` resolves
`false` in milliseconds, so the "✓ N%" status is instantly overwritten by the next
take's "Listening… say the phrase". From the user's seat (c) is indistinguishable from
"never finalizes, no auto-stop, no playback" — but the take actually scored. (c) also
explains "tap ✓ doesn't fix it" without any service wedge: checker's `_unlock` never
retries after one failure (see Bugs list). Only the overlay separates (a)/(b)/(c): it
needs per-result `isFinal`, every `status()` string with timestamps (to catch the
flash), and `playTake`'s resolve/reject. The fixes differ completely — (a)/(b) touch
recognition handling, (c) is purely the audio-unlock/playback path.

**H9: system-level wedge.** T4's fresh-load failure means iOS's dictation service (or
Safari's audio session) stays broken across reloads. Test protocol must control for it:
force-quit Safari (or close the tab) between EVERY test run, and record whether Safari
was killed since the last run. Without this, runs aren't comparable — this alone
explains "inconsistent behavior".

Overlay additions now required (Step 1 amendments):

- log **every** `result` event with per-result `isFinal` flags and `resultIndex` — the
  single most valuable discriminator for H8
- log the last interim text seen, so we know what a fallback-to-interim would have scored
- log safety-timer (12 s) fires vs natural `onend` vs `onerror`, with ordering
- persist the trace in `sessionStorage` and re-render after reload — catches T4
- log a per-pageload id + `navigator.userActivation.isActive` at every recognition start

Candidate fixes IF H8 confirms (one commit each, device-tested, in this order):

1. **Fallback-to-interim**: keep the latest interim; on end with no finals, score it.
   Smallest change; converts the failure into a working take.
2. **Own the endpointing**: the meter/analyser already runs on the persistent stream —
   reuse loop-style VAD (~1 s trailing silence → `checker.stop()`) instead of trusting
   iOS to endpoint. Makes check takes behave exactly like loop takes.
3. **Discriminating experiment** (debug-flag only): release + re-acquire the stream per
   take on iOS — tests whether the *persistent* stream is what breaks finalization after
   take 1, i.e. whether the v1 trick and finals are mutually exclusive.

## Device sessions 2–3 — 2026-07-09, iPhone, Step 0 rerun + probe isolation

**Step 0, doubly answered.** T1–T5 rerun at `05b9a4d~1` (pre ALL checker commits):
take-2 failure identical → revert dead. HEAD rerun with force-quit-Safari-between-
every-run protocol: take 1 always works, take 2 always breaks → the failure is
deterministic, not accumulated OS state. H9 survives only as: the wedge persists
across reload but is cleared by force-quit.

**HEAD symptom decode (matches code exactly):** runs where iOS throws recognition
*errors* increment `_ccFails`; at 3 the checker degrades to recognition-only, which
WORKS — those runs recover scoring but never playback ("auto-stop yes, Revealed, no
playback"). Runs with the silent interims-no-final mode never increment `_ccFails`,
so every take (incl. manual ✓) re-attempts concurrency and re-breaks — never
recovers. The "inconsistency" is just which failure flavor iOS throws.

**Probe isolation (probe_continuous.html, variants added):**

| Run | Pattern | Result |
|---|---|---|
| B | persistent stream, ONE recorder never cycled, no-gesture recognition restarts | finals every session, blob audible start-to-end |
| B1 | same + recorder STOPPED/RECREATED between sessions | recognition still finalized, BUT session blobs from recorder #2 on are ~120 KB of NOISE (not the spoken phrase); playback during a run kills subsequent pickup; **a finished B1 run poisons the NEXT run** ("No speech detected" on fresh everything) |
| B3 | same as B + audio-element tone played between sessions (element unlocked in tap) | finals every session, repeatable across runs; gestureless `play()` resolved (`activation=no`) |
| manual per-run start/stop (full churn + gesture) | | reproduced BOTH app failure modes outside the app — gesture does not help |

**VERDICT: cycling MediaRecorder on a live stream is the poison.**
Instance #2+ captures garbage (explains "no playback" — the app plays a noise
blob), and the churn cumulatively degrades Safari's audio session (explains the
take-2 recognition death, the cross-run/cross-reload wedge, and force-quit as the
only recovery). Playback is innocent (B3). Gesture is irrelevant (H1 dead both
directions). H3 dead (blob audible across sessions). H4 effectively dead
(gestureless play works on an unlocked element).

**B4 (TTS between sessions): innocent — with one condition.** First attempt: TTS
silently never started (no onstart, 5 s timeouts) — gestureless first
`speechSynthesis.speak()` is stuck on iOS. After adding the empty-utterance
unlock inside the starting tap: TTS audible between every take, finals keep
coming (restart-results ≥ 1), repeatable across runs WITHOUT force-quit, no
cross-run poison, per-run blob contains exactly the spoken phrases.
→ Latent app bug to check: the app's hands-free TTS may silently fail whenever
no TTS ran from a tap first; `tts.js` needs the tap-unlock pattern.

**Final matrix:** no-gesture restarts OK (B) · recorder cycling = POISON (B1) ·
audio-element playback innocent w/ tap unlock (B3) · TTS innocent w/ tap unlock (B4).

**Fix design (evidence-backed, checker.js rework):**

1. On the first ✓ tap (session start): getUserMedia once (persistent stream,
   already the case), ONE AudioContext for the whole session, unlock the audio
   element AND speechSynthesis (empty utterance) — all inside the gesture.
2. **Drop MediaRecorder from the checker entirely** — nothing left to cycle.
   Per-take audio: WebAudio PCM capture (ScriptProcessor/AudioWorklet on the
   session context, gated by a per-take flag) → WAV blob per take. The meter
   uses the same context (also resolves H5's churn direction).
3. Recognition: unchanged pattern — fresh SR per take, no-gesture restarts
   (proven B/B3/B4). Degrade logic only for real recognition errors.
4. `reset()` closes the context + releases the stream, as today.
5. Device checkpoints between commits: (a) probe-style sanity — take 1 AND
   take 2 with audible correct playback; (b) full T1–T5 script re-run.

Residual risk (small): PCM capture concurrent with recognition across restarts
wasn't explicitly probed — but the app's meter already runs an AudioContext
source on the stream during recognition (take 1 works), and B-runs prove
heavier concurrency. Checkpoint (a) covers it before anything else builds on it.

## Bugs found while reading (file for later; do NOT fix now)

- `_finalize`'s "first take starts recognition-only" comment describes code that no longer exists — the stale comment is itself evidence of round-2/3 churn.
- `playTake` swallows autoplay rejection (`resolve(false)`, no user feedback).
- Checker `_unlock` never resets `_unlocked` on failure (LoopRecorder's does).
- H2's failure mode (empty blob) leaves `_ccFails` untouched — "3 fails → give up" logic can never trigger on the most likely iOS failure.
- `rec.start()` exceptions are reported as generic `_onError` with the real exception discarded.
