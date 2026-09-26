/*
 * Diction Masters as an installed app (apps/landing/pwa.py).
 *
 * 1. Registers the service worker, and checks for a new version whenever
 *    the app is opened or comes back to the front.
 * 2. New releases activate automatically and reload the page onto the new
 *    version. The first service-worker installation does not interrupt it.
 * 3. Any [data-install-app] button installs the app: the browser's own
 *    prompt where there is one, otherwise the steps for that device.
 */
(function () {
  // Inside the Android/iPhone app (static/js/native_app.js) it is already installed.
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true ||
    document.documentElement.hasAttribute("data-native-app");

  // ---------------------------------------------------------------- updates
  if ("serviceWorker" in navigator) {
    var hadController = !!navigator.serviceWorker.controller;
    var reloadingForUpdate = false;
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (!hadController) {
        hadController = true;
        return;
      }
      if (reloadingForUpdate) return;
      reloadingForUpdate = true;
      window.location.reload();
    });

    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function (registration) {
        // Also activates an update already waiting under an older worker.
        if (registration.waiting) registration.waiting.postMessage("update-now");
        registration.addEventListener("updatefound", function () {
          var worker = registration.installing;
          if (!worker) return;
          worker.addEventListener("statechange", function () {
            if (worker.state === "installed" && registration.waiting) {
              registration.waiting.postMessage("update-now");
            }
          });
        });
        document.addEventListener("visibilitychange", function () {
          if (document.visibilityState === "visible") registration.update().catch(function () {});
        });
        setInterval(function () { registration.update().catch(function () {}); }, 30 * 60 * 1000);
      }).catch(function () {});
    });
  }

  // Sync the small, safe progress queue when a signed-in learner reconnects.
  function syncLearningProgress() {
    if (!navigator.onLine || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready.then(function (registration) {
      if (registration.sync) registration.sync.register("dm-learning-sync").catch(function () {});
      if (navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage("sync-learning");
    }).catch(function () {});
  }
  window.addEventListener("online", syncLearningProgress);
  window.addEventListener("load", function () { window.setTimeout(syncLearningProgress, 800); });
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", function (event) {
      var data = event.data || {};
      if (data.type !== "learning-sync" || (!data.synced && !data.pending)) return;
      var note = document.createElement("div");
      note.setAttribute("role", "status");
      note.style.cssText = "position:fixed;left:16px;right:16px;bottom:20px;z-index:10000;margin:auto;max-width:520px;padding:14px 18px;border-radius:14px;background:#14213d;color:#fffdf8;box-shadow:0 10px 30px rgba(0,0,0,.2);font:600 15px system-ui;text-align:center";
      note.textContent = data.synced
        ? data.synced + " offline progress item" + (data.synced === 1 ? "" : "s") + " synced."
        : data.pending + " progress item" + (data.pending === 1 ? " is" : "s are") + " waiting to sync. Stay signed in and reconnect.";
      document.body.appendChild(note);
      window.setTimeout(function () { note.remove(); }, 7000);
    });
  }

  // ---------------------------------------------------------------- install
  var deferred = null;
  var buttons = [];
  var installed = standalone;

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
  });
  window.addEventListener("appinstalled", function () {
    installed = true;
    deferred = null;
    buttons.forEach(function (button) { button.hidden = true; });
    var fab = document.querySelector("[data-install-fab]");
    if (fab) fab.hidden = true;
  });

  function device() {
    var ua = navigator.userAgent || "";
    if (/iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) return "ios";
    if (/android/i.test(ua)) return "android";
    return "desktop";
  }

  function showSteps() {
    var dialog = document.getElementById("install-steps");
    if (!dialog) return;
    var which = device();
    var secureNote = dialog.querySelector("[data-install-insecure]");
    var secureIntro = dialog.querySelector("[data-install-secure]");
    if (secureNote) secureNote.hidden = window.isSecureContext;
    if (secureIntro) secureIntro.hidden = !window.isSecureContext;
    dialog.querySelectorAll("[data-for]").forEach(function (part) {
      part.hidden = !window.isSecureContext || part.getAttribute("data-for") !== which;
    });
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function hideInstallButtons() {
    buttons.forEach(function (button) { button.hidden = true; });
    var fab = document.querySelector("[data-install-fab]");
    if (fab) fab.hidden = true;
  }

  // The real Android/iPhone app, when there is one to offer (the <html> tag
  // says so, from NATIVE_APP_* in config/settings.py): the install buttons
  // open the "Get the app" page instead of adding the website.
  function nativeAppOffered() {
    var root = document.documentElement;
    var which = device();
    return (which === "android" && root.hasAttribute("data-android-app")) ||
      (which === "ios" && root.hasAttribute("data-ios-app"));
  }

  function requestInstall() {
    if (installed) return;
    if (nativeAppOffered() && location.pathname !== "/app/get/") {
      location.href = "/app/get/";
      return;
    }
    if (!deferred) {
      showSteps();
      return;
    }

    // Call prompt synchronously in the click handler: browsers require the
    // user's activation to still be active when the native prompt is opened.
    var installEvent = deferred;
    deferred = null;
    var promptResult;
    try {
      promptResult = installEvent.prompt();
    } catch (error) {
      showSteps();
      return;
    }

    function recordChoice(choice) {
      if (choice && choice.outcome === "accepted") {
        installed = true;
        hideInstallButtons();
      }
    }

    // Some implementations return the choice from prompt(); Chromium also
    // exposes userChoice. Handle either form, and retain a useful fallback if
    // the browser rejects the native prompt.
    function handlePromptResult(result) {
      if (result && result.outcome) {
        recordChoice(result);
      } else if (installEvent.userChoice && typeof installEvent.userChoice.then === "function") {
        installEvent.userChoice.then(recordChoice).catch(showSteps);
      }
    }
    if (promptResult && typeof promptResult.then === "function") {
      promptResult.then(handlePromptResult).catch(showSteps);
    } else if (installEvent.userChoice && typeof installEvent.userChoice.then === "function") {
      installEvent.userChoice.then(recordChoice).catch(showSteps);
    }
  }

  var HIDDEN_FOR = 30 * 24 * 60 * 60 * 1000;      // "not now" lasts a month

  function putAway() {
    try { localStorage.setItem("dm-install-hidden", String(Date.now())); } catch (error) { /* fine */ }
  }

  function putAwayRecently() {
    try {
      var when = Number(localStorage.getItem("dm-install-hidden") || 0);
      return when && Date.now() - when < HIDDEN_FOR;
    } catch (error) { return false; }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var fab = document.querySelector("[data-install-fab]");
    if (fab) {
      fab.hidden = standalone || putAwayRecently();
      var close = fab.querySelector("[data-install-hide]");
      if (close) close.addEventListener("click", function () { fab.hidden = true; putAway(); });
    }
    buttons = Array.prototype.slice.call(document.querySelectorAll("[data-install-app]"));
    buttons.forEach(function (button) {
      // Already running as the app: nothing to install.
      button.hidden = installed;
      button.addEventListener("click", requestInstall);
    });
    if (installed) hideInstallButtons();
    var dialog = document.getElementById("install-steps");
    if (dialog) {
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
      });
    }
  });
})();
