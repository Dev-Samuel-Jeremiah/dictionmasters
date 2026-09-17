/* Show or hide what you're typing in a password box.

   Every password field on the page gets a small eye button beside it:
   registering, signing in, and the control room's own sign-in. Nothing
   is remembered between pages — a box always starts hidden.

   Without this script the boxes are ordinary password fields.  */

(function () {
  "use strict";

  var EYE =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">' +
    '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">' +
    '<path d="M2 12s3.6-6.5 10-6.5c1.7 0 3.2.5 4.5 1.1M22 12s-3.6 6.5-10 6.5c-1.7 0-3.2-.5-4.5-1.1" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="12" cy="12" r="3"/><path d="m4 4 16 16" stroke-linecap="round"/></svg>';

  function attach(input) {
    if (input.dataset.pwToggle) return;
    input.dataset.pwToggle = "1";

    var wrap = document.createElement("span");
    wrap.className = "pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "pw-toggle";
    button.innerHTML = EYE;
    button.title = "Show password";
    button.setAttribute("aria-label", "Show password");
    button.setAttribute("aria-pressed", "false");
    wrap.appendChild(button);

    button.addEventListener("click", function () {
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.innerHTML = showing ? EYE : EYE_OFF;
      button.title = showing ? "Show password" : "Hide password";
      button.setAttribute("aria-label", button.title);
      button.setAttribute("aria-pressed", String(!showing));
      // Carry on typing where they left off.
      var at = input.value.length;
      input.focus({ preventScroll: true });
      try { input.setSelectionRange(at, at); } catch (error) { /* some browsers refuse on a just-switched field */ }
    });
  }

  function init() {
    document.querySelectorAll('input[type="password"]').forEach(attach);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
