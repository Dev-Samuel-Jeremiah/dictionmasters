/*
 * Lessons on this device: download them for offline study, and keep them
 * up to date (templates/pwa/sw.js does the storing).
 *
 * Loaded on every page for signed-in learners (templates/base.html):
 *
 *   - On the "Offline lessons & videos" page ([data-offline-sync], in
 *     templates/videos/offline.html) it runs the panel: download, sync
 *     now, remove, and what's on this device.
 *   - Everywhere, once a learner has downloaded lessons, it quietly
 *     refreshes them about twice a day when the device is online on Wi-Fi,
 *     and carries on a download that was interrupted by leaving the page.
 *
 * Progress made offline (lessons completed, words saved, answers) is sent
 * by the service worker when the device reconnects (static/js/pwa.js asks
 * it to, and so does static/js/native_app.js inside the phone apps).
 *
 * window.DMOffline gives the same controls to other scripts.
 */
(function () {
  "use strict";

  if (!("serviceWorker" in navigator) || !window.MessageChannel) return;

  var KEY_SETTINGS = "dm-offline-settings"; // {media: bool, auto: bool}
  var KEY_RUN = "dm-offline-run";           // an unfinished download
  var KEY_LAST = "dm-offline-last";         // when the last one finished
  var REFRESH_EVERY = 12 * 60 * 60 * 1000;

  function read(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function write(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* private mode: nothing to remember */ }
  }

  // Ask the service worker something and wait for its answer.
  function ask(message) {
    return navigator.serviceWorker.ready.then(function (registration) {
      var worker = navigator.serviceWorker.controller || registration.active;
      if (!worker) throw new Error("no worker");
      return new Promise(function (resolve, reject) {
        var channel = new MessageChannel();
        var timer = setTimeout(function () { reject(new Error("timeout")); }, 120000);
        channel.port1.onmessage = function (event) {
          clearTimeout(timer);
          channel.port1.close();
          resolve(event.data);
        };
        worker.postMessage(message, [channel.port2]);
      });
    });
  }

  // Is this a good moment to use data without asking?
  function onWifi() {
    var app = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Network;
    if (app) {
      return app.getStatus().then(function (s) { return s.connected && s.connectionType === "wifi"; })
        .catch(function () { return false; });
    }
    var c = navigator.connection;
    if (c && (c.saveData || c.type === "cellular" || /2g/.test(c.effectiveType || ""))) return Promise.resolve(false);
    return Promise.resolve(navigator.onLine);
  }

  var running = null;
  var listeners = [];
  function emit(state) { listeners.forEach(function (fn) { try { fn(state); } catch (e) {} }); }

  // Download (or refresh) lessons, one short step at a time.
  function download(options) {
    if (running) return running;
    options = options || {};
    var state = options.resume || null;
    var first = { type: "offline-download", media: !!options.media, limit: options.limit || 400 };
    running = (function loop() {
      return ask(state ? { type: "offline-download", state: state } : first).then(function (next) {
        state = next;
        write(KEY_RUN, state.done ? null : state);
        emit(state);
        if (!state.done) return loop();
        if (!state.stopped) write(KEY_LAST, Date.now());
        return state;
      });
    })().then(function (result) {
      running = null;
      return result;
    }, function (error) {
      running = null;
      throw error;
    });
    return running;
  }

  function status() { return ask({ type: "offline-status" }); }
  function syncNow() {
    return navigator.serviceWorker.ready.then(function (registration) {
      var worker = navigator.serviceWorker.controller || registration.active;
      if (worker) worker.postMessage("sync-learning");
    });
  }
  function clearAll() {
    write(KEY_RUN, null);
    write(KEY_LAST, null);
    return ask({ type: "offline-clear" });
  }

  window.DMOffline = { download: download, status: status, syncNow: syncNow, clear: clearAll,
    onProgress: function (fn) { listeners.push(fn); } };

  // ------------------------------------------------ in the background
  function background() {
    var settings = read(KEY_SETTINGS, null);
    if (!settings || !settings.auto || !navigator.onLine) return;
    var unfinished = read(KEY_RUN, null);
    var last = read(KEY_LAST, 0);
    if (!unfinished && Date.now() - last < REFRESH_EVERY) return;
    onWifi().then(function (ok) {
      if (!ok) return;
      download({ media: settings.media, resume: unfinished }).catch(function () {});
    });
  }
  window.addEventListener("load", function () { setTimeout(background, 4000); });
  window.addEventListener("online", function () { setTimeout(background, 4000); });

  // ------------------------------------------------------ the panel
  var panel = document.querySelector("[data-offline-sync]");
  if (!panel) return;

  function $(sel) { return panel.querySelector(sel); }
  var out = {
    pages: $("[data-os-pages]"), media: $("[data-os-media]"), pending: $("[data-os-pending]"),
    last: $("[data-os-last]"), status: $("[data-os-status]"), bar: $("[data-os-progress]"),
  };
  var mediaBox = $("[data-os-media-toggle]");
  var autoBox = $("[data-os-auto]");
  var downloadBtn = $("[data-os-download]");
  var syncBtn = $("[data-os-sync]");
  var clearBtn = $("[data-os-clear]");

  var saved = read(KEY_SETTINGS, { media: false, auto: true });
  if (mediaBox) mediaBox.checked = !!saved.media;
  if (autoBox) autoBox.checked = saved.auto !== false;
  function remember() {
    var s = read(KEY_SETTINGS, null);
    if (!s) return; // only once they've downloaded something
    write(KEY_SETTINGS, { media: mediaBox && mediaBox.checked, auto: autoBox && autoBox.checked });
  }
  if (mediaBox) mediaBox.addEventListener("change", remember);
  if (autoBox) autoBox.addEventListener("change", remember);

  function say(text) { if (out.status) out.status.textContent = text; }
  function when(time) {
    if (!time) return "Never";
    var d = new Date(time);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + ", " +
      d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }

  function refresh() {
    status().then(function (s) {
      if (out.pages) out.pages.textContent = s.pages;
      if (out.media) out.media.textContent = s.media;
      if (out.pending) out.pending.textContent = s.pending;
      if (out.last) out.last.textContent = when(read(KEY_LAST, 0));
    }).catch(function () { say("Offline lessons need a moment to get ready. Reload this page."); });
  }

  function showProgress(state) {
    if (!out.bar) return;
    var total = state.pages + (state.remaining || 0);
    out.bar.hidden = state.done;
    out.bar.max = Math.max(total, 1);
    out.bar.value = state.pages;
    if (!state.done) say("Downloading… " + state.pages + " pages saved" + (state.media_kept ? ", " + state.media_kept + " pictures and recordings" : "") + ".");
  }
  listeners.push(showProgress);

  function finished(state) {
    downloadBtn.disabled = false;
    if (state.stopped === "offline") say("The connection dropped. " + state.pages + " pages saved; tap Download again to carry on.");
    else if (state.stopped === "signed-out") say("Please sign in again, then download.");
    else if (state.stopped) say("Something went wrong. " + state.pages + " pages were saved; please try again.");
    else say("Done. " + state.pages + " pages" + (state.media_kept ? " and " + state.media_kept + " pictures and recordings" : "") + " are ready to use offline.");
    refresh();
  }

  if (downloadBtn) downloadBtn.addEventListener("click", function () {
    if (!navigator.onLine) { say("You're offline. Connect to the internet to download lessons."); return; }
    var withMedia = mediaBox && mediaBox.checked;
    onWifi().then(function (wifi) {
      if (!wifi && !window.confirm("You're not on Wi-Fi. Downloading lessons" + (withMedia ? " with pictures and audio" : "") +
          " uses mobile data. Carry on?")) return;
      write(KEY_SETTINGS, { media: withMedia, auto: autoBox ? autoBox.checked : true });
      downloadBtn.disabled = true;
      say("Starting…");
      download({ media: withMedia, resume: read(KEY_RUN, null) }).then(finished, function () {
        downloadBtn.disabled = false;
        say("The download stopped. Please try again.");
      });
    });
  });

  if (syncBtn) syncBtn.addEventListener("click", function () {
    if (!navigator.onLine) { say("You're offline. Your progress will be sent as soon as you reconnect."); return; }
    say("Sending your progress…");
    syncNow();
  });

  if (clearBtn) clearBtn.addEventListener("click", function () {
    if (!window.confirm("Remove the downloaded lessons from this device? Saved videos stay.")) return;
    write(KEY_SETTINGS, null);
    clearAll().then(function () { say("Downloaded lessons removed."); refresh(); });
  });

  navigator.serviceWorker.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.type === "learning-sync") {
      if (data.synced || data.dropped) say("Progress sent: " + data.synced + " item" + (data.synced === 1 ? "" : "s") + ".");
      else if (data.pending) say(data.pending + " item" + (data.pending === 1 ? " is" : "s are") + " waiting for a connection.");
      else say("Everything is up to date.");
      refresh();
    }
  });

  if (running) running.then(finished);
  refresh();
})();
