/* Control room > Photo slides (templates/manage/lesson_slides.html).
   Lists the pictures chosen for upload, and lets the slideshow be put in
   order by dragging (or with each picture's arrows, by keyboard). */
(function () {
  "use strict";

  // ---------------------------------------------------------- uploading
  var upload = document.querySelector("[data-ms-upload]");
  if (upload) {
    var input = upload.querySelector("[data-ms-files]");
    var drop = upload.querySelector("[data-ms-drop]");
    var chosen = upload.querySelector("[data-ms-chosen]");
    var note = upload.querySelector("[data-ms-upload-note]");
    var button = upload.querySelector("[data-ms-upload-btn]");

    var list = function () {
      chosen.innerHTML = "";
      var files = Array.prototype.slice.call(input.files);
      files.slice(0, 24).forEach(function (file) {
        var li = document.createElement("li");
        if (/^image\//.test(file.type)) {
          var img = document.createElement("img");
          img.alt = "";
          img.src = URL.createObjectURL(file);
          img.onload = function () { URL.revokeObjectURL(img.src); };
          li.appendChild(img);
        }
        var name = document.createElement("span");
        name.textContent = file.name;
        li.appendChild(name);
        chosen.appendChild(li);
      });
      if (files.length > 24) {
        var more = document.createElement("li");
        more.className = "ms-chosen__more";
        more.textContent = "+ " + (files.length - 24) + " more";
        chosen.appendChild(more);
      }
      chosen.hidden = !files.length;
      button.textContent = files.length ? "Upload " + files.length + " picture" + (files.length === 1 ? "" : "s") : "Upload pictures";
    };
    input.addEventListener("change", list);
    ["dragenter", "dragover"].forEach(function (name) {
      drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.add("is-over"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      drop.addEventListener(name, function () { drop.classList.remove("is-over"); });
    });
    drop.addEventListener("drop", function (event) {
      event.preventDefault();
      if (event.dataTransfer && event.dataTransfer.files.length) {
        input.files = event.dataTransfer.files;
        list();
      }
    });
    upload.addEventListener("submit", function () {
      button.disabled = true;
      button.textContent = "Uploading…";
      note.textContent = "Large photos take a moment. Keep this page open.";
    });
  }

  // ---------------------------------------------------------- arranging
  var arrange = document.querySelector("[data-ms-arrange]");
  if (!arrange) return;
  var grid = arrange.querySelector("[data-ms-grid]");
  var orderField = arrange.querySelector("[data-ms-order]");
  var dirtyNote = arrange.querySelector("[data-ms-dirty]");
  var dragging = null;

  function renumber() {
    var ids = [];
    grid.querySelectorAll("[data-ms-slide]").forEach(function (slide, n) {
      slide.querySelector("[data-ms-n]").textContent = n + 1;
      ids.push(slide.dataset.id);
    });
    orderField.value = ids.join(",");
  }
  function changed() { dirtyNote.hidden = false; renumber(); }

  grid.addEventListener("dragstart", function (event) {
    dragging = event.target.closest("[data-ms-slide]");
    if (!dragging) return;
    dragging.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", dragging.dataset.id);
  });
  grid.addEventListener("dragend", function () {
    if (dragging) dragging.classList.remove("is-dragging");
    dragging = null;
    changed();
  });
  grid.addEventListener("dragover", function (event) {
    if (!dragging) return;
    event.preventDefault();
    var over = event.target.closest("[data-ms-slide]");
    if (!over || over === dragging) return;
    var box = over.getBoundingClientRect();
    var after = (event.clientX - box.left) > box.width / 2;
    grid.insertBefore(dragging, after ? over.nextSibling : over);
  });

  grid.addEventListener("click", function (event) {
    var slide = event.target.closest("[data-ms-slide]");
    if (!slide) return;
    if (event.target.closest("[data-ms-left]") && slide.previousElementSibling) {
      grid.insertBefore(slide, slide.previousElementSibling);
      changed();
      slide.querySelector("[data-ms-left]").focus();
    } else if (event.target.closest("[data-ms-right]") && slide.nextElementSibling) {
      grid.insertBefore(slide.nextElementSibling, slide);
      changed();
      slide.querySelector("[data-ms-right]").focus();
    }
  });
  arrange.addEventListener("change", function (event) {
    if (event.target.matches("[data-ms-remove]")) {
      event.target.closest("[data-ms-slide]").classList.toggle("is-removed", event.target.checked);
    }
    dirtyNote.hidden = false;
  });
  arrange.addEventListener("input", function () { dirtyNote.hidden = false; });
  arrange.addEventListener("submit", function (event) {
    var removing = arrange.querySelectorAll("[data-ms-remove]:checked").length;
    if (removing && !window.confirm("Remove " + removing + " picture" + (removing === 1 ? "" : "s") + " from the slideshow?")) {
      event.preventDefault();
      return;
    }
    renumber();
  });
  renumber();
})();
