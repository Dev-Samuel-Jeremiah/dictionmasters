/* Student sign-up: once a school code is typed, "Your class" lists that
   school's classes (and its grades with no class yet), from
   /accounts/register/student/classes/. Without JavaScript the form still
   works: the server checks the class against the code either way. */
(function () {
  var code = document.querySelector("[data-join-code]");
  var select = document.querySelector("[data-join-class]");
  if (!code || !select) return;
  var url = select.form.getAttribute("data-classes-url");
  var timer = null, last = "";

  function fill(groups) {
    var keep = select.value;
    while (select.options.length > 1) select.remove(1);
    [].slice.call(select.querySelectorAll("optgroup")).forEach(function (g) { g.remove(); });
    groups.forEach(function (group) {
      var box = document.createElement("optgroup");
      box.label = group.label;
      group.options.forEach(function (pair) {
        var option = new Option(pair[1], pair[0]);
        option.selected = pair[0] === keep;
        box.appendChild(option);
      });
      select.appendChild(box);
    });
  }

  function load() {
    var typed = code.value.trim();
    if (typed.length < 4 || typed === last) return;
    last = typed;
    fetch(url + "?school=" + encodeURIComponent(typed), { headers: { "Accept": "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) { if (data && data.groups) fill(data.groups); })
      .catch(function () { /* keep the grades already listed */ });
  }

  code.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(load, 450); });
  code.addEventListener("change", load);
  if (code.value) load();
})();
