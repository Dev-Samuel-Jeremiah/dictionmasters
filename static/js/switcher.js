// The account switcher (templates/accounts/_switcher.html): opens the panel,
// moves between its panes (this school > choose a school > that school's
// accounts), and asks before removing accounts from the device.
(function () {
  var dialog = document.getElementById("px-switch");
  var opener = document.querySelector("[data-switch-open]");

  // "Are you sure?" on remove buttons, here and on the log-in page.
  document.addEventListener("click", function (e) {
    // A form with data-confirm is asked when it's submitted, not here too.
    var btn = e.target.closest("button[data-confirm], a[data-confirm]");
    if (btn && !window.confirm(btn.getAttribute("data-confirm"))) e.preventDefault();
  });
  // One tap at a time: a switch button waits for the page to change.
  document.addEventListener("submit", function (e) {
    var btn = e.target.querySelector(".px-switch__pick[type=submit]");
    if (btn) btn.disabled = true;
  });

  if (!dialog || !opener) return;
  var back = dialog.querySelector("[data-switch-back]");
  var title = dialog.querySelector(".px-switch__title");
  var trail = [];

  function show(name) {
    dialog.querySelectorAll("[data-pane]").forEach(function (pane) {
      var on = pane.getAttribute("data-pane") === name;
      pane.hidden = !on;
      if (on) {
        pane.classList.remove("is-entering");
        void pane.offsetWidth;
        pane.classList.add("is-entering");
      }
    });
    back.hidden = trail.length === 0;
    title.textContent = name === "main" ? "Accounts on this device" : name === "schools" ? "Switch school" : "Switch account";
  }
  function go(name) { trail.push(currentPane()); show(name); }
  function currentPane() {
    var on = dialog.querySelector("[data-pane]:not([hidden])");
    return on ? on.getAttribute("data-pane") : "main";
  }

  opener.addEventListener("click", function () {
    trail = [];
    show("main");
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
  });
  dialog.querySelector("[data-switch-close]").addEventListener("click", function () { dialog.close(); });
  back.addEventListener("click", function () { show(trail.pop() || "main"); });
  dialog.addEventListener("click", function (e) {
    if (e.target === dialog) dialog.close();            // a tap on the backdrop
    var to = e.target.closest("[data-go]");
    if (to) go(to.getAttribute("data-go"));
  });
})();
