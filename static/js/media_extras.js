/* Two helpers for every recording on the site (loaded by boot.js on pages
   that have an <audio> or <video>):

   1. Replay — each player with controls gets a "Replay" button that goes
      back to the start and plays. Cards that already have their own
      (EchoSpell's listening cards: .circle-replay) are left alone.

   2. Up next — when a lesson video is nearly over, a card slides in on the
      right of the video pointing at the page's own Next step (the Next
      button at the foot of a 44 Academy / Tricks section or an EchoSpell
      card: .tab-steps__btn--next, or anything marked [data-next-link]).
      It stays up once the video ends, so nobody has to scroll to find it.

   Players added later (a card that opens, Radio changing episode) are
   picked up too. */
(function () {
  "use strict";

  var NEAR_END = 10;          // seconds left when "Up next" appears...
  var NEAR_END_SHARE = 0.12;  // ...or this share of a short video, whichever is smaller

  function el(tag, cls, html) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html) node.innerHTML = html;
    return node;
  }

  function replay(media) {
    media.currentTime = 0;
    var playing = media.play();
    if (playing && playing.catch) playing.catch(function () { /* the browser may want a tap on the player */ });
  }

  var REPLAY_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 12a8 8 0 1 0 2.4-5.7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M4 4v5h5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // ---- the page's Next step, if it has one
  function nextStep() {
    var link = document.querySelector("[data-next-link]") || document.querySelector(".tab-steps__btn--next");
    if (!link || !link.getAttribute("href")) return null;
    var small = link.querySelector("small"), strong = link.querySelector("strong");
    return {
      href: link.getAttribute("href"),
      kicker: small ? small.textContent.trim() : "Up next",
      label: strong ? strong.textContent.trim() : link.textContent.trim()
    };
  }

  // ---- videos: a stage around the player carries Replay and Up next
  function stageFor(video) {
    if (video.parentElement && video.parentElement.classList.contains("mx-stage")) return video.parentElement;
    var stage = el("div", "mx-stage");
    video.parentNode.insertBefore(stage, video);
    stage.appendChild(video);
    return stage;
  }

  function setUpVideo(video) {
    var stage = stageFor(video);

    var again = el("button", "mx-replay mx-replay--video", REPLAY_ICON + "<span>Replay</span>");
    again.type = "button";
    again.setAttribute("aria-label", "Replay from the start");
    again.addEventListener("click", function () { replay(video); });
    stage.appendChild(again);
    function showReplay() { stage.classList.toggle("is-rewindable", video.currentTime > 1 && (video.paused || video.ended)); }
    ["pause", "ended", "play", "seeked"].forEach(function (type) { video.addEventListener(type, showReplay); });

    var next = nextStep();
    if (!next) return;
    var card = el("div", "mx-next");
    card.setAttribute("role", "region");
    card.setAttribute("aria-label", "Up next");
    card.hidden = true;
    var go = el("a", "mx-next__go");
    go.href = next.href;
    go.innerHTML = '<span class="mx-next__text"><small></small><strong></strong></span><span class="mx-next__arrow" aria-hidden="true">&rarr;</span>';
    go.querySelector("small").textContent = next.kicker || "Up next";
    go.querySelector("strong").textContent = next.label;
    var close = el("button", "mx-next__close", "&times;");
    close.type = "button";
    close.setAttribute("aria-label", "Hide");
    card.appendChild(go);
    card.appendChild(close);
    stage.appendChild(card);

    var dismissed = false;
    close.addEventListener("click", function () { dismissed = true; card.hidden = true; stage.classList.remove("has-next"); });
    function check() {
      var length = video.duration;
      if (!isFinite(length) || !length) return;
      var left = length - video.currentTime;
      var near = video.ended || left <= Math.min(NEAR_END, length * NEAR_END_SHARE + 2);
      if (!near) dismissed = false;               // they went back: offer it again next time
      var show = near && !dismissed;
      if (show === !card.hidden) return;
      card.hidden = !show;
      stage.classList.toggle("has-next", show);
    }
    ["timeupdate", "ended", "seeked", "loadedmetadata"].forEach(function (type) { video.addEventListener(type, check); });
  }

  // ---- audio: a small Replay pill just after the player
  function setUpAudio(audio) {
    var again = el("button", "mx-replay mx-replay--audio", REPLAY_ICON + "<span>Replay</span>");
    again.type = "button";
    again.setAttribute("aria-label", "Replay from the start");
    again.addEventListener("click", function () { replay(audio); });
    audio.insertAdjacentElement("afterend", again);
  }

  function setUp(media) {
    if (media.dataset.mxReady || !media.hasAttribute("controls")) return;
    if (media.closest("[data-no-replay]")) return;
    var card = media.closest(".word-card, .content-card");
    if (card && card.querySelector(".circle-replay")) return;   // it has its own Replay
    media.dataset.mxReady = "1";
    if (media.tagName === "VIDEO") setUpVideo(media); else setUpAudio(media);
  }

  function scan(root) {
    if (root.matches && root.matches("audio, video")) setUp(root);
    if (root.querySelectorAll) Array.prototype.forEach.call(root.querySelectorAll("audio, video"), setUp);
  }

  function start() {
    scan(document);
    if (window.MutationObserver) {
      new MutationObserver(function (changes) {
        changes.forEach(function (change) { Array.prototype.forEach.call(change.addedNodes, function (node) { if (node.nodeType === 1) scan(node); }); });
      }).observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
