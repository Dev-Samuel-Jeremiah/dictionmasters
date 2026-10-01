/* Scan & Listen. Page photos stay in this browser tab; narration uses ElevenLabs. */
(function () {
  "use strict";

  var page = document.querySelector(".bs-page");
  if (!page) return;

  var MAX_FILE_BYTES = 15 * 1024 * 1024;
  var MAX_TEXT_CHARS = 24000;
  var AUDIO_CHUNK_CHARS = 4000;
  var AUDIO_GENERATION_CONCURRENCY = 3;
  var ocrEndpoint = page.dataset.ocrUrl;
  var audioEndpoint = page.dataset.audioUrl;
  var narrationReady = page.dataset.audioReady === "true";

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
  var downloadButton = page.querySelector("[data-download]");
  var clearButton = page.querySelector("[data-clear]");
  var playButton = page.querySelector("[data-play]");
  var generateAudioButton = page.querySelector("[data-generate-audio]");
  var stopButton = page.querySelector("[data-stop]");
  var downloadAudioButton = page.querySelector("[data-download-audio]");
  var speedInput = page.querySelector("[data-speed]");
  var speedLabel = page.querySelector("[data-speed-label]");
  var player = page.querySelector("[data-player]");
  var playerTitle = page.querySelector("[data-player-title]");
  var playerSub = page.querySelector("[data-player-sub]");
  var audioDownloadStatus = page.querySelector("[data-audio-download-status]");
  var audioNote = page.querySelector("[data-audio-note]");
  var audioError = page.querySelector("[data-audio-error]");
  var csrfToken = page.querySelector("[data-speech-token] input[name='csrfmiddlewaretoken']").value;

  var ocrRequest = null;
  var currentPhotoUrl = "";
  var pageCount = 0;
  var isBusy = false;
  var speechChunks = [];
  var speechIndex = 0;
  var isSpeaking = false;
  var isPaused = false;
  var isPreparingAudio = false;
  var activeAudio = null;
  var activeAudioUrl = "";
  var audioRequests = [];
  var generationRun = 0;
  var narrationCacheText = "";
  var narrationParts = [];

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
    downloadButton.disabled = !text.trim();
    clearButton.disabled = !text.trim() && !pageCount;
    speedInput.disabled = !narrationReady;
    if (!isSpeaking) setWorkflowStep(text.trim() ? 2 : 1);
    if (words) {
      var minutes = Math.max(1, Math.ceil(words / 150));
      playerSub.textContent = words.toLocaleString() + " words · about " + minutes + " min";
      if (!isSpeaking && !isPaused) {
        playerTitle.textContent = hasCompleteNarration() ? "Complete audio ready" : (isPreparingAudio ? "Preparing your audio…" : "Ready to generate audio");
      }
    } else {
      playerSub.textContent = "Scan a page or add text to get started";
      if (!isSpeaking && !isPaused) playerTitle.textContent = "Ready when you are";
    }
    updateAudioControls();
  }

  function hasCompleteNarration() {
    var text = transcript.value.trim();
    return !!text && narrationCacheText === text && narrationParts.length > 0 && narrationParts.filter(Boolean).length === narrationParts.length;
  }

  function updateAudioControls() {
    var generatedCount = narrationParts.filter(Boolean).length;
    var ready = hasCompleteNarration();
    downloadAudioButton.disabled = !ready;
    generateAudioButton.hidden = ready;
    generateAudioButton.disabled = !transcript.value.trim() || !narrationReady || isPreparingAudio;
    var progress = narrationParts.length ? Math.round((generatedCount / narrationParts.length) * 100) : 0;
    generateAudioButton.textContent = isPreparingAudio
      ? "Generating audio · " + progress + "%"
      : (generatedCount ? "Continue generation" : "Generate audio");
    playButton.disabled = !transcript.value.trim() || !narrationReady || !ready || isPreparingAudio;
    stopButton.disabled = !isSpeaking && !isPreparingAudio;
    stopButton.setAttribute("aria-label", isPreparingAudio ? "Cancel audio generation" : "Stop reading");
    if (ready) {
      audioDownloadStatus.textContent = "Complete audio is ready to play or download";
    } else if (isPreparingAudio) {
      audioDownloadStatus.textContent = "Preparing audio · " + generatedCount + " of " + narrationParts.length + " parts ready";
    } else if (generatedCount) {
      audioDownloadStatus.textContent = generatedCount + " of " + narrationParts.length + " parts ready · Continue to finish";
    } else {
      audioDownloadStatus.textContent = "Generate the complete audio before playing · Up to 48,000 characters per hour";
    }
  }

  function clearNarrationCache() {
    narrationCacheText = "";
    narrationParts = [];
    updateAudioControls();
  }

  function prepareNarrationCache(text, chunks) {
    if (narrationCacheText !== text || narrationParts.length !== chunks.length) {
      narrationCacheText = text;
      narrationParts = new Array(chunks.length);
    }
    updateAudioControls();
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
      request.timeout = 45000;
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
      if (isSpeaking || isPreparingAudio || activeAudio || audioRequests.length || speechChunks.length) stopSpeech();
      clearNarrationCache();
      transcript.value = transcript.value.trimEnd() + separator + foundText;
      pageCount += 1;
      updateTranscript();
      quality.textContent = "Page " + pageCount + " added · OCR confidence " + Math.round(result.confidence || 0) + "% · Please review names and punctuation.";
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

  function makeSpeechChunks(text) {
    var sentences = text.match(/[^.!?]+[.!?]+[”’"')\]]*|[^.!?]+$/g) || [text];
    var chunks = [];
    sentences.forEach(function (sentence) {
      var value = sentence.trim();
      while (value.length > AUDIO_CHUNK_CHARS) {
        var splitAt = value.lastIndexOf(" ", AUDIO_CHUNK_CHARS);
        if (splitAt < 1) splitAt = AUDIO_CHUNK_CHARS;
        chunks.push(value.slice(0, splitAt).trim());
        value = value.slice(splitAt).trim();
      }
      if (value) chunks.push(value);
    });
    return chunks;
  }

  function releaseActiveAudio() {
    if (activeAudio) {
      activeAudio.onended = null;
      activeAudio.onerror = null;
      activeAudio.pause();
      activeAudio.removeAttribute("src");
      activeAudio.load();
      activeAudio = null;
    }
    if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = "";
  }

  function showNarrationError(message) {
    audioError.textContent = message;
    audioError.hidden = false;
    playerTitle.textContent = "Narration unavailable";
    playerSub.textContent = "You can try again in a moment.";
  }

  function setSpeechState(speaking, paused) {
    isSpeaking = speaking;
    isPaused = paused;
    player.classList.toggle("is-speaking", speaking && !paused);
    playButton.setAttribute("aria-label", paused ? "Resume narration" : (speaking ? "Pause narration" : "Play complete narration"));
    playButton.innerHTML = "";
    if (speaking && !paused) {
      playButton.textContent = "Ⅱ";
      playButton.setAttribute("aria-label", "Pause reading aloud");
    } else {
      var icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("class", "px-ic");
      icon.setAttribute("width", "20"); icon.setAttribute("height", "20");
      icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("fill", "currentColor"); icon.setAttribute("aria-hidden", "true");
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M8 5.5v13l11-6.5z"); icon.appendChild(path); playButton.appendChild(icon);
      if (paused) playButton.setAttribute("aria-label", "Resume reading aloud");
    }
    updateAudioControls();
    if (speaking) playerTitle.textContent = paused ? "Reading paused" : "Reading your text aloud";
    else if (hasCompleteNarration()) playerTitle.textContent = "Complete audio ready";
    else if (countWords(transcript.value)) playerTitle.textContent = "Ready to generate audio";
    else playerTitle.textContent = "Ready when you are";
    setWorkflowStep(speaking ? 3 : (countWords(transcript.value) ? 2 : 1));
  }

  function speakNextChunk() {
    if (!isSpeaking || isPaused) return;
    if (speechIndex >= speechChunks.length) {
      releaseActiveAudio();
      speechChunks = [];
      speechIndex = 0;
      setSpeechState(false, false);
      playerTitle.textContent = "Finished listening";
      return;
    }
    var audioBlob = narrationParts[speechIndex];
    if (!audioBlob) {
      setSpeechState(false, false);
      showNarrationError("This audio part is missing. Generate the narration again before playing.");
      return;
    }
    setSpeechState(true, false);
    playerSub.textContent = "Part " + (speechIndex + 1) + " of " + speechChunks.length;
    activeAudioUrl = URL.createObjectURL(audioBlob);
    activeAudio = new Audio(activeAudioUrl);
    activeAudio.preload = "auto";
    activeAudio.playbackRate = Number(speedInput.value) || 1;
    activeAudio.onended = function () {
      releaseActiveAudio();
      speechIndex += 1;
      speakNextChunk();
    };
    activeAudio.onerror = function () {
      if (!isSpeaking) return;
      releaseActiveAudio();
      speechChunks = [];
      speechIndex = 0;
      setSpeechState(false, false);
      showNarrationError("This audio could not be played. Please try again.");
    };
    activeAudio.play().catch(function (problem) {
      if (problem && problem.name === "NotAllowedError") {
        setSpeechState(false, false);
        playerTitle.textContent = "Audio ready — press Play to listen";
        playerSub.textContent = "Your complete narration is ready.";
        return;
      }
      setSpeechState(false, false);
      showNarrationError(problem && problem.message ? problem.message : "Audio could not be played.");
    });
  }

  async function requestNarration(text, signal) {
    var response = await fetch(audioEndpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ text: text }),
      signal: signal
    });
    if (!response.ok) {
      var problem = {};
      try { problem = await response.json(); } catch (_ignored) { /* The session may have expired. */ }
      throw new Error(problem.error || "Narration could not be created. Please sign in again and try.");
    }
    if (!(response.headers.get("content-type") || "").toLowerCase().includes("audio/mpeg")) {
      throw new Error("The narration service returned an unexpected response. Please refresh and try again.");
    }
    return response.blob();
  }

  async function prepareAudio() {
    if (!narrationReady || !transcript.value.trim() || isPreparingAudio) return;
    var text = transcript.value.trim();
    var chunks = makeSpeechChunks(text);
    prepareNarrationCache(text, chunks);
    if (hasCompleteNarration()) return;

    isPreparingAudio = true;
    var run = ++generationRun;
    var nextIndex = 0;
    var firstFailure = null;
    var cachedCount = narrationParts.filter(Boolean).length;
    var controllers = [];
    audioRequests = controllers;
    audioError.hidden = true;
    playerTitle.textContent = "Preparing your complete audio…";
    playerSub.textContent = cachedCount + " of " + chunks.length + " parts ready";
    updateAudioControls();

    async function generateWorker() {
      while (nextIndex < chunks.length && !firstFailure && generationRun === run) {
        var partIndex = nextIndex++;
        if (narrationParts[partIndex]) continue;
        var controller = new AbortController();
        controllers.push(controller);
        try {
          var blob = await requestNarration(chunks[partIndex], controller.signal);
          if (generationRun !== run) return;
          narrationParts[partIndex] = blob;
          cachedCount += 1;
          updateAudioControls();
          playerTitle.textContent = "Preparing your complete audio…";
          playerSub.textContent = cachedCount + " of " + chunks.length + " parts ready";
        } catch (problem) {
          if (generationRun !== run || controller.signal.aborted) return;
          firstFailure = problem;
        }
      }
    }

    await Promise.all(Array.from({ length: Math.min(AUDIO_GENERATION_CONCURRENCY, chunks.length) }, generateWorker));
    if (generationRun !== run) return;

    audioRequests = [];
    isPreparingAudio = false;
    updateAudioControls();
    if (firstFailure) {
      showNarrationError(firstFailure.message || "Narration could not be created. Please try again.");
      var readyCount = narrationParts.filter(Boolean).length;
      playerSub.textContent = readyCount + " of " + chunks.length + " parts ready. Continue generation to retry.";
      return;
    }
    playerTitle.textContent = "Complete audio ready";
    playerSub.textContent = "All " + chunks.length + " parts are ready to play or download.";
    setStatus("Your complete narration is ready to play or download.");
  }

  function playText() {
    if (!narrationReady || !transcript.value.trim() || !hasCompleteNarration() || isPreparingAudio) return;
    if (isSpeaking && !isPaused) {
      if (activeAudio) activeAudio.pause();
      setSpeechState(true, true);
      return;
    }
    if (isPaused && activeAudio) {
      isPaused = false;
      setSpeechState(true, false);
      activeAudio.play().catch(function (problem) {
        isSpeaking = false;
        setSpeechState(false, false);
        showNarrationError(problem && problem.message ? problem.message : "Audio could not be resumed.");
      });
      return;
    }
    if (activeAudio && activeAudioUrl) {
      setSpeechState(true, false);
      activeAudio.play().catch(function (problem) {
        isSpeaking = false;
        setSpeechState(false, false);
        showNarrationError(problem && problem.message ? problem.message : "Audio could not be played.");
      });
      return;
    }
    speechChunks = makeSpeechChunks(transcript.value.trim());
    speechIndex = 0;
    setSpeechState(true, false);
    speakNextChunk();
  }

  function stopSpeech() {
    if (isPreparingAudio) {
      generationRun += 1;
      audioRequests.forEach(function (controller) { controller.abort(); });
      audioRequests = [];
      isPreparingAudio = false;
    }
    releaseActiveAudio();
    speechChunks = [];
    speechIndex = 0;
    setSpeechState(false, false);
    updateAudioControls();
    updateTranscript();
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

  function downloadText() {
    var blob = new Blob([transcript.value], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "book-scan-" + new Date().toISOString().slice(0, 10) + ".txt";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    setStatus("Your transcript was downloaded as a text file.");
  }

  function downloadAudio() {
    if (downloadAudioButton.disabled || !hasCompleteNarration()) return;
    var audioBlob = new Blob(narrationParts, { type: "audio/mpeg" });
    var url = URL.createObjectURL(audioBlob);
    var link = document.createElement("a");
    link.href = url;
    link.download = "book-scan-audio-" + new Date().toISOString().slice(0, 10) + ".mp3";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    setStatus("Your narration was downloaded as an MP3 file.");
  }

  page.querySelector("[data-snap]").addEventListener("click", function () { if (!isBusy) cameraInput.click(); });
  page.querySelector("[data-upload]").addEventListener("click", function () { if (!isBusy) fileInput.click(); });
  cameraInput.addEventListener("change", function () {
    var selected = cameraInput.files && cameraInput.files[0];
    cameraInput.value = "";
    scanFile(selected);
  });
  fileInput.addEventListener("change", function () {
    var selected = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    scanFile(selected);
  });
  page.querySelector("[data-remove-photo]").addEventListener("click", removePhoto);
  transcript.addEventListener("input", function () {
    if (isSpeaking || isPreparingAudio || activeAudio || audioRequests.length || speechChunks.length) stopSpeech();
    clearNarrationCache();
    updateTranscript();
    setError("");
  });
  copyButton.addEventListener("click", copyText);
  downloadButton.addEventListener("click", downloadText);
  downloadAudioButton.addEventListener("click", downloadAudio);
  generateAudioButton.addEventListener("click", prepareAudio);
  clearButton.addEventListener("click", function () {
    stopSpeech();
    clearNarrationCache();
    transcript.value = "";
    pageCount = 0;
    quality.hidden = true;
    setError("");
    removePhoto();
    updateTranscript();
    setStatus("Your text was cleared from this tab. Take a new photo or add text when you’re ready.");
  });
  playButton.addEventListener("click", playText);
  stopButton.addEventListener("click", stopSpeech);
  speedInput.addEventListener("input", function () {
    var rate = Number(speedInput.value) || 1;
    speedLabel.value = rate.toFixed(1).replace(/\.0$/, "") + "×";
    if (activeAudio) activeAudio.playbackRate = rate;
  });

  if (!narrationReady) {
    playButton.disabled = true;
    speedInput.disabled = true;
    audioNote.hidden = false;
  }
  updateTranscript();
  updateAudioControls();
  window.addEventListener("pagehide", function () {
    if (ocrRequest) ocrRequest.abort();
    generationRun += 1;
    audioRequests.forEach(function (controller) { controller.abort(); });
    releaseActiveAudio();
    if (currentPhotoUrl) URL.revokeObjectURL(currentPhotoUrl);
  }, { once: true });
})();
