/* Zzzpeak book audio — real per-sentence recordings (piper TTS, opus)
 * served from the separate zzzpeak-audio Pages site. Drop-in upgrade
 * over Web Speech: the reader speaks through speakCurrent(), which
 * prefers this when the current sentence has a file, and falls back to
 * TTS otherwise (per-sentence coverage is allowed to be partial).
 *
 * Chunk playback slices the SENTENCE file using timing.json (per-run
 * end times from piper's native phoneme alignments — see audio3.py):
 * Web Audio buffer slice — sample-accurate, ~5ms edge ramps, small
 * stop padding into the inter-word pause. The media element remains
 * as fallback: rate≠1 stays on it (element playbackRate is pitch-
 * preserving, AudioBufferSourceNode's is not) and browsers whose
 * decodeAudioData can't do Ogg Opus fall back automatically. The
 * element path waits for the seek to LAND before playing and stops
 * via a rAF watcher (its overshoot supplies the padding there).
 *
 * iOS: like Web Speech, the first .play() must happen inside a user
 * gesture — self-arm on the first tap (same pattern as tts.js).
 */
(function (global) {
  "use strict";

  var SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEA"
    + "RKwAAIhYAQACABAAZGF0YQAAAAA=";   // 0-sample wav: unlock ping

  function create(base, bookId) {
    if (base && base[base.length - 1] !== "/") base += "/";
    var root = base + bookId + "/";
    var manifest = null, timing = null;
    var el = new Audio();              // single element, like TTS's utterance
    el.preload = "auto";
    var watcher = 0, done = null;      // pending resolve of the active play
    var fetched = {};                  // sids already prefetch-warmed

    /* Web Audio chunk slicing (2026-07-13). PAD moves the cut past the
     * last word's nominal end into the inter-word pause (the duration
     * tensor ends words mid-decay); pause-LESS boundaries (starter/
     * beginner mid-clause cuts) gain nothing from padding by nature —
     * for those the RAMP is the whole mitigation: a clean fade instead
     * of a click. Element path gets no PAD: its stop overshoot
     * (currentTime granularity + rAF) already supplies about as much. */
    var PAD = 0.045;                   // s, Web Audio stop padding
    var RAMP = 0.005;                  // s, gain ramp at slice edges
    var actx = null, noWebAudio = false, noDecode = false;
    var srcNode = null;                // active AudioBufferSourceNode
    var decoded = {}, decodedIds = []; // tiny per-sid decode cache

    function audioCtx() {
      if (actx || noWebAudio) return actx;
      var AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) { noWebAudio = true; return null; }
      actx = new AC();
      return actx;
    }

    function decodeSid(sid) {
      if (decoded[sid]) return decoded[sid];
      var p = fetch(root + sid + ".opus")
        .then(function (r) {
          if (!r.ok) throw new Error("http " + r.status);
          return r.arrayBuffer();
        })
        .then(function (buf) {
          return new Promise(function (res, rej) {
            actx.decodeAudioData(buf, res, function (e) {
              noDecode = true;         // codec unsupported here: stop
              rej(e || new Error("decode"));   // trying Web Audio at all
            });
          });
        });
      decoded[sid] = p;
      decodedIds.push(sid);
      if (decodedIds.length > 4) delete decoded[decodedIds.shift()];
      p.catch(function () { delete decoded[sid]; });
      return p;
    }

    var unlocked = false;
    function arm() {
      if (unlocked) return;
      unlocked = true;
      try { el.src = SILENCE; el.play().catch(function () {}); } catch (e) {}
      var c = audioCtx();              // unlock Web Audio in the same tap
      if (c && c.state === "suspended") c.resume().catch(function () {});
      document.removeEventListener("touchend", arm, true);
      document.removeEventListener("click", arm, true);
    }
    document.addEventListener("touchend", arm, true);
    document.addEventListener("click", arm, true);

    var ready = Promise.all([
      fetch(root + "manifest.json").then(function (r) { return r.ok ? r.json() : null; }),
      fetch(root + "timing.json").then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; }),
    ]).then(function (rs) {
      manifest = rs[0];
      timing = rs[1];
      return !!manifest;
    }).catch(function () { return false; });

    function finish(ok) {
      if (watcher) { cancelAnimationFrame(watcher); watcher = 0; }
      var d = done; done = null;
      if (d) d(ok);
    }

    var api = {
      ready: ready,

      /* usable at all? (resolved manifest with any coverage) */
      active: function () {
        return !!(manifest && manifest.durations
                  && Object.keys(manifest.durations).length);
      },

      has: function (sid) {
        return !!(manifest && manifest.durations
                  && Object.prototype.hasOwnProperty.call(manifest.durations, sid));
      },

      /* Play sentence `sent`'s file, sliced to chunk [a, b) when the
       * span is partial and timing allows; whole file otherwise.
       * Resolves true when playback completed, false on any failure —
       * the caller falls back to Web Speech on false. */
      play: function (sent, a, b, rate) {
        var sid = sent.id;
        if (!api.has(sid)) return Promise.resolve(false);
        api.stop();
        var whole = a <= 0 && b >= sent.toks.length;
        var t0 = 0, t1 = null;         // null = play to natural end
        if (!whole) {
          var ends = timing && timing.runs && timing.runs[sid];
          var slice = ends ? Data3.audioSlice(sent, a, b, ends) : null;
          if (!slice) return Promise.resolve(false);   // no timing: TTS does the chunk
          t0 = slice.t0; t1 = slice.t1;
        }
        return new Promise(function (resolve) {
          done = resolve;

          function elementPlay() {
            el.onended = function () { finish(true); };
            el.onerror = function () { finish(false); };
            // seek only after metadata exists (iOS/Safari ignore earlier)
            var begin = function () {
              el.onloadedmetadata = null;
              el.playbackRate = rate || 1;
              var started = false;
              var go = function () {
                if (started || done !== resolve) return;
                started = true;
                el.onseeked = null;
                var p = el.play();
                if (p && p.catch) p.catch(function () { finish(false); });
                if (t1 != null) {
                  var watch = function () {
                    if (!done) return;
                    if (el.currentTime >= t1) { el.pause(); finish(true); return; }
                    watcher = requestAnimationFrame(watch);
                  };
                  watcher = requestAnimationFrame(watch);
                }
              };
              // play only once the seek LANDS (Safari otherwise plays a
              // beat from the old position); the timeout covers browsers
              // that skip `seeked` when the position doesn't change
              el.onseeked = go;
              try { el.currentTime = t0; } catch (e) {}
              setTimeout(go, 200);
            };
            el.onloadedmetadata = begin;
            el.src = root + sid + ".opus";   // (re)setting src triggers load
          }

          // sample-accurate slice via Web Audio; element path when the
          // codec can't be decoded or rate≠1 (buffer-source playbackRate
          // would shift pitch — the element preserves it)
          if (t1 != null && (!rate || rate === 1) && !noDecode && audioCtx()) {
            decodeSid(sid).then(function (buf) {
              if (done !== resolve) return;            // superseded
              var end = Math.min(t1 + PAD, buf.duration);
              var dur = Math.max(end - t0, RAMP * 2);
              var g = actx.createGain();
              var s = actx.createBufferSource();
              s.buffer = buf; s.connect(g); g.connect(actx.destination);
              var now = actx.currentTime;
              g.gain.setValueAtTime(0, now);
              g.gain.linearRampToValueAtTime(1, now + RAMP);
              g.gain.setValueAtTime(1, now + dur - RAMP);
              g.gain.linearRampToValueAtTime(0, now + dur);
              s.onended = function () {
                srcNode = null;
                if (done === resolve) finish(true);
              };
              srcNode = s;
              s.start(now, t0, dur);
            }).catch(function () {
              if (done === resolve) elementPlay();     // one-shot fallback
            });
            return;
          }
          elementPlay();
        });
      },

      /* Warm the HTTP cache for upcoming sentences while the current one
       * plays (fetch-nothing-until-play is the caller's job: the reader
       * only calls this alongside play()).  Fire-and-forget; a failed
       * fetch is forgotten so it can be retried later. */
      prefetch: function (sids) {
        (sids || []).forEach(function (sid) {
          if (!api.has(sid) || fetched[sid]) return;
          fetched[sid] = true;
          fetch(root + sid + ".opus")
            .then(function (r) { return r.ok ? r.blob() : Promise.reject(); })
            .catch(function () { delete fetched[sid]; });
        });
      },

      /* stop resolves the pending play with null (cancelled), which the
       * reader must NOT treat as "fall back to Web Speech" — only a
       * strict false means the source failed. */
      stop: function () {
        if (srcNode) {                 // onended fires after done is
          try { srcNode.stop(); } catch (e) {}   // nulled -> no-op
          srcNode = null;
        }
        try { el.pause(); } catch (e) {}
        finish(null);
      },

      playing: function () {
        return !!done;
      },
    };
    return api;
  }

  global.BookAudio = { create: create };
})(typeof window !== "undefined" ? window : this);
