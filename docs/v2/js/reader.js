/* Zzzpeak v2 reader — focus line + context, per-chunk loop recording,
 * TTS shadowing, starred review deck, hands-free flow.
 * Fetches shared book data from ../data/ (docs/data/ is frozen/shared). */
(function () {
  "use strict";

  const qs = new URLSearchParams(location.search);
  const bookId = qs.get("book");
  const review = qs.get("review") === "1";   // practice starred phrases
  const $ = (id) => document.getElementById(id);

  const el = {
    title: $("btitle"),
    sec: $("sectitle"),
    zone: $("chunkzone"),
    prog: $("progfill"),
    status: $("status"),
    rec: $("recbtn"),
    recLabel: $("reclabel"),
    recIcon: $("recicon"),
    prev: $("prevbtn"),
    next: $("nextbtn"),
    tts: $("ttsbtn"),
    star: $("starbtn"),
    levelBtn: $("levelbtn"),
    sheet: $("levelsheet"),
    levelOpts: $("levelopts"),
    ring: $("levelring"),
    gearBtn: $("gearbtn"),
    settingsSheet: $("settingssheet"),
  };

  const LEVEL_INFO = {
    starter: "1–3 words per phrase — tiny bites",
    beginner: "2–5 words per phrase",
    intermediate: "up to 8 words per phrase",
    advanced: "up to 12 words per phrase",
  };

  let meta = null;       // entry from books.json
  let book = null;       // loaded book json (null in review mode)
  let flat = [];         // [{t, e?, cont?, sec, secTitle, i, lv?, sentStart?, sentEnd?}]
  let idx = 0;
  let level = null;
  let sentenceStep = null;  // null | {start, end, t, e} — virtual full-sentence step

  // ---------------- settings ----------------

  const prefs = {
    hideText: Store.getPref("hideText", false),
    autoStop: Store.getPref("autoStop", true),
    after: Store.getPref("after", "repeat"),      // repeat | next | stop
    recordOnNext: Store.getPref("recordOnNext", false),
    ttsFirst: Store.getPref("ttsFirst", false),
    ttsRate: Store.getPref("ttsRate", 1),
    sentenceReplay: Store.getPref("sentenceReplay", false),
    sentenceShowText: Store.getPref("sentenceShowText", true),
    abCompare: Store.getPref("abCompare", false),
  };

  // ---------------- data ----------------

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " -> " + r.status);
    return r.json();
  }

  async function init() {
    if (!bookId) { fail("No book selected."); return; }
    let index;
    try { index = await fetchJSON("../data/books.json"); }
    catch (e) { fail("Could not load the book list."); return; }
    meta = (index.books || []).find((b) => b.id === bookId);
    if (!meta) { fail("Unknown book: " + bookId); return; }
    el.title.textContent = (review ? "★ " : "") + meta.title;
    level = Store.getLevel(bookId, meta.levels.includes("beginner")
      ? "beginner" : meta.levels[0]);
    if (!meta.levels.includes(level)) level = meta.levels[0];
    if (!TTS.available()) el.tts.style.display = "none";
    buildSettingsSheet();
    if (review) {
      el.levelBtn.style.display = "none";
      loadDeck();
    } else {
      buildLevelSheet();
      await loadLevel(level, true);
    }
    bind();
  }

  /* group flat[] into sentences: a run of `cont` chunks ending at the
   * first chunk without `cont`. Stores sentStart/sentEnd on each item.
   * Skipped in review mode — the starred deck has no reliable `cont`
   * context, so those flat items never get these fields. */
  function computeSentences() {
    let start = 0;
    for (let k = 0; k < flat.length; k++) {
      if (!flat[k].cont) {
        for (let j = start; j <= k; j++) {
          flat[j].sentStart = start;
          flat[j].sentEnd = k;
        }
        start = k + 1;
      }
    }
    if (start < flat.length) {
      for (let j = start; j < flat.length; j++) {
        flat[j].sentStart = start;
        flat[j].sentEnd = flat.length - 1;
      }
    }
  }

  function buildSentenceStep(start, end) {
    let t = "", e = "";
    for (let k = start; k <= end; k++) {
      t += (t ? " " : "") + flat[k].t;
      if (flat[k].e) e += flat[k].e;
    }
    return { start, end, t: t.replace(/\s+/g, " ").trim(), e };
  }

  /* current text/emoji: the virtual sentence step's joined values while
   * active, otherwise the current chunk's. Route all TTS/record access
   * through these so the step is a drop-in replacement for flat[idx]. */
  function curText() { return sentenceStep ? sentenceStep.t : flat[idx].t; }
  function curEmoji() { return sentenceStep ? sentenceStep.e : flat[idx].e; }

  /* review mode: the deck is every starred phrase, across levels */
  function loadDeck() {
    sentenceStep = null;
    flat = [];
    meta.levels.forEach((lv) => {
      Store.getStars(bookId, lv).forEach((s) => {
        flat.push({ t: s.t, e: s.e, i: s.i, lv,
                    secTitle: "Starred · " + lv });
      });
    });
    idx = Math.min(idx, Math.max(0, flat.length - 1));
    if (!flat.length) {
      fail("No starred phrases yet — tap ☆ while reading to collect the hard ones here.");
      el.prog.style.width = "0%";
      return;
    }
    render();
  }

  async function loadLevel(lv, restore) {
    const prevFrac = flat.length ? idx / flat.length : null;
    try {
      book = await fetchJSON("../data/" + meta.lang + "/" + bookId + "_" + lv + ".json");
    } catch (e) {
      fail("Could not load “" + meta.title + "” (" + lv + ").");
      return;
    }
    level = lv;
    Store.setLevel(bookId, lv);
    sentenceStep = null;
    flat = [];
    book.sections.forEach((s, si) => {
      s.chunks.forEach((c) => {
        flat.push({ t: c.t, e: c.e, cont: c.cont, sec: si,
                    secTitle: s.title, i: flat.length });
      });
    });
    computeSentences();
    if (restore) {
      const p = Store.getProgress(bookId, lv);
      idx = p ? Math.min(p.chunk, flat.length - 1) : 0;
    } else if (prevFrac !== null) {
      idx = Math.min(Math.round(prevFrac * flat.length), flat.length - 1);
    } else {
      idx = 0;
    }
    el.levelBtn.textContent = lv[0].toUpperCase() + lv.slice(1);
    render();
  }

  function fail(msg) {
    el.zone.querySelectorAll(".chunk").forEach((n) => n.remove());
    const old = el.zone.querySelector(".empty");
    if (old) old.remove();
    const d = document.createElement("div");
    d.className = "empty";
    d.textContent = msg;
    el.zone.appendChild(d);
  }

  // ---------------- rendering ----------------

  function chunkNode(c, cls) {
    const d = document.createElement("div");
    d.className = "chunk " + cls;
    if (cls === "now" && c.e) {
      const em = document.createElement("span");
      em.className = "emoji";
      em.textContent = c.e;
      d.appendChild(em);
    }
    const txt = document.createElement("span");
    txt.className = "txt";
    txt.textContent = c.t;
    if (c.cont) {
      const dot = document.createElement("span");
      dot.className = "cont-dot";
      dot.textContent = " ›";
      txt.appendChild(dot);
    }
    d.appendChild(txt);
    return d;
  }

  function render() {
    if (!flat.length) { fail("This book has no content."); return; }
    const c = flat[idx];
    el.sec.textContent = c.secTitle || meta.title;
    const old = el.zone.querySelector(".empty");
    if (old) old.remove();
    el.zone.querySelectorAll(".chunk").forEach((n) => n.remove());
    const frag = document.createDocumentFragment();
    if (sentenceStep) {
      // context rows are blank during the virtual sentence step — the
      // individual chunks it merges are already behind us.
      for (let o = -2; o <= 2; o++) {
        if (o === 0) {
          frag.appendChild(chunkNode({ t: sentenceStep.t, e: sentenceStep.e }, "now"));
        } else {
          const pad = document.createElement("div");
          pad.className = "chunk ctx" + (Math.abs(o) === 2 ? " far" : "");
          pad.innerHTML = "&nbsp;";
          frag.appendChild(pad);
        }
      }
    } else {
      for (let o = -2; o <= 2; o++) {
        const j = idx + o;
        if (j < 0 || j >= flat.length) {
          const pad = document.createElement("div");
          pad.className = "chunk ctx" + (Math.abs(o) === 2 ? " far" : "");
          pad.innerHTML = "&nbsp;";
          frag.appendChild(pad);
          continue;
        }
        const cls = o === 0 ? "now" : "ctx" + (Math.abs(o) === 2 ? " far" : "");
        frag.appendChild(chunkNode(flat[j], cls));
      }
    }
    el.zone.appendChild(frag);
    el.prog.style.width = (100 * (idx + 1) / flat.length).toFixed(2) + "%";
    // the sentence step is virtual — position stays saved at the last
    // real chunk (idx) until the user moves past it.
    if (!review && !sentenceStep) Store.setProgress(bookId, level, c.sec, idx, flat.length);
    if (sentenceStep) {
      el.star.style.display = "none";
    } else {
      el.star.style.display = "";
      updateStar();
    }
  }

  function veil(on) {
    el.zone.classList.toggle("veil", !!on);
  }

  // ---------------- stars ----------------

  function updateStar() {
    const starred = review ? true
      : Store.isStarred(bookId, level, idx);
    el.star.textContent = starred ? "★" : "☆";
  }

  function toggleStar() {
    if (!flat.length || sentenceStep) return;   // star button is hidden during the step
    const c = flat[idx];
    if (review) {
      Store.toggleStar(bookId, c.lv, { i: c.i, t: c.t, e: c.e });  // unstar
      flat.splice(idx, 1);
      rec.halt();
      if (!flat.length) {
        fail("Deck cleared — nice work.");
        el.prog.style.width = "0%";
        return;
      }
      idx = Math.min(idx, flat.length - 1);
      render();
    } else {
      const on = Store.toggleStar(bookId, level, { i: idx, t: c.t, e: c.e });
      updateStar();
      status(on ? "Starred — practice it later from the library." : "");
    }
  }

  // ---------------- TTS ----------------

  function speakCurrent() {
    if (!flat.length || !TTS.available()) return Promise.resolve(false);
    rec.halt();                      // never TTS into an open take
    status("");
    return TTS.speak(curText(), meta.lang, prefs.ttsRate);
  }

  /* begin a take, optionally hearing the phrase first (shadowing).
   * During the sentence step, ttsFirst is ignored: that step has its own
   * fixed order (own take, then TTS) so the learner can self-correct —
   * see onPlayEnd below. */
  function startTake() {
    if (!sentenceStep && prefs.ttsFirst && TTS.available()) {
      speakCurrent().then(() => rec.record());
    } else {
      rec.record();
    }
  }

  // ---------------- recorder ----------------

  /* the `after` pref (repeat/next/stop), run once all playback for the
   * current step (own take, plus TTS during the sentence step) is done. */
  function runAfter() {
    if (prefs.after === "repeat") startTake();
    else if (prefs.after === "next") {
      if (go(1, { keepMic: true })) startTake();
      else status(review ? "End of the deck — well done!" : "End of the book — well read!");
    }
    // "stop": stay idle
  }

  const rec = new LoopRecorder({
    autoStop: prefs.autoStop,
    onState: (s) => {
      el.rec.className = "recbtn " + (s === "idle" ? "" : s);
      if (s === "recording") { el.recIcon.textContent = "◼"; el.recLabel.textContent = "stop"; }
      else if (s === "playing") { el.recIcon.textContent = "▶"; el.recLabel.textContent = "listen"; }
      else { el.recIcon.textContent = "●"; el.recLabel.textContent = "record"; }
      if (s !== "recording") veil(false);   // reveal during playback / idle
      status(s === "recording"
        ? (prefs.autoStop ? "Read the phrase aloud — pausing ends the take."
                          : "Read the phrase aloud…")
        : s === "playing" ? afterHint()
        : "");
    },
    beforePlay: () => {
      // sentence step has its own fixed order (own take, then TTS —
      // see onPlayEnd below), so skip the ab-compare pre-play here to
      // avoid hearing TTS twice / out of order.
      if (sentenceStep || !prefs.abCompare || !TTS.available()) return Promise.resolve();
      status("Listen…");
      return TTS.speak(curText(), meta.lang, prefs.ttsRate);
    },
    onError: (msg) => { veil(false); status(msg, true); },
    onSpeechStart: () => {
      // during the sentence step, hideText only veils if sentenceShowText is off
      const hide = sentenceStep ? (prefs.hideText && !prefs.sentenceShowText) : prefs.hideText;
      if (hide) veil(true);
    },
    onPlayEnd: () => {
      // Sentence step: hear your own take (just finished), then hear the
      // correct TTS reading, THEN apply the after-playback pref — so the
      // learner can notice what they got wrong before moving on.
      if (sentenceStep) {
        const step = sentenceStep;
        speakCurrent().then(() => {
          if (sentenceStep !== step) return;   // step left/changed during TTS
          runAfter();
        });
        return;
      }
      runAfter();
    },
    onLevel: (v) => {
      el.ring.style.opacity = v > 0.02 ? Math.min(1, v * 3).toFixed(2) : 0;
      el.ring.style.transform = "scale(" + (1 + v * 0.25).toFixed(3) + ")";
    },
  });

  function afterHint() {
    return prefs.after === "repeat" ? "Playing back — recording starts again after."
      : prefs.after === "next" ? "Playing back — next phrase starts after."
      : "Playing back.";
  }

  function status(msg, isErr) {
    el.status.textContent = msg;
    el.status.className = "statusline" + (isErr ? " err" : "");
  }

  // ---------------- navigation ----------------

  // Returns true if the navigation moved somewhere (a real chunk or the
  // virtual sentence step), false if there was nowhere to go (used by the
  // hands-free "next" flow to know whether to keep going or stop).
  function go(delta, opts) {
    opts = opts || {};
    TTS.stop();

    // Leaving an active sentence step: next continues after it, prev
    // returns to its last (real) chunk. Either way the step ends.
    if (sentenceStep) {
      const step = sentenceStep;
      if (delta > 0) {
        const n = step.end + 1;
        if (n >= flat.length) return false;
        sentenceStep = null;
        if (opts.keepMic || prefs.recordOnNext) rec.halt();
        else rec.reset();
        idx = n;
        render();
        if (!opts.keepMic && prefs.recordOnNext) { rec._unlock(); startTake(); }
        return true;
      } else {
        sentenceStep = null;
        if (opts.keepMic || prefs.recordOnNext) rec.halt();
        else rec.reset();
        idx = step.end;
        render();
        return true;
      }
    }

    // Leaving the last chunk of a multi-chunk sentence (advancing forward):
    // insert the virtual whole-sentence step instead of moving idx.
    if (delta > 0 && !review && prefs.sentenceReplay) {
      const c = flat[idx];
      if (c && c.sentEnd === idx && c.sentEnd > c.sentStart) {
        if (opts.keepMic || prefs.recordOnNext) rec.halt();
        else rec.reset();
        sentenceStep = buildSentenceStep(c.sentStart, c.sentEnd);
        render();
        if (!opts.keepMic && prefs.recordOnNext) { rec._unlock(); startTake(); }
        return true;
      }
    }

    const n = idx + delta;
    if (n < 0 || n >= flat.length) return false;
    if (opts.keepMic || prefs.recordOnNext) rec.halt();  // keep mic session
    else rec.reset();
    idx = n;
    render();
    // one-tap reading: advancing starts the next take immediately
    if (!opts.keepMic && prefs.recordOnNext && delta > 0) {
      rec._unlock();
      startTake();
    }
    return true;
  }

  function bind() {
    el.next.addEventListener("click", () => go(1));
    el.prev.addEventListener("click", () => go(-1));
    document.querySelector(".tapzone.right").addEventListener("click", () => go(1));
    document.querySelector(".tapzone.left").addEventListener("click", () => go(-1));
    el.rec.addEventListener("click", () => {
      if (!LoopRecorder.isSupported()) {
        status("Recording is not supported in this browser.", true);
        return;
      }
      if (rec.state === "recording") { rec.toggle(); return; }
      rec._unlock();               // inside the tap: allow later playback
      startTake();
    });
    el.tts.addEventListener("click", () => { speakCurrent(); });
    el.star.addEventListener("click", toggleStar);

    // swipe
    let x0 = null, y0 = null;
    el.zone.addEventListener("touchstart", (e) => {
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    }, { passive: true });
    el.zone.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      const dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
    }, { passive: true });

    document.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "r" || e.key === "R") rec.toggle();
      else if (e.key === "l" || e.key === "L") speakCurrent();
      else if (e.key === "s" || e.key === "S") toggleStar();
    });

    el.levelBtn.addEventListener("click", () => el.sheet.classList.add("open"));
    el.sheet.addEventListener("click", (e) => {
      if (e.target === el.sheet) el.sheet.classList.remove("open");
    });
    el.gearBtn.addEventListener("click", () => el.settingsSheet.classList.add("open"));
    el.settingsSheet.addEventListener("click", (e) => {
      if (e.target === el.settingsSheet) el.settingsSheet.classList.remove("open");
    });

    // release mic when the page goes away / is hidden
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { rec.reset(); TTS.stop(); }
    });
    window.addEventListener("pagehide", () => { rec.reset(); TTS.stop(); });
  }

  // ---------------- sheets ----------------

  function buildLevelSheet() {
    el.levelOpts.innerHTML = "";
    meta.levels.forEach((lv) => {
      const b = document.createElement("button");
      b.className = "opt" + (lv === level ? " sel" : "");
      b.innerHTML = lv[0].toUpperCase() + lv.slice(1) +
        "<small>" + (LEVEL_INFO[lv] || "") + "</small>";
      b.addEventListener("click", async () => {
        el.sheet.classList.remove("open");
        if (lv !== level) {
          rec.reset();
          await loadLevel(lv, false);
          buildLevelSheet();
        }
      });
      el.levelOpts.appendChild(b);
    });
  }

  function setPref(name, value) {
    prefs[name] = value;
    Store.setPref(name, value);
    if (name === "autoStop") rec.autoStop = value;
    buildSettingsSheet();
  }

  function buildSettingsSheet() {
    const box = $("settingsopts");
    box.innerHTML = "";

    const toggle = (label, hint, name) => {
      const b = document.createElement("button");
      b.className = "opt" + (prefs[name] ? " sel" : "");
      b.innerHTML = (prefs[name] ? "✓ " : "") + label + "<small>" + hint + "</small>";
      b.addEventListener("click", () => setPref(name, !prefs[name]));
      box.appendChild(b);
    };
    const heading = (t) => {
      const h = document.createElement("h3");
      h.textContent = t;
      h.style.marginTop = "16px";
      box.appendChild(h);
    };

    toggle("Auto-stop when you pause", "No second tap: about a second of silence ends the take and playback starts.", "autoStop");
    toggle("Hide text while you speak", "The phrase disappears the moment your voice starts (emoji hint stays) and comes back for playback — recall practice.", "hideText");
    toggle("Record when you go to the next phrase", "Tapping next immediately starts the next take.", "recordOnNext");

    heading("Sentence replay");
    toggle("Read the whole sentence", "After the last piece of a sentence, read the complete sentence once.", "sentenceReplay");
    if (prefs.sentenceReplay) {
      toggle("Show text for full sentences", "Even when chunk text is hidden, the complete-sentence step stays visible.", "sentenceShowText");
    }

    if (TTS.available()) {
      heading("Listening (on-device voice)");
      toggle("Hear the phrase first", "Shadowing: the phrase is spoken aloud, then recording starts — imitate what you heard.", "ttsFirst");
      toggle("Compare with the voice", "After each take: hear your own recording, then the phrase spoken, back to back.", "abCompare");
      const rates = [[0.6, "Slow"], [0.8, "Relaxed"], [1, "Normal"]];
      const row = document.createElement("div");
      rates.forEach(([v, label]) => {
        const b = document.createElement("button");
        b.className = "opt rateopt" + (prefs.ttsRate === v ? " sel" : "");
        b.textContent = label;
        b.addEventListener("click", () => setPref("ttsRate", v));
        row.appendChild(b);
      });
      row.className = "raterow";
      box.appendChild(row);
    }

    heading("After playback");
    [["repeat", "Repeat this phrase", "Record the same phrase again — the classic loop."],
     ["next", "Go to the next phrase", "Hands-free flow: advance and start recording automatically."],
     ["stop", "Stop", "Wait for a tap."]].forEach(([val, label, hint]) => {
      const b = document.createElement("button");
      b.className = "opt" + (prefs.after === val ? " sel" : "");
      b.innerHTML = label + "<small>" + hint + "</small>";
      b.addEventListener("click", () => setPref("after", val));
      box.appendChild(b);
    });
  }

  init();
})();
