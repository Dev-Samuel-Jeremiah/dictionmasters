/* Keep the lessons on the platform.

   Every recording on the site is set to play only: no download button in
   the player's own menu, no right-click "Save audio as…", no dragging the
   player onto the desktop, no casting or picture-in-picture. New players
   added to a page later — a card that opens, a panel that loads — are
   caught too.

   The files themselves sit behind links that are signed and expire (see
   R2_LINK_LIFETIME_SECONDS), so a copied address stops working shortly
   after it is copied.

   Worth being straight about the limit: anything a device can play, that
   device can record. This stops casual saving and passing links around;
   it is not protection against someone determined.  */

(function () {
  "use strict";

  function lock(media) {
    if (media.dataset.guarded) return;
    media.dataset.guarded = "1";
    // Chrome and Edge read this and drop the download item from the menu.
    media.setAttribute("controlsList", "nodownload noremoteplayback noplaybackrate");
    media.setAttribute("disablePictureInPicture", "");
    media.setAttribute("disableRemotePlayback", "");
    media.setAttribute("draggable", "false");
    media.addEventListener("contextmenu", function (event) { event.preventDefault(); });
    media.addEventListener("dragstart", function (event) { event.preventDefault(); });
  }

  function sweep(root) {
    (root || document).querySelectorAll("audio, video").forEach(lock);
  }

  function watch() {
    sweep();
    if (!window.MutationObserver) return;
    new MutationObserver(function (changes) {
      changes.forEach(function (change) {
        change.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.tagName === "AUDIO" || node.tagName === "VIDEO") { lock(node); } else { sweep(node); }
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
