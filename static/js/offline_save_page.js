/*
 * "Save this page for offline" (templates/offline/_save_page.html): keeps the
 * page and every picture and recording on it, for using with no internet.
 * And on My downloads (templates/videos/offline.html), the list of pages
 * saved that way, with the room this device's downloads take.
 *
 * The app's service worker does the saving (templates/pwa/sw.js, "saved
 * pages"), a short step at a time, as it does for a whole level's download:
 * the copy is sealed in the learner's own store and closes when their plan
 * ends. Pages with many short sounds (word lists, the phonemic chart) carry
 * this one button rather than one beside every sound.
 *
 * With no service worker (an old browser, the computer app) the button
 * stays hidden: there would be nowhere to keep the page.
 */
(function () {
  "use strict";

  var box = document.querySelector("[data-offline-save-page]");
  var list = document.querySelector("[data-saved-pages]");
  if (!box && !list) return;
  if (!("serviceWorker" in navigator) || !window.MessageChannel) {
    if (list) list.innerHTML = '<li class="vid-kept__none">This browser can’t keep pages for offline use.</li>';
    return;
  }

  var STOPPED = {
    offline: "You're offline. Connect to the internet, then tap Save again.",
    "signed-out": "Please sign in again, then save this page.",
    "no-access": "Your plan doesn't include saving lessons just now.",
    switched: "Someone else signed in on this device. Sign back in to save this page.",
    "not-saveable": "This page can't be saved for offline.",
    error: "That didn't work. Please try again."
  };

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

  // ------------------------------------------------- the strip on a page

  function strip(box) {
    var button = box.querySelector("[data-save-page]");
    var remove = box.querySelector("[data-save-page-remove]");
    var state = box.querySelector("[data-save-page-state]");
    var progress = box.querySelector("[data-save-page-progress]");
    var figure = progress && progress.querySelector("b");
    var path = location.pathname + location.search;
    var title = box.getAttribute("data-title") || document.title;
    var IDLE = state.textContent;
    var busy = false;

    function say(text, tone) {
      state.textContent = text;
      box.classList.toggle("save-page--good", tone === "good");
      box.classList.toggle("save-page--bad", tone === "bad");
    }

    function showProgress(percent) {
      progress.hidden = percent === null;
      if (percent === null) return;
      progress.firstElementChild.style.width = Math.max(percent, 3) + "%";
      if (figure) figure.textContent = percent + "%";
    }

    function show(status) {
      var saved = !!(status && status.saved);
      var whole = saved && status.complete;
      button.hidden = false;
      button.disabled = whole;
      button.classList.toggle("vid__btn--saved", whole);
      button.lastChild.textContent = whole ? " ✓ Saved for offline" : (saved ? " Get the missing sounds" : " Save this page for offline");
      remove.hidden = !saved;
      showProgress(null);
      if (!saved) say(IDLE);
      else if (status.open === false) say("Saved, but closed: connect to the internet once so your account can be checked.", "bad");
      else if (whole) say("✓ Saved on this device. It opens even with no internet.", "good");
      else say("Saved, but some sounds or pictures didn't arrive. Tap the button to fetch them.", "bad");
    }

    function check() {
      return ask({ type: "offline-page-status", path: path }).then(show).catch(function () { box.hidden = true; });
    }

    function percentOf(step) {
      var total = 1 + (step.queued ? step.queued.length : 0);
      var done = Math.min(total, (step.pages || 0) + (step.media_kept || 0) + (step.failed || 0));
      return Math.min(99, Math.round(done * 100 / total));
    }

    function save() {
      if (busy) return;
      if (!navigator.onLine) { say(STOPPED.offline, "bad"); return; }
      busy = true;
      button.disabled = true;
      remove.hidden = true;
      say("Saving this page…");
      showProgress(0);
      (function step(current) {
        var message = current ? { type: "offline-save-page", state: current }
                              : { type: "offline-save-page", path: path, title: title };
        return ask(message).then(function (next) {
          if (!next.done) {
            showProgress(percentOf(next));
            var waiting = next.queued ? next.queued.length - (next.media_kept || 0) - (next.failed || 0) : 0;
            say(waiting > 0 ? "Saving the sounds and pictures… " + waiting + " to go" : "Saving this page…");
            return step(next);
          }
          busy = false;
          if (next.stopped) {
            showProgress(null);
            button.disabled = false;
            return check().then(function () { say(STOPPED[next.stopped] || STOPPED.error, "bad"); });
          }
          if (!next.saved) {
            showProgress(null);
            button.disabled = false;
            say(STOPPED["not-saveable"], "bad");
            return null;
          }
          return check();
        });
      })(null).catch(function () {
        busy = false;
        button.disabled = false;
        showProgress(null);
        say(STOPPED.error, "bad");
      });
    }

    button.addEventListener("click", save);
    remove.addEventListener("click", function () {
      if (busy) return;
      busy = true;
      say("Removing…");
      ask({ type: "offline-remove-page", path: path }).then(function () {
        busy = false;
        return check();
      }).catch(function () { busy = false; say(STOPPED.error, "bad"); });
    });

    // Only once the app's worker is running: it is what keeps the page.
    navigator.serviceWorker.ready.then(function () {
      box.hidden = false;
      return check();
    });
  }

  // ------------------------------------------- My downloads: saved pages

  // "Quick Words — Diction Masters" reads better as "Quick Words".
  function shortTitle(text) {
    return String(text || "").replace(/\s+[—–-]\s+Diction Masters\s*$/, "") || "A saved page";
  }

  function when(stamp) {
    try {
      return new Date(stamp).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    } catch (error) { return ""; }
  }

  function sizeOf(bytes) {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB";
    return Math.max(1, Math.round(bytes / 1048576)) + " MB";
  }

  // How much this device's downloads take, of the room the browser allows.
  function showSpace() {
    var note = document.querySelector("[data-space-used]");
    if (!note || !navigator.storage || !navigator.storage.estimate) return;
    navigator.storage.estimate().then(function (space) {
      if (!space.usage) return;
      note.textContent = "All downloads on this device: " + sizeOf(space.usage) +
        (space.quota ? " (room for about " + sizeOf(Math.max(space.quota - space.usage, 0)) + " more)" : "");
      note.hidden = false;
    }).catch(function () {});
  }

  function savedList(list) {
    function empty() {
      list.innerHTML = '<li class="vid-kept__none">No pages saved on this device yet. On a page of words or sounds, ' +
        'tap “Save this page for offline”.</li>';
    }

    function row(page) {
      var item = document.createElement("li");
      item.className = "vid-kept saved-page";
      item.innerHTML = '<div class="vid-kept__body"><p class="vid-kept__title"></p><p class="vid-kept__note"></p></div>' +
        '<div class="vid-kept__actions">' +
        '<a class="vid__btn vid__btn--watch" href="">Open</a>' +
        '<button type="button" class="vid__btn vid__btn--remove">Remove</button></div>';
      item.querySelector(".vid-kept__title").textContent = shortTitle(page.title);
      var note = item.querySelector(".vid-kept__note");
      note.textContent = "Saved " + when(page.at);
      item.querySelector("a").href = page.p;
      ask({ type: "offline-page-status", path: page.p }).then(function (status) {
        if (status.open === false) note.textContent += " · closed until you connect once";
        else if (!status.complete) note.textContent += " · some sounds missing: open it and tap Save again";
      }).catch(function () {});
      item.querySelector("button").addEventListener("click", function () {
        item.querySelector("button").disabled = true;
        ask({ type: "offline-remove-page", path: page.p }).then(function () {
          item.remove();
          if (!list.children.length) empty();
          showSpace();
        });
      });
      return item;
    }

    ask({ type: "offline-saved-pages" }).then(function (pages) {
      list.textContent = "";
      if (!pages || !pages.length) { empty(); return; }
      pages.forEach(function (page) { list.appendChild(row(page)); });
    }).catch(function () {
      list.innerHTML = '<li class="vid-kept__none">The list of saved pages couldn’t be read. Reload this page.</li>';
    });
    showSpace();
  }

  if (box) strip(box);
  if (list) savedList(list);
})();
