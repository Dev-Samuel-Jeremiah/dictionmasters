/* The live AI reading tutor.

   The learner reads the highlighted sentence aloud. The page listens,
   notices when they've finished (a pause after speaking), and sends that
   one sentence to the server, which says how each word went. Then:

     every word right     a word of praise, and on to the next sentence
     a word or two wrong  the tutor stops, says each word properly, and
                          has the learner say it back (twice at most)
     most of it wrong     the tutor reads the whole sentence, and the
                          learner reads it again

   After the last sentence the reading is scored and the report opens.

   The microphone is asked for once and kept for the whole reading; it's
   never recording while the tutor is speaking, so the tutor doesn't hear
   itself. Nothing is recorded until "Start" is pressed, and each clip is
   only as long as one sentence.  */

(function () {
  "use strict";

  var root = document.querySelector("[data-tutor]");
  if (!root) return;

  var SENTENCE_END_SILENCE = 1300;   // ms of quiet after speaking that ends a sentence
  var WORD_END_SILENCE = 800;        // ...and a single word
  var WAIT_FOR_VOICE = 12000;        // how long to wait for the learner to begin
  var MIN_VOICE = 180;               // ms of sound that counts as speech, not a cough
  var MAX_WORD_TRIES = 2;
  var MAX_WORDS_PER_SENTENCE = 3;    // more than this and it's a sentence to hear again
  var PRAISE = ["Well read!", "Lovely — every word.", "Perfect!", "Great reading.", "Brilliant, keep going.", "Clear and correct!"];
  var TRY_AGAIN = ["That's it!", "Much better!", "Perfect — well done.", "Yes, that's right!"];

  var sentences = JSON.parse(document.getElementById("tutor-sentences").textContent);
  var csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
  var name = root.dataset.name || "";

  var el = {
    passage: root.querySelector("[data-passage]"),
    mic: root.querySelector("[data-mic]"),
    micLabel: root.querySelector("[data-mic-label]"),
    title: root.querySelector("[data-say-title]"),
    line: root.querySelector("[data-say-line]"),
    avatar: root.querySelector("[data-avatar]"),
    focus: root.querySelector("[data-focus]"),
    focusWord: root.querySelector("[data-focus-word]"),
    focusIpa: root.querySelector("[data-focus-ipa]"),
    focusTip: root.querySelector("[data-focus-tip]"),
    focusPlay: root.querySelector("[data-focus-play]"),
    hear: root.querySelector("[data-hear]"),
    skip: root.querySelector("[data-skip]"),
    finish: root.querySelector("[data-finish]"),
    progress: root.querySelector("[data-progress]"),
    progressText: root.querySelector("[data-progress-text]"),
  };

  var session = null;
  var current = 0;
  var busy = false;        // the flow is running (listening, checking or speaking)
  var paused = false;
  var stream = null, audioCtx = null, analyser = null, samples = null;
  var recorder = null;
  var stopListening = null;
  var focusAudio = null;
  var runId = 0;           // bumped to cancel a flow in progress

  function pick(list) { return list[Math.floor(Math.random() * list.length)]; }

  function url(template, id) { return template.replace("/0/", "/" + id + "/"); }

  function sentenceEl(index) { return el.passage.querySelector('[data-s="' + index + '"]'); }
  function wordEl(sentence, word) {
    var s = sentenceEl(sentence);
    return s ? s.querySelector('[data-w="' + word + '"]') : null;
  }

  function bareWord(text) { return text.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ""); }

  /* ---- what the tutor says ---------------------------------------- */

  function say(title, line, mood) {
    el.title.textContent = title;
    el.line.textContent = line || "";
    root.dataset.mood = mood || "";
  }

  function state(name) {
    root.dataset.state = name;
    var labels = { idle: "Start", listening: "Listening…", checking: "Checking…", speaking: "Tutor", paused: "Resume", done: "Done" };
    el.micLabel.textContent = labels[name] || "";
    el.mic.setAttribute("aria-label", name === "paused" ? "Resume reading" : name === "idle" ? "Start reading" : "Pause");
  }

  function showFocus(word, ipa, tip) {
    el.focusWord.textContent = word;
    el.focusIpa.textContent = ipa || "";
    el.focusTip.textContent = tip || "";
    el.focus.hidden = false;
  }
  function hideFocus() { el.focus.hidden = true; focusAudio = null; }

  function progress() {
    var done = Math.min(current, sentences.length);
    el.progress.style.width = (100 * done / sentences.length) + "%";
    el.progressText.textContent = done >= sentences.length
      ? "All " + sentences.length + " sentences read"
      : "Sentence " + (done + 1) + " of " + sentences.length;
  }

  function focusSentence(index) {
    el.passage.querySelectorAll(".tt-s--now").forEach(function (node) { node.classList.remove("tt-s--now"); });
    var s = sentenceEl(index);
    if (!s) return;
    s.classList.add("tt-s--now");
    var box = s.getBoundingClientRect();
    var dock = document.querySelector(".tt-dock").getBoundingClientRect();
    if (box.top < 90 || box.bottom > dock.top - 16) {
      window.scrollTo({ top: window.scrollY + box.top - Math.max(100, (dock.top - box.height) / 3), behavior: "smooth" });
    }
  }

  /* ---- the tutor's voice ------------------------------------------ */

  // The tutor's recordings, fetched once and kept for the reading. A word
  // flagged in a sentence starts loading the moment the check comes back,
  // so it's ready by the time the tutor says it.
  var voiceCache = {};

  function voiceFor(sentence, word) {
    var key = sentence + ":" + (word === undefined ? "" : word);
    if (!voiceCache[key]) {
      var audio = new Audio();
      audio.preload = "auto";
      audio.src = url(root.dataset.sayUrl, session) + "?sentence=" + sentence + (word === undefined ? "" : "&word=" + word);
      voiceCache[key] = audio;
    }
    return voiceCache[key];
  }

  var bestVoice = null;
  function browserVoice() {
    if (bestVoice || !window.speechSynthesis) return bestVoice;
    var voices = window.speechSynthesis.getVoices();
    var ranked = ["en-GB", "en-NG", "en-IE", "en-AU", "en-US", "en"];
    for (var i = 0; i < ranked.length && !bestVoice; i++) {
      bestVoice = voices.find(function (v) { return v.lang && v.lang.replace("_", "-").indexOf(ranked[i]) === 0 && /natural|google|premium|enhanced/i.test(v.name); })
        || voices.find(function (v) { return v.lang && v.lang.replace("_", "-").indexOf(ranked[i]) === 0; });
    }
    return bestVoice;
  }

  function speakText(text, slow) {
    return new Promise(function (resolve) {
      if (!window.speechSynthesis) { resolve(); return; }
      var utterance = new SpeechSynthesisUtterance(text);
      var voice = browserVoice();
      if (voice) utterance.voice = voice;
      utterance.lang = voice ? voice.lang : "en-GB";
      utterance.rate = slow ? 0.8 : 0.92;
      utterance.onend = utterance.onerror = function () { resolve(); };
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
      setTimeout(resolve, 8000 + text.length * 90);
    });
  }

  function playVoice(audio) {
    // Resolves true once it has played, false if it couldn't (no voice
    // available, or it didn't start in time) so the browser's voice can
    // step in.
    return new Promise(function (resolve) {
      var settled = false;
      function done(ok) {
        if (settled) return;
        settled = true;
        audio.removeEventListener("ended", ended);
        audio.removeEventListener("error", failed);
        clearTimeout(slow);
        resolve(ok);
      }
      function ended() { done(true); }
      function failed() { done(false); }
      audio.addEventListener("ended", ended);
      audio.addEventListener("error", failed);
      var slow = setTimeout(function () { if (audio.paused) { audio.pause(); done(false); } }, 6000);
      try { audio.currentTime = 0; } catch (error) { /* not loaded yet */ }
      var playing = audio.play();
      if (playing && playing.then) {
        playing.then(function () {
          clearTimeout(slow);
          slow = setTimeout(function () { done(true); }, 15000);
        }).catch(function () { done(false); });
      }
    });
  }

  function model(sentence, word, text) {
    // The tutor says it: the site's voice if there is one, otherwise the
    // browser's own.
    state("speaking");
    el.avatar.classList.add("is-speaking");
    return playVoice(voiceFor(sentence, word)).then(function (played) {
      if (!played) {
        delete voiceCache[sentence + ":" + (word === undefined ? "" : word)];
        return speakText(text, word !== undefined);
      }
      return null;
    }).then(function () {
      el.avatar.classList.remove("is-speaking");
    });
  }

  /* ---- listening --------------------------------------------------- */

  function recorderType() {
    var types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];
    for (var i = 0; i < types.length; i++) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return "";
  }

  function openMic() {
    if (stream) return Promise.resolve();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      return Promise.reject(new Error("unsupported"));
    }
    return navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    }).then(function (s) {
      stream = s;
      var Ctx = window.AudioContext || window.webkitAudioContext;
      audioCtx = new Ctx();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      samples = new Float32Array(analyser.fftSize);
      audioCtx.createMediaStreamSource(stream).connect(analyser);
    });
  }

  function loudness() {
    analyser.getFloatTimeDomainData(samples);
    var sum = 0;
    for (var i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    return Math.sqrt(sum / samples.length);
  }

  function listen(opts) {
    /* Record until the learner has spoken and then paused. Resolves with
       the recording, or null if they never started. */
    return new Promise(function (resolve) {
      if (audioCtx.state === "suspended") audioCtx.resume();
      var type = recorderType();
      var chunks = [];
      recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      recorder.ondataavailable = function (event) { if (event.data && event.data.size) chunks.push(event.data); };

      var began = Date.now();
      var floor = Infinity, spoke = 0, lastVoice = 0, voiced = false, finished = false;
      var timer = null;

      function end(keep) {
        if (finished) return;
        finished = true;
        clearInterval(timer);
        stopListening = null;
        el.mic.style.setProperty("--level", 0);
        recorder.onstop = function () {
          resolve(keep && chunks.length ? new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" }) : null);
        };
        try { recorder.stop(); } catch (error) { resolve(null); }
      }
      stopListening = function (keep) { end(keep && voiced); };

      recorder.start(250);
      timer = setInterval(function () {
        var level = loudness();
        var now = Date.now();
        // The first moment sets the room's own noise; speech is well above it.
        if (now - began < 350) { floor = Math.min(floor, level); return; }
        var threshold = Math.max(0.012, Math.min(floor, 0.05) * 3);
        el.mic.style.setProperty("--level", Math.min(1, level / (threshold * 4)).toFixed(2));
        if (level > threshold) {
          spoke += 50;
          lastVoice = now;
          if (spoke >= MIN_VOICE && !voiced) { voiced = true; root.classList.add("is-hearing"); }
        }
        if (voiced && now - lastVoice > opts.endSilence) { root.classList.remove("is-hearing"); end(true); }
        else if (!voiced && now - began > WAIT_FOR_VOICE) end(false);
        else if (now - began > opts.maxMs) { root.classList.remove("is-hearing"); end(voiced); }
      }, 50);
    });
  }

  function send(blob, sentence, word) {
    var form = new FormData();
    var ext = /mp4/.test(blob.type) ? "m4a" : /ogg/.test(blob.type) ? "ogg" : "webm";
    form.append("audio", blob, "clip." + ext);
    form.append("sentence", sentence);
    if (word !== undefined) form.append("word", word);
    return fetch(url(root.dataset.checkUrl, session), {
      method: "POST", body: form, credentials: "same-origin", headers: { "X-CSRFToken": csrf },
    }).then(function (response) {
      return response.json().then(function (data) { data.status = response.status; return data; });
    });
  }

  /* ---- the reading, sentence by sentence ---------------------------- */

  function paintSentence(index, result) {
    result.words.forEach(function (word) {
      var node = wordEl(index, word.i);
      if (!node) return;
      node.classList.remove("tt-w--ok", "tt-w--wrong", "tt-w--missed", "tt-w--fixed");
      if (word.status === "ok") node.classList.add("tt-w--ok");
      if (word.status === "wrong") { node.classList.add("tt-w--wrong"); node.title = "You said: " + word.heard; }
      if (word.status === "missed") { node.classList.add("tt-w--missed"); node.title = "Left out"; }
    });
  }

  function alive(id) { return id === runId && !paused; }

  function readSentence(id, index, attempt) {
    if (!alive(id)) return Promise.resolve();
    focusSentence(index);
    progress();
    state("listening");
    say(attempt > 1 ? "Your turn again" : "Your turn",
        attempt > 1 ? "Read the highlighted sentence once more." : "Read the highlighted sentence aloud.", "listen");
    var words = sentences[index].words.length;
    return listen({ endSilence: SENTENCE_END_SILENCE, maxMs: 8000 + words * 900 }).then(function (blob) {
      if (!alive(id)) return null;
      if (!blob) {
        say("I'm listening", "Take your time — read the highlighted sentence when you're ready.", "listen");
        return readSentence(id, index, attempt);
      }
      state("checking");
      say("Checking…", "Listening back to what you read.", "think");
      return send(blob, index).then(function (data) {
        if (!alive(id)) return null;
        if (data.status === 429 || data.status === 503 || data.error) {
          say("One moment", data.error || "Something went wrong — let's try that sentence again.", "warn");
          return wait(2200).then(function () { return readSentence(id, index, attempt); });
        }
        if (!data.heard) {
          say("I didn't catch that", "Please read the sentence again, a little louder.", "warn");
          return wait(1400).then(function () { return readSentence(id, index, attempt); });
        }
        return coach(id, index, data.sentence, attempt);
      });
    }).catch(function () {
      if (!alive(id)) return null;
      say("Connection trouble", "Let's try that sentence again.", "warn");
      return wait(2000).then(function () { return readSentence(id, index, attempt); });
    });
  }

  function coach(id, index, result, attempt) {
    paintSentence(index, result);
    result.model.slice(0, MAX_WORDS_PER_SENTENCE).forEach(function (at) { voiceFor(index, at); });
    if (result.again && attempt === 1) voiceFor(index);
    if (!result.model.length) {
      say(pick(PRAISE), attempt > 1 ? "That's the sentence done." : "", "happy");
      return wait(900);
    }
    if (result.again && attempt === 1) {
      say("Let's hear it first", "Listen to the whole sentence, then read it again.", "teach");
      return model(index, undefined, sentences[index].text).then(function () {
        if (!alive(id)) return null;
        return readSentence(id, index, 2);
      });
    }
    var words = result.model.slice(0, MAX_WORDS_PER_SENTENCE);
    var chain = Promise.resolve();
    words.forEach(function (at) {
      chain = chain.then(function () {
        if (!alive(id)) return null;
        var found = result.words.filter(function (w) { return w.i === at; })[0] || {};
        found.ipa = (result.ipa || {})[String(at)] || "";
        return practiseWord(id, index, at, found, 1);
      });
    });
    return chain.then(function () {
      hideFocus();
      if (!alive(id)) return null;
      say("Good work", "On to the next sentence.", "happy");
      return wait(700);
    });
  }

  function practiseWord(id, index, at, verdict, attempt) {
    var text = bareWord(sentences[index].words[at].text);
    var node = wordEl(index, at);
    if (node) node.classList.add("tt-w--focus");
    var tip = (verdict.tips && verdict.tips[0])
      ? "Listen for it: " + verdict.tips[0] + "."
      : verdict.status === "missed" ? "This word was left out." : verdict.heard ? "It sounded like “" + verdict.heard + "”." : "";
    showFocus(text, verdict.ipa || "", attempt === 1 ? tip : "Listen once more, closely.");
    say(attempt === 1 ? "Listen carefully" : "Once more", "This is how we say “" + text + "”.", "teach");
    focusAudio = function () { return model(index, at, text); };
    return model(index, at, text).then(function () {
      if (!alive(id)) return null;
      state("listening");
      say("Now you say it", "Say “" + text + "” clearly.", "listen");
      return listen({ endSilence: WORD_END_SILENCE, maxMs: 6000 });
    }).then(function (blob) {
      if (!alive(id)) return null;
      if (!blob) {
        say("Say it when you're ready", "Just the one word: “" + text + "”.", "listen");
        return attempt < MAX_WORD_TRIES + 1 ? practiseWord(id, index, at, verdict, attempt + 1) : null;
      }
      state("checking");
      return send(blob, index, at).then(function (data) {
        if (!alive(id)) return null;
        var ok = data.heard && data.word && data.word.ok;
        if (ok) {
          if (node) { node.classList.remove("tt-w--wrong", "tt-w--missed"); node.classList.add("tt-w--fixed"); }
          say(pick(TRY_AGAIN), "“" + text + "” — just right.", "happy");
          return wait(900);
        }
        if (attempt < MAX_WORD_TRIES) {
          var next = { status: "wrong", heard: data.word && data.word.heard, tips: data.word && data.word.tips, ipa: verdict.ipa };
          return practiseWord(id, index, at, next, attempt + 1);
        }
        say("Good try", "We'll keep practising “" + text + "”. It's on your report.", "teach");
        return wait(1300);
      });
    }).then(function () {
      if (node) node.classList.remove("tt-w--focus");
    });
  }

  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function run() {
    var id = ++runId;
    busy = true;
    el.hear.disabled = el.skip.disabled = el.finish.disabled = false;
    (function next() {
      if (!alive(id)) return;
      if (current >= sentences.length) { busy = false; finish(); return; }
      readSentence(id, current, 1).then(function () {
        if (!alive(id)) return;
        current += 1;
        next();
      });
    })();
  }

  function pause() {
    paused = true;
    runId += 1;
    if (stopListening) stopListening(false);
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    el.avatar.classList.remove("is-speaking");
    root.classList.remove("is-hearing");
    hideFocus();
    state("paused");
    say("Paused", "Press the microphone when you're ready to carry on.", "");
  }

  function resume() {
    paused = false;
    run();
  }

  function finish() {
    runId += 1;
    if (stopListening) stopListening(false);
    state("done");
    el.hear.disabled = el.skip.disabled = el.finish.disabled = true;
    say("Well done" + (name ? ", " + name : "") + "!", "Working out your reading level…", "think");
    fetch(url(root.dataset.finishUrl, session), {
      method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf },
    }).then(function (r) { return r.json().then(function (d) { d.status = r.status; return d; }); })
      .then(function (data) {
        if (data.report) { window.location.href = data.report; return; }
        say("Almost there", data.error || "Please try again.", "warn");
        el.finish.disabled = false;
      })
      .catch(function () { say("Connection trouble", "Press Finish to try again.", "warn"); el.finish.disabled = false; });
  }

  /* ---- controls ----------------------------------------------------- */

  el.mic.addEventListener("click", function () {
    var now = root.dataset.state || "idle";
    if (now === "idle") return begin();
    if (now === "paused") return resume();
    if (now === "done") return null;
    return pause();
  });

  function begin() {
    state("checking");
    say("Getting ready", "Please allow the microphone when your browser asks.", "think");
    openMic().then(function () {
      return fetch(root.dataset.startUrl, { method: "POST", credentials: "same-origin", headers: { "X-CSRFToken": csrf } });
    }).then(function (r) { return r.json(); }).then(function (data) {
      session = data.session;
      if (window.speechSynthesis) window.speechSynthesis.getVoices();
      say("Hello" + (name ? " " + name : "") + "!", "I'll listen as you read. If a word needs work, I'll help you with it.", "happy");
      return wait(1800);
    }).then(function () {
      run();
    }).catch(function (error) {
      state("idle");
      if (error && error.message === "unsupported") {
        say("Your browser can't record", "Please open this page in Chrome, Edge or Safari to read with the tutor.", "warn");
      } else if (error && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
        say("The microphone is blocked", "Allow microphone access for this site (the icon in the address bar), then press Start.", "warn");
      } else if (error && error.name === "NotFoundError") {
        say("No microphone found", "Connect a microphone or headset, then press Start.", "warn");
      } else {
        say("Couldn't start", "Please check your connection and press Start again.", "warn");
      }
    });
  }

  el.hear.addEventListener("click", function () {
    if (!session || current >= sentences.length) return;
    pause();
    say("Listen", "Here is the sentence. Press the microphone when you're ready to read it.", "teach");
    model(current, undefined, sentences[current].text).then(function () { state("paused"); });
  });

  el.skip.addEventListener("click", function () {
    if (!session || current >= sentences.length) return;
    pause();
    current += 1;
    progress();
    if (current >= sentences.length) { finish(); return; }
    resume();
  });

  el.finish.addEventListener("click", function () {
    if (!session) return;
    pause();
    finish();
  });

  el.focusPlay.addEventListener("click", function () {
    if (focusAudio && root.dataset.state !== "listening") focusAudio();
  });

  // Tap a word you've already read to hear it.
  el.passage.addEventListener("click", function (event) {
    var node = event.target.closest(".tt-w");
    if (!node || !session || root.dataset.state === "listening" || root.dataset.state === "checking") return;
    var s = Number(node.closest("[data-s]").dataset.s);
    var w = Number(node.dataset.w);
    if (s >= current) return;
    model(s, w, bareWord(node.textContent)).then(function () { if (paused) state("paused"); });
  });

  window.addEventListener("beforeunload", function () {
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
  });

  state("idle");
  progress();
})();
