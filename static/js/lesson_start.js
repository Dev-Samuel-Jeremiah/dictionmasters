/* Scanned from the book: start the lesson.

   A card's QR code carries "?play=1". Arriving with it — straight from the
   phone's camera, from the scanner in the header, or after signing in —
   the page finds the lesson's recording and plays it, so the child isn't
   left looking for the play button.

   Browsers decide for themselves whether sound may start without a tap;
   a phone that has just opened a link from its camera usually says no. When
   that happens a large "Start the lesson" button appears over the page, and
   one tap begins it. That is the most any website is allowed to do.

   The marker is removed from the address as soon as it has been read, so
   reloading the page or sharing its link doesn't start anything.  */

(function () {
  "use strict";

  var MARK = "play";

  function arrivedFromCode() {
    try {
      var url = new URL(window.location.href);
      if (url.searchParams.get(MARK) !== "1") return false;
      url.searchParams.delete(MARK);
      window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
      return true;
    } catch (error) {
      return false;
    }
  }

  function lessonPlayer() {
    // The recording the words follow first, then any other on the card.
    var main = document.querySelector("main") || document.body;
    return main.querySelector("[data-ra-media]") || main.querySelector("audio, video");
  }

  function offer(media) {
    var sheet = document.createElement("div");
    sheet.className = "ls";
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-label", "Start the lesson");
    sheet.innerHTML =
      '<button type="button" class="ls__start">' +
        '<span class="ls__icon" aria-hidden="true">' +
          '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/></svg>' +
        "</span>" +
        '<span class="ls__text"><strong>Start the lesson</strong><small>Tap to play</small></span>' +
      "</button>" +
      '<button type="button" class="ls__later">Not now</button>';
    document.body.appendChild(sheet);

    var start = sheet.querySelector(".ls__start");
    start.focus({ preventScroll: true });
    start.addEventListener("click", function () {
      sheet.remove();
      media.play().catch(function () { /* the player's own button still works */ });
    });
    sheet.querySelector(".ls__later").addEventListener("click", function () { sheet.remove(); });
  }

  function begin() {
    if (!arrivedFromCode()) return;
    var media = lessonPlayer();
    if (!media) return;

    media.scrollIntoView({ block: "center", behavior: "smooth" });
    var attempt = media.play();
    if (attempt && attempt.catch) {
      attempt.catch(function () { offer(media); });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", begin);
  } else {
    begin();
  }
})();
