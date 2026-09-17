/* Landing page motion.

   Three things happen here: the hero card cycles through words and
   writes each transcription symbol by symbol, sections reveal as they
   scroll into view, and the figures count up the first time you see
   them.

   All of it is an enhancement — the page is complete and readable
   before this file runs, and anyone who asks their system for reduced
   motion gets the finished state immediately instead. */

(function () {
  "use strict";

  var stillness = window.matchMedia("(prefers-reduced-motion: reduce)");

  // ---- the hero card ---------------------------------------------------

  function splitTranscription(element) {
    /* Wrap each symbol so it can be written on in turn. Array.from
       keeps multi-byte symbols like ː and ʃ whole. */
    var text = element.textContent;
    element.textContent = "";
    Array.from(text).forEach(function (character, index) {
      var glyph = document.createElement("span");
      glyph.className = "ipa-glyph";
      glyph.style.setProperty("--g", index);
      // A space would collapse inside an inline-block.
      glyph.textContent = character === " " ? " " : character;
      element.appendChild(glyph);
    });
  }

  function startWordCycle(card) {
    var slides = card.querySelectorAll("[data-word-slide]");
    var notes = card.querySelectorAll("[data-note-slide]");
    if (slides.length < 2) return;

    slides.forEach(function (slide) {
      splitTranscription(slide.querySelector("[data-ipa-target]"));
    });

    var current = 0;

    function show(next) {
      [slides, notes].forEach(function (group) {
        if (!group[current] || !group[next]) return;
        group[current].classList.remove("word-slide--on");
        group[current].setAttribute("aria-hidden", "true");
        group[next].classList.add("word-slide--on");
        group[next].removeAttribute("aria-hidden");
      });

      // Re-run the write-on by replacing the glyphs with fresh nodes.
      var target = slides[next].querySelector("[data-ipa-target]");
      target.replaceChildren.apply(
        target,
        Array.prototype.map.call(target.children, function (glyph) {
          return glyph.cloneNode(true);
        })
      );

      current = next;
    }

    var timer = setInterval(function () {
      // Nothing to look at while the tab is hidden — don't animate.
      if (document.hidden) return;
      show((current + 1) % slides.length);
    }, 4200);

    window.addEventListener("pagehide", function () { clearInterval(timer); });
  }

  // ---- reveal on scroll ------------------------------------------------

  function watchReveals() {
    var targets = document.querySelectorAll(".reveal");
    if (!targets.length) return;

    if (!("IntersectionObserver" in window)) {
      targets.forEach(function (el) { el.classList.add("reveal--in"); });
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("reveal--in");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.1 });

    targets.forEach(function (el) { observer.observe(el); });
  }

  // ---- counting figures ------------------------------------------------

  function countUp(element) {
    var target = parseInt(element.dataset.countTo, 10);
    if (isNaN(target)) return;

    var duration = 1100;
    var started = null;

    function frame(now) {
      if (started === null) started = now;
      var progress = Math.min((now - started) / duration, 1);
      // Ease out, so it slows as it lands on the real number.
      var eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = Math.round(target * eased);
      if (progress < 1) requestAnimationFrame(frame);
    }

    element.textContent = "0";
    requestAnimationFrame(frame);
  }

  function watchCounters() {
    var figures = document.querySelectorAll("[data-count-to]");
    if (!figures.length || !("IntersectionObserver" in window)) return;

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        countUp(entry.target);
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.6 });

    figures.forEach(function (figure) { observer.observe(figure); });
  }

  // ---- start -----------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    if (stillness.matches) {
      // Show the finished state, animate nothing.
      document.querySelectorAll(".reveal").forEach(function (el) {
        el.classList.add("reveal--in");
      });
      return;
    }

    var card = document.querySelector("[data-word-cycle]");
    if (card) startWordCycle(card);
    watchReveals();
    watchCounters();
  });
})();
