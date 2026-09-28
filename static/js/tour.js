/* The welcome tour (templates/landing/tour.html): swipe, arrow keys, dots
   or Next move between the three screens; on the last one Next becomes
   "Get Started" and goes on to sign-up. Without this script the page is
   still usable: Next and Skip are ordinary links to sign-up. */

(function () {
  "use strict";

  var tour = document.querySelector("[data-tour]");
  if (!tour) return;
  var track = tour.querySelector("[data-track]");
  var slides = [].slice.call(tour.querySelectorAll("[data-slide]"));
  var dots = [].slice.call(tour.querySelectorAll("[data-dot]"));
  var next = tour.querySelector("[data-next]");
  var label = tour.querySelector("[data-next-label]");
  var at = 0;

  function go(index) {
    at = Math.max(0, Math.min(slides.length - 1, index));
    track.style.transform = "translateX(" + (-100 * at) + "%)";
    slides.forEach(function (s, i) {
      var on = i === at;
      s.classList.toggle("is-active", on);
      s.setAttribute("aria-hidden", String(!on));
      if ("inert" in s) s.inert = !on;
    });
    dots.forEach(function (d, i) {
      d.classList.toggle("is-on", i === at);
      d.setAttribute("aria-selected", String(i === at));
    });
    var last = at === slides.length - 1;
    label.textContent = last ? next.getAttribute("data-last-label") : "Next";
    next.classList.toggle("is-last", last);
  }

  next.addEventListener("click", function (e) {
    if (at < slides.length - 1) { e.preventDefault(); go(at + 1); }
  });
  var skip = tour.querySelector("[data-skip]");
  if (skip) skip.addEventListener("click", function (e) { e.preventDefault(); go(slides.length - 1); });
  dots.forEach(function (d) { d.addEventListener("click", function () { go(Number(d.getAttribute("data-dot"))); }); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight") go(at + 1);
    else if (e.key === "ArrowLeft") go(at - 1);
  });

  // Swipe: follow the finger, then settle on the nearest screen.
  var viewport = tour.querySelector("[data-viewport]");
  var startX = null, startY = null, dx = 0, dragging = false;
  viewport.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    startX = e.clientX; startY = e.clientY; dx = 0; dragging = false;
  });
  viewport.addEventListener("pointermove", function (e) {
    if (startX === null) return;
    dx = e.clientX - startX;
    if (!dragging && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(e.clientY - startY)) {
      dragging = true;
      track.classList.add("is-dragging");
      try { viewport.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
    }
    if (dragging) {
      var edge = (at === 0 && dx > 0) || (at === slides.length - 1 && dx < 0) ? 0.3 : 1;
      track.style.transform = "translateX(calc(" + (-100 * at) + "% + " + dx * edge + "px))";
    }
  });
  function end() {
    if (startX === null) return;
    track.classList.remove("is-dragging");
    if (dragging && Math.abs(dx) > viewport.clientWidth * 0.18) go(at + (dx < 0 ? 1 : -1));
    else go(at);
    startX = null; dragging = false;
  }
  viewport.addEventListener("pointerup", end);
  viewport.addEventListener("pointercancel", end);

  // Floating cards: show as many as fit whole in the picture, never a cut-off one.
  function fitCards() {
    tour.querySelectorAll(".tour__cards").forEach(function (list) {
      var cards = [].slice.call(list.children);
      cards.forEach(function (c) { c.classList.remove("is-cut"); });
      var room = list.clientHeight;
      if (!room) return;
      var used = 0, gap = parseFloat(getComputedStyle(list).rowGap) || 0;
      cards.forEach(function (c, i) {
        used += c.offsetHeight + (i ? gap : 0);
        if (used > room) c.classList.add("is-cut");
      });
    });
  }
  var fitTimer;
  window.addEventListener("resize", function () { clearTimeout(fitTimer); fitTimer = setTimeout(fitCards, 120); });

  go(0);
  fitCards();
})();
