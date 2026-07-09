/* Zzzpeak v2 — Check mode engine (Phase 04).
 *
 * Owns the Web Speech API SpeechRecognition lifecycle and, where the
 * platform allows it (see probe / Milestone 0), a CONCURRENT MediaRecorder
 * capture so the user's take can be played back. Deliberately NOT built on
 * LoopRecorder — separate concern — but it obeys the same iOS rules:
 *   - start only from a user gesture,
 *   - negotiate the mime type (never assume webm),
 *   - one <audio> element, unlocked once inside the tap,
 *   - the two mic systems (this and LoopRecorder) never run at once; the
 *     reader reset()s the other before starting either.
 *
 * Scoring lives in match.js; this module only produces the transcript,
 * its alternatives, and (optionally) a playable take URL, then hands them
 * back via onResult for the reader to score and render.
 */
(function (global) {
  "use strict";

  var SILENCE =
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

  var SR = global.SpeechRecognition || global.webkitSpeechRecognition || null;

  function pickMime() {
    if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return null;
    var types = ["audio/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
    for (var i = 0; i < types.length; i++) {
      try { if (MediaRecorder.isTypeSupported(types[i])) return types[i]; } catch (e) {}
    }
    return "";
  }

  function noop() {}

  function Checker(opts) {
    opts = opts || {};
    this.lang = Checker.bcp(opts.lang || "en");
    this.onState = opts.onState || noop;     // (state)
    this.onInterim = opts.onInterim || noop; // (interimText)
    this.onLevel = opts.onLevel || null;     // (0..1)
    this.onResult = opts.onResult || noop;   // ({transcript, alternatives, takeUrl})
    this.onError = opts.onError || noop;     // (kind, message)  kind: mic|no-speech|unavailable|generic

    this.state = "idle";
    this._rec = null;         // SpeechRecognition
    this._mr = null;          // MediaRecorder
    this._stream = null;
    this._chunks = [];
    this._mime = pickMime();
    this._url = null;
    this._safety = null;
    this._gen = 0;            // bumped each session; stale callbacks bail
    this._finals = [];        // final alternative transcripts (best first)
    this._disabled = false;   // recognition service unavailable this session
    this._degraded = false;   // concurrency failed once -> recognition only
    // capability: playback needs a recorder AND a mic AND not-yet-degraded
    this._canPlayback = !!(navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia && typeof MediaRecorder !== "undefined");

    this.audio = new Audio();
    this.audio.setAttribute("playsinline", "");
    this.audio.preload = "auto";
    this._unlocked = false;

    this._analyser = null; this._meterCtx = null; this._meterRAF = null;
  }

  Checker.isSupported = function () { return !!SR; };

  Checker.bcp = function (lang) {
    if (!lang) return "en-US";
    if (lang.indexOf("-") > 0) return lang;      // already a BCP tag
    var map = { de: "de-DE", en: "en-US" };
    return map[lang.toLowerCase()] || lang;
  };

  Checker.prototype.playbackEnabled = function () { return this._canPlayback && !this._degraded; };
  Checker.prototype.disabled = function () { return this._disabled; };
  Checker.prototype.hasTake = function () { return !!this._url; };

  Checker.prototype._set = function (s) { this.state = s; this._gen++; this.onState(s); };

  Checker.prototype._unlock = function () {
    if (this._unlocked) return;
    this._unlocked = true;
    this.audio.src = SILENCE;
    var p = this.audio.play();
    if (p && p.catch) p.catch(function () {}.bind(this));
  };

  // ---- level meter (only when we hold a stream, i.e. playback path) ----
  Checker.prototype._startMeter = function () {
    if (!this.onLevel || !this._stream || this._analyser) return;
    try {
      var Ctx = global.AudioContext || global.webkitAudioContext;
      this._meterCtx = new Ctx();
      var src = this._meterCtx.createMediaStreamSource(this._stream);
      this._analyser = this._meterCtx.createAnalyser();
      this._analyser.fftSize = 512;
      src.connect(this._analyser);
      var data = new Uint8Array(this._analyser.frequencyBinCount);
      var self = this;
      var tick = function () {
        if (!self._analyser) return;
        self._analyser.getByteTimeDomainData(data);
        var peak = 0;
        for (var i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i] - 128) / 128);
        if (self.onLevel) self.onLevel(self.state === "listening" ? peak : 0);
        self._meterRAF = requestAnimationFrame(tick);
      };
      tick();
    } catch (e) { /* meter is best-effort */ }
  };

  Checker.prototype._stopMeter = function () {
    if (this._meterRAF) cancelAnimationFrame(this._meterRAF);
    this._meterRAF = null; this._analyser = null;
    if (this._meterCtx && this._meterCtx.state !== "closed") this._meterCtx.close().catch(function () {});
    this._meterCtx = null;
    if (this.onLevel) this.onLevel(0);
  };

  // ---- public: begin a check take (call from a user tap) ----
  Checker.prototype.start = function () {
    if (!SR || this._disabled || this.state === "listening") return;
    this._finals = [];
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this._set("listening");
    if (this.playbackEnabled()) this._startWithRecorder();
    else this._startRecognition();
  };

  Checker.prototype._startWithRecorder = function () {
    var self = this, gen = this._gen;
    navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true }
    }).then(function (stream) {
      if (self._gen !== gen) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      self._stream = stream;
      self._chunks = [];
      try {
        self._mr = self._mime ? new MediaRecorder(stream, { mimeType: self._mime })
                              : new MediaRecorder(stream);
      } catch (e) { self._mr = new MediaRecorder(stream); }
      self._mr.ondataavailable = function (e) { if (e.data && e.data.size) self._chunks.push(e.data); };
      try { self._mr.start(); } catch (e) {}
      self._startMeter();
      // small beat so the capture session is really open before recognition
      setTimeout(function () { if (self._gen === gen) self._startRecognition(); }, 200);
    }).catch(function (err) {
      // No mic for the recorder: fall back to recognition-only (still useful).
      self._canPlayback = false;
      self._releaseStream();
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

    rec.onerror = function (e) { if (self._gen === gen) self._onError(e.error || "generic"); };
    rec.onend = function () { if (self._gen === gen) self._finalize(); };

    try { rec.start(); }
    catch (e) { this._onError("generic"); return; }

    if (this._safety) clearTimeout(this._safety);
    this._safety = setTimeout(function () { if (self._gen === gen) self.stop(); }, 12000);
  };

  Checker.prototype._onError = function (kind) {
    // Service genuinely unavailable -> hide Check mode for the session.
    if (kind === "network" || kind === "service-not-allowed" || kind === "language-not-supported") {
      this._disabled = true;
      this._teardown();
      this.onError("unavailable", "Speech recognition isn't available here.");
      return;
    }
    if (kind === "not-allowed") {
      this._teardown();
      this.onError("mic", "Microphone/dictation permission is needed. On iPhone: Settings → Siri & Search → enable dictation, and allow the mic.");
      return;
    }
    if (kind === "no-speech") {
      this._teardown();
      this.onError("no-speech", "Didn't hear anything — tap to try again.");
      return;
    }
    // audio-capture / aborted / unknown: if the recorder might be the cause,
    // auto-degrade ONCE and retry recognition alone.
    if (!this._degraded && (this._mr || this._stream)) {
      this._degraded = true;
      this._canPlayback = false;
      this._detachRec();
      this._releaseStream();
      this._stopMeter();
      this._gen++;                 // invalidate the failed session's callbacks
      var self = this, gen = this._gen;
      this.state = "listening";
      setTimeout(function () { if (self._gen === gen) self._startRecognition(); }, 50);
      return;
    }
    this._teardown();
    this.onError("generic", "Speech recognition failed — tap to try again.");
  };

  Checker.prototype._finalize = function () {
    var self = this, gen = this._gen;
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    // best alternatives across final results: flatten, best (index 0) first
    var alternatives = [];
    for (var i = 0; i < this._finals.length; i++)
      for (var k = 0; k < this._finals[i].length; k++) alternatives.push(this._finals[i][k]);
    var transcript = alternatives.length ? alternatives[0] : "";

    var done = function (takeUrl) {
      if (self._gen !== gen) return;
      self._stopMeter();
      self._releaseStream();
      self._rec = null;
      self._set("idle");
      self.onResult({ transcript: transcript, alternatives: alternatives, takeUrl: takeUrl || null });
    };

    if (this._mr && this._mr.state !== "inactive") {
      var mr = this._mr;
      mr.onstop = function () {
        var blob = self._chunks.length ? new Blob(self._chunks, { type: mr.mimeType || self._mime || "" }) : null;
        if (blob && blob.size) { self._url = URL.createObjectURL(blob); done(self._url); }
        else done(null);
      };
      try { mr.stop(); } catch (e) { done(null); }
    } else {
      done(null);
    }
  };

  // ---- public: stop the current recognition (ends the session normally) ----
  Checker.prototype.stop = function () {
    if (this.state !== "listening") return;
    if (this._rec) { try { this._rec.stop(); } catch (e) { this._finalize(); } }
    else this._finalize();
  };

  // ---- public: play the last take (user tap) ----
  Checker.prototype.playTake = function () {
    var self = this;
    return new Promise(function (resolve) {
      if (!self._url) { resolve(false); return; }
      self._unlock();
      var a = self.audio;
      a.src = self._url;
      a.onended = function () { resolve(true); };
      var p = a.play();
      if (p && p.catch) p.catch(function () { resolve(false); });
    });
  };

  Checker.prototype._detachRec = function () {
    if (this._rec) {
      this._rec.onresult = this._rec.onerror = this._rec.onend = null;
      try { this._rec.abort(); } catch (e) {}
      this._rec = null;
    }
  };

  Checker.prototype._releaseStream = function () {
    if (this._mr && this._mr.state !== "inactive") { try { this._mr.stop(); } catch (e) {} }
    this._mr = null;
    if (this._stream) { this._stream.getTracks().forEach(function (t) { t.stop(); }); this._stream = null; }
  };

  Checker.prototype._teardown = function () {
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._releaseStream();
    this._stopMeter();
    this._set("idle");
  };

  // ---- public: full stop, release everything (leaving Check mode / nav) ----
  Checker.prototype.reset = function () {
    this._gen++;                 // invalidate any in-flight callbacks
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._releaseStream();
    this._stopMeter();
    try { this.audio.pause(); } catch (e) {}
    this.audio.onended = null;
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this.state = "idle";
  };

  global.Checker = Checker;
})(window);
