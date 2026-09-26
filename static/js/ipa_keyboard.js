/* The phonemic keyboard: the 44 sounds of British English, typed into any
   text box on the site.

   Focus a text box and a small "ABC | əː" switch appears. Choose əː and the
   keyboard opens; each key types its symbol where the cursor is. On a phone
   the device's own keyboard stays hidden while this one is open, and comes
   back when you switch to ABC. The choice is remembered on this device.
   Ctrl+Alt+P switches too.

   Symbols are written the way the rest of the site writes them — plain
   "g", "r" and "e" — so what's typed matches lessons and marked answers. */

(function () {
  "use strict";

  var SETS = [
    { key: "vowels", label: "Vowels", keys: [
      ["iː", "fleece"], ["ɪ", "kit"], ["ʊ", "foot"], ["uː", "goose"], ["e", "dress"], ["ə", "comma"],
      ["ɜː", "nurse"], ["ɔː", "thought"], ["æ", "trap"], ["ʌ", "strut"], ["ɑː", "start"], ["ɒ", "lot"]] },
    { key: "diphthongs", label: "Diphthongs", keys: [
      ["ɪə", "near"], ["eɪ", "face"], ["ʊə", "cure"], ["ɔɪ", "choice"], ["əʊ", "goat"], ["eə", "square"],
      ["aɪ", "price"], ["aʊ", "mouth"]] },
    { key: "consonants", label: "Consonants", keys: [
      ["p", "pen"], ["b", "bad"], ["t", "tea"], ["d", "did"], ["tʃ", "church"], ["dʒ", "judge"],
      ["k", "cat"], ["g", "got"], ["f", "fat"], ["v", "van"], ["θ", "think"], ["ð", "this"],
      ["s", "sit"], ["z", "zoo"], ["ʃ", "she"], ["ʒ", "vision"], ["m", "man"], ["n", "no"],
      ["ŋ", "sing"], ["h", "hot"], ["l", "leg"], ["r", "red"], ["w", "wet"], ["j", "yes"]] },
    { key: "marks", label: "Marks", keys: [
      ["ˈ", "main stress"], ["ˌ", "second stress"], ["ː", "long"], ["/", "slash"], [".", "syllable"],
      ["[", "open bracket"], ["]", "close bracket"], ["‿", "linking"]] },
  ];
  var STORE = "dm-ipa-keyboard";
  var SKIP_TYPES = /^(password|email|number|tel|url|date|datetime-local|month|week|time|color|range|file|checkbox|radio|hidden|submit|button|reset|image)$/i;

  var target = null;          // the text box being typed into
  var on = false;             // phonemic mode
  var set = "vowels";
  try {
    on = localStorage.getItem(STORE) === "on";
    set = localStorage.getItem(STORE + "-set") || set;
  } catch (e) { /* private mode: start with ABC */ }

  function editable(el) {
    if (!el || el.closest && el.closest(".ipa-kb, .ipa-switch, [data-no-ipa]")) return false;
    if (el.isContentEditable) return true;
    if (el.tagName === "TEXTAREA") return !el.readOnly && !el.disabled;
    if (el.tagName === "INPUT") return !SKIP_TYPES.test(el.type || "text") && !el.readOnly && !el.disabled;
    return false;
  }

  /* ---------- building ---------- */

  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  var sw = h("div", "ipa-switch");
  sw.setAttribute("role", "group");
  sw.setAttribute("aria-label", "Keyboard");
  sw.hidden = true;
  var abcBtn = h("button", "ipa-switch__btn", "ABC");
  var ipaBtn = h("button", "ipa-switch__btn ipa-switch__btn--ipa", "əː");
  abcBtn.type = ipaBtn.type = "button";
  abcBtn.title = "Your usual keyboard";
  ipaBtn.title = "Phonemic keyboard (Ctrl+Alt+P)";
  sw.appendChild(abcBtn); sw.appendChild(ipaBtn);

  var kb = h("div", "ipa-kb");
  kb.setAttribute("role", "group");
  kb.setAttribute("aria-label", "Phonemic keyboard");
  kb.hidden = true;
  var head = h("div", "ipa-kb__head");
  var tabs = h("div", "ipa-kb__tabs");
  tabs.setAttribute("role", "tablist");
  var tools = h("div", "ipa-kb__tools");
  var keys = h("div", "ipa-kb__keys");
  var foot = h("div", "ipa-kb__foot");
  head.appendChild(tabs); head.appendChild(tools);
  kb.appendChild(head); kb.appendChild(keys); kb.appendChild(foot);

  SETS.forEach(function (s) {
    var t = h("button", "ipa-kb__tab", s.label);
    t.type = "button";
    t.setAttribute("role", "tab");
    t.dataset.set = s.key;
    tabs.appendChild(t);
  });
  var hideBtn = h("button", "ipa-kb__tool", "ABC ⌨");
  hideBtn.type = "button";
  hideBtn.title = "Back to your usual keyboard";
  tools.appendChild(hideBtn);

  [["←", "left", "Move left"], ["space", "space", "Space"], ["→", "right", "Move right"], ["⌫", "back", "Delete"]].forEach(function (k) {
    var b = h("button", "ipa-kb__key ipa-kb__key--" + k[1], k[0] === "space" ? "" : k[0]);
    b.type = "button";
    b.dataset.action = k[1];
    b.setAttribute("aria-label", k[2]);
    if (k[1] === "space") b.appendChild(h("span", "ipa-kb__spacebar", "space"));
    foot.appendChild(b);
  });

  function drawKeys() {
    keys.textContent = "";
    var current = SETS.filter(function (s) { return s.key === set; })[0] || SETS[0];
    set = current.key;
    current.keys.forEach(function (k) {
      var b = h("button", "ipa-kb__key");
      b.type = "button";
      b.dataset.sym = k[0];
      b.setAttribute("aria-label", k[0] + ", as in " + k[1]);
      b.title = k[1];
      b.appendChild(h("span", "ipa-kb__sym", k[0]));
      b.appendChild(h("span", "ipa-kb__word", k[1]));
      keys.appendChild(b);
    });
    tabs.querySelectorAll(".ipa-kb__tab").forEach(function (t) {
      var sel = t.dataset.set === set;
      t.classList.toggle("is-on", sel);
      t.setAttribute("aria-selected", String(sel));
    });
  }

  /* ---------- typing ---------- */

  function fire(el) {
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function insert(text) {
    if (!target) return;
    if (target.isContentEditable) {
      target.focus();
      document.execCommand("insertText", false, text);
      return;
    }
    var start = target.selectionStart, end = target.selectionEnd;
    if (start === null || start === undefined) { target.value += text; fire(target); return; }
    target.setRangeText(text, start, end, "end");
    fire(target);
  }

  function action(kind) {
    if (!target) return;
    if (target.isContentEditable) {
      target.focus();
      if (kind === "space") document.execCommand("insertText", false, " ");
      else if (kind === "back") document.execCommand("delete");
      else {
        var sel = window.getSelection();
        if (sel && sel.modify) sel.modify("move", kind === "left" ? "backward" : "forward", "character");
      }
      return;
    }
    var s = target.selectionStart || 0, e = target.selectionEnd || 0;
    if (kind === "space") { insert(" "); return; }
    if (kind === "back") {
      if (s !== e) target.setRangeText("", s, e, "end");
      else if (s > 0) target.setRangeText("", s - 1, s, "end");
      fire(target);
      return;
    }
    var at = kind === "left" ? Math.max(0, s - 1) : Math.min(target.value.length, e + 1);
    target.setSelectionRange(at, at);
  }

  /* ---------- showing ---------- */

  function nativeKeyboard(off) {
    // On a phone, keep the device's keyboard down while ours is up.
    if (!target || target.isContentEditable) return;
    if (off) {
      if (!target.hasAttribute("data-ipa-inputmode")) {
        target.setAttribute("data-ipa-inputmode", target.getAttribute("inputmode") || "");
      }
      target.setAttribute("inputmode", "none");
    } else if (target.hasAttribute("data-ipa-inputmode")) {
      var was = target.getAttribute("data-ipa-inputmode");
      if (was) target.setAttribute("inputmode", was); else target.removeAttribute("inputmode");
      target.removeAttribute("data-ipa-inputmode");
    }
  }

  function measure() {
    if (!kb.hidden) document.documentElement.style.setProperty("--ipa-kb-h", kb.offsetHeight + "px");
  }

  function keepInSight() {
    // Keep the text box in sight above the keyboard.
    if (!target || kb.hidden) return;
    var r = target.getBoundingClientRect(), top = window.innerHeight - kb.offsetHeight;
    if (r.bottom > top - 12) window.scrollBy({ top: r.bottom - top + 60, behavior: "smooth" });
    else if (r.top < 0) window.scrollBy({ top: r.top - 80, behavior: "smooth" });
  }

  function render() {
    var active = !!target;
    var open = active && on;
    sw.hidden = !active || open;           // once open, the keyboard's own ABC button switches back
    kb.hidden = !open;
    abcBtn.setAttribute("aria-pressed", String(!on));
    ipaBtn.setAttribute("aria-pressed", String(on));
    document.documentElement.classList.toggle("ipa-kb-open", open);
    if (open) {
      measure();
      requestAnimationFrame(keepInSight);
    }
  }

  function setMode(next) {
    on = next;
    try { localStorage.setItem(STORE, on ? "on" : "off"); } catch (e) { /* fine */ }
    if (target) {
      nativeKeyboard(on);
      // Re-focus so the device notices the change of keyboard.
      if (!target.isContentEditable && document.activeElement === target) { target.blur(); target.focus({ preventScroll: true }); }
    }
    render();
  }

  // Tapping the keyboard must never take the cursor out of the text box.
  [kb, sw].forEach(function (panel) {
    panel.addEventListener("pointerdown", function (e) {
      if (e.target.closest("button")) e.preventDefault();
    });
  });

  kb.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.sym) insert(b.dataset.sym);
    else if (b.dataset.action) action(b.dataset.action);
    else if (b.dataset.set) {
      set = b.dataset.set;
      try { localStorage.setItem(STORE + "-set", set); } catch (err) { /* fine */ }
      drawKeys();
      measure();
    } else if (b === hideBtn) setMode(false);
  });
  abcBtn.addEventListener("click", function () { setMode(false); });
  ipaBtn.addEventListener("click", function () { setMode(true); });

  document.addEventListener("focusin", function (e) {
    if (editable(e.target)) {
      if (target && target !== e.target) nativeKeyboard(false);
      target = e.target;
      if (on) nativeKeyboard(true);
      render();
    }
  });
  document.addEventListener("focusout", function () {
    // Wait a moment: focus may simply be moving to another text box.
    setTimeout(function () {
      var now = document.activeElement;
      if (now && (editable(now) || now.closest && now.closest(".ipa-kb, .ipa-switch"))) return;
      if (target) nativeKeyboard(false);
      target = null;
      render();
    }, 120);
  });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && e.altKey && (e.key === "p" || e.key === "P")) {
      if (!target && !editable(document.activeElement)) return;
      e.preventDefault();
      setMode(!on);
    }
  });

  function mount() {
    drawKeys();
    if (window.ResizeObserver) new ResizeObserver(function () { measure(); keepInSight(); }).observe(kb);
    document.body.appendChild(kb);
    document.body.appendChild(sw);
    if (editable(document.activeElement)) { target = document.activeElement; if (on) nativeKeyboard(true); }
    render();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
