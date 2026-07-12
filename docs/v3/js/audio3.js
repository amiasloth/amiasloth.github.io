/* Zzzpeak book audio — real per-sentence recordings (piper TTS, opus)
 * served from the separate zzzpeak-audio Pages site. Drop-in upgrade
 * over Web Speech: the reader speaks through speakCurrent(), which
 * prefers this when the current sentence has a file, and falls back to
 * TTS otherwise (per-sentence coverage is allowed to be partial).
 *
 * Chunk playback slices the SENTENCE file using timing.json (per-run
 * end times from piper's native phoneme alignments — see audio3.py):
 * seek to t0, stop at t1 via a rAF watcher (~1 frame precision; Web
 * Audio sample-accurate slicing is the upgrade path if ever needed).
 * playbackRate is pitch-preserving in modern browsers, so the existing
 * "Voice speed" pref maps straight onto it.
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

    var unlocked = false;
    function arm() {
      if (unlocked) return;
      unlocked = true;
      try { el.src = SILENCE; el.play().catch(function () {}); } catch (e) {}
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
          el.onended = function () { finish(true); };
          el.onerror = function () { finish(false); };
          // seek only after metadata exists (iOS/Safari ignore earlier)
          var begin = function () {
            el.onloadedmetadata = null;
            el.playbackRate = rate || 1;
            try { el.currentTime = t0; } catch (e) {}
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
          el.onloadedmetadata = begin;
          el.src = root + sid + ".opus";   // (re)setting src triggers load
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
