/* Conversational Dialogue: hear a target word, and "Act it out" — pick a
   speaker and their lines are hidden to say from memory (tap to check). */

(function () {
  "use strict";

  var page = document.querySelector("[data-dialogue]");
  if (!page) return;

  // Hear a word, in a British voice where the device has one.
  var voice = null;
  function pickVoice() {
    if (!("speechSynthesis" in window)) return;
    var voices = window.speechSynthesis.getVoices();
    voice = voices.filter(function (v) { return /en[-_]GB/i.test(v.lang); })[0] ||
            voices.filter(function (v) { return /^en/i.test(v.lang); })[0] || null;
  }
  if ("speechSynthesis" in window) {
    pickVoice();
    window.speechSynthesis.onvoiceschanged = pickVoice;
  }
  page.querySelectorAll("[data-say]").forEach(function (btn) {
    if (!("speechSynthesis" in window)) { btn.hidden = true; return; }
    btn.addEventListener("click", function () {
      var u = new SpeechSynthesisUtterance(btn.getAttribute("data-say"));
      u.lang = "en-GB"; u.rate = 0.85;
      if (voice) u.voice = voice;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      btn.classList.add("is-saying");
      u.onend = function () { btn.classList.remove("is-saying"); };
    });
  });

  // Act it out.
  var roles = page.querySelectorAll("[data-role]");
  var lines = page.querySelectorAll(".cd-line[data-speaker]");
  var hint = page.querySelector("[data-role-hint]");
  var mine = null;
  function apply() {
    lines.forEach(function (line) {
      var hide = mine !== null && line.getAttribute("data-speaker") === mine;
      line.classList.toggle("is-mine", hide);
      line.classList.remove("is-revealed");
      line.tabIndex = hide ? 0 : -1;
      if (hide) line.setAttribute("aria-label", "Your line, hidden. Press to check it.");
      else line.removeAttribute("aria-label");
    });
    roles.forEach(function (r) { r.setAttribute("aria-pressed", String(r.getAttribute("data-role") === mine)); });
    if (hint) hint.hidden = mine === null;
  }
  roles.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var role = btn.getAttribute("data-role");
      mine = mine === role ? null : role;
      apply();
    });
  });
  lines.forEach(function (line) {
    function reveal() { if (line.classList.contains("is-mine")) line.classList.toggle("is-revealed"); }
    line.addEventListener("click", reveal);
    line.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); reveal(); } });
  });
})();
