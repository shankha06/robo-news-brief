/* The Brief — Service Worker v1 */
const CACHE = "brief-v1";
const STATIC = ["/", "/static/css/style.css", "/static/js/app.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);

  // SSE and API calls: network-first, cache the successful response
  if (url.pathname.startsWith("/api/") && !url.pathname.includes("/stream/")) {
    e.respondWith(
      fetch(request)
        .then((r) => {
          const clone = r.clone();
          caches.open(CACHE).then((c) => c.put(request, clone));
          return r;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // SSE streams: always network (never cache streaming responses)
  if (url.pathname.includes("/stream/")) {
    return; // let browser handle natively
  }

  // Static assets: cache-first
  e.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
