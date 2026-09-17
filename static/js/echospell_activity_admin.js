/* EchoSpell admin: grey out the fields the chosen activity kind does
   not use, on the activity form and on every question below it.

   Locking never uses `disabled` on a text field: a disabled input is
   left out of the POST, so saving would silently wipe whatever was
   already stored there. Text fields are made readonly (still
   submitted, so the value survives), and only file inputs — which
   Django leaves alone when nothing is chosen — are truly disabled. */

(function () {
  "use strict";

  var ITEM_FIELDS = ["prompt", "answer", "options", "hint", "image", "audio_file", "audio_url"];
  var ACTIVITY_FIELDS = ["buckets"];

  var config = null;
  var kindSelect = null;
  var observer = null;
  var inlineGroup = null;

  function boxesFor(root, name) {
    return root.querySelectorAll(".field-" + name);
  }

  function setLocked(box, locked, kindLabel) {
    if (box.dataset.unlockedByHand === "true") return;

    box.classList.toggle("echospell-locked", locked);
    box.querySelectorAll("input, textarea, select").forEach(function (el) {
      if (el.type === "file" || el.type === "checkbox" || el.tagName === "SELECT") {
        el.disabled = locked;
      } else {
        el.readOnly = locked;
      }
    });

    var note = box.querySelector(".echospell-lock-note");
    if (!locked) {
      if (note) note.remove();
      return;
    }
    if (!note) {
      note = document.createElement("p");
      note.className = "echospell-lock-note";
      var text = document.createElement("span");
      var button = document.createElement("button");
      button.type = "button";
      button.className = "echospell-unlock";
      button.textContent = "Use it anyway";
      button.addEventListener("click", function () {
        // Open it first: setLocked bails out early once the flag is set.
        setLocked(box, false);
        box.dataset.unlockedByHand = "true";
        box.classList.add("echospell-unlocked");
      });
      note.appendChild(text);
      note.appendChild(button);
      box.appendChild(note);
    }
    var wording = "Not used by " + kindLabel + " — ";
    var label = note.querySelector("span");
    if (label.textContent !== wording) label.textContent = wording;
  }

  function apply() {
    if (!config || !kindSelect) return;
    // Locking writes into the inline group, which the observer watches;
    // without this it would retrigger itself forever.
    if (observer) observer.disconnect();

    var current = config[kindSelect.value];
    var label = current ? current.label : "this activity type";

    ACTIVITY_FIELDS.forEach(function (name) {
      var used = current && current.activity.indexOf(name) > -1;
      // Only the activity's own fieldsets, never the inline questions.
      document.querySelectorAll(".field-" + name).forEach(function (box) {
        if (box.closest(".inline-group")) return;
        setLocked(box, !used, label);
      });
    });

    document.querySelectorAll(".inline-group .inline-related").forEach(function (row) {
      ITEM_FIELDS.forEach(function (name) {
        var used = current && current.item.indexOf(name) > -1;
        boxesFor(row, name).forEach(function (box) {
          setLocked(box, !used, label);
        });
      });
    });

    if (observer && inlineGroup) {
      observer.observe(inlineGroup, { childList: true, subtree: true });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var data = document.getElementById("echospell-kind-fields");
    kindSelect = document.getElementById("id_kind");
    if (!data || !kindSelect) return;

    try {
      config = JSON.parse(data.textContent);
    } catch (error) {
      return;
    }

    kindSelect.addEventListener("change", apply);

    // "Add another Question" builds a row after this runs.
    inlineGroup = document.querySelector(".inline-group");
    if (inlineGroup) observer = new MutationObserver(apply);

    apply();
  });
})();
