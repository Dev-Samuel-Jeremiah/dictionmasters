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
  if (url.pathname === "/offline-sync/manifest/") {
    if (manifest === 401) return new Response("{}", { status: 401 });
    return new Response(JSON.stringify(manifest), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  const body = site[url.pathname];
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
          getAll() { return req([...idb.rows.values()]); },
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
const worker = new Function("self", "caches", src + "\nreturn { mediaIn, indexAll, clearLearnerData, staticFilesIn, followable, canQueueProgress, mediaKey, isRemoteMedia, runDownload, downloadStep, newDownload, cachedPage, queueProgress, flushProgressQueue, countQueue, wantsJson, queuedResponse, keepPage, matchMedia, clearLibrary, accessOpen, connectAgainPage, sealKey, sealBytes, openBytes, unsealed, partOf };");
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
assert.deepEqual(paths("dm-library"), ["/accounts/dashboard/", "/echospell/level-1/", "/echospell/level-1/group-a/", "/echospell/level-1/group-b/"]);
assert.equal(result.pages, 4);
assert.equal(result.skipped, 1, "a lesson not reached yet is skipped");
assert.ok(!(await mod.indexAll()).some((e) => e.p === "/tricks/lessons/locked/"), "and tried again next time");
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
assert.equal(paths("dm-library").length, 4);

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
assert.equal(paths("dm-library").length, 4, "what's on the device stays");
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
assert.equal(paths("dm-library").length, 4, "still on the device");
assert.equal(mod.connectAgainPage().status, 503);
assert.ok((await mod.connectAgainPage().text()).includes("Connect to the internet once"));
clock -= 60 * day;                                               // winding the clock back
assert.equal(await mod.accessOpen(), false, "doesn't reopen them");
clock += 61 * day;
await mod.runDownload({ media: true });                          // connects once
assert.equal(await mod.accessOpen(), true, "and they're back");
assert.ok(await mod.matchMedia(R2 + "/a.mp3"));
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
assert.equal(back.pages, 4);
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
assert.equal(tight.pages, 4);
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
globalThis.fetch = async (input, init) => {
  fetched.push({ url: input, init });
  return new Response("ok", { status: String(input).includes("/save/") ? 404 : 200 });
};
await mod.flushProgressQueue();
assert.equal(await mod.countQueue(), 0);
assert.equal(fetched.length, 2);
assert.equal(new TextDecoder().decode(fetched[0].init.body), "csrfmiddlewaretoken=t", "body replayed intact");
assert.equal(fetched[0].init.headers["content-type"], "application/x-www-form-urlencoded");
const note = messages.find((m) => m.type === "learning-sync");
assert.deepEqual([note.synced, note.dropped, note.pending], [1, 1, 0]);
// server error keeps the queue
await mod.queueProgress(new Request(ORIGIN + "/echospell/l/g/complete/", { method: "POST", body: "a=1" }));
globalThis.fetch = async () => new Response("err", { status: 502 });
await mod.flushProgressQueue();
assert.equal(await mod.countQueue(), 1, "kept on 5xx");
console.log("sync ok");
console.log("ALL SERVICE WORKER TESTS PASSED");
