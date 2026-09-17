/* Quick Words live search.

   As you type, words from the library that match appear straight
   away. If the word isn't in the library, pressing Enter looks it up
   and takes you to it — added for everyone.

   Two things keep it fast and correct while typing quickly:
   an in-flight request is cancelled the moment you type another
   letter, so a slow answer for "ac" can never overwrite the answer for
   "ach"; and every answer is remembered, so backspacing is instant.

   Everything shown is written with textContent, never innerHTML —
   some of these entries were written by an AI and are not trusted as
   markup. Without JavaScript the plain search form still works. */

(function () {
  "use strict";

  var form = document.querySelector("[data-live-search]");
  if (!form) return;

  var input = form.querySelector("input[name='q']");
  var list = form.querySelector(".qw-suggest");
  var csrf = form.querySelector("input[name='csrfmiddlewaretoken']");
  var suggestUrl = form.dataset.suggestUrl;
  var lookupUrl = form.dataset.lookupUrl;

  var answers = {};          // query -> server response, so repeats are instant
  var pending = null;        // AbortController for the request in flight
  var timer = null;
  var latest = null;         // the response currently shown
  var active = -1;           // highlighted row
  var looking = false;

  // ---- drawing the dropdown ------------------------------------------

  function open() {
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function rows() {
    return list.querySelectorAll("[data-row]");
  }

  function highlight(index) {
    var all = rows();
    all.forEach(function (row) { row.classList.remove("qw-suggest__row--active"); });
    active = index;
    if (index >= 0 && all[index]) {
      all[index].classList.add("qw-suggest__row--active");
      input.setAttribute("aria-activedescendant", all[index].id);
      all[index].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  /* The word with the typed letters picked out, built from text nodes. */
  function markedWord(word, query) {
    var fragment = document.createDocumentFragment();
    var at = word.toLowerCase().indexOf(query.toLowerCase());
    if (at < 0 || !query) {
      fragment.appendChild(document.createTextNode(word));
      return fragment;
    }
    fragment.appendChild(document.createTextNode(word.slice(0, at)));
    var mark = document.createElement("mark");
    mark.textContent = word.slice(at, at + query.length);
    fragment.appendChild(mark);
    fragment.appendChild(document.createTextNode(word.slice(at + query.length)));
    return fragment;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function draw(data) {
    latest = data;
    list.replaceChildren();
    active = -1;

    data.results.forEach(function (item, index) {
      var row = el("li", "qw-suggest__row");
      row.id = "qw-suggest-" + index;
      row.setAttribute("role", "option");
      row.dataset.row = "word";
      row.dataset.url = item.url;

      var top = el("span", "qw-suggest__top");
      var word = el("span", "qw-suggest__word");
      word.appendChild(markedWord(item.word, data.query));
      top.appendChild(word);
      if (item.ipa) top.appendChild(el("span", "qw-suggest__ipa", item.ipa));
      row.appendChild(top);
      if (item.definition) row.appendChild(el("span", "qw-suggest__def", item.definition));

      row.addEventListener("mousedown", function (event) {
        event.preventDefault();          // keep focus in the box
        window.location.href = item.url;
      });
      list.appendChild(row);
    });

    if (data.can_lookup) {
      var action = el("li", "qw-suggest__row qw-suggest__row--lookup");
      action.id = "qw-suggest-lookup";
      action.setAttribute("role", "option");
      action.dataset.row = "lookup";
      action.appendChild(el("span", "qw-suggest__lookup-icon", "✨"));
      var label = el("span", "qw-suggest__lookup-label");
      label.appendChild(document.createTextNode(
        data.results.length ? "Not what you meant? Look up " : "Look up "
      ));
      label.appendChild(el("strong", "", "“" + data.query + "”"));
      label.appendChild(document.createTextNode(" and add it"));
      action.appendChild(label);
      action.appendChild(el("span", "qw-suggest__hint", "Enter"));
      action.addEventListener("mousedown", function (event) {
        event.preventDefault();
        lookUp(data.query);
      });
      list.appendChild(action);
    }

    if (!data.results.length && !data.can_lookup) {
      list.appendChild(el("li", "qw-suggest__note",
        "Type a single word to look it up, or part of a meaning to search."));
    }

    // Start on the closest match so Enter does the obvious thing.
    if (data.results.length || data.can_lookup) highlight(0);
    open();
  }

  function showStatus(text, kind) {
    list.replaceChildren(el("li", "qw-suggest__status qw-suggest__status--" + kind, text));
    open();
  }

  // ---- fetching suggestions ------------------------------------------

  function fetchSuggestions(query) {
    if (answers[query]) {
      draw(answers[query]);
      return;
    }
    if (pending) pending.abort();
    pending = new AbortController();

    fetch(suggestUrl + "?q=" + encodeURIComponent(query), {
      signal: pending.signal,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        answers[query] = data;
        // Ignore an answer for letters the box no longer holds.
        if (input.value.trim() === query) draw(data);
      })
      .catch(function (error) {
        if (error.name !== "AbortError") close();
      });
  }

  input.addEventListener("input", function () {
    var query = input.value.trim();
    clearTimeout(timer);
    if (!query) {
      if (pending) pending.abort();
      close();
      return;
    }
    // Cached answers need no pause at all; new ones wait a beat so a
    // burst of typing sends one request, not one per letter.
    timer = setTimeout(function () { fetchSuggestions(query); }, answers[query] ? 0 : 110);
  });

  // ---- looking up a new word -----------------------------------------

  function lookUp(query) {
    if (looking) return;
    looking = true;
    showStatus("Looking up “" + query + "”…", "busy");

    var body = new URLSearchParams();
    body.append("word", query);

    fetch(lookupUrl, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": csrf ? csrf.value : "",
      },
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && result.data.url) {
          showStatus(
            result.data.created
              ? "Added “" + result.data.word + "” — opening it…"
              : "Found “" + result.data.word + "” — opening it…",
            "done"
          );
          window.location.href = result.data.url;
          return;
        }
        looking = false;
        showStatus(result.data.message || "That word couldn't be looked up.", "error");
      })
      .catch(function () {
        looking = false;
        showStatus("Couldn't reach the server — check your connection and try again.", "error");
      });
  }

  // ---- keyboard and submit -------------------------------------------

  function activate(index) {
    var row = rows()[index];
    if (!row) return false;
    if (row.dataset.row === "lookup") {
      lookUp(input.value.trim());
    } else {
      window.location.href = row.dataset.url;
    }
    return true;
  }

  input.addEventListener("keydown", function (event) {
    var count = rows().length;
    if (event.key === "ArrowDown") {
      if (list.hidden) return;
      event.preventDefault();
      highlight(count ? (active + 1) % count : -1);
    } else if (event.key === "ArrowUp") {
      if (list.hidden) return;
      event.preventDefault();
      highlight(count ? (active - 1 + count) % count : -1);
    } else if (event.key === "Escape") {
      close();
    }
  });

  form.addEventListener("submit", function (event) {
    var query = input.value.trim();
    if (!query) return;

    // The dropdown is up to date for exactly this query: act on it.
    if (latest && latest.query === query && !list.hidden && active >= 0) {
      event.preventDefault();
      activate(active);
      return;
    }
    // Pressed Enter before suggestions arrived, and it's a new word.
    if (latest && latest.query === query && !latest.results.length && latest.can_lookup) {
      event.preventDefault();
      lookUp(query);
    }
    // Otherwise let the normal search run and filter the grid.
  });

  input.addEventListener("blur", function () {
    // Leave a moment for a click on a row to register first.
    setTimeout(function () { if (!looking) close(); }, 150);
  });

  input.addEventListener("focus", function () {
    var query = input.value.trim();
    if (query && answers[query]) draw(answers[query]);
  });
})();
