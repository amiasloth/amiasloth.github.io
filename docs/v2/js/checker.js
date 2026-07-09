/* Zzzpeak v2 — Check mode engine (Phase 04), reworked after device isolation.
 * Evidence: docs/v2/STT_DEBUG_PLAN.md, device sessions 1–3 (probe B/B1/B3/B4).
 *
 * WHAT THE PROBES PROVED (iPhone, real device):
 *  - Cycling MediaRecorder per take on a live stream is the iOS poison:
 *    recorder instance #2+ captures NOISE, and the churn cumulatively wedges
 *    Safari's audio session (breaks recognition on later takes, survives
 *    reload, only force-quit recovers). MediaRecorder is therefore GONE
 *    from this file.
 *  - Fresh SpeechRecognition per take, restarted with NO gesture on a
 *    persistent mic stream, works — as long as nothing is cycled (probe B).
 *  - Audio-element playback and TTS between takes are harmless, provided
 *    each got its one-time unlock inside a user tap (probes B3/B4).
 *
 * DESIGN:
 *  - PERSISTENT SESSION (the v1 trick): getUserMedia ONCE from the first
 *    tap; the stream lives across phrases, released only on reset().
 *  - ONE AudioContext per mic session (never per take — no churn). It
 *    feeds BOTH the level meter and a ScriptProcessor PCM capture.
 *  - Per take: gate the PCM capture on/off + one fresh recognition. The
 *    take's audio becomes a small WAV blob — playable immediately, no
 *    recorder involved.
 *
 * Scoring lives in match.js; this module only produces the transcript, its
 * alternatives, and (optionally) a playable take URL via onResult.
 */
(function (global) {
  "use strict";

  var SILENCE =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

  var SR = global.SpeechRecognition || global.webkitSpeechRecognition || null;
  var Ctx = global.AudioContext || global.webkitAudioContext || null;

  var MAX_TAKE_SECONDS = 20;   // hard cap on captured audio per take

  function noop() {}

  // Float32 chunks -> 16-bit mono WAV blob.
  function encodeWav(chunks, totalLen, rate) {
    var buf = new ArrayBuffer(44 + totalLen * 2), v = new DataView(buf);
    function str(o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    str(0, "RIFF"); v.setUint32(4, 36 + totalLen * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, totalLen * 2, true);
    var off = 44;
    for (var c = 0; c < chunks.length; c++) {
      var ch = chunks[c];
      for (var i = 0; i < ch.length; i++) {
        var s = Math.max(-1, Math.min(1, ch[i]));
        v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true); off += 2;
      }
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  function Checker(opts) {
    opts = opts || {};
    this.lang = Checker.bcp(opts.lang || "en");
    this.onState = opts.onState || noop;     // (state)
    this.onInterim = opts.onInterim || noop; // (interimText)
    this.onSpeechStart = opts.onSpeechStart || null; // fires when speech is detected
    this.onLevel = opts.onLevel || null;     // (0..1)
    this.onResult = opts.onResult || noop;   // ({transcript, alternatives, takeUrl})
    this.onError = opts.onError || noop;     // (kind, message)  kind: mic|no-speech|unavailable|generic

    this.state = "idle";
    this._rec = null;         // SpeechRecognition (per take)
    this._stream = null;      // PERSISTENT mic stream (kept across takes)
    this._url = null;         // last take's WAV url
    this._safety = null;
    this._gen = 0;            // bumped each take/reset; stale callbacks bail
    this._finals = [];        // final alternative transcripts (best first)
    this._disabled = false;   // recognition service unavailable this session
    this._canPlayback = !!(navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia && Ctx);

    // WebAudio graph — ONE per mic session, shared by meter + capture.
    this._ctx = null;
    this._graphStream = null; // the stream the graph was built on
    this._srcNode = null;
    this._proc = null;
    this._sink = null;        // zero-gain node so the processor runs w/o feedback
    this._analyser = null;
    this._meterRAF = null;

    // per-take PCM capture state
    this._capturing = false;
    this._capChunks = [];
    this._capLen = 0;

    this.audio = new Audio();
    this.audio.setAttribute("playsinline", "");
    this.audio.preload = "auto";
    this._unlocked = false;
  }

  Checker.isSupported = function () { return !!SR; };

  Checker.bcp = function (lang) {
    if (!lang) return "en-US";
    if (lang.indexOf("-") > 0) return lang;
    var map = { de: "de-DE", en: "en-US" };
    return map[lang.toLowerCase()] || lang;
  };

  Checker.prototype.playbackEnabled = function () { return this._canPlayback; };
  Checker.prototype.disabled = function () { return this._disabled; };
  Checker.prototype.hasTake = function () { return !!this._url; };
  Checker.prototype.micOpen = function () { return !!(this._stream && this._stream.active); };

  Checker.prototype._set = function (s) { this.state = s; this._gen++; this.onState(s); };

  Checker.prototype._unlock = function () {
    if (this._unlocked) return;
    this._unlocked = true;
    this.audio.src = SILENCE;
    var self = this;
    var p = this.audio.play();
    // A failed unlock must NOT latch: reset so the next tap can try again.
    if (p && p.catch) p.catch(function () { self._unlocked = false; });
  };

  // ---- audio graph (one per mic session; NEVER cycled per take) ----
  Checker.prototype._ensureGraph = function () {
    if (!this._stream || !this._stream.active || !Ctx) return false;
    if (this._ctx && this._graphStream === this._stream) return true;
    this._closeGraph();                       // stream changed: rebuild once
    try {
      this._ctx = new Ctx();
      this._srcNode = this._ctx.createMediaStreamSource(this._stream);
      this._analyser = this._ctx.createAnalyser();
      this._analyser.fftSize = 512;
      this._srcNode.connect(this._analyser);
      this._proc = this._ctx.createScriptProcessor(4096, 1, 1);
      this._sink = this._ctx.createGain();
      this._sink.gain.value = 0;              // keep the processor pumping, no feedback
      this._srcNode.connect(this._proc);
      this._proc.connect(this._sink);
      this._sink.connect(this._ctx.destination);
      var self = this;
      this._proc.onaudioprocess = function (e) {
        if (!self._capturing || !self._ctx) return;
        var d = e.inputBuffer.getChannelData(0);
        if (self._capLen + d.length > self._ctx.sampleRate * MAX_TAKE_SECONDS) return;
        self._capChunks.push(new Float32Array(d));
        self._capLen += d.length;
      };
      this._graphStream = this._stream;
      return true;
    } catch (e) {                             // no capture this take; retry next take
      this._closeGraph();
      return false;
    }
  };

  Checker.prototype._closeGraph = function () {
    try { if (this._proc) { this._proc.onaudioprocess = null; this._proc.disconnect(); } } catch (e) {}
    try { if (this._srcNode) this._srcNode.disconnect(); } catch (e) {}
    try { if (this._sink) this._sink.disconnect(); } catch (e) {}
    if (this._ctx && this._ctx.state !== "closed") { try { this._ctx.close().catch(noop); } catch (e) {} }
    this._ctx = null; this._srcNode = null; this._proc = null; this._sink = null;
    this._analyser = null; this._graphStream = null;
  };

  // ---- per-take capture gating ----
  Checker.prototype._beginCapture = function () {
    if (!this._canPlayback || !this._ensureGraph()) return;
    if (this._ctx.state === "suspended") { try { this._ctx.resume().catch(noop); } catch (e) {} }
    this._capChunks = []; this._capLen = 0;
    this._capturing = true;
    this._startMeter();
  };

  Checker.prototype._discardCapture = function () {
    this._capturing = false;
    this._capChunks = []; this._capLen = 0;
  };

  // End the capture and return a WAV object URL for the take (or null).
  Checker.prototype._endCaptureUrl = function () {
    this._capturing = false;
    if (!this._capLen || !this._ctx) { this._discardCapture(); return null; }
    var url = null;
    try {
      var blob = encodeWav(this._capChunks, this._capLen, this._ctx.sampleRate);
      if (blob && blob.size) url = URL.createObjectURL(blob);
    } catch (e) { /* no playback for this take */ }
    this._discardCapture();
    return url;
  };

  // ---- level meter (reads the session analyser; RAF only, no ctx churn) ----
  Checker.prototype._startMeter = function () {
    if (!this.onLevel || !this._analyser || this._meterRAF) return;
    var self = this;
    var data = new Uint8Array(this._analyser.frequencyBinCount);
    var tick = function () {
      if (!self._analyser) { self._meterRAF = null; return; }
      self._analyser.getByteTimeDomainData(data);
      var peak = 0;
      for (var i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i] - 128) / 128);
      if (self.onLevel) self.onLevel(self.state === "listening" ? peak : 0);
      self._meterRAF = requestAnimationFrame(tick);
    };
    this._meterRAF = requestAnimationFrame(tick);
  };

  Checker.prototype._stopMeter = function () {
    if (this._meterRAF) cancelAnimationFrame(this._meterRAF);
    this._meterRAF = null;
    if (this.onLevel) this.onLevel(0);
  };

  // Reuse the open mic stream if we have one; otherwise acquire it once.
  Checker.prototype._ensureStream = function (gen) {
    var self = this;
    if (this._stream && this._stream.active) return Promise.resolve(this._stream);
    return navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true }
    }).then(function (s) {
      if (self._gen !== gen) { s.getTracks().forEach(function (t) { t.stop(); }); return null; }
      self._stream = s;
      return s;
    });
  };

  // Mic failure policy: only a REAL permission denial is permanent. Anything
  // else (device busy, teardown race, transient iOS audio-session weirdness)
  // is retried on a later take.
  Checker.prototype._noteMicFail = function (err) {
    var name = err && err.name;
    if (name === "NotAllowedError" || name === "SecurityError") this._canPlayback = false;
  };

  // ---- public: begin one check take (call the first one from a user tap) ----
  //  - session already open: gate capture on + fresh recognition, both sync
  //    (probe-verified: restarts on a live session need no gesture and no delay);
  //  - first take: stream -> graph + capture -> brief beat -> recognition
  //    (the beat matches the take-1 pattern that always worked on device).
  Checker.prototype.start = function () {
    if (!SR || this._disabled || this.state === "listening") return;
    this._finals = [];
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this._set("listening");
    var self = this, gen = this._gen;
    if (this._stream && this._stream.active) {
      this._beginCapture();
      this._startRecognition();
      return;
    }
    if (!this._canPlayback) {
      this._startRecognition();
      return;
    }
    this._ensureStream(gen).then(function (stream) {
      if (self._gen !== gen) return;
      if (stream) {
        self._beginCapture();
        setTimeout(function () { if (self._gen === gen) self._startRecognition(); }, 120);
      } else {
        self._startRecognition();
      }
    }).catch(function (err) {
      self._noteMicFail(err);
      if (self._gen === gen) self._startRecognition();
    });
  };

  Checker.prototype._startRecognition = function () {
    var self = this, gen = this._gen;
    var rec = new SR();
    this._rec = rec;
    rec.lang = this.lang;
    rec.continuous = false;
    rec.interimResults = true;
    try { rec.maxAlternatives = 3; } catch (e) {}

    rec.onresult = function (e) {
      if (self._gen !== gen) return;
      var interim = "";
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var res = e.results[i];
        if (res.isFinal) {
          var alts = [];
          for (var a = 0; a < res.length; a++) if (res[a] && res[a].transcript) alts.push(res[a].transcript.trim());
          if (alts.length) self._finals.push(alts);
        } else {
          interim += res[0].transcript;
        }
      }
      if (interim) self.onInterim(interim.trim());
    };

    rec.onspeechstart = function () { if (self._gen === gen && self.onSpeechStart) self.onSpeechStart(); };
    rec.onerror = function (e) { if (self._gen === gen) self._onError(e.error || "generic"); };
    rec.onend = function () { if (self._gen === gen) self._finalize(); };

    try { rec.start(); }
    catch (e) { this._onError("generic"); return; }

    if (this._safety) clearTimeout(this._safety);
    this._safety = setTimeout(function () { if (self._gen === gen) self.stop(); }, 12000);
  };

  Checker.prototype._onError = function (kind) {
    if (kind === "network" || kind === "service-not-allowed" || kind === "language-not-supported") {
      this._disabled = true;
      this.reset();                                // release the mic — feature hidden
      this.onError("unavailable", "Speech recognition isn't available here.");
      return;
    }
    if (kind === "not-allowed") {
      // If we already hold a live mic stream, this is NOT a permission
      // denial — it's iOS refusing a recognition start. Keep the persistent
      // session alive (it's what makes hands-free work) and just ask for a tap.
      if (this._stream && this._stream.active) {
        this._endTakeIdle();
        this.onError("generic", "Tap ✓ to continue.");
        return;
      }
      this.reset();
      this.onError("mic", "Microphone/dictation permission is needed. On iPhone: Settings → Siri & Search → enable dictation, and allow the mic.");
      return;
    }
    if (kind === "no-speech") {
      this._endTakeIdle();                         // keep the mic open for a quick retry
      this.onError("no-speech", "Didn't hear anything — tap to try again.");
      return;
    }
    // aborted / audio-capture / unknown: end the take, keep the session.
    // (The old degrade-and-restart machinery existed to dodge recorder
    // interference; with no recorder there is nothing to degrade to, and its
    // instant restart caused a second error on iOS — see the debug plan.)
    this._endTakeIdle();
    this.onError("generic", "Speech recognition failed — tap to try again.");
  };

  Checker.prototype._finalize = function () {
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    var alternatives = [];
    for (var i = 0; i < this._finals.length; i++)
      for (var k = 0; k < this._finals[i].length; k++) alternatives.push(this._finals[i][k]);
    var transcript = alternatives.length ? alternatives[0] : "";

    this._detachRec();
    this._stopMeter();
    var url = this._endCaptureUrl();             // WAV for THIS take (or null)
    if (url) this._url = url;
    this._set("idle");                           // stream + graph stay OPEN for the next phrase
    this._primeStream();                         // recognition-only first take: open the session now
    this.onResult({ transcript: transcript, alternatives: alternatives, takeUrl: url || null });
  };

  // ---- public: stop the current recognition (ends the take normally) ----
  Checker.prototype.stop = function () {
    if (this.state !== "listening") return;
    if (this._rec) { try { this._rec.stop(); } catch (e) { this._finalize(); } }
    else this._finalize();
  };

  // ---- public: end the current take but KEEP the mic open (used on nav
  // between phrases so the persistent session survives, v1-style) ----
  Checker.prototype.endTake = function () {
    this._gen++;
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._discardCapture();
    this._stopMeter();
    this.state = "idle";
    this.onState("idle");
  };

  Checker.prototype._endTakeIdle = function () {
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._discardCapture();
    this._stopMeter();
    this._set("idle");
    this._primeStream();   // e.g. a silent first take must still open the session
  };

  // Open the persistent mic stream between takes if we don't hold it yet.
  // Delayed a beat so it never races the recognition teardown (on iOS the
  // mic is still "busy" right after a take ends -> NotReadableError, which
  // must stay transient, not kill playback for the session).
  Checker.prototype._primeStream = function () {
    if (this._disabled || !this._canPlayback) return;
    if (this._stream && this._stream.active) return;
    var self = this, gen = this._gen;
    setTimeout(function () {
      if (self._gen !== gen) return;                       // a new take took over
      if (self._stream && self._stream.active) return;
      self._ensureStream(gen).catch(function (e) { self._noteMicFail(e); });
    }, 300);
  };

  // ---- public: play the last take ----
  Checker.prototype.playTake = function () {
    var self = this;
    return new Promise(function (resolve) {
      if (!self._url) { resolve(false); return; }
      self._unlock();
      var a = self.audio;
      a.src = self._url;
      a.onended = function () { resolve(true); };
      var p = a.play();
      // A rejected play means the unlock is gone — reset it so the next
      // user tap can restore playback (was a latched failure before).
      if (p && p.catch) p.catch(function () { self._unlocked = false; resolve(false); });
    });
  };

  Checker.prototype._detachRec = function () {
    if (this._rec) {
      this._rec.onresult = this._rec.onerror = this._rec.onend = this._rec.onspeechstart = null;
      try { this._rec.abort(); } catch (e) {}
      this._rec = null;
    }
  };

  Checker.prototype._releaseStream = function () {
    if (this._stream) { this._stream.getTracks().forEach(function (t) { t.stop(); }); this._stream = null; }
  };

  // ---- public: full stop — release the mic (leaving Check mode / hidden) ----
  Checker.prototype.reset = function () {
    this._gen++;
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._discardCapture();
    this._stopMeter();
    this._closeGraph();
    this._releaseStream();
    try { this.audio.pause(); } catch (e) {}
    this.audio.onended = null;
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this.state = "idle";
  };

  global.Checker = Checker;
})(window);
