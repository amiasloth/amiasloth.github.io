/* Zzzpeak v3 reader — focus line + context, per-chunk loop recording,
 * TTS shadowing, starred review deck, hands-free flow.
 * v2 behavior on v3 data: one book file per book (../data3/), tokens +
 * per-level cut positions; chunks are derived at load by js/data3.js.
 * Progress is sentence-keyed (id, occ) per the pinned v3 schema. */
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
    studyBtn: $("studybtn"),
    studySheet: $("studysheet"),
    tocSheet: $("tocsheet"),
  };

  const LEVEL_INFO = {
    starter: "1–3 words per phrase — tiny bites",
    beginner: "2–5 words per phrase",
    intermediate: "up to 8 words per phrase",
    advanced: "up to 12 words per phrase",
  };

  let meta = null;       // entry from books.json
  let book = null;       // loaded book json (null in review mode)
  let gloss = null;      // loaded gloss json (null in review mode / on miss)
  let flat = [];         // [{t, e?, cont?, sec, secTitle, i, lv?, sentStart?, sentEnd?}]
  let idx = 0;
  let level = null;
  let sentenceStep = null;  // null | {start, end, t, e} — virtual full-sentence step

  // ---- Check mode (Phase 04) ----
  let checker = null;       // Checker instance (only if SpeechRecognition exists)
  let checkRetry = 0;       // failed attempts on the current phrase (cap 3)
  let checkHidden = false;  // recognition service unavailable this session
  let checkDiffShown = false;
  let checkAuto = false;    // current check take was auto-started (no user gesture)
  let checkSilent = 0;      // consecutive silent takes (hands-free re-arm cap)

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
    checkMode: Store.getPref("checkMode", false),
    studyWords: Store.getPref("studyWords", true),   // mark study words
    orthModern: Store.getPref("orthModern", false),  // modernised spelling
  };

  let bookHasOrth = false;   // any sentence carries an orth map

  // ---------------- data ----------------

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " -> " + r.status);
    return r.json();
  }

  async function init() {
    if (!bookId) { fail("No book selected."); return; }
    let index;
    try { index = await fetchJSON("../data3/books.json"); }
    catch (e) { fail("Could not load the book list."); return; }
    meta = (index.books || []).find((b) => b.id === bookId);
    if (!meta) { fail("Unknown book: " + bookId); return; }
    el.title.textContent = (review ? "★ " : "") + meta.title;
    level = Store.getLevel(bookId, meta.levels.includes("beginner")
      ? "beginner" : meta.levels[0]);
    if (!meta.levels.includes(level)) level = meta.levels[0];
    if (!TTS.available()) el.tts.style.display = "none";
    if (Checker.isSupported()) {
      checker = new Checker({
        lang: meta.lang,
        autoStop: prefs.autoStop,   // VAD endpointing: ~1s silence ends the take
        onState: onCheckState,
        onInterim: onCheckInterim,
        onResult: onCheckResult,
        onError: onCheckError,
        onSpeechStart: () => {
          // The previous take's miss marks stay visible while we wait — only
          // clear them once you actually start speaking again.
          clearCheckDiff();
          // Hide the text only once you actually start speaking (like the
          // loop's VAD) — NOT the instant listening begins, so you can read.
          const hide = sentenceStep ? (prefs.hideText && !prefs.sentenceShowText) : prefs.hideText;
          if (hide) veil(true);
        },
        onLevel: (v) => {
          el.ring.style.opacity = v > 0.02 ? Math.min(1, v * 3).toFixed(2) : 0;
          el.ring.style.transform = "scale(" + (1 + v * 0.25).toFixed(3) + ")";
        },
      });
    }
    buildSettingsSheet();
    if (review) {
      el.levelBtn.style.display = "none";
      el.studyBtn.style.display = "none";
      loadDeck();
    } else {
      // v3: ONE file per book, fetched once — level switches re-derive
      // chunks from it without another fetch.
      try {
        book = await fetchJSON("../data3/" + meta.lang + "/" + bookId + ".json");
      } catch (e) {
        fail("Could not load “" + meta.title + "”.");
        return;
      }
      // gloss is optional — without it word taps and study lists are off
      try { gloss = await fetchJSON("../data3/gloss/" + bookId + ".json"); }
      catch (e) { gloss = null; }
      if (!gloss) el.studyBtn.style.display = "none";
      bookHasOrth = book.sections.some(
        (s) => s.sentences.some((x) => x.orth));
      buildLevelSheet();
      loadLevel(level, true);
    }
    bind();
    paintIdleButton();   // reflect persisted Check mode on the record button
  }

  /* Sentence grouping (sentStart/sentEnd) comes straight from the data3
   * flatten — v3 sentences are explicit, no `cont`-run reconstruction.
   * Review-mode deck items never get these fields (as in v2). */

  function buildSentenceStep(start, end) {
    let t = "";
    for (let k = start; k <= end; k++) t += (t ? " " : "") + flat[k].t;
    // all chunks of the step share one sentence — carry its token range
    // so the step gets the same verb/name rendering as a normal chunk
    const sent = flat[start].sent, a = flat[start].a, b = flat[end].b;
    return { start, end, t: t.replace(/\s+/g, " ").trim(),
             e: gloss && sent ? Data3.chunkEmoji(gloss, sent, a, b) : "",
             sent, a, b };
  }

  /* current text/emoji: the virtual sentence step's joined values while
   * active, otherwise the current chunk's. Route all TTS/record access
   * through these so the step is a drop-in replacement for flat[idx]. */
  function curText() { return sentenceStep ? sentenceStep.t : flat[idx].t; }
  // Word count of the current reference text — long takes (the full-sentence
  // step) get wider stop/safety windows; chunks stay on the tuned defaults.
  function curWords() { return curText().trim().split(/\s+/).filter(Boolean).length; }
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

  function loadLevel(lv, restore) {
    // v3: no per-level fetch — re-derive the chunk list from the already
    // loaded book file (levels are cut sets into the same tokens).
    const prevPos = flat.length
      ? { sid: flat[idx].sid, occ: flat[idx].occ, ci: 0 } : null;
    const prevFrac = flat.length ? idx / flat.length : null;
    level = lv;
    Store.setLevel(bookId, lv);
    sentenceStep = null;
    flat = Data3.flatten(book, lv);
    if (restore) {
      // sentence-keyed resume; fraction fallback if the sentence is gone
      const p = Store.getProgress(bookId);
      const at = p ? Data3.findPosition(flat, p) : -1;
      idx = at >= 0 ? at
        : p && p.total
          ? Math.min(Math.round((p.flatIdx || 0) / p.total * flat.length),
                     Math.max(0, flat.length - 1))
          : 0;
    } else if (prevPos) {
      // level switch: stay on the same sentence
      const at = Data3.findPosition(flat, prevPos);
      idx = at >= 0 ? at
        : Math.min(Math.round(prevFrac * flat.length),
                   Math.max(0, flat.length - 1));
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

  // UPOS → span class. AUX counts as a verb: German verb brackets
  // ("hat … gemacht", "wird … sehen") lose their frame without it.
  const POS_CLS = { VERB: "vb", AUX: "vb" };

  // Token indices covered by named-entity spans ([start, end, label],
  // end-exclusive — see the v3 schema).
  function entMask(sent) {
    if (!sent.ents || !sent.ents.length) return null;
    const m = new Set();
    sent.ents.forEach((sp) => { for (let k = sp[0]; k < sp[1]; k++) m.add(k); });
    return m;
  }

  /* Per-token spans for the slice [a, b) of a sentence: verbs get .vb
   * (POS colouring), entity tokens get .ent (subtle name rendering).
   * Trailing space stays INSIDE each span so the plain-text fallback and
   * renderDiff (which rebuilds .txt from whitespace-split text) agree.
   * On the focus line (`now`, gloss loaded): word tokens get data-k so
   * a tap can look them up, and — when the "Mark study words" pref is on
   * — tokens whose lemma is in the sentence's study list get .sw, a very
   * subtle underline pointing out the words worth a tap. */
  function tokenSpans(sent, a, b, now) {
    const frag = document.createDocumentFragment();
    const ents = entMask(sent);
    const tappable = now && !!gloss;
    let study = null;
    if (tappable && prefs.studyWords && gloss.study_by_sent &&
        Object.prototype.hasOwnProperty.call(gloss.study_by_sent, sent.id)) {
      study = new Set(gloss.study_by_sent[sent.id]);
    }
    const orth = prefs.orthModern && sent.orth;   // display toggle
    for (let k = a; k < b; k++) {
      const sp = document.createElement("span");
      let t = (orth && sent.orth[String(k)]) || sent.toks[k];
      if (k + 1 < b && sent.sp.charAt(k) === "1") t += " ";
      sp.textContent = t;
      let cls = (sent.pos && POS_CLS[sent.pos[k]]) || "";
      if (ents && ents.has(k)) cls += (cls ? " " : "") + "ent";
      if (tappable && /[\p{L}\p{N}]/u.test(sent.toks[k])) {
        sp.dataset.k = k;
        if (study && study.size) {
          const r = Data3.glossLookup(gloss, sent, k);
          if (!r.isEnt && r.lemma && study.has(r.lemma))
            cls += (cls ? " " : "") + "sw";
        }
      }
      if (cls) sp.className = cls;
      frag.appendChild(sp);
    }
    return frag;
  }

  function chunkNode(c, cls) {
    const d = document.createElement("div");
    d.className = "chunk " + cls;
    // chunk emoji is computed at runtime from the gloss (rarest glossed
    // word with an emoji) and cached on the item — stars and curEmoji()
    // then see the same value the reader showed
    if (cls === "now" && c.e === undefined)
      c.e = gloss && c.sent ? Data3.chunkEmoji(gloss, c.sent, c.a, c.b) : "";
    if (cls === "now" && c.e) {
      const em = document.createElement("span");
      em.className = "emoji";
      em.textContent = c.e;
      d.appendChild(em);
    }
    const txt = document.createElement("span");
    txt.className = "txt";
    if (c.sent) txt.appendChild(tokenSpans(c.sent, c.a, c.b, cls === "now"));
    else txt.textContent = c.t;        // review-deck items: plain text
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
    hideGloss();
    if (!flat.length) { fail("This book has no content."); return; }
    const c = flat[idx];
    el.sec.textContent = (c.secTitle || meta.title) + (review ? "" : " ▾");
    const old = el.zone.querySelector(".empty");
    if (old) old.remove();
    el.zone.querySelectorAll(".chunk").forEach((n) => n.remove());
    const frag = document.createDocumentFragment();
    if (sentenceStep) {
      // context rows are blank during the virtual sentence step — the
      // individual chunks it merges are already behind us.
      for (let o = -2; o <= 2; o++) {
        if (o === 0) {
          frag.appendChild(chunkNode(sentenceStep, "now"));
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
    if (!review && !sentenceStep) Store.setProgress(bookId, {
      sid: c.sid, occ: c.occ, ci: c.ci, level: level,
      flatIdx: idx, total: flat.length,
    });
    if (sentenceStep) {
      el.star.style.display = "none";
    } else {
      el.star.style.display = "";
      updateStar();
    }
  }

  function veil(on) {
    if (on) hideGloss();               // no meaning hints during recall
    el.zone.classList.toggle("veil", !!on);
  }

  // ---------------- gloss bubble ----------------

  let bubble = null;      // open bubble element (carries ._k)

  function hideGloss() {
    if (!bubble) return;
    bubble.remove();
    bubble = null;
    const hit = el.zone.querySelector(".gb-hit");
    if (hit) hit.classList.remove("gb-hit");
  }

  /* Tap a word in the focus line: surface → lemma (forms map), gloss
   * text where the lemma is rare enough to be in `words` (g_de preferred
   * once the AI pass fills it, g_en otherwise), lemma emoji if any.
   * Entities gloss to "a name" (the gloss file skips them by design). */
  function showGloss(spanEl) {
    const k = +spanEl.dataset.k;
    if (bubble && bubble._k === k) { hideGloss(); return; }   // toggle off
    hideGloss();
    const cur = sentenceStep || flat[idx];
    if (!gloss || !cur || !cur.sent) return;
    const info = Data3.glossLookup(gloss, cur.sent, k);

    const d = document.createElement("div");
    d.className = "glossbubble";
    const head = document.createElement("div");
    head.className = "gb-word";
    head.textContent = info.surface;
    const lemmaDisp = info.entry ? info.entry.l : info.lemma;
    if (lemmaDisp && Data3.nfcLower(lemmaDisp) !== Data3.nfcLower(info.surface)) {
      head.appendChild(document.createTextNode(" → "));
      const lm = document.createElement("span");
      lm.className = "gb-lemma";
      lm.textContent = lemmaDisp;
      head.appendChild(lm);
    }
    if (info.entry && info.entry.e) {
      const em = document.createElement("span");
      em.className = "gb-emoji";
      em.textContent = info.entry.e;
      head.appendChild(em);
    }
    d.appendChild(head);
    const body = document.createElement("div");
    body.className = "gb-gloss";
    body.textContent = info.isEnt ? "a name"
      : info.entry ? (info.entry.g_de || info.entry.g_en || "")
      : info.lemma ? "" : "no glossary entry";
    if (body.textContent) d.appendChild(body);

    document.body.appendChild(d);
    // position above the tapped word, clamped to the viewport; flip
    // below when there is no room above
    const r = spanEl.getBoundingClientRect();
    const bw = d.offsetWidth, bh = d.offsetHeight, m = 8;
    d.style.left = Math.max(m, Math.min(r.left + r.width / 2 - bw / 2,
                                        innerWidth - bw - m)) + "px";
    const above = r.top - bh - m;
    d.style.top = (above >= m ? above : r.bottom + m) + "px";
    d._k = k;
    bubble = d;
    spanEl.classList.add("gb-hit");
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
    // Same rule for a check take: end it SILENTLY (endTake, not stop) so no
    // result fires — otherwise the silence re-arm could start listening
    // while the TTS is speaking and transcribe the voice.
    if (checker && checker.state === "listening") checker.endTake();
    status("");
    return TTS.speak(curText(), meta.lang, prefs.ttsRate);
  }

  /* begin a take, optionally hearing the phrase first (shadowing).
   * During the sentence step, ttsFirst is ignored: that step has its own
   * fixed order (own take, then TTS) so the learner can self-correct —
   * see onPlayEnd below. */
  function startTake() {
    if (!sentenceStep && prefs.ttsFirst && TTS.available()) {
      speakCurrent().then(() => rec.record({ words: curWords() }));
    } else {
      rec.record({ words: curWords() });
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
      if (s === "recording") { el.rec.className = "recbtn recording"; el.recIcon.textContent = "◼"; el.recLabel.textContent = "stop"; }
      else if (s === "playing") { el.rec.className = "recbtn playing"; el.recIcon.textContent = "▶"; el.recLabel.textContent = "listen"; }
      else { paintIdleButton(); }   // idle: "record" or "check" depending on mode
      if (s !== "recording") veil(false);   // reveal during playback / idle
      status(s === "recording"
        ? (prefs.autoStop ? "Read the phrase aloud — pausing ends the take."
                          : "Read the phrase aloud…")
        : s === "playing" ? afterHint()
        : "");
    },
    onError: (msg) => { veil(false); status(msg, true); },
    onSpeechStart: () => {
      // during the sentence step, hideText only veils if sentenceShowText is off
      const hide = sentenceStep ? (prefs.hideText && !prefs.sentenceShowText) : prefs.hideText;
      if (hide) veil(true);
    },
    onPlayEnd: () => {
      // Compare-after: hear your own take (just finished), then hear the
      // correct TTS reading, THEN apply the after-playback pref — so the
      // learner can notice what they got wrong before moving on. Always on
      // for the sentence step; on normal chunks only when "Compare with
      // the voice" (abCompare) is enabled.
      if (sentenceStep || prefs.abCompare) {
        const stepSnap = sentenceStep, idxSnap = idx;
        speakCurrent().then(() => {
          // bail if the user moved on (sentence step ended/changed, or
          // navigated to a different chunk) while TTS was playing
          if (sentenceStep !== stepSnap || idx !== idxSnap) return;
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

  // ---------------- check mode ----------------

  function checkActive() {
    return prefs.checkMode && Checker.isSupported() && !checkHidden;
  }

  // Record button while Check mode is on shows "✓ check" when idle.
  function paintIdleButton() {
    el.rec.className = "recbtn";
    if (checkActive()) { el.recIcon.textContent = "✓"; el.recLabel.textContent = "check"; }
    else { el.recIcon.textContent = "●"; el.recLabel.textContent = "record"; }
  }

  // Begin a check take. `auto` = started hands-free (no fresh user gesture),
  // e.g. auto-retry or auto-advance. Text is NOT blurred here — it blurs on
  // speech start (see onSpeechStart) so you can read until you speak.
  // NOTE: hands-free auto-starts have no user gesture; iOS Safari requires a
  // tap to begin dictation, so on iOS these fall back to "Tap ✓" (the mic
  // simply won't arm itself). On desktop they run fully hands-free.
  function startCheckTake(auto) {
    if (!checker) return;
    checkAuto = !!auto;
    TTS.stop();
    rec.reset();                 // the two mic systems never run at once (harmless if idle)
    checker._unlock();           // best-effort audio unlock for take playback
    // NOTE: the previous diff (miss marks) intentionally stays on screen
    // while listening — it clears on speech start (see onSpeechStart).
    const listen = () => {
      if (!checkActive()) return;   // bailed out during TTS
      status("Listening… say the phrase.");
      checker.start({ words: curWords() });
    };
    // "Hear the phrase first" — config always wins, on every take (including
    // miss-retries: a retry is just the same phrase run like a new one). If
    // iOS blocks the delayed recognition start (no gesture), the checker's
    // not-allowed path keeps the session and asks for a tap — TTS still plays.
    if (prefs.ttsFirst && TTS.available()) {
      status("Listen…");
      TTS.speak(curText(), meta.lang, prefs.ttsRate).then(listen);
    } else listen();
  }

  // A check take from a user tap. Tapping again while listening stops early.
  function onCheckTap() {
    if (!checker) return;
    checkSilent = 0;
    if (checker.state === "listening") { checker.stop(); return; }
    startCheckTake(false);
  }

  // Hands-free patience: recognition ends itself after a few seconds of
  // silence (continuous=false). While the flow is hands-free (after !=
  // "stop"), quietly re-arm the mic instead of stopping — the persistent
  // stream makes a no-gesture restart work. Capped so an abandoned tab
  // doesn't listen forever (~6 takes ≈ a minute of patience).
  function rearmOnSilence() {
    // Never re-arm while TTS is speaking — recognition would transcribe it.
    if (!checkActive() || prefs.after === "stop" || checkSilent >= 6 || TTS.speaking()) return false;
    checkSilent++;
    checkAuto = true;
    status("Listening… say the phrase.");
    checker.start({ words: curWords() });
    return true;
  }

  function onCheckState(s) {
    if (s === "listening") {
      el.rec.className = "recbtn recording";
      el.recIcon.textContent = "◼"; el.recLabel.textContent = "stop";
    } else paintIdleButton();
  }

  function onCheckInterim(text) {
    if (checker && checker.state === "listening" && text) status("… " + text);
  }

  /* Check-mode reference (02 schema): grade against the MODERNISED
   * form and discount entities. One displayRuns walk yields the modern
   * reference, the per-token entity-discount vector and the display
   * tokens for the diff (original or modern, following the orth
   * toggle) — always aligned. Review-deck items have no sentence data:
   * v2 behavior (plain text, no discount). */
  function checkRef() {
    const cur = sentenceStep || flat[idx];
    if (!cur || !cur.sent) return { ref: curText(), discount: null, disp: null };
    const runs = Data3.displayRuns(cur.sent, cur.a, cur.b);
    return {
      ref: runs.map((r) => r.modern).join(" "),
      discount: runs.map((r) => r.ent),
      disp: runs.map((r) => (prefs.orthModern ? r.modern : r.orig)),
    };
  }

  function onCheckResult(res) {
    const auto = checkAuto;
    veil(false);
    if (!res.transcript) {   // nothing recognized: silence, or iOS blocked an auto-start
      // Hands-free: keep listening (re-arm) rather than stopping the flow.
      if (rearmOnSilence()) return;
      status(auto ? "Tap ✓ to continue." : "Didn't catch that — tap ✓ to try again.");
      return;
    }
    checkSilent = 0;
    const cr = checkRef();
    let best = Match.score(cr.ref, res.transcript, cr.discount);
    (res.alternatives || []).forEach((alt) => {           // score the best alternative
      const sc = Match.score(cr.ref, alt, cr.discount);
      if (sc.score > best.score) best = sc;
    });
    // diff shows the DISPLAY form of each token, marks from the modern
    // scoring (token counts align — both come from the same runs)
    renderDiff(cr.disp
      ? best.tokens.map((tk, i) => ({
          display: cr.disp[i] !== undefined ? cr.disp[i] : tk.display,
          ok: tk.ok,
        }))
      : best.tokens);
    const passed = best.score >= Match.PASS;
    if (passed) { checkRetry = 0; status("✓ " + Math.round(best.score * 100) + "% — you said it."); }
    else {
      checkRetry++;
      status(checkRetry >= 3 ? "Revealed." : "Try again — " + (3 - checkRetry) + " left.");
    }
    // Loop-mode playback shape, IDENTICAL for pass and miss:
    //   take plays back (always, like the loop) -> abCompare? TTS -> continue.
    // Only "continue" differs: pass = the after-pref; miss = same phrase
    // again, run exactly like a new phrase (see checkNext).
    const idxSnap = idx, stepSnap = sentenceStep;
    const playTake = () => (res.takeUrl && checker.playbackEnabled())
      ? checker.playTake() : Promise.resolve();
    const speakModel = () => (prefs.abCompare && TTS.available())
      ? TTS.speak(curText(), meta.lang, prefs.ttsRate) : Promise.resolve();
    playTake().then(speakModel).then(() => {
      // bail if the user navigated away during playback (loop does the same)
      if (idx !== idxSnap || sentenceStep !== stepSnap) return;
      checkNext(passed);
    });
  }

  // "Continue" after a scored take. Pass and miss are IDENTICAL except for
  // the target:
  //   pass -> the after-pref (next: advance; repeat: same phrase; stop: wait)
  //   miss -> the same phrase again, started exactly like a new phrase
  //           (ttsFirst, hideText, autoStop all honored), until the 3-miss
  //           cap; the reveal then continues as a pass would.
  function checkNext(passed) {
    if (prefs.after === "stop") return;
    const advance = () => {
      if (go(1, { keepMic: true })) startCheckTake(true);
      else status(review ? "End of the deck — well done!" : "End of the book — well read!");
    };
    if (!passed && checkRetry < 3) { startCheckTake(true); return; }  // same phrase, fresh take
    if (!passed) checkRetry = 0;                       // cap reached: revealed, continue as pass
    if (prefs.after === "repeat") startCheckTake(true);
    else advance();                                    // "next"
  }

  function onCheckError(kind, msg) {
    veil(false);
    if (kind === "unavailable") {   // recognition service gone: hide the feature this session
      checkHidden = true;
      prefs.checkMode = false;
      Store.setPref("checkMode", false);
      buildSettingsSheet();
      paintIdleButton();
      status(msg, true);
      return;
    }
    // Silence: in the hands-free flow, quietly keep listening.
    if (kind === "no-speech") {
      if (rearmOnSilence()) return;
      status(msg, true);
      return;
    }
    // An auto-start that couldn't arm the mic (e.g. iOS wants a gesture):
    // don't show the scary permission error — just invite a tap.
    if (checkAuto && (kind === "mic" || kind === "generic")) {
      status("Tap ✓ to continue.");
      return;
    }
    status(msg, true);
  }

  // Render the transcript diff into the focus line: reference text verbatim,
  // missed words marked. Reveals the text (in case hideText veiled it).
  function renderDiff(tokens) {
    const txt = el.zone.querySelector(".chunk.now .txt");
    if (!txt) return;
    txt.innerHTML = "";
    tokens.forEach((tk, i) => {
      const sp = document.createElement("span");
      sp.textContent = (i ? " " : "") + tk.display;
      if (tk.ok === false) sp.className = "miss";
      txt.appendChild(sp);
    });
    veil(false);
    checkDiffShown = true;
  }

  function clearCheckDiff() {
    if (checkDiffShown) { checkDiffShown = false; render(); }
  }

  // ---------------- navigation ----------------

  // Returns true if the navigation moved somewhere (a real chunk or the
  // virtual sentence step), false if there was nowhere to go (used by the
  // hands-free "next" flow to know whether to keep going or stop).
  function go(delta, opts) {
    opts = opts || {};
    TTS.stop();
    // Leaving a phrase in Check mode: end the current take but KEEP the mic
    // open (persistent session), drop the diff, reset the retry counter.
    // render() (below) redraws the focus line clean.
    if (checkActive()) { if (checker) checker.endTake(); checkRetry = 0; checkSilent = 0; checkDiffShown = false; }

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
        autoStartOnNav(opts);
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
        autoStartOnNav(opts);
        return true;
      }
    }

    const n = idx + delta;
    if (n < 0 || n >= flat.length) return false;
    if (opts.keepMic || prefs.recordOnNext) rec.halt();  // keep mic session
    else rec.reset();
    idx = n;
    render();
    // one-tap reading: advancing starts the next take immediately (forward only)
    if (delta > 0) autoStartOnNav(opts);
    return true;
  }

  // "Record when you go to the next phrase": on a manual forward move, arm
  // the next take automatically — a CHECK take in Check mode, otherwise the
  // classic loop take. Suppressed when the caller keeps the mic (the
  // hands-free after-pref flows start their own take).
  function autoStartOnNav(opts) {
    if (opts.keepMic || !prefs.recordOnNext) return;
    if (checkActive()) { if (checker) checker._unlock(); startCheckTake(false); }
    else { rec._unlock(); startTake(); }
  }

  function bind() {
    // word taps (gloss bubble) — the focus line is raised above the tap
    // zones in CSS, so word spans receive their own clicks
    el.zone.addEventListener("click", (e) => {
      const sp = e.target.closest && e.target.closest(".chunk.now span[data-k]");
      if (sp) { e.stopPropagation(); showGloss(sp); }
    });
    // any tap that is not on a word dismisses the bubble (capture phase,
    // so it runs before navigation handlers)
    document.addEventListener("click", (e) => {
      if (bubble && !(e.target.closest && e.target.closest("span[data-k]")))
        hideGloss();
    }, true);

    el.next.addEventListener("click", () => go(1));
    el.prev.addEventListener("click", () => go(-1));
    document.querySelector(".tapzone.right").addEventListener("click", () => go(1));
    document.querySelector(".tapzone.left").addEventListener("click", () => go(-1));
    el.rec.addEventListener("click", () => {
      if (checkActive()) { onCheckTap(); return; }
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
      else if (e.key === "r" || e.key === "R") { if (checkActive()) onCheckTap(); else rec.toggle({ words: curWords() }); }
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
    el.studyBtn.addEventListener("click", () => {
      buildStudySheet();               // rebuilt on open: follows position
      el.studySheet.classList.add("open");
    });
    el.studySheet.addEventListener("click", (e) => {
      if (e.target === el.studySheet) el.studySheet.classList.remove("open");
    });
    el.sec.addEventListener("click", () => {
      if (review || !book) return;
      buildTocSheet();                 // rebuilt on open: marks the current section
      el.tocSheet.classList.add("open");
    });
    el.tocSheet.addEventListener("click", (e) => {
      if (e.target === el.tocSheet) el.tocSheet.classList.remove("open");
    });

    // release mic when the page goes away / is hidden
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { rec.reset(); if (checker) checker.reset(); TTS.stop(); }
    });
    window.addEventListener("pagehide", () => { rec.reset(); if (checker) checker.reset(); TTS.stop(); });
  }

  // ---------------- sheets ----------------

  function buildLevelSheet() {
    el.levelOpts.innerHTML = "";
    meta.levels.forEach((lv) => {
      const b = document.createElement("button");
      b.className = "opt" + (lv === level ? " sel" : "");
      b.innerHTML = lv[0].toUpperCase() + lv.slice(1) +
        "<small>" + (LEVEL_INFO[lv] || "") + "</small>";
      b.addEventListener("click", () => {
        el.sheet.classList.remove("open");
        if (lv !== level) {
          rec.reset();
          loadLevel(lv, false);
          buildLevelSheet();
        }
      });
      el.levelOpts.appendChild(b);
    });
  }

  /* TOC: tap the section-title line -> sheet with every section; tap a
   * section -> jump to its first chunk (the current section jumps back
   * to its own start — "restart chapter"). Sentence counts are counted
   * client-side per the schema (derivable, not baked). */
  function jumpToSection(si) {
    const at = flat.findIndex((c) => c.sec === si);
    if (at < 0) return;
    TTS.stop();                       // clean handover, like a level switch
    rec.reset();
    if (checker) checker.reset();
    checkRetry = 0; checkSilent = 0; checkDiffShown = false;
    sentenceStep = null;
    idx = at;
    render();
  }

  function buildTocSheet() {
    const box = $("tocopts");
    box.innerHTML = "";
    const cur = flat.length ? flat[idx].sec : -1;
    book.sections.forEach((s, si) => {
      const b = document.createElement("button");
      b.className = "opt" + (si === cur ? " sel" : "");
      const t = document.createElement("div");
      t.textContent = s.title || "Section " + (si + 1);
      const small = document.createElement("small");
      small.textContent = s.sentences.length + " sentences";
      b.appendChild(t);
      b.appendChild(small);
      b.addEventListener("click", () => {
        el.tocSheet.classList.remove("open");
        jumpToSection(si);
      });
      box.appendChild(b);
    });
  }

  /* Study words (gloss file): the current sentence's rare lemmas
   * (study_by_sent, keyed by sentence id — identical sentences share the
   * list by design) and the current section's pre-study list
   * (sections[].study, first-occurrence order). Display-only for now;
   * known-word tracking is a v4 concern. */
  function studyRow(lemma) {
    const w = gloss.words &&
      Object.prototype.hasOwnProperty.call(gloss.words, lemma)
      ? gloss.words[lemma] : null;
    const d = document.createElement("div");
    d.className = "wordrow";
    const head = document.createElement("div");
    head.className = "wr-lemma";
    head.textContent = (w && w.l) || lemma;
    if (w && w.e) {
      const em = document.createElement("span");
      em.className = "wr-emoji";
      em.textContent = w.e;
      head.appendChild(em);
    }
    d.appendChild(head);
    const g = document.createElement("div");
    g.className = "wr-gloss";
    g.textContent = w ? (w.g_de || w.g_en || "") : "";
    d.appendChild(g);
    return d;
  }

  function buildStudySheet() {
    const box = $("studyopts");
    box.innerHTML = "";
    const c = flat[idx];
    if (!gloss || !c) return;
    const heading = (t) => {
      const h = document.createElement("h3");
      h.textContent = t;
      h.className = "wr-head";
      box.appendChild(h);
    };
    const sentList = (gloss.study_by_sent &&
      Object.prototype.hasOwnProperty.call(gloss.study_by_sent, c.sid)
      ? gloss.study_by_sent[c.sid] : []) || [];
    heading("In this sentence");
    if (sentList.length) sentList.forEach((l) => box.appendChild(studyRow(l)));
    else {
      const p = document.createElement("div");
      p.className = "wr-empty";
      p.textContent = "Nothing rare here — read on.";
      box.appendChild(p);
    }
    const sec = gloss.sections && gloss.sections[c.sec];
    if (sec && sec.study && sec.study.length) {
      heading((c.secTitle || "This section") + " — before you read (" +
              sec.study.length + ")");
      sec.study.forEach((l) => box.appendChild(studyRow(l)));
    }
  }

  function setPref(name, value) {
    prefs[name] = value;
    Store.setPref(name, value);
    if (name === "autoStop") {
      rec.autoStop = value;
      if (checker) checker.setAutoStop(value);   // check takes use it too (VAD endpointing)
    }
    if (name === "studyWords" || name === "orthModern") render();  // repaint text
    if (name === "checkMode") {   // switching modes: hand the mic over cleanly
      if (checker) checker.reset();
      rec.reset();
      TTS.stop();
      checkRetry = 0;
      clearCheckDiff();
      paintIdleButton();
      status("");
    }
    buildSettingsSheet();
  }

  // Settings are tabbed (Reading / Practice / Voice) — the option list
  // outgrew one column. The active tab is sticky for the session only.
  let settingsTab = null;

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

    // ---- tab row (a tab is hidden when its feature is unavailable)
    const tabs = [];
    if (gloss || bookHasOrth) tabs.push(["reading", "Reading"]);
    tabs.push(["practice", "Practice"]);
    if (TTS.available()) tabs.push(["voice", "Voice"]);
    if (!settingsTab || !tabs.some((t) => t[0] === settingsTab))
      settingsTab = tabs[0][0];
    if (tabs.length > 1) {
      const row = document.createElement("div");
      row.className = "tabrow";
      tabs.forEach(([id, label]) => {
        const b = document.createElement("button");
        b.className = "tabbtn" + (id === settingsTab ? " sel" : "");
        b.textContent = label;
        b.addEventListener("click", () => {
          settingsTab = id;
          buildSettingsSheet();
        });
        row.appendChild(b);
      });
      box.appendChild(row);
    }

    if (settingsTab === "reading") {
      if (gloss)
        toggle("Mark study words", "A faint underline on the rare words of the current phrase — the ones the study list (Aa) collects. Turn off if it distracts.", "studyWords");
      if (bookHasOrth)
        toggle("Modernised spelling", "Show Tür instead of Thür, dass instead of daß. Speaking checks always accept the modern form either way.", "orthModern");
      return;
    }

    if (settingsTab === "voice") {
      toggle("Hear the phrase first", "Shadowing: the phrase is spoken aloud, then recording starts — imitate what you heard.", "ttsFirst");
      toggle("Compare with the voice", "After each take: hear your own recording, then the phrase spoken, back to back.", "abCompare");
      heading("Voice speed");
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
      return;
    }

    // ---- practice
    toggle("Auto-stop when you pause", "No second tap: about a second of silence ends the take — recording plays back, check takes score right away.", "autoStop");
    toggle("Hide text while you speak", "The phrase disappears the moment your voice starts (emoji hint stays) and comes back for playback — recall practice.", "hideText");
    toggle("Record when you go to the next phrase", "Tapping next immediately starts the next take.", "recordOnNext");

    heading("Sentence replay");
    toggle("Read the whole sentence", "After the last piece of a sentence, read the complete sentence once.", "sentenceReplay");
    if (prefs.sentenceReplay) {
      toggle("Show text for full sentences", "Even when chunk text is hidden, the complete-sentence step stays visible.", "sentenceShowText");
    }

    if (Checker.isSupported() && !checkHidden) {
      heading("Check mode (recall test)");
      toggle("Check what you said", "Speak the phrase; the app checks your words against the text and marks any you missed. Up to 3 tries, then it reveals and lets you move on. Playback of your take is included where the device allows it.", "checkMode");
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
