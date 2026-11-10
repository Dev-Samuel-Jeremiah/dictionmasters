/* Meta Pixel, only with consent (apps/landing/meta_pixel.py says where).

   Nothing loads from Meta until the visitor taps Accept on the banner; the
   choice is remembered in this browser ("dm-ads-consent": "yes" or "no")
   and can be changed on the privacy page ([data-ads-choice]). */
(function () {
  "use strict";

  var KEY = "dm-ads-consent";
  function choice() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function remember(value) {
    try {
      if (value === null) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, value);
    } catch (e) { /* private mode: asked again next time */ }
  }

  // The privacy page: change the choice made earlier.
  document.querySelectorAll("[data-ads-choice]").forEach(function (button) {
    var note = document.querySelector("[data-ads-choice-note]");
    function show() {
      if (note) note.textContent = choice() === "yes" ? "You have accepted it in this browser." :
        choice() === "no" ? "You have turned it down in this browser." : "You haven't chosen yet in this browser.";
    }
    show();
    button.addEventListener("click", function () {
      remember(button.getAttribute("data-ads-choice") === "yes" ? "yes" : "no");
      show();
    });
  });

  var holder = document.getElementById("dm-meta-pixel");
  if (!holder) return;
  var pixel = holder.getAttribute("data-pixel");
  var event = holder.getAttribute("data-event");
  if (!pixel) return;

  function load() {
    if (window.fbq) return;
    /* Meta's own loader, as Events Manager gives it. */
    !function (f, b, e, v, n, t, s) {
      if (f.fbq) return; n = f.fbq = function () { n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments); };
      if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = "2.0"; n.queue = [];
      t = b.createElement(e); t.async = !0; t.src = v; s = b.getElementsByTagName(e)[0]; s.parentNode.insertBefore(t, s);
    }(window, document, "script", "https://connect.facebook.net/en_US/fbevents.js");
    if (event) {
      // A signed-in page, after an adult signs up: this one event and nothing
      // gathered from the page.
      window.fbq("set", "autoConfig", false, pixel);
      window.fbq("init", pixel);
      window.fbq("track", event);
    } else {
      window.fbq("init", pixel);
      window.fbq("track", "PageView");
    }
  }

  if (choice() === "yes") { load(); return; }
  if (choice() === "no" || event) return;
  var banner = document.querySelector("[data-consent]");
  if (!banner) return;
  banner.hidden = false;
  banner.querySelector("[data-consent-yes]").addEventListener("click", function () {
    remember("yes");
    banner.hidden = true;
    load();
  });
  banner.querySelector("[data-consent-no]").addEventListener("click", function () {
    remember("no");
    banner.hidden = true;
  });
})();
