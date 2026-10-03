/* Scan & Listen. Page photos stay in this browser tab and are discarded
   once read. The text is saved as it changes (apps/learning_tools/
   scan_library.py) — to the school's library for school accounts — and its
   audio is made once on the server and played in the protected player,
   which can keep it offline inside the app but never hands over a file. */
(function () {
  "use strict";

  var page = document.querySelector(".bs-page");
  if (!page) return;

  var MAX_FILE_BYTES = 15 * 1024 * 1024;
  var MAX_TEXT_CHARS = 24000;
  var saveEndpoint = page.dataset.saveUrl;
  var searchEndpoint = page.dataset.searchUrl;
  var narrationReady = page.dataset.audioReady === "true";
  var readingId = page.dataset.reading || "";
  var readingMine = page.dataset.readingMine === "true";

  var cameraInput = page.querySelector("[data-camera-input]");
  var fileInput = page.querySelector("[data-file-input]");
  var transcript = page.querySelector("[data-transcript]");
  var status = page.querySelector("[data-status]");
  var error = page.querySelector("[data-error]");
  var processing = page.querySelector("[data-processing]");
  var progressBar = page.querySelector("[data-progress-bar]");
  var progressLabel = page.querySelector("[data-progress-label]");
  var processingLabel = page.querySelector("[data-processing-label]");
  var preview = page.querySelector("[data-preview]");
  var previewImage = page.querySelector("[data-preview-image]");
  var previewName = page.querySelector("[data-preview-name]");
  var wordCount = page.querySelector("[data-word-count]");
  var charCount = page.querySelector("[data-char-count]");
  var quality = page.querySelector("[data-quality]");
  var copyButton = page.querySelector("[data-copy]");
  var clearButton = page.querySelector("[data-clear]");
  var titleInput = page.querySelector("[data-title]");
  var savedNote = page.querySelector("[data-saved]");
  var generateAudioButton = page.querySelector("[data-generate-audio]");
  var audioProgress = page.querySelector("[data-audio-progress]");
  var audioNote = page.querySelector("[data-audio-note]");
  var audioError = page.querySelector("[data-audio-error]");
  var deleteButton = page.querySelector("[data-delete-reading]");
  var librarySearch = page.querySelector("[data-library-search]");
  var libraryList = page.querySelector("[data-library-list]");
  var csrfToken = page.querySelector("[data-speech-token] input[name='csrfmiddlewaretoken']").value;
  var library = page.dataset.library || "My readings";

  var ocrRequest = null;
  var currentPhotoUrl = "";
  var pageCount = 0;
  var isBusy = false;
  var saveTimer = null;
  var saving = null;
  var savedText = transcript.value;
  var savedTitle = titleInput ? titleInput.value : "";
  var polling = null;

  function setStatus(message) {
    status.textContent = message;
  }

  function setError(message) {
    error.textContent = message || "";
    error.hidden = !message;
  }

  function setBusy(busy) {
    isBusy = busy;
    processing.hidden = !busy;
    page.querySelector("[data-snap]").disabled = busy;
    page.querySelector("[data-upload]").disabled = busy;
    if (busy) {
      progressBar.value = 0;
      progressLabel.textContent = "0%";
    }
  }

  function setWorkflowStep(activeNumber) {
    Array.prototype.forEach.call(page.querySelectorAll(".bs-steps li"), function (step, index) {
      var number = index + 1;
      step.classList.toggle("is-active", number === activeNumber);
      step.classList.toggle("is-done", number < activeNumber);
      if (number === activeNumber) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    });
  }

  function countWords(text) {
    var matches = text.match(/[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*/gu);
    return matches ? matches.length : 0;
  }

  function updateTranscript() {
    var text = transcript.value;
    var words = countWords(text);
    wordCount.textContent = words + (words === 1 ? " word" : " words");
    charCount.textContent = text.length.toLocaleString() + " / 24,000";
    copyButton.disabled = !text.trim();
    clearButton.disabled = !text.trim() && !pageCount;
    if (generateAudioButton) generateAudioButton.disabled = !text.trim() || !narrationReady;
    setWorkflowStep(page.querySelector("[data-read-along]") ? 3 : (text.trim() ? 2 : 1));
  }

  // ---------------------------------------------------------- saving
  function say(text) { if (savedNote) savedNote.textContent = text; }

  function scheduleSave(now) {
    window.clearTimeout(saveTimer);
    if (!transcript.value.trim()) return;
    say("Saving…");
    saveTimer = window.setTimeout(saveNow, now ? 0 : 1500);
  }

  function saveNow() {
    var text = transcript.value;
    var title = titleInput ? titleInput.value : "";
    if (!text.trim()) return Promise.resolve(null);
    if (readingId && text === savedText && title === savedTitle) return Promise.resolve(readingId);
    if (saving) return saving.then(saveNow);
    saving = fetch(saveEndpoint, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ id: readingMine ? readingId : "", text: text, title: title })
    }).then(function (response) {
      return response.json().then(function (data) { return { ok: response.ok, data: data }; });
    }).then(function (result) {
      saving = null;
      if (!result.ok) throw new Error(result.data.error || "Couldn't save.");
      var data = result.data;
      var copied = readingId && String(data.id) !== String(readingId);
      readingId = String(data.id);
      readingMine = true;
      savedText = text; savedTitle = title;
      if (window.history && window.history.replaceState) window.history.replaceState(null, "", data.url);
      say((copied ? "✓ Saved as your own copy in " : "✓ Saved to ") + (data.where === "My readings" ? "My readings" : "the " + data.where));
      if (data.audio === "ready" && !data.audio_current && generateAudioButton) {
        generateAudioButton.hidden = false;
        generateAudioButton.querySelector("span").textContent = "Generate audio again";
      }
      return readingId;
    }).catch(function (problem) {
      saving = null;
      say("Not saved yet — " + (problem.message || "check your connection") + " We’ll try again when you edit.");
      return null;
    });
    return saving;
  }

  // ------------------------------------------------------------ audio
  function showAudioError(message) {
    audioError.textContent = message;
    audioError.hidden = !message;
  }

  function follow() {
    if (polling || !readingId) return;
    var delay = 2500;
    var tick = function () {
      fetch(saveEndpoint.replace("save/", readingId + "/status/"), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (state) {
          if (state.audio === "ready") { window.location.href = state.url; return; }
          if (state.audio === "failed") {
            polling = null;
            audioProgress.hidden = true;
            generateAudioButton.disabled = false;
            showAudioError(state.audio_error || "The audio couldn't be made. Please try again.");
            return;
          }
          delay = Math.min(delay + 1000, 6000);
          polling = window.setTimeout(tick, delay);
        })
        .catch(function () { polling = window.setTimeout(tick, 8000); });
    };
    polling = window.setTimeout(tick, delay);
  }

  function generateAudio() {
    if (!narrationReady || !transcript.value.trim()) return;
    generateAudioButton.disabled = true;
    showAudioError("");
    window.clearTimeout(saveTimer);
    saveNow().then(function (id) {
      if (!id) throw new Error("Your text couldn't be saved, so audio can't be made yet. Please try again.");
      return fetch(saveEndpoint.replace("save/", id + "/audio/"), {
        method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrfToken }
      });
    }).then(function (response) {
      return response.json().then(function (data) { return { ok: response.ok, data: data }; });
    }).then(function (result) {
      if (!result.ok) throw new Error(result.data.error || "The audio couldn't be started.");
      if (result.data.audio === "ready") { window.location.href = result.data.url; return; }
      audioProgress.hidden = false;
      setStatus("Making your audio. It will appear here when it’s ready.");
      follow();
    }).catch(function (problem) {
      generateAudioButton.disabled = false;
      showAudioError(problem.message);
    });
  }

  // ---------------------------------------------------------- library
  function renderLibrary(results) {
    libraryList.innerHTML = "";
    if (!results.length) {
      var none = document.createElement("li");
      none.className = "bs-library__empty";
      none.textContent = "No saved reading matches. Scan the page and it will be saved here.";
      libraryList.appendChild(none);
      return;
    }
    results.forEach(function (r) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = r.url;
      a.className = "bs-library__item" + (String(r.id) === String(readingId) ? " is-open" : "");
      a.innerHTML = '<span class="bs-library__icon' + (r.audio ? " has-audio" : "") + '" aria-hidden="true">' + (r.audio ? "♪" : "Aa") + '</span>' +
        '<span class="bs-library__text"><strong></strong><small></small><em></em></span>';
      a.querySelector("strong").textContent = r.title;
      a.querySelector("small").textContent = r.by + " · " + r.when + (r.audio ? " · audio ready" : " · no audio yet");
      a.querySelector("em").textContent = r.snippet;
      li.appendChild(a);
      libraryList.appendChild(li);
    });
  }

  var searchTimer = null;
  function searchLibrary() {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(function () {
      fetch(searchEndpoint + "?q=" + encodeURIComponent(librarySearch.value), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) { renderLibrary(data.results || []); })
        .catch(function () { /* the list stays as it was */ });
    }, 300);
  }

  function normalizeOcrText(text) {
    return String(text || "")
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n[ \t]+/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function showPhoto(file) {
    if (currentPhotoUrl) URL.revokeObjectURL(currentPhotoUrl);
    currentPhotoUrl = URL.createObjectURL(file);
    previewImage.src = currentPhotoUrl;
    previewName.textContent = file.name || "Camera photo";
    preview.hidden = false;
  }

  function removePhoto() {
    if (currentPhotoUrl) URL.revokeObjectURL(currentPhotoUrl);
    currentPhotoUrl = "";
    previewImage.removeAttribute("src");
    preview.hidden = true;
    cameraInput.value = "";
    fileInput.value = "";
  }

  function preprocessImage(file) {
    return new Promise(function (resolve, reject) {
      var imageUrl = URL.createObjectURL(file);
      var image = new Image();
      image.onload = function () {
        URL.revokeObjectURL(imageUrl);
        var longest = Math.max(image.naturalWidth, image.naturalHeight);
        if (!longest) {
          reject(new Error("This image could not be opened. Try taking the photo again."));
          return;
        }
        var scale = Math.min(1, 2600 / longest);
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
        var context = canvas.getContext("2d", { willReadFrequently: false });
        if (!context) {
          reject(new Error("This browser could not prepare the photo. Try a different browser or choose another image."));
          return;
        }
        if ("filter" in context) context.filter = "grayscale(1) contrast(1.12)";
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(function (blob) {
          canvas.width = 0;
          canvas.height = 0;
          if (blob) resolve(blob);
          else reject(new Error("This photo could not be prepared. Try another JPG or PNG image."));
        }, "image/jpeg", 0.93);
      };
      image.onerror = function () {
        URL.revokeObjectURL(imageUrl);
        reject(new Error("This image could not be opened. Choose a JPG, PNG or WebP photo."));
      };
      image.src = imageUrl;
    });
  }

  function recognizeOnServer(imageBlob) {
    return new Promise(function (resolve, reject) {
      var request = new XMLHttpRequest();
      var payload = new FormData();
      payload.append("image", imageBlob, "book-page.jpg");
      ocrRequest = request;
      request.open("POST", ocrEndpoint, true);
      request.responseType = "json";
      request.timeout = 100000;
      request.setRequestHeader("X-CSRFToken", csrfToken);
      request.upload.addEventListener("progress", function (event) {
        if (!event.lengthComputable) return;
        var percent = Math.max(1, Math.min(80, Math.round((event.loaded / event.total) * 80)));
        progressBar.value = percent;
        progressLabel.textContent = percent + "%";
        processingLabel.textContent = "Sending your compressed page securely…";
      });
      request.upload.addEventListener("load", function () {
        progressBar.value = 88;
        progressLabel.textContent = "88%";
        processingLabel.textContent = "Reading the page…";
      });
      request.addEventListener("load", function () {
        ocrRequest = null;
        var result = request.response;
        if (typeof result === "string") {
          try { result = JSON.parse(result); } catch (_ignored) { result = {}; }
        }
        if (request.status >= 200 && request.status < 300 && result) {
          progressBar.value = 100;
          progressLabel.textContent = "100%";
          resolve(result);
        } else {
          reject(new Error((result && result.error) || "Page recognition could not finish. Please try again."));
        }
      });
      request.addEventListener("error", function () {
        ocrRequest = null;
        reject(new Error("Could not reach page recognition. Check your connection and try again. Your photo was not saved."));
      });
      request.addEventListener("timeout", function () {
        ocrRequest = null;
        reject(new Error("Page recognition took too long. Try a sharper photo of one page."));
      });
      request.addEventListener("abort", function () {
        ocrRequest = null;
        reject(new Error("Page recognition was stopped."));
      });
      request.send(payload);
    });
  }

  function userFacingOcrError(problem) {
    var message = problem && problem.message ? problem.message : "The page could not be read.";
    if (/connection|network|failed to fetch|could not reach/i.test(message)) {
      return "Could not reach page recognition. Check your internet connection and try again. Your photo was not saved.";
    }
    if (/memory|allocation|out of/i.test(message)) {
      return "This photo is too large for the device to process. Try a closer, clearer photo of just one page.";
    }
    return message + " The photo was not saved. You can try again or type the words below.";
  }

  async function scanFile(file) {
    if (!file) return;
    setError("");
    quality.hidden = true;
    if (!file.type || file.type.indexOf("image/") !== 0 || !/image\/(jpeg|png|webp)/i.test(file.type)) {
      setError("Choose a JPG, PNG or WebP image. HEIC photos can be converted to JPG in your device’s photo settings.");
      setStatus("Choose a supported page photo to continue.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("This photo is larger than 15 MB. Choose a smaller image or reduce its size in your photo settings.");
      setStatus("Choose a smaller page photo to continue.");
      return;
    }
    if (transcript.value.length >= MAX_TEXT_CHARS) {
      setError("This reading has reached the 24,000 character limit. Clear some text before adding another page.");
      return;
    }

    showPhoto(file);
    setBusy(true);
    processingLabel.textContent = "Preparing your page…";
    setStatus("Compressing a page photo for secure recognition.");
    try {
      var preparedImage = await preprocessImage(file);
      processingLabel.textContent = "Sending your compressed page securely…";
      var result = await recognizeOnServer(preparedImage);
      var foundText = normalizeOcrText(result && result.text ? result.text : "");
      if (!foundText) {
        setError("We couldn’t find readable text in that photo. Move closer, use brighter light, and keep the page flat before trying again.");
        setStatus("No clear text was found. Your earlier pages are still here.");
        return;
      }
      var separator = transcript.value.trim() ? "\n\n" : "";
      if (transcript.value.length + separator.length + foundText.length > MAX_TEXT_CHARS) {
        setError("This page would take the text over the 24,000 character limit. Clear some text before adding it.");
        return;
      }
      transcript.value = transcript.value.trimEnd() + separator + foundText;
      pageCount += 1;
      updateTranscript();
      scheduleSave(true);
      quality.textContent = result.engine === "ai"
        ? "Page " + pageCount + " added · Read word for word from your photo · Glance over any names before listening."
        : "Page " + pageCount + " added · OCR confidence " + Math.round(result.confidence || 0) + "% · Please review names and punctuation.";
      quality.hidden = false;
      setStatus("Page " + pageCount + " added to your reading. You can snap another page or review the text now.");
      transcript.focus({ preventScroll: true });
    } catch (problem) {
      setError(userFacingOcrError(problem));
      setStatus("The photo was not saved. You can try again or type the words below.");
    } finally {
      setBusy(false);
      fileInput.value = "";
      cameraInput.value = "";
    }
  }

  function copyText() {
    var text = transcript.value;
    if (!text.trim()) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setStatus("Text copied to your clipboard.");
      }).catch(function () {
        setError("Your browser did not allow clipboard access. Select the text and copy it instead.");
      });
      return;
    }
    transcript.focus();
    transcript.select();
    try {
      document.execCommand("copy");
      setStatus("Text copied to your clipboard.");
    } catch (_problem) {
      setError("Select the text and copy it using your device’s copy command.");
    }
  }

  // Every photo, from the camera or the gallery, goes through the crop
  // tool first (static/js/book_scanner_capture.js), so only the page's
  // writing is sent to be read.
  function cropThenScan(file) {
    if (!file) return;
    var capture = window.DMPageCapture;
    if (!capture || !/^image\/(jpeg|png|webp)$/i.test(file.type || "")) { scanFile(file); return; }
    capture.crop(file).then(function (cropped) {
      if (cropped) scanFile(cropped);
      else setStatus("Cropping was cancelled. Take or choose a photo when you’re ready.");
    }).catch(function () { scanFile(file); });
  }

  page.querySelector("[data-snap]").addEventListener("click", function () {
    if (isBusy) return;
    var capture = window.DMPageCapture;
    if (!capture || !capture.cameraSupported()) { cameraInput.click(); return; }
    setError("");
    capture.camera().then(function (photo) {
      if (photo) cropThenScan(photo);
    }).catch(function () {
      // No camera could be opened in the page: use the device's own camera app.
      cameraInput.click();
    });
  });
  page.querySelector("[data-upload]").addEventListener("click", function () { if (!isBusy) fileInput.click(); });
  cameraInput.addEventListener("change", function () {
    var selected = cameraInput.files && cameraInput.files[0];
    cameraInput.value = "";
    cropThenScan(selected);
  });
  fileInput.addEventListener("change", function () {
    var selected = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    cropThenScan(selected);
  });
  page.querySelector("[data-remove-photo]").addEventListener("click", removePhoto);
  transcript.addEventListener("input", function () {
    updateTranscript();
    setError("");
    scheduleSave(false);
  });
  if (titleInput) titleInput.addEventListener("input", function () { scheduleSave(false); });
  copyButton.addEventListener("click", copyText);
  if (generateAudioButton) generateAudioButton.addEventListener("click", generateAudio);
  clearButton.addEventListener("click", function () {
    // Start a fresh reading; the saved one stays in Saved readings.
    window.location.href = window.location.pathname;
  });
  if (librarySearch) librarySearch.addEventListener("input", searchLibrary);
  if (deleteButton) deleteButton.addEventListener("click", function () {
    if (!window.confirm("Delete this reading and its audio for everyone? This can't be undone.")) return;
    fetch(deleteButton.dataset.url, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrfToken } })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (result) {
        if (!result.ok) throw new Error(result.data.error || "Couldn't delete it.");
        window.location.href = window.location.pathname;
      })
      .catch(function (problem) { showAudioError(problem.message); });
  });

  if (!narrationReady && audioNote) audioNote.hidden = false;
  if (page.dataset.audioStatus === "working") follow();
  updateTranscript();
  // Leaving with unsaved words: save them on the way out.
  window.addEventListener("pagehide", function () {
    if (ocrRequest) ocrRequest.abort();
    if (transcript.value.trim() && (transcript.value !== savedText || (titleInput && titleInput.value !== savedTitle))) {
      fetch(saveEndpoint, {
        method: "POST", credentials: "same-origin", keepalive: true,
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ id: readingMine ? readingId : "", text: transcript.value, title: titleInput ? titleInput.value : "" })
      });
    }
    if (currentPhotoUrl) URL.revokeObjectURL(currentPhotoUrl);
  }, { once: true });
})();
