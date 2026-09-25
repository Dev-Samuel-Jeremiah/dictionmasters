/* The account menu in the top bar (My dashboard, Learning tools, Log out).

   It's a <details>, so it opens and closes on its own; this only makes it
   behave like a menu: it closes when you click anywhere else, press Escape,
   or open another one.  */

/* The menu drawer on phones and tablets: the sidebar, slid in from the left
   by the header's menu button. Closes on the X, the dimmed page, Escape or
   following a link. */
(function () {
  "use strict";

  var side = document.getElementById("px-side");
  var opener = document.querySelector("[data-drawer-open]");
  var scrim = document.querySelector(".px-scrim");
  if (!side || !opener || !scrim) return;
  var body = document.body;

  function setOpen(open) {
    body.classList.toggle("px-drawer-open", open);
    scrim.hidden = !open;
    opener.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      var first = side.querySelector("[data-drawer-close]");
      if (first) first.focus();
    }
  }

  opener.addEventListener("click", function () { setOpen(true); });
  [].slice.call(document.querySelectorAll("[data-drawer-close]")).forEach(function (el) {
    el.addEventListener("click", function () { setOpen(false); opener.focus(); });
  });
  side.addEventListener("click", function (event) {
    if (event.target.closest("a")) setOpen(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && body.classList.contains("px-drawer-open")) {
      setOpen(false);
      opener.focus();
    }
  });
  window.matchMedia("(min-width: 1100px)").addEventListener("change", function (mq) {
    if (mq.matches) setOpen(false);
  });
})();

(function () {
  "use strict";

  var menus = [].slice.call(document.querySelectorAll("[data-account-menu]"));
  if (!menus.length) return;

  function closeAll(except) {
    menus.forEach(function (menu) { if (menu !== except) menu.open = false; });
  }

  menus.forEach(function (menu) {
    menu.addEventListener("toggle", function () { if (menu.open) closeAll(menu); });
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-account-menu]")) closeAll(null);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var open = menus.filter(function (menu) { return menu.open; })[0];
    if (!open) return;
    open.open = false;
    open.querySelector("summary").focus();
  });
})();
