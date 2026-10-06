/* A form marked data-submit-once is sent once: a second tap while the first
   is on its way (a slow phone, an impatient finger) is ignored, so a sign-up
   can never be made twice. If nothing happens for a while (the connection
   dropped), or the page is come back to, the button works again. */
(function () {
  "use strict";
  var RETRY_AFTER = 15000;

  function reset(form) {
    delete form.dataset.sending;
    form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (button) {
      button.disabled = false;
      if (button.dataset.label) { button.innerHTML = button.dataset.label; delete button.dataset.label; }
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("[data-submit-once]")) return;
    if (form.dataset.sending) { event.preventDefault(); return; }
    form.dataset.sending = "1";
    // Disabled a moment later, so the button's own value still goes with the form.
    window.setTimeout(function () {
      form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (button) {
        button.dataset.label = button.innerHTML;
        button.disabled = true;
        button.textContent = "Please wait…";
      });
    }, 0);
    window.setTimeout(function () { reset(form); }, RETRY_AFTER);
  }, true);

  // Back to the page from the browser's history: ready to use again.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-submit-once][data-sending]").forEach(reset);
  });
})();
