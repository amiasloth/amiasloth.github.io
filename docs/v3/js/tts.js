/* Zzzpeak TTS — on-device speech synthesis for shadowing practice.
 * Web Speech API: free, offline-capable, no server. iOS ships good
 * de/en voices. Quirks handled here:
 *  - voices load asynchronously (voiceschanged) and lazily on iOS;
 *  - speaking must begin from a user gesture at least once;
 *  - utterances are GC'd mid-speech unless referenced (classic bug);
 *  - always cancel() before speak() or iOS queues forever.
 */
(function (global) {
  "use strict";

  const synth = global.speechSynthesis || null;
  let voices = [];
  let current = null;              // keep a ref so GC can't eat the utterance
  let unlocked = false;

  function refresh() { if (synth) voices = synth.getVoices() || []; }
  if (synth) {
    refresh();
    synth.onvoiceschanged = refresh;
  }

  // iOS requires the FIRST speak() of a session to happen inside a user
  // gesture — a gestureless first utterance silently never starts (verified
  // on device, probe B4: stuck for 5s with no onstart). After one in-gesture
  // speak, gestureless speaks work for the whole session. Self-arm on the
  // first tap anywhere so hands-free TTS is unlocked before it's needed.
  function unlock() {
    if (unlocked || !synth || synth.speaking) return;
    unlocked = true;
    try { synth.speak(new SpeechSynthesisUtterance("")); } catch (e) {}
  }
  if (synth) {
    const arm = () => {
      unlock();
      document.removeEventListener("touchend", arm, true);
      document.removeEventListener("click", arm, true);
    };
    document.addEventListener("touchend", arm, true);
    document.addEventListener("click", arm, true);
  }

  function pickVoice(lang) {
    if (!voices.length) refresh();
    const pre = lang.toLowerCase();
    const cand = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith(pre));
    if (!cand.length) return null;
    // prefer on-device voices (work offline, no lag), then default flag
    return cand.find((v) => v.localService && v.default)
        || cand.find((v) => v.localService)
        || cand[0];
  }

  const TTS = {
    available() { return !!synth; },

    /* Call from any user gesture to unlock gestureless TTS (idempotent). */
    unlock,

    hasVoice(lang) { return !!pickVoice(lang); },

    /* Speak text; resolves when done (or on error/cancel). */
    speak(text, lang, rate) {
      return new Promise((resolve) => {
        if (!synth) { resolve(false); return; }
        synth.cancel();
        const u = new SpeechSynthesisUtterance(text);
        const v = pickVoice(lang);
        if (v) u.voice = v;
        u.lang = (v && v.lang) || lang;
        u.rate = rate || 1;
        u.onend = () => { current = null; resolve(true); };
        u.onerror = () => { current = null; resolve(false); };
        current = u;
        synth.speak(u);
        // safety net: some browsers never fire onend after cancel
        const guard = setInterval(() => {
          if (!synth.speaking && current === u) {
            clearInterval(guard); current = null; resolve(true);
          } else if (current !== u) clearInterval(guard);
        }, 500);
      });
    },

    stop() { if (synth) synth.cancel(); current = null; },

    speaking() { return !!(synth && synth.speaking); },
  };

  global.TTS = TTS;
})(window);
