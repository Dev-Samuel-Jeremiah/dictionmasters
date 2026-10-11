/* The bell (templates/includes/header.html): opens a dropdown of things to
   do and updates (loaded from data-panel-url), and keeps the red badge up
   to date every minute while the page is open. Without JavaScript the
   bell is a link to the Notifications page. */
(function () {
  var bell = document.querySelector("[data-bell]");
  if (!bell) return;
  var button = bell.querySelector("[data-bell-button]");
  var panel = bell.querySelector("[data-bell-panel]");
  var badge = bell.querySelector("[data-bell-count]");

  function setCount(n) {
    if (n > 0) {
      badge.textContent = n > 9 ? "9+" : String(n);
      badge.hidden = false;
      button.classList.add("has-news");
      button.setAttribute("aria-label", "Notifications: " + n + " to see");
    } else {
      badge.hidden = true;
      button.classList.remove("has-news");
      button.setAttribute("aria-label", "Notifications");
    }
  }
  setCount(parseInt(badge.textContent, 10) || 0);

  function refreshCount() {
    if (document.hidden) return;
    fetch(bell.dataset.countUrl, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) setCount(data.count); })
      .catch(function () {});
  }

  function close() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
  }

  function open() {
    panel.innerHTML = '<p class="nb-loading">Loading…</p>';
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    fetch(bell.dataset.panelUrl, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
      .then(function (html) { panel.innerHTML = html; refreshCount(); })   // what it showed is now read
      .catch(function () { window.location.href = button.href; });
  }

  button.addEventListener("click", function (event) {
    event.preventDefault();
    if (panel.hidden) open(); else close();
  });
  document.addEventListener("click", function (event) {
    if (!panel.hidden && !bell.contains(event.target)) close();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) { close(); button.focus(); }
  });
  setInterval(refreshCount, 60000);
  document.addEventListener("visibilitychange", refreshCount);
})();
