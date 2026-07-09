# Phase 01 — v2 scaffold, storage split, service-worker rule

Goal: a working copy of the reader at `/v2/`, functionally identical to the
original, with isolated storage and safe caching. No new features yet.

Read `00_overview.md` first. Frozen-file rules apply.

## Step 1 — copy the app into docs/v2/

Create:

```
docs/v2/
  index.html      copy of docs/index.html   (library)
  read.html       copy of docs/read.html    (reader)
  css/app.css     copy of docs/css/app.css
  js/store.js     copy, then modified (Step 2)
  js/tts.js       verbatim copy
  js/recorder.js  verbatim copy
  js/reader.js    copy, then modified (Step 3)
```

Do NOT copy `looper.html`, `sw.js`, `manifest.webmanifest`, `icons/`.
v2 is part of the same PWA; it registers no service worker of its own and
has no manifest (Safari uses the site-level one). If `index.html` or
`read.html` contain a `<script>` that registers the service worker, KEEP
that registration but make sure the registration path is `../sw.js` with
scope unchanged — actually simpler and safer: REMOVE the SW registration
from the v2 pages entirely; the SW installed by the original app already
controls the whole origin, and v2 must not race it.

Path fixes inside the copied HTML/JS:
- CSS/JS references stay relative (`css/app.css`, `js/reader.js`) — they
  resolve under `/v2/` automatically.
- Book data: the original fetches `data/books.json` and
  `data/<lang>/<book>_<level>.json` (see `reader.js` `fetchJSON` calls and
  `init()`). v2 must fetch `../data/books.json` and
  `../data/...` so it reuses the shared data. Grep every `fetch(` and
  `data/` literal in the copied `reader.js` and `index.html` and prefix
  with `../`.
- Links from v2 library to v2 reader must stay within `/v2/`
  (`read.html?book=...`, relative — already correct after a verbatim copy).
- Add a small visible marker so the two apps are never confused: in
  `docs/v2/index.html`, suffix the page title with " v2" (e.g.
  "Zzzpeak v2") and keep it subtle in the UI (the header title element).

## Step 2 — storage split (docs/v2/js/store.js)

In the copied `store.js`:
1. Change `const KEY = "zzzpeak.v1"` to `"zzzpeak.v2"`.
2. Add a one-time import: on load, if `localStorage["zzzpeak.v2"]` does not
   exist and `localStorage["zzzpeak.v1"]` does, copy the v1 JSON string
   into `zzzpeak.v2` once (progress, stars, levels, prefs all carry over).
   Wrap in try/catch; on any error start empty. NEVER write to
   `zzzpeak.v1`.

After this, the two apps have fully independent progress/prefs. That is
intended (they will diverge as v2 gains settings).

## Step 3 — reader namespace touch-ups (docs/v2/js/reader.js)

Only the `../data/` path changes from Step 1, plus: change the document
title / header suffix if it is set in JS. No behavior changes in this
phase.

## Step 4 — the ONE service-worker change

`docs/sw.js` currently: cache-first for everything same-origin;
stale-while-revalidate for paths containing `/data/`. Problem: v2 files
would be cached on first visit under the current VERSION and never
refresh, making v2 iteration impossible without version bumps, and version
bumps churn the original's cache.

Make exactly this change and nothing else:

1. In the fetch handler, BEFORE the existing `/data/` branch, add:

```js
  // v2 app: network-first, fall back to cache when offline.
  if (url.pathname.includes("/v2/")) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          if (r.ok)
            caches.open(VERSION).then((c) => c.put(e.request, r.clone()));
          return r;
        })
        .catch(() => caches.match(e.request).then((c) => c || Response.error()))
    );
    return;
  }
```

2. Bump `const VERSION = "zzzpeak-v4"` to `"zzzpeak-v5"` (any SW edit
   requires a bump so the new worker installs cleanly).

Notes: the `/data/` branch stays after the v2 branch, so v2's fetches of
`../data/...` still get stale-while-revalidate (URL contains `/data/` but
not `/v2/`). Do NOT add v2 files to the `SHELL` precache list. The
original's offline behavior is unchanged: same cache-first logic, new cache
name refilled on install from SHELL.

This is the only edit to a shared file in the entire project. After this
commit, `sw.js` is frozen again.

## Step 5 — verify and commit

Regression check from `00_overview.md` (original app, all 5 points), then:
- `/v2/` library loads, lists the same books.
- v2 reader: record loop, TTS, stars, levels, review mode, swipe — all
  work identically to the original.
- v2 progress is independent: advance 5 chunks in v2, reload original —
  original position unchanged (and vice versa).
- Offline (after one online visit of both apps): original loads offline;
  v2 loads offline too (from the runtime cache) — if v2 offline fails,
  that is acceptable for this phase, but the original MUST pass.
- iPhone Safari: repeat record-loop + TTS test on device.

Commit: `v2: phase 01 scaffold — isolated copy under /v2/, storage split, SW network-first rule`
(You may split the sw.js change into its own commit; recommended.)
