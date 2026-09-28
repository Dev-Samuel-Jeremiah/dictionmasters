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

  /* A download that stops part-way (the network drops, the phone sleeps,
     the learner taps Pause) is not thrown away. Every 4MB piece already
     written stays in the database, and a note of how far it got is kept
     under "partial:<id>" in meta. Continuing asks the server for the rest
     of the file only (a Range request) and carries on from the next piece. */
  var STALL = 25000;                          // no bytes for this long: treat as dropped

  function partialKey(id) { return "partial:" + id; }

  function partialFor(id) {
    return ask("meta", "get", partialKey(id)).catch(function () { return null; });
  }

  function dropPieces(id, count) {
    var chain = Promise.resolve();
    for (var n = 0; n < count; n++) {
      (function (index) { chain = chain.then(function () { return ask("pieces", "delete", [id, index]); }); })(n);
    }
    return chain.catch(function () { /* nothing left to remove */ });
  }

  // Give up a half-finished download: its pieces, its note, and the server's licence.
  function cancelPartial(id) {
    return partialFor(id).then(function (partial) {
      if (!partial) return null;
      return dropPieces(id, partial.pieces + 1).then(function () {
        return ask("meta", "delete", partialKey(id));
      }).then(function () {
        return fetch("/videos/release/", {
          method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
          body: JSON.stringify({ id: partial.licence, device: partial.device })
        }).catch(function () { /* Django can clean it up on the next attempt */ });
      });
    });
  }

  function save(entry, onProgress, control) {
    var record = null;
    return Promise.all([deviceId(), key()]).then(function (both) {
      var device = both[0], secret = both[1];
      // Asked again on every start and every continue: it's the same licence
      // each time, and it hands back a fresh address if the old one ran out.
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
        return partialFor(entry.ticketId).then(function (partial) {
          var carryOn = partial && partial.size === allowed.size && partial.licence === allowed.id;
          record = {
            id: entry.ticketId, licence: allowed.id, title: allowed.title, size: allowed.size,
            type: allowed.content_type, expires: allowed.expires_at, watch: allowed.watch_url,
            page: location.pathname, pieces: carryOn ? partial.pieces : 0, device: device
          };
          var clear = carryOn || !partial ? Promise.resolve() : dropPieces(record.id, partial.pieces + 1);
          return clear.then(function () {
            return ask("meta", "put", record, partialKey(record.id));
          }).then(function () {
            return stream(allowed.url, secret, record, onProgress, control);
          });
        });
      });
    }).then(function () {
      return ask("videos", "put", record).then(function () {
        return ask("meta", "delete", partialKey(record.id)).catch(function () {});
      }).then(function () { return record; });
    });
  }

  function stream(url, secret, record, onProgress, control) {
    var from = record.pieces * PIECE;
    var aborter = "AbortController" in window ? new AbortController() : null;
    var why = "";
    var chain = Promise.resolve();
    var stall = null;

    function stop(reason) {
      why = reason;
      if (aborter) aborter.abort();
    }
    if (control) control.stop = stop;
    function watch() {
      window.clearTimeout(stall);
      stall = window.setTimeout(function () { stop("stalled"); }, STALL);
    }

    // Each piece is written, then the note of how far we've got moves on.
    function commit(piece, n) {
      chain = chain.then(function () { return writePiece(piece, secret, record, n); }).then(function () {
        record.pieces = n + 1;
        return ask("meta", "put", record, partialKey(record.id));
      });
    }

    watch();
    return fetch(url, {
      credentials: "same-origin",
      headers: from ? { Range: "bytes=" + from + "-" } : {},
      signal: aborter ? aborter.signal : undefined
    }).then(function (response) {
      if (!response.ok) throw new Error("The video couldn't be fetched (" + response.status + ").");
      if (from && response.status !== 206) {
        // The server sent the whole file after all: start from the top.
        from = 0;
        record.pieces = 0;
      }
      var reader = response.body && response.body.getReader ? response.body.getReader() : null;
      if (!reader) {
        // Older browsers: take the rest in one go, then cut it into pieces.
        return response.arrayBuffer().then(function (whole) {
          var bytes = new Uint8Array(whole), number = record.pieces;
          for (var at = 0; at < bytes.length; at += PIECE) commit(bytes.slice(at, at + PIECE), number++);
          return chain;
        });
      }
      var held = [], filled = 0, done = from, number = record.pieces;
      function pump() {
        return reader.read().then(function (step) {
          watch();
          if (step.done) {
            if (filled) commit(join(held, filled), number++);
            return chain;
          }
          held.push(step.value);
          filled += step.value.length;
          done += step.value.length;
          if (onProgress && record.size) onProgress(Math.min(99, Math.round(done * 100 / record.size)));
          if (filled >= PIECE) {
            commit(join(held, filled), number++);
            held = []; filled = 0;
          }
          return pump();
        });
      }
      return pump();
    }).then(function () {
      window.clearTimeout(stall);
    }, function (error) {
      window.clearTimeout(stall);
      // Let pieces already on their way finish landing, so Continue picks up after them.
      return chain.catch(function () {}).then(function () {
        var paused;
        if (error && error.name === "QuotaExceededError") {
          paused = new Error("This device is out of space. Free some up, then continue.");
        } else if (why === "paused") {
          paused = new Error("Paused.");
        } else if (why === "stalled") {
          paused = new Error("The download stopped moving — the connection may have dropped.");
        } else if (!navigator.onLine) {
          paused = new Error("You're offline, so the download paused.");
        } else {
          paused = new Error((error && error.message) || "The download was interrupted.");
        }
        paused.code = "paused";
        paused.why = why;
        throw paused;
      });
    });
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
    var resumeButton = box.querySelector("[data-offline-resume]");
    var pauseButton = box.querySelector("[data-offline-pause]");
    var cancelButton = box.querySelector("[data-offline-cancel]");
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
    // "idle", "saving" or "paused"; control.stop() interrupts a download.
    var mode = "idle", control = {}, lastPercent = 0, autoResumed = false;
    keepButton.disabled = true;

    function say(text, tone) {
      state.hidden = !text;
      state.textContent = text || "";
      state.className = "vid__state" + (tone ? " vid__state--" + tone : "");
    }

    function showProgress(percent) {
      lastPercent = percent;
      progress.hidden = false;
      progress.firstElementChild.style.width = Math.max(percent, 2) + "%";
      if (figure) figure.textContent = percent + "%";
    }

    function show() {
      var kept = !!record;
      keepButton.hidden = mode !== "idle";
      keepButton.disabled = kept || !recordLoaded;
      keepButton.lastChild.textContent = kept ? " ✓ Already downloaded" : " Save for offline";
      keepButton.setAttribute("aria-label", kept ? "Already downloaded on this device" : "Save for offline");
      keepButton.classList.toggle("vid__btn--saved", kept);
      resumeButton.hidden = mode !== "paused";
      pauseButton.hidden = mode !== "saving";
      cancelButton.hidden = mode === "idle";
      watchButton.hidden = !kept;
      removeButton.hidden = !kept;
      progress.hidden = mode === "idle";
      var manageDevices = box.querySelector("[data-manage-devices]");
      if (manageDevices && mode !== "idle") manageDevices.hidden = true;
      if (mode === "idle") {
        if (kept) say("✓ Saved on this device · until " + when(record.expires), "good");
        else if (!state.classList.contains("vid__state--bad")) say("");
      }
    }

    function begin(fresh) {
      mode = "saving";
      autoResumed = false;
      show();
      showProgress(lastPercent);
      say(fresh ? "Getting your copy ready…" : "Continuing from " + lastPercent + "%…", "working");
      control = {};
      save(entry, function (percent) {
        showProgress(percent);
        say("Saving for offline — " + percent + "% done", "working");
      }, control).then(function (made) {
        record = made;
        mode = "idle";
        show();
      }).catch(function (error) {
        if (error.code === "paused") {
          if (error.why === "cancel") return;           // handled by the Cancel button
          mode = "paused";
          show();
          showProgress(lastPercent);
          say((error.why === "paused" ? "Paused at " + lastPercent + "%." : error.message + " Saved so far: " + lastPercent + "%.") +
              " Tap “Continue download” to carry on from there.", error.why === "paused" ? "working" : "bad");
          return;
        }
        // Not allowed at all (plan, device limit…): nothing to continue.
        mode = "idle";
        show();
        say(error.message || "That didn't work. Please try again.", "bad");
        var manageDevices = box.querySelector("[data-manage-devices]");
        if (manageDevices) manageDevices.hidden = error.code !== "device_limit";
      });
    }

    Promise.all([
      ask("videos", "get", entry.ticketId).catch(function () { return null; }),
      partialFor(entry.ticketId)
    ]).then(function (found) {
      record = found[0] || null;
      recordLoaded = true;
      if (!record && found[1]) {
        // A download that stopped last time: offer to finish it.
        mode = "paused";
        var partial = found[1];
        lastPercent = partial.size ? Math.min(99, Math.round(partial.pieces * PIECE * 100 / partial.size)) : 0;
        show();
        showProgress(lastPercent);
        say("Your download stopped at " + lastPercent + "%. Tap “Continue download” to finish it.", "working");
        return;
      }
      show();
    });

    keepButton.addEventListener("click", function () {
      if (!recordLoaded || mode !== "idle") return;
      if (record) {
        say("✓ Already downloaded on this device", "good");
        return;
      }
      lastPercent = 0;
      begin(true);
    });

    resumeButton.addEventListener("click", function () {
      if (mode === "paused") begin(false);
    });

    pauseButton.addEventListener("click", function () {
      if (mode === "saving" && control.stop) control.stop("paused");
    });

    cancelButton.addEventListener("click", function () {
      if (mode === "saving" && control.stop) control.stop("cancel");
      say("Cancelling…");
      // Give an interrupted write a moment to settle before clearing up.
      window.setTimeout(function () {
        cancelPartial(entry.ticketId).then(function () {
          mode = "idle";
          lastPercent = 0;
          show();
          say("Download cancelled.");
        });
      }, 300);
    });

    // Back online after the connection dropped: carry on by itself, once.
    window.addEventListener("online", function () {
      if (mode === "paused" && !autoResumed && state.classList.contains("vid__state--bad")) {
        autoResumed = true;
        begin(false);
      }
    });
    // Going offline mid-download: pause straight away rather than wait.
    window.addEventListener("offline", function () {
      if (mode === "saving" && control.stop) control.stop("stalled");
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
