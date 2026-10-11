/*
 * The QR box in an EchoSpell, Tricks or 44 Academy hero (staff only, see
 * templates/echospell/_qr_box.html): copy the link, or copy the code as an
 * image with the page's name under it, for the book layout.
 */
// Copying the code: the address as text, or the image itself for pasting
// straight into the book layout.
(function () {
  var box = document.querySelector("[data-qr]");
  if (!box) return;
  var said = box.querySelector("[data-qr-said]");
  var url = box.dataset.qrUrl;          // kept out of sight; the buttons hand it over
  var png = box.dataset.qrPng;

  function say(message) {
    said.textContent = message;
    window.setTimeout(function () { said.textContent = ""; }, 4000);
  }

  box.querySelector("[data-qr-copy-link]").addEventListener("click", function () {
    navigator.clipboard.writeText(url).then(function () { say("Link copied."); },
      function () { say("Couldn't copy — the link is shown above."); });
  });

  box.querySelector("[data-qr-copy-image]").addEventListener("click", function () {
    if (!window.ClipboardItem || !navigator.clipboard || !navigator.clipboard.write) {
      say("This browser can't copy images — use Download PNG.");
      return;
    }

    function imageWithName(blob, name) {
      return new Promise(function (resolve, reject) {
        var image = new Image();
        var objectUrl = URL.createObjectURL(blob);
        image.onload = function () {
          URL.revokeObjectURL(objectUrl);
          try {
            var margin = 24;
            var fontSize = Math.max(14, Math.min(24, Math.round(image.width / 22)));
            var lineHeight = fontSize + 6;
            var canvas = document.createElement("canvas");
            var context = canvas.getContext("2d");
            context.font = "600 " + fontSize + "px system-ui, sans-serif";

            // Wrap longer card names so the full label stays legible.
            var lines = [];
            var line = "";
            name.split(/\s+/).forEach(function (word) {
              var candidate = line ? line + " " + word : word;
              if (line && context.measureText(candidate).width > image.width) {
                lines.push(line);
                line = word;
              } else {
                line = candidate;
              }
            });
            if (line) lines.push(line);

            var textTop = margin + image.height + 14 + fontSize;
            canvas.width = image.width + margin * 2;
            canvas.height = textTop + Math.max(0, lines.length - 1) * lineHeight + margin;
            context = canvas.getContext("2d");
            context.fillStyle = "#fff";
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.drawImage(image, margin, margin);
            context.fillStyle = "#111";
            context.font = "600 " + fontSize + "px system-ui, sans-serif";
            context.textAlign = "center";
            lines.forEach(function (text, index) {
              context.fillText(text, canvas.width / 2, textTop + index * lineHeight);
            });
            canvas.toBlob(function (namedBlob) {
              if (namedBlob) resolve(namedBlob);
              else reject(new Error("Could not create the named QR image."));
            }, "image/png");
          } catch (error) {
            reject(error);
          }
        };
        image.onerror = function () {
          URL.revokeObjectURL(objectUrl);
          reject(new Error("Could not load the QR image."));
        };
        image.src = objectUrl;
      });
    }

    fetch(png, { credentials: "same-origin" })
      .then(function (response) { return response.blob(); })
      .then(function (blob) { return imageWithName(blob, box.dataset.qrName); })
      .then(function (blob) { return navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]); })
      .then(function () { say("QR image with name copied — paste it into your layout."); },
            function () { say("Couldn't copy the image — use Download PNG."); });
  });
})();
