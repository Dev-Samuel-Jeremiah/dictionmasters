/*
 * Assembly Recitals: clicking a recital's card plays it in a popup, on top
 * of the section's list (templates/assembly_recitals/section.html). The
 * card is still a link: a new tab, or a browser without <dialog>, gets the
 * full page, which also has Present mode and the teacher's notes.
 *
 * Opening a card is a click, so browsers let the recording start at once.
 * Closing always stops it: an <audio> taken off the page keeps playing
 * unless it's paused first.
 */
(function () {
  var modal = document.querySelector("[data-recital-modal]");
  if (!modal || typeof modal.showModal !== "function") return;
  var body = modal.querySelector("[data-recital-body]");

  function open(id) {
    var content = document.getElementById(id);
    if (!content) return false;
    body.replaceChildren(content.content.cloneNode(true));
    modal.showModal();
    modal.scrollTop = 0;
    var player = body.querySelector("video") || body.querySelector("audio");
    if (player) player.play().catch(function () { /* blocked: its Play button is there */ });
    return true;
  }

  document.addEventListener("click", function (event) {
    var card = event.target.closest && event.target.closest("[data-recital-open]");
    if (!card || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    if (open(card.getAttribute("data-recital-open"))) event.preventDefault();
  });

  modal.addEventListener("click", function (event) {
    if (event.target === modal || event.target.closest("[data-recital-close]")) modal.close();
  });

  // Every way out (the ×, Esc, clicking outside) ends here.
  modal.addEventListener("close", function () {
    body.querySelectorAll("audio, video").forEach(function (player) { player.pause(); });
    body.replaceChildren();
  });
})();
