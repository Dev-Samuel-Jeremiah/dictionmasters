/*
 * Diction Masters service worker (apps/landing/pwa.py explains the plan).
 *
 *   pages        learner pages are tried from the server first and kept
 *                on this device for offline study. Admin, billing and
 *                account-entry pages are never cached. Logging out clears
 *                the learner cache and queued progress for this device.
 *   /static/     the site's own files: kept once fetched, since a changed
 *                file always comes with a new address.
 *   media        same-origin lesson images and audio are kept for offline
 *                use; videos use their separate encrypted offline store.
 *   progress     simple completion actions queue offline and sync later.
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
const REQUIRED_PRECACHE = PRECACHE.filter((path) => !path.startsWith("/site-branding/"));
const BRAND_PRECACHE = PRECACHE.filter((path) => path.startsWith("/site-branding/"));
const OFFLINE_PAGE = "/videos/offline/";
const LOGOUT_PATH = "/accounts/logout/";
const QUEUE_DB = "dm-offline-sync";
const MAX_PAGES = 300;
const MAX_MEDIA = 250;

// Learner pages and progress are private to this browser profile. They are
// removed when the learner logs out. Account entry, commerce and staff pages
// never enter the offline cache.
const SENSITIVE_PREFIXES = ["/manage/", "/admin/", "/billing/", "/school/", "/console/"];
const SENSITIVE_PATHS = [
  "/accounts/login/", "/accounts/logout/", "/accounts/register/", "/accounts/join/",
];

function isSensitive(pathname) {
  return SENSITIVE_PREFIXES.some((prefix) => pathname.startsWith(prefix)) ||
    SENSITIVE_PATHS.some((path) => pathname.startsWith(path));
}

const QUEUEABLE_PROGRESS = [
  /^\/learning-modules\/[^/]+\/[^/]+\/[^/]+\/[^/]+\/complete\/$/,
  /^\/echospell\/[^/]+\/[^/]+\/complete\/$/,
  /^\/reading-club\/[^/]+\/[^/]+\/[^/]+\/complete\/$/,
];

function canQueueProgress(request, pathname) {
  return request.method === "POST" &&
    request.headers.get("Content-Type", "").startsWith("application/x-www-form-urlencoded") &&
    QUEUEABLE_PROGRESS.some((pattern) => pattern.test(pathname));
}


self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(REQUIRED_PRECACHE).catch(() => {});
    await Promise.all(BRAND_PRECACHE.map((path) => cache.add(path).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data === "update-now") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(async (names) => {
      // Older cached pages may still reference fingerprinted styles from a
      // previous release. Keep several static versions with the page cache.
      const oldStatic = names.filter((name) => name.startsWith("dm-static-") && name !== CACHE);
      const keepStatic = new Set(oldStatic.slice(-4));
      await Promise.all(names.filter((name) => name.startsWith("dm-") && name !== CACHE &&
        name !== PAGES_CACHE && name !== "dm-media" && !keepStatic.has(name)).map((name) => caches.delete(name)));
      await self.clients.claim();
    })
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

async function cachedPath(pathname) {
  const cache = await caches.open(PAGES_CACHE);
  const keys = await cache.keys();
  const key = keys.find((item) => new URL(item.url).pathname === pathname);
  return key ? cache.match(key) : null;
}

async function cachedPage(request) {
  const cache = await caches.open(PAGES_CACHE);
  return (await cache.match(request)) || cachedPath(new URL(request.url).pathname);
}

async function cacheMedia(request) {
  const cache = await caches.open("dm-media");
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic") {
      await cache.put(request, response.clone());
      const keys = await cache.keys();
      if (keys.length > MAX_MEDIA) await Promise.all(keys.slice(0, keys.length - MAX_MEDIA).map((key) => cache.delete(key)));
    }
    return response;
  } catch (error) {
    return (await cache.match(request)) || Response.error();
  }
}

function openQueue() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(QUEUE_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("progress")) {
        request.result.createObjectStore("progress", { keyPath: "id", autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function queueProgress(request) {
  const body = await request.clone().text();
  const headers = {};
  request.headers.forEach((value, key) => { headers[key] = value; });
  const db = await openQueue();
  await new Promise((resolve, reject) => {
    const tx = db.transaction("progress", "readwrite");
    tx.objectStore("progress").add({ url: request.url, method: request.method, headers, body,
      referrer: request.referrer, created: Date.now() });
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
  db.close();
  try { await self.registration.sync.register("dm-learning-sync"); } catch (error) { /* foreground reconnect also syncs */ }
}

async function queuedResponse(request) {
  const referrer = request.referrer ? new URL(request.referrer) : new URL(OFFLINE_URL, self.location.origin);
  const cached = await cachedPath(referrer.pathname);
  if (!cached) return Response.redirect(new URL(OFFLINE_URL, self.location.origin).href, 303);
  const html = await cached.text();
  const notice = '<div role="status" style="position:sticky;top:0;z-index:99999;padding:12px 18px;background:#14213d;color:#fffdf8;text-align:center;font:600 15px system-ui">Saved on this device. Your progress will sync when you are online.</div>';
  const updated = html.includes("</body>") ? html.replace("</body>", notice + "</body>") : html + notice;
  return new Response(updated, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

async function flushProgressQueue() {
  const db = await openQueue();
  const jobs = await new Promise((resolve, reject) => {
    const tx = db.transaction("progress", "readonly");
    const request = tx.objectStore("progress").getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
  let synced = 0;
  for (const job of jobs) {
    try {
      const response = await fetch(job.url, { method: job.method, headers: job.headers, body: job.body,
        credentials: "include", redirect: "follow" });
      if (new URL(response.url || job.url).pathname.startsWith("/accounts/login/")) break;
      if (!response.ok) break;
      await new Promise((resolve, reject) => {
        const tx = db.transaction("progress", "readwrite");
        tx.objectStore("progress").delete(job.id);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });
      synced += 1;
    } catch (error) { break; }
  }
  db.close();
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  clients.forEach((client) => client.postMessage({ type: "learning-sync", synced, pending: jobs.length - synced }));
}

async function clearProgressQueue() {
  const db = await openQueue().catch(() => null);
  if (!db) return;
  await new Promise((resolve) => {
    const tx = db.transaction("progress", "readwrite");
    tx.objectStore("progress").clear();
    tx.oncomplete = resolve;
    tx.onerror = resolve;
  });
  db.close();
}

self.addEventListener("sync", (event) => {
  if (event.tag === "dm-learning-sync") event.waitUntil(flushProgressQueue());
});

self.addEventListener("message", (event) => {
  if (event.data === "sync-learning") event.waitUntil(flushProgressQueue());
  if (event.data === "offline-pages" && event.ports && event.ports[0]) {
    event.waitUntil((async () => {
      const cache = await caches.open(PAGES_CACHE);
      const keys = await cache.keys();
      const seen = new Set();
      const pages = [];
      keys.forEach((key) => {
        const url = new URL(key.url);
        if (isSensitive(url.pathname) || seen.has(url.pathname)) return;
        seen.add(url.pathname);
        pages.push({ url: url.pathname, label: url.pathname === "/accounts/dashboard/" ? "My dashboard" :
          decodeURIComponent(url.pathname.replace(/^\/|\/$/g, "").split("/").slice(-1)[0] || "Home").replace(/[-_]/g, " ") });
      });
      event.ports[0].postMessage(pages);
    })());
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method !== "GET") {
    if (url.pathname === LOGOUT_PATH && request.method === "POST") {
      event.respondWith(fetch(request.clone()).then(async (response) => {
        await caches.delete(PAGES_CACHE);
        await caches.delete("dm-media");
        await clearProgressQueue();
        return response;
      }).catch(async () => {
        await caches.delete(PAGES_CACHE);
        await caches.delete("dm-media");
        await clearProgressQueue();
        return (await caches.match(OFFLINE_URL)) || Response.error();
      }));
      return;
    }
    if (canQueueProgress(request, url.pathname)) {
      event.respondWith(fetch(request.clone()).catch(async () => {
        await queueProgress(request);
        return queuedResponse(request);
      }));
    }
    return;
  }

  if (request.mode === "navigate") {
    // Logging out: stop keeping this device's cached pages from here on.
    if (url.pathname === LOGOUT_PATH) {
      event.respondWith(
        fetch(request).then(async (response) => {
          await caches.delete(PAGES_CACHE);
          await caches.delete("dm-media");
          await clearProgressQueue();
          return response;
        }).catch(async () => {
          await caches.delete(PAGES_CACHE);
          await caches.delete("dm-media");
          await clearProgressQueue();
          return (await caches.match(OFFLINE_URL)) || Response.error();
        })
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
        const finalPath = response.url ? new URL(response.url).pathname : "";
        if (!sensitive && !finalPath.startsWith("/accounts/login/")) await keepPage(request, response);
        return response;
      }).catch(async () => {
        const page = sensitive ? null : await cachedPage(request);
        return page || (await caches.match(OFFLINE_URL)) || Response.error();
      })
    );
    return;
  }

  // Uploaded logos and favicons are public brand assets and must also be
  // available to cached pages when the app is offline.
  if (url.pathname.startsWith("/site-branding/")) {
    event.respondWith(caches.open(CACHE).then(async (cache) => {
      try {
        const response = await fetch(request);
        if (response.ok) await cache.put(request, response.clone());
        return response;
      } catch (error) {
        return (await cache.match(request)) || Response.error();
      }
    }));
    return;
  }

  // A video is never kept by the worker: saved copies are encrypted in
  // the browser's own database instead.
  if (url.pathname.startsWith("/videos/")) return;

  // Keep same-origin lesson images and audio on this device. Cross-origin
  // media needs an app-origin media route before the worker can store it.
  if (request.destination === "image" || request.destination === "audio") {
    event.respondWith(cacheMedia(request));
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