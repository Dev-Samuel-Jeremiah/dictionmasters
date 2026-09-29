/* The Diction Library reader: a book opens right in its page, with the
   Download button under it — no new tab.

   The file always comes from this site (diction_library:file), so the same
   "who may see this" check as the page applies. How it is shown depends on
   the file (data-reader, set by diction_library.views.reader_for):

     pdf   — PDF.js draws each page, so it works on phones too (Android
             browsers can't show a PDF inside a page). Pages are drawn as
             they scroll into view, sharp at any screen density.
     epub  — epub.js, a page at a time, with Prev / Next (and arrow keys).
     docx  — mammoth turns the Word document into readable text.
     text  — the text itself.
     image — the picture.

   The reading libraries are only fetched when a book is opened. */
(function () {
  "use strict";

  var LIBS = {
    pdf: ["https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"],
    pdfWorker: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js",
    epub: ["https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js",
           "https://cdn.jsdelivr.net/npm/epubjs@0.3.93/dist/epub.min.js"],
    docx: ["https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js"]
  };

  function load(urls) {
    return urls.reduce(function (chain, url) {
      return chain.then(function () {
        if (document.querySelector('script[data-lr-lib="' + url + '"]')) return null;
        return new Promise(function (resolve, reject) {
          var tag = document.createElement("script");
          tag.src = url;
          tag.async = true;
          tag.setAttribute("data-lr-lib", url);
          tag.onload = resolve;
          tag.onerror = function () { reject(new Error("The reader couldn't load. Check your connection and try again.")); };
          document.head.appendChild(tag);
        });
      });
    }, Promise.resolve());
  }

  function fetchBytes(src) {
    return fetch(src, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("The book couldn't be opened (" + response.status + ").");
      return response.arrayBuffer();
    });
  }

  function setUp(box) {
    var kind = box.getAttribute("data-reader");
    var src = box.getAttribute("data-src");
    var openBtn = box.querySelector("[data-lr-open]");
    if (!kind || !openBtn) return;
    var stage = box.querySelector("[data-lr-stage]");
    var view = box.querySelector("[data-lr-view]");
    var status = box.querySelector("[data-lr-status]");
    var download = box.querySelector("[data-lr-download]");
    var prev = box.querySelector("[data-lr-prev]"), next = box.querySelector("[data-lr-next]");
    var zoomIn = box.querySelector("[data-lr-zoom-in]"), zoomOut = box.querySelector("[data-lr-zoom-out]");
    var opened = false;

    function say(text) { status.textContent = text; }

    function open() {
      openBtn.hidden = true;
      stage.hidden = false;
      download.hidden = false;
      stage.scrollIntoView({ behavior: "smooth", block: "start" });
      if (opened) return;
      opened = true;
      var show = { pdf: showPdf, epub: showEpub, docx: showDocx, text: showText, image: showImage }[kind];
      Promise.resolve().then(show).catch(function (error) {
        say(error.message || "The book couldn't be opened.");
        view.innerHTML = '<p class="lr__fail">This book couldn\'t be shown here. Use Download below to read it on your device.</p>';
      });
    }

    function close() {
      stage.hidden = true;
      openBtn.hidden = false;
      openBtn.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    // ---- PDF: each page drawn when it comes into view
    function showPdf() {
      say("Opening…");
      return load(LIBS.pdf).then(function () {
        var lib = window.pdfjsLib;
        lib.GlobalWorkerOptions.workerSrc = LIBS.pdfWorker;
        return lib.getDocument({ url: src, withCredentials: true }).promise;
      }).then(function (pdf) {
        var zoom = 1, pages = [], drawn = {};
        zoomIn.hidden = zoomOut.hidden = false;
        view.classList.add("lr__view--pdf");
        for (var n = 1; n <= pdf.numPages; n++) {
          var page = document.createElement("div");
          page.className = "lr__page";
          page.dataset.page = n;
          page.style.aspectRatio = "0.707";          // A4 until the real size is known
          view.appendChild(page);
          pages.push(page);
        }
        function draw(page) {
          var n = Number(page.dataset.page);
          if (drawn[n] === zoom) return;
          drawn[n] = zoom;
          pdf.getPage(n).then(function (p) {
            var base = p.getViewport({ scale: 1 });
            var width = Math.min(view.clientWidth - 2, 1100) * zoom;
            var ratio = window.devicePixelRatio || 1;
            var viewport = p.getViewport({ scale: width / base.width * ratio });
            var canvas = document.createElement("canvas");
            canvas.width = viewport.width; canvas.height = viewport.height;
            canvas.style.width = width + "px";
            canvas.setAttribute("aria-label", "Page " + n);
            page.style.aspectRatio = base.width + " / " + base.height;
            page.style.width = width + "px";
            return p.render({ canvasContext: canvas.getContext("2d"), viewport: viewport }).promise.then(function () {
              page.innerHTML = "";
              page.appendChild(canvas);
            });
          });
        }
        // Drawn as they come near; let go of when far away, so a long book
        // never holds more than a few pages in memory (phones included).
        var near = window.IntersectionObserver ? new IntersectionObserver(function (entries) {
          entries.forEach(function (e) { if (e.isIntersecting) draw(e.target); });
        }, { root: view, rootMargin: "800px 0px" }) : null;
        var far = window.IntersectionObserver ? new IntersectionObserver(function (entries) {
          entries.forEach(function (e) {
            if (e.isIntersecting) return;
            var n = e.target.dataset.page;
            if (drawn[n] !== undefined) { delete drawn[n]; e.target.innerHTML = ""; }
          });
        }, { root: view, rootMargin: "4000px 0px" }) : null;
        pages.forEach(function (page) {
          if (near) { near.observe(page); far.observe(page); } else draw(page);
        });
        function where() {
          var box = view.getBoundingClientRect(), mid = box.top + Math.min(box.height, window.innerHeight) / 2, at = 1;
          pages.forEach(function (page) { if (page.getBoundingClientRect().top < mid) at = Number(page.dataset.page); });
          say("Page " + at + " of " + pdf.numPages);
        }
        window.addEventListener("scroll", where, { passive: true });
        view.addEventListener("scroll", where, { passive: true });
        where();
        function rezoom(by) {
          zoom = Math.min(2.5, Math.max(0.6, Math.round((zoom + by) * 10) / 10));
          pages.forEach(function (page) {
            var r = page.getBoundingClientRect();
            if (r.bottom > -600 && r.top < window.innerHeight + 600) draw(page);
            else { delete drawn[page.dataset.page]; page.style.width = Math.min(view.clientWidth - 2, 1100) * zoom + "px"; }
          });
        }
        zoomIn.addEventListener("click", function () { rezoom(0.2); });
        zoomOut.addEventListener("click", function () { rezoom(-0.2); });
        var resize;
        window.addEventListener("resize", function () {
          clearTimeout(resize);
          resize = setTimeout(function () { drawn = {}; pages.forEach(function (page) {
            var r = page.getBoundingClientRect();
            if (r.bottom > -600 && r.top < window.innerHeight + 600) draw(page);
          }); }, 250);
        });
      });
    }

    // ---- EPUB: one page at a time
    function showEpub() {
      say("Opening…");
      return Promise.all([load(LIBS.epub), fetchBytes(src)]).then(function (both) {
        view.classList.add("lr__view--epub");
        var book = window.ePub(both[1]);
        var rendition = book.renderTo(view, { width: "100%", height: "100%", spread: "none" });
        prev.hidden = next.hidden = false;
        prev.addEventListener("click", function () { rendition.prev(); });
        next.addEventListener("click", function () { rendition.next(); });
        document.addEventListener("keydown", function (e) {
          if (stage.hidden) return;
          if (e.key === "ArrowLeft") rendition.prev();
          if (e.key === "ArrowRight") rendition.next();
        });
        book.ready.then(function () { return book.locations.generate(1200); }).then(function () {
          rendition.on("relocated", function (where) {
            var pct = Math.round((where.start.percentage || 0) * 100);
            say(pct + "% read");
          });
        });
        return rendition.display().then(function () { say("Use Prev and Next to turn the page"); });
      });
    }

    // ---- Word (.docx): its text, readable
    function showDocx() {
      say("Opening…");
      return Promise.all([load(LIBS.docx), fetchBytes(src)]).then(function (both) {
        return window.mammoth.convertToHtml({ arrayBuffer: both[1] });
      }).then(function (result) {
        view.classList.add("lr__view--doc");
        var doc = document.createElement("div");
        doc.className = "lr__doc dm-rich-content";
        doc.innerHTML = result.value;
        doc.querySelectorAll("script, iframe, object, embed").forEach(function (n) { n.remove(); });
        view.appendChild(doc);
        say("Word document");
      });
    }

    // ---- plain text
    function showText() {
      say("Opening…");
      return fetch(src, { credentials: "same-origin" }).then(function (response) {
        if (!response.ok) throw new Error("The book couldn't be opened (" + response.status + ").");
        return response.text();
      }).then(function (text) {
        view.classList.add("lr__view--doc");
        var doc = document.createElement("div");
        doc.className = "lr__doc lr__doc--text";
        doc.textContent = text;
        view.appendChild(doc);
        say("Text");
      });
    }

    // ---- a picture
    function showImage() {
      var img = document.createElement("img");
      img.className = "lr__image";
      img.alt = box.getAttribute("data-title") || "";
      img.src = src;
      view.appendChild(img);
      say("Picture");
    }

    openBtn.addEventListener("click", open);
    box.querySelector("[data-lr-close]").addEventListener("click", close);
    box.querySelector("[data-lr-full]").addEventListener("click", function () {
      if (document.fullscreenElement) { document.exitFullscreen(); return; }
      if (stage.requestFullscreen) stage.requestFullscreen().catch(function () {});
    });
  }

  function start() { document.querySelectorAll("[data-lib-reader]").forEach(setUp); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
