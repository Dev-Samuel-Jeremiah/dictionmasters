/* Scan the code in the book and land on that card.

   The button in the header opens the camera, watches for a QR code, and
   goes straight to the card it points at. Signed out, the site asks the
   reader to sign in and then opens the same card, so nobody has to hunt
   for the lesson afterwards.

   Reading the code: the browser's own detector where there is one (most
   Android phones), otherwise jsQR, which is only fetched if it's needed
   — that keeps a page load light for everyone else.

   The camera needs a secure page (https, or localhost while developing).
   Without one, and on a laptop with no camera, the panel says so and
   points at the phone's own camera app, which opens these codes too.  */

(function () {
  "use strict";

  var FALLBACK = "/static/js/vendor/jsqr.js";
  var LOOK_EVERY = 120;        // milliseconds between looks at the picture

  var sheet = null;
  var stream = null;
  var timer = null;
  var reader = null;
  var opener = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function ours(address) {
    /* Only our own codes lead anywhere: anything else is somebody's poster. */
    try {
      var url = new URL(address, window.location.href);
      if (url.origin === window.location.origin) return url.pathname + url.search + url.hash;
      var site = document.documentElement.dataset.siteUrl || "";
      if (site && url.origin === new URL(site).origin) return url.pathname + url.search + url.hash;
    } catch (error) { /* not an address at all */ }
    return "";
  }

  function build() {
    sheet = el("div", "qs");
    sheet.hidden = true;
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-label", "Scan a code");
    sheet.innerHTML =
      '<div class="qs__panel">' +
        '<div class="qs__head">' +
          '<p class="qs__title">Scan the code in your book</p>' +
          '<button type="button" class="qs__close" aria-label="Close the scanner">&times;</button>' +
        "</div>" +
        '<div class="qs__stage">' +
          '<video class="qs__video" playsinline muted></video>' +
          '<div class="qs__frame" aria-hidden="true"></div>' +
        "</div>" +
        '<p class="qs__says" role="status">Point the camera at the code beside the lesson.</p>' +
      "</div>";
    document.body.appendChild(sheet);
    sheet.querySelector(".qs__close").addEventListener("click", close);
    sheet.addEventListener("click", function (event) { if (event.target === sheet) close(); });
    return sheet;
  }

  function says(message) {
    sheet.querySelector(".qs__says").textContent = message;
  }

  function loadFallback() {
    if (window.jsQR) return Promise.resolve(window.jsQR);
    return new Promise(function (done, fail) {
      var tag = document.createElement("script");
      tag.src = FALLBACK;
      tag.onload = function () { done(window.jsQR); };
      tag.onerror = fail;
      document.head.appendChild(tag);
    });
  }

  function readerFor() {
    /* The browser's own reader, or jsQR: both answer with the text of the
       first code they can see. */
    if ("BarcodeDetector" in window) {
      try {
        var detector = new window.BarcodeDetector({ formats: ["qr_code"] });
        return Promise.resolve(function (video) {
          return detector.detect(video).then(function (found) {
            return found.length ? found[0].rawValue : "";
          });
        });
      } catch (error) { /* fall through to jsQR */ }
    }
    var canvas = document.createElement("canvas");
    var paper = canvas.getContext("2d", { willReadFrequently: true });
    return loadFallback().then(function (jsQR) {
      return function (video) {
        var width = video.videoWidth;
        var height = video.videoHeight;
        if (!width || !height) return Promise.resolve("");
        canvas.width = width;
        canvas.height = height;
        paper.drawImage(video, 0, 0, width, height);
        var found = jsQR(paper.getImageData(0, 0, width, height).data, width, height, { inversionAttempts: "dontInvert" });
        return Promise.resolve(found ? found.data : "");
      };
    });
  }

  function watch(video) {
    timer = window.setInterval(function () {
      if (!reader || video.readyState < 2) return;
      reader(video).then(function (text) {
        if (!text) return;
        var here = ours(text);
        if (!here) {
          says("That isn't a Diction Masters code. Try the one printed beside the lesson.");
          return;
        }
        window.clearInterval(timer);
        timer = null;
        says("Found it — opening the lesson…");
        sheet.classList.add("is-found");
        stop();
        window.location.assign(here);
      }).catch(function () { /* one bad frame doesn't matter */ });
    }, LOOK_EVERY);
  }

  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
    if (stream) {
      stream.getTracks().forEach(function (track) { track.stop(); });
      stream = null;
    }
  }

  function close() {
    stop();
    if (sheet) sheet.hidden = true;
    document.documentElement.classList.remove("qs-open");
    if (opener) opener.focus({ preventScroll: true });
  }

  function open(button) {
    opener = button;
    if (!sheet) build();
    sheet.hidden = false;
    sheet.classList.remove("is-found");
    document.documentElement.classList.add("qs-open");
    sheet.querySelector(".qs__close").focus({ preventScroll: true });
    says("Point the camera at the code beside the lesson.");

    var video = sheet.querySelector(".qs__video");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      says("This device can't open the camera here. Use your phone's camera app on the code — it opens the lesson too.");
      return;
    }

    navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
      .then(function (camera) {
        stream = camera;
        video.srcObject = camera;
        return video.play();
      })
      .then(function () { return readerFor(); })
      .then(function (found) {
        reader = found;
        watch(video);
      })
      .catch(function (error) {
        stop();
        var refused = error && (error.name === "NotAllowedError" || error.name === "SecurityError");
        says(refused
          ? "The camera is blocked for this site. Allow it in your browser settings, or use your phone's camera app on the code."
          : "No camera here. Use your phone's camera app on the code — it opens the lesson too.");
      });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-scan-open]");
    if (!button) return;
    event.preventDefault();
    if (sheet && !sheet.hidden) { close(); } else { open(button); }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && sheet && !sheet.hidden) close();
  });
})();
