/* A link to something inside a folded section (<details>) opens the
   section first, so "Login details" or "Students" on the school dashboard
   always lands on what it names — also when the page is opened at #logins. */
(function () {
  "use strict";
  function openFor(hash) {
    if (!hash || hash.length < 2) return;
    var target = document.getElementById(decodeURIComponent(hash.slice(1)));
    for (var node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
    if (target) target.scrollIntoView({ block: "start" });
  }
  document.addEventListener("click", function (event) {
    var link = event.target.closest('a[href^="#"]');
    if (link) openFor(link.getAttribute("href"));
  });
  window.addEventListener("hashchange", function () { openFor(window.location.hash); });
  openFor(window.location.hash);
})();
