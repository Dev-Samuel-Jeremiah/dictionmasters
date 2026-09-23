(function () {
  document.querySelectorAll("[data-recorder]").forEach(function (box) {
    var start = box.querySelector("[data-record-start]");
    var stop = box.querySelector("[data-record-stop]");
    var status = box.querySelector("[data-record-status]");
    var playback = box.querySelector("[data-record-playback]");
    var input = box.querySelector("[data-record-file]");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      status.textContent = "Microphone recording isn't available here. Choose an audio file instead.";
      start.hidden = true;
      return;
    }
    var recorder, stream, chunks = [], seconds = 0, timer;
    start.addEventListener("click", function () {
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (media) {
        stream = media;
        chunks = [];
        seconds = 0;
        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = function (event) { if (event.data && event.data.size) chunks.push(event.data); };
        recorder.onstop = function () {
          stream.getTracks().forEach(function (track) { track.stop(); });
          var blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          playback.src = URL.createObjectURL(blob);
          playback.hidden = false;
          var extension = blob.type.indexOf("ogg") >= 0 ? "ogg" : blob.type.indexOf("mp4") >= 0 ? "m4a" : "webm";
          try {
            var transfer = new DataTransfer();
            transfer.items.add(new File([blob], "teacher-feedback." + extension, { type: blob.type }));
            input.files = transfer.files;
            status.textContent = "Recorded " + seconds + "s. Listen back, then save feedback.";
          } catch (error) {
            status.textContent = "Recording couldn't be attached. Choose an audio file instead.";
          }
        };
        recorder.start();
        start.hidden = true;
        stop.hidden = false;
        status.textContent = "Recording… 0s";
        timer = window.setInterval(function () { seconds += 1; status.textContent = "Recording… " + seconds + "s"; }, 1000);
      }).catch(function () { status.textContent = "Microphone access was denied or unavailable."; });
    });
    stop.addEventListener("click", function () {
      if (recorder && recorder.state !== "inactive") recorder.stop();
      window.clearInterval(timer);
      stop.hidden = true;
      start.hidden = false;
      start.textContent = "Record again";
    });
    input.addEventListener("change", function () {
      if (input.files && input.files[0]) {
        playback.src = URL.createObjectURL(input.files[0]);
        playback.hidden = false;
      }
    });
  });
})();
