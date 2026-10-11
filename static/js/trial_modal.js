/* The trial modal on Schools & people (templates/manage/_trial_modal.html).
   Anything with data-trial-target opens it for that school or learner: a
   school card whose access has ended (data-trial-expired) on a click
   instead of opening the school; a plan chip (data-trial-chip) always. */
(function () {
  var dialog = document.querySelector("[data-trial-modal]");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var field = function (name) { return dialog.querySelector('[data-trial-field="' + name + '"]'); };
  var length = dialog.querySelector("[data-trial-length]");
  var unit = dialog.querySelector("[data-trial-unit]");

  function open(source) {
    field("target").value = source.dataset.trialTarget;
    field("name").textContent = "Add more trial: " + source.dataset.trialName;
    field("state").textContent = source.dataset.trialState || "";
    var link = field("open");
    if (source.dataset.trialOpen) { link.href = source.dataset.trialOpen; link.hidden = false; } else { link.hidden = true; }
    dialog.showModal();
    length.focus();
    length.select();
  }

  document.addEventListener("click", function (event) {
    var chip = event.target.closest("[data-trial-chip]");
    var card = event.target.closest("[data-trial-expired]");
    var source = chip || card;
    if (!source || !source.dataset.trialTarget) return;
    event.preventDefault();
    event.stopPropagation();
    open(source);
  }, true);
  document.addEventListener("keydown", function (event) {
    var chip = event.target.closest && event.target.closest("[data-trial-chip]");
    if (chip && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); open(chip); }
  });
  dialog.querySelectorAll("[data-trial-quick]").forEach(function (button) {
    button.addEventListener("click", function () {
      var parts = button.dataset.trialQuick.split(" ");
      length.value = parts[0];
      unit.value = parts[1];
      dialog.querySelectorAll("[data-trial-quick]").forEach(function (b) { b.classList.toggle("is-on", b === button); });
    });
  });
  dialog.querySelector("[data-trial-close]").addEventListener("click", function () { dialog.close(); });
  dialog.addEventListener("click", function (event) { if (event.target === dialog) dialog.close(); });   // the backdrop
})();
