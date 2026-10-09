/* The sidebar's folded groups ("All courses", "All tools";
   templates/includes/app_nav.html): each stays open or closed the way it
   was left on this device, and opens by itself on one of its own pages.
   Without this script they still open and close; they just start closed. */
(function () {
  "use strict";
  document.querySelectorAll("[data-side-fold]").forEach(function (fold) {
    var key = "side-fold-" + fold.dataset.sideFold;
    var here = fold.querySelector(".is-on");
    var saved = null;
    try { saved = window.localStorage.getItem(key); } catch (error) { /* private window */ }
    if (here || saved === "open") fold.open = true;
    fold.addEventListener("toggle", function () {
      try { window.localStorage.setItem(key, fold.open ? "open" : "closed"); } catch (error) { /* fine */ }
    });
  });
})();
