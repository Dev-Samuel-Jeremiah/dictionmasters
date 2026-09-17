/*
 * Dashboard cards tilt towards the pointer, with a glare that follows it.
 * Only an enhancement: without this file the cards still lift on hover.
 * Skipped for touch screens and for anyone who prefers reduced motion.
 */
(function () {
  "use strict";

  var fine = window.matchMedia("(hover: hover) and (pointer: fine)");
  var calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (!fine.matches || calm.matches) return;

  var MAX_TILT = 7; // degrees

  document.querySelectorAll("[data-tilt]").forEach(function (card) {
    var frame = 0;

    card.addEventListener("pointermove", function (event) {
      var box = card.getBoundingClientRect();
      var x = (event.clientX - box.left) / box.width;
      var y = (event.clientY - box.top) / box.height;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function () {
        card.classList.add("is-tilting");
        card.style.setProperty("--ry", ((x - 0.5) * 2 * MAX_TILT).toFixed(2) + "deg");
        card.style.setProperty("--rx", ((0.5 - y) * 2 * MAX_TILT).toFixed(2) + "deg");
        card.style.setProperty("--gx", (x * 100).toFixed(1) + "%");
        card.style.setProperty("--gy", (y * 100).toFixed(1) + "%");
      });
    });

    card.addEventListener("pointerleave", function () {
      cancelAnimationFrame(frame);
      card.classList.remove("is-tilting");
      card.style.setProperty("--rx", "0deg");
      card.style.setProperty("--ry", "0deg");
    });
  });
})();
