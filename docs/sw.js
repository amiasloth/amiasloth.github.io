/* Zzzpeak service worker — app shell cache-first, book data stale-while-revalidate.
   v6 (2026-07-12): /v3/ pages+js network-first (active development) and
   /data3/ stale-while-revalidate — previously both fell through to the
   cache-first shell rule ("/data3/" does not match "/data/") and were
   pinned forever, so v3 readers kept stale gloss/book files. */
const VERSION = "zzzpeak-v6";
const SHELL = [
  "./",
  "./index.html",
  "./read.html",
  "./looper.html",
  "./css/app.css",
  "./js/store.js",
  "./js/tts.js",
  "./js/recorder.js",
  "./js/reader.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-180.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSION)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  // v2 + v3 apps: network-first, fall back to cache when offline.
  if (url.pathname.includes("/v2/") || url.pathname.includes("/v3/")) {
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

  // book data (v1/v2 and v3): serve cached immediately, refresh in
  // the background
  if (url.pathname.includes("/data/") || url.pathname.includes("/data3/")) {
    e.respondWith(
      caches.open(VERSION).then(async (cache) => {
        const cached = await cache.match(e.request);
        const net = fetch(e.request)
          .then((r) => { if (r.ok) cache.put(e.request, r.clone()); return r; })
          .catch(() => null);
        return cached || net.then((r) => r || Response.error());
      })
    );
    return;
  }

  // shell: cache first, network fallback (and cache what we fetch)
  e.respondWith(
    caches.match(e.request).then(
      (cached) =>
        cached ||
        fetch(e.request).then((r) => {
          if (r.ok)
            caches.open(VERSION).then((c) => c.put(e.request, r.clone()));
          return r;
        })
    )
  );
});
