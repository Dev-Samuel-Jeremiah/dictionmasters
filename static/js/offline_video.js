/*
 * Keeping a lesson video on the device, for watching without the internet.
 *
 * What happens when a learner saves one:
 *
 *   1. The page asks Django whether this device may keep this video
 *      (/videos/prepare/). Django registers the device, applies the
 *      device limit and sets the date the copy runs out.
 *   2. The video is fetched through Django — never from storage — and
 *      written into this browser's own database in pieces, each piece
 *      encrypted as it arrives.
 *   3. The key is made here, by the browser, and marked so that it can
 *      never be read back out: this code can decrypt with it, but no
 *      code — ours or anyone's — can copy it out of the browser. A
 *      stolen database is therefore of no use on another device.
 *   4. To watch offline, the pieces are decrypted in memory and played.
 *      Nothing is written to disk in the clear, and there is no file to
 *      pass on to anybody.
 *
 * Whenever the app is online it checks with Django which copies are
 * still allowed, and quietly removes any that have run out or been taken
 * back.
 *
 * Being straight about the limit: this is not DRM. It keeps lessons off
 * the open web and makes casual copying pointless. It cannot stop
 * someone determined from recording their own screen.
 */
(function () {
  "use strict";

  var DB = "dm-offline-video";
  var VERSION = 1;
  var PIECE = 4 * 1024 * 1024;               // written in 4MB pieces
  var db = null;

  // ------------------------------------------------------------ storage

  function open() {
    if (db) return Promise.resolve(db);
    return new Promise(function (resolve, reject) {
      var request = indexedDB.open(DB, VERSION);
      request.onupgradeneeded = function () {
        var store = request.result;
        if (!store.objectStoreNames.contains("meta")) store.createObjectStore("meta");
        if (!store.objectStoreNames.contains("videos")) store.createObjectStore("videos", { keyPath: "id" });
        if (!store.objectStoreNames.contains("pieces")) {
          store.createObjectStore("pieces", { keyPath: ["id", "n"] });
        }
      };
      request.onsuccess = function () { db = request.result; resolve(db); };
      request.onerror = function () { reject(request.error); };
    });
  }

  function tx(store, mode) {
    return open().then(function (handle) {
      return handle.transaction(store, mode).objectStore(store);
    });
  }

  function ask(store, method, arg, arg2) {
    return tx(store, method === "get" || method === "getAll" ? "readonly" : "readwrite").then(function (s) {
      return new Promise(function (resolve, reject) {
        var request = arg2 === undefined ? s[method](arg) : s[method](arg, arg2);
        request.onsuccess = function () { resolve(request.result); };
        request.onerror = function () { reject(request.error); };
      });
    });
  }

  // ------------------------------------------------- this device, and its key

  function deviceId() {
    return ask("meta", "get", "device").then(function (found) {
      if (found) return found;
      var made = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
      return ask("meta", "put", made, "device").then(function () { return made; });
    });
  }

  function deviceName() {
    var ua = navigator.userAgent || "";
    var device = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android phone"
      : /Macintosh/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows PC" : "This device";
    var browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox"
      : /Safari\//.test(ua) ? "Safari" : "browser";
    return device + " · " + browser;
  }

  /* The key never leaves the browser: extractable is false, so even this
     code cannot read it back — only ask the browser to decrypt with it. */
  function key() {
    return ask("meta", "get", "key").then(function (found) {
      if (found) return found;
      return crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"])
        .then(function (made) {
          return ask("meta", "put", made, "key").then(function () { return made; });
        });
    });
  }

  // ------------------------------------------------------------ fetching

  function save(entry, onProgress) {
    var record = null;
    return Promise.all([deviceId(), key()]).then(function (both) {
      var device = both[0], secret = both[1];
      return fetch("/videos/prepare/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
        body: JSON.stringify({ ticket: entry.ticket, device: device, device_name: deviceName(), title: entry.title })
      }).then(readJson).then(function (allowed) {
        if (!allowed.ok) {
          var denied = new Error(allowed.error || "That copy isn't allowed.");
          denied.code = allowed.code || "";
          throw denied;
        }
        record = {
          id: entry.ticketId, licence: allowed.id, title: allowed.title, size: allowed.size,
          type: allowed.content_type, expires: allowed.expires_at, watch: allowed.watch_url,
          page: location.pathname, pieces: 0, device: device
        };
        return stream(allowed.url, secret, record, onProgress).catch(function (error) {
          // Prepare reserves a licence before bytes arrive. If the transfer
          // fails, release it and remove any partial encrypted chunks.
          return ask("pieces", "getAll").catch(function () { return []; }).then(function (pieces) {
            var cleanup = Promise.resolve();
            (pieces || []).forEach(function (piece) {
              if (piece.id === record.id) {
                cleanup = cleanup.then(function () { return ask("pieces", "delete", [piece.id, piece.n]); });
              }
            });
            return cleanup.catch(function () { /* still release the server licence */ });
          }).then(function () {
            return fetch("/videos/release/", {
              method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
              body: JSON.stringify({ id: record.licence, device: record.device })
            }).catch(function () { /* Django can clean it up on the next attempt */ });
          }).then(function () { throw error; });
        });
      });
    }).then(function () {
      return ask("videos", "put", record).then(function () { return record; });
    });
  }

  function stream(url, secret, record, onProgress) {
    return fetch(url, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("The video couldn't be fetched (" + response.status + ").");
      var reader = response.body && response.body.getReader ? response.body.getReader() : null;
      if (!reader) {
        // Older browsers: take it in one go, then cut it into pieces.
        return response.arrayBuffer().then(function (whole) {
          return writePieces(new Uint8Array(whole), secret, record, onProgress);
        });
      }
      var held = [], filled = 0, done = 0, number = 0, chain = Promise.resolve();
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) {
            if (filled) chain = chain.then(function () { return writePiece(join(held, filled), secret, record, number++); });
            return chain.then(function () { record.pieces = number; });
          }
          held.push(step.value);
          filled += step.value.length;
          done += step.value.length;
          if (onProgress && record.size) onProgress(Math.min(99, Math.round(done * 100 / record.size)));
          if (filled >= PIECE) {
            var piece = join(held, filled), n = number++;
            held = []; filled = 0;
            chain = chain.then(function () { return writePiece(piece, secret, record, n); });
          }
          return pump();
        });
      }
      return pump();
    });
  }

  function writePieces(bytes, secret, record, onProgress) {
    var chain = Promise.resolve(), number = 0;
    for (var at = 0; at < bytes.length; at += PIECE) {
      (function (piece, n) {
        chain = chain.then(function () {
          if (onProgress && record.size) onProgress(Math.min(99, Math.round((n + 1) * PIECE * 100 / record.size)));
          return writePiece(piece, secret, record, n);
        });
      })(bytes.slice(at, at + PIECE), number++);
    }
    return chain.then(function () { record.pieces = number; });
  }

  function writePiece(bytes, secret, record, n) {
    var iv = crypto.getRandomValues(new Uint8Array(12));
    return crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, secret, bytes).then(function (sealed) {
      return ask("pieces", "put", { id: record.id, n: n, iv: iv, data: sealed });
    });
  }

  function join(parts, length) {
    var whole = new Uint8Array(length), at = 0;
    parts.forEach(function (part) { whole.set(part, at); at += part.length; });
    return whole;
  }

  // ------------------------------------------------------------ playing

  function blobFor(record) {
    return key().then(function (secret) {
      var pieces = [];
      var chain = Promise.resolve();
      for (var n = 0; n < record.pieces; n++) {
        (function (index) {
          chain = chain.then(function () {
            return ask("pieces", "get", [record.id, index]).then(function (piece) {
              if (!piece) throw new Error("This copy is incomplete. Save it again.");
              return crypto.subtle.decrypt({ name: "AES-GCM", iv: piece.iv }, secret, piece.data)
                .then(function (plain) { pieces.push(new Uint8Array(plain)); });
            });
          });
        })(n);
      }
      return chain.then(function () { return new Blob(pieces, { type: record.type || "video/mp4" }); });
    });
  }

  function forget(record) {
    var chain = Promise.resolve();
    for (var n = 0; n < record.pieces; n++) {
      (function (index) { chain = chain.then(function () { return ask("pieces", "delete", [record.id, index]); }); })(n);
    }
    return chain.then(function () { return ask("videos", "delete", record.id); }).then(function () {
      return fetch("/videos/release/", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
        body: JSON.stringify({ id: record.licence, device: record.device })
      }).catch(function () { /* offline: Django hears about it next time */ });
    });
  }

  // ---------------------------------------------------- keeping in step

  function refresh() {
    if (!navigator.onLine) return Promise.resolve();
    return deviceId().then(function (device) {
      return fetch("/videos/licenses/", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
        body: JSON.stringify({ device: device })
      }).then(readJson).then(function (answer) {
        if (!answer.ok) return null;
        var live = {};
        answer.licenses.forEach(function (row) { live[row.id] = row; });
        return ask("videos", "getAll").then(function (kept) {
          var chain = Promise.resolve();
          (kept || []).forEach(function (record) {
            var row = live[record.licence];
            if (!row || !row.live) {
              chain = chain.then(function () { return forget(record); });
            } else if (row.expires_at !== record.expires) {
              record.expires = row.expires_at;
              chain = chain.then(function () { return ask("videos", "put", record); });
            }
          });
          return chain;
        });
      });
    }).catch(function () { /* nothing to do while offline */ });
  }

  function readJson(response) {
    return response.json().catch(function () { return { ok: false, error: "Something went wrong." }; });
  }

  function token() {
    var field = document.querySelector("input[name='csrfmiddlewaretoken']");
    if (field) return field.value;
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : "";
  }

  function when(iso) {
    try {
      return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    } catch (error) { return ""; }
  }

  // ------------------------------------------------------------ the page

  function wire(box) {
    var video = box.querySelector("[data-video-el]");
    var keepButton = box.querySelector("[data-offline-keep]");
    var watchButton = box.querySelector("[data-offline-watch]");
    var removeButton = box.querySelector("[data-offline-remove]");
    var state = box.querySelector("[data-offline-state]");
    var progress = box.querySelector("[data-offline-progress]");
    var figure = box.querySelector("[data-offline-figure]");
    if (!keepButton) return;

    var entry = {
      ticket: box.dataset.ticket,
      title: box.dataset.title || "Lesson video",
      ticketId: box.dataset.videoId                       // which lesson video this is
    };
    var record = null, playing = false, recordLoaded = false;
    keepButton.disabled = true;

    function say(text, tone) {
      state.hidden = !text;
      state.textContent = text || "";
      state.className = "vid__state" + (tone ? " vid__state--" + tone : "");
    }

    function showProgress(percent) {
      progress.hidden = false;
      progress.firstElementChild.style.width = Math.max(percent, 2) + "%";
      if (figure) figure.textContent = percent + "%";
    }

    function show() {
      var kept = !!record;
      keepButton.hidden = false;
      keepButton.disabled = kept || !recordLoaded;
      keepButton.lastChild.textContent = kept ? " ✓ Already downloaded" : " Save for offline";
      keepButton.setAttribute("aria-label", kept ? "Already downloaded on this device" : "Save for offline");
      keepButton.classList.toggle("vid__btn--saved", kept);
      watchButton.hidden = !kept;
      removeButton.hidden = !kept;
      progress.hidden = true;
      var manageDevices = box.querySelector("[data-manage-devices]");
      if (manageDevices) manageDevices.hidden = true;
      if (kept) say("✓ Saved on this device · until " + when(record.expires), "good");
      else say("");
    }

    ask("videos", "get", entry.ticketId).then(function (found) {
      record = found || null;
      recordLoaded = true;
      show();
    }).catch(function () {
      recordLoaded = true;
      show();
    });

    keepButton.addEventListener("click", function () {
      if (!recordLoaded) return;
      if (record) {
        say("✓ Already downloaded on this device", "good");
        return;
      }
      keepButton.disabled = true;
      keepButton.lastChild.textContent = " Saving…";
      showProgress(0);
      say("Getting your copy ready…", "working");
      save(entry, function (percent) {
        showProgress(percent);
        say("Saving for offline — " + percent + "% done", "working");
      }).then(function (made) {
        keepButton.lastChild.textContent = " Save for offline";
        record = made;
        keepButton.disabled = false;
        show();
      }).catch(function (error) {
        keepButton.disabled = false;
        keepButton.lastChild.textContent = " Save for offline";
        progress.hidden = true;
        say(error.message || "That didn't work. Please try again.", "bad");
        var manageDevices = box.querySelector("[data-manage-devices]");
        if (manageDevices) manageDevices.hidden = error.code !== "device_limit";
      });
    });

    watchButton.addEventListener("click", function () {
      if (!record) return;
      say("Opening your copy…");
      blobFor(record).then(function (blob) {
        if (playing) URL.revokeObjectURL(video.src);
        video.src = URL.createObjectURL(blob);
        playing = true;
        video.play().catch(function () { /* the learner can press play */ });
        say("▶ Playing your offline copy · until " + when(record.expires), "good");
      }).catch(function (error) {
        say(error.message || "That copy couldn't be opened.", "bad");
      });
    });

    removeButton.addEventListener("click", function () {
      if (!record) return;
      say("Removing…");
      forget(record).then(function () {
        record = null;
        if (playing) { URL.revokeObjectURL(video.src); playing = false; }
        show();
      });
    });
  }

  function start() {
    var boxes = document.querySelectorAll("[data-video][data-ticket]");
    if (!boxes.length && !document.querySelector("[data-offline-list]")) return;
    refresh().then(function () {
      Array.prototype.forEach.call(boxes, wire);
      var list = document.querySelector("[data-offline-list]");
      if (list) fillList(list);
    });
  }

  // boot.js injects this file only on pages with a video. Dynamically
  // inserted scripts can finish loading after DOMContentLoaded, in which
  // case a listener registered here would never run and no buttons receive
  // their handlers.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }

  // The "Offline videos" page: what this device is holding.
  function fillList(list) {
    ask("videos", "getAll").then(function (kept) {
      list.innerHTML = "";
      if (!kept || !kept.length) {
        list.innerHTML = '<li class="vid-kept__none">Nothing saved on this device yet. ' +
          'Open a lesson video and choose “Save for offline”.</li>';
        return;
      }
      kept.forEach(function (record) {
        var row = document.createElement("li");
        row.className = "vid-kept";
        row.innerHTML = '<div class="vid-kept__body"><p class="vid-kept__title"></p>' +
          '<p class="vid-kept__note"></p></div>' +
          '<video class="vid-kept__player" controls playsinline hidden></video>' +
          '<div class="vid-kept__actions">' +
          '<button type="button" class="vid__btn vid__btn--watch">&#9654; Watch offline</button>' +
          '<a class="vid__btn vid__btn--lesson" href="">Open the lesson</a>' +
          '<button type="button" class="vid__btn vid__btn--remove">Remove</button></div>';
        row.querySelector(".vid-kept__title").textContent = record.title;
        row.querySelector(".vid-kept__note").textContent = "Saved on this device · until " + when(record.expires);
        row.querySelector(".vid__btn--lesson").href = record.page || "/";
        var player = row.querySelector("video");
        row.querySelector(".vid__btn--watch").addEventListener("click", function () {
          blobFor(record).then(function (blob) {
            player.hidden = false;
            player.src = URL.createObjectURL(blob);
            player.play().catch(function () {});
          });
        });
        row.querySelector(".vid__btn--remove").addEventListener("click", function () {
          forget(record).then(function () { fillList(list); });
        });
        list.appendChild(row);
      });
    });
  }
})();
