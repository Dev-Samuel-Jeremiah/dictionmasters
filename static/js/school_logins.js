/* School dashboard: teachers' and students' logins (apps/schools/logins.py).

   "Login" beside a person opens their sign-in name and password, with a
   reset. With people ticked, the bar downloads their logins, or resets
   their passwords and downloads the new ones, as Excel. Everything needs
   the admin's password confirmed first (the Login details panel). */
(function () {
  "use strict";

  var csrf = (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";
  var dialog = document.querySelector("[data-sl-login]");

  function open(d) { if (d.showModal) d.showModal(); else d.setAttribute("open", ""); }
  function close(d) { if (d.close) d.close(); else d.removeAttribute("open"); }

  function post(url, form) {
    form.append("csrfmiddlewaretoken", csrf);
    return fetch(url, { method: "POST", body: form, credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } });
  }

  function locked() {
    window.alert("Confirm your password in Login details first, then try again.");
    var panel = document.getElementById("logins");
    if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
    var field = document.getElementById("sl-admin-password");
    if (field) field.focus({ preventScroll: true });
  }

  // ------------------------------------------------- one person's login
  if (dialog) {
    var nameEl = dialog.querySelector("[data-sl-login-name]");
    var userEl = dialog.querySelector("[data-sl-login-user]");
    var passEl = dialog.querySelector("[data-sl-login-pass]");
    var noteEl = dialog.querySelector("[data-sl-login-note]");
    var body = dialog.querySelector("[data-sl-login-body]");
    var lockedNote = dialog.querySelector("[data-sl-login-locked]");
    var newPass = dialog.querySelector("[data-sl-new-pass]");
    var resetGo = dialog.querySelector("[data-sl-reset-go]");
    var details = dialog.querySelector(".sl-reset");
    var resetUrl = "";

    var show = function (data, isNew) {
      nameEl.textContent = data.name + (data.role ? " · " + data.role : "");
      userEl.textContent = data.login;
      passEl.textContent = data.password || "Not available";
      passEl.classList.toggle("is-missing", !data.password);
      noteEl.textContent = isNew
        ? "✓ New password set. Share it with them — their old one no longer works."
        : (data.available ? "" : "This password was set before passwords could be shown again. Reset it to give them one you can see and share.");
      noteEl.classList.toggle("is-good", !!isNew);
    };

    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-sl-login-open]");
      if (!button) return;
      resetUrl = button.dataset.resetUrl;
      details.open = false;
      newPass.value = "";
      fetch(button.dataset.url, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (result) {
          body.hidden = !result.ok;
          lockedNote.hidden = result.ok;
          if (result.ok) show(result.data, false);
          else nameEl.textContent = "Login details are locked";
          open(dialog);
        })
        .catch(function () { window.alert("That login couldn't be loaded. Check your connection and try again."); });
    });

    resetGo.addEventListener("click", function () {
      if (!window.confirm("Reset this password? They'll need the new one to sign in.")) return;
      resetGo.disabled = true;
      var form = new FormData();
      form.append("password", newPass.value);
      post(resetUrl, form)
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (result) {
          resetGo.disabled = false;
          if (result.data.locked) { close(dialog); locked(); return; }
          if (!result.ok) { noteEl.textContent = result.data.error; noteEl.classList.remove("is-good"); return; }
          show(result.data, true);
          details.open = false;
          newPass.value = "";
        })
        .catch(function () { resetGo.disabled = false; noteEl.textContent = "The password couldn't be reset. Please try again."; });
    });

    dialog.querySelector("[data-sl-copy]").addEventListener("click", function (event) {
      var text = "Username: " + userEl.textContent + "\nPassword: " + passEl.textContent;
      var button = event.currentTarget;
      var done = function () { button.textContent = "Copied ✓"; window.setTimeout(function () { button.textContent = "Copy both"; }, 1600); };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done);
      else window.prompt("Copy the login:", text);
    });
    dialog.querySelector("[data-sl-login-close]").addEventListener("click", function () { close(dialog); });
    dialog.addEventListener("click", function (event) { if (event.target === dialog) close(dialog); });
  }

  // ------------------------------------------- everyone ticked: Excel
  function ticked(list) {
    return Array.prototype.filter.call(list.querySelectorAll("[data-sl-row]"), function (row) {
      return !row.hidden && row.querySelector("[data-sl-pick]").checked;
    }).map(function (row) { return row.querySelector("[data-sl-pick]").value; });
  }

  function download(response, fallbackName) {
    var type = response.headers.get("content-type") || "";
    if (response.status === 403 || type.indexOf("json") > -1) { locked(); return Promise.resolve(false); }
    if (!response.ok || type.indexOf("spreadsheet") < 0) throw new Error("The sheet couldn't be made.");
    var name = ((response.headers.get("content-disposition") || "").match(/filename="([^"]+)"/) || [])[1] || fallbackName;
    return response.blob().then(function (blob) {
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      return true;
    });
  }

  document.querySelectorAll("[data-sl]").forEach(function (list) {
    var role = list.dataset.role;
    var getLogins = list.querySelector("[data-sl-logins]");
    var reset = list.querySelector("[data-sl-reset]");

    function send(button, extra, confirmText, fileName, doneText) {
      var ids = ticked(list);
      if (!ids.length) return;
      if (confirmText && !window.confirm(confirmText.replace("{n}", ids.length))) return;
      var form = new FormData();
      ids.forEach(function (id) { form.append("members", id); });
      Object.keys(extra).forEach(function (key) { form.append(key, extra[key]); });
      var label = button.textContent;
      button.disabled = true;
      button.textContent = "Preparing…";
      post(button.dataset.url, form)
        .then(function (response) { return download(response, fileName); })
        .then(function (ok) {
          button.disabled = false;
          button.textContent = ok && doneText ? doneText : label;
          if (ok && doneText) window.setTimeout(function () { button.textContent = label; }, 3000);
        })
        .catch(function (problem) { button.disabled = false; button.textContent = label; window.alert(problem.message); });
    }

    if (getLogins) getLogins.addEventListener("click", function () {
      send(getLogins, { picked: "1", role: role }, "", role + "-logins.xlsx", "✓ Downloaded");
    });
    if (reset) reset.addEventListener("click", function () {
      send(reset, {}, "Give {n} " + role + "(s) new passwords? Their old passwords will stop working, and a sheet of the new ones will download.",
           role + "-new-passwords.xlsx", "✓ Reset — sheet downloaded");
    });
  });
})();
