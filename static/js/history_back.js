/* Use browser history for a previous page on this site, while keeping a
   real link destination for direct visits and no-JavaScript browsers. */
(function () {
  "use strict";
  document.querySelectorAll("[data-history-back]").forEach(function (link) {
    link.addEventListener("click", function (event) {
      if (!document.referrer || window.history.length < 2) return;
      try {
        if (new URL(document.referrer).origin === window.location.origin) {
          event.preventDefault();
          window.history.back();
        }
      } catch (error) { /* use the link's fallback */ }
    });
  });
})();
