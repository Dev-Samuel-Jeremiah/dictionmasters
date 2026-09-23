/*
 * Diction Masters service worker (apps/landing/pwa.py explains the plan).
 *
 *   pages        tried from the server first. A page that answers is also
 *                kept, so opening it again with no connection shows the
 *                same page instead of the generic offline card — nobody
 *                has to remember to "save" anything first. Pages under a
 *                SENSITIVE path (accounts, billing, the control room, a
 *                test result, a live Clash score) are never kept, since a
 *                shared school device shouldn't show the last learner's
 *                page to the next one while offline. Logging out clears
 *                every page that was kept, for the same reason.
 *   /static/     the site's own files: kept once fetched, since a changed
 *                file always comes with a new address.
 *   everything   else (uploads, recordings, forms, live requests) goes
 *                straight to the server, untouched.
 */
const VERSION = "{{ version }}";
const CACHE = "dm-static-" + VERSION;
const PAGES_CACHE = "dm-pages";
// Not versioned like CACHE: a learner's kept pages shouldn't vanish just
// because a release shipped a new stylesheet. They're cleared on logout
// instead (below), and trimmed as they grow (MAX_PAGES).
const OFFLINE_URL = "{{ offline_url }}";
const STATIC_PREFIX = "{{ static_prefix }}";
const PRECACHE = {{ precache|safe }};
const OFFLINE_PAGE = "/videos/offline/";
const LOGOUT_PATH = "/accounts/logout/";
const MAX_PAGES = 60;

// Pages under these are never kept for offline use — account details,
// money, admin tools, and anything scored or timestamped per learner.
const SENSITIVE_PREFIXES = [
  "/accounts/", "/manage/", "/admin/", "/billing/", "/school/",
  "/assessments/", "/clash/", "/daily-practice/", "/console/",
];

function isSensitive(pathname) {
  // The learner dashboard is the home base for offline study. Keep its
  // last successful response on this device; other account pages can
  // contain login, registration, or account management details.
  if (pathname === "/accounts/dashboard/") return false;
  return SENSITIVE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

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
      .then((names) => Promise.all(
        names.filter((n) => n.startsWith("dm-") && n !== CACHE && n !== PAGES_CACHE).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

async function trimPagesCache() {
  const cache = await caches.open(PAGES_CACHE);
  const keys = await cache.keys();
  const extra = keys.length - MAX_PAGES;
  if (extra > 0) await Promise.all(keys.slice(0, extra).map((key) => cache.delete(key)));
}

async function keepPage(request, response) {
  if (!response.ok || response.type !== "basic") return;
  const cache = await caches.open(PAGES_CACHE);
  await cache.put(request, response.clone());
  trimPagesCache();
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    // Logging out: stop keeping this device's cached pages from here on.
    if (url.pathname === LOGOUT_PATH) {
      event.respondWith(
        fetch(request).then((response) => {
          caches.delete(PAGES_CACHE);
          return response;
        }).catch(() => caches.match(OFFLINE_URL).then((page) => page || Response.error()))
      );
      return;
    }

    // The Offline videos page is kept, so it opens with no connection.
    if (url.pathname === OFFLINE_PAGE) {
      event.respondWith(
        fetch(request).then(async (response) => {
          if (response.ok) {
            const cache = await caches.open(CACHE);
            await cache.put(OFFLINE_PAGE, response.clone());
          }
          return response;
        }).catch(() => caches.match(OFFLINE_PAGE).then((page) => page || caches.match(OFFLINE_URL)))
      );
      return;
    }

    const sensitive = isSensitive(url.pathname);
    event.respondWith(
      fetch(request).then(async (response) => {
        if (!sensitive) await keepPage(request, response);
        return response;
      }).catch(() =>
        (sensitive ? Promise.resolve() : caches.match(request))
          .then((page) => page || caches.match(OFFLINE_URL))
          .then((page) => page || Response.error())
      )
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