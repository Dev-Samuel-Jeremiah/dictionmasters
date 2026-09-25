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
    if (item.transcript) {
      transcript.innerHTML = item.transcript;
      transcriptWrap.hidden = false;
    } else {
      transcript.textContent = "";
      transcriptWrap.hidden = true;
    }
    trackButtons.forEach((button) => {
      const current = Number(button.dataset.radioTrack) === activeIndex;
      button.classList.toggle("is-playing", current);
      if (current) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
  }

  async function start(index = activeIndex) {
    if (index !== activeIndex) paintTrack(index);
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
    status.textContent = "This episode could not be played. Skipping to the next episode…";
    if (activeIndex < queue.length - 1) window.setTimeout(() => start(activeIndex + 1), 900);
    else audio.pause();
  });

  paintTrack(activeIndex);
  if (savedState && String(savedState.id) === String(queue[activeIndex].id) && savedState.time > 0) {
    audio.addEventListener("loadedmetadata", () => {
      if (Number.isFinite(audio.duration) && savedState.time < audio.duration) audio.currentTime = savedState.time;
    }, { once: true });
    status.textContent = "Your last episode is ready to resume. Press Play when you’re ready.";
  }
})();
