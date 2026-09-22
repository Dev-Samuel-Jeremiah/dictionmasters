/*
 * Diction Masters as an installed app (apps/landing/pwa.py).
 *
 * 1. Registers the service worker, and checks for a new version whenever
 *    the app is opened or comes back to the front.
 * 2. When a release is waiting, shows a small bar: "A new version is
 *    ready — Update". Updating reloads the page onto it. (Pages always
 *    come fresh from the server anyway; this brings the rest along.)
 * 3. Any [data-install-app] button installs the app: the browser's own
 *    prompt where there is one, otherwise the steps for that device.
 */
(function () {
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

  // ---------------------------------------------------------------- updates
  if ("serviceWorker" in navigator) {
    // Only a version the person asked for reloads the page. The worker
    // taking charge for the first time must not interrupt them.
    var updating = false;
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (!updating) return;
      updating = false;
      window.location.reload();
    });

    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function (registration) {
        function offer(worker) {
          if (worker && navigator.serviceWorker.controller) showUpdateBar(worker);
        }
        offer(registration.waiting);
        registration.addEventListener("updatefound", function () {
          var worker = registration.installing;
          if (!worker) return;
          worker.addEventListener("statechange", function () {
            if (worker.state === "installed") offer(worker);
          });
        });
        // Look for a new release whenever the app comes back to the front.
        document.addEventListener("visibilitychange", function () {
          if (document.visibilityState === "visible") registration.update().catch(function () {});
        });
        setInterval(function () { registration.update().catch(function () {}); }, 30 * 60 * 1000);
      }).catch(function () {});
    });
  }

  function showUpdateBar(worker) {
    if (document.getElementById("app-update")) return;
    var bar = document.createElement("div");
    bar.id = "app-update";
    bar.className = "app-update";
    bar.setAttribute("role", "status");
    bar.innerHTML = '<span class="app-update__text">&#10024; A new version of Diction Masters is ready.</span>' +
      '<button type="button" class="app-update__go">Update</button>' +
      '<button type="button" class="app-update__later" aria-label="Later">&times;</button>';
    document.body.appendChild(bar);
    bar.querySelector(".app-update__go").addEventListener("click", function () {
      this.disabled = true;
      this.textContent = "Updating…";
      updating = true;
      worker.postMessage("update-now");
    });
    bar.querySelector(".app-update__later").addEventListener("click", function () { bar.remove(); });
  }

  // ---------------------------------------------------------------- install
  var deferred = null;
  var buttons = [];

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
  });
  window.addEventListener("appinstalled", function () {
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
    dialog.querySelectorAll("[data-for]").forEach(function (part) {
      part.hidden = part.getAttribute("data-for") !== which;
    });
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
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
      button.hidden = standalone;
      button.addEventListener("click", function () {
        if (deferred) {
          deferred.prompt();
          deferred.userChoice.finally(function () { deferred = null; });
        } else {
          showSteps();
        }
      });
    });
    var dialog = document.getElementById("install-steps");
    if (dialog) {
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
      });
    }
  });
})();
