/*
 * Loads the extra scripts a page actually needs, and no others.
 *
 * Most pages have no password box, no file upload and no QR button, so
 * fetching those scripts everywhere costs a phone several round trips
 * for nothing. This looks at the page first, then asks for what belongs
 * on it. Anything a page always needs is loaded by the page itself.
 */
(function () {
  "use strict";

  var listed = document.getElementById("page-scripts");
  if (!listed) return;
  var scripts = {};
  try { scripts = JSON.parse(listed.textContent); } catch (error) { return; }

  function load(files) {
    (files || []).forEach(function (src) {
      var script = document.createElement("script");
      script.src = src;
      script.defer = true;
      document.head.appendChild(script);
    });
  }

  function ifPresent(selector, name) {
    if (document.querySelector(selector)) load(scripts[name]);
  }

  ifPresent('input[type="password"]', "password");
  ifPresent('input[type="file"]', "upload");
  ifPresent("[data-scan-open]", "scan");
  ifPresent("audio, video", "media");
  ifPresent("[data-video][data-ticket], [data-offline-list]", "offline");
  // Arriving from a scanned code (?play=1): the page offers to start the lesson.
  if (document.querySelector("audio, video") && /[?&]play=1(&|$)/.test(location.search)) {
    load(scripts.lesson);
  }
})();
