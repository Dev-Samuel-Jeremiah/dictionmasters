/*
 * Control room: show only the fields an activity's type needs
 * (apps/manage/kind_fields.py). Reads the guide the page carries and,
 * whenever the Activity type (or, for a question, its activity) changes,
 * hides the fields that type doesn't use and rewords the hints.
 */
(function () {
  var source = document.getElementById("kind-guide");
  if (!source) return;
  var guide = JSON.parse(source.textContent);
  var form = document.querySelector(".cr-form");
  if (!form) return;

  function fieldBox(name) {
    var input = form.querySelector('[name="' + name + '"]');
    return input ? input.closest(".cr-field") : null;
  }

  // A line under the chooser saying what this type is.
  function summaryBox(anchor) {
    var box = document.getElementById("kind-summary");
    if (!box) {
      box = document.createElement("p");
      box.id = "kind-summary";
      box.className = "cr-kindnote";
      anchor.appendChild(box);
    }
    return box;
  }

  if (!guide.select) {
    // The type is already fixed: the form was built with only its fields.
    var first = form.querySelector(".cr-field");
    if (first && guide.summary) {
      summaryBox(first.parentNode).textContent = guide.summary;
      first.parentNode.insertBefore(document.getElementById("kind-summary"), first);
    }
    return;
  }

  var select = form.querySelector('[name="' + guide.select + '"]');
  if (!select) return;
  var selectBox = select.closest(".cr-field");
  var originalHelp = {};
  guide.managed.forEach(function (name) {
    var box = fieldBox(name);
    var help = box && box.querySelector(".cr-help");
    originalHelp[name] = help ? help.textContent : "";
  });

  function apply() {
    var rules = guide.by_value[select.value];
    var note = summaryBox(selectBox);
    note.textContent = rules ? rules.summary : "";
    note.hidden = !rules;
    guide.managed.forEach(function (name) {
      var box = fieldBox(name);
      if (!box) return;
      // Nothing chosen yet: show everything rather than guess.
      var used = !rules || rules.fields.indexOf(name) !== -1;
      box.hidden = !used;
      var help = box.querySelector(".cr-help");
      var text = rules && rules.help && rules.help[name];
      if (help) help.textContent = text || originalHelp[name];
    });
    if (rules && rules.placeholder) {
      Object.keys(rules.placeholder).forEach(function (name) {
        var input = form.querySelector('[name="' + name + '"]');
        if (input) input.placeholder = "Leave blank to use: " + rules.placeholder[name];
      });
    }
  }

  select.addEventListener("change", apply);
  apply();
})();
