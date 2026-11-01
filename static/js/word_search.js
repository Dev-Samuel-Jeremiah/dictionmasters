/*
 * A Word search activity (templates/echospell/activity_detail.html).
 *
 * Drag across a word's letters, or tap its first letter and then its last:
 * the two-tap way is for small fingers and tiny grids on a phone, and Enter
 * on two letters does the same from a keyboard. A line is always straight,
 * so a shaky finger snaps to the nearest direction. A word counts whichever
 * end it's found from; finding one fills its hidden field, which is what
 * gets marked (apps/echospell/marking.py).
 */
(function () {
  var COLOURS = 6;
  var board = document.querySelector("[data-word-search]");
  if (!board) return;

  var cells = {};
  board.querySelectorAll(".word-search__cell").forEach(function (cell) {
    cells[cell.dataset.r + ":" + cell.dataset.c] = cell;
  });
  var words = Array.prototype.map.call(board.querySelectorAll("[data-word]"), function (row) {
    return { row: row, letters: row.dataset.word.toUpperCase().replace(/[^\p{L}]/gu, "") };
  });
  var foundCount = board.querySelector("[data-found]");
  var found = 0;
  var dragFrom = null;   // the cell a drag began on
  var dragEnd = null;
  var tapped = null;     // the first of two taps

  function at(cell) { return { r: Number(cell.dataset.r), c: Number(cell.dataset.c) }; }

  // Every cell from one to the other, in a straight line.
  function line(from, to) {
    var a = at(from), b = at(to);
    var dr = b.r - a.r, dc = b.c - a.c;
    var across = Math.abs(dc), down = Math.abs(dr);
    if (down > across * 2) dc = 0;
    else if (across > down * 2) dr = 0;
    else {
      var most = Math.max(across, down);
      dr = (dr < 0 ? -1 : 1) * most;
      dc = (dc < 0 ? -1 : 1) * most;
    }
    var steps = Math.max(Math.abs(dr), Math.abs(dc));
    var path = [];
    for (var i = 0; i <= steps; i++) {
      var cell = cells[(a.r + Math.sign(dr) * i) + ":" + (a.c + Math.sign(dc) * i)];
      if (cell) path.push(cell);
    }
    return path;
  }

  function clearPreview() {
    board.querySelectorAll(".is-selecting").forEach(function (cell) { cell.classList.remove("is-selecting"); });
  }

  function preview(path) {
    clearPreview();
    path.forEach(function (cell) { cell.classList.add("is-selecting"); });
  }

  function check(path) {
    var text = path.map(function (cell) { return cell.textContent; }).join("");
    var back = text.split("").reverse().join("");
    var match = words.filter(function (word) {
      return !word.done && (word.letters === text || word.letters === back);
    })[0];
    if (!match) return;
    match.done = true;
    var colour = found % COLOURS;
    path.forEach(function (cell) {
      cell.classList.add("is-found");
      cell.dataset.colour = colour;
    });
    match.row.classList.add("is-found");
    match.row.dataset.colour = colour;
    match.row.querySelector("input").value = match.row.dataset.word;
    found += 1;
    foundCount.textContent = found;
    if (found === words.length) board.classList.add("is-complete");
  }

  function cellUnder(event) {
    var hit = document.elementFromPoint(event.clientX, event.clientY);
    return hit && hit.closest ? hit.closest(".word-search__cell") : null;
  }

  function tap(cell) {
    if (tapped && tapped !== cell) {
      var path = line(tapped, cell);
      tapped.classList.remove("is-picked");
      tapped = null;
      check(path);
      return;
    }
    if (tapped) {
      tapped.classList.remove("is-picked");
      tapped = null;
      return;
    }
    tapped = cell;
    cell.classList.add("is-picked");
  }

  var grid = board.querySelector(".word-search__grid");

  grid.addEventListener("pointerdown", function (event) {
    var cell = cellUnder(event);
    if (!cell) return;
    event.preventDefault();
    dragFrom = dragEnd = cell;
    if (grid.setPointerCapture) grid.setPointerCapture(event.pointerId);
  });

  grid.addEventListener("pointermove", function (event) {
    if (!dragFrom) return;
    var cell = cellUnder(event);
    if (!cell || cell === dragEnd) return;
    dragEnd = cell;
    preview(line(dragFrom, cell));
  });

  function finish() {
    if (!dragFrom) return;
    var from = dragFrom, to = dragEnd;
    dragFrom = dragEnd = null;
    clearPreview();
    if (from === to) {
      tap(from);
      return;
    }
    if (tapped) {
      tapped.classList.remove("is-picked");
      tapped = null;
    }
    check(line(from, to));
  }

  grid.addEventListener("pointerup", finish);
  grid.addEventListener("pointercancel", function () {
    dragFrom = dragEnd = null;
    clearPreview();
  });

  // Enter or Space on a letter. A mouse or finger was already handled above.
  grid.addEventListener("click", function (event) {
    var cell = event.target.closest(".word-search__cell");
    if (cell && event.detail === 0) tap(cell);
  });
})();
