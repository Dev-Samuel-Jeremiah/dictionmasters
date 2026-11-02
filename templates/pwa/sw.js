/*
 * Diction Masters service worker (apps/landing/pwa.py explains the plan).
 *
 *   pages        learner pages are tried from the server first and kept
 *                on this device for offline study. Admin, billing and
 *                account-entry pages are never cached. Logging out clears
 *                the learner cache and queued progress for this device.
 *   library      a learner's lessons, kept for offline use. The server lists
 *                every page they may open with a version (apps/offline/
 *                catalog.py); a sync fetches only what's new or changed, with
 *                its pictures and audio, and removes what's gone. Nothing
 *                here is trimmed: it's the whole of what they asked to keep.
 *   /static/     the site's own files: kept once fetched, since a changed
 *                file always comes with a new address.
 *   media        lesson images and audio (ours, and the ones stored on
 *                Cloudflare R2) are kept for offline use; videos use their
 *                separate encrypted offline store.
 *   progress     learning actions made offline (marking lessons complete,
 *                word lists, saved answers, the card you were on) wait on
 *                this device and are sent, in order, when it reconnects.
 *   sealing      all of the above except /static/ is encrypted before it's
 *                stored: AES-256-GCM, with a key made on this device that no
 *                script can read back out. Copying the stored files elsewhere
 *                gets nothing readable. It isn't DRM: the key has to be on the
 *                device for lessons to open offline, so someone determined,
 *                on a device they've broken into, could still reach it.
 */
const VERSION = "{{ version }}";
const CACHE = "dm-static-" + VERSION;
// "-2": encrypted. The stores from before encryption are deleted when this
// worker activates, and the next sync fills these.
const PAGES_CACHE = "dm-pages-2";
const MEDIA_CACHE = "dm-media-2";
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
// The library: what a sync keeps, apart from the pages and media kept in
// passing above, so those limits never trim it. Its index says which version
// of each page is here, and which files that page uses.
const LIBRARY_CACHE = "dm-library";
const LIBRARY_MEDIA = "dm-library-media";
const LIBRARY_DB = "dm-library-index";
const KEY_DB = "dm-offline-key";
const MANIFEST_URL = "/offline-sync/manifest/";

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
        name !== PAGES_CACHE && name !== MEDIA_CACHE && name !== LIBRARY_CACHE && name !== LIBRARY_MEDIA &&
        !keepStatic.has(name)).map((name) => caches.delete(name)));
      await self.clients.claim();
    })
  );
});

// ---------------------------------------------------------------- sealing

function openKeys() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(KEY_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("keys")) request.result.createObjectStore("keys", { keyPath: "p" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function keyStore(mode, change) {
  const db = await openKeys();
  const answer = await new Promise((resolve, reject) => {
    const tx = db.transaction("keys", mode);
    const request = change(tx.objectStore("keys"));
    tx.oncomplete = () => resolve(request && request.result);
    tx.onerror = () => reject(tx.error);
  });
  db.close();
  return answer;
}

let sealKeyMade = null;

// One key for this device, made once. "false" means it can be used but
// never exported, by this code or any other.
function sealKey() {
  sealKeyMade = sealKeyMade || (async () => {
    const kept = await keyStore("readonly", (store) => store.get("seal"));
    if (kept) return kept.key;
    const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    await keyStore("readwrite", (store) => store.put({ p: "seal", key }));
    return key;
  })().catch((error) => { sealKeyMade = null; throw error; });
  return sealKeyMade;
}

async function forgetSealKey() {
  sealKeyMade = null;
  await keyStore("readwrite", (store) => store.delete("seal")).catch(() => {});
}

async function sealBytes(bytes) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const secret = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await sealKey(), bytes);
  const out = new Uint8Array(iv.length + secret.byteLength);
  out.set(iv);
  out.set(new Uint8Array(secret), iv.length);
  return out;
}

async function openBytes(bytes) {
  const all = new Uint8Array(bytes);
  return crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, await sealKey(), all.slice(12));
}

// The original type travels beside the sealed bytes: "text/html" gives
// nothing away, and the browser needs it back to show the page.
async function sealed(response) {
  return new Response(await sealBytes(await response.arrayBuffer()), {
    status: 200, headers: { "X-DM-Type": response.headers.get("Content-Type") || "application/octet-stream" },
  });
}

// What was stored, readable again; null if nothing was, or it can't be
// opened (the key has gone), which is treated just like not having it.
async function unsealed(kept) {
  if (!kept) return null;
  try {
    const bytes = await openBytes(await kept.arrayBuffer());
    return new Response(bytes, { status: 200, headers: {
      "Content-Type": kept.headers.get("X-DM-Type") || "application/octet-stream",
      "Content-Length": String(bytes.byteLength), "Accept-Ranges": "bytes",
    } });
  } catch (error) {
    return null;
  }
}

// Audio players ask for part of a file to seek, and iPhones insist on it.
async function partOf(request, response) {
  const asked = response && /^bytes=(\d*)-(\d*)$/.exec(request.headers.get("range") || "");
  if (!asked) return response;
  const bytes = await response.arrayBuffer();
  const size = bytes.byteLength;
  const start = asked[1] ? Number(asked[1]) : Math.max(size - Number(asked[2]), 0);
  const end = asked[1] && asked[2] ? Math.min(Number(asked[2]), size - 1) : size - 1;
  if (start >= size || start > end) {
    return new Response(null, { status: 416, headers: { "Content-Range": `bytes */${size}` } });
  }
  return new Response(bytes.slice(start, end + 1), { status: 206, headers: {
    "Content-Type": response.headers.get("Content-Type") || "application/octet-stream",
    "Content-Range": `bytes ${start}-${end}/${size}`,
    "Content-Length": String(end - start + 1), "Accept-Ranges": "bytes",
  } });
}

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
  await cache.put(request, await sealed(response.clone()));
  trimCache(PAGES_CACHE, MAX_PAGES);
}

async function cachedPath(pathname) {
  const library = await caches.open(LIBRARY_CACHE);
  const synced = await unsealed(await library.match(self.location.origin + pathname));
  if (synced) return synced;
  const cache = await caches.open(PAGES_CACHE);
  const keys = await cache.keys();
  const key = keys.find((item) => new URL(item.url).pathname === pathname);
  return key ? unsealed(await cache.match(key)) : null;
}

async function cachedPage(request) {
  const cache = await caches.open(PAGES_CACHE);
  const pathname = new URL(request.url).pathname;
  const page = (await unsealed(await cache.match(request, { ignoreSearch: true }))) || (await cachedPath(pathname));
  if (page) return page;
  // The app and the installed web app open on "/", which only redirects:
  // offline, open the learner's dashboard instead.
  if (pathname === "/") return cachedPath(HOME_PATH);
  return null;
}

async function clearLibrary() {
  await caches.delete(LIBRARY_CACHE);
  await caches.delete(LIBRARY_MEDIA);
  await indexClear();
}

async function clearLearnerData() {
  await caches.delete(PAGES_CACHE);
  await caches.delete(MEDIA_CACHE);
  await clearLibrary();
  await clearProgressQueue();
  await forgetSealKey();
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
  await cache.put(key, await sealed(response));
  trimCache(MEDIA_CACHE, MAX_MEDIA);
}

async function libraryMedia(url) {
  return unsealed(await (await caches.open(LIBRARY_MEDIA)).match(mediaKey(url)));
}

async function matchMedia(url) {
  const cache = await caches.open(MEDIA_CACHE);
  return (await libraryMedia(url)) || (await unsealed(await cache.match(mediaKey(url)))) ||
    unsealed(await cache.match(url));
}

// Our own pictures and audio: keep what the learner has seen.
async function cacheMedia(request) {
  const cache = await caches.open(MEDIA_CACHE);
  const cached = (await libraryMedia(request.url)) || (await unsealed(await cache.match(request)));
  if (cached) return partOf(request, cached);
  try {
    const response = await fetch(request);
    if (response.ok && response.type === "basic" && !request.headers.has("range")) {
      await putMedia(request.url, response.clone());
    }
    return response;
  } catch (error) {
    return Response.error();
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
    return (await partOf(request, await matchMedia(request.url))) || Response.error();
  }
}

// Used by a sync: fetch a picture or recording and keep it in the library.
async function downloadMedia(address) {
  const key = mediaKey(address);
  const cache = await caches.open(LIBRARY_MEDIA);
  if (await cache.match(key)) return true;
  try {
    // A readable (CORS) copy, which plays back offline everywhere. Files on
    // R2 need the bucket's CORS rule for this (MOBILE_APP_GUIDE.md, section 11).
    const sameSite = new URL(address).origin === self.location.origin;
    const response = await fetch(address, sameSite ? { credentials: "include" } : { mode: "cors", credentials: "omit" });
    if (!response.ok) return false;
    await cache.put(key, await sealed(response));
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

// Never kept, whatever the list says: actions, searches, live or one-off pages.
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

function mediaIn(html, base) {
  const media = [];
  const source = /<(?:img|audio|source)\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/gi;
  let match;
  while ((match = source.exec(html))) {
    try { media.push(new URL(decodeEntities(match[1]), base)); } catch (error) { /* not an address */ }
  }
  return media.filter((url) => (url.origin === self.location.origin && !url.pathname.startsWith(STATIC_PREFIX)) ||
    isRemoteMedia(url));
}

async function tellClients(message) {
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  clients.forEach((client) => client.postMessage(message));
}

// ---------------------------------------------------------------- library

function openIndex() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(LIBRARY_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("pages")) request.result.createObjectStore("pages", { keyPath: "p" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function indexChange(change) {
  const db = await openIndex();
  await new Promise((resolve, reject) => {
    const tx = db.transaction("pages", "readwrite");
    change(tx.objectStore("pages"));
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

const indexPut = (entry) => indexChange((store) => store.put(entry));
const indexDelete = (paths) => indexChange((store) => paths.forEach((path) => store.delete(path)));
const indexClear = () => indexChange((store) => store.clear()).catch(() => {});

async function indexAll() {
  const db = await openIndex();
  const entries = await new Promise((resolve, reject) => {
    const request = db.transaction("pages", "readonly").objectStore("pages").getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
  db.close();
  return entries;
}

// A sync runs in steps: the page (static/js/offline_sync.js) asks for one
// step at a time and hands back where it got to. Browsers stop a service
// worker that works on one job for too long, so each step is short. A sync
// that's cut off loses nothing: the index knows what arrived, so the next
// one carries on from there.
async function newDownload(options) {
  const state = {
    media: Boolean(options && options.media),
    limit: Number(options && options.limit) || 0,
    todo: [], stale: [],
    pages: 0, media_kept: 0, skipped: 0, failed: 0, remaining: 0, done: false, stopped: "",
  };
  const stop = (why) => { state.stopped = why; state.done = true; return state; };
  let response;
  try {
    response = await fetch(MANIFEST_URL, { credentials: "include", headers: { Accept: "application/json" } });
  } catch (error) {
    return stop("offline");
  }
  if (response.status === 401) return stop("signed-out");
  if (!response.ok) return stop("error");
  const manifest = await response.json();
  // Their access has ended: nothing to fetch, and what's here is left alone.
  if (!manifest.access) return stop("no-access");

  const kept = new Map((await indexAll()).map((entry) => [entry.p, entry]));
  const wanted = manifest.pages.filter((page) => followable(new URL(page.p, self.location.origin)));
  for (const page of wanted) {
    const here = kept.get(page.p);
    // A page with no version shows the learner's progress: always fetched.
    if (!page.v || !here || here.v !== page.v || (state.media && here.pending)) state.todo.push([page.p, page.v]);
  }
  if (state.limit) {
    state.todo = state.todo.slice(0, state.limit);       // part of a sync: nothing is removed
  } else {
    const paths = new Set(wanted.map((page) => page.p));
    state.stale = [...kept.keys()].filter((path) => !paths.has(path));
  }
  state.remaining = state.todo.length;
  return state;
}

async function syncPage(state, [path, version]) {
  const address = new URL(path, self.location.origin);
  let response;
  try {
    response = await fetch(address.href, { credentials: "include", redirect: "follow", headers: { Accept: "text/html" } });
  } catch (error) {
    state.failed += 1;
    if (!navigator.onLine) state.stopped = "offline";
    return;
  }
  const finalUrl = new URL(response.url || address.href);
  if (finalUrl.pathname.startsWith("/accounts/login/")) { state.stopped = "signed-out"; return; }
  // A lesson they haven't reached yet sends them back: a later sync gets it.
  const movedOn = version && response.redirected && finalUrl.pathname !== address.pathname;
  if (movedOn || !response.ok || isSensitive(finalUrl.pathname) ||
      !(response.headers.get("Content-Type") || "").includes("text/html")) {
    state.skipped += 1;
    return;
  }
  const html = await response.text();
  // Stored under the address that was asked for, so it opens offline even
  // if the server redirected to it (a dashboard, say).
  await (await caches.open(LIBRARY_CACHE)).put(address.origin + address.pathname, await sealed(new Response(html, {
    status: 200, headers: { "Content-Type": response.headers.get("Content-Type") || "text/html; charset=utf-8" },
  })));
  state.pages += 1;
  await Promise.all(staticFilesIn(html).map(downloadStatic));

  const media = mediaIn(html, finalUrl.href);
  let pending = media.length > 0 && !state.media;
  if (state.media) {
    for (const url of media) {
      if (await downloadMedia(url.href)) state.media_kept += 1;
      else { pending = true; state.failed += 1; }
    }
  }
  await indexPut({ p: path, v: version, media: media.map((url) => mediaKey(url.href)), pending });
}

// Pages that have gone, and the files only they used.
async function tidyLibrary(state) {
  if (state.stale.length) {
    const cache = await caches.open(LIBRARY_CACHE);
    await Promise.all(state.stale.map((path) => cache.delete(self.location.origin + path)));
    await indexDelete(state.stale);
  }
  const used = new Set((await indexAll()).flatMap((entry) => entry.media || []));
  const media = await caches.open(LIBRARY_MEDIA);
  await Promise.all((await media.keys()).filter((key) => !used.has(key.url)).map((key) => media.delete(key)));
}

async function downloadStep(state, stepPages) {
  // Two pages at a time: quick on Wi-Fi, gentle on the server.
  for (let done = 0; state.todo.length && !state.stopped && done < stepPages; done += 2) {
    await Promise.all(state.todo.splice(0, 2).map((page) => syncPage(state, page)));
  }
  state.remaining = state.todo.length;
  state.done = Boolean(state.stopped) || !state.todo.length;
  if (state.done && !state.stopped && !state.limit) await tidyLibrary(state);
  return state;
}

// For tests and simple callers: a whole sync in one go.
async function runDownload(options) {
  let state = await newDownload(options);
  while (!state.done) state = await downloadStep(state, 10);
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
  const body = await sealBytes(await request.clone().arrayBuffer());
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
      let body;
      try {
        body = await openBytes(job.body);
      } catch (error) {  // sealed with a key that's gone: it can't be sent
        dropped += 1;
        await remove(job.id);
        continue;
      }
      let response;
      try {
        response = await fetch(job.url, { method: job.method, headers: job.headers, body,
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
      const keys = [...await (await caches.open(PAGES_CACHE)).keys(), ...await (await caches.open(LIBRARY_CACHE)).keys()];
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
      const count = async (name) => (await (await caches.open(name)).keys()).length;
      port.postMessage({
        pages: (await count(PAGES_CACHE)) + (await count(LIBRARY_CACHE)),
        media: (await count(MEDIA_CACHE)) + (await count(LIBRARY_MEDIA)),
        pending: await countQueue(),
      });
    })());
  }
  // One step of a lesson download; the answer carries where to carry on.
  if (data && data.type === "offline-download" && port) {
    event.waitUntil((async () => {
      let state = data.state;
      try {
        state = state || await newDownload(data);
        port.postMessage(state.done ? state : await downloadStep(state, 10));
      } catch (error) {
        port.postMessage({ ...(state || { pages: 0, media_kept: 0 }), stopped: "error", done: true });
      }
    })());
  }
  if (data && data.type === "offline-clear") {
    event.waitUntil((async () => {
      await caches.delete(PAGES_CACHE);
      await caches.delete(MEDIA_CACHE);
      await clearLibrary();
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
          if (response.ok) await keepPage(request, response);
          return response;
        }).catch(async () => (await cachedPage(request)) || caches.match(OFFLINE_URL))
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
