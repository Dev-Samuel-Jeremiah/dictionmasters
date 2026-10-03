/* Photo slides for children (templates/learning_modules/_slides.html).

   Big arrows, swiping, the arrow keys and picture "dots" move between
   slides; Play turns the pages by itself; Full screen fills the screen.
   A slide with a recording plays it as it opens (after the child's first
   tap — browsers don't play sound before that), and the last page says
   well done. */
(function () {
  "use strict";

  var PLAY_SECONDS = 5;
  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setUp(box) {
    var stage = box.querySelector("[data-ps-stage]");
    var track = box.querySelector("[data-ps-track]");
    var slides = Array.prototype.slice.call(box.querySelectorAll("[data-ps-slide]"));
    var end = box.querySelector("[data-ps-end]");
    var dots = Array.prototype.slice.call(box.querySelectorAll("[data-ps-dot]"));
    var count = box.querySelector("[data-ps-count]");
    var prev = box.querySelector("[data-ps-prev]");
    var next = box.querySelector("[data-ps-next]");
    var play = box.querySelector("[data-ps-play]");
    var playLabel = box.querySelector("[data-ps-play-label]");
    var soundButton = box.querySelector("[data-ps-sound]");
    var full = box.querySelector("[data-ps-full]");
    if (!slides.length) return;

    box.classList.add("is-ready");
    end.hidden = false;
    var pages = slides.concat([end]);
    var at = 0, timer = null, touched = false, soundOn = true;
    var player = new Audio();
    var hasSound = slides.some(function (s) { return s.dataset.sound; });
    if (soundButton) soundButton.hidden = !hasSound;

    function show(n, fromUser) {
      at = Math.max(0, Math.min(n, pages.length - 1));
      if (fromUser) touched = true;
      track.style.transform = "translateX(" + (-100 * at) + "%)";
      pages.forEach(function (page, i) { page.setAttribute("aria-hidden", String(i !== at)); });
      var last = at === pages.length - 1;
      count.textContent = last ? "★" : (at + 1) + " / " + slides.length;
      prev.disabled = at === 0;
      next.disabled = last;
      dots.forEach(function (dot, i) {
        dot.setAttribute("aria-selected", String(i === at));
        dot.classList.toggle("is-on", i === at);
      });
      var dot = dots[at];
      if (dot && dot.parentNode.scrollWidth > dot.parentNode.clientWidth) {
        dot.parentNode.scrollTo({ left: dot.offsetLeft - dot.parentNode.clientWidth / 2 + dot.clientWidth / 2, behavior: calm ? "auto" : "smooth" });
      }
      // Load the next picture before it's needed.
      var ahead = slides[at + 1] && slides[at + 1].querySelector("img");
      if (ahead) ahead.loading = "eager";
      sound();
      if (last) stop();
    }

    function sound() {
      player.pause();
      var src = slides[at] && slides[at].dataset.sound;
      if (!src || !soundOn || !touched) return;
      player.src = src;
      player.currentTime = 0;
      player.play().catch(function () { /* waits for a tap */ });
    }

    function stop() {
      window.clearInterval(timer);
      timer = null;
      play.setAttribute("aria-pressed", "false");
      playLabel.textContent = "▶ Play";
    }
    function start() {
      touched = true;
      if (at >= slides.length) show(0);
      play.setAttribute("aria-pressed", "true");
      playLabel.textContent = "❚❚ Pause";
      sound();
      timer = window.setInterval(function () {
        // Wait for a slide's recording to finish before turning the page.
        if (!player.paused && !player.ended) return;
        show(at + 1);
      }, PLAY_SECONDS * 1000);
    }

    prev.addEventListener("click", function () { stop(); show(at - 1, true); });
    next.addEventListener("click", function () { stop(); show(at + 1, true); });
    dots.forEach(function (dot, i) { dot.addEventListener("click", function () { stop(); show(i, true); }); });
    play.addEventListener("click", function () { if (timer) stop(); else start(); });
    box.querySelector("[data-ps-again]").addEventListener("click", function () { show(0, true); });
    if (soundButton) soundButton.addEventListener("click", function () {
      soundOn = !soundOn;
      soundButton.setAttribute("aria-pressed", String(soundOn));
      soundButton.textContent = soundOn ? "🔊 Sound on" : "🔈 Sound off";
      if (!soundOn) player.pause(); else { touched = true; sound(); }
    });

    box.addEventListener("keydown", function (event) {
      if (event.key === "ArrowRight") { stop(); show(at + 1, true); event.preventDefault(); }
      else if (event.key === "ArrowLeft") { stop(); show(at - 1, true); event.preventDefault(); }
      else if (event.key === " " && event.target === box) { if (timer) stop(); else start(); event.preventDefault(); }
    });

    // Swipe, with the picture following the finger.
    var startX = null, startY = null, moved = 0, width = 1;
    stage.addEventListener("pointerdown", function (event) {
      if (event.pointerType === "mouse" || event.target.closest("button")) return;
      startX = event.clientX; startY = event.clientY; moved = 0; width = stage.clientWidth || 1;
      track.classList.add("is-dragging");
    });
    stage.addEventListener("pointermove", function (event) {
      if (startX === null) return;
      moved = event.clientX - startX;
      if (Math.abs(event.clientY - startY) > Math.abs(moved) && Math.abs(moved) < 10) return;
      track.style.transform = "translateX(calc(" + (-100 * at) + "% + " + moved + "px))";
    });
    function release() {
      if (startX === null) return;
      track.classList.remove("is-dragging");
      var go = Math.abs(moved) > width * 0.18 ? (moved < 0 ? 1 : -1) : 0;
      startX = null;
      if (go) stop();
      show(at + go, true);
    }
    stage.addEventListener("pointerup", release);
    stage.addEventListener("pointercancel", release);

    full.addEventListener("click", function () {
      var fs = document.fullscreenElement || document.webkitFullscreenElement;
      if (fs) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
      var ask = box.requestFullscreen || box.webkitRequestFullscreen;
      if (ask) ask.call(box); else box.classList.toggle("is-full");   // iPhone: fill the window instead
    });
    document.addEventListener("fullscreenchange", function () {
      full.textContent = document.fullscreenElement === box ? "✕ Exit full screen" : "⛶ Full screen";
    });

    show(0);
  }

  function init() { document.querySelectorAll("[data-ps]").forEach(setUp); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
