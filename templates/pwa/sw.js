/*
 * Diction Masters service worker (apps/landing/pwa.py explains the plan).
 *
 *   pages        always from the server; the offline page if there is no
 *                connection. Pages are never stored, so nothing private
 *                stays on the device and every new feature shows at once.
 *   /static/     the site's own files: kept once fetched, since a changed
 *                file always comes with a new address.
 *   everything   else (uploads, recordings, forms, live requests) goes
 *                straight to the server, untouched.
 */
const VERSION = "{{ version }}";
const CACHE = "dm-static-" + VERSION;
const OFFLINE_URL = "{{ offline_url }}";
const STATIC_PREFIX = "{{ static_prefix }}";
const PRECACHE = {{ precache|safe }};
const OFFLINE_PAGE = "/videos/offline/";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).catch(() => {}));
  // The page decides when to switch over (static/js/pwa.js), so a learner
  // is never moved to a new version halfway through an activity.
});

self.addEventListener("message", (event) => {
  if (event.data === "update-now") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n.startsWith("dm-") && n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    // The Offline videos page is kept, so it opens with no connection.
    if (url.pathname === OFFLINE_PAGE) {
      event.respondWith(
        fetch(request).then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(OFFLINE_PAGE, copy));
          return response;
        }).catch(() => caches.match(OFFLINE_PAGE).then((page) => page || caches.match(OFFLINE_URL)))
      );
      return;
    }
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL).then((page) => page || Response.error()))
    );
    return;
  }

  // A video is never kept by the worker: saved copies are encrypted in
  // the browser's own database instead.
  if (url.pathname.startsWith("/videos/")) return;

  if (url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((kept) => kept || fetch(request).then((response) => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        }))
      )
    );
  }
});
