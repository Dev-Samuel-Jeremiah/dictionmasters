/*
 * Phone features for the Android and iPhone apps.
 *
 * Loaded only inside the apps (templates/base.html checks `native_app`,
 * see apps/landing/native_app.py). The apps open this website in a native
 * window; Capacitor (the native part, in the separate mobile/ project) puts
 * `window.Capacitor` on every page, and this file uses it to:
 *
 *   1. hide the splash screen and colour the status bar
 *   2. make Android's back button go back a page (and close dialogs first)
 *   3. open other websites in an in-app browser, so the learner never
 *      gets stuck on a page with no way back
 *   4. save "download" links (e.g. EchoSpell QR codes) through the share sheet
 *   5. give Android the Web Share API (navigator.share) that iPhone has
 *   6. say when the phone goes offline / comes back, and send progress
 *      made offline as soon as it reconnects or the app is reopened
 *   7. open website links (from WhatsApp, email...) inside the app
 *   8. show a thin loading line while the next page loads
 *   9. "Update available": when a newer Android app is published, offer it
 *      (the user taps Update; Android installs it over the old one, and
 *      their account and downloaded lessons stay)
 *
 * Because this file lives on the website, changing it changes the apps
 * straight away. To test, open the app and (Android) chrome://inspect in
 * Chrome on your computer, or (iPhone) Safari > Develop.
 *
 * Other pages can use it too:  if (window.DMApp) DMApp.haptic();
 */
(function () {
  "use strict";

  var cap = window.Capacitor;
  if (!cap || !cap.isNativePlatform || !cap.isNativePlatform()) return;

  var P = cap.Plugins || {};
  var platform = cap.getPlatform(); // "android" or "ios"
  var root = document.documentElement;
  var siteHost = location.host;
  var appHosts = [siteHost, siteHost.replace(/^www\./, ""), "www." + siteHost.replace(/^www\./, "")];

  function call(plugin, method, options) {
    try {
      if (P[plugin] && typeof P[plugin][method] === "function") {
        return Promise.resolve(P[plugin][method](options)).catch(function () {});
      }
    } catch (error) { /* plugin missing in an older app build: ignore */ }
    return Promise.resolve();
  }

  // ------------------------------------------------------------ 1. chrome
  call("SplashScreen", "hide", { fadeOutDuration: 250 });
  call("StatusBar", "setStyle", { style: "DARK" }); // light text on the navy bar
  if (platform === "android") call("StatusBar", "setBackgroundColor", { color: "#0B1A4A" });

  // ---------------------------------------------------------- toast
  var toastTimer = null;
  function toast(message, kind) {
    var el = document.querySelector(".dm-app-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "dm-app-toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.className = "dm-app-toast" + (kind ? " dm-app-toast--" + kind : "");
    el.textContent = message;
    requestAnimationFrame(function () { el.classList.add("is-on"); });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("is-on"); }, 3500);
  }

  // ---------------------------------------------------- 2. back button
  function closeSomethingOpen() {
    // The "Update available" panel (section 9): back = Later. A required one stays.
    var update = document.querySelector(".dm-update");
    if (update) {
      var later = update.querySelector(".dm-update__later");
      if (later) later.click();
      return true;
    }
    // An open <dialog> (install steps, QR scanner, quick-look panel...)
    var dialogs = document.querySelectorAll("dialog[open]");
    if (dialogs.length) {
      var d = dialogs[dialogs.length - 1];
      if (typeof d.close === "function") d.close(); else d.removeAttribute("open");
      return true;
    }
    // The account menu (a <details>).
    var menu = document.querySelector("details[data-account-menu][open]");
    if (menu) { menu.open = false; return true; }
    // The side drawer (learners) or the control room's menu (staff): both close on Escape.
    if (document.body.classList.contains("px-drawer-open") || document.body.classList.contains("cr-side-open")) {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      return true;
    }
    return false;
  }

  var HOME_PATHS = ["/accounts/dashboard/", "/school/dashboard/", "/app/welcome/"];
  if (P.App) {
    P.App.addListener("backButton", function (event) {
      if (closeSomethingOpen()) return;
      if (HOME_PATHS.indexOf(location.pathname) !== -1 || !event.canGoBack) {
        call("App", "minimizeApp"); // like the home button: the app stays signed in
        return;
      }
      history.back();
    });
  }

  // ------------------------------------------------ 3. links & windows
  function isAppHost(host) { return appHosts.indexOf(host) !== -1; }

  function openOutside(url) {
    if (P.Browser) return call("Browser", "open", { url: url, presentationStyle: "popover", toolbarColor: "#0B1A4A" });
    window.location.href = url;
    return Promise.resolve();
  }

  var FILE_EXT = /\.(pdf|docx?|xlsx?|pptx?|zip|mp3|m4a|wav|mp4|mov|png|jpe?g|gif|webp|svg|csv|txt)(\?|#|$)/i;

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    var link = event.target.closest && event.target.closest("a[href]");
    if (!link) return;
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /^javascript:/i.test(href)) return;

    var url;
    try { url = new URL(href, location.href); } catch (error) { return; }

    // mailto:, tel:, whatsapp:, sms: — the app hands these to the phone itself.
    if (!/^https?:$/.test(url.protocol)) return;

    // 4. "download" links on our own site: save or share the file.
    if (link.hasAttribute("download") && isAppHost(url.host)) {
      event.preventDefault();
      saveFile(url.href, link.getAttribute("download") || url.pathname.split("/").pop());
      return;
    }

    // Another website, or a file (PDF, audio...) stored elsewhere: in-app browser.
    if (!isAppHost(url.host)) {
      event.preventDefault();
      openOutside(url.href);
      return;
    }

    // Our own site asking for a new tab: the app has no tabs, stay in place
    // (files still go to the viewer so the learner can come back).
    if (link.target === "_blank") {
      event.preventDefault();
      if (FILE_EXT.test(url.pathname)) openOutside(url.href);
      else window.location.href = url.href;
    }
  }, false);

  var nativeOpen = window.open;
  window.open = function (href, target, features) {
    try {
      var url = new URL(href, location.href);
      if (!isAppHost(url.host) || FILE_EXT.test(url.pathname)) { openOutside(url.href); return null; }
      window.location.href = url.href;
      return null;
    } catch (error) {
      return nativeOpen ? nativeOpen.call(window, href, target, features) : null;
    }
  };

  // -------------------------------------------------------- 4. files
  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result).split(",")[1]); };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function saveFile(href, name) {
    if (!P.Filesystem || !P.Share) { openOutside(href); return; }
    toast("Preparing " + name + "…");
    fetch(href, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.blob();
      })
      .then(blobToBase64)
      .then(function (data) {
        var safe = String(name || "download").replace(/[^\w.\-]+/g, "_");
        return P.Filesystem.writeFile({ path: safe, data: data, directory: "CACHE" });
      })
      .then(function (written) {
        return P.Share.share({ title: name, files: [written.uri], dialogTitle: "Save or share" });
      })
      .catch(function () { openOutside(href); });
  }

  // ---------------------------------------------------- 5. Web Share
  if (!navigator.share && P.Share) {
    navigator.share = function (data) {
      data = data || {};
      return P.Share.share({ title: data.title, text: data.text, url: data.url, dialogTitle: "Share" });
    };
  }

  // ------------------------------------------------- 6. online/offline
  if (P.Network) {
    var wasConnected = true;
    call("Network", "getStatus").then(function (s) { if (s) wasConnected = s.connected; });
    P.Network.addListener("networkStatusChange", function (status) {
      if (status.connected === wasConnected) return;
      wasConnected = status.connected;
      if (status.connected) {
        toast("Back online");
        sendProgress();
      } else {
        toast("You're offline. Downloaded lessons still work.", "offline");
      }
    });
  }

  // Send anything done offline as soon as possible: on reconnecting (above),
  // and whenever the app comes back to the front. See static/js/offline_sync.js.
  function sendProgress() {
    if (window.DMOffline) window.DMOffline.syncNow();
    else if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage("sync-learning");
    }
  }
  if (P.App) {
    P.App.addListener("resume", function () { if (navigator.onLine) sendProgress(); });
  }

  // ----------------------------------------------------- 7. deep links
  if (P.App) {
    P.App.addListener("appUrlOpen", function (event) {
      try {
        var url = new URL(event.url);
        if (isAppHost(url.host)) window.location.href = url.pathname + url.search + url.hash;
      } catch (error) { /* not a web address */ }
    });
  }

  // -------------------------------------------------- 8. loading line
  var bar = document.createElement("div");
  bar.className = "dm-app-loading";
  bar.setAttribute("aria-hidden", "true");
  document.addEventListener("DOMContentLoaded", function () { document.body.appendChild(bar); });
  window.addEventListener("beforeunload", function () { bar.classList.add("is-on"); });
  window.addEventListener("pageshow", function () { bar.classList.remove("is-on"); });

  // ----------------------------------------------- 9. update available
  //
  // /app/version.json (apps/landing/native_app.py) says which Android app is
  // the newest; App.getInfo() says which one this is. If this one is older,
  // a panel offers the update. "Later" hides it for a day; a build older than
  // NATIVE_APP_ANDROID_MIN_BUILD (server setting) can't be put off.
  var UPDATE_SNOOZE = "dm-update-later";
  var UPDATE_SEEN = "dm-update-latest";   // the last answer, so not every page asks the server
  var CHECK_EVERY = 3 * 60 * 60 * 1000;   // ask the server at most every 3 hours

  function remember(key, value) {
    try {
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value));
    } catch (error) { /* storage unavailable: just ask again next time */ }
  }
  function recall(key) {
    try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (error) { return null; }
  }

  function escapeText(text) {
    var div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function showUpdate(latest, installed, required) {
    if (document.querySelector(".dm-update")) return;
    var sheet = document.createElement("div");
    sheet.className = "dm-update" + (required ? " dm-update--required" : "");
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-labelledby", "dm-update-title");
    sheet.innerHTML =
      '<div class="dm-update__backdrop"></div>' +
      '<div class="dm-update__card">' +
        '<div class="dm-update__badge" aria-hidden="true">' +
          '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M12 3v12m0 0-4.5-4.5M12 15l4.5-4.5M5 20h14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
        '</div>' +
        '<h2 class="dm-update__title" id="dm-update-title">' + (required ? "Please update Diction Masters" : "Update available") + '</h2>' +
        '<p class="dm-update__lede">' +
          (latest.version ? "Version " + escapeText(latest.version) + " (build " + escapeText(latest.build) + ")" : "A new version") +
          " is ready." + (required ? " This update is needed to keep using the app." : "") +
        '</p>' +
        (latest.notes ? '<div class="dm-update__notes"><strong>What\'s new</strong><p>' + escapeText(latest.notes) + '</p></div>' : "") +
        '<p class="dm-update__safe">&#10003; Your account, progress and downloaded lessons stay. No need to uninstall.</p>' +
        '<div class="dm-update__steps" hidden>' +
          '<p><strong>Almost done:</strong></p>' +
          '<ol><li>Wait for the download to finish.</li>' +
          '<li>Tap <strong>diction-masters.apk</strong> in the notification (or your Downloads).</li>' +
          '<li>Tap <strong>Update</strong>.</li></ol>' +
        '</div>' +
        '<div class="dm-update__actions">' +
          '<button type="button" class="dm-update__go">Update now</button>' +
          (required ? "" : '<button type="button" class="dm-update__later">Later</button>') +
        '</div>' +
        '<p class="dm-update__version">You have build ' + escapeText(installed) + '.</p>' +
      '</div>';
    document.body.appendChild(sheet);
    document.documentElement.classList.add("dm-update-open");
    requestAnimationFrame(function () { sheet.classList.add("is-on"); });

    function close() {
      sheet.classList.remove("is-on");
      document.documentElement.classList.remove("dm-update-open");
      setTimeout(function () { sheet.remove(); }, 250);
    }
    var later = sheet.querySelector(".dm-update__later");
    if (later) {
      later.addEventListener("click", function () {
        remember(UPDATE_SNOOZE, { build: latest.build, until: Date.now() + 24 * 60 * 60 * 1000 });
        close();
      });
      sheet.querySelector(".dm-update__backdrop").addEventListener("click", later.click.bind(later));
    }
    sheet.querySelector(".dm-update__go").addEventListener("click", function () {
      var go = this;
      // Don't ask again on every page while it downloads and installs.
      if (!required) remember(UPDATE_SNOOZE, { build: latest.build, until: Date.now() + 60 * 60 * 1000 });
      // The browser downloads the new app file; Android then installs it over this one.
      openOutside(latest.url);
      sheet.querySelector(".dm-update__steps").hidden = false;
      go.textContent = "Download again";
      if (!required) {
        var laterButton = sheet.querySelector(".dm-update__later");
        if (laterButton) laterButton.textContent = "Close";
      }
    });
    call("Haptics", "impact", { style: "LIGHT" });
  }

  function newestKnown(force) {
    var seen = recall(UPDATE_SEEN);
    if (!force && seen && Date.now() - seen.at < CHECK_EVERY) return Promise.resolve(seen.data);
    if (!navigator.onLine) return Promise.resolve(seen ? seen.data : null);
    return fetch("/app/version.json", { credentials: "same-origin", cache: "no-store" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (data) remember(UPDATE_SEEN, { at: Date.now(), data: data });
        return data;
      });
  }

  function checkForUpdate(force) {
    if (platform !== "android" || !P.App) return;
    Promise.all([call("App", "getInfo"), newestKnown(force)]).then(function (results) {
      var info = results[0];
      var latest = results[1] && results[1].android;
      if (!info || !latest || !latest.url) return;
      var installed = parseInt(info.build, 10) || 0;
      var newest = parseInt(latest.build, 10) || 0;
      if (!installed || newest <= installed) return;
      var required = installed < (parseInt(latest.min_build, 10) || 0);
      var snoozed = recall(UPDATE_SNOOZE);
      if (!required && snoozed && snoozed.build === latest.build && Date.now() < snoozed.until) return;
      showUpdate(latest, installed, required);
    }).catch(function () { /* offline or server busy: check again later */ });
  }

  // A moment after each page opens, so the page itself appears first.
  setTimeout(function () { checkForUpdate(false); }, 2500);
  if (P.App) {
    P.App.addListener("resume", function () { setTimeout(function () { checkForUpdate(false); }, 1500); });
  }

  // ------------------------------------------------------- public API
  window.DMApp = {
    platform: platform,
    toast: toast,
    openOutside: openOutside,
    saveFile: saveFile,
    share: function (data) { return call("Share", "share", data); },
    haptic: function (style) { return call("Haptics", "impact", { style: style || "LIGHT" }); },
    checkForUpdate: function () { remember(UPDATE_SNOOZE, null); checkForUpdate(true); },
  };
})();
