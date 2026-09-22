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
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL).then((page) => page || Response.error()))
    );
    return;
  }

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
