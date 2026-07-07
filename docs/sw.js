/* Zzzpeak service worker — app shell cache-first, book data stale-while-revalidate. */
const VERSION = "zzzpeak-v4";
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

  // book data: serve cached immediately, refresh in the background
  if (url.pathname.includes("/data/")) {
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
