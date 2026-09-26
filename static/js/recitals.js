/* Assembly Recitals: text size for the words, and Present mode — the words
   on the hall screen, a verse (or a line) at a time, full screen. */

(function () {
  "use strict";

  var page = document.querySelector("[data-recital]");
  if (!page) return;

  // Text size, remembered for next time.
  var verses = page.querySelector("[data-verses]");
  var SIZES = [1, 1.2, 1.45, 1.75, 2.1];
  var size = 1;
  try { size = Math.min(SIZES.length - 1, Math.max(0, Number(localStorage.getItem("dm-recital-size") || 1))); } catch (e) { /* fine */ }
  function applySize() { if (verses) verses.style.setProperty("--rc-scale", SIZES[size]); }
  applySize();
  page.querySelectorAll("[data-size]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      size = Math.min(SIZES.length - 1, Math.max(0, size + Number(btn.getAttribute("data-size"))));
      applySize();
      try { localStorage.setItem("dm-recital-size", String(size)); } catch (e) { /* fine */ }
    });
  });

  // Present mode.
  var overlay = page.querySelector("[data-present]");
  var data = document.getElementById("recital-verses");
  if (!overlay || !data) return;
  var allVerses = JSON.parse(data.textContent);
  var stage = overlay.querySelector("[data-stage]");
  var count = overlay.querySelector("[data-count]");
  var modeBtn = overlay.querySelector("[data-mode]");
  var playBtn = overlay.querySelector("[data-play]");
  var audio = page.querySelector("[data-recital-audio]");
  var opener = page.querySelector("[data-present-open]");
  var byLine = false, at = 0;

  function slides() {
    return byLine ? allVerses.reduce(function (acc, v) { return acc.concat(v.map(function (l) { return [l]; })); }, []) : allVerses;
  }

  function render() {
    var list = slides();
    at = Math.max(0, Math.min(at, list.length - 1));
    stage.textContent = "";
    var card = document.createElement("div");
    card.className = "rc-present__slide" + (byLine ? " is-line" : "");
    list[at].forEach(function (line) {
      var p = document.createElement("p");
      p.className = "rc-present__line";
      p.textContent = line;
      card.appendChild(p);
    });
    stage.appendChild(card);
    count.textContent = (at + 1) + " of " + list.length;
    overlay.querySelector("[data-prev]").disabled = at === 0;
    overlay.querySelector("[data-next]").disabled = at === list.length - 1;
  }

  function open() {
    at = 0;
    overlay.hidden = false;
    document.documentElement.classList.add("rc-presenting");
    render();
    if (overlay.requestFullscreen) overlay.requestFullscreen().catch(function () { /* the overlay still fills the window */ });
    overlay.querySelector("[data-next]").focus();
  }

  function close() {
    overlay.hidden = true;
    document.documentElement.classList.remove("rc-presenting");
    if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
    if (opener) opener.focus();
  }

  function step(d) { at += d; render(); }

  opener.addEventListener("click", open);
  overlay.querySelector("[data-present-close]").addEventListener("click", close);
  overlay.querySelector("[data-prev]").addEventListener("click", function () { step(-1); });
  overlay.querySelector("[data-next]").addEventListener("click", function () { step(1); });
  modeBtn.addEventListener("click", function () {
    // Keep the place: the first line of the current verse, or that line's verse.
    var list = slides(), line = list[at] ? list[at][0] : null;
    byLine = !byLine;
    modeBtn.setAttribute("aria-pressed", String(byLine));
    modeBtn.textContent = byLine ? "Whole verses" : "One line at a time";
    var next = slides();
    var found = next.findIndex(function (s) { return s.indexOf(line) > -1; });
    at = found > -1 ? found : 0;
    render();
    overlay.querySelector("[data-next]").focus();
  });
  if (playBtn && audio) {
    playBtn.addEventListener("click", function () {
      if (audio.paused) audio.play(); else audio.pause();
    });
    audio.addEventListener("play", function () { playBtn.textContent = "❚❚ Pause recording"; });
    audio.addEventListener("pause", function () { playBtn.textContent = "▶ Play recording"; });
  }
  document.addEventListener("keydown", function (e) {
    if (overlay.hidden) return;
    if (e.key === "Escape") { close(); }
    else if (e.key === "ArrowRight" || e.key === "PageDown" || (e.key === " " && !e.target.closest("button, input, audio"))) { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); step(-1); }
  });
  document.addEventListener("fullscreenchange", function () {
    if (!document.fullscreenElement && !overlay.hidden) close();
  });
})();
