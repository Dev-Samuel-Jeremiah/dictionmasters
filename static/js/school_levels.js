/* School dashboard: moving teachers and students between levels
   (templates/schools/_people_table.html, apps/schools/levels.py).

   Each list can be searched and filtered by level; the top box ticks
   everyone shown. With people ticked, a bar offers "Promote to next level"
   (students) and "Move to…". A promotion is previewed first — who goes
   from which level to which — before anything changes. "Change" beside a
   person opens a small dialog with their levels: one for a student, any
   number for a teacher. */
(function () {
  "use strict";

  var LEVELS = ["Pre-Level"];
  for (var i = 1; i <= 12; i++) LEVELS.push("Level " + i);

  function nextLevel(level) {
    var at = LEVELS.indexOf(level);
    return at < 0 || at === LEVELS.length - 1 ? null : LEVELS[at + 1];
  }

  function openDialog(dialog) {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }
  function closeDialog(dialog) {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  // ------------------------------------------------------------ the lists
  document.querySelectorAll("[data-sl]").forEach(function (list) {
    var rows = Array.prototype.slice.call(list.querySelectorAll("[data-sl-row]"));
    var search = list.querySelector("[data-sl-search]");
    var filter = list.querySelector("[data-sl-filter]");
    var all = list.querySelector("[data-sl-all]");
    var bar = list.querySelector("[data-sl-bar]");
    var count = list.querySelector("[data-sl-count]");
    var empty = list.querySelector("[data-sl-empty]");
    var form = list.querySelector("[data-sl-bulk-form]");
    var role = list.dataset.role;

    // How many are in each level, in the filter's options.
    Array.prototype.forEach.call(filter.options, function (option) {
      if (!option.value) return;
      var n = rows.filter(function (row) {
        return option.value === "none" ? !row.dataset.level : row.dataset.levels.split(",").indexOf(option.value) > -1;
      }).length;
      option.textContent = (option.value === "none" ? "No level yet" : option.value) + " (" + n + ")";
      option.hidden = n === 0;
      option.disabled = n === 0;
    });

    function shown(row) { return !row.hidden; }
    function picked() { return rows.filter(function (row) { return row.querySelector("[data-sl-pick]").checked; }); }

    function refresh() {
      var chosen = picked();
      count.textContent = chosen.length;
      bar.hidden = chosen.length === 0;
      var visible = rows.filter(shown);
      var ticked = visible.filter(function (row) { return row.querySelector("[data-sl-pick]").checked; }).length;
      all.checked = visible.length > 0 && ticked === visible.length;
      all.indeterminate = ticked > 0 && ticked < visible.length;
      rows.forEach(function (row) { row.classList.toggle("is-picked", row.querySelector("[data-sl-pick]").checked); });
    }

    function applyFilter() {
      var text = search.value.trim().toLowerCase();
      var level = filter.value;
      var any = false;
      rows.forEach(function (row) {
        var okLevel = !level || (level === "none" ? !row.dataset.level : row.dataset.levels.split(",").indexOf(level) > -1);
        var okText = !text || row.dataset.search.indexOf(text) > -1;
        row.hidden = !(okLevel && okText);
        if (!row.hidden) any = true;
      });
      empty.hidden = any;
      refresh();
    }

    search.addEventListener("input", applyFilter);
    filter.addEventListener("change", applyFilter);
    all.addEventListener("change", function () {
      rows.filter(shown).forEach(function (row) { row.querySelector("[data-sl-pick]").checked = all.checked; });
      refresh();
    });
    list.addEventListener("change", function (event) {
      if (event.target.matches("[data-sl-pick]")) refresh();
    });
    list.querySelector("[data-sl-clear]").addEventListener("click", function () {
      rows.forEach(function (row) { row.querySelector("[data-sl-pick]").checked = false; });
      refresh();
    });

    // Hidden rows that are still ticked would be changed too: only send
    // the ones the admin can see.
    function sendOnlyShown() {
      rows.forEach(function (row) {
        var box = row.querySelector("[data-sl-pick]");
        if (row.hidden) box.checked = false;
      });
    }

    function confirmThen(title, items, note, goLabel, go) {
      var dialog = document.querySelector("[data-sl-confirm]");
      dialog.querySelector("[data-sl-confirm-title]").textContent = title;
      var ul = dialog.querySelector("[data-sl-confirm-list]");
      ul.innerHTML = "";
      items.forEach(function (item) {
        var li = document.createElement("li");
        li.innerHTML = "<span></span><strong></strong>";
        li.firstChild.textContent = item[0];
        li.lastChild.textContent = item[1];
        ul.appendChild(li);
      });
      ul.hidden = items.length === 0;
      dialog.querySelector("[data-sl-confirm-note]").textContent = note;
      var goButton = dialog.querySelector("[data-sl-confirm-go]");
      goButton.textContent = goLabel;
      goButton.disabled = items.length === 0;
      goButton.onclick = function () { goButton.disabled = true; go(); };
      dialog.querySelector("[data-sl-confirm-cancel]").onclick = function () { closeDialog(dialog); };
      openDialog(dialog);
    }

    function people(n) { return n + " " + role + (n === 1 ? "" : "s"); }

    var promote = list.querySelector("[data-sl-promote]");
    if (promote) promote.addEventListener("click", function () {
      sendOnlyShown();
      var chosen = picked();
      var moves = {}, order = [], top = 0, none = 0;
      chosen.forEach(function (row) {
        var from = row.dataset.level;
        if (!from) { none++; return; }
        var to = nextLevel(from);
        if (!to) { top++; return; }
        var key = from + " → " + to;
        if (!moves[key]) { moves[key] = 0; order.push(key); }
        moves[key]++;
      });
      order.sort(function (a, b) { return LEVELS.indexOf(a.split(" → ")[0]) - LEVELS.indexOf(b.split(" → ")[0]); });
      var items = order.map(function (key) { return [key, people(moves[key])]; });
      var notes = [];
      if (top) notes.push(people(top) + " already in Level 12 will stay there.");
      if (none) notes.push(people(none) + " with no level yet will be left as they are.");
      var total = chosen.length - top - none;
      notes.push(total ? "You can undo this afterwards under Level changes." : "Nobody here can be promoted.");
      confirmThen("Promote " + people(total) + " to their next level?", items, notes.join(" "), "Promote " + people(total), function () {
        form.querySelector("[data-sl-action]").value = "promote";
        form.submit();
      });
    });

    var moveTo = list.querySelector("[data-sl-move-to]");
    list.querySelector("[data-sl-move]").addEventListener("click", function () {
      if (!moveTo.value) { moveTo.focus(); return; }
      sendOnlyShown();
      var chosen = picked();
      var from = {}, order = [];
      chosen.forEach(function (row) {
        var key = row.dataset.level || "No level";
        if (key === moveTo.value) return;
        if (!from[key]) { from[key] = 0; order.push(key); }
        from[key]++;
      });
      var items = order.map(function (key) { return [key + " → " + moveTo.value, people(from[key])]; });
      var already = chosen.filter(function (row) { return row.dataset.level === moveTo.value; }).length;
      var note = (already ? people(already) + " already in " + moveTo.value + " stay. " : "") +
        (role === "teacher" ? "Teachers keep any other levels they also teach. " : "") + "You can undo this afterwards.";
      confirmThen("Move " + people(chosen.length - already) + " to " + moveTo.value + "?", items, note, "Move to " + moveTo.value, function () {
        form.querySelector("[data-sl-action]").value = "move";
        form.querySelector("[data-sl-level]").value = moveTo.value;
        form.submit();
      });
    });

    refresh();
  });

  // ------------------------------------- change one person's level(s)
  var dialog = document.querySelector("[data-sl-dialog]");
  if (!dialog) return;
  var dialogForm = dialog.querySelector("[data-sl-dialog-form]");
  var boxes = dialog.querySelectorAll("[data-sl-dialog-levels] input");
  var lede = dialog.querySelector("[data-sl-dialog-lede]");
  var single = false;

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-sl-change]");
    if (!button) return;
    var row = button.closest("[data-sl-row]");
    var role = button.closest("[data-sl]").dataset.role;
    var levels = row.dataset.levels ? row.dataset.levels.split(",") : [];
    single = role === "student";
    dialogForm.action = button.dataset.url;
    dialog.querySelector(".sl-dialog__title").textContent = "Change level · " + button.dataset.name;
    lede.textContent = single
      ? "Choose the level this student is in. They'll see that level's work from their next page."
      : "Tick every level this teacher teaches. The first one they already had stays their main level.";
    boxes.forEach(function (box) {
      box.type = single ? "radio" : "checkbox";
      box.checked = levels.indexOf(box.value) > -1;
    });
    openDialog(dialog);
    var first = dialog.querySelector("[data-sl-dialog-levels] input:checked") || boxes[0];
    first.focus();
  });
  dialog.querySelector("[data-sl-dialog-close]").addEventListener("click", function () { closeDialog(dialog); });
  dialogForm.addEventListener("submit", function (event) {
    if (!dialog.querySelector("[data-sl-dialog-levels] input:checked")) {
      event.preventDefault();
      lede.textContent = "Choose at least one level.";
    }
  });
  // Close by clicking the dimmed area around a dialog.
  document.querySelectorAll(".sl-dialog").forEach(function (d) {
    d.addEventListener("click", function (event) { if (event.target === d) closeDialog(d); });
  });
})();
