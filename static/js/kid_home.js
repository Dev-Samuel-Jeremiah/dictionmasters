/* The learner's home (templates/accounts/learner_home.html): course tiles
   that tilt towards the pointer, and the streak counting up. Nothing runs
   under reduced motion; the page works the same without it. */
(function () {
  var home = document.querySelector("[data-kid-home]");
  if (!home || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  // Tilt: only for a real pointer that hovers (mouse, pen), not a finger.
  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    home.querySelectorAll("[data-tilt]").forEach(function (tile) {
      tile.addEventListener("pointermove", function (event) {
        var box = tile.getBoundingClientRect();
        var x = (event.clientX - box.left) / box.width - 0.5;
        var y = (event.clientY - box.top) / box.height - 0.5;
        tile.style.transform = "rotateX(" + (-y * 12).toFixed(2) + "deg) rotateY(" + (x * 14).toFixed(2) + "deg) translateY(-4px)";
      });
      tile.addEventListener("pointerleave", function () { tile.style.transform = ""; });
    });
  }

  // The streak counts up from 0 the first time the home is shown.
  home.querySelectorAll("[data-count-up]").forEach(function (el) {
    var end = parseInt(el.getAttribute("data-count-up"), 10);
    if (!(end > 1)) return;
    var start = null, ms = Math.min(900, 250 + end * 60);
    function step(now) {
      if (start === null) start = now;
      var t = Math.min(1, (now - start) / ms);
      el.textContent = Math.round(end * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(step);
    }
    el.textContent = "0";
    requestAnimationFrame(step);
  });
})();
