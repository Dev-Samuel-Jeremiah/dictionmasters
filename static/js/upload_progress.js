/* A progress bar for anything with a file on it.

   Sending a form with a video, an audio file or an image normally leaves
   the page sitting there with no sign of life — a long lesson video can
   take minutes, and there is no way to tell whether it is working. So
   any form carrying a file is sent in the background instead, with a bar
   showing how much has gone, the megabytes so far, and a Cancel button.

   It attaches itself to every multipart form on the page: the control
   room, the Django admin, and a learner sending a recording.

   Without this script the forms submit the ordinary way.  */

(function () {
  "use strict";

  var BAR_ID = "dm-upload-progress";

  function chosenFiles(form) {
    var files = [];
    form.querySelectorAll('input[type="file"]').forEach(function (input) {
      if (input.disabled || !input.files) return;
      Array.prototype.forEach.call(input.files, function (file) { files.push(file); });
    });
    return files;
  }

  function size(bytes) {
    if (bytes >= 1024 * 1024 * 1024) return (bytes / 1024 / 1024 / 1024).toFixed(1) + " GB";
    if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
    if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
    return bytes + " bytes";
  }

  function panel(form, files) {
    var total = files.reduce(function (sum, file) { return sum + file.size; }, 0);
    var names = files.length === 1 ? files[0].name : files.length + " files";

    var box = document.createElement("div");
    box.className = "up-progress";
    box.id = BAR_ID;
    box.setAttribute("role", "status");
    box.innerHTML =
      '<div class="up-progress__head">' +
        '<p class="up-progress__name"></p>' +
        '<p class="up-progress__percent">0%</p>' +
      "</div>" +
      '<div class="up-progress__track"><div class="up-progress__fill"></div></div>' +
      '<div class="up-progress__foot">' +
        '<p class="up-progress__detail"></p>' +
        '<button type="button" class="up-progress__cancel">Cancel</button>' +
      "</div>";
    box.querySelector(".up-progress__name").textContent = "Uploading " + names;
    box.querySelector(".up-progress__detail").textContent = size(0) + " of " + size(total);
    form.appendChild(box);
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });

    return {
      node: box,
      sent: function (loaded, known) {
        var percent = known && total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
        box.querySelector(".up-progress__percent").textContent = known ? percent + "%" : "…";
        box.querySelector(".up-progress__fill").style.width = (known ? percent : 100) + "%";
        box.querySelector(".up-progress__detail").textContent = known
          ? size(loaded) + " of " + size(total)
          : "Uploading " + size(total);
      },
      saving: function () {
        box.classList.add("is-saving");
        box.querySelector(".up-progress__name").textContent = "Saving your data…";
        box.querySelector(".up-progress__percent").textContent = "Saving";
        box.querySelector(".up-progress__fill").style.width = "100%";
        box.querySelector(".up-progress__detail").textContent = "Upload complete. The server is processing the file and preparing your result.";
        box.querySelector(".up-progress__cancel").hidden = true;
      },
      done: function () {
        box.classList.add("is-done");
        box.querySelector(".up-progress__name").textContent = "Saved ✓";
        box.querySelector(".up-progress__detail").textContent = "Opening the next page…";
      },
      failed: function (message) {
        box.classList.add("is-failed");
        box.querySelector(".up-progress__name").textContent = "Upload didn't finish";
        box.querySelector(".up-progress__percent").textContent = "";
        box.querySelector(".up-progress__detail").textContent = message;
        box.querySelector(".up-progress__cancel").textContent = "Close";
      },
      close: function () { box.remove(); },
      onCancel: function (run) { box.querySelector(".up-progress__cancel").addEventListener("click", run); },
    };
  }

  function show(html) {
    /* The form came back with something to say (a validation error, say).
       Swap the whole page for it, exactly as a normal submit would. */
    document.open();
    document.write(html);
    document.close();
  }

  function readBlob(blob, done) {
    if (!blob) { done(""); return; }
    var reader = new FileReader();
    reader.onload = function () { done(String(reader.result || "")); };
    reader.onerror = function () { done(""); };
    reader.readAsText(blob, "UTF-8");
  }

  function attachmentName(header) {
    var encoded = /filename\*=UTF-8''([^;]+)/i.exec(header || "");
    var plain = /filename="?([^";]+)"?/i.exec(header || "");
    var name = encoded ? encoded[1].trim() : (plain ? plain[1].trim() : "download");
    try { name = decodeURIComponent(name); } catch (error) { /* use the header value as-is */ }
    return name.replace(/[\\/]/g, "_");
  }

  function download(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
  }

  function send(form, button) {
    var files = chosenFiles(form);
    if (!files.length) return false;

    var data = new FormData(form);
    // Which button was pressed matters: "Save and add another", the Django
    // admin's "_continue", and so on.
    if (button && button.name) data.append(button.name, button.value || "");

    var view = panel(form, files);
    var buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    buttons.forEach(function (one) { one.disabled = true; });

    var request = new XMLHttpRequest();
    request.open("POST", form.action || window.location.href, true);
    request.responseType = "blob";
    request.setRequestHeader("X-DM-Upload", "1");

    request.upload.addEventListener("progress", function (event) {
      view.sent(event.loaded, event.lengthComputable);
      if (event.lengthComputable && event.loaded >= event.total) view.saving();
    });
    request.upload.addEventListener("load", function () { view.saving(); });

    request.addEventListener("load", function () {
      if (request.status === 402) {          // access ran out mid-upload
        var where = "/billing/";
        readBlob(request.response, function (text) {
          try { where = JSON.parse(text).url || where; } catch (error) { /* keep the default */ }
          window.location.assign(where);
        });
        return;
      }
      if (request.status >= 400) {
        buttons.forEach(function (one) { one.disabled = false; });
        view.failed("The server answered " + request.status + ". Nothing was saved — please try again.");
        return;
      }
      var disposition = request.getResponseHeader("Content-Disposition") || "";
      if (/attachment/i.test(disposition)) {
        download(request.response, attachmentName(disposition));
        view.done();
        // The response also sets the success message. Reload after starting
        // the download to show it and clear the uploaded file from the form.
        window.setTimeout(function () { window.location.reload(); }, 1000);
        return;
      }

      readBlob(request.response, function (html) {
        view.done();
        var landed = request.responseURL || "";
        var here = window.location.href.split("#")[0];
        if (landed && landed.split("#")[0] !== here && landed.split("?")[0] !== (form.action || here).split("?")[0]) {
          window.location.assign(landed);    // saved, and the server moved us on
        } else {
          show(html);                         // same page again: it has something to say
        }
      });
    });

    request.addEventListener("error", function () {
      buttons.forEach(function (one) { one.disabled = false; });
      view.failed("The connection dropped. Nothing was saved — check your internet and try again.");
    });

    view.onCancel(function () {
      request.abort();
      buttons.forEach(function (one) { one.disabled = false; });
      view.close();
    });

    request.send(data);
    return true;
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || form.dataset.noProgress !== undefined) return;
    if ((form.enctype || "").toLowerCase() !== "multipart/form-data") return;
    if (document.getElementById(BAR_ID)) return;        // one at a time
    if (!window.FormData || !window.XMLHttpRequest) return;
    if (send(form, event.submitter)) event.preventDefault();
  });
})();
