(() => {
  const root = document.querySelector("[data-radio-player]");
  const payload = document.getElementById("diction-radio-queue");
  if (!root || !payload) return;

  let queue;
  try { queue = JSON.parse(payload.textContent); } catch (_) { return; }
  if (!Array.isArray(queue) || !queue.length) return;

  const audio = root.querySelector("[data-radio-audio]");
  const title = root.querySelector("[data-radio-title]");
  const program = root.querySelector("[data-radio-program]");
  const description = root.querySelector("[data-radio-description]");
  const status = root.querySelector("[data-radio-status]");
  const playButton = root.querySelector("[data-radio-play]");
  const cover = root.querySelector("[data-radio-cover]");
  const artPlaceholder = root.querySelector("[data-radio-art-placeholder]");
  const transcriptWrap = root.querySelector("[data-radio-transcript-wrap]");
  const transcript = root.querySelector("[data-radio-transcript]");
  const trackButtons = [...root.querySelectorAll("[data-radio-track]")];
  const storageKey = "dictionRadioLastTrack";
  let activeIndex = 0;
  let savedState = null;

  try {
    savedState = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (savedState && savedState.id) {
      const savedIndex = queue.findIndex((item) => String(item.id) === String(savedState.id));
      if (savedIndex >= 0) activeIndex = savedIndex;
    } else if (savedState && Number.isInteger(savedState.index) && savedState.index >= 0 && savedState.index < queue.length) {
      activeIndex = savedState.index;
    }
  } catch (_) { /* Storage may be disabled. */ }

  const savePosition = () => {
    try { localStorage.setItem(storageKey, JSON.stringify({ id: queue[activeIndex].id, index: activeIndex, time: audio.currentTime || 0 })); }
    catch (_) { /* Storage is optional. */ }
  };

  function paintTrack(index) {
    const nextIndex = (index + queue.length) % queue.length;
    if (nextIndex !== activeIndex && !audio.paused) {
      savePosition();
      audio.pause();
    }
    activeIndex = nextIndex;
    const item = queue[activeIndex];
    if (audio.dataset.trackId !== String(item.id)) {
      audio.dataset.trackId = String(item.id);
      delete audio.dataset.offlineCopy;
      audio.src = item.src;
      audio.load();
    }
    title.textContent = item.title;
    program.textContent = item.program;
    description.innerHTML = item.description || "Settle in and enjoy this Diction Radio programme.";
    if (item.cover) {
      cover.src = item.cover;
      cover.hidden = false;
      artPlaceholder.hidden = true;
    } else {
      cover.removeAttribute("src");
      cover.hidden = true;
      artPlaceholder.hidden = false;
    }
    showTranscript(item);
    trackButtons.forEach((button) => {
      const current = Number(button.dataset.radioTrack) === activeIndex;
      button.classList.toggle("is-playing", current);
      if (current) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
  }

  // The transcript highlights word by word as the episode plays: a fresh
  // read-along box for each episode, following the station's one player.
  let reading = null;
  function showTranscript(item) {
    if (reading && reading.readAlong && reading.readAlong.destroy) reading.readAlong.destroy();
    reading = null;
    transcript.textContent = "";
    transcriptWrap.hidden = !item.transcript;
    if (!item.transcript) return;
    const box = document.createElement("div");
    const words = document.createElement("div");
    words.className = "dm-rich-content";
    words.setAttribute("data-ra-text", "");
    words.innerHTML = item.transcript;
    box.appendChild(words);
    transcript.appendChild(box);
    if (item.sync && window.DMReadAlong) {
      box.setAttribute("data-read-along", "");
      box.setAttribute("data-ra-sync", item.sync);
      box.setAttribute("data-ra-player", "[data-radio-audio]");
      window.DMReadAlong.setUp(box);
      reading = box;
    }
  }

  let listening = false;
  async function start(index = activeIndex) {
    listening = true;
    if (index !== activeIndex) paintTrack(index);
    // No internet: the saved copy, if this episode has one.
    if (!navigator.onLine && !audio.dataset.offlineCopy && await playSaved(true)) return;
    status.textContent = "Connecting to Diction Radio…";
    try {
      await audio.play();
      status.textContent = `Now playing ${queue[activeIndex].title}.`;
    } catch (_) {
      status.textContent = "Playback was blocked. Press Play on the player to start listening.";
    }
  }

  playButton.addEventListener("click", () => {
    if (audio.paused) start();
    else audio.pause();
  });
  root.querySelector("[data-radio-next]").addEventListener("click", () => start(activeIndex + 1));
  root.querySelector("[data-radio-previous]").addEventListener("click", () => {
    if (audio.currentTime > 4) {
      audio.currentTime = 0;
      start();
    } else start(activeIndex - 1);
  });
  trackButtons.forEach((button) => button.addEventListener("click", () => start(Number(button.dataset.radioTrack))));

  audio.addEventListener("play", () => {
    status.textContent = `Now playing ${queue[activeIndex].title}.`;
    playButton.innerHTML = "&#10074;&#10074;";
    playButton.setAttribute("aria-label", "Pause Diction Radio");
    root.classList.add("is-playing");
  });
  audio.addEventListener("pause", () => {
    playButton.innerHTML = "&#9654;";
    playButton.setAttribute("aria-label", "Play Diction Radio");
    root.classList.remove("is-playing");
    if (!audio.ended) {
      status.textContent = "Paused. Press Play to continue listening.";
      savePosition();
    }
  });
  audio.addEventListener("timeupdate", savePosition);
  audio.addEventListener("ended", () => {
    if (activeIndex < queue.length - 1) start(activeIndex + 1);
    else {
      status.textContent = "The station lineup is starting again from the top.";
      start(0);
    }
  });
  audio.addEventListener("error", () => {
    if (!audio.dataset.offlineCopy) {
      // Played only if someone pressed Play: a page opened offline stays quiet.
      playSaved(listening).then((playing) => { if (!playing) skipBroken(); });
      return;
    }
    skipBroken();
  });
  function skipBroken() {
    status.textContent = "This episode could not be played. Skipping to the next episode…";
    if (activeIndex < queue.length - 1) window.setTimeout(() => start(activeIndex + 1), 900);
    else audio.pause();
  }

  // ---- saved for listening offline (static/js/offline_video.js) ----------
  // Each episode of ours has a Save button. Offline, or when an episode won't
  // load, the player plays the saved copy instead.
  const saveBoxes = new Map([...root.querySelectorAll("[data-radio-offline]")]
    .filter((box) => box.dataset.ticket)
    .map((box) => [Number(box.dataset.radioOffline), box]));
  let offlineUrl = "";

  function withCopies(job) {
    if (window.DMOfflineVideos) return job(window.DMOfflineVideos);
    document.addEventListener("dm-offline-videos", () => job(window.DMOfflineVideos), { once: true });
  }

  function paintSave(box, record, note) {
    const keep = box.querySelector("[data-radio-save]");
    const drop = box.querySelector("[data-radio-unsave]");
    keep.disabled = Boolean(record) || Boolean(note);
    keep.classList.toggle("is-saved", Boolean(record));
    keep.textContent = note || (record ? "✓ Saved" : "⬇ Save");
    drop.hidden = !record;
  }

  function wireSave(api, index, box) {
    const entry = { ticket: box.dataset.ticket, ticketId: box.dataset.ref, title: box.dataset.title || "Diction Radio" };
    box.hidden = false;
    api.copyOf(entry.ticketId).then((record) => paintSave(box, record));
    box.querySelector("[data-radio-save]").addEventListener("click", () => {
      paintSave(box, null, "Saving…");
      api.keepCopy(entry, (percent) => paintSave(box, null, `Saving ${percent}%`))
        .then((record) => {
          paintSave(box, record);
          status.textContent = `${entry.title} is saved on this device for listening offline.`;
        })
        .catch((error) => {
          paintSave(box, null);
          status.textContent = (error && error.message) || "That episode couldn't be saved. Please try again.";
        });
    });
    box.querySelector("[data-radio-unsave]").addEventListener("click", () => {
      api.copyOf(entry.ticketId).then((record) => record && api.dropCopy(record)).then(() => paintSave(box, null));
    });
  }

  // The saved copy of the episode on now, if there is one: true once playing from it.
  function playSaved(andPlay) {
    const box = saveBoxes.get(activeIndex);
    if (!box) return Promise.resolve(false);
    // The saving script may still be on its way (it loads after this one).
    if (!window.DMOfflineVideos) return new Promise((resolve) => withCopies(() => resolve(playSaved(andPlay))));
    const api = window.DMOfflineVideos;
    const wanted = activeIndex;
    return api.copyOf(box.dataset.ref).then((record) => {
      if (!record) return false;
      return api.openCopy(record).then((blob) => {
        if (wanted !== activeIndex) return false;
        if (offlineUrl) URL.revokeObjectURL(offlineUrl);
        offlineUrl = URL.createObjectURL(blob);
        audio.src = offlineUrl;
        audio.dataset.offlineCopy = "1";
        if (andPlay) audio.play().catch(() => {});
        status.textContent = `Playing your saved copy of ${queue[activeIndex].title}.`;
        return true;
      });
    }).catch((error) => {
      status.textContent = (error && error.message) || "That saved copy couldn't be opened.";
      return false;
    });
  }

  if (saveBoxes.size) withCopies((api) => saveBoxes.forEach((box, index) => wireSave(api, index, box)));

  paintTrack(activeIndex);
  if (!navigator.onLine) playSaved(false);
  if (savedState && String(savedState.id) === String(queue[activeIndex].id) && savedState.time > 0) {
    audio.addEventListener("loadedmetadata", () => {
      if (Number.isFinite(audio.duration) && savedState.time < audio.duration) audio.currentTime = savedState.time;
    }, { once: true });
    status.textContent = "Your last episode is ready to resume. Press Play when you’re ready.";
  }
})();
