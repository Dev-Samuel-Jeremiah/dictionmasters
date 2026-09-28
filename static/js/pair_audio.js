/* Minimal pairs: play one word, or "Hear both" one after the other. */
(function () {
  "use strict";

  function stopAll() {
    document.querySelectorAll("[data-pair-audio]").forEach(function (a) { a.pause(); a.currentTime = 0; });
    document.querySelectorAll(".pair-word.is-playing").forEach(function (w) { w.classList.remove("is-playing"); });
  }

  function play(word, then) {
    var audio = word.querySelector("[data-pair-audio]");
    if (!audio) { if (then) then(); return; }
    word.classList.add("is-playing");
    audio.onended = function () { word.classList.remove("is-playing"); if (then) setTimeout(then, 350); };
    audio.play().catch(function () { word.classList.remove("is-playing"); });
  }

  document.addEventListener("click", function (e) {
    var one = e.target.closest("[data-pair-play]");
    if (one) { stopAll(); play(one.closest(".pair-word")); return; }
    var both = e.target.closest("[data-pair-both]");
    if (both) {
      stopAll();
      var words = both.parentElement.querySelectorAll(".pair-word");
      play(words[0], function () { play(words[1]); });
    }
  });
})();
