/* Read along: the text highlights itself as the audio or video plays.

   Any block of text that sits beside a recording can use it — a Reading
   Club chapter, a lesson item, a passage or a conversation:

     <div data-read-along>
       <audio controls src="..." data-ra-media></audio>
       <div data-ra-text>… the words …</div>
     </div>

   How the timing works
   --------------------
   Uploads don't come with word timings, so the words are spread across
   the real length of the recording: each word takes time in proportion
   to how long it is to say, and punctuation is given the pause a reader
   would take. That tracks a steady read-aloud closely, which is what
   these recordings are. Tapping any word jumps the recording to it, so
   a child is never more than one tap from the right place.

   Everything here is an enhancement. Without it — or with JavaScript
   off — the text and the player are both still there, unchanged.  */

(function () {
  "use strict";

  var STORE_KEY = "dm-read-along";
  var PAUSE_AFTER = { ",": 1.6, ";": 2, ":": 2, "—": 1.6, ".": 3.2, "!": 3.2, "?": 3.2, "…": 3.2 };
  var LETTER_UNIT = 1;      // a letter's share of the time
  var WORD_UNIT = 1.4;      // every word costs a little, however short
  var BLOCK_PAUSE = 2.4;    // the breath at the end of a paragraph or line
  var SCROLL_REST_MS = 2600; // leave the reader alone this long after they scroll

  var calm = window.matchMedia("(prefers-reduced-motion: reduce)");

  function remembered() {
    try {
      return window.localStorage.getItem(STORE_KEY) !== "off";
    } catch (error) {
      return true;
    }
  }

  function remember(on) {
    try {
      window.localStorage.setItem(STORE_KEY, on ? "on" : "off");
    } catch (error) { /* private window: the choice just won't persist */ }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* ---- splitting the text into words ------------------------------- */

  function wordSpans(root) {
    /* Wrap every word in its own span, leaving the markup around it
       (paragraphs, line breaks, names in a dialogue) exactly as it is. */
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (node.parentElement.closest("[data-ra-skip]")) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    var textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    var words = [];
    textNodes.forEach(function (node) {
      var fragment = document.createDocumentFragment();
      // Keep the spaces: split on them but put them back between words.
      node.nodeValue.split(/(\s+)/).forEach(function (piece) {
        if (!piece) return;
        if (!piece.trim()) {
          fragment.appendChild(document.createTextNode(piece));
          return;
        }
        var span = el("span", "ra-w", piece);
        span.dataset.raIndex = words.length;
        words.push({ node: span, text: piece });
        fragment.appendChild(span);
      });
      node.parentNode.replaceChild(fragment, node);
    });
    return words;
  }

  function measure(words) {
    /* How long each word takes to say, in rough "units", plus the pause
       that follows it. Sentences are numbered as we go so the one being
       read can be lifted out of the page. */
    var sentence = 0;
    words.forEach(function (word, index) {
      var letters = word.text.replace(/[^\p{L}\p{N}]/gu, "").length || 1;
      var last = word.text.slice(-1);
      var pause = PAUSE_AFTER[last] || 0;
      // A line or paragraph of its own gets a breath after it.
      var next = words[index + 1];
      if (next && word.node.closest("p, li, div, h1, h2, h3") !== next.node.closest("p, li, div, h1, h2, h3")) {
        pause = Math.max(pause, BLOCK_PAUSE);
      }
      word.units = letters * LETTER_UNIT + WORD_UNIT;
      word.pause = pause;
      word.sentence = sentence;
      if (PAUSE_AFTER[last] >= 3) sentence += 1;
    });
    return words;
  }

  function schedule(words, duration) {
    /* Spread the words across the real length of the recording. A little
       is held back at each end for the silence a recording usually has. */
    var total = words.reduce(function (sum, word) { return sum + word.units + word.pause; }, 0) || 1;
    var lead = Math.min(0.3, duration * 0.02);
    var tail = Math.min(0.5, duration * 0.03);
    var span = Math.max(duration - lead - tail, 0.1);
    var at = lead;
    words.forEach(function (word) {
      word.start = at;
      at += (word.units / total) * span;
      word.end = at;
      at += (word.pause / total) * span;
    });
  }

  /* ---- one read-along block ---------------------------------------- */

  function setUp(box) {
    // The marked player wins: a lesson item can hold a video and the
    // read-aloud audio, and the words follow the audio.
    var media = box.querySelector("[data-ra-media]") || box.querySelector("audio, video");
    var textBox = box.querySelector("[data-ra-text]");
    if (!media || !textBox) return;

    var words = measure(wordSpans(textBox));
    if (words.length < 2) return;

    var on = remembered();
    var current = -1;
    var ready = false;
    var frame = 0;
    var lastScroll = 0;
    var userScrolled = 0;

    box.classList.add("ra", "is-ready");
    textBox.classList.add("ra-text");

    // ---- the bar above the text
    var bar = box.querySelector("[data-ra-bar]") || box.insertBefore(el("div"), textBox);
    bar.classList.add("ra-bar");

    var toggle = el("button", "ra-toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-pressed", String(on));
    toggle.innerHTML = '<span class="ra-toggle__dot" aria-hidden="true"></span><span>Follow the words</span>';

    var hint = el("span", "ra-hint", "Tap any word to jump there");
    bar.appendChild(toggle);
    bar.appendChild(hint);

    function paint(index) {
      if (index === current) return;
      if (words[current]) {
        words[current].node.classList.remove("ra-w--on");
        markSentence(words[current].sentence, false);
      }
      current = index;
      if (words[current]) {
        words[current].node.classList.add("ra-w--on");
        markSentence(words[current].sentence, true);
        follow(words[current].node);
      }
    }

    var sentences = {};
    words.forEach(function (word) {
      (sentences[word.sentence] = sentences[word.sentence] || []).push(word.node);
    });

    function markSentence(number, active) {
      (sentences[number] || []).forEach(function (node) {
        node.classList.toggle("ra-w--near", active);
      });
    }

    function follow(node) {
      if (!on || Date.now() - userScrolled < SCROLL_REST_MS) return;
      var now = Date.now();
      if (now - lastScroll < 400) return;
      var box_ = node.getBoundingClientRect();
      var margin = 120;
      if (box_.top < margin || box_.bottom > window.innerHeight - margin) {
        lastScroll = now;
        node.scrollIntoView({ block: "center", behavior: calm.matches ? "auto" : "smooth" });
      }
    }

    function indexAt(time) {
      var low = 0;
      var high = words.length - 1;
      var found = -1;
      while (low <= high) {
        var mid = (low + high) >> 1;
        if (time < words[mid].start) {
          high = mid - 1;
        } else {
          found = mid;
          low = mid + 1;
        }
      }
      return found;
    }

    function tick() {
      if (!on || !ready) return;
      paint(indexAt(media.currentTime));
      if (!media.paused && !media.ended) frame = window.requestAnimationFrame(tick);
    }

    function prepare() {
      if (!isFinite(media.duration) || media.duration <= 0) return;
      schedule(words, media.duration);
      ready = true;
      box.classList.add("is-timed");
      tick();
    }

    function clear() {
      window.cancelAnimationFrame(frame);
      if (words[current]) {
        words[current].node.classList.remove("ra-w--on");
        markSentence(words[current].sentence, false);
      }
      current = -1;
    }

    media.addEventListener("loadedmetadata", prepare);
    media.addEventListener("durationchange", prepare);
    if (media.readyState >= 1) prepare();

    media.addEventListener("play", function () {
      box.classList.add("is-playing");
      window.cancelAnimationFrame(frame);
      tick();
    });
    ["pause", "ended"].forEach(function (event) {
      media.addEventListener(event, function () {
        box.classList.remove("is-playing");
        window.cancelAnimationFrame(frame);
        if (event === "ended") clear();
      });
    });
    media.addEventListener("seeked", function () {
      if (on && ready) paint(indexAt(media.currentTime));
    });

    textBox.addEventListener("click", function (event) {
      var word = event.target.closest(".ra-w");
      if (!word || !ready) return;
      var chosen = words[Number(word.dataset.raIndex)];
      if (!chosen) return;
      userScrolled = 0;
      media.currentTime = chosen.start;
      paint(Number(word.dataset.raIndex));
      if (media.paused) media.play().catch(function () { /* the browser may want a tap on the player itself */ });
    });

    toggle.addEventListener("click", function () {
      on = !on;
      remember(on);
      toggle.setAttribute("aria-pressed", String(on));
      box.classList.toggle("is-off", !on);
      if (on) { tick(); } else { clear(); }
    });

    window.addEventListener("scroll", function () { userScrolled = Date.now(); }, { passive: true });

    box.classList.toggle("is-off", !on);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-read-along]").forEach(setUp);
  });
})();
