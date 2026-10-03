/* Lesson Notes to Audio (apps/lesson_audio).

   The hub: the three ways to start a note (tabs), the upload drop zone, and
   a "working" message while a note is read or written.

   A note: playback speed and a jump-to-section outline for the read-along
   (static/js/read_along.js does the highlighting), audio made in the
   background with the page following its progress, and the key words —
   hear one, hear them all, or practise one with the microphone and be told
   how it sounded. */
(function () {
  "use strict";

  var csrf = (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";

  function words(text) {
    var n = (text.trim().match(/\S+/g) || []).length;
    return n + " word" + (n === 1 ? "" : "s") + " · about " + Math.max(1, Math.round(n / 150)) + " min to read";
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-confirm]");
    if (button && !window.confirm(button.getAttribute("data-confirm"))) event.preventDefault();
  });

  // ---------------------------------------------------------------- counters
  document.querySelectorAll("[data-la-count]").forEach(function (area) {
    var form = area.closest("form");
    var out = form && form.querySelector("[data-la-counter]");
    if (!out) return;
    var update = function () { out.textContent = words(area.value); };
    area.addEventListener("input", update);
    update();
  });

  // ------------------------------------------------- busy message on submit
  var busyBox = document.querySelector("[data-la-busy-box]");
  document.querySelectorAll("form[data-la-busy]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector("[type=submit]");
      if (button) { button.disabled = true; button.classList.add("is-busy"); }
      if (busyBox) {
        busyBox.querySelector("[data-la-busy-text]").textContent = form.dataset.laBusy;
        busyBox.hidden = false;
      }
    });
  });

  // --------------------------------------------------------------- the hub
  var hub = document.querySelector("[data-la-hub]");
  if (hub) {
    var tabs = hub.querySelectorAll("[data-la-tab]");
    var show = function (name) {
      tabs.forEach(function (tab) { tab.setAttribute("aria-selected", String(tab.dataset.laTab === name)); });
      hub.querySelectorAll("[data-la-panel]").forEach(function (panel) { panel.hidden = panel.dataset.laPanel !== name; });
    };
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { show(tab.dataset.laTab); });
      tab.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        var next = tabs[(i + step + tabs.length) % tabs.length];
        next.focus(); show(next.dataset.laTab);
      });
    });
    var selected = hub.querySelector("[data-la-tab][aria-selected=true]");
    show(selected ? selected.dataset.laTab : "write");

    var drop = hub.querySelector("[data-la-drop]");
    var input = hub.querySelector("[data-la-files]");
    var list = hub.querySelector("[data-la-filelist]");
    var listFiles = function () {
      list.innerHTML = "";
      Array.prototype.forEach.call(input.files, function (file) {
        var li = document.createElement("li");
        li.textContent = file.name + " · " + (file.size > 1048576 ? (file.size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(file.size / 1024)) + " KB");
        list.appendChild(li);
      });
      list.hidden = !input.files.length;
    };
    if (drop && input) {
      input.addEventListener("change", listFiles);
      ["dragenter", "dragover"].forEach(function (name) {
        drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.add("is-over"); });
      });
      ["dragleave", "drop"].forEach(function (name) {
        drop.addEventListener(name, function () { drop.classList.remove("is-over"); });
      });
      drop.addEventListener("drop", function (event) {
        event.preventDefault();
        if (event.dataTransfer && event.dataTransfer.files.length) {
          input.files = event.dataTransfer.files;
          listFiles();
        }
      });
    }
  }

  // --------------------------------------------------------------- a note
  var page = document.querySelector("[data-la-note]");
  if (!page) return;

  // The note saves itself as it's typed (a moment after the last key),
  // and once more on the way out if anything is still unsaved.
  var editForm = page.querySelector("[data-la-edit-form]");
  var savedBadge = page.querySelector("[data-la-saved]");
  var dirty = false, saveTimer = null, saving = null;

  function saveNote() {
    if (!editForm || !dirty) return Promise.resolve(true);
    if (saving) return saving.then(saveNote);
    dirty = false;
    savedBadge.textContent = "Saving…";
    savedBadge.className = "la-autosave is-saving";
    saving = fetch(editForm.action, {
      method: "POST", body: new FormData(editForm), credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        saving = null;
        if (!result.ok) throw new Error(result.data.error || "Couldn't save.");
        savedBadge.textContent = "✓ All changes saved";
        savedBadge.className = "la-autosave";
        var stale = page.querySelector("[data-la-stale]");
        if (stale) stale.hidden = result.data.audio_current;
        var wordsStale = page.querySelector("[data-la-words-stale]");
        if (wordsStale) wordsStale.hidden = result.data.keywords_current;
        var count = page.querySelector("[data-la-wordcount]");
        if (count) count.textContent = result.data.words + " words · about " + result.data.minutes + " min to read";
        return true;
      })
      .catch(function (problem) {
        saving = null;
        dirty = true;
        savedBadge.textContent = "Not saved — " + problem.message + " Retrying…";
        savedBadge.className = "la-autosave is-error";
        saveTimer = window.setTimeout(saveNote, 5000);
        return false;
      });
    return saving;
  }

  if (editForm) {
    editForm.addEventListener("input", function () {
      dirty = true;
      savedBadge.textContent = "Saving…";
      savedBadge.className = "la-autosave is-saving";
      window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(saveNote, 1200);
    });
    editForm.addEventListener("submit", function (event) { event.preventDefault(); saveNote(); });
    window.addEventListener("pagehide", function () {
      if (!dirty) return;
      fetch(editForm.action, { method: "POST", body: new FormData(editForm), credentials: "same-origin", keepalive: true,
                               headers: { "X-Requested-With": "XMLHttpRequest" } });
    });
  }

  var printButton = page.querySelector("[data-la-print]");
  if (printButton) printButton.addEventListener("click", function () { window.print(); });

  // Speed.
  var audio = page.querySelector(".la-player video, [data-la-audio]");
  page.querySelectorAll("[data-la-speed]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!audio) return;
      audio.playbackRate = Number(button.dataset.laSpeed);
      page.querySelectorAll("[data-la-speed]").forEach(function (b) { b.setAttribute("aria-pressed", String(b === button)); });
    });
  });

  // Jump to a section: the headings of the note, as chips.
  var outline = page.querySelector("[data-la-outline]");
  var reading = page.querySelector(".la-read");
  if (outline && reading) {
    var headings = reading.querySelectorAll("h3");
    if (headings.length > 1) {
      headings.forEach(function (heading) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.textContent = heading.textContent.replace(/:.*$/, "").trim().slice(0, 34);
        chip.addEventListener("click", function () {
          var first = heading.querySelector(".ra-w");
          if (first) first.click();          // read_along.js seeks to a tapped word
          heading.scrollIntoView({ behavior: "smooth", block: "center" });
        });
        outline.appendChild(chip);
      });
      outline.hidden = false;
    }
  }

  // ---- background jobs: start the audio, and follow both jobs until done
  var statusUrl = page.dataset.statusUrl;
  var audioForm = page.querySelector("[data-la-audio-form]");
  var audioProgress = page.querySelector("[data-la-audio-progress]");
  var audioError = page.querySelector("[data-la-audio-error]");
  var generate = page.querySelector("[data-la-generate]");
  var wordsProgress = page.querySelector("[data-la-words-progress]");
  var waiting = { audio: page.dataset.audioStatus === "working", keywords: page.dataset.keywordsStatus === "working" };
  var polling = null;

  function poll() {
    if (polling) return;
    var delay = 2500;
    var tick = function () {
      fetch(statusUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (state) {
          var reload = false;
          if (waiting.audio && state.audio !== "working") reload = true;
          if (waiting.keywords && state.keywords !== "working") reload = true;
          if (reload) {
            // Save anything still being typed, then show the new audio or words.
            window.clearTimeout(saveTimer);
            saveNote().then(function () { window.location.reload(); });
            return;
          }
          delay = Math.min(delay + 1000, 6000);
          polling = window.setTimeout(tick, delay);
        })
        .catch(function () { polling = window.setTimeout(tick, 8000); });
    };
    polling = window.setTimeout(tick, delay);
  }
  if (waiting.audio || waiting.keywords) poll();

  if (audioForm) {
    audioForm.addEventListener("submit", function (event) {
      event.preventDefault();
      generate.disabled = true;
      audioError.hidden = true;
      window.clearTimeout(saveTimer);
      saveNote().then(function () { return fetch(audioForm.action, {
        method: "POST", body: new FormData(audioForm), credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
      }); })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (result) {
          if (!result.ok) throw new Error(result.data.error || "The audio couldn't be started.");
          audioProgress.hidden = false;
          waiting.audio = true;
          poll();
        })
        .catch(function (error) {
          audioError.textContent = error.message;
          audioError.hidden = false;
          generate.disabled = false;
        });
    });
  }

  // ---------------------------------------------------------- key words
  function stopAll() {
    page.querySelectorAll("[data-la-word-audio]").forEach(function (a) { a.pause(); a.currentTime = 0; });
    page.querySelectorAll(".la-word.is-playing").forEach(function (li) { li.classList.remove("is-playing"); });
  }
  function playWord(li) {
    var sound = li.querySelector("[data-la-word-audio]");
    if (!sound) return Promise.resolve();
    stopAll();
    li.classList.add("is-playing");
    return new Promise(function (resolve) {
      var done = function () { li.classList.remove("is-playing"); sound.removeEventListener("ended", done); resolve(); };
      sound.addEventListener("ended", done);
      sound.play().catch(done);
    });
  }
  page.querySelectorAll("[data-la-play]").forEach(function (button) {
    button.addEventListener("click", function () { playWord(button.closest("[data-la-word]")); });
  });

  var playAll = page.querySelector("[data-la-playall]");
  if (playAll) {
    var running = false;
    playAll.addEventListener("click", function () {
      if (running) { running = false; stopAll(); playAll.classList.remove("is-on"); return; }
      running = true;
      playAll.classList.add("is-on");
      var items = Array.prototype.slice.call(page.querySelectorAll("[data-la-word]"));
      var next = function (i) {
        if (!running || i >= items.length) { running = false; playAll.classList.remove("is-on"); return; }
        items[i].scrollIntoView({ behavior: "smooth", block: "nearest" });
        playWord(items[i]).then(function () { window.setTimeout(function () { next(i + 1); }, 700); });
      };
      next(0);
    });
  }

  // Practise: record the teacher saying the word, and say how it sounded.
  var recorder = null;
  var MAX_SECONDS = 5;

  function setResult(li, text, kind) {
    var out = li.querySelector("[data-la-result]");
    out.textContent = text;
    out.className = "la-word__result" + (kind ? " is-" + kind : "");
  }

  function mimeType() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find(function (t) { return MediaRecorder.isTypeSupported(t); }) || "";
  }

  function send(li, blob, type) {
    var form = new FormData();
    var ext = /mp4/.test(type) ? "mp4" : /ogg/.test(type) ? "ogg" : "webm";
    form.append("audio", blob, "word." + ext);
    setResult(li, "Listening…", "wait");
    return fetch(li.dataset.practiseUrl, {
      method: "POST", body: form, credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        var data = result.data;
        if (!result.ok) throw new Error(data.error || "That couldn't be checked.");
        if (data.ok) {
          li.classList.add("is-mastered");
          setResult(li, "Well said! ✓", "ok");
        } else {
          var text = data.heard ? "We heard “" + data.heard + "”. " : "";
          text += (data.tips && data.tips.length) ? data.tips.join(" ") : "Listen again, then try once more.";
          setResult(li, text, "try");
        }
        if (typeof data.mastered_total === "number") {
          var count = page.querySelector("[data-la-mastered]");
          var bar = page.querySelector("[data-la-mastery-bar]");
          if (count) count.textContent = data.mastered_total;
          if (bar && data.total) bar.style.width = Math.round(data.mastered_total * 100 / data.total) + "%";
        }
      })
      .catch(function (error) { setResult(li, error.message, "try"); });
  }

  function stopRecording() {
    if (recorder && recorder.state === "recording") recorder.stop();
  }

  page.querySelectorAll("[data-la-practise]").forEach(function (button) {
    button.addEventListener("click", function () {
      var li = button.closest("[data-la-word]");
      if (recorder && recorder.state === "recording") { stopRecording(); return; }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
        setResult(li, "This browser can't record. Try Chrome, Edge or Safari.", "try");
        return;
      }
      stopAll();
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        var type = mimeType();
        var chunks = [];
        recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
        var label = button.querySelector("span");
        var timer = null;
        recorder.ondataavailable = function (event) { if (event.data && event.data.size) chunks.push(event.data); };
        recorder.onstop = function () {
          window.clearTimeout(timer);
          stream.getTracks().forEach(function (t) { t.stop(); });
          button.classList.remove("is-recording");
          label.textContent = "Practise";
          var blob = new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" });
          recorder = null;
          if (blob.size < 800) { setResult(li, "That was too short — press Practise, then say the word.", "try"); return; }
          button.disabled = true;
          send(li, blob, blob.type).then(function () { button.disabled = false; });
        };
        recorder.start();
        button.classList.add("is-recording");
        label.textContent = "Stop";
        setResult(li, "Say “" + li.querySelector(".la-word__name strong").textContent + "” now…", "rec");
        timer = window.setTimeout(stopRecording, MAX_SECONDS * 1000);
      }).catch(function () {
        setResult(li, "Allow the microphone (the icon in the address bar) to practise.", "try");
      });
    });
  });

  // Jump to the editor from the header.
  var gotoEdit = page.querySelector("[data-la-goto-edit]");
  if (gotoEdit) gotoEdit.addEventListener("click", function () {
    window.setTimeout(function () { var area = page.querySelector("[data-la-body]"); if (area) area.focus({ preventScroll: true }); }, 400);
  });
})();
