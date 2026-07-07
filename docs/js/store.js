/* Zzzpeak progress store — localStorage, no accounts, everything local. */
(function (global) {
  "use strict";
  const KEY = "zzzpeak.v1";

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
