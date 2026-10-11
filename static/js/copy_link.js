/* "Copy link" buttons: a [data-copy] button copies the [data-copy-source]
   field beside it (inside the same [data-copy-box]), or selects it for
   copying by hand where the clipboard isn't available. */
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-copy]");
  if (!button) return;
  var field = button.closest("[data-copy-box]").querySelector("[data-copy-source]");
  var label = button.textContent;
  var done = function () { button.textContent = "Copied ✓"; setTimeout(function () { button.textContent = label; }, 1800); };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(field.value).then(done, function () { field.select(); });
  } else {
    field.select();
    try { document.execCommand("copy"); done(); } catch (err) { /* left selected to copy by hand */ }
  }
});
