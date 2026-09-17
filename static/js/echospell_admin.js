// EchoSpell admin: on the Level add/change page, auto-fill each inline
// Group's Title as "<Level name> Group <number>" from the two dropdowns,
// unless the admin has typed their own title for that row.
document.addEventListener("DOMContentLoaded", function () {
  var levelNameField = document.getElementById("id_name");
  var groupsContainer = document.getElementById("groups-group");
  if (!levelNameField || !groupsContainer) return;

  function currentLevelName() {
    var option = levelNameField.options[levelNameField.selectedIndex];
    return option ? option.value : "";
  }

  function updateRow(numberField) {
    var row = numberField.closest("tr");
    var titleField = row && row.querySelector('input[name$="-title"]');
    if (!titleField || titleField.dataset.manuallyEdited === "true") return;

    var levelName = currentLevelName();
    var number = numberField.value;
    titleField.value = levelName && number ? levelName + " Group " + number : "";
  }

  groupsContainer.addEventListener("change", function (event) {
    if (event.target.matches('select[name$="-number"]')) {
      updateRow(event.target);
    }
  });

  groupsContainer.addEventListener("input", function (event) {
    if (event.target.matches('input[name$="-title"]')) {
      event.target.dataset.manuallyEdited = "true";
    }
  });

  levelNameField.addEventListener("change", function () {
    groupsContainer.querySelectorAll('select[name$="-number"]').forEach(updateRow);
  });
});
