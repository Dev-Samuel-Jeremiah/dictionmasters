(function () {
  var list = document.querySelector("[data-question-list]");
  var addButton = document.querySelector("[data-add-question]");
  var template = document.getElementById("bulk-question-template");
  var totalForms = document.getElementById("id_questions-TOTAL_FORMS");
  if (!list || !addButton || !template || !totalForms) return;

  function activeRows() {
    return Array.prototype.filter.call(list.querySelectorAll("[data-bulk-row]"), function (row) {
      return !row.hidden;
    });
  }

  function updateRows() {
    activeRows().forEach(function (row, index) {
      var number = row.querySelector("[data-question-number]");
      if (number) number.textContent = "Question " + (index + 1);
    });
  }

  function clearRow(row) {
    row.querySelectorAll("input:not([type=hidden]):not([type=checkbox]), textarea, select").forEach(function (input) {
      input.value = "";
    });
  }

  list.querySelectorAll("[data-bulk-row]").forEach(function (row) {
    var deletion = row.querySelector('input[name$="-DELETE"]');
    if (deletion && deletion.checked) row.hidden = true;
  });
  updateRows();

  addButton.addEventListener("click", function () {
    var index = Number(totalForms.value);
    if (index >= 100) {
      addButton.disabled = true;
      return;
    }
    var html = template.innerHTML
      .split("__prefix__").join(String(index))
      .split("__number__").join(String(index + 1));
    list.insertAdjacentHTML("beforeend", html);
    totalForms.value = String(index + 1);
    updateRows();
    var rows = activeRows();
    var firstField = rows[rows.length - 1].querySelector("input:not([type=hidden]):not([type=checkbox]), textarea, select");
    if (firstField) firstField.focus();
    if (index + 1 >= 100) addButton.disabled = true;
  });

  list.addEventListener("click", function (event) {
    var button = event.target.closest("[data-remove-question]");
    if (!button) return;
    var row = button.closest("[data-bulk-row]");
    if (!row) return;
    var rows = activeRows();
    if (rows.length <= 1) {
      clearRow(row);
      return;
    }
    var deletion = row.querySelector('input[name$="-DELETE"]');
    if (deletion) deletion.checked = true;
    row.hidden = true;
    updateRows();
    addButton.disabled = Number(totalForms.value) >= 100;
  });
})();
