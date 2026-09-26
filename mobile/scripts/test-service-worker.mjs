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
const site = {
  "/accounts/dashboard/": `<a href="/echospell/">E</a><a href="/accounts/logout/">out</a><link rel="stylesheet" href="/static/css/ui.css?v=12"><script type="application/json">{"x": ["/static/js/boot.js"]}</script>`,
  "/echospell/": `<a href="/echospell/level-1/">L1</a><a href="/search/?q=x">s</a><a href="/billing/">b</a><a href="https://other.com/x">o</a>`,
  "/echospell/level-1/": `<a href="/echospell/level-1/group-a/">G</a><a href="/echospell/level-1/group-a/complete/">c</a>`,
  "/echospell/level-1/group-a/": `<a href="/echospell/level-1/group-a/cards/">cards</a><img src="https://acc.r2.cloudflarestorage.com/b/media/pic.png?X-Amz-Signature=1&amp;X-Amz-Date=2"><audio src="https://acc.r2.cloudflarestorage.com/b/media/a.mp3?sig=2"></audio>`,
  "/echospell/level-1/group-a/cards/": `<a href="/echospell/level-1/group-a/cards/deeper/">too deep</a>`,
  "/echospell/level-1/group-a/cards/deeper/": `<a href="/echospell/level-1/group-a/cards/deeper/d5/">5</a>`,
  "/echospell/level-1/group-a/cards/deeper/d5/": `<a href="/echospell/level-1/group-a/cards/deeper/d5/d6/">6</a>`,
  "/echospell/level-1/group-a/cards/deeper/d5/d6/": `never`,
};
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
  if (url.pathname === "/learning-tools/") { const r = new Response("", { status: 302 }); return r; }
  const body = site[url.pathname];
  if (body === undefined) return new Response("nope", { status: 404, headers: { "Content-Type": "text/html" } });
  const r = new Response("<html><body>" + body + "</body></html>", { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
  Object.defineProperty(r, "url", { value: url.href });
  Object.defineProperty(r, "type", { value: "basic" });
  return r;
};
// ---- fake IndexedDB (minimal, enough for the queue)
const idb = { rows: new Map(), next: 1 };
function req(result) { const r = { result }; setTimeout(() => r.onsuccess && r.onsuccess()); return r; }
globalThis.indexedDB = { open() {
  const db = {
    objectStoreNames: { contains: () => true },
    close() {},
    transaction() {
      const tx = { objectStore() { return {
        add(v) { const id = idb.next++; idb.rows.set(id, { ...v, id }); setTimeout(() => tx.oncomplete && tx.oncomplete()); },
        delete(id) { idb.rows.delete(id); setTimeout(() => tx.oncomplete && tx.oncomplete()); },
        clear() { idb.rows.clear(); setTimeout(() => tx.oncomplete && tx.oncomplete()); },
        getAll() { return req([...idb.rows.values()]); },
        count() { return req(idb.rows.size); },
      }; } };
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
const mod = new Function("self", "caches", src + "\nreturn { linksIn, staticFilesIn, followable, canQueueProgress, mediaKey, isRemoteMedia, runDownload, downloadStep, newDownload, cachedPage, queueProgress, flushProgressQueue, countQueue, wantsJson, queuedResponse, keepPage };")(self, caches);

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
for (const q of ["/echospell/l/g/complete/", "/echospell/card-position/", "/quick-words/lists/4/toggle/cat/", "/quick-words/lists/new/", "/assessments/attempt/9/save/", "/learning-modules/a/b/c/monday/complete/", "/reading-club/a/b/c/complete/"]) assert.ok(mod.canQueueProgress(post(q), q), q);
for (const q of ["/assessments/attempt/9/check/", "/tutor/start/", "/clash/start/", "/echospell/vocabulary/check-sentences/"]) assert.ok(!mod.canQueueProgress(post(q), q), q);
console.log("helpers ok");

// download
const result = await mod.runDownload({ media: true, limit: 50 });
const pages = [...stores.get("dm-pages").m.keys()].map((u) => new URL(u).pathname).sort();
console.log("pages kept:", pages);
assert.ok(pages.includes("/accounts/dashboard/"));
assert.ok(pages.includes("/echospell/level-1/group-a/cards/"));
assert.ok(pages.includes("/echospell/level-1/group-a/cards/deeper/d5/"), "depth 5 kept");
assert.ok(!pages.includes("/echospell/level-1/group-a/cards/deeper/d5/d6/"), "depth limit");
// steps: a 1-page step hands back a resumable state
const s1 = await mod.downloadStep(mod.newDownload({}), 1);
assert.ok(!s1.done && s1.queue.length > 0 && s1.pages >= 1);
const again = JSON.parse(JSON.stringify(s1)); // survives being posted to the page and back
const s2 = await mod.downloadStep(again, 1000);
assert.ok(s2.done && s2.pages >= 7);
assert.ok(!pages.some((p) => p.startsWith("/billing") || p.startsWith("/search") || p.includes("logout")));
assert.ok(!fetched.some((x) => x.url.includes("/accounts/logout/")), "never visits logout");
const media = [...stores.get("dm-media").m.keys()];
console.log("media kept:", media);
assert.ok(media.includes("https://acc.r2.cloudflarestorage.com/b/media/pic.png"));
assert.ok(media.includes("https://acc.r2.cloudflarestorage.com/b/media/a.mp3"));
const statics = [...stores.get("dm-static-abc123def456").m.keys()];
assert.ok(statics.some((u) => u.includes("/static/css/ui.css?v=12")) && statics.some((u) => u.includes("/static/js/boot.js")), "static kept");
assert.equal(result.done, true);
assert.ok(result.pages >= 5);
console.log("download ok:", result.pages, "pages,", result.media_kept, "media");

// offline: cached pages open, "/" opens dashboard
online = false;
const page = await mod.cachedPage(new Request(ORIGIN + "/echospell/level-1/?x=1"));
assert.ok(page && (await page.text()).includes("group-a"));
const home = await mod.cachedPage(new Request(ORIGIN + "/"));
assert.ok(home && (await home.text()).includes("/echospell/"));
console.log("offline pages ok");

// queue and sync
await mod.queueProgress(new Request(ORIGIN + "/echospell/l/g/complete/", { method: "POST", body: "csrfmiddlewaretoken=t", headers: { "Content-Type": "application/x-www-form-urlencoded" } }));
await mod.queueProgress(new Request(ORIGIN + "/assessments/attempt/9/save/", { method: "POST", body: JSON.stringify({ question: 1 }), headers: { "Content-Type": "application/json", "X-CSRFToken": "t" } }));
assert.equal(await mod.countQueue(), 2);
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
