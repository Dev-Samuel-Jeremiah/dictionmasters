/*
 * Loading a lesson pack from a file — a flash drive, say — instead of
 * downloading a level's pictures and recordings over the internet
 * (templates/videos/offline.html, "Load lessons from a file").
 *
 * The pack (apps/offline/packs.py) is one level's files, each piece sealed
 * with the pack's own key. The server gives that key only to a signed-in
 * learner of that level with a plan running, so this needs a moment of
 * internet. Each file is opened here, then handed to the service worker,
 * which seals it again with this device's own key and keeps it with the
 * synced lessons (templates/pwa/sw.js, "offline-import"). Files already on
 * the device are skipped, so a load that's cut off can simply be run again.
 * A sync afterwards brings the lesson pages, which are small.
 */
(function () {
  "use strict";

  var box = document.querySelector("[data-pack]");
  if (!box || !("serviceWorker" in navigator) || !window.crypto || !crypto.subtle || !window.Blob || !Blob.prototype.arrayBuffer) return;
  box.hidden = false;

  var input = box.querySelector("[data-pack-file]");
  var bar = box.querySelector("[data-pack-progress]");
  var status = box.querySelector("[data-pack-status]");
  var MAGIC = "DMPACK1\n";

  function say(text) { status.textContent = text; }

  function slice(file, from, to) { return file.slice(from, to).arrayBuffer(); }

  function fromBase64(text) {
    var raw = atob(text), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function megabytes(bytes) {
    var mb = Math.ceil(bytes / 1048576);
    return mb >= 1000 ? (Math.ceil(mb / 100) / 10) + " GB" : mb + " MB";
  }

  // Ask the service worker something, handing it bytes without copying them.
  function ask(message, transfer) {
    return navigator.serviceWorker.ready.then(function (registration) {
      var worker = navigator.serviceWorker.controller || registration.active;
      return new Promise(function (resolve, reject) {
        var channel = new MessageChannel();
        var timer = setTimeout(function () { reject(new Error("The app stopped answering. Reload the page and try again.")); }, 120000);
        channel.port1.onmessage = function (event) { clearTimeout(timer); channel.port1.close(); resolve(event.data); };
        worker.postMessage(message, [channel.port2].concat(transfer || []));
      });
    });
  }

  function readIndex(file) {
    return slice(file, 0, MAGIC.length).then(function (head) {
      if (new TextDecoder().decode(head) !== MAGIC) throw new Error("That file isn't a Diction Masters lesson pack.");
      return slice(file, file.size - 8, file.size);
    }).then(function (tail) {
      var view = new DataView(tail);
      var length = view.getUint32(0) * 4294967296 + view.getUint32(4);
      return slice(file, file.size - 8 - length, file.size - 8);
    }).then(function (raw) {
      return JSON.parse(new TextDecoder().decode(raw));
    });
  }

  function unlock(index) {
    if (!navigator.onLine) return Promise.reject(new Error("Connect to the internet for a moment, so the pack can be unlocked for you."));
    return fetch("/offline-sync/pack/" + index.pack + "/", { credentials: "same-origin" }).then(function (response) {
      return response.json().catch(function () { return {}; });
    }).then(function (answer) {
      if (!answer.ok) throw new Error(answer.error || "This pack couldn't be unlocked. Sign in and try again.");
      return crypto.subtle.importKey("raw", fromBase64(answer.key), "AES-GCM", false, ["decrypt"]);
    });
  }

  function openFile(file, key, entry) {
    var pieces = [];
    var chain = Promise.resolve();
    entry.parts.forEach(function (part) {
      chain = chain.then(function () { return slice(file, part[0], part[0] + part[1]); }).then(function (sealed) {
        return crypto.subtle.decrypt({ name: "AES-GCM", iv: fromBase64(part[2]) }, key, sealed);
      }).then(function (piece) { pieces.push(new Uint8Array(piece)); });
    });
    return chain.then(function () {
      var total = pieces.reduce(function (sum, piece) { return sum + piece.length; }, 0);
      var whole = new Uint8Array(total), at = 0;
      pieces.forEach(function (piece) { whole.set(piece, at); at += piece.length; });
      return whole.buffer;
    });
  }

  // Where the app keeps a file: the full address, or this site's own.
  function keyOf(entry) { return entry.k.charAt(0) === "/" ? location.origin + entry.k : entry.k; }

  function roomFor(bytes) {
    if (!navigator.storage || !navigator.storage.estimate) return Promise.resolve(true);
    return navigator.storage.estimate().then(function (space) {
      return !space.quota || space.quota - space.usage > bytes + 200 * 1048576;
    });
  }

  function load(file) {
    var index, key, todo, done = 0;
    input.disabled = true;
    say("Reading the pack…");
    return readIndex(file).then(function (found) {
      index = found;
      say("Unlocking " + index.level + "'s pack…");
      return unlock(index);
    }).then(function (opened) {
      key = opened;
      return ask({ type: "offline-has" });
    }).then(function (have) {
      var here = {};
      (have || []).forEach(function (address) { here[address] = true; });
      todo = index.files.filter(function (entry) { return !here[keyOf(entry)]; });
      var needed = todo.reduce(function (sum, entry) { return sum + entry.size; }, 0);
      return roomFor(needed).then(function (room) {
        if (!room) throw new Error("This device needs about " + megabytes(needed) + " free for this pack. Free some space, then try again.");
      });
    }).then(function () {
      bar.hidden = false;
      var chain = Promise.resolve();
      todo.forEach(function (entry) {
        chain = chain.then(function () { return openFile(file, key, entry); }).then(function (bytes) {
          return ask({ type: "offline-import", key: keyOf(entry), contentType: entry.t, bytes: bytes }, [bytes]);
        }).then(function (answer) {
          if (!answer || !answer.ok) throw new Error((answer && answer.error) || "A file couldn't be saved. Is the device full?");
          done += 1;
          bar.value = Math.floor(done * 100 / todo.length);
          say("Loading " + index.level + "'s lessons… " + done + " of " + todo.length);
        });
      });
      return chain;
    }).then(function () {
      // Kept even before a sync reaches the lessons that use them.
      return ask({ type: "offline-pack-keys", keys: index.files.map(keyOf) });
    }).then(function () {
      bar.hidden = true;
      say("Done: " + index.level + "'s pictures and recordings are on this device" +
          (todo.length < index.files.length ? " (" + (index.files.length - todo.length) + " were here already)" : "") +
          ". Getting the lesson pages now…");
      if (window.DMOffline && navigator.onLine) {
        return window.DMOffline.download({ media: true }).then(function (state) {
          say(state.stopped ? "The pictures and recordings are loaded. Tap Download lessons when you're online to get the lesson pages."
                            : "Done: " + index.level + "'s lessons are ready offline.");
        });
      }
    }).catch(function (error) {
      bar.hidden = true;
      say(error.message || "The pack couldn't be loaded.");
    }).then(function () {
      input.disabled = false;
      input.value = "";
    });
  }

  input.addEventListener("change", function () {
    if (input.files && input.files[0]) load(input.files[0]);
  });
})();
