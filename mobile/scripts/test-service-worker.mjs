/*
 * Tests for the offline logic in templates/pwa/sw.js (downloads, offline
 * pages, the progress sync queue), run without a browser:
 *
 *     cd mobile && npm run test:sw
 *
 * Run it after changing sw.js. It fakes the browser pieces (caches,
 * IndexedDB, the network) around a tiny pretend website.
 */
import fs from "node:fs";
import assert from "node:assert/strict";

let src = fs.readFileSync(process.argv[2] || new URL("../../templates/pwa/sw.js", import.meta.url), "utf8")
  .replace('"{{ version }}"', '"abc123def456"')
  .replace('"{{ offline_url }}"', '"/offline/"')
  .replace('"{{ static_prefix }}"', '"/static/"')
  .replace("{{ precache|safe }}", '["/offline/"]')
  .replace("{{ media_hosts|safe }}", '["r2.cloudflarestorage.com","r2.dev"]');
assert(!src.includes("{{"));

const ORIGIN = "https://www.dictionmasters.app";
// ---- fake Cache Storage
const stores = new Map();
function keyOf(r) { return typeof r === "string" ? new URL(r, ORIGIN).href : r.url; }
class FakeCache {
  constructor() { this.m = new Map(); }
  async put(req, res) { this.m.set(keyOf(req), res); }
  async match(req, opts) {
    const k = keyOf(req);
    if (this.m.has(k)) return this.m.get(k).clone();
    if (opts && opts.ignoreSearch) { for (const [kk, v] of this.m) if (kk.split("?")[0] === k.split("?")[0]) return v.clone(); }
    return undefined;
  }
  async keys() { return [...this.m.keys()].map((u) => new Request(u)); }
  async delete(req) { return this.m.delete(keyOf(req)); }
  async addAll() {} async add() {}
}
const caches = {
  async open(n) { if (!stores.has(n)) stores.set(n, new FakeCache()); return stores.get(n); },
  async delete(n) { return stores.delete(n); },
  async has(n) { return stores.has(n); },
  async keys() { return [...stores.keys()]; },
  async match(r) { for (const c of stores.values()) { const x = await c.match(r); if (x) return x; } },
};
// ---- fake site
const R2 = "https://acc.r2.cloudflarestorage.com/b/media";
const site = {
  "/accounts/dashboard/": `<a href="/accounts/logout/">out</a><link rel="stylesheet" href="/static/css/ui.css?v=12"><script type="application/json">{"x": ["/static/js/boot.js"]}</script>`,
  "/echospell/level-1/": `<a href="/billing/">b</a>`,
  "/echospell/level-1/group-a/": `<img src="${R2}/pic.png?X-Amz-Signature=1&amp;X-Amz-Date=2"><audio src="${R2}/a.mp3?sig=2"></audio>`,
  "/echospell/level-1/group-b/": `<audio src="${R2}/b.mp3?sig=3"></audio>`,
  "/tricks/lessons/locked/": `moved`,
};
const list = (extra = {}) => ({ release: "r1", access: true, pages: [
  { p: "/accounts/dashboard/", v: "" },
  { p: "/echospell/level-1/", v: "r1.a" },
  { p: "/echospell/level-1/group-a/", v: "r1.b" },
  { p: "/echospell/level-1/group-b/", v: "r1.c" },
  { p: "/tricks/lessons/locked/", v: "r1.d" },
  { p: "/billing/", v: "r1.never" },
  { p: "/accounts/logout/", v: "r1.never" },
], ...extra });
let manifest = list();
// who the fake site says is signed in (/offline-sync/learner/)
const secretFor = (id) => Buffer.from(Array.from({ length: 32 }, (_, i) => (i * 7 + Number(id)) % 256)).toString("base64");
const learnerFor = (id) => ({ ok: true, id, secret: secretFor(id), token: "fresh-" + id });
let signedIn = null;
const fetched = [];
let online = true;
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(typeof input === "string" ? input : input.url, ORIGIN);
  fetched.push({ url: url.href, init, method: init.method || (input.method) || "GET" });
  if (!online) throw new TypeError("Failed to fetch");
  if (url.hostname.endsWith("r2.cloudflarestorage.com")) {
    if (init.mode === "cors") return new Response("MEDIA:" + url.pathname, { status: 200 });
  }
  if (url.origin !== ORIGIN) return new Response("x");
  if (url.pathname.startsWith("/static/")) return new Response("static", { status: 200 });
  if (url.pathname === "/offline-sync/learner/") {
    return signedIn ? new Response(JSON.stringify(signedIn), { status: 200, headers: { "Content-Type": "application/json" } })
                    : new Response("{}", { status: 401 });
  }
  if (url.pathname === "/offline-sync/manifest/") {
    if (manifest === 401) return new Response("{}", { status: 401 });
    return new Response(JSON.stringify(manifest), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  // the site takes sign-in, switching and signing out with a redirect
  if ((init.method || input.method) === "POST" && url.pathname.startsWith("/accounts/")) {
    return new Response(null, { status: 302, headers: { Location: "/accounts/dashboard/" } });
  }
  const body = site[url.pathname + url.search] ?? site[url.pathname];
  if (body === undefined) return new Response("nope", { status: 404, headers: { "Content-Type": "text/html" } });
  const r = new Response("<html><body>" + body + "</body></html>", { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
  Object.defineProperty(r, "url", { value: url.pathname === "/tricks/lessons/locked/" ? ORIGIN + "/tricks/" : url.href });
  if (url.pathname === "/tricks/lessons/locked/") Object.defineProperty(r, "redirected", { value: true });
  Object.defineProperty(r, "type", { value: "basic" });
  return r;
};
// ---- fake IndexedDB (minimal: one store per database)
const dbs = new Map();
function req(result) { const r = { result }; setTimeout(() => r.onsuccess && r.onsuccess()); return r; }
globalThis.indexedDB = { open(name) {
  if (!dbs.has(name)) dbs.set(name, { rows: new Map(), next: 1 });
  const idb = dbs.get(name);
  const db = {
    objectStoreNames: { contains: () => true },
    close() {},
    transaction() {
      const tx = { objectStore() {
        const done = () => setTimeout(() => tx.oncomplete && tx.oncomplete());
        return {
          add(v) { const id = idb.next++; idb.rows.set(id, { ...v, id }); done(); },
          put(v) { idb.rows.set(v.p, v); done(); },
          get(k) { const r = req(idb.rows.get(k)); done(); return r; },
          delete(id) { idb.rows.delete(id); done(); },
          clear() { idb.rows.clear(); done(); },
          getAll() { const r = req([...idb.rows.values()]); done(); return r; },
          count() { return req(idb.rows.size); },
        };
      } };
      return tx;
    },
  };
  return req(db);
} };
// ---- fake SW global
const listeners = {};
const messages = [];
const self = {
  location: new URL(ORIGIN + "/sw.js"),
  addEventListener(t, f) { (listeners[t] ||= []).push(f); },
  skipWaiting() {}, registration: { sync: { register: async () => {} } },
  clients: { claim() {}, matchAll: async () => [{ postMessage: (m) => messages.push(m) }] },
};
globalThis.self = self;
globalThis.caches = caches;
Object.defineProperty(globalThis, "navigator", { value: { onLine: true }, configurable: true });
const worker = new Function("self", "caches", src + "\nreturn { mediaIn, indexAll, clearLearnerData, staticFilesIn, followable, canQueueProgress, mediaKey, isRemoteMedia, runDownload, downloadStep, newDownload, cachedPage, queueProgress, flushProgressQueue, countQueue, wantsJson, queuedResponse, keepPage, matchMedia, clearLibrary, accessOpen, storesOf, useLearner, lockLearner, currentLearner, withToken, connectAgainPage, sealKey, sealBytes, openBytes, unsealed, partOf, keptLearners, pendingSignIn };");
const mod = worker(self, caches);

// ---------------- tests
assert.equal(mod.mediaKey("https://a.r2.cloudflarestorage.com/b/x.mp3?sig=1"), "https://a.r2.cloudflarestorage.com/b/x.mp3");
assert.ok(mod.isRemoteMedia(new URL("https://acc.r2.cloudflarestorage.com/x")));
assert.ok(mod.isRemoteMedia(new URL("https://pub-1.r2.dev/x")));
assert.ok(!mod.isRemoteMedia(new URL("https://evil-r2.dev.com/x")));
assert.deepEqual(mod.staticFilesIn(`<link href="/static/css/a.css?v=1"> "/static/js/b.js" '/static/x.png'`), ["/static/css/a.css?v=1", "/static/js/b.js", "/static/x.png"]);
const f = (p) => mod.followable(new URL(p, ORIGIN));
for (const ok of ["/echospell/l/g/", "/book/44-academy/ee/", "/tricks/lessons/x/listen/", "/videos/offline/", "/accounts/dashboard/", "/assessments/some-quiz/"]) assert.ok(f(ok), ok);
for (const no of ["/accounts/logout/", "/billing/", "/search/", "/echospell/l/g/c/qr.png", "/videos/play/abc/", "/assessments/attempt/3/", "/clash/5/", "/clash/sound/", "/manage/", "/echospell/l/g/complete/", "/assessments/q/start/", "/accounts/delete/", "/app/welcome/"]) assert.ok(!f(no), no);
const post = (path, headers = {}) => new Request(ORIGIN + path, { method: "POST", headers, body: "a=1" });
for (const q of ["/echospell/l/g/complete/", "/echospell/card-position/", "/quick-words/lists/4/toggle/cat/", "/quick-words/lists/new/", "/assessments/attempt/9/save/", "/learning-modules/a/b/c/monday/complete/", "/reading-club/a/b/c/complete/", "/book/44-academy/ee/assessment/quiz-1/", "/tricks/lessons/linking/assessment/drill/", "/echospell/level-1/group-a/activities/spell-it/"]) assert.ok(mod.canQueueProgress(post(q), q), q);
for (const q of ["/book/44-academy/ee/assessment/quiz-1/result/4/", "/assessments/attempt/9/check/", "/tutor/start/", "/clash/start/", "/echospell/vocabulary/check-sentences/"]) assert.ok(!mod.canQueueProgress(post(q), q), q);
console.log("helpers ok");

// sync: the first one fetches the list, and what isn't there is skipped
const paths = (name) => [...stores.get(name).m.keys()].map((u) => new URL(u).pathname).sort();
const pagesFetched = () => fetched.filter((x) => new URL(x.url).origin === ORIGIN && !new URL(x.url).pathname.startsWith("/static/") &&
  !new URL(x.url).pathname.startsWith("/offline-sync/")).map((x) => new URL(x.url).pathname);
const result = await mod.runDownload({ media: true });
assert.equal(result.done, true);
assert.equal(result.stopped, "");
assert.deepEqual(paths("dm-library"), ["/accounts/dashboard/", "/echospell/level-1/", "/echospell/level-1/group-a/", "/echospell/level-1/group-b/", "/tricks/lessons/locked/"]);
assert.equal(result.pages, 5);
assert.equal(result.skipped, 0);
assert.ok((await mod.indexAll()).find((e) => e.p === "/tricks/lessons/locked/").moved,
  "a lesson not reached yet keeps what the site shows instead (finish the one before), and is tried again next time");
assert.ok(!fetched.some((x) => x.url.includes("/accounts/logout/") || x.url.includes("/billing/")), "never fetches what shouldn't be kept");
const media = [...stores.get("dm-library-media").m.keys()].sort();
assert.deepEqual(media, [R2 + "/a.mp3", R2 + "/b.mp3", R2 + "/pic.png"]);
const statics = [...stores.get("dm-library-static").m.keys()];
assert.ok(statics.some((u) => u.includes("/static/css/ui.css?v=12")) && statics.some((u) => u.includes("/static/js/boot.js")), "a page's stylesheets stay with it");

// everything kept is sealed: the stored bytes give nothing away
const rawPage = await stores.get("dm-library").m.get(ORIGIN + "/echospell/level-1/group-a/").clone().arrayBuffer();
assert.ok(!Buffer.from(rawPage).toString("latin1").includes("<audio"), "a stored page isn't readable");
assert.equal(stores.get("dm-library").m.get(ORIGIN + "/echospell/level-1/group-a/").headers.get("X-DM-Type"), "text/html; charset=utf-8");
const rawMedia = await stores.get("dm-library-media").m.get(R2 + "/a.mp3").clone().arrayBuffer();
assert.ok(!Buffer.from(rawMedia).toString("latin1").includes("MEDIA:"), "a stored file isn't readable");
// the same page sealed twice looks different: nothing can be compared
const same = new TextEncoder().encode("same words");
assert.notDeepEqual(await mod.sealBytes(same), await mod.sealBytes(same));
// the key can be used, never read out
const key = dbs.get("dm-offline-key").rows.get("seal").key;
assert.equal(key.extractable, false);
await assert.rejects(crypto.subtle.exportKey("raw", key), "the key can't be exported");
// changed stored bytes are refused, not shown
const tampered = new Uint8Array(rawPage);
tampered[20] ^= 1;
assert.equal(await mod.unsealed(new Response(tampered, { headers: { "X-DM-Type": "text/html" } })), null);
// reading back works, and audio can be asked for in parts
assert.equal(await (await mod.matchMedia(R2 + "/a.mp3")).text(), "MEDIA:/b/media/a.mp3");
const part = await mod.partOf(new Request(R2 + "/a.mp3", { headers: { range: "bytes=2-6" } }), await mod.matchMedia(R2 + "/a.mp3"));
assert.equal(part.status, 206);
assert.equal(part.headers.get("Content-Range"), "bytes 2-6/20");
assert.equal(await part.text(), "DIA:/");
const tail = await mod.partOf(new Request(R2 + "/a.mp3", { headers: { range: "bytes=-3" } }), await mod.matchMedia(R2 + "/a.mp3"));
assert.equal(await tail.text(), "mp3");
const past = await mod.partOf(new Request(R2 + "/a.mp3", { headers: { range: "bytes=99-" } }), await mod.matchMedia(R2 + "/a.mp3"));
assert.equal(past.status, 416);
const whole = await mod.partOf(new Request(R2 + "/a.mp3"), await mod.matchMedia(R2 + "/a.mp3"));
assert.equal(whole.status, 200);

// the same stored files with a different key (another device, say) open as nothing
const keptKey = dbs.get("dm-offline-key");
dbs.delete("dm-offline-key");
const elsewhere = worker(self, caches);
assert.equal(await elsewhere.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")), null);
assert.equal(await elsewhere.matchMedia(R2 + "/a.mp3"), null);
dbs.set("dm-offline-key", keptKey);

// updating removes the old unencrypted stores, and keeps the sealed ones
await caches.open("dm-pages");
await caches.open("dm-media");
await caches.open("dm-pages-2");
let activated;
listeners.activate[0]({ waitUntil: (work) => { activated = work; } });
await activated;
assert.ok(!stores.has("dm-pages") && !stores.has("dm-media"), "old plain stores are gone");
assert.ok(stores.has("dm-library") && stores.has("dm-library-media") && stores.has("dm-pages-2"));

// until the bucket lets the apps read it, its files wait: none are fetched
await mod.clearLearnerData();
await mod.clearLibrary();
manifest = list({ storage_media: false });
fetched.length = 0;
const waiting = await mod.runDownload({ media: true });
assert.equal(waiting.pages, 5);
assert.ok(!fetched.some((x) => x.url.startsWith(R2)), "nothing asked of the bucket");
assert.ok((await mod.indexAll()).some((e) => e.pending), "they're noted as still to come");
manifest = list();
await mod.runDownload({ media: true });
assert.equal(stores.get("dm-library-media").m.size, 3, "and arrive once it's turned on");

// a lesson full of recordings: short steps that keep moving, files queued
// across them, the page pending until all its files are here
await mod.clearLearnerData();
await mod.clearLibrary();
site["/echospell/level-1/group-b/"] = Array.from({ length: 40 }, (_, i) => `<audio src="${R2}/many-${i}.mp3?sig=1"></audio>`).join("");
let heavy = await mod.newDownload({ media: true });
const progress = [];
for (let steps = 0; !heavy.done && steps < 200; steps++) {
  heavy = await mod.downloadStep(JSON.parse(JSON.stringify(heavy)), 1000, 0);   // no time at all: one batch each
  progress.push(heavy.pages + heavy.skipped + heavy.media_kept + heavy.failed);
}
assert.ok(heavy.done && heavy.stopped === "", "it finishes");
assert.ok(progress.every((n, i) => i === 0 || n > progress[i - 1]), "every step moves on");
assert.ok(progress.length > 20, "in many short steps, not one long one");
assert.equal(heavy.media_kept, 42);
assert.ok(!(await mod.indexAll()).some((e) => e.pending), "nothing left pending once all files are here");
// cut off half-way through the files: the page stays pending and the rest follow
await mod.clearLibrary();
let half = await mod.newDownload({ media: true });
for (let i = 0; i < 6; i++) half = await mod.downloadStep(half, 1000, 0);
assert.ok(!half.done && half.files.length > 0);
assert.ok((await mod.indexAll()).find((e) => e.p === "/echospell/level-1/group-b/").pending, "still pending");
const finish = await mod.runDownload({ media: true });
assert.equal(stores.get("dm-library-media").m.size, 42, "the rest arrive next time");
assert.ok(!(await mod.indexAll()).some((e) => e.pending));
site["/echospell/level-1/group-b/"] = `<audio src="${R2}/b.mp3?sig=3"></audio>`;
await mod.runDownload({ media: true });

// a lesson pack loaded from a file: its files go in sealed, and stay even
// before a sync reaches the lessons that use them
const askWorker = (message) => new Promise((resolve) => {
  const port = { postMessage: resolve };
  listeners.message[0]({ data: message, ports: [port], waitUntil: (work) => work });
});
await mod.clearLearnerData();
await mod.clearLibrary();
const packed = R2 + "/not-reached-yet.mp3";
assert.equal((await askWorker({ type: "offline-import", key: packed, contentType: "audio/mpeg", bytes: new TextEncoder().encode("PACKED AUDIO").buffer })).ok, true);
const rawPacked = await stores.get("dm-library-media").m.get(packed).clone().arrayBuffer();
assert.ok(!Buffer.from(rawPacked).toString("latin1").includes("PACKED AUDIO"), "sealed with this device's key");
assert.equal(await (await mod.matchMedia(packed + "?sig=x")).text(), "PACKED AUDIO");
assert.deepEqual(await askWorker({ type: "offline-has" }), [packed]);
await askWorker({ type: "offline-pack-keys", keys: [packed] });
await mod.runDownload({ media: true });
assert.ok(stores.get("dm-library-media").m.has(packed), "kept though no lesson uses it yet");
await mod.clearLibrary();
await mod.runDownload({ media: true });
assert.ok(!stores.get("dm-library-media").m.has(packed), "Remove downloads takes it too");

// the second sync fetches only what can change, and files aren't fetched twice
fetched.length = 0;
await mod.runDownload({ media: true });
assert.deepEqual(pagesFetched().sort(), ["/accounts/dashboard/", "/tricks/lessons/locked/"]);

// a page's content changed: only that page is fetched again
manifest.pages[2].v = "r1.changed";
fetched.length = 0;
await mod.runDownload({ media: true });
assert.deepEqual(pagesFetched().sort(), ["/accounts/dashboard/", "/echospell/level-1/group-a/", "/tricks/lessons/locked/"]);

// a page removed from the list goes, with the files only it used
manifest.pages.splice(3, 1);
await mod.runDownload({ media: true });
assert.ok(!paths("dm-library").includes("/echospell/level-1/group-b/"));
assert.deepEqual([...stores.get("dm-library-media").m.keys()].sort(), [R2 + "/a.mp3", R2 + "/pic.png"]);

// pages kept without their files (mobile data): files follow on Wi-Fi
await mod.clearLearnerData();
await mod.clearLibrary();
manifest = list();
const light = await mod.runDownload({ media: false, limit: 3 });
assert.equal(light.pages, 3);
assert.ok(!stores.has("dm-library-media") || stores.get("dm-library-media").m.size === 0);
fetched.length = 0;
await mod.runDownload({ media: true });
assert.ok(pagesFetched().includes("/echospell/level-1/group-a/"), "the page that needs its files comes again");
assert.equal(stores.get("dm-library-media").m.size, 3);

// a sync cut off part-way carries on where it stopped
await mod.clearLearnerData();
await mod.clearLibrary();
let partial = await mod.newDownload({ media: true });
partial = await mod.downloadStep(JSON.parse(JSON.stringify(partial)), 2);
assert.ok(!partial.done && partial.pages === 2);
fetched.length = 0;
const rest = await mod.runDownload({ media: true });
assert.ok(rest.pages >= 2 && rest.stopped === "");
assert.equal(paths("dm-library").length, 5);

// offline pages and files open from the library, past the kept-in-passing limits
online = false;
const kept = await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/"));
assert.ok(kept && (await kept.text()).includes("<audio"));
assert.ok(await mod.matchMedia(R2 + "/a.mp3?sig=new"), "a new signature finds the same file");
online = true;

// signed out, or their plan has ended: nothing is fetched and nothing goes
manifest = 401;
assert.equal((await mod.runDownload({ media: true })).stopped, "signed-out");
manifest = { release: "r1", access: false, pages: [] };
const ended = await mod.runDownload({ media: true });
assert.equal(ended.stopped, "no-access");
assert.equal(paths("dm-library").length, 5, "what's on the device stays");
assert.equal(await mod.accessOpen(), false, "but no longer opens");
assert.equal(await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")), null);
manifest = list();
await mod.runDownload({ media: true });
assert.equal(await mod.accessOpen(), true, "their plan back: open again");

// offline for longer than the limit: lessons stay, but don't open until it connects
const realNow = Date.now;
const day = 86400000;
let clock = realNow();
Date.now = () => clock;
manifest = list({ offline_days: 90 });
await mod.runDownload({ media: true });
clock += 89 * day;
assert.equal(await mod.accessOpen(), true, "fine on day 89");
assert.ok(await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")));
clock += 2 * day;
assert.equal(await mod.accessOpen(), false, "closed after 90 days offline");
assert.equal(await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")), null);
assert.equal(await mod.matchMedia(R2 + "/a.mp3"), null);
assert.equal(paths("dm-library").length, 5, "still on the device");
assert.equal(mod.connectAgainPage().status, 503);
assert.ok((await mod.connectAgainPage().text()).includes("Connect to the internet once"));
clock -= 60 * day;                                               // winding the clock back
assert.equal(await mod.accessOpen(), false, "doesn't reopen them");
clock += 61 * day;
await mod.runDownload({ media: true });                          // connects once
assert.equal(await mod.accessOpen(), true, "and they're back");
assert.ok(await mod.matchMedia(R2 + "/a.mp3"));

// the plan ends before the 90 days: closed on that date, even with no internet
manifest = list({ offline_days: 90, access_ends: clock + 10 * day });
await mod.runDownload({ media: true });
clock += 9 * day;
assert.equal(await mod.accessOpen(), true, "open while the plan runs");
clock += 2 * day;
assert.equal(await mod.accessOpen(), false, "closed the day the plan ends, offline");
assert.equal(await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")), null);
clock -= 5 * day;
assert.equal(await mod.accessOpen(), false, "winding the clock back doesn't reopen it");
// renewed: the next check-in reopens it
clock += 6 * day;
manifest = list({ offline_days: 90, access_ends: clock + 365 * day });
await mod.runDownload({ media: true });
assert.equal(await mod.accessOpen(), true, "renewed: open again");
clock += 91 * day;
assert.equal(await mod.accessOpen(), false, "a long plan still has the 90-day limit");
// no end date (staff, or the paywall off): just the 90 days
manifest = list({ offline_days: 90, access_ends: null });
await mod.runDownload({ media: true });
clock += 80 * day;
assert.equal(await mod.accessOpen(), true);
Date.now = realNow;
manifest = list();

// logging out removes what's personal; the heavy files stay, and open
const sealedKey = dbs.get("dm-offline-key").rows.get("seal").key;
await mod.clearLearnerData();
assert.ok(!stores.has("dm-library"), "pages show who was signed in: they go");
assert.equal((await mod.indexAll()).length, 0);
assert.equal(stores.get("dm-library-media").m.size, 3, "pictures and audio stay");
assert.equal(dbs.get("dm-offline-key").rows.get("seal").key, sealedKey, "with the key that opens them");
assert.ok(await mod.matchMedia(R2 + "/a.mp3"));
// the next sign-in doesn't fetch them again
fetched.length = 0;
const back = await mod.runDownload({ media: true });
assert.equal(back.pages, 5);
assert.ok(!fetched.some((x) => x.url.includes(".mp3") || x.url.includes(".png")), "files already here aren't fetched");
// the next learner doesn't need one: it goes when their sync finishes
manifest.pages.splice(3, 1);
await mod.clearLearnerData();
await mod.runDownload({ media: true });
assert.deepEqual([...stores.get("dm-library-media").m.keys()].sort(), [R2 + "/a.mp3", R2 + "/pic.png"]);
manifest = list();
await mod.runDownload({ media: true });

// "Remove downloads" takes the lot
await mod.clearLibrary();
assert.ok(!stores.has("dm-library") && !stores.has("dm-library-media") && !stores.has("dm-library-static"));
await mod.runDownload({ media: true });

// not enough room: pages come, the files wait, and it says how much is needed
await mod.clearLearnerData();
await mod.clearLibrary();
manifest = list({ need_mb: 1800 });
navigator.storage = { estimate: async () => ({ quota: 200 * 1048576, usage: 100 * 1048576 }) };
const tight = await mod.runDownload({ media: true });
assert.equal(tight.pages, 5);
assert.ok(tight.low_space_mb > 100, "says how much is needed");
assert.ok(!stores.has("dm-library-media") || stores.get("dm-library-media").m.size === 0);
navigator.storage = { estimate: async () => ({ quota: 90000 * 1048576, usage: 0 }) };
const roomy = await mod.runDownload({ media: true });
assert.ok(!roomy.low_space_mb);
assert.equal(stores.get("dm-library-media").m.size, 3, "and arrive when there's room");
delete navigator.storage;
manifest = list();
console.log("download ok:", result.pages, "pages,", result.media_kept, "media");

// offline: cached pages open, "/" opens dashboard
online = false;
const page = await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/?x=1"));
assert.ok(page && (await page.text()).includes("/billing/"));
const home = await mod.cachedPage(new Request(ORIGIN + "/"));
assert.ok(home && (await home.text()).includes("/accounts/logout/"));
console.log("offline pages ok");

// queue and sync (answers wait sealed)
await mod.queueProgress(new Request(ORIGIN + "/echospell/l/g/complete/", { method: "POST", body: "csrfmiddlewaretoken=t", headers: { "Content-Type": "application/x-www-form-urlencoded" } }));
await mod.queueProgress(new Request(ORIGIN + "/assessments/attempt/9/save/", { method: "POST", body: JSON.stringify({ question: 1 }), headers: { "Content-Type": "application/json", "X-CSRFToken": "t" } }));
assert.equal(await mod.countQueue(), 2);
for (const job of dbs.get("dm-offline-sync").rows.values()) {
  assert.ok(!Buffer.from(job.body).toString("latin1").includes("csrfmiddlewaretoken") && !Buffer.from(job.body).toString("latin1").includes("question"), "answers wait sealed");
}
const j = await mod.queuedResponse(new Request(ORIGIN + "/assessments/attempt/9/save/", { method: "POST", headers: { Accept: "application/json" } }));
assert.equal(j.status, 202); assert.equal((await j.json()).queued, true);
await mod.flushProgressQueue(); // still offline
assert.equal(await mod.countQueue(), 2, "kept while offline");
online = true;
fetched.length = 0;
messages.length = 0;
// server answers 200 for the first, 404 (gone) for the second
const realFetch = globalThis.fetch;
const asWho = (other) => async (input, init) => {
  if (String(input).includes("/offline-sync/learner/")) {
    return new Response(JSON.stringify(learnerFor("7")), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  fetched.push({ url: input, init });
  return other(input, init);
};
globalThis.fetch = asWho(async (input) => new Response("ok", { status: String(input).includes("/save/") ? 404 : 200 }));
await mod.flushProgressQueue();
assert.equal(await mod.countQueue(), 0);
assert.equal(fetched.length, 2);
assert.equal(new TextDecoder().decode(fetched[0].init.body), "csrfmiddlewaretoken=fresh-7", "sent with today's security token");
assert.equal(fetched[0].init.headers["content-type"], "application/x-www-form-urlencoded");
assert.equal(fetched[1].init.headers["x-csrftoken"], "fresh-7");
const note = messages.find((m) => m.type === "learning-sync");
assert.deepEqual([note.synced, note.dropped, note.pending], [1, 1, 0]);
// server error keeps the queue
await mod.queueProgress(new Request(ORIGIN + "/echospell/l/g/complete/", { method: "POST", body: "a=1" }));
globalThis.fetch = asWho(async () => new Response("err", { status: 502 }));
await mod.flushProgressQueue();
assert.equal(await mod.countQueue(), 1, "kept on 5xx");
globalThis.fetch = realFetch;
console.log("sync ok");

// ------------------------------------------------ learners on a shared tablet
await mod.lockLearner();
await mod.clearLibrary();
await mod.clearLearnerData();
online = true;
const A = "21", B = "22";
const rawOf = async (name, path) => stores.get(name) && stores.get(name).m.get(ORIGIN + path);
// Ada syncs: her pages go in her own store, sealed with her own key
signedIn = learnerFor(A);
manifest = list({ learner: { id: A, secret: secretFor(A) } });
await mod.runDownload({ media: true });
assert.equal((await mod.currentLearner()).id, A);
assert.ok(await rawOf(`dm-l${A}-library`, "/echospell/level-1/group-a/"), "in her own store");
assert.ok(!stores.has("dm-library") || stores.get("dm-library").m.size === 0, "not the device's");
const adaPage = await rawOf(`dm-l${A}-library`, "/echospell/level-1/group-a/");
assert.equal(await mod.unsealed(adaPage.clone()), null, "the device's own key can't open it");
assert.ok(await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")));
// she logs out: her store stays, locked
await mod.clearLearnerData();
assert.equal(await mod.currentLearner(), null);
assert.ok(await rawOf(`dm-l${A}-library`, "/echospell/level-1/group-a/"), "kept");
assert.equal(await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/")), null, "but nobody can open it");
// Bo signs in on the same tablet: his own store; he never sees Ada's
signedIn = learnerFor(B);
manifest = list({ learner: { id: B, secret: secretFor(B) } });
await mod.runDownload({ media: true });
assert.equal((await mod.currentLearner()).id, B);
assert.ok(await rawOf(`dm-l${B}-library`, "/echospell/level-1/group-a/"));
assert.equal(await mod.unsealed((await rawOf(`dm-l${A}-library`, "/echospell/level-1/group-a/")).clone(), (await mod.currentLearner()).key), null,
  "Bo's key can't open Ada's pages");
// the shared recordings stayed: Bo didn't fetch them again
assert.equal(stores.get("dm-library-media").m.size, 3);
// Bo answers offline; his work waits in his own queue
online = false;
await mod.queueProgress(new Request(ORIGIN + "/echospell/l/g/complete/", { method: "POST", body: "csrfmiddlewaretoken=old&done=bo",
  headers: { "Content-Type": "application/x-www-form-urlencoded" } }));
assert.equal(dbs.get(`dm-l${B}-queue`).rows.size, 1);
// Ada is back: her lessons are still here, only the front pages come again
await mod.clearLearnerData();
online = true;
signedIn = learnerFor(A);
manifest = list({ learner: { id: A, secret: secretFor(A) } });
fetched.length = 0;
await mod.runDownload({ media: true });
assert.deepEqual(pagesFetched().sort(), ["/accounts/dashboard/", "/tricks/lessons/locked/"], "her lessons were kept");
// with Ada signed in, Bo's waiting work is not sent under her name
const sentAs = [];
globalThis.fetch = async (input, init) => {
  if (String(input).includes("/offline-sync/learner/")) return new Response(JSON.stringify(signedIn), { status: 200 });
  sentAs.push(signedIn.id);
  return new Response("ok", { status: 200 });
};
await mod.flushProgressQueue();
assert.deepEqual(sentAs, [], "nothing of Bo's went out as Ada");
assert.equal(dbs.get(`dm-l${B}-queue`).rows.size, 1, "it waits for Bo");
// Bo signs in again: his work goes, as him, with his fresh token
await mod.clearLearnerData();
signedIn = learnerFor(B);
const bodies = [];
globalThis.fetch = async (input, init) => {
  if (String(input).includes("/offline-sync/learner/")) return new Response(JSON.stringify(signedIn), { status: 200 });
  sentAs.push(signedIn.id);
  bodies.push(new TextDecoder().decode(init.body));
  return new Response("ok", { status: 200 });
};
await mod.flushProgressQueue();
assert.deepEqual(sentAs, [B]);
assert.equal(bodies[0], "csrfmiddlewaretoken=fresh-22&done=bo");
assert.equal(dbs.get(`dm-l${B}-queue`).rows.size, 0);
globalThis.fetch = realFetch;
// a page that says someone else is signed in stops the sync, rather than filing it under the wrong learner
site["/echospell/level-1/group-a/"] = `<html data-learner="99"><audio src="${R2}/a.mp3?sig=2"></audio>`;
manifest = list({ learner: { id: B, secret: secretFor(B) } });
manifest.pages[2].v = "r1.someone-else";
const mixed = await mod.runDownload({ media: true });
assert.equal(mixed.stopped, "switched");
site["/echospell/level-1/group-a/"] = `<img src="${R2}/pic.png?X-Amz-Signature=1&amp;X-Amz-Date=2"><audio src="${R2}/a.mp3?sig=2"></audio>`;
// a recording sent with a form gets the fresh token, and its bytes stay exactly as they were
const formBoundary = "XyZ";
const formAudio = Uint8Array.from([0, 13, 10, 255, 128, 13, 10, 7]);
const formHead = new TextEncoder().encode(`--${formBoundary}\r\nContent-Disposition: form-data; name="csrfmiddlewaretoken"\r\n\r\nOLDTOKEN\r\n--${formBoundary}\r\nContent-Disposition: form-data; name="rec"\r\n\r\n`);
const formTail = new TextEncoder().encode(`\r\n--${formBoundary}--\r\n`);
const formBytes = new Uint8Array([...formHead, ...formAudio, ...formTail]);
const swapped = mod.withToken({ headers: { "content-type": `multipart/form-data; boundary=${formBoundary}` } }, formBytes.buffer, "NEWTOKEN1");
const formText = Buffer.from(swapped.body).toString("latin1");
assert.ok(formText.includes("\r\n\r\nNEWTOKEN1\r\n") && !formText.includes("OLDTOKEN"));
assert.deepEqual([...swapped.body.slice(swapped.body.length - formTail.length - formAudio.length, swapped.body.length - formTail.length)], [...formAudio], "the recording is untouched");
// a crowded tablet: the learners not seen for longest give up their lessons (not their waiting work)
for (let n = 0; n < 12; n++) await mod.useLearner({ id: String(100 + n), secret: secretFor(String(100 + n)) });
assert.ok(!stores.has(`dm-l${A}-library`), "the longest unseen learner's lessons make room");
signedIn = learnerFor(B);
manifest = list({ learner: { id: B, secret: secretFor(B) } });
await mod.runDownload({ media: true });
// updating the app keeps every learner's stores
let reactivated;
listeners.activate[0]({ waitUntil: (work) => { reactivated = work; } });
await reactivated;
assert.ok(stores.has(`dm-l${B}-library`), "learners' stores survive an update");
signedIn = null;
manifest = list();
console.log("learners ok");

// ------------------------------------------------ signing in offline: tap your name
const nav = (path, init) => { const r = new Request(ORIGIN + path, init); Object.defineProperty(r, "mode", { value: "navigate" }); return r; };
const visit = async (path, init) => {
  let answer;
  listeners.fetch[0]({ request: nav(path, init), respondWith(p) { answer = p; } });
  return answer && await answer;
};
const form = (fields) => ({ method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(fields).toString() });
const keyRows = () => dbs.get("dm-offline-key").rows;
const C = "23";
const person = (id, device, name) => ({ ...learnerFor(id), name, initials: name.slice(0, 1), device });
online = true;
// Bo signs in with "Remember me on this device": their key stays for offline
site["/accounts/dashboard/"] = `<i data-learner="${B}">Bo's home</i>`;
signedIn = person(B, [B], "Bo <Ade>");
await mod.flushProgressQueue();
assert.ok(keyRows().has(`kept:${B}`), "a remembered learner's key is kept");
await visit("/accounts/dashboard/");
let answer = await visit("/accounts/logout/", form({}));
assert.equal(answer.status, 302);
assert.equal(await mod.currentLearner(), null, "signing out locks their lessons");
assert.ok(keyRows().has(`kept:${B}`), "but a remembered learner can sign in again offline");
// Cy signs in without "Remember me": nothing kept for them
signedIn = person(C, [B], "Cy");
await mod.flushProgressQueue();
assert.ok(!keyRows().has(`kept:${C}`), "someone not remembered has no key kept");
await visit("/accounts/logout/", form({}));
// offline: the log-in page lists who can tap their name
online = false;
answer = await visit("/accounts/login/");
let text = await answer.text();
assert.ok(text.includes("Who is learning?") && text.includes("Bo &#60;Ade&#62;") && !text.includes("Bo <Ade>"), "names listed, safely");
assert.ok(!text.includes("Cy") && text.includes('action="/offline-sync/sign-in/"'));
answer = await visit("/offline-sync/sign-in/", form({ user: C }));
assert.equal(answer.status, 503, "someone not remembered needs the internet");
assert.equal(await mod.currentLearner(), null);
answer = await visit("/offline-sync/sign-in/", form({ user: B }));
assert.equal(answer.status, 303);
assert.equal(new URL(answer.headers.get("Location")).pathname, "/accounts/dashboard/");
assert.equal((await mod.currentLearner()).id, B, "tapping their name opens their lessons");
assert.equal((await mod.pendingSignIn()).id, B);
text = await (await visit("/accounts/dashboard/")).text();
assert.ok(text.includes("Bo's home"), "their own dashboard, offline");
// signing out offline, then the app opened again: who is learning?
answer = await visit("/accounts/logout/", form({}));
assert.equal(answer.status, 303);
assert.equal(new URL(answer.headers.get("Location")).pathname, "/accounts/login/");
assert.equal((await mod.pendingSignIn()).id, "", "the site is still to hear about it");
assert.ok((await (await visit("/")).text()).includes("Who is learning?"));
// the dashboard's own switcher works offline too
answer = await visit("/accounts/switch/", form({ user: B, csrfmiddlewaretoken: "old" }));
assert.equal(answer.status, 303);
assert.equal((await mod.currentLearner()).id, B);
// back online, but the site still has Cy signed in: ask before going on
site["/reading-club/"] = `<i data-learner="${C}">Cy's page</i>`;
signedIn = person(C, [B], "Cy");
online = true;
answer = await visit("/reading-club/");
text = await answer.text();
assert.ok(text.includes("Welcome back online") && text.includes(`name="user" value="${B}"`) && text.includes("fresh-23"), "finish signing in as Bo");
assert.ok(!text.includes("Cy's page"), "not Cy's page under Bo's name");
assert.ok(!(stores.get(`dm-l${C}-pages`) && stores.get(`dm-l${C}-pages`).m.size), "nothing kept for Cy meanwhile");
await mod.flushProgressQueue();
assert.equal((await mod.currentLearner()).id, B, "Cy's waiting work goes without opening Cy's lessons on Bo's screen");
answer = await visit("/accounts/switch/", form({ user: B, csrfmiddlewaretoken: "fresh-23" }));
assert.equal(answer.status, 302);
assert.equal(await mod.pendingSignIn(), null, "the site took the switch");
signedIn = person(B, [B], "Bo <Ade>");
assert.ok((await (await visit("/accounts/dashboard/")).text()).includes("Bo's home"));
// signed out offline, and the site still has Bo signed in: finish signing out
online = false;
await visit("/accounts/logout/", form({}));
online = true;
text = await (await visit("/accounts/dashboard/")).text();
assert.ok(text.includes("Finishing signing out") && text.includes('action="/accounts/logout/"') && text.includes("fresh-22"));
await visit("/accounts/logout/", form({ csrfmiddlewaretoken: "fresh-22" }));
assert.equal(await mod.pendingSignIn(), null);
// a page for the learner who signed in offline settles it quietly
online = false;
await visit("/offline-sync/sign-in/", form({ user: B }));
online = true;
assert.ok((await (await visit("/accounts/dashboard/")).text()).includes("Bo's home"));
assert.equal(await mod.pendingSignIn(), null, "signed in as them already");
// taken off this device, or no longer on its list: no more offline sign-in
await visit("/accounts/switch/remove/", form({ user: B }));
assert.ok(!keyRows().has(`kept:${B}`), "removed from the device");
await mod.flushProgressQueue();
assert.ok(keyRows().has(`kept:${B}`));
signedIn = person(C, [], "Cy");
await mod.flushProgressQueue();
assert.ok(!keyRows().has(`kept:${B}`), "the site's list of who is remembered here wins");
online = false;
assert.ok((await (await visit("/accounts/login/")).text()).includes("Connect to sign in"), "nobody to list");
online = true;
signedIn = null;
delete site["/accounts/dashboard/"];
delete site["/reading-club/"];
console.log("signing in ok");

// ------------------------------------------------ lessons saved before learners had their own stores
await mod.lockLearner();
manifest = list();                                     // an older server: no learner in the list
await mod.runDownload({ media: true });
assert.ok(stores.get("dm-library").m.size >= 4, "kept in the device's stores, as before the update");
const D = "24";
signedIn = person(D, [D], "Dee");
await mod.flushProgressQueue();                        // the first learner the app meets after the update
assert.equal((await mod.currentLearner()).id, D);
assert.ok(!stores.has("dm-library"), "moved out of the device's stores");
assert.ok(stores.get(`dm-l${D}-library`).m.size >= 4, "into Dee's");
assert.ok((await mod.indexAll(`dm-l${D}-index`)).length >= 4, "with what the next sync needs to know");
online = false;
assert.ok((await (await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/group-a/"))).text()).includes("<audio"),
  "opens offline, nothing downloaded again");
// offline, a page that isn't saved says so, and what needs the internet says that
text = await (await visit("/tutor/")).text();
assert.ok(text.includes("The AI tutor needs the internet") && text.includes('href="/accounts/dashboard/"'));
text = await (await visit("/somewhere-not-saved/")).text();
assert.ok(text.includes("isn't on this device yet"));
const saved = await askWorker({ type: "offline-saved" });
assert.equal(saved.offline, true, "the last page came from the device");
assert.ok(saved.paths.includes("/echospell/level-1/group-a/") && saved.paths.includes("/accounts/logout/") && !saved.paths.includes("/tutor/"));
online = true;
// a sync after that fetches only what changed
fetched.length = 0;
manifest = list({ learner: { id: D, secret: secretFor(D) } });
await mod.runDownload({ media: true });
assert.deepEqual(pagesFetched().sort(), ["/accounts/dashboard/", "/tricks/lessons/locked/"], "Dee's moved lessons aren't fetched again");
signedIn = null;
manifest = list();
console.log("old downloads ok");

// ------------------------------------------------ copies aren't visits; offline visits are made again online
const copied = fetched.filter((x) => new URL(x.url).pathname === "/accounts/dashboard/");
assert.ok(copied.length && copied.every((x) => x.init.headers["X-DM-Offline-Copy"] === "1"), "a page fetched to keep says so");
const DAY = "/learning-modules/m/t/w/monday/";
site[DAY] = `<i data-learner="${D}">Monday start</i>`;
site[DAY + "?step=1"] = `<i data-learner="${D}">Step one</i>`;
site[DAY + "?step=2"] = `<i data-learner="${D}">Step two</i>`;
signedIn = person(D, [D], "Dee");
manifest = list({ learner: { id: D, secret: secretFor(D) } });
manifest.pages.push({ p: DAY, v: "r1.day" }, { p: DAY + "?step=1", v: "r1.day" }, { p: DAY + "?step=2", v: "r1.day" });
await mod.runDownload({ media: true });
online = false;
assert.ok((await (await visit(DAY + "?step=2")).text()).includes("Step two"), "each step of a day is its own page offline");
assert.ok((await (await visit(DAY + "?step=1")).text()).includes("Step one"));
assert.ok((await (await visit(DAY + "?step=9")).text()).includes("Monday start"), "an unknown step falls back to the day");
await visit(DAY + "?step=2");                                        // opened twice: counts once
await visit("/echospell/level-1/");                                  // not a page that counts
const waitingJobs = [...dbs.get(`dm-l${D}-queue`).rows.values()].filter((job) => job.method === "GET").map((job) => new URL(job.url).search);
assert.deepEqual(waitingJobs.sort(), ["?step=1", "?step=2", "?step=9"], "visits that count wait for the connection");
online = true;
fetched.length = 0;
await mod.flushProgressQueue();
const replays = fetched.filter((x) => x.url.includes(DAY));
assert.equal(replays.length, 3);
assert.ok(replays.every((x) => x.init.method === "GET" && x.init.body === undefined && x.init.headers["x-dm-offline-replay"] === "1"),
  "made again as the visits they were, marked as done offline");
assert.equal([...dbs.get(`dm-l${D}-queue`).rows.values()].length, 0);
signedIn = null;
manifest = list();
console.log("visits ok");
console.log("ALL SERVICE WORKER TESTS PASSED");
