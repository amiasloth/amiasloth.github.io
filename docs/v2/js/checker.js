/* Zzzpeak v2 — Check mode engine (Phase 04).
 *
 * Owns the Web Speech API SpeechRecognition lifecycle and, where the
 * platform allows it, a concurrent MediaRecorder capture so the user's take
 * can be played back. Deliberately NOT built on LoopRecorder, but it obeys
 * the same iOS rules.
 *
 * PERSISTENT SESSION (the v1 trick): the getUserMedia mic stream is opened
 * ONCE (from the first user tap) and kept alive across phrases — released
 * only on reset() (leaving Check mode / page hidden). Each phrase reuses the
 * open stream: a fresh MediaRecorder + a fresh recognition, no re-acquiring
 * the mic. This is what lets the reader auto-continue hands-free WITHOUT a
 * tap per phrase, including on iOS Safari (verified with probe_continuous:
 * a no-gesture recognition restart on an already-open mic session works).
 *
 * Scoring lives in match.js; this module only produces the transcript, its
 * alternatives, and (optionally) a playable take URL via onResult.
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
    this.onSpeechStart = opts.onSpeechStart || null; // fires when speech is detected
    this.onLevel = opts.onLevel || null;     // (0..1)
    this.onResult = opts.onResult || noop;   // ({transcript, alternatives, takeUrl})
    this.onError = opts.onError || noop;     // (kind, message)  kind: mic|no-speech|unavailable|generic

    this.state = "idle";
    this._rec = null;         // SpeechRecognition (per take)
    this._mr = null;          // MediaRecorder (per take)
    this._stream = null;      // PERSISTENT mic stream (kept across takes)
    this._chunks = [];
    this._mime = pickMime();
    this._url = null;
    this._safety = null;
    this._gen = 0;            // bumped each take/reset; stale callbacks bail
    this._finals = [];        // final alternative transcripts (best first)
    this._disabled = false;   // recognition service unavailable this session
    this._degraded = false;   // concurrency failed on THIS take -> recognition only
    this._ccFails = 0;        // consecutive concurrency failures (3 -> give up)
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
    if (lang.indexOf("-") > 0) return lang;
    var map = { de: "de-DE", en: "en-US" };
    return map[lang.toLowerCase()] || lang;
  };

  Checker.prototype.playbackEnabled = function () {
    return this._canPlayback && !this._degraded && this._ccFails < 3;
  };
  Checker.prototype.disabled = function () { return this._disabled; };
  Checker.prototype.hasTake = function () { return !!this._url; };
  Checker.prototype.micOpen = function () { return !!(this._stream && this._stream.active); };

  Checker.prototype._set = function (s) { this.state = s; this._gen++; this.onState(s); };

  Checker.prototype._unlock = function () {
    if (this._unlocked) return;
    this._unlocked = true;
    this.audio.src = SILENCE;
    var p = this.audio.play();
    if (p && p.catch) p.catch(function () {});
  };

  // ---- level meter (uses the persistent stream) ----
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
    } catch (e) { /* best-effort */ }
  };

  Checker.prototype._stopMeter = function () {
    if (this._meterRAF) cancelAnimationFrame(this._meterRAF);
    this._meterRAF = null; this._analyser = null;
    if (this._meterCtx && this._meterCtx.state !== "closed") this._meterCtx.close().catch(function () {});
    this._meterCtx = null;
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
  // is retried on a later take — a one-off hiccup must never disable
  // playback or the persistent session for the whole visit.
  Checker.prototype._noteMicFail = function (err) {
    var name = err && err.name;
    if (name === "NotAllowedError" || name === "SecurityError") this._canPlayback = false;
  };

  // ---- public: begin one check take (call the first one from a user tap) ----
  // Same start order on ALL platforms (concurrent capture + recognition is
  // verified working on iOS):
  //  - session already open: recorder + recognition, both sync;
  //  - first take: stream -> recorder -> brief beat -> recognition.
  // If a platform ever refuses a recognition start on this path, the
  // not-allowed handler keeps the session alive and asks for a tap — it
  // degrades per-take, never silently changes configured behavior.
  Checker.prototype.start = function () {
    if (!SR || this._disabled || this.state === "listening") return;
    this._degraded = false;    // retry concurrency each take (until _ccFails caps)
    this._finals = [];
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this._set("listening");
    var self = this, gen = this._gen;
    if (this.playbackEnabled() && this._stream && this._stream.active) {
      this._startRecorder(this._stream);
      this._startRecognition();
      return;
    }
    if (!this.playbackEnabled()) {
      this._startRecognition();
      return;
    }
    this._ensureStream(gen).then(function (stream) {
      if (self._gen !== gen) return;
      if (stream) {
        self._startRecorder(stream);
        // brief beat so capture is really open before recognition
        setTimeout(function () { if (self._gen === gen) self._startRecognition(); }, 120);
      } else {
        self._startRecognition();
      }
    }).catch(function (err) {
      self._noteMicFail(err);
      if (self._gen === gen) self._startRecognition();
    });
  };

  Checker.prototype._startRecorder = function (stream) {
    this._chunks = [];
    try {
      this._mr = this._mime ? new MediaRecorder(stream, { mimeType: this._mime })
                            : new MediaRecorder(stream);
    } catch (e) { this._mr = new MediaRecorder(stream); }
    var self = this;
    this._mr.ondataavailable = function (e) { if (e.data && e.data.size) self._chunks.push(e.data); };
    try { this._mr.start(); } catch (e) {}
    this._startMeter();
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
      // denial — it's iOS refusing a recognition start outside a gesture.
      // Keep the persistent session alive (it's what makes hands-free work)
      // and just ask for a tap.
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
    // audio-capture / aborted / unknown: degrade THIS take (recognition
    // alone). Concurrency is retried next take; 3 consecutive failures ->
    // give up for the session; any success forgives past failures.
    if (!this._degraded && (this._mr || this.playbackEnabled())) {
      this._degraded = true;
      this._ccFails++;
      this._detachRec();
      this._stopRecorder();
      this._stopMeter();
      this._gen++;
      var self = this, gen = this._gen;
      this.state = "listening";
      setTimeout(function () { if (self._gen === gen) self._startRecognition(); }, 50);
      return;
    }
    this._endTakeIdle();
    this.onError("generic", "Speech recognition failed — tap to try again.");
  };

  Checker.prototype._finalize = function () {
    var self = this, gen = this._gen;
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    var alternatives = [];
    for (var i = 0; i < this._finals.length; i++)
      for (var k = 0; k < this._finals[i].length; k++) alternatives.push(this._finals[i][k]);
    var transcript = alternatives.length ? alternatives[0] : "";

    var done = function (takeUrl) {
      if (self._gen !== gen) return;
      self._detachRec();
      self._stopMeter();                           // stream stays OPEN for the next phrase
      self._set("idle");
      // PERSISTENT SESSION: if we don't hold the mic yet (first take starts
      // recognition-only so the tap gesture isn't wasted on getUserMedia),
      // open it NOW — between takes, where it can't disturb recognition.
      // This is what keeps hands-free auto-restart working on iPhone, and
      // enables take playback from the next phrase on.
      self._primeStream();
      self.onResult({ transcript: transcript, alternatives: alternatives, takeUrl: takeUrl || null });
    };

    if (this._mr && this._mr.state !== "inactive") {
      var mr = this._mr;
      mr.onstop = function () {
        var blob = self._chunks.length ? new Blob(self._chunks, { type: mr.mimeType || self._mime || "" }) : null;
        self._mr = null;
        if (blob && blob.size) {
          self._ccFails = 0;                     // concurrency worked — forgive past failures
          self._url = URL.createObjectURL(blob);
          done(self._url);
        }
        else done(null);
      };
      try { mr.stop(); } catch (e) { self._mr = null; done(null); }
    } else {
      done(null);
    }
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
    this._stopRecorder();
    this._stopMeter();
    this.state = "idle";
    this.onState("idle");
  };

  Checker.prototype._endTakeIdle = function () {
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._stopRecorder();
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
      this._rec.onresult = this._rec.onerror = this._rec.onend = this._rec.onspeechstart = null;
      try { this._rec.abort(); } catch (e) {}
      this._rec = null;
    }
  };

  Checker.prototype._stopRecorder = function () {
    if (this._mr && this._mr.state !== "inactive") { try { this._mr.stop(); } catch (e) {} }
    this._mr = null;
    this._chunks = [];
  };

  Checker.prototype._releaseStream = function () {
    if (this._stream) { this._stream.getTracks().forEach(function (t) { t.stop(); }); this._stream = null; }
  };

  // ---- public: full stop — release the mic (leaving Check mode / hidden) ----
  // Also clears the transient failure counters, so toggling Check mode is a
  // true clean slate. (_canPlayback stays: it only latches on a REAL
  // permission denial; _disabled stays: the service won't come back.)
  Checker.prototype.reset = function () {
    this._gen++;
    this._ccFails = 0;
    this._degraded = false;
    if (this._safety) { clearTimeout(this._safety); this._safety = null; }
    this._detachRec();
    this._stopRecorder();
    this._stopMeter();
    this._releaseStream();
    try { this.audio.pause(); } catch (e) {}
    this.audio.onended = null;
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this.state = "idle";
  };

  global.Checker = Checker;
})(window);
