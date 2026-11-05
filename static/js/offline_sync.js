/*
 * Lessons on this device: download them for offline study, and keep them
 * up to date (templates/pwa/sw.js does the storing; the server lists what
 * this learner may keep in apps/offline/catalog.py).
 *
 * Loaded on every page for signed-in learners (templates/base.html):
 *
 *   - On the "Offline lessons & videos" page ([data-offline-sync], in
 *     templates/videos/offline.html) it runs the panel: download, sync
 *     now, remove, and what's on this device.
 *   - Everywhere, once a learner has downloaded lessons, it quietly
 *     refreshes them about twice a day when the device is online on Wi-Fi,
 *     and carries on a download that was interrupted by leaving the page.
 *   - In the Android, iPhone and computer apps this starts by itself: the
 *     first time a learner is signed in on Wi-Fi, their lessons (with pictures
 *     and audio), then their level's videos, are saved on the device, so the
 *     app works with no internet from then on, with a small note showing how
 *     far it's got. On mobile data it saves just the most-used pages, to
 *     spare data.
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

  // One set per learner: on a shared tablet each has their own lessons, so
  // their own schedule (templates/pwa/sw.js, "learners").
  var WHO = document.documentElement.getAttribute("data-learner") || "";
  var FOR = WHO ? ":" + WHO : "";
  var KEY_SETTINGS = "dm-offline-settings" + FOR; // {media: bool, auto: bool}
  var KEY_RUN = "dm-offline-run" + FOR;           // an unfinished download
  var KEY_LAST = "dm-offline-last" + FOR;         // when the last one finished
  var KEY_NEXT = "dm-offline-next" + FOR;         // when the next one is due
  var REFRESH_EVERY = 12 * 60 * 60 * 1000;
  // Each device picks its own time, so they don't all reach the server at once.
  var REFRESH_SPREAD = 6 * 60 * 60 * 1000;
  var PAUSE_BETWEEN_STEPS = 400;            // in the background, gentle on the server
  var SHOW_NOTE_FROM = 30;                  // pages: a small refresh goes unnoticed

  function read(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (e) { return fallback; }
  }
  function write(key, value) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* private mode: nothing to remember */ }
  }

  // Ask the service worker something and wait for its answer. A step of a
  // download answers within about 8 seconds; this only catches a worker
  // that has gone quiet altogether.
  function ask(message) {
    return navigator.serviceWorker.ready.then(function (registration) {
      var worker = navigator.serviceWorker.controller || registration.active;
      if (!worker) throw new Error("no worker");
      return new Promise(function (resolve, reject) {
        var channel = new MessageChannel();
        var timer = setTimeout(function () { reject(new Error("timeout")); }, 300000);
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

  // How far a sync has got: pages, then their pictures and audio, together.
  function done(state) {
    return state.pages + (state.skipped || 0) + (state.media_kept || 0) + (state.failed || 0);
  }
  function percent(state) {
    var total = done(state) + (state.remaining || 0);
    return total ? Math.min(99, Math.floor(done(state) * 100 / total)) : 0;
  }

  var running = null;
  var listeners = [];
  function emit(state) { listeners.forEach(function (fn) { try { fn(state); } catch (e) {} }); }

  // Download (or refresh) lessons, one short step at a time.
  function download(options) {
    if (running) return running;
    options = options || {};
    var state = null;
    var first = { type: "offline-download", media: !!options.media, limit: options.limit || 0 };
    running = (function loop() {
      return ask(state ? { type: "offline-download", state: state } : first).then(function (next) {
        state = next;
        write(KEY_RUN, state.done ? null : 1);   // the next sync picks up what's missing
        emit(state);
        if (!state.done) {
          if (!options.gentle) return loop();
          return new Promise(function (resolve) { setTimeout(resolve, PAUSE_BETWEEN_STEPS); }).then(loop);
        }
        if (!state.stopped) {
          write(KEY_LAST, Date.now());
          write(KEY_NEXT, Date.now() + REFRESH_EVERY + Math.random() * REFRESH_SPREAD);
        }
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
    write(KEY_NEXT, null);
    return ask({ type: "offline-clear" });
  }

  window.DMOffline = { download: download, status: status, syncNow: syncNow, clear: clearAll,
    onProgress: function (fn) { listeners.push(fn); } };

  // ------------------------------------------------ in the background
  var inApp = document.documentElement.hasAttribute("data-native-app");
  var KEY_ESSENTIALS = "dm-offline-essentials" + FOR; // when the mobile-data top-up last ran
  var KEY_ASKED_TO_STAY = "dm-offline-persist";

  // The note in the corner of the app: how far a big download has got.
  var note = null;
  function showNote(text, link) {
    if (!note) {
      note = document.createElement("a");
      note.className = "offline-note";
      note.href = "/videos/offline/";
      note.setAttribute("role", "status");
      document.body.appendChild(note);
    }
    note.textContent = text;
    note.hidden = false;
    note.classList.toggle("offline-note--tap", !!link);
  }
  function hideNote(after) {
    if (note) setTimeout(function () { note.hidden = true; }, after);
  }

  function noteProgress(state) {
    if (!state.done && done(state) + (state.remaining || 0) >= SHOW_NOTE_FROM) {
      showNote("Saving lessons for offline… " + percent(state) + "%");
    }
  }
  function megabytes(mb) {
    return mb >= 1000 ? (Math.ceil(mb / 100) / 10) + " GB" : mb + " MB";
  }

  // A browser may clear a site's storage when it's short of room. This asks
  // it not to, once. It may say no; the next sync then fetches what went.
  function askToStay() {
    if (read(KEY_ASKED_TO_STAY, false) || !navigator.storage || !navigator.storage.persist) return;
    write(KEY_ASKED_TO_STAY, true);
    navigator.storage.persist().catch(function () {});
  }

  // The level's videos, one at a time, once its lessons are in. Only in the
  // apps, only on Wi-Fi; if the page closes, the next one carries on.
  var videosRunning = false;
  function loadVideoScript() {
    if (window.DMOfflineVideos) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var scripts = JSON.parse(document.getElementById("page-scripts").textContent);
      var tag = document.createElement("script");
      tag.src = scripts.offline[0];
      tag.onload = resolve;
      tag.onerror = reject;
      document.head.appendChild(tag);
    });
  }
  function saveVideos(refs) {
    if (videosRunning || !refs || !refs.length) return;
    videosRunning = true;
    loadVideoScript().then(function () {
      return window.DMOfflineVideos.saveAll(refs, {
        allowed: onWifi,
        progress: function (done, total) {
          showNote("Saving videos for offline… " + done + " of " + total);
          if (done === total) hideNote(4000);
        },
        lowSpace: function () { showNote("This device is nearly full, so the rest of the videos weren't saved.", true); },
      });
    }).catch(function () {}).then(function () {
      videosRunning = false;
      hideNote(4000);
    });
  }

  function backgroundDone(state, settings) {
    if (state.low_space_mb) {
      showNote("Lessons saved. Free up " + megabytes(state.low_space_mb) + " to save their pictures and audio.", true);
      return;
    }
    if (state.stopped) { hideNote(0); return; }
    if (state.pages >= SHOW_NOTE_FROM) {
      showNote("Your lessons are ready offline ✓");
      hideNote(4000);
    }
    if (inApp && settings.media) saveVideos(state.videos);
  }

  function background() {
    var settings = read(KEY_SETTINGS, null);
    if (!settings && inApp) {
      // The app works offline out of the box: switched on the first time.
      settings = { media: true, auto: true, fromApp: true };
      write(KEY_SETTINGS, settings);
    }
    if (!settings || !settings.auto || !navigator.onLine) return;
    var unfinished = read(KEY_RUN, null);
    var last = read(KEY_LAST, 0);
    if (!read(KEY_NEXT, 0) && last) {
      // Saved lessons from before this version: each device picks its own
      // time within the next 12 hours, so they don't all fetch at once.
      write(KEY_NEXT, Date.now() + Math.random() * REFRESH_EVERY);
      return;
    }
    if (!unfinished && Date.now() < read(KEY_NEXT, 0)) {
      // Lessons are up to date: carry on with any videos still to come.
      onWifi().then(function (ok) {
        if (ok && inApp && settings.media) ask({ type: "offline-videos" }).then(saveVideos).catch(function () {});
      });
      return;
    }
    onWifi().then(function (ok) {
      if (ok) {
        askToStay();
        download({ media: settings.media, gentle: true }).then(function (state) {
          backgroundDone(state, settings);
        }).catch(function () {
          // The worker went quiet (the browser may have stopped it). What came
          // down is kept; carry on in a minute.
          if (note && !note.hidden) showNote("Saving paused. It will carry on in a moment…");
          setTimeout(background, 60000);
        });
        return;
      }
      // Mobile data, in the app: just the front pages and the first lessons,
      // once a day, without pictures or audio, so the app still opens offline.
      if (inApp && !unfinished && Date.now() - read(KEY_ESSENTIALS, 0) > REFRESH_EVERY * 2) {
        write(KEY_ESSENTIALS, Date.now());
        download({ media: false, limit: 60 }).then(function (state) {
          // Not a full download: the Wi-Fi one stays due.
          write(KEY_LAST, last || 0);
          return state;
        }).catch(function () {});
      }
    });
  }
  if (inApp) listeners.push(noteProgress);
  window.addEventListener("load", function () { setTimeout(background, 4000); });
  window.addEventListener("online", function () { setTimeout(background, 4000); });

  // ------------------------------------------------------ the panel
  var panel = document.querySelector("[data-offline-sync]");
  if (!panel) return;

  function $(sel) { return panel.querySelector(sel); }
  var out = {
    pages: $("[data-os-pages]"), media: $("[data-os-media]"), pending: $("[data-os-pending]"),
    last: $("[data-os-last]"), status: $("[data-os-status]"), bar: $("[data-os-progress]"), until: $("[data-os-until]"),
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
      if (out.until) {
        out.until.textContent = s.until === null || s.until === undefined ? "–"
          : s.until > Date.now() ? new Date(s.until).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
          : "Connect to reopen";
      }
    }).catch(function () { say("Offline lessons need a moment to get ready. Reload this page."); });
  }

  function showProgress(state) {
    if (!out.bar) return;
    out.bar.hidden = state.done;
    out.bar.max = 100;
    out.bar.value = percent(state);
    if (!state.done) say("Downloading… " + percent(state) + "% · " + state.pages + " pages" + (state.media_kept ? ", " + state.media_kept + " pictures and recordings" : "") + " saved.");
  }
  listeners.push(showProgress);

  function finished(state) {
    downloadBtn.disabled = false;
    if (state.stopped === "offline") say("The connection dropped. " + state.pages + " pages saved; tap Download again to carry on.");
    else if (state.stopped === "signed-out") say("Please sign in again, then download.");
    else if (state.stopped === "no-access") say("Your plan has ended, so new lessons can't be downloaded.");
    else if (state.stopped) say("Something went wrong. " + state.pages + " pages were saved; please try again.");
    else if (state.low_space_mb) say("Lessons saved, but not their pictures and audio: free up " + megabytes(state.low_space_mb) + " on this device, then download again.");
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
      download({ media: withMedia }).then(finished, function () {
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
