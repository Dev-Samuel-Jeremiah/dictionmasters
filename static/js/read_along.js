/* Read along: the text highlights itself as the audio or video plays.

   Any block of text that sits beside a recording can use it — a Reading
   Club chapter, a lesson item, a passage or a conversation:

     <div data-read-along data-ra-sync="/book/read-along/…/">
       <audio controls src="..." data-ra-media></audio>
       <div data-ra-text>… the words …</div>
     </div>

   How the timing works
   --------------------
   Every recording is measured once on the server (apps/book/read_along.py)
   and fetched from data-ra-sync: the start and end of each spoken word,
   the stretches where someone is actually speaking, and how much of the
   page's text the recording really says.

   The words heard are lined up with the words on the page by matching
   what is said, so punctuation, a heading or a skipped word never knock
   the rest out of step. Words in between two matches share the gap, and
   they share it in *speaking* time, so nothing moves while the reader
   pauses for breath.

   If the recording turns out not to be reading this text at all — a
   different take, or the wrong file — the words can't be matched, so the
   page is paced along the voice instead: phrase by phrase, each one
   starting as the voice starts, nothing moving while it pauses. With neither (the first visit, or without
   the services set up) the words are spread over the recording's length
   in proportion to how long each takes to say.

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
  var GAP_SEARCH = 400;       // ...and how far, at most, between two sure footholds
  var MIN_MATCHED = 0.35;     // below this the recording isn't reading this text
  var SNAP_ONSET = 0.22;      // pull a word's start onto the moment speech resumes, within this
  var AFTER_PAUSE = 0.25;     // ...but only for a word that follows a real gap
  var ANTICIPATE = 0.035;     // light a word a frame or two early, so it never reads as late
  var LEAST_LIT = 0.06;       // no word is lit for less time than the eye can catch
  var LINGER = 1.2;           // how long a word stays lit after it has been said
  var MOST_LIT = 1.5;         // the longest anyone spends saying a single word
  var UNREAD_RUN = 10;        // more unmatched words in a row than this, and the voice isn't reading them
  var EDGE_RUN = 4;           // ...or this many at the very start or end, which a recording often skips
  var TRUST_MATCH = 0.5;      // below this the transcript is too patchy to say what was left unread
  var LONELY = 4;             // an anchor with no other within this many words is a coincidence
  var TIME_COMPANY = 5;       // ...and its neighbour must be within this many seconds of it
  var INTRO_MIN = 3;          // a greeting longer than this is worth pointing out
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

  var ONES = { zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9,
    ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17,
    eighteen: 18, nineteen: 19 };
  var TENS = { twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90 };

  function asNumber(key) {
    /* "three" and "3" are the same word to a listener; so are "twenty-one"
       and "21". A page can be written either way. */
    if (key in ONES) return String(ONES[key]);
    if (key in TENS) return String(TENS[key]);
    var found = "";
    Object.keys(TENS).forEach(function (tens) {
      if (!found && key.indexOf(tens) === 0 && key.slice(tens.length) in ONES) {
        found = String(TENS[tens] + ONES[key.slice(tens.length)]);
      }
    });
    return found;
  }

  /* A word reduced to what's said: lower case, no accents, no punctuation,
     one kind of apostrophe, numbers as digits. "Don’t," and "don't" are the
     same word, and so are "12" and "twelve". */
  function keyOf(text) {
    var key = String(text)
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^\p{L}\p{N}]/gu, "");
    return asNumber(key) || key;
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

  /* Where the reader is actually speaking, as a way of measuring time:
     `spoken(t)` is how many seconds of speech have happened by `t`, and
     `at(x)` is the other way round. Silence costs nothing, so words never
     creep forward during a pause. */
  function speechClock(runs, duration) {
    var edges = [];
    var total = 0;
    (runs || []).forEach(function (run) {
      var from = Math.max(0, Number(run[0]));
      var to = Math.max(from, Number(run[1]));
      edges.push({ from: from, to: to, before: total });
      total += to - from;
    });
    if (!edges.length || total <= 0) return null;

    return {
      total: total,
      spoken: function (time) {
        var sum = 0;
        for (var i = 0; i < edges.length; i++) {
          if (time <= edges[i].from) break;
          sum += Math.min(time, edges[i].to) - edges[i].from;
          if (time < edges[i].to) break;
        }
        return sum;
      },
      at: function (seconds) {
        for (var i = 0; i < edges.length; i++) {
          var length = edges[i].to - edges[i].from;
          if (seconds <= edges[i].before + length) return edges[i].from + (seconds - edges[i].before);
        }
        return edges[edges.length - 1].to;
      },
      lastEnd: edges[edges.length - 1].to,
      firstStart: edges[0].from,
      // The moment a run of speech begins, for a sentence to start on.
      snap: function (time, within) {
        var best = time;
        var gap = within || 1.5;
        edges.forEach(function (edge) {
          var distance = Math.abs(edge.from - time);
          if (distance < gap) { gap = distance; best = edge.from; }
        });
        return best;
      },
    };
  }

  /* Spread `run` of words between two moments, sharing the time out by how
     long each word takes to say — through the speech clock when there is
     one, so pauses stay quiet. */
  function spread(run, from, to, clock) {
    var units = run.reduce(function (sum, word) { return sum + word.units; }, 0) || run.length || 1;
    var startAt = clock ? clock.spoken(from) : from;
    var endAt = clock ? clock.spoken(to) : to;
    var length = Math.max(endAt - startAt, 0);
    var at = startAt;
    run.forEach(function (word) {
      var share = (word.units / units) * length;
      word.start = clock ? clock.at(at) : at;
      word.end = Math.min(clock ? clock.at(at + share) : at + share, word.start + MOST_LIT);
      at += share;
    });
  }

  /* Phrase by phrase across the speech. A phrase ends wherever a reader
     would draw breath — a comma, a full stop, the end of a line — so a
     pause in the recording falls between phrases, never inside one. */
  function spreadSentences(words, clock) {
    var groups = [];
    var open = null;
    words.forEach(function (word) {
      if (open === null) {
        open = { words: [word], units: word.units };
        groups.push(open);
      } else {
        open.words.push(word);
        open.units += word.units;
      }
      if (word.pause > 0) open = null;         // a breath: start the next phrase here
    });

    var total = groups.reduce(function (sum, group) { return sum + group.units; }, 0) || 1;
    var at = 0;
    var edges = [clock.firstStart];
    groups.forEach(function (group) {
      at += (group.units / total) * clock.total;
      edges.push(clock.at(at));
    });
    // Pull each sentence's start onto the start of a run of speech, keeping
    // them in order.
    for (var i = 1; i < edges.length - 1; i++) {
      edges[i] = Math.max(edges[i - 1], clock.snap(edges[i]));
    }
    edges[edges.length - 1] = Math.max(edges[edges.length - 2], clock.lastEnd);
    groups.forEach(function (group, index) {
      spread(group.words, edges[index], edges[index + 1], clock);
    });
  }

  /* ---- lining the page up with what was heard --------------------- */

  function nearly(a, b) {
    /* The same word spelt a little differently — "Timi" and "Timmy",
       "colour" and "color" — one letter added, dropped or changed. Only
       for words of four letters or more, where that can't be chance. */
    if (a === b) return true;
    if (a.length < 4 || b.length < 4 || Math.abs(a.length - b.length) > 1) return false;
    var i = 0, j = 0, edits = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { i += 1; j += 1; continue; }
      if (++edits > 1) return false;
      if (a.length > b.length) { i += 1; }
      else if (b.length > a.length) { j += 1; }
      else { i += 1; j += 1; }
    }
    return edits + (a.length - i) + (b.length - j) <= 1;
  }

  var SOUND_GROUPS = { b: 1, f: 1, p: 1, v: 1, c: 2, g: 2, j: 2, k: 2, q: 2, s: 2, x: 2, z: 2,
    d: 3, t: 3, l: 4, m: 5, n: 5, r: 6 };

  function soundOf(key) {
    /* Soundex: what a word sounds like, so "Timi" and "Timmy", "Ade" and
       "Addy" come out the same. */
    if (!/^[a-z]+$/.test(key)) return key;
    var code = key[0];
    var last = SOUND_GROUPS[key[0]] || 0;
    for (var i = 1; i < key.length && code.length < 4; i++) {
      var group = SOUND_GROUPS[key[i]] || 0;
      if (group && group !== last) code += group;
      if (key[i] !== "h" && key[i] !== "w") last = group;
    }
    return (code + "000").slice(0, 4);
  }

  function soundsLike(a, b) {
    return a.length >= 4 && b.length >= 4 && a[0] === b[0]
      && Math.abs(a.length - b.length) <= 2 && soundOf(a) === soundOf(b);
  }

  function counts(list) {
    var seen = {};
    list.forEach(function (key) { seen[key] = (seen[key] || 0) + 1; });
    return seen;
  }

  function longestRun(pairs) {
    /* The longest set of pairs whose spoken positions keep going forward:
       the backbone of the alignment (patience sorting). */
    var tails = [];
    var back = [];
    pairs.forEach(function (pair, index) {
      var low = 0, high = tails.length;
      while (low < high) {
        var mid = (low + high) >> 1;
        if (pairs[tails[mid]].said < pair.said) { low = mid + 1; } else { high = mid; }
      }
      back[index] = low > 0 ? tails[low - 1] : -1;
      tails[low] = index;
      if (low === tails.length) tails.push(index);
    });
    var out = [];
    var at = tails.length ? tails[tails.length - 1] : -1;
    while (at >= 0) { out.unshift(pairs[at]); at = back[at]; }
    return out;
  }

  function anchorsFor(page, said) {
    /* Words that appear exactly once on the page and once in the recording
       can only mean each other; they pin the two together. Then the words
       between two pins are matched off in order. */
    var pageSeen = counts(page.map(function (word) { return word.key; }));
    var saidSeen = counts(said.map(function (word) { return word.key; }));
    var unique = [];
    page.forEach(function (word, index) {
      if (pageSeen[word.key] === 1 && saidSeen[word.key] === 1) {
        var where = -1;
        for (var i = 0; i < said.length; i++) { if (said[i].key === word.key) { where = i; break; } }
        if (where >= 0) unique.push({ page: index, said: where });
      }
    });

    var pins = longestRun(unique);
    var anchors = [];
    var lastPage = -1, lastSaid = -1;
    pins.concat([{ page: page.length, said: said.length }]).forEach(function (pin) {
      // Fill in between this pin and the one before, in order. The search
      // runs the whole way to the next pin, so a recording that opens with
      // a greeting — "Hi, it's me, let's read together" — doesn't hide the
      // place where the reading actually starts.
      var p = lastPage + 1, q = lastSaid + 1;
      function agrees(pageAt, saidAt) {
        // The same word, or a spelling of it — "Timi" read as "Timmy" —
        // as long as the word after it agrees as well.
        if (nearly(page[pageAt].key, said[saidAt].key)) return true;
        return soundsLike(page[pageAt].key, said[saidAt].key)
          && pageAt + 1 < page.length && saidAt + 1 < said.length
          && nearly(page[pageAt + 1].key, said[saidAt + 1].key);
      }

      while (p < pin.page && q < pin.said) {
        if (agrees(p, q)) {
          anchors.push({ page: p, said: q });
          p += 1; q += 1;
          continue;
        }
        var limit = Math.min(pin.said, q + GAP_SEARCH);
        var found = -1;
        var pair = -1;
        for (var i = q; i < limit; i++) {
          if (!agrees(p, i)) continue;
          if (found < 0) found = i;
          // Two words in a row settle it: a lone "the" or "and" can land
          // anywhere, but "the Monday" only lands where the reading is.
          if (p + 1 < pin.page && i + 1 < said.length && nearly(said[i + 1].key, page[p + 1].key)) { pair = i; break; }
        }
        var at = pair >= 0 ? pair : found;
        if (at >= 0) { anchors.push({ page: p, said: at }); p += 1; q = at + 1; } else { p += 1; }
      }
      if (pin.page < page.length) anchors.push({ page: pin.page, said: pin.said });
      lastPage = pin.page; lastSaid = pin.said;
    });
    return anchors;
  }

  function withoutStrays(anchors, said) {
    /* A single "and" or "to" matching somewhere far from every other match
       is a coincidence, not the reading — most often in a closing remark
       after the passage has finished. Anchors need company to be believed. */
    function close(one, other) {
      // Company means next to each other on the page, next to each other in
      // what was heard, and at about the same moment. A page word matched
      // to a word spoken sixteen seconds later — in the reader's closing
      // remarks — is a coincidence, however near it looks on the page.
      if (!other) return false;
      return Math.abs(other.page - one.page) <= LONELY
        && Math.abs(other.said - one.said) <= LONELY * 3
        && Math.abs(said[other.said].start - said[one.said].start) <= TIME_COMPANY;
    }

    return anchors.filter(function (anchor, at) {
      return close(anchor, anchors[at - 1]) || close(anchor, anchors[at + 1]);
    });
  }

  function applyTiming(words, data) {
    /* Give every word on the page a start and an end. Returns the way it
       was worked out: "measured", "speech" or "" when neither is possible. */
    var duration = Number(data.duration) || 0;
    var clock = speechClock(data.speech, duration);

    words.forEach(function (word) { word.silent = false; });

    var said = [];
    (data.words || []).forEach(function (row) {
      var key = keyOf(row[0]);
      var start = Number(row[1]);
      var end = Number(row[2]);
      if (!key || !isFinite(start) || !isFinite(end)) return;
      // Two words aren't said at once: one that starts inside the word
      // before it really starts where that one ends.
      var previous = said[said.length - 1];
      if (previous && start < previous.end && previous.end < end) start = previous.end;
      said.push({ key: key, start: start, end: Math.max(end, start) });
    });

    var page = [];
    words.forEach(function (word, index) { if (word.key) page.push({ key: word.key, index: index }); });
    if (!page.length) return "";

    var anchors = said.length ? withoutStrays(anchorsFor(page, said), said) : [];
    if (anchors.length >= Math.max(2, page.length * MIN_MATCHED)) {
      words.forEach(function (word) { word.start = word.end = null; });
      words.forEach(function (word) { word.heard = null; });
      anchors.forEach(function (anchor) {
        var word = words[page[anchor.page].index];
        word.start = said[anchor.said].start;
        word.end = said[anchor.said].end;
        word.heard = said[anchor.said].key;      // which spoken word it was matched to
      });
      // Everything between two anchors shares the gap between them — but a
      // long run with nothing to anchor it is text the recording never
      // reads: the opening it skips, the ending it stops short of, a
      // paragraph the reader left out. Those words are never lit, so the
      // highlight doesn't crawl through words nobody is saying.
      var index = 0;
      var lastEnd = said[said.length - 1].end;
      var firstAnchored = -1, lastAnchored = -1;
      words.forEach(function (word, at) {
        if (word.start === null || word.start === undefined || !word.key) return;
        if (firstAnchored < 0) firstAnchored = at;
        lastAnchored = at;
      });
      while (index < words.length) {
        if (words[index].start !== null && words[index].start !== undefined) { index += 1; continue; }
        var from = index;
        while (index < words.length && (words[index].start === null || words[index].start === undefined)) index += 1;
        var run = words.slice(from, index);
        var spoken = run.filter(function (word) { return word.key; }).length;
        var atEdge = from < firstAnchored || index > lastAnchored + 1;
        // Only trust "the voice never says this" when the recording was
        // heard clearly. With a patchy transcript, a missing word means the
        // listener missed it, not that the reader skipped it — so those
        // words keep their place in the line rather than going dark.
        var trusted = Number(data.quality) >= TRUST_MATCH;
        if (trusted && (spoken > UNREAD_RUN || (atEdge && spoken >= EDGE_RUN))) {
          run.forEach(function (word) { word.silent = true; word.start = word.end = null; });
          continue;
        }
        var before = from > 0 ? words[from - 1].end : (clock ? clock.firstStart : 0);
        var after = index < words.length ? words[index].start : Math.max(lastEnd, duration || lastEnd);
        spread(run, before, Math.max(after, before), clock);
      }
      // A word spoken after a pause begins exactly when the voice comes
      // back, which the silences know more precisely than the transcript.
      if (data.speech && data.speech.length) {
        var openings = data.speech.map(function (run) { return Number(run[0]); });
        words.forEach(function (word, index) {
          var before = index > 0 ? words[index - 1] : null;
          if (before && word.start - before.end < AFTER_PAUSE) return;
          for (var i = 0; i < openings.length; i++) {
            if (Math.abs(openings[i] - word.start) <= SNAP_ONSET) { word.start = openings[i]; break; }
          }
        });
      }

      // Tidy the edges: always forward, never a word so short it flickers,
      // and never one still lit after the voice has moved on.
      var floor = 0;
      words.forEach(function (word, index) {
        if (word.silent) return;
        var next = words[index + 1];
        word.start = Math.max(word.start, floor);
        word.end = Math.max(word.end, word.start + LEAST_LIT);
        if (next && next.start > word.start) word.end = Math.min(word.end, next.start);
        // Nobody says one word for a second and a half. A word next to a
        // gap in the recording keeps its own length, and the gap stays a
        // gap, rather than the highlight sitting on it while nothing is said.
        word.end = Math.min(word.end, word.start + MOST_LIT);
        floor = word.start;
      });
      return "measured";
    }

    // The recording isn't reading this text — a different take, or the
    // wrong file. The words heard still say when the voice speaks and how
    // fast, which beats the silences, so the page is paced along them.
    var heard = said.length ? speechClock(said.map(function (word) { return [word.start, word.end]; }), duration) : null;
    if (heard || clock) {
      spreadSentences(words, heard || clock);
      return "speech";
    }
    return "";
  }

  function estimate(words, duration) {
    /* No measurement yet: spread the words across the recording's length,
       with the pauses a reader takes at punctuation. */
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
    // Only words with something to say are ever highlighted: a lone dash
    // or bullet just belongs to its neighbours.
    var track = [];

    function rebuildTrack() {
      track = words.filter(function (w) { return w.key && !w.silent; });
      words.forEach(function (w) { w.track = -1; });
      track.forEach(function (w, n) { w.track = n; });
    }

    rebuildTrack();
    if (track.length < 2) return;

    var on = remembered();
    var mode = "";             // "", "estimate" or "measured"
    var current = -1;
    var frame = 0;
    var clockTime = 0;
    var clockWall = 0;
    var userScrolled = 0;
    var lastFollow = 0;
    var latency = null;
    var audio = null;

    // A handle for measuring how closely the highlight tracks the voice.
    box.readAlong = { words: words, track: track, mode: function () { return mode; } };
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

    // Some recordings open with a greeting before the reading itself. Say so,
    // rather than leaving the words sitting there doing nothing.
    var skip = el("button", "ra-skip");
    skip.type = "button";
    skip.hidden = true;
    bar.appendChild(skip);

    function offerSkip() {
      var first = track[0];
      if (!mode || !first || first.start < INTRO_MIN) { skip.hidden = true; return; }
      var minutes = Math.floor(first.start / 60);
      var seconds = Math.round(first.start % 60);
      skip.textContent = "Reading starts at " + minutes + ":" + (seconds < 10 ? "0" : "") + seconds + " — skip to it";
      skip.hidden = false;
    }

    skip.addEventListener("click", function () {
      var first = track[0];
      if (!first) return;
      userScrolled = 0;
      media.currentTime = Math.max(0, first.start - TAP_PREROLL);
      if (media.paused) media.play().catch(function () { /* the browser may want a tap on the player */ });
    });

    // ---- the highlight that glides between words
    var marker = el("span", "ra-marker");
    marker.setAttribute("aria-hidden", "true");
    marker.appendChild(el("span", "ra-marker__fill"));
    textBox.appendChild(marker);
    var markerTop = null;

    var sentences = {};

    function groupSentences() {
      sentences = {};
      track.forEach(function (word) {
        (sentences[word.sentence] = sentences[word.sentence] || []).push(word.node);
      });
    }

    groupSentences();

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
        var wasTop = markerTop;
        place(track[current].node, glide, before ? track[current].start - before.start : 0);
        follow(track[current].node, wasTop === null || Math.abs(markerTop - wasTop) > 4);
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

    function follow(node, newLine) {
      /* Follow the line, not the word: the page moves once as the reading
         reaches a new line, and only when that line is drifting out of
         comfortable view. */
      if (!on || media.paused || Date.now() - userScrolled < USER_SCROLL_REST) return;
      var now = Date.now();
      if (now - lastFollow < 400) return;
      var rect = node.getBoundingClientRect();
      var view = window.innerHeight;
      var settled = rect.top > view * 0.16 && rect.bottom < view * 0.72;
      if (settled || (!newLine && rect.top > view * 0.05 && rect.bottom < view * 0.85)) return;
      lastFollow = now;
      window.scrollBy({ top: Math.round(rect.top - view * 0.38), behavior: calm.matches ? "auto" : "smooth" });
    }

    function litAt(time) {
      /* Which word is being said now. A word stays lit through the breath
         after it, but never through a real pause: in a silence — the
         greeting before a reading, a gap in the middle — nothing is lit,
         and the page waits with the reader instead of hanging on a word. */
      var index = indexAt(time);
      if (index < 0) return -1;
      var word = track[index];
      if (time <= word.end) return index;
      var next = track[index + 1];
      var until = next ? Math.min(next.start, word.end + LINGER) : word.end + LINGER;
      return time <= until ? index : -1;
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

    function heardOffset() {
      /* What comes out of the speakers is a moment behind the player's own
         clock — a few milliseconds wired, a fifth of a second over
         Bluetooth. The browser can say by how much, so the words can be
         lit when the sound actually arrives rather than when it is sent. */
      if (latency !== null) return latency;
      latency = 0;
      try {
        var Ctor = window.AudioContext || window.webkitAudioContext;
        if (Ctor) {
          audio = audio || new Ctor();
          var reported = audio.outputLatency || audio.baseLatency || 0;
          latency = Math.min(Math.max(reported, 0), 0.4);
        }
      } catch (error) { /* no Web Audio: assume none */ }
      return latency;
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
      var time = now() - heardOffset() + ANTICIPATE;
      paint(litAt(time), glide);
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
      rebuildTrack();
      groupSentences();
      box.classList.add("is-timed");
      box.classList.toggle("is-measured", newMode === "measured" || newMode === "speech");
      offerSkip();
      var keep = current;
      current = -1;
      if (track[keep]) track[keep].node.classList.remove("ra-w--on");
      if (!media.paused || media.currentTime > 0) start();
    }

    function useEstimate() {
      if (mode === "measured" || mode === "speech") return;
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
          if (data.status === "ready") {
            // Fill in the recording's own length if the player knows it.
            if (!data.duration && isFinite(media.duration)) data.duration = media.duration;
            var how = applyTiming(words, data);
            if (how) becomeTimed(how);
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
      // Two voices at once helps nobody: quieten the rest of the page.
      document.querySelectorAll("audio, video").forEach(function (other) {
        if (other !== media && !other.paused) other.pause();
      });
      latency = null;                       // re-read it: they may have switched to Bluetooth
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
