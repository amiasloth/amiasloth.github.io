/* Zzzpeak reader — focus line + context, per-chunk loop recording. */
(function () {
  "use strict";

  const qs = new URLSearchParams(location.search);
  const bookId = qs.get("book");
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
    levelBtn: $("levelbtn"),
    sheet: $("levelsheet"),
    levelOpts: $("levelopts"),
    ring: $("levelring"),
  };

  const LEVEL_INFO = {
    beginner: "2–5 words per phrase",
    intermediate: "up to 8 words per phrase",
    advanced: "up to 12 words per phrase",
  };

  let meta = null;       // entry from books.json
  let book = null;       // loaded book json
  let flat = [];         // [{t, e?, cont?, sec, secTitle}]
  let idx = 0;
  let level = null;

  // ---------------- data ----------------

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " -> " + r.status);
    return r.json();
  }

  async function init() {
    if (!bookId) { fail("No book selected."); return; }
    let index;
    try { index = await fetchJSON("data/books.json"); }
    catch (e) { fail("Could not load the book list."); return; }
    meta = (index.books || []).find((b) => b.id === bookId);
    if (!meta) { fail("Unknown book: " + bookId); return; }
    el.title.textContent = meta.title;
    level = Store.getLevel(bookId, meta.levels.includes("beginner")
      ? "beginner" : meta.levels[0]);
    if (!meta.levels.includes(level)) level = meta.levels[0];
    buildLevelSheet();
    await loadLevel(level, true);
    bind();
  }

  async function loadLevel(lv, restore) {
    const prevFrac = flat.length ? idx / flat.length : null;
    try {
      book = await fetchJSON("data/" + meta.lang + "/" + bookId + "_" + lv + ".json");
    } catch (e) {
      fail("Could not load “" + meta.title + "” (" + lv + ").");
      return;
    }
    level = lv;
    Store.setLevel(bookId, lv);
    flat = [];
    book.sections.forEach((s, si) => {
      s.chunks.forEach((c) => {
        flat.push({ t: c.t, e: c.e, cont: c.cont, sec: si, secTitle: s.title });
      });
    });
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
    el.zone.innerHTML = "";
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
    d.appendChild(document.createTextNode(c.t));
    if (c.cont) {
      const dot = document.createElement("span");
      dot.className = "cont-dot";
      dot.textContent = " ›";
      d.appendChild(dot);
    }
    return d;
  }

  function render() {
    if (!flat.length) { fail("This book has no content."); return; }
    const c = flat[idx];
    el.sec.textContent = c.secTitle || book.title;
    el.zone.querySelectorAll(".chunk").forEach((n) => n.remove());
    const frag = document.createDocumentFragment();
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
    el.zone.appendChild(frag);
    el.prog.style.width = (100 * (idx + 1) / flat.length).toFixed(2) + "%";
    Store.setProgress(bookId, level, c.sec, idx, flat.length);
  }

  // ---------------- recorder ----------------

  const rec = new LoopRecorder({
    loop: true,
    onState: (s) => {
      el.rec.className = "recbtn " + (s === "idle" ? "" : s);
      if (s === "recording") { el.recIcon.textContent = "◼"; el.recLabel.textContent = "stop"; }
      else if (s === "playing") { el.recIcon.textContent = "▶"; el.recLabel.textContent = "listen"; }
      else { el.recIcon.textContent = "●"; el.recLabel.textContent = "record"; }
      status(s === "recording" ? "Read the phrase aloud…"
        : s === "playing" ? "Playing back — recording starts again after."
        : "");
    },
    onError: (msg) => status(msg, true),
    onLevel: (v) => {
      el.ring.style.opacity = v > 0.02 ? Math.min(1, v * 3).toFixed(2) : 0;
      el.ring.style.transform = "scale(" + (1 + v * 0.25).toFixed(3) + ")";
    },
  });

  function status(msg, isErr) {
    el.status.textContent = msg;
    el.status.className = "statusline" + (isErr ? " err" : "");
  }

  // ---------------- navigation ----------------

  function go(delta) {
    const n = idx + delta;
    if (n < 0 || n >= flat.length) return;
    rec.reset();                       // moving on ends the loop
    idx = n;
    render();
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
      rec.toggle();
    });

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
    });

    el.levelBtn.addEventListener("click", () => el.sheet.classList.add("open"));
    el.sheet.addEventListener("click", (e) => {
      if (e.target === el.sheet) el.sheet.classList.remove("open");
    });

    // release mic when the page goes away / is hidden
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) rec.reset();
    });
    window.addEventListener("pagehide", () => rec.reset());
  }

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

  init();
})();
