/* The account menu in the top bar (My dashboard, Learning tools, Log out).

   It's a <details>, so it opens and closes on its own; this only makes it
   behave like a menu: it closes when you click anywhere else, press Escape,
   or open another one.  */

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
