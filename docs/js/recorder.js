/* Zzzpeak LoopRecorder
 *
 * Record -> stop -> playback -> auto re-record, forever, until reset.
 * Built to survive iOS Safari, which is where naive versions break:
 *
 *  - getUserMedia only works over HTTPS and must start from a user tap.
 *  - iOS Safari's MediaRecorder produces audio/mp4 (AAC), not webm,
 *    so the mime type is negotiated, never assumed.
 *  - Old iOS (<14.3) has no MediaRecorder at all -> WAV fallback via
 *    Web Audio (ScriptProcessor), which works everywhere.
 *  - audio.play() outside a user gesture is blocked, so the ONE shared
 *    <audio> element is "unlocked" with a silent clip during the tap
 *    that starts recording; afterwards we may freely swap its src.
 *  - Stopping mic tracks between loops makes iOS flap its audio session
 *    (volume ducking, permission re-prompts), so the stream is kept
 *    alive for the whole loop session and released only on reset.
 */
(function (global) {
  "use strict";

  // 0.05s of silence as a WAV data URI - used to unlock the audio element
  const SILENCE =
    "data:audio/wav;base64,UklGRkQDAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YSADAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" +
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==";

  function pickMime() {
    if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported)
      return null;
    const types = [
      "audio/mp4",                 // iOS Safari
      "audio/webm;codecs=opus",    // Chrome / Firefox / Edge
      "audio/webm",
      "audio/ogg;codecs=opus",
    ];
    for (const t of types) {
      try { if (MediaRecorder.isTypeSupported(t)) return t; } catch (e) {}
    }
    return "";                     // let the browser choose
  }

  // ---- WAV fallback (no MediaRecorder): ScriptProcessor -> 16-bit PCM
  function WavCapture(stream) {
    const Ctx = global.AudioContext || global.webkitAudioContext;
    this.ctx = new Ctx();
    this.source = this.ctx.createMediaStreamSource(stream);
    this.proc = this.ctx.createScriptProcessor(4096, 1, 1);
    this.buffers = [];
    this.sampleRate = this.ctx.sampleRate;
    this.proc.onaudioprocess = (e) => {
      this.buffers.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    this.source.connect(this.proc);
    this.proc.connect(this.ctx.destination); // required by some browsers
  }
  WavCapture.prototype.stop = function () {
    this.proc.disconnect();
    this.source.disconnect();
    const len = this.buffers.reduce((n, b) => n + b.length, 0);
    const pcm = new Float32Array(len);
    let off = 0;
    for (const b of this.buffers) { pcm.set(b, off); off += b.length; }
    this.buffers = [];
    const blob = encodeWav(pcm, this.sampleRate);
    const ctx = this.ctx;
    this.ctx = null;
    if (ctx && ctx.state !== "closed") ctx.close().catch(() => {});
    return blob;
  };

  function encodeWav(samples, sampleRate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const wStr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    wStr(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true);
    wStr(8, "WAVE"); wStr(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    wStr(36, "data"); v.setUint32(40, samples.length * 2, true);
    let o = 44;
    for (let i = 0; i < samples.length; i++, o += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  /* states: idle -> recording -> playing -> recording -> ... -> idle */
  function LoopRecorder(opts) {
    opts = opts || {};
    this.loop = opts.loop !== false;
    this.onState = opts.onState || function () {};
    this.onError = opts.onError || function () {};
    this.onLevel = opts.onLevel || null;   // mic level meter callback (0..1)
    this.state = "idle";
    this.stream = null;
    this.rec = null;          // MediaRecorder or WavCapture
    this.chunks = [];
    this.mime = pickMime();   // null => WAV fallback
    this.url = null;
    this.stopping = false;

    // ONE audio element for all playback, unlocked on first user tap
    this.audio = new Audio();
    this.audio.setAttribute("playsinline", "");
    this.audio.preload = "auto";
    this._unlocked = false;

    this._levelTimer = null;
    this._analyser = null;
    this._levelCtx = null;
  }

  LoopRecorder.isSupported = function () {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  };

  LoopRecorder.prototype._set = function (s) {
    this.state = s;
    this.onState(s);
  };

  LoopRecorder.prototype._unlock = function () {
    // Must run synchronously inside the user's tap.
    if (this._unlocked) return;
    this._unlocked = true;
    this.audio.src = SILENCE;
    const p = this.audio.play();
    if (p && p.catch) p.catch(() => { this._unlocked = false; });
  };

  LoopRecorder.prototype._startLevelMeter = function () {
    if (!this.onLevel || this._analyser) return;
    try {
      const Ctx = global.AudioContext || global.webkitAudioContext;
      this._levelCtx = new Ctx();
      const src = this._levelCtx.createMediaStreamSource(this.stream);
      this._analyser = this._levelCtx.createAnalyser();
      this._analyser.fftSize = 512;
      src.connect(this._analyser);
      const data = new Uint8Array(this._analyser.frequencyBinCount);
      const tick = () => {
        if (!this._analyser) return;
        this._analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (let i = 0; i < data.length; i++)
          peak = Math.max(peak, Math.abs(data[i] - 128) / 128);
        this.onLevel(this.state === "recording" ? peak : 0);
        this._levelTimer = requestAnimationFrame(tick);
      };
      tick();
    } catch (e) { /* meter is decorative; never fatal */ }
  };

  LoopRecorder.prototype._stopLevelMeter = function () {
    if (this._levelTimer) cancelAnimationFrame(this._levelTimer);
    this._levelTimer = null;
    this._analyser = null;
    if (this._levelCtx && this._levelCtx.state !== "closed")
      this._levelCtx.close().catch(() => {});
    this._levelCtx = null;
    if (this.onLevel) this.onLevel(0);
  };

  /* Public: call from a user tap. idle -> record; playing -> re-record;
   * recording -> stop & play. */
  LoopRecorder.prototype.toggle = function () {
    this._unlock();
    if (this.state === "recording") this.stopAndPlay();
    else this.record();
  };

  LoopRecorder.prototype.record = async function () {
    if (this.state === "recording") return;
    this._stopPlayback();
    try {
      if (!this.stream || !this.stream.active) {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
      }
    } catch (err) {
      this._set("idle");
      this.onError(
        err && (err.name === "NotAllowedError" || err.name === "SecurityError")
          ? "Microphone access was denied. Allow the microphone in your browser settings (the page must be served over https)."
          : "Could not open the microphone: " + (err && err.message ? err.message : err)
      );
      return;
    }
    this._startLevelMeter();
    this.chunks = [];
    try {
      if (this.mime === null) {
        this.rec = new WavCapture(this.stream);
      } else {
        this.rec = new MediaRecorder(
          this.stream, this.mime ? { mimeType: this.mime } : undefined);
        this.rec.ondataavailable = (e) => {
          if (e.data && e.data.size) this.chunks.push(e.data);
        };
      }
    } catch (e) {
      // MediaRecorder constructor failed (odd Safari builds): WAV fallback
      this.mime = null;
      this.rec = new WavCapture(this.stream);
    }
    if (this.rec instanceof WavCapture) { /* already capturing */ }
    else this.rec.start();
    this._set("recording");
  };

  LoopRecorder.prototype.stopAndPlay = function () {
    if (this.state !== "recording" || this.stopping) return;
    this.stopping = true;
    const finish = (blob) => {
      this.stopping = false;
      if (this.url) URL.revokeObjectURL(this.url);
      if (!blob || !blob.size) { this._set("idle"); return; }
      this.url = URL.createObjectURL(blob);
      this._play();
    };
    if (this.rec instanceof WavCapture) {
      finish(this.rec.stop());
    } else {
      const rec = this.rec;
      rec.onstop = () => {
        finish(new Blob(this.chunks, { type: rec.mimeType || this.mime || "" }));
      };
      try { rec.stop(); } catch (e) { this.stopping = false; this._set("idle"); }
    }
  };

  LoopRecorder.prototype._play = function () {
    const a = this.audio;
    a.src = this.url;
    a.onended = () => {
      if (this.state !== "playing") return;
      if (this.loop) this.record();      // the loop: hear it, say it again
      else this._set("idle");
    };
    const p = a.play();
    this._set("playing");
    if (p && p.catch) {
      p.catch(() => {
        // Autoplay blocked (unlock failed): stay stopped but keep the take.
        this._set("idle");
        this.onError("Tap Record again to hear the playback — this browser blocked automatic playback.");
      });
    }
  };

  LoopRecorder.prototype._stopPlayback = function () {
    this.audio.onended = null;
    try { this.audio.pause(); } catch (e) {}
  };

  /* Public: full stop; releases the microphone. */
  LoopRecorder.prototype.reset = function () {
    this._stopPlayback();
    if (this.state === "recording" && this.rec) {
      try {
        if (this.rec instanceof WavCapture) this.rec.stop();
        else { this.rec.onstop = null; this.rec.ondataavailable = null; this.rec.stop(); }
      } catch (e) {}
    }
    this.rec = null;
    this.stopping = false;
    this._stopLevelMeter();
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.url) { URL.revokeObjectURL(this.url); this.url = null; }
    this._set("idle");
  };

  /* Replay the last take once (no re-record). */
  LoopRecorder.prototype.replay = function () {
    if (!this.url || this.state === "recording") return;
    this._unlock();
    const a = this.audio;
    a.src = this.url;
    a.onended = () => this._set("idle");
    this._set("playing");
    const p = a.play();
    if (p && p.catch) p.catch(() => this._set("idle"));
  };

  LoopRecorder.prototype.hasTake = function () { return !!this.url; };

  global.LoopRecorder = LoopRecorder;
})(window);
