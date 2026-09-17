/* Quick look: the Phonemic Chart and Quick Words, without losing your place.

   The two tool buttons in the header open their tool in a panel over the
   page you're on, instead of leaving it. The page underneath is never
   unloaded, so an EchoSpell activity keeps its typed answers, dragged
   words, scroll position and audio exactly as they were. Anything that
   was playing is paused while the panel is open and carries on when it
   closes.

   Press the same button again (or "Back to my page", or Escape) to close
   the panel. Each tool keeps its own state too, so reopening the chart
   shows the sound you last looked at.

   Inside the panel the tool is its own page, marked "is-embedded" by
   base.html so it drops the site header and footer. Links from there to
   anywhere other than the two tools open in the main window.

   Without this script the buttons are ordinary links.  */

(function () {
  "use strict";

  var TOOL_PATHS = ["/book/phonemic-chart/", "/quick-words/"];
  var embedded = document.documentElement.classList.contains("is-embedded");

  /* ---- inside the panel ------------------------------------------- */

  if (embedded) {
    // Only the tools themselves stay in the panel; a link elsewhere (a
    // full sound lesson, the dashboard) takes the whole window there.
    document.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[href]");
      if (!link || link.target || link.hasAttribute("download")) return;
      var url;
      try { url = new URL(link.href, location.href); } catch (error) { return; }
      var tool = url.origin === location.origin && TOOL_PATHS.some(function (path) {
        return url.pathname.indexOf(path) === 0;
      });
      if (!tool) link.target = "_top";
    }, true);

    // Escape closes the panel even while the tool has the focus.
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        try { window.parent.dispatchEvent(new CustomEvent("dm:tool-close")); } catch (error) { /* not ours */ }
      }
    });
    return;
  }

  /* ---- on the page ------------------------------------------------ */

  var buttons = Array.prototype.slice.call(document.querySelectorAll(".tool-btn[data-tool]"));
  if (!buttons.length) return;

  var header = document.querySelector(".site-header");
  var calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  var sheet = null;
  var frames = {};
  var openTool = null;
  var paused = [];
  var returnFocus = null;
  var savedScroll = null;

  function onToolPage(button) {
    return location.pathname.indexOf(button.dataset.toolUrl) === 0;
  }

  function build() {
    sheet = document.createElement("div");
    sheet.className = "tool-sheet";
    sheet.hidden = true;
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.innerHTML =
      '<div class="tool-sheet__bar">' +
        '<p class="tool-sheet__title"></p>' +
        '<p class="tool-sheet__note">Your page is paused. Close this to carry on where you left off.</p>' +
        '<button type="button" class="tool-sheet__close">&larr; Back to my page</button>' +
      "</div>" +
      '<div class="tool-sheet__stage"><p class="tool-sheet__loading">Opening&hellip;</p></div>';
    document.body.appendChild(sheet);
    sheet.querySelector(".tool-sheet__close").addEventListener("click", close);
  }

  function frameFor(button) {
    var key = button.dataset.tool;
    if (frames[key]) return frames[key];
    var frame = document.createElement("iframe");
    frame.className = "tool-sheet__frame";
    frame.title = button.dataset.toolTitle;
    frame.src = button.dataset.toolUrl;
    frame.addEventListener("load", function () {
      frame.classList.add("is-loaded");
    });
    sheet.querySelector(".tool-sheet__stage").appendChild(frame);
    frames[key] = frame;
    return frame;
  }

  function placeBelowHeader() {
    // The header stays on top, so the button that opened the panel is
    // right there to close it again.
    var bottom = header ? Math.max(header.getBoundingClientRect().bottom, 0) : 0;
    sheet.style.setProperty("--tool-top", Math.round(bottom) + "px");
  }

  function pausePage() {
    paused = [];
    document.querySelectorAll("audio, video").forEach(function (media) {
      if (!media.paused && !media.ended) {
        media.pause();
        paused.push(media);
      }
    });
  }

  function resumePage() {
    paused.forEach(function (media) {
      var playing = media.play();
      if (playing && playing.catch) playing.catch(function () { /* the browser wants a tap first */ });
    });
    paused = [];
  }

  function hushTools() {
    Object.keys(frames).forEach(function (key) {
      try {
        frames[key].contentDocument.querySelectorAll("audio, video").forEach(function (media) { media.pause(); });
      } catch (error) { /* still loading */ }
    });
  }

  function setButtons() {
    buttons.forEach(function (button) {
      var active = openTool === button.dataset.tool;
      button.classList.toggle("is-open", active);
      button.setAttribute("aria-expanded", String(active));
    });
  }

  function open(button) {
    if (!sheet) build();
    var wasOpen = openTool !== null;
    if (!wasOpen) {
      returnFocus = button;
      // A tool jumping to a sound (#top) can scroll the page behind it,
      // so the reader's place is written down and put back on close.
      savedScroll = { x: window.scrollX, y: window.scrollY };
      pausePage();
      document.documentElement.classList.add("tool-sheet-open");
    } else {
      hushTools();
    }

    openTool = button.dataset.tool;
    var frame = frameFor(button);
    Object.keys(frames).forEach(function (key) { frames[key].hidden = frames[key] !== frame; });
    sheet.querySelector(".tool-sheet__title").textContent = button.dataset.toolTitle;
    sheet.setAttribute("aria-label", button.dataset.toolTitle);
    placeBelowHeader();
    sheet.hidden = false;
    if (!wasOpen && !calm.matches) {
      sheet.classList.remove("is-in");
      void sheet.offsetWidth;      // restart the entrance
    }
    sheet.classList.add("is-in");
    setButtons();
    sheet.querySelector(".tool-sheet__close").focus({ preventScroll: true });
  }

  function close() {
    if (openTool === null) return;
    hushTools();
    sheet.hidden = true;
    sheet.classList.remove("is-in");
    document.documentElement.classList.remove("tool-sheet-open");
    openTool = null;
    setButtons();
    if (savedScroll) window.scrollTo({ left: savedScroll.x, top: savedScroll.y, behavior: "instant" });
    resumePage();
    if (returnFocus) returnFocus.focus({ preventScroll: true });
  }

  buttons.forEach(function (button) {
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-haspopup", "dialog");

    button.addEventListener("click", function (event) {
      // Let a new tab, or the tool's own page, behave as a link.
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
      if (onToolPage(button)) {
        // Already on this tool's page: go back to whatever came before,
        // which the browser can usually restore exactly.
        if (document.referrer && document.referrer.indexOf(location.origin) === 0 && history.length > 1) {
          event.preventDefault();
          history.back();
        }
        return;
      }
      event.preventDefault();
      if (openTool === button.dataset.tool) {
        close();
      } else {
        open(button);
      }
    });
  });

  window.addEventListener("dm:tool-close", close);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && openTool !== null) close();
  });
  window.addEventListener("resize", function () {
    if (openTool !== null) placeBelowHeader();
  });
})();
