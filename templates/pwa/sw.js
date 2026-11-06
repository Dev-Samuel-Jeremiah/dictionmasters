/*
 * Diction Masters service worker (apps/landing/pwa.py explains the plan).
 *
 *   pages        learner pages are tried from the server first and kept
 *                on this device for offline study. Admin, billing and
 *                account-entry pages are never cached. Logging out clears
 *                the learner's pages and queued progress from this device;
 *                the pictures and audio stay, sealed, since they hold nothing
 *                personal and take the longest to fetch again.
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
 *   learners     on a shared tablet each learner's pages, their list and their
 *                waiting progress are kept apart, sealed with that learner's
 *                own key (from the server: apps/offline/views.py, learner),
 *                and locked again when they log out. Pictures, recordings and
 *                videos are shared: there's nothing personal in them.
 *   signing in   with no connection, the log-in page lists the learners
 *                remembered on this device ("Remember me"); tapping a name
 *                opens their lessons. Back online, the site is brought round
 *                to the same person before anyone carries on.
 *   access       kept lessons open offline until the learner's plan ends, or
 *                for OFFLINE_ACCESS_DAYS (Django settings) after the app last
 *                checked in, whichever comes first, connected or not. Past
 *                that they stay stored, sealed, and open again as soon as the
 *                app connects with a plan running. Saved videos follow the
 *                same record (static/js/offline_video.js).
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
const LOGIN_PATH = "/accounts/login/";
const SWITCH_PATH = "/accounts/switch/";
const REMOVE_PATH = "/accounts/switch/remove/";
const FORGET_PATH = "/accounts/switch/forget/";
const SIGN_IN_PATH = "/offline-sync/sign-in/";   // answered here only: the offline sign-in screen's taps
const HOME_PATH = "/accounts/dashboard/";
const QUEUE_DB = "dm-offline-sync";
const MAX_PAGES = 500;
const MAX_MEDIA = 800;
// The library: what a sync keeps, apart from the pages and media kept in
// passing above, so those limits never trim it. Its index says which version
// of each page is here, and which files that page uses.
const LIBRARY_CACHE = "dm-library";
const LIBRARY_MEDIA = "dm-library-media";
const LIBRARY_STATIC = "dm-library-static";
const LIBRARY_DB = "dm-library-index";
const KEY_DB = "dm-offline-key";
const MANIFEST_URL = "/offline-sync/manifest/";
const LEARNER_URL = "/offline-sync/learner/";
const MAX_LEARNERS = 12;      // learners whose lessons one device keeps; the longest unseen go first

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

// Pages where opening them counts as progress (apps/offline/copies.py): an
// EchoSpell group or card, a Tricks or 44 Academy tab, a step of a Learning
// Modules day. Opened offline, the visit waits in the queue and is made again
// once back online, in order, so the site records it just as it happened.
const COUNTED_VISITS = [
  /^\/echospell\/[^/]+\/[^/]+\/([^/]+\/)?$/,
  /^\/(tricks\/lessons|book\/44-academy)\/[^/]+\/([^/]+\/)?$/,
  /^\/learning-modules\/[^/]+\/[^/]+\/[^/]+\/[^/]+\/$/,
];

function countsAsVisit(pathname) {
  return COUNTED_VISITS.some((pattern) => pattern.test(pathname)) && !/\/(activities|assessment)\/[^/]+\/$/.test(pathname);
}

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
        name !== LIBRARY_STATIC && !/^dm-l\d+-/.test(name) && !keepStatic.has(name)).map((name) => caches.delete(name)));
      // A device that met its learner before this could move their old
      // downloads (see "learners") does it now.
      await adoptOldDownloads(await currentLearner()).catch(() => {});
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

// Sealed with a learner's own key (their pages and progress), or else this
// device's (pictures, recordings, and anything from before learners).
async function sealBytes(bytes, key) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const secret = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key || await sealKey(), bytes);
  const out = new Uint8Array(iv.length + secret.byteLength);
  out.set(iv);
  out.set(new Uint8Array(secret), iv.length);
  return out;
}

async function openBytes(bytes, key) {
  const all = new Uint8Array(bytes);
  return crypto.subtle.decrypt({ name: "AES-GCM", iv: all.slice(0, 12) }, key || await sealKey(), all.slice(12));
}

// The original type travels beside the sealed bytes: "text/html" gives
// nothing away, and the browser needs it back to show the page.
async function sealed(response, key) {
  return new Response(await sealBytes(await response.arrayBuffer(), key), {
    status: 200, headers: { "X-DM-Type": response.headers.get("Content-Type") || "application/octet-stream" },
  });
}

// What was stored, readable again; null if nothing was, if it can't be
// opened (the key has gone), or if offline access has run out — each
// treated just like not having it.
async function unsealed(kept, key) {
  if (!kept || !(await accessOpen())) return null;
  try {
    const bytes = await openBytes(await kept.arrayBuffer(), key);
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

// ---------------------------------------------------------------- learners

// {p: "learner", id, key}: the learner whose stores are open, with their key
// (usable, never readable). Set when the site says who's signed in, or when
// they sign in offline by tapping their name; gone when they log out, which
// locks their stores until they're back.
//
// {p: "kept:<id>", id, key, name, initials}: the people remembered on this
// device ("Remember me", apps/accounts/switcher.py), whose keys stay when
// they sign out so they can sign in again offline. The site says who they
// are (apps/offline/views.py, learner_info): an account whose password has
// changed is never among them. An admin may be: offline that opens only the
// lessons kept here, never the control room, and back online the site asks
// for their password before switching to them. Nothing here checks a
// password, so there is no password, or anything like one, to copy.
let learnerNow;

function fromBase64(text) {
  const raw = atob(text);
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

async function currentLearner() {
  if (learnerNow === undefined) learnerNow = (await keyStore("readonly", (store) => store.get("learner")).catch(() => null)) || null;
  return learnerNow;
}

// Where a learner's things are kept; with nobody signed in, the device's own
// stores (and anything from before learners).
function storesOf(learner) {
  if (!learner) {
    return { id: null, key: null, pages: PAGES_CACHE, library: LIBRARY_CACHE, index: LIBRARY_DB, queue: QUEUE_DB, access: "access" };
  }
  const name = `dm-l${learner.id}`;
  return { id: String(learner.id), key: learner.key, pages: `${name}-pages`, library: `${name}-library`,
           index: `${name}-index`, queue: `${name}-queue`, access: `access:${learner.id}` };
}

async function stores() {
  return storesOf(await currentLearner());
}

async function knownLearners() {
  const kept = await keyStore("readonly", (store) => store.get("learners")).catch(() => null);
  return (kept && kept.ids) || [];
}

// Who the site says is signed in, with their key; null offline or signed out.
async function fetchLearner() {
  try {
    const response = await fetch(LEARNER_URL, { credentials: "include", headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const answer = await response.json();
    return answer.ok ? answer : null;
  } catch (error) {
    return null;
  }
}

function learnerKey(secret) {
  return crypto.subtle.importKey("raw", fromBase64(secret), "AES-GCM", false, ["encrypt", "decrypt"]);
}

// Open this learner's stores (and lock whoever's were open), as the site
// says who they are.
async function useLearner(info) {
  const current = await currentLearner();
  const same = current && current.id === String(info.id);
  const key = same ? current.key : await learnerKey(info.secret);
  await keepLearners(info, key);
  return same ? current : openLearner(String(info.id), key);
}

async function openLearner(id, key) {
  learnerNow = { p: "learner", id, key };
  await keyStore("readwrite", (store) => store.put(learnerNow));
  await adoptOldDownloads(learnerNow);
  const ids = [learnerNow.id, ...(await knownLearners()).filter((id) => id !== learnerNow.id)];
  // Room for so many learners' lessons: the longest unseen give theirs up
  // (their waiting progress stays, to be sent when they're back).
  for (const id of ids.slice(MAX_LEARNERS)) {
    const old = storesOf({ id });
    await caches.delete(old.pages);
    await caches.delete(old.library);
    await indexClear(old.index);
    await forgetLearner(id);
  }
  await keyStore("readwrite", (store) => store.put({ p: "learners", ids }));
  return learnerNow;
}

// Lessons saved before each learner had their own stores sit in the
// device's stores, sealed with the device's key. They belong to whoever was
// signed in then (signing out used to delete them), which is the first
// learner the app meets: they move into that learner's stores, sealed
// again with their key, so nothing has to be downloaded again.
let adopting = null;

function adoptOldDownloads(learner) {
  adopting = adopting || (async () => {
    if (!learner || !(await caches.has(LIBRARY_CACHE) || await caches.has(PAGES_CACHE))) return;
    const into = storesOf(learner);
    for (const [from, to] of [[LIBRARY_CACHE, into.library], [PAGES_CACHE, into.pages]]) {
      if (!(await caches.has(from))) continue;
      const old = await caches.open(from);
      const fresh = await caches.open(to);
      for (const request of await old.keys()) {
        if (await fresh.match(request)) continue;            // theirs already, and newer
        const kept = await old.match(request);
        try {
          const bytes = await openBytes(await kept.arrayBuffer());
          await fresh.put(request, await sealed(new Response(bytes, {
            headers: { "Content-Type": kept.headers.get("X-DM-Type") || "text/html; charset=utf-8" },
          }), learner.key));
        } catch (error) { /* unreadable: left behind, fetched again at the next sync */ }
      }
    }
    const entries = await indexAll(LIBRARY_DB).catch(() => []);
    if (entries.length) {
      const have = new Set((await indexAll(into.index).catch(() => [])).map((entry) => entry.p));
      await indexChange((store) => entries.filter((entry) => !have.has(entry.p)).forEach((entry) => store.put(entry)), into.index);
    }
    const access = await keyStore("readonly", (store) => store.get("access")).catch(() => null);
    const theirs = await keyStore("readonly", (store) => store.get(into.access)).catch(() => null);
    if (access && !theirs) await keyStore("readwrite", (store) => store.put({ ...access, p: into.access }));
    await caches.delete(LIBRARY_CACHE);
    await caches.delete(PAGES_CACHE);
    await indexClear(LIBRARY_DB);
    await keyStore("readwrite", (store) => store.delete("access")).catch(() => {});
    accessName = null;
  })().finally(() => { adopting = null; });
  return adopting;
}

// The people who may sign in here offline, the most recently seen first.
async function keptLearners() {
  const all = (await keyStore("readonly", (store) => store.getAll()).catch(() => null)) || [];
  const kept = all.filter((record) => record.p.startsWith("kept:"));
  const order = await knownLearners();
  const at = (one) => (order.includes(one.id) ? order.indexOf(one.id) : order.length);
  return kept.sort((a, b) => at(a) - at(b));
}

async function forgetLearner(id) {
  await keyStore("readwrite", (store) => store.delete(`kept:${id}`)).catch(() => {});
}

// Keep this learner's key if they're remembered on this device, and let go
// of anyone's who isn't any more (taken off the device, a password changed).
async function keepLearners(info, key) {
  if (!Array.isArray(info.device)) return;
  const device = info.device.map(String);
  const id = String(info.id);
  for (const one of await keptLearners()) {
    if (!device.includes(one.id)) await forgetLearner(one.id);
  }
  if (device.includes(id)) {
    await keyStore("readwrite", (store) => store.put({
      p: `kept:${id}`, id, key, name: String(info.name || "Learner"), initials: String(info.initials || ""),
    }));
  }
}

async function lockLearner() {
  learnerNow = null;
  await keyStore("readwrite", (store) => store.delete("learner")).catch(() => {});
}

function pageLearner(html) {
  const mark = /data-learner="(\d+)"/.exec(html.slice(0, 4000));
  return mark ? mark[1] : null;
}

// Whose page is this? The site marks every signed-in page with the learner
// (templates/base.html, data-learner). A page for someone else than the
// learner whose stores are open (they signed in as someone else) opens
// theirs; a page with no mark goes where the current stores are.
async function storesForPage(html) {
  const mark = pageLearner(html);
  if (!mark) return stores();
  const me = await currentLearner();
  if (me && me.id === mark) {
    refreshLearner(mark);
    return storesOf(me);
  }
  const who = await fetchLearner();
  return who && String(who.id) === mark ? storesOf(await useLearner(who)) : null;
}

// Once in a while (each time the worker starts), ask who is remembered on
// this device, so a learner who has just ticked "Remember me" can sign in
// offline straight away, not only after their next sync.
const refreshed = new Set();

function refreshLearner(id) {
  if (refreshed.has(id)) return;
  refreshed.add(id);
  fetchLearner().then((who) => (who && String(who.id) === id ? useLearner(who) : null)).catch(() => {});
}

// ---------------------------------------------------------- signing in

// Offline, the log-in page lists the people remembered here: tapping a name
// opens their lessons. The site doesn't know yet, so {p: "pending-sign-in",
// id, name} keeps it (id "" for signing out offline). Back online, the
// first page from the site finishes it: signed in as them already, nothing
// to do; anyone else, and the app asks before going on (finishSignInPage),
// so nobody carries on in someone else's account.
async function pendingSignIn() {
  return (await keyStore("readonly", (store) => store.get("pending-sign-in")).catch(() => null)) || null;
}

async function setPendingSignIn(id, name) {
  await keyStore("readwrite", (store) => store.put({ p: "pending-sign-in", id, name })).catch(() => {});
}

async function clearPendingSignIn() {
  await keyStore("readwrite", (store) => store.delete("pending-sign-in")).catch(() => {});
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
}

function shell(title, body, status = 200) {
  const html = '<!DOCTYPE html><html lang="en-gb"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1"><title>' + title + '</title><style>' +
    'body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F2F5FC;color:#0B1A4A;' +
    'font:16px/1.5 system-ui,sans-serif;padding:24px 16px;box-sizing:border-box}' +
    'main{width:100%;max-width:440px;text-align:center}h1{font-size:24px;margin:8px 0}p{color:#55607E}' +
    'ul{list-style:none;margin:20px 0;padding:0;display:grid;gap:12px}form{margin:0}' +
    '.who{display:flex;align-items:center;gap:14px;width:100%;min-height:64px;padding:10px 16px;border:0;' +
    'border-radius:16px;background:#fff;box-shadow:0 2px 10px rgba(11,26,74,.1);color:#0B1A4A;' +
    'font:700 17px system-ui,sans-serif;text-align:left;cursor:pointer}' +
    '.who:focus-visible,.go:focus-visible{outline:3px solid #0B1A4A;outline-offset:2px}' +
    '.face{flex:none;display:grid;place-items:center;width:44px;height:44px;border-radius:50%;' +
    'background:#FFC72C;font-size:16px}.name{flex:1;min-width:0;overflow-wrap:anywhere}' +
    '.note{display:block;font:500 13px system-ui,sans-serif;color:#8A4B00}' +
    '.go{display:inline-block;min-height:56px;box-sizing:border-box;border:0;border-radius:99px;' +
    'background:#FFC72C;color:#0B1A4A;font:800 16px system-ui,sans-serif;padding:16px 30px;cursor:pointer;margin:6px}' +
    '.go--plain{background:#fff;box-shadow:inset 0 0 0 2px #0B1A4A}</style></head><body><main>' + body + '</main></body></html>';
  return new Response(html, { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

// Is this learner's offline access closed (see "access")? Shown on their name.
async function accessClosed(id) {
  const record = await keyStore("readonly", (store) => store.get(`access:${id}`)).catch(() => null);
  return Boolean(record) && Math.max(Date.now(), record.seen || 0) >= record.until;
}

// The log-in page with no connection: tap your name.
async function signInPage() {
  const people = await keptLearners();
  if (!people.length) {
    return shell("Sign in", '<p style="font-size:44px;margin:0">&#128246;</p><h1>Connect to sign in</h1>' +
      '<p>Nobody can sign in on this device without the internet yet. Sign in once while connected, ' +
      'with <strong>Remember me on this device</strong> ticked, and next time you can sign in here offline.</p>' +
      '<button class="go" onclick="location.reload()">Try again</button>');
  }
  const rows = [];
  for (const one of people) {
    const closed = await accessClosed(one.id);
    rows.push('<li><form method="post" action="' + SIGN_IN_PATH + '"><input type="hidden" name="user" value="' +
      escapeHtml(one.id) + '"><button class="who" type="submit"><span class="face" aria-hidden="true">' +
      escapeHtml(one.initials || one.name.slice(0, 1)) + '</span><span class="name">' + escapeHtml(one.name) +
      (closed ? '<span class="note">Connect once to open your lessons</span>' : '') +
      '</span><span aria-hidden="true">&rsaquo;</span></button></form></li>');
  }
  return shell("Who is learning?", '<p style="font-size:44px;margin:0">&#128075;</p><h1>Who is learning?</h1>' +
    '<p>You are offline. Tap your name to open your lessons.</p><ul>' + rows.join("") + '</ul>' +
    '<p style="font-size:14px">Not here? Connect to the internet to sign in with your password.</p>');
}

// A name tapped offline (on the sign-in screen, or the account switcher on a
// kept dashboard): open their lessons, if they're remembered here.
async function signInOffline(request) {
  let id = "";
  try {
    id = String((await request.formData()).get("user") || "");
  } catch (error) { /* not a form: nobody */ }
  const one = (await keptLearners()).find((person) => person.id === id);
  if (!one) {
    return shell("Connect to sign in", '<p style="font-size:44px;margin:0">&#128246;</p><h1>Connect to sign in</h1>' +
      '<p>This account needs the internet to sign in. Connect, then try again.</p>' +
      '<button class="go" onclick="history.back()">Go back</button>', 503);
  }
  await openLearner(one.id, one.key);
  await setPendingSignIn(one.id, one.name);
  return Response.redirect(self.location.origin + HOME_PATH, 303);
}

// Back online, the site sent a page for someone other than who signed in
// (or out) here offline: finish that first. Needs the site's security
// token, so with none (still half-connected), the page is shown as it is.
async function finishSignInPage(pending) {
  const who = await fetchLearner();
  if (!who) return null;
  const token = '<input type="hidden" name="csrfmiddlewaretoken" value="' + escapeHtml(who.token) + '">';
  const signOut = '<form method="post" action="' + LOGOUT_PATH + '" style="display:inline">' + token;
  if (!pending.id) {
    return shell("Signing out", '<p style="font-size:44px;margin:0">&#128075;</p><h1>Finishing signing out</h1>' +
      '<p>Someone signed out of this device while it was offline.</p>' + signOut +
      '<button class="go" type="submit">Carry on</button></form><script>document.forms[0].submit()</script>');
  }
  const name = escapeHtml(pending.name || "you");
  return shell("Welcome back", '<p style="font-size:44px;margin:0">&#127881;</p><h1>Welcome back online</h1>' +
    '<p><strong>' + name + '</strong> signed in on this device while it was offline. Carry on as ' + name + '?</p>' +
    '<form method="post" action="' + SWITCH_PATH + '" style="display:inline">' + token +
    '<input type="hidden" name="user" value="' + escapeHtml(pending.id) + '">' +
    '<button class="go" type="submit">Yes, I am ' + name + '</button></form>' + signOut +
    '<button class="go go--plain" type="submit">Someone else</button></form>');
}

// Did the last page come from this device because the site couldn't be
// reached? Browsers often still say "online" on Wi-Fi with no internet.
let servedOffline = false;

// Offline, a page this device hasn't saved: say which, and what still works.
const ONLINE_ONLY = [
  [/^\/tutor\//, "The AI tutor"],
  [/^\/clash\//, "Clash"],
  [/^\/search\//, "Search"],
  [/^\/notifications\//, "Notifications"],
  [/^\/learning-tools\/book-scanner\//, "The book scanner"],
  [/^\/accounts\//, "Your account settings"],
  [/^\/assessments\/(?!results\/|type\/|$)/, "Taking a test"],
  [/^\/app\//, "Getting the app"],
];

function notSavedPage(pathname) {
  const online = ONLINE_ONLY.find(([pattern]) => pattern.test(pathname));
  const heading = online ? `${online[1]} needs the internet` : "This page isn't on this device yet";
  const words = online ? "Connect to the internet, then try again. Your saved lessons still work offline." :
    "It wasn't saved for offline use. Connect to the internet to open it; your saved lessons still work offline.";
  return shell(heading, '<p style="font-size:44px;margin:0">&#128246;</p><h1>' + escapeHtml(heading) + '</h1>' +
    '<p>' + words + '</p><button class="go" onclick="history.length > 1 ? history.back() : location.assign(\'' +
    HOME_PATH + '\')">Go back</button><a class="go go--plain" href="' + HOME_PATH + '" style="text-decoration:none">' +
    'My dashboard</a><p style="margin-top:18px"><a href="' + OFFLINE_PAGE + '" style="color:#1846E0;font-weight:700">' +
    'Saved videos</a></p>', 503);
}

// Signing out with no connection: their lessons lock now, and the site is
// told once the device is back online (see finishSignInPage).
async function signOutOffline() {
  await clearLearnerData();
  await setPendingSignIn("", "");
  return Response.redirect(self.location.origin + LOGIN_PATH, 303);
}

// The site took a form (signed in, switched, signed out): it redirects.
function wentThrough(response) {
  return response.type === "opaqueredirect" || response.redirected || (response.status >= 300 && response.status < 400);
}

// The site's answer to a page, unless a sign-in made offline is still to be
// finished (see above).
async function settleSignIn(response) {
  const pending = await pendingSignIn();
  if (!pending || !response.ok || response.redirected) return null;
  if (!(response.headers.get("Content-Type") || "").includes("text/html")) return null;
  const mark = pageLearner(await response.clone().text());
  if (!mark) return null;          // the log-in page, say: it lists who can carry on
  if (mark === pending.id) {
    await clearPendingSignIn();
    return null;
  }
  return finishSignInPage(pending);
}

// ---------------------------------------------------------------- access

// {p: "access", until, seen}, one per learner: open until when, and the
// latest time this device has shown. Winding the clock back doesn't reopen
// anything: the later of now and "seen" is what counts. No record yet
// (nothing synced, or pages kept before this existed) means open.
let accessRecord;
let accessName;

async function readAccess() {
  const name = (await stores()).access;
  if (accessName !== name) {
    accessName = name;
    accessRecord = (await keyStore("readonly", (store) => store.get(name)).catch(() => null)) || null;
  }
  return accessRecord;
}

async function writeAccess(record) {
  accessName = record.p;
  accessRecord = record;
  await keyStore("readwrite", (store) => store.put(record)).catch(() => {});
}

// After every check-in: open for that many days from now, but never past
// the end of their plan; or closed.
async function grantAccess(days, planEnds) {
  const now = Date.now();
  let until = days > 0 ? now + days * 86400000 : 0;
  if (until && typeof planEnds === "number") until = Math.min(until, planEnds);
  await writeAccess({ p: (await stores()).access, until, seen: now });
}

async function accessOpen() {
  const record = await readAccess();
  if (!record) return true;
  const now = Math.max(Date.now(), record.seen || 0);
  if (now > (record.seen || 0) + 3600000) await writeAccess({ ...record, seen: now });
  return now < record.until;
}

// Shown in place of a kept lesson once the app has been offline too long.
function connectAgainPage() {
  const html = '<!DOCTYPE html><html lang="en-gb"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect to keep learning</title></head>' +
    '<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#F2F5FC;color:#0B1A4A;' +
    'font:16px/1.5 system-ui,sans-serif;text-align:center;padding:24px">' +
    '<main style="max-width:440px"><p style="font-size:44px;margin:0">&#128246;</p>' +
    '<h1 style="font-size:22px">Connect to the internet once</h1>' +
    '<p style="color:#55607E">Your lessons are still saved on this device. It has been a while since the app last ' +
    'connected, so it needs to check your account before they open again. Connect for a moment and they\'ll be back.</p>' +
    '<button onclick="location.reload()" style="border:0;border-radius:99px;background:#FFC72C;color:#0B1A4A;' +
    'font:800 16px system-ui;padding:14px 30px">Try again</button></main></body></html>';
  return new Response(html, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });
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
  const html = await response.clone().text();
  const where = await storesForPage(html);
  if (!where) return;
  const cache = await caches.open(where.pages);
  await cache.put(request, await sealed(new Response(html, {
    headers: { "Content-Type": response.headers.get("Content-Type") || "text/html; charset=utf-8" },
  }), where.key));
  trimCache(where.pages, MAX_PAGES);
}

async function cachedPath(pathname) {
  const where = await stores();
  const library = await caches.open(where.library);
  const synced = await unsealed(await library.match(self.location.origin + pathname), where.key);
  if (synced) return synced;
  const cache = await caches.open(where.pages);
  const keys = await cache.keys();
  const key = keys.find((item) => new URL(item.url).pathname === pathname);
  return key ? unsealed(await cache.match(key), where.key) : null;
}

async function cachedPage(request) {
  const where = await stores();
  const cache = await caches.open(where.pages);
  const { pathname, search } = new URL(request.url);
  const step = search && (await unsealed(await (await caches.open(where.library)).match(self.location.origin + pathname + search), where.key));
  if (step) return step;
  const page = (await unsealed(await cache.match(request, { ignoreSearch: true }), where.key)) || (await cachedPath(pathname));
  if (page) return page;
  // The app and the installed web app open on "/", which only redirects:
  // offline, open the learner's dashboard instead.
  if (pathname === "/") return cachedPath(HOME_PATH);
  return null;
}

// "Remove downloads": every learner's on this device, and the shared files.
// Waiting progress stays, to be sent.
async function clearLibrary() {
  for (const where of [storesOf(null), ...(await knownLearners()).map((id) => storesOf({ id }))]) {
    await caches.delete(where.library);
    await indexClear(where.index);
  }
  await caches.delete(LIBRARY_MEDIA);
  await caches.delete(LIBRARY_STATIC);
  await keyStore("readwrite", (store) => store.delete("pack-keys")).catch(() => {});
}

// The files a lesson pack brought (static/js/offline_pack.js): kept even
// before a sync reaches the lessons that use them, such as a Tricks lesson the
// learner hasn't got to yet.
async function packKeys() {
  const kept = await keyStore("readonly", (store) => store.get("pack-keys")).catch(() => null);
  return (kept && kept.keys) || [];
}

// Logging out: the learner's own stores are locked, not deleted, so their
// lessons and waiting progress are there when they're back, and nobody else
// on this device can open them. Pages kept from before learners (the
// device's own stores) go, as they always did. Pictures and recordings stay:
// there's nothing personal in them.
async function clearLearnerData() {
  await caches.delete(PAGES_CACHE);
  await caches.delete(MEDIA_CACHE);
  await caches.delete(LIBRARY_CACHE);
  await indexClear(LIBRARY_DB);
  await clearProgressQueue(QUEUE_DB);
  await lockLearner();
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

// The page's own stylesheets and scripts, so a kept page looks right offline.
// They stay until no kept page names them, however many site updates pass.
// The files a stylesheet uses itself: the stylesheets it imports, its
// pictures and fonts (the cat on EchoSpell's pages, say), or they're
// missing offline.
function filesInCss(text, path) {
  const base = new URL(path, self.location.origin);
  const found = [...text.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => {
    try { return new URL(match[1], base); } catch (error) { return null; }
  }).filter((url) => url && url.origin === self.location.origin && url.pathname.startsWith(STATIC_PREFIX));
  const imports = [...text.matchAll(/@import\s+["']([^"']+)["']/g)].map((match) => new URL(match[1], base))
    .filter((url) => url.origin === self.location.origin && url.pathname.startsWith(STATIC_PREFIX));
  return [...new Set([...found, ...imports].map((url) => url.pathname))];
}

// Keeps a file; answers with every file kept for it (a stylesheet's own
// pictures and fonts too), so the page's index names them all and tidying
// up leaves them be.
async function downloadStatic(path, seen = new Set()) {
  if (seen.has(path)) return [];                  // stylesheets importing each other
  seen.add(path);
  const cache = await caches.open(LIBRARY_STATIC);
  const css = /\.css(\?|$)/.test(path);
  try {
    let kept = await cache.match(path);
    if (!kept) {
      const response = await fetch(path);
      if (!response.ok) return [];
      await cache.put(path, response.clone());
      kept = response;
    }
    if (!css) return [path];
    const inside = await Promise.all(filesInCss(await kept.text(), path).map((file) => downloadStatic(file, seen)));
    return [path, ...inside.flat()];
  } catch (error) {
    return [];                       // try again next download
  }
}

// ---------------------------------------------------------- read-along

// A recording's measured word timings (static/js/read_along.js lights each
// word as it's spoken). Nothing personal: kept with the shared files, under
// the recording's own name, since the link's signature changes each time the
// page is made.
const READ_ALONG_PATH = "/book/read-along/";

function readAlongKey(url) {
  const u = new URL(url, self.location.origin);
  return self.location.origin + READ_ALONG_PATH + u.pathname.slice(READ_ALONG_PATH.length).split(":")[0] + "/";
}

function readAlongIn(html) {
  return [...html.matchAll(/data-ra-sync="([^"]+)"/g)].map((match) => decodeEntities(match[1]));
}

async function keepReadAlong(url, response) {
  const data = await response.clone().json().catch(() => null);
  if (data && data.status === "ready") await (await caches.open(LIBRARY_STATIC)).put(readAlongKey(url), response.clone());
}

// Answers with where it's kept (for the page's index), or nothing yet.
async function downloadReadAlong(url) {
  const cache = await caches.open(LIBRARY_STATIC);
  const key = readAlongKey(url);
  if (await cache.match(key)) return [key];
  try {
    const response = await fetch(new URL(url, self.location.origin).href, { credentials: "include", headers: { Accept: "application/json" } });
    if (response.ok) await keepReadAlong(url, response);
  } catch (error) { /* try again next download */ }
  return (await cache.match(key)) ? [key] : [];
}

async function readAlong(request) {
  try {
    const response = await fetch(request);
    if (response.ok) await keepReadAlong(request.url, response);
    return response;
  } catch (error) {
    const kept = await (await caches.open(LIBRARY_STATIC)).match(readAlongKey(request.url));
    // Not kept: say so once, rather than the page asking again and again.
    return kept || new Response(JSON.stringify({ status: "offline", retry: 0, words: [], speech: [] }),
      { status: 200, headers: { "Content-Type": "application/json" } });
  }
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

async function openIndex(name) {
  name = name || (await stores()).index;
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("pages")) request.result.createObjectStore("pages", { keyPath: "p" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function indexChange(change, name) {
  const db = await openIndex(name);
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
const indexClear = (name) => indexChange((store) => store.clear(), name).catch(() => {});

async function indexAll(name) {
  const db = await openIndex(name);
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
// Someone who can open every level chooses which to keep on this device
// (the Offline page; apps/offline/catalog.py, levels_for): kept per
// learner, so every download and video save asks for the same ones.
async function chosenLevels() {
  const name = `levels:${(await stores()).id || ""}`;
  const kept = await keyStore("readonly", (store) => store.get(name)).catch(() => null);
  return (kept && kept.levels) || [];
}

async function manifestUrl() {
  const levels = await chosenLevels();
  return levels.length ? `${MANIFEST_URL}?levels=${encodeURIComponent(levels.join(","))}` : MANIFEST_URL;
}

async function newDownload(options) {
  const state = {
    media: Boolean(options && options.media),
    limit: Number(options && options.limit) || 0,
    todo: [], stale: [],
    pages: 0, media_kept: 0, skipped: 0, failed: 0, remaining: 0, done: false, stopped: "",
    storage: true,
    files: [], queued: [],       // pictures and audio still to fetch, and every one ever queued
  };
  const stop = (why) => { state.stopped = why; state.done = true; return state; };
  let response;
  try {
    response = await fetch(await manifestUrl(), { credentials: "include", headers: { Accept: "application/json" } });
  } catch (error) {
    return stop("offline");
  }
  if (response.status === 401) return stop("signed-out");
  if (!response.ok) return stop("error");
  const manifest = await response.json();
  if (manifest.learner) await useLearner(manifest.learner);
  await grantAccess(manifest.access ? (manifest.offline_days ?? 90) : 0, manifest.access_ends);
  // Their access has ended: nothing to fetch, and what's here stays, closed.
  if (!manifest.access) return stop("no-access");

  // Files in the storage bucket can only be read once it allows the apps to:
  // until then they're left for a later sync.
  state.storage = manifest.storage_media !== false;
  const kept = new Map((await indexAll()).map((entry) => [entry.p, entry]));
  const wanted = manifest.pages.filter((page) => followable(new URL(page.p, self.location.origin)));
  for (const page of wanted) {
    const here = kept.get(page.p);
    // A page with no version shows the learner's progress: always fetched.
    if (!page.v || !here || here.v !== page.v || here.moved || (state.media && here.pending)) state.todo.push([page.p, page.v]);
  }
  if (state.limit) {
    state.todo = state.todo.slice(0, state.limit);       // part of a sync: nothing is removed
  } else {
    const paths = new Set(wanted.map((page) => page.p));
    state.stale = [...kept.keys()].filter((path) => !paths.has(path));
  }
  state.remaining = state.todo.length;
  state.videos = manifest.videos || [];
  await checkSpace(state, manifest, wanted.length);
  return state;
}

// Pictures and audio only if they'll fit. Pages take next to no room, so
// those still come; the files follow at a sync when there's space.
async function checkSpace(state, manifest, pages) {
  if (!state.media || !manifest.need_mb || !state.todo.length || !navigator.storage || !navigator.storage.estimate) return;
  const { quota = 0, usage = 0 } = await navigator.storage.estimate();
  const needed = Math.ceil(manifest.need_mb * state.todo.length / Math.max(pages, 1));
  if (quota && (quota - usage) / 1048576 < needed) {
    state.media = false;
    state.low_space_mb = needed;
  }
}

async function syncPage(state, [path, version]) {
  const address = new URL(path, self.location.origin);
  let response;
  try {
    // Marked as a copy (apps/offline/copies.py): fetching a page to keep
    // isn't the learner opening it, so it records no progress.
    response = await fetch(address.href, { credentials: "include", redirect: "follow",
      headers: { Accept: "text/html", "X-DM-Offline-Copy": "1" } });
  } catch (error) {
    state.failed += 1;
    if (!navigator.onLine) state.stopped = "offline";
    return;
  }
  const finalUrl = new URL(response.url || address.href);
  if (finalUrl.pathname.startsWith("/accounts/login/")) { state.stopped = "signed-out"; return; }
  // Turned away for now: a lesson they haven't reached ("finish this one
  // first"), or an activity before every part of its lesson was opened (sent
  // back up to the lesson). What the site shows instead is kept under this
  // address, as it would show online, and fetched again at every sync until
  // it opens. Sent along to a page beside or below (a lesson opening on its
  // first tab) is just where that address leads: kept, nothing to retry.
  const sentUp = response.redirected && finalUrl.pathname !== address.pathname &&
    address.pathname.startsWith(finalUrl.pathname);
  const turnedAway = Boolean(version) && (sentUp || response.status === 403);
  if ((!response.ok && !turnedAway) || isSensitive(finalUrl.pathname) ||
      !(response.headers.get("Content-Type") || "").includes("text/html")) {
    state.skipped += 1;
    return;
  }
  const html = await response.text();
  const where = await stores();
  const mark = /data-learner="(\d+)"/.exec(html.slice(0, 4000));
  if (mark && mark[1] !== where.id) { state.stopped = "switched"; return; }     // someone else signed in meanwhile
  // Stored under the address that was asked for, so it opens offline even
  // if the server redirected to it (a dashboard, say). A step of a lesson
  // (?step=2) is a page of its own.
  await (await caches.open(where.library)).put(address.origin + address.pathname + address.search, await sealed(new Response(html, {
    status: 200, headers: { "Content-Type": response.headers.get("Content-Type") || "text/html; charset=utf-8" },
  }), where.key));
  state.pages += 1;
  const statics = [...new Set([
    ...(await Promise.all(staticFilesIn(html).map((file) => downloadStatic(file)))).flat(),
    ...(await Promise.all(readAlongIn(html).map(downloadReadAlong))).flat(),
  ])];

  // The page's files are queued, not fetched here: one lesson can hold dozens
  // of recordings, and a step must stay short (downloadStep). Until they're
  // all here the page is "pending", so a cut-off sync fetches it again (with
  // fresh links) and carries on.
  const media = mediaIn(html, finalUrl.href);
  const keys = media.map((url) => mediaKey(url.href));
  if (state.media) {
    const queued = new Set(state.queued);
    for (const url of media) {
      const key = mediaKey(url.href);
      if (queued.has(key) || (!state.storage && isRemoteMedia(url))) continue;
      queued.add(key);
      state.queued.push(key);
      state.files.push(url.href);
    }
  }
  await indexPut({ p: path, v: version, media: keys, pending: keys.length > 0, statics, moved: turnedAway });
}

// After a whole sync: a page is no longer pending once all its files are here.
async function settlePending() {
  const here = new Set((await (await caches.open(LIBRARY_MEDIA)).keys()).map((key) => key.url));
  for (const entry of await indexAll()) {
    if (entry.pending && (entry.media || []).every((key) => here.has(key))) await indexPut({ ...entry, pending: false });
  }
}

// Every learner's list on this device, and the one from before learners.
async function everyonesEntries() {
  const names = [LIBRARY_DB, ...(await knownLearners()).map((id) => storesOf({ id }).index)];
  return (await Promise.all(names.map((name) => indexAll(name).catch(() => [])))).flat();
}

// Pages that have gone, and the files no learner on this device uses.
async function tidyLibrary(state) {
  if (state.stale.length) {
    const cache = await caches.open((await stores()).library);
    await Promise.all(state.stale.map((path) => cache.delete(self.location.origin + path)));
    await indexDelete(state.stale);
  }
  const entries = await everyonesEntries();
  const used = new Set([...entries.flatMap((entry) => entry.media || []), ...await packKeys()]);
  const media = await caches.open(LIBRARY_MEDIA);
  await Promise.all((await media.keys()).filter((key) => !used.has(key.url)).map((key) => media.delete(key)));
  const named = new Set(entries.flatMap((entry) => entry.statics || []).map((path) => new URL(path, self.location.origin).href));
  const statics = await caches.open(LIBRARY_STATIC);
  await Promise.all((await statics.keys()).filter((key) => !named.has(key.url)).map((key) => statics.delete(key)));
}

// One step of a sync: pages first, then their files, two at a time (quick
// on Wi-Fi, gentle on the server), for about STEP_MS at most (8 seconds), so the page
// hears back often and the browser never stops the worker mid-step. A file
// already started is finished; a very large one may run the step over.
const STEP_MS = 8000;

async function downloadStep(state, stepPages = 1000, budget = STEP_MS) {
  const until = Date.now() + budget;
  let worked = false;                      // every step moves on by at least one batch
  const timeLeft = () => !worked || Date.now() < until;
  for (let done = 0; state.todo.length && !state.stopped && done < stepPages && timeLeft(); done += 2) {
    await Promise.all(state.todo.splice(0, 2).map((page) => syncPage(state, page)));
    worked = true;
  }
  while (!state.todo.length && state.files.length && !state.stopped && timeLeft()) {
    worked = true;
    await Promise.all(state.files.splice(0, 2).map(async (address) => {
      if (await downloadMedia(address)) state.media_kept += 1;
      else state.failed += 1;
    }));
    if (!navigator.onLine) state.stopped = "offline";
  }
  state.remaining = state.todo.length + state.files.length;
  state.done = Boolean(state.stopped) || !state.remaining;
  if (state.done && !state.stopped) {
    await settlePending();
    if (!state.limit) await tidyLibrary(state);
  }
  return state;
}

// For tests and simple callers: a whole sync in one go.
async function runDownload(options) {
  let state = await newDownload(options);
  while (!state.done) state = await downloadStep(state);
  return state;
}

// ------------------------------------------------------------- progress

function openQueue(name = QUEUE_DB) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 1);
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
  const where = await stores();
  const body = await sealBytes(await request.clone().arrayBuffer(), where.key);
  const headers = {};
  request.headers.forEach((value, key) => { headers[key] = value; });
  const db = await openQueue(where.queue);
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

async function queueVisit(url) {
  const where = await stores();
  const db = await openQueue(where.queue);
  const waiting = await new Promise((resolve) => {
    const request = db.transaction("progress", "readonly").objectStore("progress").getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => resolve([]);
  });
  // The same page opened twice offline counts once.
  if (!waiting.some((job) => job.method === "GET" && job.url === url)) {
    const body = await sealBytes(new ArrayBuffer(0), where.key);
    await new Promise((resolve, reject) => {
      const tx = db.transaction("progress", "readwrite");
      tx.objectStore("progress").add({ url, method: "GET", headers: { accept: "text/html" }, body, created: Date.now() });
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
  db.close();
  try { await self.registration.sync.register("dm-learning-sync"); } catch (error) { /* foreground reconnect also syncs */ }
}

async function countQueue() {
  const db = await openQueue((await stores()).queue).catch(() => null);
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

// Signing in renews the site's security token, so progress kept before it
// would be refused (and lost). It's sent with the current token instead.
const CSRF_FIELD = new TextEncoder().encode('name="csrfmiddlewaretoken"\r\n\r\n');

function withToken(job, body, token) {
  const headers = { ...job.headers };
  if ("x-csrftoken" in headers) headers["x-csrftoken"] = token;
  const type = (headers["content-type"] || "").toLowerCase();
  let bytes = new Uint8Array(body);
  if (type.startsWith("application/x-www-form-urlencoded")) {
    const form = new URLSearchParams(new TextDecoder().decode(bytes));
    if (form.has("csrfmiddlewaretoken")) {
      form.set("csrfmiddlewaretoken", token);
      bytes = new TextEncoder().encode(form.toString());
    }
  } else if (type.startsWith("multipart/form-data")) {
    // Swap just the token's own part, byte for byte; a recording stays as it is.
    const at = bytes.findIndex((_, i) => CSRF_FIELD.every((b, j) => bytes[i + j] === b));
    if (at >= 0) {
      const start = at + CSRF_FIELD.length;
      let end = start;
      while (end < bytes.length && bytes[end] !== 13) end += 1;
      const swapped = new TextEncoder().encode(token);
      const out = new Uint8Array(bytes.length - (end - start) + swapped.length);
      out.set(bytes.slice(0, start));
      out.set(swapped, start);
      out.set(bytes.slice(end), start + swapped.length);
      bytes = out;
    }
  }
  return { headers, body: bytes };
}

async function flushProgressQueue() {
  if (flushing) return flushing;
  flushing = (async () => {
    // Who is signed in here, and their token. Each learner's progress goes
    // only while they're the one signed in: never under someone else's name.
    const who = await fetchLearner();
    if (!who) return;
    // Someone else signed in here offline and is still to finish signing
    // in: the signed-in learner's progress goes, without opening their
    // lessons on the screen in front of the other one.
    const pending = await pendingSignIn();
    const mine = pending && pending.id !== String(who.id) ?
      storesOf({ id: String(who.id), key: await learnerKey(who.secret) }) : storesOf(await useLearner(who));
    const sent = [await sendQueue(mine.queue, mine.key, who.token), await sendQueue(QUEUE_DB, null, who.token)];
    const total = (field) => sent.reduce((sum, one) => sum + one[field], 0);
    await tellClients({ type: "learning-sync", synced: total("synced"), pending: total("pending"), dropped: total("dropped") });
  })().finally(() => { flushing = null; });
  return flushing;
}

async function sendQueue(name, key, token) {
  const db = await openQueue(name);
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
      body = await openBytes(job.body, key);
    } catch (error) {  // sealed with a key that's gone: it can't be sent
      dropped += 1;
      await remove(job.id);
      continue;
    }
    const signed = withToken(job, body, token);
    let response;
    try {
      // Done offline, sent now (apps/offline/copies.py).
      response = await fetch(job.url, { method: job.method, headers: { ...signed.headers, "x-dm-offline-replay": "1" },
        body: job.method === "GET" ? undefined : signed.body, credentials: "include", redirect: "follow" });
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
  return { synced, dropped, pending: jobs.length - synced - dropped };
}

async function clearProgressQueue(name) {
  const db = await openQueue(name).catch(() => null);
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
      const where = await stores();
      const keys = [...await (await caches.open(where.pages)).keys(), ...await (await caches.open(where.library)).keys()];
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

  // static/js/offline_sync.js: which pages open here offline, so links to
  // the rest can say they need the internet.
  if (data && data.type === "offline-saved" && port) {
    event.waitUntil((async () => {
      const where = await stores();
      const keys = [...await (await caches.open(where.pages)).keys(), ...await (await caches.open(where.library)).keys()];
      const paths = new Set(keys.map((key) => new URL(key.url).pathname));
      if (paths.has(HOME_PATH)) paths.add("/");
      [LOGIN_PATH, LOGOUT_PATH, OFFLINE_URL, OFFLINE_PAGE].forEach((path) => paths.add(path));
      port.postMessage({ offline: servedOffline, paths: [...paths] });
    })());
  }

  // static/js/offline_sync.js: what's on this device, and downloading more.
  if (data && data.type === "offline-status" && port) {
    event.waitUntil((async () => {
      const count = async (name) => (await (await caches.open(name)).keys()).length;
      const access = await readAccess();
      const where = await stores();
      port.postMessage({
        until: access ? access.until : null,
        pages: (await count(where.pages)) + (await count(where.library)),
        media: (await count(MEDIA_CACHE)) + (await count(LIBRARY_MEDIA)),
        pending: await countQueue(),
      });
    })());
  }
  // A lesson pack loaded from a file (static/js/offline_pack.js): which of
  // its files are here already, keeping one, and remembering them all.
  if (data && data.type === "offline-has" && port) {
    event.waitUntil((async () => {
      port.postMessage((await (await caches.open(LIBRARY_MEDIA)).keys()).map((key) => key.url));
    })());
  }
  if (data && data.type === "offline-import" && port) {
    event.waitUntil((async () => {
      try {
        const file = new Response(data.bytes, { headers: { "Content-Type": data.contentType || "application/octet-stream" } });
        await (await caches.open(LIBRARY_MEDIA)).put(data.key, await sealed(file));
        port.postMessage({ ok: true });
      } catch (error) {
        port.postMessage({ ok: false, error: error && error.name === "QuotaExceededError" ? "This device is full." : "" });
      }
    })());
  }
  if (data && data.type === "offline-pack-keys" && port) {
    event.waitUntil((async () => {
      await keyStore("readwrite", (store) => store.put({ p: "pack-keys", keys: data.keys || [] }));
      port.postMessage({ ok: true });
    })());
  }
  // Which videos this learner's app keeps.
  if (data && data.type === "offline-videos" && port) {
    event.waitUntil((async () => {
      const response = await fetch(await manifestUrl(), { credentials: "include" }).catch(() => null);
      const manifest = response && response.ok ? await response.json() : null;
      port.postMessage((manifest && manifest.videos) || []);
    })());
  }
  // The levels kept on this device (the Offline page): read, or changed.
  if (data && data.type === "offline-levels" && port) {
    event.waitUntil((async () => {
      const name = `levels:${(await stores()).id || ""}`;
      if (Array.isArray(data.levels)) {
        await keyStore("readwrite", (store) => store.put({ p: name, levels: data.levels.map(String).slice(0, 12) }));
      }
      port.postMessage({ levels: await chosenLevels() });
    })());
  }

  // One step of a lesson download; the answer carries where to carry on.
  if (data && data.type === "offline-download" && port) {
    event.waitUntil((async () => {
      let state = data.state;
      try {
        state = state || await newDownload(data);
        port.postMessage(state.done ? state : await downloadStep(state));
      } catch (error) {
        port.postMessage({ ...(state || { pages: 0, media_kept: 0 }), stopped: "error", done: true });
      }
    })());
  }
  if (data && data.type === "offline-clear") {
    event.waitUntil((async () => {
      await caches.delete((await stores()).pages);
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
        if (wentThrough(response)) await clearPendingSignIn();
        return response;
      }).catch(() => signOutOffline()));
      return;
    }
    // Signing in, offline and on: see "signing in".
    if (url.pathname === SIGN_IN_PATH && request.method === "POST") {
      event.respondWith(signInOffline(request));
      return;
    }
    if ((url.pathname === SWITCH_PATH || url.pathname === LOGIN_PATH) && request.method === "POST") {
      event.respondWith(fetch(request.clone()).then(async (response) => {
        if (wentThrough(response)) await clearPendingSignIn();
        return response;
      }).catch(() => (url.pathname === SWITCH_PATH ? signInOffline(request) : signInPage())));
      return;
    }
    // Taken off this device: they can't sign in here offline any more.
    if ((url.pathname === REMOVE_PATH || url.pathname === FORGET_PATH) && request.method === "POST") {
      event.respondWith((async () => {
        const form = await request.clone().formData().catch(() => null);
        const response = await fetch(request).catch(() => null);
        if (!response) return needsInternetPage();
        if (wentThrough(response)) {
          const gone = url.pathname === FORGET_PATH ? (await keptLearners()).map((one) => one.id) :
            [String((form && form.get("user")) || "")];
          for (const id of gone) await forgetLearner(id);
        }
        return response;
      })());
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
          if (wentThrough(response)) await clearPendingSignIn();
          return response;
        }).catch(() => signOutOffline())
      );
      return;
    }

    // No connection: the log-in page lists who can sign in here offline.
    if (url.pathname === LOGIN_PATH) {
      event.respondWith(fetch(request).then(async (response) => (await settleSignIn(response)) || response)
        .catch(() => signInPage()));
      return;
    }

    // The Offline videos page is kept, so it opens with no connection.
    if (url.pathname === OFFLINE_PAGE) {
      event.respondWith(
        fetch(request).then(async (response) => {
          const settle = await settleSignIn(response);
          if (settle) return settle;
          if (response.ok) await keepPage(request, response);
          return response;
        }).catch(async () => (await cachedPage(request)) || caches.match(OFFLINE_URL))
      );
      return;
    }

    const sensitive = isSensitive(url.pathname);
    event.respondWith(
      fetch(request).then(async (response) => {
        servedOffline = false;
        const settle = await settleSignIn(response);
        if (settle) return settle;
        const finalPath = response.url ? new URL(response.url).pathname : "";
        if (!sensitive && !response.redirected && !finalPath.startsWith("/accounts/login/")) {
          await keepPage(request, response);
        }
        return response;
      }).catch(async () => {
        servedOffline = true;
        const page = sensitive ? null : await cachedPage(request);
        if (page && countsAsVisit(url.pathname)) await queueVisit(url.href).catch(() => {});
        // Nobody's lessons open (signed out): who is learning?
        if (!page && !(await currentLearner()) && (await keptLearners()).length) return signInPage();
        if (!page && !sensitive && !(await accessOpen())) return connectAgainPage();
        if (!page && (await currentLearner())) return notSavedPage(url.pathname);
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

  // Read-along word timings: kept, so the highlighting works offline.
  if (url.pathname.startsWith(READ_ALONG_PATH)) {
    event.respondWith(readAlong(request));
    return;
  }

  // A video is never kept by the worker: saved copies are encrypted in
  // the browser's own database instead.
  if (url.pathname.startsWith("/videos/")) return;

  // Keep same-origin lesson images and audio on this device. The site's own
  // pictures (in /static/, like a stylesheet's) are site files: below.
  if ((request.destination === "image" || request.destination === "audio") && !url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(cacheMedia(request));
    return;
  }

  if (url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const kept = (await cache.match(request)) || (await (await caches.open(LIBRARY_STATIC)).match(request));
        return kept || fetch(request).then((response) => {
          if (response.ok) cache.put(request, response.clone());
          return response;
        });
      })
    );
  }
});
