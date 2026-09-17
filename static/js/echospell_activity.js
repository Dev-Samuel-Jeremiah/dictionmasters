/* EchoSpell activities — dragging words into boxes or into order, and
   recording a spoken answer.

   Every drag also works as two taps: tap a word to pick it up, then tap
   where it goes. HTML5 drag events never fire on a touchscreen, and
   these exercises are used on school tablets and phones. */

(function () {
  "use strict";

  var picked = null;

  function setPicked(chip) {
    if (picked) picked.classList.remove("chip--picked");
    picked = chip || null;
    if (picked) picked.classList.add("chip--picked");
  }

  /* Each sorted word writes the label of the box it is sitting in into
     its own hidden field; still in the word bank means no answer. */
  function syncSort(scope) {
    scope.querySelectorAll(".chip[data-item-id]").forEach(function (chip) {
      var zone = chip.closest(".dropzone");
      var input = scope.querySelector('[data-answer-for="' + chip.dataset.itemId + '"]');
      if (input) input.value = zone ? zone.dataset.bucket || "" : "";
    });
  }

  function syncOrder(item) {
    var line = item.querySelector('[data-role="line"]');
    var input = item.querySelector("[data-answer-for]");
    if (!line || !input) return;
    input.value = Array.prototype.map
      .call(line.querySelectorAll(".chip"), function (chip) {
        return chip.textContent.trim();
      })
      .join(line.dataset.join || " ");
  }

  function dropInto(zone, chip) {
    if (!zone || !chip) return;
    (zone.querySelector(".chip-bank__chips, .bucket__chips") || zone).appendChild(chip);

    var form = zone.closest("form");
    if (form) syncSort(form);
    var item = zone.closest(".activity-item");
    if (item) syncOrder(item);
  }

  // ---- dragging (mouse) -------------------------------------------------

  document.addEventListener("dragstart", function (event) {
    var chip = event.target.closest && event.target.closest(".chip");
    if (!chip) return;
    setPicked(chip);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", chip.textContent);
  });

  document.addEventListener("dragover", function (event) {
    var zone = event.target.closest && event.target.closest(".dropzone");
    if (!zone || !picked) return;
    event.preventDefault();
    zone.classList.add("dropzone--over");
  });

  document.addEventListener("dragleave", function (event) {
    var zone = event.target.closest && event.target.closest(".dropzone");
    if (zone) zone.classList.remove("dropzone--over");
  });

  document.addEventListener("drop", function (event) {
    var zone = event.target.closest && event.target.closest(".dropzone");
    if (!zone || !picked) return;
    event.preventDefault();
    zone.classList.remove("dropzone--over");
    dropInto(zone, picked);
    setPicked(null);
  });

  document.addEventListener("dragend", function () {
    document.querySelectorAll(".dropzone--over").forEach(function (zone) {
      zone.classList.remove("dropzone--over");
    });
    setPicked(null);
  });

  // ---- tapping (touch, and anyone who prefers it) -----------------------

  document.addEventListener("click", function (event) {
    if (!event.target.closest) return;
    var chip = event.target.closest(".chip");

    if (chip) {
      // Building a sentence: one tap sends a word to the line, and a
      // tap on a word already in the line takes it back.
      var item = chip.closest(".activity-item");
      if (item && item.querySelector('[data-role="line"]')) {
        var inLine = !!chip.closest('[data-role="line"]');
        dropInto(item.querySelector(inLine ? '[data-role="bank"]' : '[data-role="line"]'), chip);
        setPicked(null);
        return;
      }

      // Already holding a word and tapped a different one: boxes fill
      // up, so a tap that lands on a word sitting in a box means "put
      // mine in that box too", not "pick that one up instead".
      if (picked && picked !== chip) {
        var zone = chip.closest(".dropzone");
        if (zone) {
          dropInto(zone, picked);
          setPicked(null);
          return;
        }
      }

      setPicked(picked === chip ? null : chip);
      return;
    }

    var zone = event.target.closest(".dropzone");
    if (zone && picked) {
      dropInto(zone, picked);
      setPicked(null);
    }
  });

  // ---- recording --------------------------------------------------------

  document.querySelectorAll(".recorder").forEach(function (recorderBox) {
    var startBtn = recorderBox.querySelector(".recorder__start");
    var stopBtn = recorderBox.querySelector(".recorder__stop");
    var status = recorderBox.querySelector(".recorder__status");
    var playback = recorderBox.querySelector(".recorder__playback");
    var fileInput = recorderBox.querySelector(".recorder__file");
    var recorder = null;
    var chunks = [];
    var timer = null;
    var seconds = 0;

    if (!navigator.mediaDevices || !window.MediaRecorder) {
      startBtn.hidden = true;
      status.textContent = "This browser can't record — choose an audio file instead.";
      return;
    }

    function attach(blob) {
      var extension = blob.type.indexOf("ogg") > -1 ? "ogg" : blob.type.indexOf("mp4") > -1 ? "m4a" : "webm";
      try {
        var transfer = new DataTransfer();
        transfer.items.add(new File([blob], "recording." + extension, { type: blob.type }));
        fileInput.files = transfer.files;
        return true;
      } catch (error) {
        return false;
      }
    }

    startBtn.addEventListener("click", function () {
      navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then(function (stream) {
          chunks = [];
          seconds = 0;
          recorder = new MediaRecorder(stream);

          recorder.ondataavailable = function (event) {
            if (event.data && event.data.size) chunks.push(event.data);
          };

          recorder.onstop = function () {
            stream.getTracks().forEach(function (track) { track.stop(); });
            var blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
            playback.src = URL.createObjectURL(blob);
            playback.hidden = false;
            status.textContent = attach(blob)
              ? "Recorded " + seconds + "s — listen back, or record again."
              : "Recorded, but this browser won't attach it — please choose a file instead.";
          };

          recorder.start();
          startBtn.hidden = true;
          stopBtn.hidden = false;
          status.textContent = "Recording… 0s";
          timer = setInterval(function () {
            seconds += 1;
            status.textContent = "Recording… " + seconds + "s";
          }, 1000);
        })
        .catch(function () {
          status.textContent = "We couldn't reach your microphone — allow it, or choose a file.";
        });
    });

    stopBtn.addEventListener("click", function () {
      if (recorder && recorder.state !== "inactive") recorder.stop();
      clearInterval(timer);
      stopBtn.hidden = true;
      startBtn.hidden = false;
      startBtn.innerHTML = "&#9679; Record again";
    });
  });
})();
