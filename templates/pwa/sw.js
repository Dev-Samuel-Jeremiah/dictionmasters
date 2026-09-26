/*
 * Diction Masters service worker (apps/landing/pwa.py explains the plan).
 *
 *   pages        learner pages are tried from the server first and kept
 *                on this device for offline study. Admin, billing and
 *                account-entry pages are never cached. Logging out clears
 *                the learner cache and queued progress for this device.
 *   downloads    "Download lessons for offline" (static/js/offline_sync.js)
 *                walks the learning tools from their front pages and keeps
 *                every lesson page it finds, optionally with its pictures
 *                and audio, so lessons open with no connection at all.
 *   /static/     the site's own files: kept once fetched, since a changed
 *                file always comes with a new address.
 *   media        lesson images and audio (ours, and the ones stored on
 *                Cloudflare R2) are kept for offline use; videos use their
 *                separate encrypted offline store.
 *   progress     learning actions made offline (marking lessons complete,
 *                word lists, saved answers, the card you were on) wait on
 *                this device and are sent, in order, when it reconnects.
 */
const VERSION = "{{ version }}";
const CACHE = "dm-static-" + VERSION;
const PAGES_CACHE = "dm-pages";
const MEDIA_CACHE = "dm-media";
// Not versioned like CACHE: a learner's kept pages shouldn't vanish just
// because a release shipped a new stylesheet. They're cleared on logout
// instead (below), and trimmed as they grow (MAX_PAGES).
const OFFLINE_URL = "{{ offline_url }}";
const STATIC_PREFIX = "{{ static_prefix }}";
const PRECACHE = {{ precache|safe }};
// Hosts that lesson pictures and audio come from besides this site
// (Cloudflare R2 and any listed in OFFLINE_MEDIA_HOSTS, config/settings.py).
const MEDIA_HOSTS = {{ media_hosts|safe }};
const REQUIRED_PRECACHE = PRECACHE.filter((path) => !path.startsWith("/site-branding/"));
const BRAND_PRECACHE = PRECACHE.filter((path) => path.startsWith("/site-branding/"));
const OFFLINE_PAGE = "/videos/offline/";
const LOGOUT_PATH = "/accounts/logout/";
const HOME_PATH = "/accounts/dashboard/";
const QUEUE_DB = "dm-offline-sync";
const MAX_PAGES = 500;
const MAX_MEDIA = 800;

// Learner pages and progress are private to this browser profile. They are
// removed when the learner logs out. Account entry, commerce and staff pages
// never enter the offline cache.
const SENSITIVE_PREFIXES = ["/manage/", "/admin/", "/billing/", "/school/", "/console/"];
const SENSITIVE_PATHS = [
  "/accounts/login/", "/accounts/logout/", "/accounts/register/", "/accounts/join/", "/accounts/delete/",
];

function isSensitive(pathname) {
  return SENSITIVE_PREFIXES.some((prefix) => pathname.startsWith(prefix)) ||
    SENSITIVE_PATHS.some((path) => pathname.startsWith(path));
}

// Learning actions that can wait until the device is back online. Each is
// safe to send later: it records something the learner did, and needs no
// answer from the server to carry on. (Things that need the server to
// answer — AI feedback, checking an answer, a live Clash match — are not here.)
const QUEUEABLE_PROGRESS = [
  /^\/learning-modules\/[^/]+\/[^/]+\/[^/]+\/[^/]+\/complete\/$/,
  /^\/echospell\/[^/]+\/[^/]+\/complete\/$/,
  /^\/echospell\/card-position\/$/,
  /^\/reading-club\/[^/]+\/[^/]+\/[^/]+\/complete\/$/,
  /^\/quick-words\/lists\/new\/$/,
  /^\/quick-words\/lists\/\d+\/toggle\/[^/]+\/$/,
  /^\/quick-words\/lists\/\d+\/delete\/$/,
  /^\/assessments\/attempt\/\d+\/save\/$/,
  // Lesson activities (44 Academy, Tricks, EchoSpell): marked on the server
  // from the answers alone, so they can be sent later and marked then.
  /^\/book\/44-academy\/[^/]+\/assessment\/[^/]+\/$/,
  /^\/tricks\/lessons\/[^/]+\/assessment\/[^/]+\/$/,
  /^\/echospell\/[^/]+\/[^/]+\/activities\/[^/]+\/$/,
];

function isActivity(pathname) {
  return /\/(assessment|activities)\/[^/]+\/$/.test(pathname);
}

function canQueueProgress(request, pathname) {
  return request.method === "POST" && QUEUEABLE_PROGRESS.some((pattern) => pattern.test(pathname));
}

// ------------------------------------------------------------ lifecycle

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(REQUIRED_PRECACHE).catch(() => {});
    await Promise.all(BRAND_PRECACHE.map((path) => cache.add(path).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(async (names) => {
      // Older cached pages may still reference fingerprinted styles from a
      // previous release. Keep several static versions with the page cache.
      const oldStatic = names.filter((name) => name.startsWith("dm-static-") && name !== CACHE);
      const keepStatic = new Set(oldStatic.slice(-4));
      await Promise.all(names.filter((name) => name.startsWith("dm-") && name !== CACHE &&
        name !== PAGES_CACHE && name !== MEDIA_CACHE && !keepStatic.has(name)).map((name) => caches.delete(name)));
      await self.clients.claim();
    })
  );
});

// ---------------------------------------------------------------- pages

async function trimCache(name, max) {
  const cache = await caches.open(name);
  const keys = await cache.keys();
  const extra = keys.length - max;
  if (extra > 0) await Promise.all(keys.slice(0, extra).map((key) => cache.delete(key)));
}

async function keepPage(request, response) {
  // "basic": fetched from this site; "default": a page a download stored.
  if (!response.ok || (response.type !== "basic" && response.type !== "default")) return;
  const cache = await caches.open(PAGES_CACHE);
  await cache.put(request, response.clone());
  trimCache(PAGES_CACHE, MAX_PAGES);
}

async function cachedPath(pathname) {
  const cache = await caches.open(PAGES_CACHE);
  const keys = await cache.keys();
  const key = keys.find((item) => new URL(item.url).pathname === pathname);
  return key ? cache.match(key) : null;
}

async function cachedPage(request) {
  const cache = await caches.open(PAGES_CACHE);
  const pathname = new URL(request.url).pathname;
  const page = (await cache.match(request, { ignoreSearch: true })) || (await cachedPath(pathname));
  if (page) return page;
  // The app and the installed web app open on "/", which only redirects:
  // offline, open the learner's dashboard instead.
  if (pathname === "/") return cachedPath(HOME_PATH);
  return null;
}

async function clearLearnerData() {
  await caches.delete(PAGES_CACHE);
  await caches.delete(MEDIA_CACHE);
  await clearProgressQueue();
}

// ---------------------------------------------------------------- media

// Stored media links carry a signature that expires; the file is kept under
// its address without the signature, so a page kept last week still finds it.
function mediaKey(url) {
  const u = new URL(url);
  return u.origin + u.pathname;
}

function isRemoteMedia(url) {
  return MEDIA_HOSTS.some((host) => url.hostname === host || url.hostname.endsWith("." + host));
}

async function putMedia(key, response) {
  const cache = await caches.open(MEDIA_CACHE);
  await cache.put(key, response);
  trimCache(MEDIA_CACHE, MAX_MEDIA);
}

async function matchMedia(url) {
  const cache = await caches.open(MEDIA_CACHE);
  return (await cache.match(mediaKey(url))) || (await cache.match(url));
}

// Our own pictures and audio: keep what the learner has seen.
async function cacheMedia(request) {
  const cache = await caches.open(MEDIA_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic" && !request.headers.has("range")) {
      await putMedia(request.url, response.clone());
    }
    return response;
  } catch (error) {
    return (await cache.match(request)) || Response.error();
  }
}

// Pictures and audio on R2: from the network while online (so playback and
// seeking behave normally), from the device when offline.
async function remoteMedia(request) {
  if (request.destination === "image") {
    // Pictures seen online are kept too. Asking with CORS gives a readable
    // copy (opaque copies would eat the phone's storage allowance).
    try {
      const response = await fetch(request.url, { mode: "cors", credentials: "omit" });
      if (response.ok) putMedia(mediaKey(request.url), response.clone()).catch(() => {});
      return response;
    } catch (error) { /* no CORS rule on the bucket, or offline: below */ }
  }
  try {
    // Audio: straight from the network, so streaming and seeking behave
    // normally. It is kept for offline use by a lesson download.
    return await fetch(request);
  } catch (error) {
    return (await matchMedia(request.url)) || Response.error();
  }
}

// Used by a lesson download: fetch a picture or recording and keep it.
async function downloadMedia(address) {
  const key = mediaKey(address);
  const cache = await caches.open(MEDIA_CACHE);
  if (await cache.match(key)) return true;
  try {
    // A readable (CORS) copy, which plays back offline everywhere. Files on
    // R2 need the bucket's CORS rule for this (MOBILE_APP_GUIDE.md, section 11).
    const sameSite = new URL(address).origin === self.location.origin;
    const response = await fetch(address, sameSite ? { credentials: "include" } : { mode: "cors", credentials: "omit" });
    if (!response.ok) return false;
    await putMedia(key, response);
    return true;
  } catch (error) {
    return false;
  }
}

// The page's own stylesheets and scripts, so a downloaded page looks right offline.
async function downloadStatic(path) {
  const cache = await caches.open(CACHE);
  if (await cache.match(path)) return;
  try {
    const response = await fetch(path);
    if (response.ok) await cache.put(path, response);
  } catch (error) { /* try again next download */ }
}

// ------------------------------------------------------- lesson download

// Where a download starts: the front page of every learning tool.
const DOWNLOAD_SEEDS = [
  HOME_PATH, "/learning-tools/", "/book/", "/book/44-academy/", "/book/phonemic-chart/",
  "/tricks/", "/tricks/lessons/", "/echospell/", "/learning-modules/", "/reading-club/",
  "/quick-words/", "/quick-words/lists/", "/daily-practice/", "/library/", "/reference-library/",
  "/radio/", "/assessments/", "/assessments/results/", OFFLINE_PAGE,
];

// Links a download never follows: actions, searches, live or one-off pages.
const DOWNLOAD_SKIP = [
  /^\/search\//, /\/suggest\//, /\/read-along\//, /\/qr-sheet\//, /\.[a-z0-9]{2,5}$/i,
  /^\/videos\/(?!offline\/$)/, /^\/assessments\/(attempt|marking)\//, /^\/clash\/\d+/,
  /^\/accounts\/(?!dashboard\/$)/, /^\/app\//, /^\/offline\/$/, /^\/privacy\/$/,
  /\/(start|complete|delete|toggle|new|lookup)\/$/, /^\/clash\/sound\/$/, /^\/(manage|admin|billing|school|console)\//,
  /\/assessment\/[^/]+\/result\//,
];

function followable(url) {
  if (url.origin !== self.location.origin) return false;
  if (isSensitive(url.pathname)) return false;
  return !DOWNLOAD_SKIP.some((pattern) => pattern.test(url.pathname));
}

function decodeEntities(text) {
  return text.replace(/&amp;/g, "&").replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"');
}

function staticFilesIn(html) {
  const files = new Set();
  const pattern = new RegExp("[\"'](" + STATIC_PREFIX.replace(/[.*+?^$()|[\]\\]/g, "\\$&") + "[^\"'\\s#]+)[\"']", "g");
  let match;
  while ((match = pattern.exec(html))) files.add(decodeEntities(match[1]));
  return [...files];
}

function linksIn(html, base) {
  const pages = [];
  const media = [];
  const anchor = /<a\b[^>]*?\bhref\s*=\s*["']([^"'#]+)["']/gi;
  const source = /<(?:img|audio|source)\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/gi;
  let match;
  while ((match = anchor.exec(html))) {
    try { pages.push(new URL(decodeEntities(match[1]), base)); } catch (error) { /* not an address */ }
  }
  while ((match = source.exec(html))) {
    try { media.push(new URL(decodeEntities(match[1]), base)); } catch (error) { /* not an address */ }
  }
  return { pages, media };
}

async function tellClients(message) {
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  clients.forEach((client) => client.postMessage(message));
}

// A download runs in steps: the page (static/js/offline_sync.js) asks for
// one step at a time and hands back where it got to. Browsers stop a
// service worker that works on one job for too long, so each step is short.
function newDownload(options) {
  return {
    media: Boolean(options && options.media),
    limit: Math.min(Number(options && options.limit) || 400, MAX_PAGES),
    queue: DOWNLOAD_SEEDS.map((path) => [path, 0]),
    seen: DOWNLOAD_SEEDS.slice(),
    mediaSeen: [],
    pages: 0, media_kept: 0, failed: 0, done: false, stopped: "",
  };
}

async function downloadStep(state, stepPages) {
  const maxDepth = 5;
  const seen = new Set(state.seen);
  const mediaSeen = new Set(state.mediaSeen);
  let doneThisStep = 0;

  async function one([path, depth]) {
    const address = new URL(path, self.location.origin);
    let response;
    try {
      response = await fetch(address.href, { credentials: "include", redirect: "follow",
        headers: { Accept: "text/html" } });
    } catch (error) {
      state.failed += 1;
      if (!navigator.onLine) state.stopped = "offline";
      return;
    }
    const finalUrl = new URL(response.url || address.href);
    if (finalUrl.pathname.startsWith("/accounts/login/")) { state.stopped = "signed-out"; return; }
    if (!response.ok || isSensitive(finalUrl.pathname) ||
        !(response.headers.get("Content-Type") || "").includes("text/html")) return;

    const html = await response.text();
    // Stored as a fresh response under the address that was asked for, so
    // it opens offline even if the server redirected to it.
    await keepPage(new Request(address.href), new Response(html, {
      status: 200, headers: { "Content-Type": response.headers.get("Content-Type") || "text/html; charset=utf-8" },
    }));
    state.pages += 1;
    doneThisStep += 1;
    await Promise.all(staticFilesIn(html).map(downloadStatic));

    const found = linksIn(html, finalUrl.href);
    if (depth < maxDepth) {
      for (const link of found.pages) {
        link.search = "";
        link.hash = "";
        if (!followable(link) || seen.has(link.pathname)) continue;
        seen.add(link.pathname);
        state.queue.push([link.pathname, depth + 1]);
      }
    }
    if (state.media) {
      for (const media of found.media) {
        const isOurs = media.origin === self.location.origin && !media.pathname.startsWith(STATIC_PREFIX);
        if (!(isOurs || isRemoteMedia(media))) continue;
        const key = mediaKey(media.href);
        if (mediaSeen.has(key) || mediaSeen.size >= MAX_MEDIA) continue;
        mediaSeen.add(key);
        if (await downloadMedia(media.href)) state.media_kept += 1;
      }
    }
  }

  // A few pages at a time: quick on Wi-Fi, gentle on the server.
  while (state.queue.length && state.pages < state.limit && !state.stopped && doneThisStep < stepPages) {
    const batch = state.queue.splice(0, 3);
    await Promise.all(batch.map(one));
  }
  state.seen = [...seen];
  state.mediaSeen = [...mediaSeen];
  state.done = Boolean(state.stopped) || !state.queue.length || state.pages >= state.limit;
  state.remaining = state.done ? 0 : Math.min(state.queue.length, state.limit - state.pages);
  return state;
}

// For tests and simple callers: a whole download in one go.
async function runDownload(options) {
  let state = newDownload(options);
  while (!state.done) state = await downloadStep(state, 25);
  return state;
}

// ------------------------------------------------------------- progress

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
  // Kept as raw bytes, so forms with a recording or a JSON answer survive too.
  const body = await request.clone().arrayBuffer();
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

async function countQueue() {
  const db = await openQueue().catch(() => null);
  if (!db) return 0;
  const count = await new Promise((resolve) => {
    const request = db.transaction("progress", "readonly").objectStore("progress").count();
    request.onsuccess = () => resolve(request.result || 0);
    request.onerror = () => resolve(0);
  });
  db.close();
  return count;
}

function wantsJson(request) {
  const accept = request.headers.get("Accept") || "";
  return request.mode !== "navigate" || accept.includes("application/json") ||
    request.headers.get("X-Requested-With") === "XMLHttpRequest";
}

async function queuedResponse(request) {
  if (wantsJson(request)) {
    return new Response(JSON.stringify({ saved: true, queued: true, offline: true }), {
      status: 202, headers: { "Content-Type": "application/json" },
    });
  }
  const referrer = request.referrer ? new URL(request.referrer) : new URL(OFFLINE_URL, self.location.origin);
  const cached = await cachedPath(referrer.pathname);
  if (!cached) return Response.redirect(new URL(OFFLINE_URL, self.location.origin).href, 303);
  const html = await cached.text();
  const message = isActivity(new URL(request.url).pathname)
    ? "Your answers are saved on this device. They will be sent and marked as soon as you are online."
    : "Saved on this device. Your progress will sync when you are online.";
  const notice = '<div role="status" style="position:sticky;top:0;z-index:99999;padding:12px 18px;background:#14213d;color:#fffdf8;text-align:center;font:600 15px system-ui">' + message + '</div>';
  const updated = html.includes("</body>") ? html.replace("</body>", notice + "</body>") : html + notice;
  return new Response(updated, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

// A form that needs the server (say, an activity marked by the AI) was sent
// with no connection: say so plainly instead of showing a browser error.
function needsInternetPage() {
  const html = '<!DOCTYPE html><html lang="en-gb"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1"><title>No connection</title></head>' +
    '<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#F2F5FC;color:#0B1A4A;' +
    'font:16px/1.5 system-ui,sans-serif;text-align:center;padding:24px">' +
    '<main style="max-width:420px"><p style="font-size:44px;margin:0">&#128246;</p>' +
    '<h1 style="font-size:22px">This needs the internet</h1>' +
    '<p style="color:#55607E">You are offline, so this wasn\'t sent. Go back, and try again when you are connected. ' +
    'Your lessons, and progress like completed lessons, still save offline.</p>' +
    '<button onclick="history.back()" style="border:0;border-radius:99px;background:#FFC72C;color:#0B1A4A;' +
    'font:800 16px system-ui;padding:14px 30px">Go back</button></main></body></html>';
  return new Response(html, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

let flushing = null;

async function flushProgressQueue() {
  if (flushing) return flushing;
  flushing = (async () => {
    const db = await openQueue();
    const jobs = await new Promise((resolve, reject) => {
      const tx = db.transaction("progress", "readonly");
      const request = tx.objectStore("progress").getAll();
      request.onsuccess = () => resolve(request.result || []);
      request.onerror = () => reject(request.error);
    });
    const remove = (id) => new Promise((resolve, reject) => {
      const tx = db.transaction("progress", "readwrite");
      tx.objectStore("progress").delete(id);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
    let synced = 0;
    let dropped = 0;
    for (const job of jobs) {
      let response;
      try {
        response = await fetch(job.url, { method: job.method, headers: job.headers, body: job.body,
          credentials: "include", redirect: "follow" });
      } catch (error) { break; } // still offline: try again later
      // Signed out meanwhile: keep everything until they sign back in.
      if (new URL(response.url || job.url).pathname.startsWith("/accounts/login/")) break;
      if (response.status >= 500) break; // the server is struggling: try again later
      // Sent (2xx/3xx), or refused for good (4xx: the lesson was removed,
      // the attempt had closed...). Either way it must not block the rest.
      if (!response.ok && response.status >= 400) dropped += 1;
      else synced += 1;
      await remove(job.id);
    }
    db.close();
    const pending = jobs.length - synced - dropped;
    await tellClients({ type: "learning-sync", synced, pending, dropped });
  })().finally(() => { flushing = null; });
  return flushing;
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

// ------------------------------------------------------------- messages

self.addEventListener("sync", (event) => {
  if (event.tag === "dm-learning-sync") event.waitUntil(flushProgressQueue());
});

self.addEventListener("message", (event) => {
  const data = event.data;
  const port = event.ports && event.ports[0];

  if (data === "update-now") self.skipWaiting();
  if (data === "sync-learning") event.waitUntil(flushProgressQueue());

  if (data === "offline-pages" && port) {
    event.waitUntil((async () => {
      const cache = await caches.open(PAGES_CACHE);
      const keys = await cache.keys();
      const seen = new Set();
      const pages = [];
      keys.forEach((key) => {
        const url = new URL(key.url);
        if (isSensitive(url.pathname) || seen.has(url.pathname)) return;
        seen.add(url.pathname);
        pages.push({ url: url.pathname, label: url.pathname === HOME_PATH ? "My dashboard" :
          decodeURIComponent(url.pathname.replace(/^\/|\/$/g, "").split("/").slice(-1)[0] || "Home").replace(/[-_]/g, " ") });
      });
      port.postMessage(pages);
    })());
  }

  // static/js/offline_sync.js: what's on this device, and downloading more.
  if (data && data.type === "offline-status" && port) {
    event.waitUntil((async () => {
      const pages = await (await caches.open(PAGES_CACHE)).keys();
      const media = await (await caches.open(MEDIA_CACHE)).keys();
      port.postMessage({ pages: pages.length, media: media.length, pending: await countQueue() });
    })());
  }
  // One step of a lesson download; the answer carries where to carry on.
  if (data && data.type === "offline-download" && port) {
    event.waitUntil((async () => {
      const state = data.state || newDownload(data);
      try {
        port.postMessage(await downloadStep(state, 20));
      } catch (error) {
        state.stopped = "error";
        state.done = true;
        port.postMessage(state);
      }
    })());
  }
  if (data && data.type === "offline-clear") {
    event.waitUntil((async () => {
      await caches.delete(PAGES_CACHE);
      await caches.delete(MEDIA_CACHE);
      if (port) port.postMessage({ cleared: true });
    })());
  }
});

// ---------------------------------------------------------------- fetch

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Lesson pictures and audio stored on R2.
  if (url.origin !== self.location.origin) {
    if (request.method === "GET" && isRemoteMedia(url) &&
        (request.destination === "image" || request.destination === "audio")) {
      event.respondWith(remoteMedia(request));
    }
    return;
  }

  if (request.method !== "GET") {
    if (url.pathname === LOGOUT_PATH && request.method === "POST") {
      event.respondWith(fetch(request.clone()).then(async (response) => {
        await clearLearnerData();
        return response;
      }).catch(async () => {
        await clearLearnerData();
        return (await caches.match(OFFLINE_URL)) || Response.error();
      }));
      return;
    }
    if (canQueueProgress(request, url.pathname)) {
      event.respondWith(fetch(request.clone()).catch(async () => {
        await queueProgress(request);
        return queuedResponse(request);
      }));
      return;
    }
    if (request.mode === "navigate") {
      event.respondWith(fetch(request).catch(() => needsInternetPage()));
    }
    return;
  }

  if (request.mode === "navigate") {
    // Logging out: stop keeping this device's cached pages from here on.
    if (url.pathname === LOGOUT_PATH) {
      event.respondWith(
        fetch(request).then(async (response) => {
          await clearLearnerData();
          return response;
        }).catch(async () => {
          await clearLearnerData();
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
        if (!sensitive && !response.redirected && !finalPath.startsWith("/accounts/login/")) {
          await keepPage(request, response);
        }
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

  // Keep same-origin lesson images and audio on this device.
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
