/* Scan & Listen: the in-page camera and the crop tool.
 *
 *   DMPageCapture.camera()   opens the live camera (laptop webcam or the
 *                            phone's back camera); resolves a File, or null
 *                            if closed. Rejects when no camera can be used,
 *                            so the caller can fall back to the device's
 *                            own camera app.
 *   DMPageCapture.crop(file) lets the learner crop and rotate a photo;
 *                            resolves the cropped JPEG File, or null if
 *                            cancelled. Rejects if the image can't be opened.
 *
 * Everything happens in this tab: nothing is uploaded until the caller
 * sends the finished page for reading.
 */
(function () {
  "use strict";

  var OUTPUT_MAX = 3000;          // longest side of the cropped page, px
  var MIN_CROP = 0.06;            // smallest crop, as a share of each side

  function el(tag, className, html) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (html != null) node.innerHTML = html;
    return node;
  }

  function overlay(title) {
    var root = el("div", "bsx");
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", title);
    var head = el("div", "bsx__head");
    head.appendChild(el("h2", "bsx__title", title));
    var close = el("button", "bsx__close", "&times;");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    head.appendChild(close);
    root.appendChild(head);
    var stage = el("div", "bsx__stage");
    root.appendChild(stage);
    var bar = el("div", "bsx__bar");
    root.appendChild(bar);
    document.body.appendChild(root);
    document.documentElement.classList.add("bsx-open");
    return { root: root, stage: stage, bar: bar, close: close };
  }

  function dispose(view) {
    document.documentElement.classList.remove("bsx-open");
    if (view.root.parentNode) view.root.parentNode.removeChild(view.root);
  }

  function button(label, kind) {
    var b = el("button", "bsx__btn" + (kind ? " bsx__btn--" + kind : ""), label);
    b.type = "button";
    return b;
  }

  function onEscape(handler) {
    function listener(event) { if (event.key === "Escape") handler(); }
    document.addEventListener("keydown", listener);
    return function () { document.removeEventListener("keydown", listener); };
  }

  /* ---------------------------------------------------------------- camera */

  function cameraSupported() {
    return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function openStream(deviceId) {
    var video = { width: { ideal: 3840 }, height: { ideal: 2160 } };
    if (deviceId) video.deviceId = { exact: deviceId };
    else video.facingMode = { ideal: "environment" };
    return navigator.mediaDevices.getUserMedia({ video: video, audio: false });
  }

  function cameraError(problem) {
    var name = problem && problem.name;
    if (name === "NotAllowedError" || name === "SecurityError") {
      return "Camera access is blocked. Allow the camera for this site (the camera icon in the address bar), then try again — or use Choose a photo.";
    }
    if (name === "NotFoundError" || name === "OverconstrainedError") {
      return "No camera was found on this device. Use Choose a photo instead.";
    }
    if (name === "NotReadableError") {
      return "The camera is being used by another app. Close it and try again.";
    }
    return "The camera could not be started. Try again, or use Choose a photo.";
  }

  function camera() {
    if (!cameraSupported()) return Promise.reject(new Error("unsupported"));

    return new Promise(function (resolve, reject) {
      var view = overlay("Take a photo of the page");
      view.root.classList.add("bsx--camera");
      var video = el("video", "bsx__video");
      video.setAttribute("playsinline", "");
      video.muted = true;
      video.autoplay = true;
      var guide = el("div", "bsx__guide", "<span>Fit one page inside the frame</span>");
      var message = el("p", "bsx__message");
      message.hidden = true;
      view.stage.appendChild(video);
      view.stage.appendChild(guide);
      view.stage.appendChild(message);

      var flip = button("&#8635; Switch camera", "ghost");
      flip.hidden = true;
      var shutter = el("button", "bsx__shutter");
      shutter.type = "button";
      shutter.disabled = true;
      shutter.setAttribute("aria-label", "Take the photo");
      var cancel = button("Cancel", "ghost");
      view.bar.appendChild(cancel);
      view.bar.appendChild(shutter);
      view.bar.appendChild(flip);

      var stream = null;
      var cameras = [];
      var cameraIndex = -1;
      var settled = false;

      function stop() {
        if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
        stream = null;
        video.srcObject = null;
      }
      function finish(result) {
        if (settled) return;
        settled = true;
        stop();
        removeEscape();
        dispose(view);
        resolve(result);
      }
      var removeEscape = onEscape(function () { finish(null); });
      view.close.addEventListener("click", function () { finish(null); });
      cancel.addEventListener("click", function () { finish(null); });

      function start(deviceId) {
        stop();
        shutter.disabled = true;
        return openStream(deviceId).then(function (s) {
          if (settled) { s.getTracks().forEach(function (t) { t.stop(); }); return; }
          stream = s;
          video.srcObject = s;
          message.hidden = true;
          var playing = video.play();
          if (playing && playing.catch) playing.catch(function () {});
          video.addEventListener("loadedmetadata", function ready() {
            video.removeEventListener("loadedmetadata", ready);
            shutter.disabled = false;
            shutter.focus({ preventScroll: true });
          });
          return navigator.mediaDevices.enumerateDevices().then(function (devices) {
            cameras = devices.filter(function (d) { return d.kind === "videoinput"; });
            var current = s.getVideoTracks()[0];
            var currentId = current && current.getSettings ? current.getSettings().deviceId : "";
            cameraIndex = cameras.findIndex(function (d) { return d.deviceId === currentId; });
            flip.hidden = cameras.length < 2;
          }).catch(function () {});
        });
      }

      flip.addEventListener("click", function () {
        if (cameras.length < 2) return;
        cameraIndex = (cameraIndex + 1) % cameras.length;
        start(cameras[cameraIndex].deviceId).catch(function (problem) {
          message.textContent = cameraError(problem);
          message.hidden = false;
        });
      });

      shutter.addEventListener("click", function () {
        if (!stream || shutter.disabled) return;
        shutter.disabled = true;
        view.root.classList.add("bsx--flash");
        grab().then(function (blob) {
          finish(new File([blob], "Camera photo.jpg", { type: "image/jpeg" }));
        }).catch(function () {
          shutter.disabled = false;
          message.textContent = "The photo could not be taken. Please try again.";
          message.hidden = false;
        });
      });

      // A full-resolution still where the browser offers one; otherwise the
      // current video frame, which is already the camera's best video size.
      function grab() {
        var track = stream.getVideoTracks()[0];
        if (window.ImageCapture && track) {
          try {
            return new window.ImageCapture(track).takePhoto().catch(frame);
          } catch (_ignored) { /* fall through */ }
        }
        return frame();
      }
      function frame() {
        return new Promise(function (ok, fail) {
          var canvas = document.createElement("canvas");
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          if (!canvas.width || !canvas.height) { fail(new Error("no frame")); return; }
          canvas.getContext("2d").drawImage(video, 0, 0);
          canvas.toBlob(function (blob) { blob ? ok(blob) : fail(new Error("no blob")); }, "image/jpeg", 0.95);
        });
      }

      start().catch(function (problem) {
        if (settled) return;
        // Let the caller fall back to the device's own camera app when no
        // camera can be opened here at all; show why when it was refused.
        if (problem && problem.name === "NotAllowedError") {
          message.textContent = cameraError(problem);
          message.hidden = false;
          return;
        }
        settled = true;
        removeEscape();
        dispose(view);
        reject(problem);
      });
    });
  }

  /* ------------------------------------------------------------------ crop */

  function loadImage(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var image = new Image();
      image.onload = function () { URL.revokeObjectURL(url); resolve(image); };
      image.onerror = function () { URL.revokeObjectURL(url); reject(new Error("unreadable")); };
      image.src = url;
    });
  }

  // The photo turned by 0, 90, 180 or 270 degrees, at up to OUTPUT_MAX * 1.5
  // so a huge photo doesn't exhaust a phone's memory.
  function rotated(image, quarter) {
    var w = image.naturalWidth, h = image.naturalHeight;
    var scale = Math.min(1, (OUTPUT_MAX * 1.5) / Math.max(w, h));
    w = Math.round(w * scale); h = Math.round(h * scale);
    var turn = ((quarter % 4) + 4) % 4;
    var canvas = document.createElement("canvas");
    canvas.width = turn % 2 ? h : w;
    canvas.height = turn % 2 ? w : h;
    var ctx = canvas.getContext("2d");
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(turn * Math.PI / 2);
    ctx.drawImage(image, -w / 2, -h / 2, w, h);
    return canvas;
  }

  function crop(file) {
    return loadImage(file).then(function (image) {
      return new Promise(function (resolve) {
        var view = overlay("Crop the page");
        view.root.classList.add("bsx--crop");
        var hint = el("p", "bsx__hint", "Drag the corners so only the page’s writing is inside the box.");
        view.root.insertBefore(hint, view.stage);

        var frameBox = el("div", "bsx__frame");
        var canvasHolder = el("div", "bsx__canvas");
        var box = el("div", "bsx__box");
        ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach(function (edge) {
          var handle = el("span", "bsx__handle bsx__handle--" + edge);
          handle.dataset.edge = edge;
          box.appendChild(handle);
        });
        box.appendChild(el("span", "bsx__grid"));
        frameBox.appendChild(canvasHolder);
        frameBox.appendChild(box);
        view.stage.appendChild(frameBox);

        var left = button("&#8634; Rotate left", "ghost");
        var right = button("&#8635; Rotate right", "ghost");
        var reset = button("Whole photo", "ghost");
        var cancel = button("Cancel", "ghost");
        var use = button("Crop &amp; read page", "primary");
        var tools = el("div", "bsx__tools");
        tools.appendChild(left); tools.appendChild(right); tools.appendChild(reset);
        var actions = el("div", "bsx__actions");
        actions.appendChild(cancel); actions.appendChild(use);
        view.bar.appendChild(tools);
        view.bar.appendChild(actions);

        var quarter = 0;
        var source = null;            // the rotated full-size canvas
        var rect = { x: 0, y: 0, w: 1, h: 1 };   // crop, as shares of the photo
        var settled = false;

        function draw() {
          source = rotated(image, quarter);
          canvasHolder.innerHTML = "";
          source.className = "bsx__photo";
          canvasHolder.appendChild(source);
          fit();
        }
        // Size the photo to the space available, keeping its shape.
        function fit() {
          if (!source) return;
          var room = view.stage.getBoundingClientRect();
          var scale = Math.min((room.width - 24) / source.width, (room.height - 24) / source.height);
          frameBox.style.width = Math.max(40, Math.floor(source.width * scale)) + "px";
          frameBox.style.height = Math.max(40, Math.floor(source.height * scale)) + "px";
          place();
        }
        function place() {
          box.style.left = rect.x * 100 + "%";
          box.style.top = rect.y * 100 + "%";
          box.style.width = rect.w * 100 + "%";
          box.style.height = rect.h * 100 + "%";
        }
        function fullRect() { rect = { x: 0.03, y: 0.03, w: 0.94, h: 0.94 }; }

        var drag = null;
        function startDrag(event) {
          if (event.button > 0) return;
          var edge = event.target.dataset && event.target.dataset.edge;
          var bounds = frameBox.getBoundingClientRect();
          drag = { edge: edge || "move", x: event.clientX, y: event.clientY,
                   start: { x: rect.x, y: rect.y, w: rect.w, h: rect.h },
                   bw: bounds.width, bh: bounds.height, id: event.pointerId };
          box.setPointerCapture(event.pointerId);
          box.classList.add("is-dragging");
          event.preventDefault();
        }
        function moveDrag(event) {
          if (!drag || event.pointerId !== drag.id) return;
          var dx = (event.clientX - drag.x) / drag.bw;
          var dy = (event.clientY - drag.y) / drag.bh;
          var s = drag.start;
          var x1 = s.x, y1 = s.y, x2 = s.x + s.w, y2 = s.y + s.h;
          if (drag.edge === "move") {
            var nx = Math.min(Math.max(0, s.x + dx), 1 - s.w);
            var ny = Math.min(Math.max(0, s.y + dy), 1 - s.h);
            rect = { x: nx, y: ny, w: s.w, h: s.h };
          } else {
            if (drag.edge.indexOf("w") > -1) x1 = Math.min(Math.max(0, s.x + dx), x2 - MIN_CROP);
            if (drag.edge.indexOf("e") > -1) x2 = Math.max(Math.min(1, x2 + dx), x1 + MIN_CROP);
            if (drag.edge.indexOf("n") > -1) y1 = Math.min(Math.max(0, s.y + dy), y2 - MIN_CROP);
            if (drag.edge.indexOf("s") > -1) y2 = Math.max(Math.min(1, y2 + dy), y1 + MIN_CROP);
            rect = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
          }
          place();
        }
        function endDrag(event) {
          if (!drag || event.pointerId !== drag.id) return;
          drag = null;
          box.classList.remove("is-dragging");
        }
        box.addEventListener("pointerdown", startDrag);
        box.addEventListener("pointermove", moveDrag);
        box.addEventListener("pointerup", endDrag);
        box.addEventListener("pointercancel", endDrag);

        // Arrow keys nudge the whole box; Shift + arrows resize it.
        box.tabIndex = 0;
        box.setAttribute("role", "group");
        box.setAttribute("aria-label", "Crop area. Arrow keys move it; Shift and arrow keys resize it.");
        box.addEventListener("keydown", function (event) {
          var step = 0.01;
          var keys = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
          var d = keys[event.key];
          if (!d) return;
          event.preventDefault();
          if (event.shiftKey) {
            rect.w = Math.min(1 - rect.x, Math.max(MIN_CROP, rect.w + d[0]));
            rect.h = Math.min(1 - rect.y, Math.max(MIN_CROP, rect.h + d[1]));
          } else {
            rect.x = Math.min(Math.max(0, rect.x + d[0]), 1 - rect.w);
            rect.y = Math.min(Math.max(0, rect.y + d[1]), 1 - rect.h);
          }
          place();
        });

        function turn(by) {
          // Keep the same part of the page selected as it turns.
          var r = rect;
          rect = by > 0 ? { x: 1 - r.y - r.h, y: r.x, w: r.h, h: r.w }
                        : { x: r.y, y: 1 - r.x - r.w, w: r.h, h: r.w };
          quarter += by;
          draw();
        }
        left.addEventListener("click", function () { turn(-1); });
        right.addEventListener("click", function () { turn(1); });
        reset.addEventListener("click", function () { rect = { x: 0, y: 0, w: 1, h: 1 }; place(); });

        function finish(result) {
          if (settled) return;
          settled = true;
          window.removeEventListener("resize", fit);
          removeEscape();
          dispose(view);
          resolve(result);
        }
        var removeEscape = onEscape(function () { finish(null); });
        view.close.addEventListener("click", function () { finish(null); });
        cancel.addEventListener("click", function () { finish(null); });

        use.addEventListener("click", function () {
          use.disabled = true;
          var sx = Math.round(rect.x * source.width), sy = Math.round(rect.y * source.height);
          var sw = Math.max(1, Math.round(rect.w * source.width)), sh = Math.max(1, Math.round(rect.h * source.height));
          var scale = Math.min(1, OUTPUT_MAX / Math.max(sw, sh));
          var out = document.createElement("canvas");
          out.width = Math.round(sw * scale);
          out.height = Math.round(sh * scale);
          var ctx = out.getContext("2d");
          ctx.imageSmoothingQuality = "high";
          ctx.drawImage(source, sx, sy, sw, sh, 0, 0, out.width, out.height);
          out.toBlob(function (blob) {
            if (!blob) { use.disabled = false; return; }
            var name = (file.name || "Page").replace(/\.[^.]+$/, "") + " (cropped).jpg";
            finish(new File([blob], name, { type: "image/jpeg" }));
          }, "image/jpeg", 0.93);
        });

        window.addEventListener("resize", fit);
        fullRect();
        draw();
        use.focus({ preventScroll: true });
      });
    });
  }

  window.DMPageCapture = { camera: camera, crop: crop, cameraSupported: cameraSupported };
})();
