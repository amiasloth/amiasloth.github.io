/* Zzzpeak v2 progress store — localStorage, no accounts, everything local.
 * Isolated from the original app's key ("zzzpeak.v1"); one-time import of
 * v1 data on first load only, never written back to v1. */
(function (global) {
  "use strict";
  const KEY = "zzzpeak.v2";
  const OLD_KEY = "zzzpeak.v1";

  // One-time import: if v2 has no data yet but v1 does, copy it once.
  // Never write to OLD_KEY.
  try {
    if (localStorage.getItem(KEY) === null) {
      const old = localStorage.getItem(OLD_KEY);
      if (old !== null) localStorage.setItem(KEY, old);
    }
  } catch (e) { /* start empty on any error */ }

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; }
    catch (e) { return {}; }
  }
  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
  }

  global.Store = {
    // progress per book+level: {sec, chunk, total}
    getProgress(bookId, level) {
      const s = load();
      return (s.progress && s.progress[bookId + ":" + level]) || null;
    },
    setProgress(bookId, level, sec, chunk, total) {
      const s = load();
      s.progress = s.progress || {};
      s.progress[bookId + ":" + level] = { sec, chunk, total, at: Date.now() };
      save(s);
    },
    getLevel(bookId, fallback) {
      const s = load();
      return (s.levels && s.levels[bookId]) || fallback;
    },
    setLevel(bookId, level) {
      const s = load();
      s.levels = s.levels || {};
      s.levels[bookId] = level;
      save(s);
    },
    // starred phrases per book+level: [{i, t, e?}]
    getStars(bookId, level) {
      const s = load();
      return (s.stars && s.stars[bookId + ":" + level]) || [];
    },
    isStarred(bookId, level, i) {
      return this.getStars(bookId, level).some((x) => x.i === i);
    },
    toggleStar(bookId, level, item) {
      const s = load();
      s.stars = s.stars || {};
      const key = bookId + ":" + level;
      const arr = s.stars[key] || [];
      const at = arr.findIndex((x) => x.i === item.i);
      if (at >= 0) arr.splice(at, 1);
      else { arr.push(item); arr.sort((a, b) => a.i - b.i); }
      s.stars[key] = arr;
      save(s);
      return at < 0;                       // true if now starred
    },
    starCount(bookId) {
      const s = load();
      let n = 0;
      for (const k in s.stars || {})
        if (k.startsWith(bookId + ":")) n += s.stars[k].length;
      return n;
    },
    starLevels(bookId) {
      const s = load();
      const out = [];
      for (const k in s.stars || {})
        if (k.startsWith(bookId + ":") && s.stars[k].length)
          out.push(k.slice(bookId.length + 1));
      return out;
    },
    getPref(name, fallback) {
      const s = load();
      return s.prefs && name in s.prefs ? s.prefs[name] : fallback;
    },
    setPref(name, value) {
      const s = load();
      s.prefs = s.prefs || {};
      s.prefs[name] = value;
      save(s);
    },
  };
})(window);
