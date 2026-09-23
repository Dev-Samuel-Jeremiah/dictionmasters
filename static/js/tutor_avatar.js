/*
 * The tutor's face, moving while it speaks (templates/tutor/_avatar.html).
 *
 * Any audio the tutor plays announces itself, and every avatar on the
 * page opens its mouth for as long as that audio lasts. The browser's
 * own voice (used when there is no recording) announces itself the same
 * way, so the face moves then too.
 */
(function () {
  "use strict";

  function faces() { return document.querySelectorAll("[data-avatar]"); }

  function speaking(on) {
    Array.prototype.forEach.call(faces(), function (face) {
      face.classList.toggle("is-speaking", !!on);
    });
  }

  var playing = 0;
  function started() { playing += 1; speaking(true); }
  function stopped() { playing = Math.max(0, playing - 1); if (!playing) speaking(false); }

  // The tutor tells the page whenever it plays something.
  document.addEventListener("dm-tutor-audio", function (event) {
    var audio = event.detail && event.detail.audio;
    if (!audio) return;
    if (audio.dataset && audio.dataset.avatarWired) return;
    if (audio.dataset) audio.dataset.avatarWired = "1";
    audio.addEventListener("playing", started);
    audio.addEventListener("ended", stopped);
    audio.addEventListener("pause", stopped);
    audio.addEventListener("error", stopped);
  });
  document.addEventListener("dm-tutor-speaking", function (event) {
    if (event.detail && event.detail.on) started(); else stopped();
  });

  // Choosing a face marks it at once, before the form is saved.
  document.addEventListener("DOMContentLoaded", function () {
    var picker = document.querySelector("[data-voice-picker]");
    if (!picker) return;
    picker.addEventListener("change", function (event) {
      if (event.target.name !== "voice") return;
      Array.prototype.forEach.call(picker.querySelectorAll("[data-voice-card]"), function (card) {
        card.classList.toggle("is-chosen", card.contains(event.target));
      });
    });
  });

  // A sample being played from the voice picker.
  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-voice-sample]"), function (button) {
      var audio = null;
      button.addEventListener("click", function () {
        var card = button.closest("[data-voice-card]");
        var face = card && card.querySelector("[data-avatar]");
        if (audio && !audio.paused) {
          audio.pause();
          return;
        }
        audio = new Audio(button.dataset.voiceSample);
        button.classList.add("is-playing");
        button.textContent = "Speaking…";
        button.setAttribute("aria-pressed", "true");
        function stop() {
          button.classList.remove("is-playing");
          button.textContent = "▶ Hear me";
          button.setAttribute("aria-pressed", "false");
          if (face) face.classList.remove("is-speaking");
        }
        audio.addEventListener("playing", function () {
          button.textContent = "Speaking…";
          if (face) face.classList.add("is-speaking");
        });
        audio.addEventListener("ended", stop);
        audio.addEventListener("pause", stop);
        audio.addEventListener("error", function () {
          stop();
          button.textContent = "No sample just now";
        });
        audio.play().catch(stop);
      });
    });
  });
})();