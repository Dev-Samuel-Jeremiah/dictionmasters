(function () {
  var list = document.querySelector("[data-offline-pages]");
  if (!list || !("serviceWorker" in navigator)) return;
  function show(pages) {
    list.textContent = "";
    if (!pages || !pages.length) {
      var empty = document.createElement("li");
      empty.className = "saved__empty";
      empty.textContent = "Browse lessons while online and they will appear here for offline reading.";
      list.appendChild(empty);
      return;
    }
    pages.sort(function (a, b) { return a.label.localeCompare(b.label); });
    pages.forEach(function (page) {
      var item = document.createElement("li");
      var link = document.createElement("a");
      link.href = page.url;
      link.textContent = page.label;
      item.appendChild(link);
      list.appendChild(item);
    });
  }
  function requestPages(worker) {
    var channel = new MessageChannel();
    channel.port1.onmessage = function (event) { show(event.data); channel.port1.close(); };
    worker.postMessage("offline-pages", [channel.port2]);
  }
  if (navigator.serviceWorker.controller) requestPages(navigator.serviceWorker.controller);
  else navigator.serviceWorker.ready.then(function (registration) {
    if (registration.active) requestPages(registration.active);
  });
})();
