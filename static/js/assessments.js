/* Taking an assessment.

   The page works as a plain form without this file. With it:
   - progress updates as questions are answered
   - answers are autosaved, so a dropped connection or closed tab loses
     nothing (and the server, not this script, decides when time is up)
   - the countdown submits the paper when it reaches zero
   - practice quizzes check each answer on the spot
   - transcription answers get a tap-to-type phonemic keyboard

   Autosave never learns whether an answer is right. Only a practice
   "check" asks, and that locks the answer first. */

(function () {
  "use strict";

  var paper = document.getElementById("as-paper");
  if (!paper) return;

  var csrf = paper.querySelector("input[name='csrfmiddlewaretoken']").value;
  var mode = paper.dataset.mode;
  var total = parseInt(paper.dataset.total, 10) || 0;
  var saveStatus = paper.querySelector("[data-save-status]");
  var submitting = false;

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body),
    }).then(function (response) {
      return response.json().then(function (data) { return { status: response.status, data: data }; });
    });
  }

  function valueOf(card) {
    var checked = card.querySelector("input[type=radio]:checked");
    if (checked) return checked.value;
    var text = card.querySelector("input[type=text]");
    if (text) return text.value;
    var file = card.querySelector("input[type=file]");
    return file && file.files.length ? "recording" : "";
  }

  // ---- progress ---------------------------------------------------------

  function updateProgress() {
    var cards = paper.querySelectorAll(".as-q");
    var answered = Array.prototype.filter.call(cards, function (card) {
      return valueOf(card).trim() !== "";
    }).length;
    paper.querySelector("[data-answered]").textContent = answered;
    paper.querySelector("[data-progress-fill]").style.width = (total ? (answered * 100) / total : 0) + "%";
    return answered;
  }

  // ---- autosave ---------------------------------------------------------

  var timers = {};

  function showSave(text, kind) {
    if (!saveStatus) return;
    saveStatus.textContent = text;
    saveStatus.className = "as-bar__saved" + (kind ? " as-bar__saved--" + kind : "");
  }

  function autosave(card) {
    var type = card.dataset.type;
    if (type === "speak" || card.classList.contains("as-q--checked")) return;
    var id = card.dataset.question;
    clearTimeout(timers[id]);
    timers[id] = setTimeout(function () {
      showSave("Saving…");
      post(paper.dataset.saveUrl, { question: id, given: valueOf(card) })
        .then(function (result) {
          if (result.data.expired) {
            showSave("Time's up — submitting…", "warn");
            submitPaper(true);
          } else if (result.data.saved) {
            showSave("All answers saved", "ok");
          }
        })
        .catch(function () { showSave("Offline — your answers will send when you submit", "warn"); });
    }, type === "choice" || type === "listen" ? 0 : 700);
  }

  paper.addEventListener("input", function (event) {
    var card = event.target.closest(".as-q");
    if (!card) return;
    updateProgress();
    if (event.target.type !== "file") autosave(card);
  });
  paper.addEventListener("change", function (event) {
    var card = event.target.closest(".as-q");
    if (!card) return;
    updateProgress();
    if (event.target.type === "radio") autosave(card);
  });

  // ---- practice: check an answer now -----------------------------------

  function lock(card) {
    card.querySelectorAll("input[type=radio]").forEach(function (input) { input.disabled = true; });
    card.querySelectorAll("input[type=text]").forEach(function (input) { input.readOnly = true; });
    var keyboard = card.querySelector(".as-ipa");
    if (keyboard) keyboard.remove();
  }

  paper.addEventListener("click", function (event) {
    var button = event.target.closest("[data-check]");
    if (!button) return;
    var card = button.closest(".as-q");
    var feedback = card.querySelector("[data-feedback]");
    var given = valueOf(card);
    if (!given.trim()) {
      feedback.hidden = false;
      feedback.replaceChildren(el("p", "as-feedback__why", "Choose or type an answer first."));
      return;
    }
    button.disabled = true;
    button.textContent = "Checking…";

    post(paper.dataset.checkUrl, { question: card.dataset.question, given: given })
      .then(function (result) {
        if (result.status !== 200) {
          button.disabled = false;
          button.textContent = "Check answer";
          feedback.hidden = false;
          feedback.replaceChildren(el("p", "as-feedback__why", result.data.error || "Couldn't check that."));
          return;
        }
        var data = result.data;
        lock(card);
        button.remove();
        card.classList.add("as-q--checked", data.correct ? "as-q--right" : "as-q--wrong");
        feedback.hidden = false;
        feedback.replaceChildren(
          el("p", "as-feedback__verdict",
             data.correct ? "✓ Correct" : "✗ Not quite — the answer is " + data.answer)
        );
        if (data.explanation) feedback.appendChild(el("p", "as-feedback__why", data.explanation));
      })
      .catch(function () {
        button.disabled = false;
        button.textContent = "Check answer";
      });
  });

  function el(tag, className, text) {
    var node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    return node;
  }

  // ---- phonemic keyboard ------------------------------------------------

  paper.addEventListener("click", function (event) {
    var key = event.target.closest("[data-ipa-key], [data-ipa-backspace]");
    if (!key) return;
    var input = key.closest(".as-q").querySelector("[data-ipa-input]");
    if (!input || input.readOnly) return;

    var start = input.selectionStart == null ? input.value.length : input.selectionStart;
    var end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
    if (key.hasAttribute("data-ipa-backspace")) {
      if (start === end && start > 0) start -= 1;
      input.value = input.value.slice(0, start) + input.value.slice(end);
      input.setSelectionRange(start, start);
    } else {
      var symbol = key.dataset.ipaKey;
      input.value = input.value.slice(0, start) + symbol + input.value.slice(end);
      input.setSelectionRange(start + symbol.length, start + symbol.length);
    }
    input.focus();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

  // ---- timer ------------------------------------------------------------

  var timer = paper.querySelector("[data-timer]");
  if (timer && paper.dataset.secondsLeft) {
    // Count against a fixed end time rather than decrementing, so a busy
    // or backgrounded tab can't make the clock drift.
    var endsAt = Date.now() + parseInt(paper.dataset.secondsLeft, 10) * 1000;
    var clock = timer.querySelector("[data-clock]");

    var tick = function () {
      var left = Math.max(0, Math.round((endsAt - Date.now()) / 1000));
      var minutes = Math.floor(left / 60);
      var seconds = left % 60;
      clock.textContent = minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
      timer.classList.toggle("as-timer--low", left <= 60);
      if (left === 0) {
        clearInterval(interval);
        showSave("Time's up — submitting…", "warn");
        submitPaper(true);
      }
    };
    var interval = setInterval(tick, 1000);
    tick();
  }

  // ---- submitting -------------------------------------------------------

  function submitPaper(automatic) {
    if (submitting) return;
    submitting = true;
    var button = paper.querySelector("[data-submit]");
    button.disabled = true;
    button.textContent = automatic ? "Submitting…" : "Sending…";
    HTMLFormElement.prototype.submit.call(paper);
  }

  paper.addEventListener("submit", function (event) {
    event.preventDefault();
    if (submitting) return;
    var unanswered = total - updateProgress();
    if (unanswered > 0) {
      var ok = window.confirm(
        "You have " + unanswered + " unanswered question" + (unanswered === 1 ? "" : "s") +
        ". Submit anyway? You can't change your answers afterwards."
      );
      if (!ok) return;
    }
    submitPaper(false);
  });

  updateProgress();
})();
