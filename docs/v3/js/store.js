/* Zzzpeak v3 progress store — localStorage, no accounts, everything local.
 * Namespace "zzzpeak.v3" ONLY (never touches v1/v2 keys; no import — the
 * v3 position schema is sentence-keyed and doesn't map from v2's chunk
 * indices).
 *
 * Progress per book is keyed by sentence (id, occ) per the pinned schema:
 * content-hash ids survive rebuilds and level switches; the chunk index
 * within the sentence (ci) is level-specific best-effort. flatIdx/total
 * are kept only for the library screen's percent bar. */
(function (global) {
  "use strict";
  const KEY = "zzzpeak.v3";

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; }
    catch (e) { return {}; }
  }
  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
  }

  global.Store = {
    // progress per book: {sid, occ, ci, level, flatIdx, total, at}
    getProgress(bookId) {
      const s = load();
      return (s.progress && s.progress[bookId]) || null;
    },
    setProgress(bookId, pos) {
      const s = load();
      s.progress = s.progress || {};
      pos.at = Date.now();
      s.progress[bookId] = pos;
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
    // starred phrases per book+level: [{i, t, e?}] (i = flat index at the
    // level; text is stored so the review deck replays without book data)
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
