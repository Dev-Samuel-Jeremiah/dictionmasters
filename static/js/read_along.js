/* Read along: the text highlights itself as the audio or video plays.

   Any block of text that sits beside a recording can use it — a Reading
   Club chapter, a lesson item, a passage or a conversation:

     <div data-read-along data-ra-sync="/book/read-along/…/">
       <audio controls src="..." data-ra-media></audio>
       <div data-ra-text>… the words …</div>
     </div>

   How the timing works
   --------------------
   Every recording is measured once on the server (apps/book/read_along.py):
   the start and end of each spoken word, taken from the recording itself.
   data-ra-sync is where those timings are fetched. They are lined up with
   the words on the page by matching the words themselves, so a comma, a
   heading or a word the reader skipped never knocks the rest out of step.

   Until a recording has been measured — the first visit, or without the
   services set up — the words are spread over the recording's length in
   proportion to how long each takes to say, with the pauses a reader
   makes at punctuation. Measured timings replace that the moment they
   arrive, even mid-play.

   Smoothness
   ----------
   A single highlight glides from word to word along a line (and steps
   cleanly to the next line), with a thin bar filling as the word is
   said. The clock runs every frame: between the player's own time
   updates it carries the time forward itself, so the highlight moves
   with the voice instead of in jumps.

   Tapping any word jumps the recording to it. Everything here is an
   enhancement: without it the text and the player are unchanged.  */

(function () {
  "use strict";

  var STORE_KEY = "dm-read-along";
  var PAUSE_AFTER = { ",": 1.6, ";": 2, ":": 2, "—": 1.6, ".": 3.2, "!": 3.2, "?": 3.2, "…": 3.2 };
  var LETTER_UNIT = 1;        // a letter's share of the time
  var WORD_UNIT = 1.4;        // every word costs a little, however short
  var BLOCK_PAUSE = 2.4;      // the breath at the end of a paragraph or line
  var USER_SCROLL_REST = 3500; // leave the reader alone this long after they scroll
  var MATCH_WINDOW = 14;      // how far ahead to look for a word the reader skipped
  var SYNC_RETRY = 15000;     // while the server is still measuring
  var SYNC_TRIES = 8;
  var TAP_PREROLL = 0.06;     // start a tapped word a hair early so its first sound isn't clipped

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

  /* A word reduced to what's said: lower case, no accents, no punctuation,
     one kind of apostrophe. "Don’t," and "don't" are the same word. */
  function keyOf(text) {
    return String(text)
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^\p{L}\p{N}]/gu, "");
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
        words.push({ node: span, text: piece, key: keyOf(piece) });
        fragment.appendChild(span);
      });
      node.parentNode.replaceChild(fragment, node);
    });
    return words;
  }

  function measure(words) {
    /* How long each word takes to say, in rough "units", plus the pause
       that follows it. Sentences are numbered as we go so the one being
       read can be brought forward. */
    var sentence = 0;
    words.forEach(function (word, index) {
      var last = word.text.slice(-1);
      var pause = PAUSE_AFTER[last] || 0;
      var next = words[index + 1];
      if (next && word.node.closest("p, li, div, h1, h2, h3") !== next.node.closest("p, li, div, h1, h2, h3")) {
        pause = Math.max(pause, BLOCK_PAUSE);
      }
      word.units = (word.key.length || 0) * LETTER_UNIT + (word.key ? WORD_UNIT : 0);
      word.pause = pause;
      word.sentence = sentence;
      if (PAUSE_AFTER[last] >= 3) sentence += 1;
    });
    return words;
  }

  /* ---- timing ------------------------------------------------------ */

  function estimate(words, duration) {
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

  function applyMeasured(words, measured) {
    /* Give each word on the page the time the recording says it. Words are
       matched in order, looking a little way ahead when one doesn't line
       up — the reader skipped it, or the page splits a word the
       recording joins (and the other way round). Returns false if too
       few match to trust, so the estimate stays. */
    var spoken = [];
    (measured || []).forEach(function (row) {
      var key = keyOf(row[0]);
      var start = Number(row[1]);
      var end = Number(row[2]);
      if (key && isFinite(start) && isFinite(end)) spoken.push({ key: key, start: start, end: Math.max(end, start) });
    });
    if (!spoken.length) return false;

    var starts = new Array(words.length);
    var ends = new Array(words.length);
    var next = 0;
    var matched = 0;
    var said = 0;

    for (var i = 0; i < words.length; i++) {
      var key = words[i].key;
      if (!key) continue;
      said += 1;
      var limit = Math.min(next + MATCH_WINDOW, spoken.length);
      for (var s = next; s < limit; s++) {
        // One spoken word, or several run together ("well" + "known").
        var joined = "";
        var m = s;
        while (m < spoken.length && joined.length < key.length) {
          joined += spoken[m].key;
          m += 1;
          if (key.indexOf(joined) !== 0) break;
        }
        if (joined === key) {
          starts[i] = spoken[s].start;
          ends[i] = spoken[m - 1].end;
          next = m;
          matched += 1;
          break;
        }
        // The page splits what the recording says as one ("to" "day" / "today").
        if (spoken[s].key.indexOf(key) === 0 && spoken[s].key !== key) {
          var rest = spoken[s].key.slice(key.length);
          var j = i + 1;
          while (j < words.length && rest && rest.indexOf(words[j].key) === 0 && words[j].key) {
            rest = rest.slice(words[j].key.length);
            j += 1;
          }
          if (!rest) {
            var share = (spoken[s].end - spoken[s].start) / (j - i);
            for (var k = i; k < j; k++) {
              starts[k] = spoken[s].start + share * (k - i);
              ends[k] = starts[k] + share;
            }
            matched += j - i;
            said += j - i - 1;
            next = s + 1;
            i = j - 1;
            break;
          }
        }
      }
    }

    if (matched < Math.max(2, said * 0.5)) return false;

    // Words that didn't match share the gap between their neighbours,
    // in proportion to how long each takes to say.
    var lastEnd = spoken[spoken.length - 1].end;
    var index = 0;
    while (index < words.length) {
      if (starts[index] !== undefined) { index += 1; continue; }
      var from = index;
      while (index < words.length && starts[index] === undefined) index += 1;
      var run = words.slice(from, index);
      var units = run.reduce(function (sum, w) { return sum + w.units; }, 0);
      var before = from > 0 ? ends[from - 1] : null;
      var after = index < words.length ? starts[index] : null;
      var gapStart = before !== null ? before : Math.max(0, after - units * 0.07);
      var gapEnd = after !== null ? after : Math.min(lastEnd + units * 0.07, gapStart + units * 0.07);
      var length = Math.max(gapEnd - gapStart, 0);
      var at = gapStart;
      run.forEach(function (w, n) {
        var part = units ? (w.units / units) * length : 0;
        starts[from + n] = at;
        ends[from + n] = at + part;
        at += part;
      });
    }

    var floor = 0;
    words.forEach(function (w, n) {
      w.start = Math.max(starts[n], floor);
      w.end = Math.max(ends[n], w.start);
      floor = w.start;
    });
    return true;
  }

  /* ---- one read-along block ---------------------------------------- */

  function setUp(box) {
    // The marked player wins: a lesson item can hold a video and the
    // read-aloud audio, and the words follow the audio.
    var media = box.querySelector("[data-ra-media]") || box.querySelector("audio, video");
    var textBox = box.querySelector("[data-ra-text]");
    if (!media || !textBox) return;

    var words = measure(wordSpans(textBox));
    // Only words with something to say are ever highlighted: a lone dash
    // or bullet just belongs to its neighbours.
    var track = words.filter(function (w) { return w.key; });
    if (track.length < 2) return;
    words.forEach(function (w) { w.track = -1; });
    track.forEach(function (w, n) { w.track = n; });

    var on = remembered();
    var mode = "";             // "", "estimate" or "measured"
    var current = -1;
    var frame = 0;
    var clockTime = 0;
    var clockWall = 0;
    var userScrolled = 0;
    var lastFollow = 0;

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

    // ---- the highlight that glides between words
    var marker = el("span", "ra-marker");
    marker.setAttribute("aria-hidden", "true");
    marker.appendChild(el("span", "ra-marker__fill"));
    textBox.appendChild(marker);
    var markerTop = null;

    var sentences = {};
    track.forEach(function (word) {
      (sentences[word.sentence] = sentences[word.sentence] || []).push(word.node);
    });

    function markSentence(number, active) {
      (sentences[number] || []).forEach(function (node) {
        node.classList.toggle("ra-w--near", active);
      });
    }

    function place(node, glide, pace) {
      var host = textBox.getBoundingClientRect();
      var rects = node.getClientRects();
      var rect = rects.length ? rects[0] : node.getBoundingClientRect();
      var x = rect.left - host.left - textBox.clientLeft;
      var y = rect.top - host.top - textBox.clientTop;
      // Along a line it glides; onto a new line it steps, rather than
      // sweeping diagonally across the paragraph.
      var sameLine = markerTop !== null && Math.abs(y - markerTop) < rect.height / 2;
      // The glide takes at most half the time until this word, so the
      // highlight never trails a quick reader.
      marker.style.setProperty("--ra-glide", Math.round(Math.min(Math.max((pace || 0) * 500, 50), 160)) + "ms");
      marker.classList.toggle("ra-marker--glide", Boolean(glide && sameLine && !calm.matches));
      marker.style.width = rect.width + "px";
      marker.style.height = rect.height + "px";
      marker.style.transform = "translate(" + x.toFixed(1) + "px, " + y.toFixed(1) + "px)";
      marker.classList.add("is-on");
      markerTop = y;
    }

    function paint(index, glide) {
      if (index === current) return;
      if (track[current]) {
        track[current].node.classList.remove("ra-w--on");
        if (!track[index] || track[index].sentence !== track[current].sentence) {
          markSentence(track[current].sentence, false);
        }
      }
      current = index;
      if (track[current]) {
        track[current].node.classList.add("ra-w--on");
        markSentence(track[current].sentence, true);
        var before = track[current - 1];
        place(track[current].node, glide, before ? track[current].start - before.start : 0);
        follow(track[current].node);
      } else {
        marker.classList.remove("is-on");
        markerTop = null;
      }
    }

    function fill(time) {
      var word = track[current];
      if (!word) return;
      var length = Math.max(word.end - word.start, 0.05);
      var progress = Math.min(Math.max((time - word.start) / length, 0), 1);
      marker.style.setProperty("--ra-p", progress.toFixed(3));
    }

    function follow(node) {
      if (!on || media.paused || Date.now() - userScrolled < USER_SCROLL_REST) return;
      var now = Date.now();
      if (now - lastFollow < 500) return;
      var rect = node.getBoundingClientRect();
      var view = window.innerHeight;
      if (rect.top < view * 0.15 || rect.bottom > view * 0.75) {
        lastFollow = now;
        window.scrollBy({ top: rect.top - view * 0.38, behavior: calm.matches ? "auto" : "smooth" });
      }
    }

    function indexAt(time) {
      var low = 0;
      var high = track.length - 1;
      var found = -1;
      while (low <= high) {
        var mid = (low + high) >> 1;
        if (time < track[mid].start) {
          high = mid - 1;
        } else {
          found = mid;
          low = mid + 1;
        }
      }
      return found;
    }

    function now() {
      /* The player's time, carried forward between its own updates so the
         highlight moves every frame. Never runs ahead while buffering. */
      var reported = media.currentTime;
      var wall = performance.now();
      var flowing = !media.paused && !media.seeking && media.readyState >= 3;
      if (!flowing || reported !== clockTime) {
        clockTime = reported;
        clockWall = wall;
        return reported;
      }
      return reported + Math.min((wall - clockWall) / 1000 * (media.playbackRate || 1), 0.3);
    }

    function render(glide) {
      if (!on || !mode) return;
      var time = now();
      paint(indexAt(time), glide);
      fill(time);
    }

    function loop() {
      frame = 0;
      render(true);
      if (on && mode && !media.paused && !media.ended) frame = window.requestAnimationFrame(loop);
    }

    function start() {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      loop();
    }

    function clear() {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      if (track[current]) {
        track[current].node.classList.remove("ra-w--on");
        markSentence(track[current].sentence, false);
      }
      current = -1;
      marker.classList.remove("is-on");
      markerTop = null;
    }

    function becomeTimed(newMode) {
      mode = newMode;
      box.classList.add("is-timed");
      box.classList.toggle("is-measured", newMode === "measured");
      var keep = current;
      current = -1;
      if (track[keep]) track[keep].node.classList.remove("ra-w--on");
      if (!media.paused || media.currentTime > 0) start();
    }

    function useEstimate() {
      if (mode === "measured") return;
      if (!isFinite(media.duration) || media.duration <= 0) return;
      estimate(words, media.duration);
      becomeTimed("estimate");
    }

    function sync(triesLeft) {
      var url = box.getAttribute("data-ra-sync");
      if (!url || !window.fetch) return;
      fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (data) {
          if (!data) return;
          if (data.status === "ready" && applyMeasured(words, data.words)) {
            becomeTimed("measured");
          } else if (data.status === "pending" && triesLeft > 1) {
            window.setTimeout(function () { sync(triesLeft - 1); }, SYNC_RETRY);
          }
        })
        .catch(function () { /* the estimate carries on */ });
    }

    media.addEventListener("loadedmetadata", useEstimate);
    media.addEventListener("durationchange", useEstimate);
    if (media.readyState >= 1) useEstimate();
    sync(SYNC_TRIES);

    media.addEventListener("play", function () {
      box.classList.add("is-playing");
      start();
    });
    media.addEventListener("playing", start);
    media.addEventListener("ratechange", start);
    ["pause", "ended"].forEach(function (event) {
      media.addEventListener(event, function () {
        box.classList.remove("is-playing");
        if (frame) window.cancelAnimationFrame(frame);
        frame = 0;
        if (event === "ended") { clear(); } else { render(false); }
      });
    });
    ["seeking", "seeked"].forEach(function (event) {
      media.addEventListener(event, function () { render(false); });
    });

    textBox.addEventListener("click", function (event) {
      var span = event.target.closest(".ra-w");
      if (!span || !mode || !on) return;
      var word = words[Number(span.dataset.raIndex)];
      if (!word || word.track < 0) return;
      userScrolled = 0;
      media.currentTime = Math.max(0, word.start - TAP_PREROLL);
      paint(word.track, false);
      if (media.paused) media.play().catch(function () { /* the browser may want a tap on the player itself */ });
    });

    toggle.addEventListener("click", function () {
      on = !on;
      remember(on);
      toggle.setAttribute("aria-pressed", String(on));
      box.classList.toggle("is-off", !on);
      if (on) { start(); } else { clear(); }
    });

    // Only the reader's own scrolling pauses the follow — not ours.
    ["wheel", "touchmove"].forEach(function (type) {
      window.addEventListener(type, function () { userScrolled = Date.now(); }, { passive: true });
    });
    window.addEventListener("keydown", function (event) {
      if (/^(ArrowUp|ArrowDown|PageUp|PageDown|Home|End| )$/.test(event.key) && event.target === document.body) {
        userScrolled = Date.now();
      }
    });

    // Text reflows when the screen turns or the window resizes.
    var reflow = function () {
      if (track[current]) place(track[current].node, false, 0);
    };
    if (window.ResizeObserver) {
      new ResizeObserver(reflow).observe(textBox);
    } else {
      window.addEventListener("resize", reflow);
    }
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(reflow);

    box.classList.toggle("is-off", !on);
  }

  function init() {
    document.querySelectorAll("[data-read-along]").forEach(setUp);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
