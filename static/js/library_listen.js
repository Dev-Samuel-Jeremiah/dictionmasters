/* "Listen and read along" on a Diction Library book: one chapter at a time,
   its words highlighted as they're read (static/js/read_along.js), and the
   next chapter played on by itself when one ends. The ▶ Listen buttons (by
   "Open book", and in the reader's bar) start it — from where this device
   stopped last time, remembered per book.

   A book can have twenty chapters, so only the chapter on screen is set up
   for highlighting (its words wrapped and its timings fetched) — the others
   wait until they're opened. */
(function () {
  "use strict";

  function start() {
    var box = document.querySelector("[data-listen]");
    if (!box) return;
    var chapters = [].slice.call(box.querySelectorAll("[data-ll-chapter]"));
    if (!chapters.length) return;
    var pick = box.querySelector("[data-ll-pick]");
    var prev = box.querySelector("[data-ll-prev]"), next = box.querySelector("[data-ll-next]");
    var auto = box.querySelector("[data-ll-auto]");
    var at = 0;
    var KEY = "dm-listen:" + (box.getAttribute("data-book") || location.pathname);

    function saved() {
      try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (error) { return null; }
    }
    function keep(chapter, time) {
      try { localStorage.setItem(KEY, JSON.stringify({ c: chapter, t: Math.floor(time) })); } catch (error) { /* private mode */ }
    }
    function forget() {
      try { localStorage.removeItem(KEY); } catch (error) { /* private mode */ }
    }

    function mount(chapter) {
      if (chapter.hasAttribute("data-read-along")) return;
      chapter.setAttribute("data-read-along", "");
      if (window.DMReadAlong) {
        try { window.DMReadAlong.setUp(chapter); } catch (error) { /* the audio still plays */ }
      }
    }

    function show(n, play, from) {
      if (n < 0 || n >= chapters.length) return;
      chapters.forEach(function (chapter, i) {
        if (i !== n) {
          var audio = chapter.querySelector("audio");
          if (audio && !audio.paused) audio.pause();
        }
        chapter.hidden = i !== n;
      });
      at = n;
      pick.value = String(n);
      prev.disabled = n === 0;
      next.disabled = n === chapters.length - 1;
      mount(chapters[n]);
      if (play) {
        var audio = chapters[n].querySelector("audio");
        box.scrollIntoView({ behavior: "smooth", block: "start" });
        if (audio) {
          if (from) {
            var seek = function () { try { audio.currentTime = from; } catch (error) { /* not seekable yet */ } };
            if (audio.readyState >= 1) seek(); else audio.addEventListener("loadedmetadata", seek, { once: true });
          }
          audio.play().catch(function () { /* the browser may want a tap on the player */ });
        }
      }
    }

    pick.addEventListener("change", function () { show(Number(pick.value), false); });
    prev.addEventListener("click", function () { show(at - 1, false); });
    next.addEventListener("click", function () { show(at + 1, false); });
    chapters.forEach(function (chapter, i) {
      var audio = chapter.querySelector("audio");
      if (!audio) return;
      var last = 0;
      audio.addEventListener("timeupdate", function () {
        if (Math.abs(audio.currentTime - last) >= 5) { last = audio.currentTime; keep(i, audio.currentTime); }
      });
      audio.addEventListener("pause", function () { if (!audio.ended) keep(i, audio.currentTime); });
      audio.addEventListener("ended", function () {
        if (i + 1 < chapters.length) {
          keep(i + 1, 0);
          if (auto && auto.checked) show(i + 1, true);
        } else {
          forget();                                   // finished the book
        }
      });
    });

    // ▶ Listen: from where this device stopped, or the beginning.
    var resume = saved();
    var startAt = resume && resume.c < chapters.length ? resume.c : 0;
    var startFrom = resume && resume.c < chapters.length ? resume.t : 0;
    if (resume && (resume.c > 0 || resume.t > 5)) {
      var title = pick.options[startAt] ? pick.options[startAt].textContent : "";
      document.querySelectorAll("[data-ll-play-label]").forEach(function (label) {
        label.textContent = "▶ Continue listening · " + title;
      });
    }
    var started = false;
    document.querySelectorAll("[data-ll-play]").forEach(function (button) {
      button.addEventListener("click", function () {
        var playing = chapters[at] && chapters[at].querySelector("audio");
        if (playing && !playing.paused) { box.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
        if (document.fullscreenElement) document.exitFullscreen();
        if (started) { show(at, true); return; }        // carry on with the chapter on screen
        started = true;
        show(startAt, true, startFrom);
      });
    });
    show(startAt, false);
  }

  // After read_along.js (both deferred, this one later), so DMReadAlong exists.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
