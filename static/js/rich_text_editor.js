/*
 * Diction Masters rich text editor.
 *
 * Upgrades any <textarea data-rich-text="true"> into a formatting editor and
 * keeps the textarea's value in sync, so forms post exactly as before. The
 * server (apps/manage/rich_text.py) sanitizes every submission; the cleaning
 * here only keeps what the author sees close to what learners will see.
 */
(function () {
  "use strict";

  var SYMBOLS = ["æ", "ɑ", "ɒ", "ə", "ɛ", "ɜː", "ɪ", "iː", "ʊ", "uː", "ʌ", "ɔː", "θ", "ð", "ŋ", "ʃ", "ʒ", "tʃ", "dʒ", "ˈ", "ˌ", "ː",
    "…", "—", "–", "‘", "’", "“", "”", "£", "€", "©", "™", "→", "←", "±", "×", "÷", "°", "•"];
  var SIZES = [["12px", "Small"], ["14px", "14"], ["16px", "Normal"], ["18px", "18"], ["22px", "Large"], ["28px", "28"], ["36px", "36"]];
  var FONTS = [["Georgia, serif", "Georgia"], ["Arial, sans-serif", "Arial"], ["Times New Roman, serif", "Times New Roman"],
    ["Verdana, sans-serif", "Verdana"], ["Courier New, monospace", "Monospace"]];
  var BLOCKS = [["p", "Paragraph"], ["h2", "Heading 2"], ["h3", "Heading 3"], ["h4", "Heading 4"], ["blockquote", "Quote"], ["pre", "Code block"]];

  // Mirrors ALLOWED_TAGS in apps/manage/rich_text.py.
  var ALLOWED = { a: 1, b: 1, blockquote: 1, br: 1, code: 1, del: 1, div: 1, em: 1, h2: 1, h3: 1, h4: 1, hr: 1, i: 1, li: 1, mark: 1,
    ol: 1, p: 1, pre: 1, s: 1, span: 1, strong: 1, sub: 1, sup: 1, table: 1, tbody: 1, td: 1, th: 1, thead: 1, tr: 1, u: 1, ul: 1 };
  var DROP = { script: 1, style: 1, iframe: 1, object: 1, embed: 1, svg: 1, math: 1, template: 1, head: 1, title: 1, meta: 1, link: 1, img: 1, picture: 1, video: 1, audio: 1 };
  var RENAME = { h1: "h2", h5: "h4", h6: "h4", strike: "s", font: "span", section: "div", article: "div", header: "div", footer: "div" };
  var PASTE_STYLES = ["color", "background-color", "text-align"];

  var ICONS = {
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    bold: '<path d="M7 4h7a4 4 0 0 1 0 8H7z"/><path d="M7 12h8a4 4 0 0 1 0 8H7z"/>',
    italic: '<path d="M19 4h-9M14 20H5M15 4 9 20"/>',
    underline: '<path d="M6 4v6a6 6 0 0 0 12 0V4"/><path d="M4 20h16"/>',
    strike: '<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/><path d="M4 12h16"/>',
    sub: '<path d="m4 5 8 8M12 5l-8 8"/><path d="M20 19h-4c0-1.5.44-2 1.5-2.5S20 15.33 20 14c0-.47-.17-.93-.48-1.29a2.11 2.11 0 0 0-2.62-.44c-.42.24-.74.62-.9 1.07"/>',
    sup: '<path d="m4 19 8-8M12 19l-8-8"/><path d="M20 12h-4c0-1.5.44-2 1.5-2.5S20 8.33 20 7c0-.47-.17-.93-.48-1.29a2.11 2.11 0 0 0-2.62-.44c-.42.24-.74.62-.9 1.07"/>',
    ul: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    ol: '<path d="M10 6h10M10 12h10M10 18h10"/><path d="M4 6h1v4M4 10h2M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
    outdent: '<path d="M21 12H11M21 6H11M21 18H11"/><path d="m7 8-4 4 4 4"/>',
    indent: '<path d="M21 12H11M21 6H11M21 18H11"/><path d="m3 8 4 4-4 4"/>',
    left: '<path d="M21 6H3M15 12H3M17 18H3"/>',
    center: '<path d="M21 6H3M17 12H7M19 18H5"/>',
    right: '<path d="M21 6H3M21 12H9M21 18H7"/>',
    justify: '<path d="M3 6h18M3 12h18M3 18h18"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    unlink: '<path d="m18.84 12.25 1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="m5.17 11.75-1.71 1.71a5 5 0 0 0 7.07 7.07l1.71-1.71"/><path d="M8 2v3M2 8h3M16 22v-3M22 16h-3"/>',
    table: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M12 3v18"/>',
    hr: '<path d="M3 12h18"/><path d="M8 6h8M8 18h8" opacity=".45"/>',
    clear: '<path d="M4 7V4h16v3M9 20h6M12 4 9.5 12"/><path d="m15 15 6 6M21 15l-6 6"/>',
    symbols: '<path d="M5 20h4v-2.5a7 7 0 1 1 6 0V20h4"/>',
    expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    collapse: '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>'
  };

  var uid = 0;

  function make(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function icon(name) {
    var span = make("span", { class: "dm-rt-icon", "aria-hidden": "true" });
    span.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" focusable="false">' + ICONS[name] + "</svg>";
    return span;
  }

  function button(opts) {
    var node = make("button", { type: "button", class: "dm-rt-btn" + (opts.cls ? " " + opts.cls : ""), title: opts.title, "aria-label": opts.label || opts.title });
    if (opts.icon) node.appendChild(icon(opts.icon));
    if (opts.text) node.appendChild(make("span", { class: "dm-rt-btn__text" }, opts.text));
    if (opts.action) node.dataset.action = opts.action;
    if (opts.cmd) node.dataset.cmd = opts.cmd;
    if (opts.state) { node.dataset.state = opts.state; node.setAttribute("aria-pressed", "false"); }
    if (opts.value !== undefined) node.dataset.value = opts.value;
    return node;
  }

  function escapeHtml(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Legacy plain text: blank lines separate paragraphs, single newlines break.
  function plainToHtml(value) {
    var paragraphs = value.replace(/\r\n?/g, "\n").split(/\n\s*\n/).filter(function (p) { return p.trim(); });
    return paragraphs.map(function (p) { return "<p>" + escapeHtml(p.trim()).replace(/\n/g, "<br>") + "</p>"; }).join("");
  }

  function hasContent(root) {
    return !!((root.textContent || "").replace(/ /g, " ").trim() || root.querySelector("hr, table"));
  }

  function safeHref(value) {
    value = (value || "").trim();
    if (!value) return "";
    if (/^(https?:|mailto:|tel:)/i.test(value) || /^[\/#?]/.test(value)) return value;
    if (/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::\d+)?(?:\/\S*)?$/i.test(value) && value.indexOf(".") > 0) return "https://" + value;
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return "mailto:" + value;
    return "";
  }

  // Cleans pasted HTML (Word, Google Docs, web pages) down to the tags and
  // inline styles the platform supports. Returns [html, droppedMedia].
  function cleanPastedHtml(markup) {
    var doc = new DOMParser().parseFromString(markup, "text/html");
    var dropped = !!doc.body.querySelector("img, picture, video, audio, iframe, svg");
    var out = document.createElement("div");

    function walk(node, parent) {
      Array.prototype.forEach.call(node.childNodes, function (child) {
        if (child.nodeType === 3) { parent.appendChild(document.createTextNode(child.nodeValue)); return; }
        if (child.nodeType !== 1) return;
        var tag = child.tagName.toLowerCase();
        if (DROP[tag]) return;
        tag = RENAME[tag] || tag;
        var style = child.getAttribute("style") || "";
        // Google Docs wraps a whole paste in <b style="font-weight:normal">.
        if ((tag === "b" || tag === "strong") && /font-weight\s*:\s*(normal|400)/i.test(style)) tag = "span";
        if (!ALLOWED[tag]) { walk(child, parent); return; }

        var target = parent;
        // Inline formatting expressed as styles becomes semantic markup.
        if (tag === "span") {
          if (/font-weight\s*:\s*(bold|[6-9]00)/i.test(style)) target = target.appendChild(document.createElement("strong"));
          if (/font-style\s*:\s*italic/i.test(style)) target = target.appendChild(document.createElement("em"));
          if (/text-decoration[^;]*underline/i.test(style)) target = target.appendChild(document.createElement("u"));
          if (/text-decoration[^;]*line-through/i.test(style)) target = target.appendChild(document.createElement("s"));
        }
        var el = document.createElement(tag);
        if (tag === "a") {
          var href = safeHref(child.getAttribute("href"));
          if (href) el.setAttribute("href", href);
        }
        var kept = [];
        PASTE_STYLES.forEach(function (prop) {
          var value = child.style && child.style.getPropertyValue(prop);
          if (!value) return;
          // Pasted black text and white backgrounds are page defaults, not formatting.
          if (prop === "color" && /^(rgb\(0, 0, 0\)|#000000|black|windowtext)$/i.test(value)) return;
          if (prop === "background-color" && /^(transparent|rgba\(0, 0, 0, 0\)|rgb\(255, 255, 255\)|#ffffff|white)$/i.test(value)) return;
          if (prop === "text-align" && (value === "left" || value === "start")) return;
          kept.push(prop + ": " + value);
        });
        if (kept.length && tag !== "a") el.setAttribute("style", kept.join("; "));
        target.appendChild(el);
        walk(child, el);
        // A span that kept nothing is noise; hoist its children.
        if (el.tagName === "SPAN" && !el.getAttribute("style")) {
          while (el.firstChild) el.parentNode.insertBefore(el.firstChild, el);
          el.parentNode.removeChild(el);
        }
      });
    }
    walk(doc.body, out);
    // Word leaves empty paragraphs between every real one.
    Array.prototype.forEach.call(out.querySelectorAll("p, div"), function (block) {
      if (!hasContent(block) && !block.querySelector("br")) block.parentNode.removeChild(block);
    });
    return [out.innerHTML, dropped];
  }

  function exec(command, value, css) {
    try { document.execCommand("styleWithCSS", false, !!css); } catch (_e) { /* optional */ }
    return document.execCommand(command, false, value === undefined ? null : value);
  }

  function attach(source) {
    if (source.dataset.richTextReady || source.dataset.richText !== "true" || source.disabled || source.readOnly) return;
    // Django Admin clones empty inline rows. Leave the prototype untouched so
    // each inserted row is initialized with its own editor.
    if (source.closest(".empty-form")) return;
    source.dataset.richTextReady = "true";
    uid += 1;
    var id = source.id || "dm-rt-" + uid;
    if (!source.id) source.id = id;

    // An editor inside a <label> would forward every click on the writing
    // area to the label's first control (the Undo button). Unwrap it.
    var wrapping = source.closest("label");
    if (wrapping && !wrapping.htmlFor) {
      var unwrapped = document.createElement("div");
      Array.prototype.forEach.call(wrapping.attributes, function (attr) { unwrapped.setAttribute(attr.name, attr.value); });
      while (wrapping.firstChild) unwrapped.appendChild(wrapping.firstChild);
      wrapping.parentNode.replaceChild(unwrapped, wrapping);
      var caption = unwrapped.querySelector("span");
      if (caption) {
        var captionLabel = make("label", { for: id, class: caption.className || "" });
        captionLabel.textContent = caption.textContent;
        caption.parentNode.replaceChild(captionLabel, caption);
      }
    }

    var host = make("div", { class: "dm-rich-editor" });
    var toolbar = make("div", { class: "dm-rt-toolbar", role: "toolbar", "aria-label": "Text formatting", "aria-controls": id + "-surface" });
    var surface = make("div", {
      id: id + "-surface",
      class: "dm-rt-surface",
      contenteditable: "true",
      role: "textbox",
      "aria-multiline": "true",
      spellcheck: "true",
      "data-placeholder": source.getAttribute("placeholder") || "Start writing…"
    });
    var panel = make("div", { class: "dm-rt-panel", hidden: "" });
    var footer = make("div", { class: "dm-rt-footer" });
    var status = make("span", { class: "dm-rt-hint", role: "status" }, "Formatting is shown to learners.");
    var count = make("span", { class: "dm-rt-count" }, "0 words");
    var defaultHint = status.textContent;
    host.style.setProperty("--rt-placeholder", JSON.stringify(surface.getAttribute("data-placeholder")));

    var label = document.querySelector('label[for="' + CSS.escape(id) + '"]');
    if (label) {
      if (!label.id) label.id = id + "-label";
      surface.setAttribute("aria-labelledby", label.id);
      // The label points at the hidden textarea; send its clicks to the editor.
      label.addEventListener("click", function (event) { event.preventDefault(); surface.focus(); });
    } else {
      surface.setAttribute("aria-label", source.getAttribute("aria-label") || "Rich text");
    }

    function group() {
      var box = make("div", { class: "dm-rt-group", role: "group" });
      toolbar.appendChild(box);
      return box;
    }

    var g = group();
    g.appendChild(button({ icon: "undo", title: "Undo (Ctrl+Z)", label: "Undo", action: "command", cmd: "undo" }));
    g.appendChild(button({ icon: "redo", title: "Redo (Ctrl+Y)", label: "Redo", action: "command", cmd: "redo" }));

    g = group();
    var blockSelect = make("select", { class: "dm-rt-select dm-rt-block", "aria-label": "Paragraph style", title: "Paragraph style", "data-action": "block" });
    BLOCKS.forEach(function (b) { blockSelect.appendChild(make("option", { value: b[0] }, b[1])); });
    g.appendChild(blockSelect);
    var sizeSelect = make("select", { class: "dm-rt-select dm-rt-size", "aria-label": "Text size", title: "Text size", "data-action": "size" });
    sizeSelect.appendChild(make("option", { value: "" }, "Size"));
    SIZES.forEach(function (s) { sizeSelect.appendChild(make("option", { value: s[0] }, s[1])); });
    g.appendChild(sizeSelect);
    var fontSelect = make("select", { class: "dm-rt-select dm-rt-font", "aria-label": "Font", title: "Font", "data-action": "font" });
    fontSelect.appendChild(make("option", { value: "" }, "Font"));
    FONTS.forEach(function (f) { fontSelect.appendChild(make("option", { value: f[0] }, f[1])); });
    g.appendChild(fontSelect);

    g = group();
    [["bold", "Bold (Ctrl+B)", "Bold", "bold"], ["italic", "Italic (Ctrl+I)", "Italic", "italic"], ["underline", "Underline (Ctrl+U)", "Underline", "underline"],
      ["strike", "Strikethrough", "Strikethrough", "strikeThrough"], ["sub", "Subscript", "Subscript", "subscript"], ["sup", "Superscript", "Superscript", "superscript"]]
      .forEach(function (b) { g.appendChild(button({ icon: b[0], title: b[1], label: b[2], action: "command", cmd: b[3], state: b[3] })); });

    g = group();
    var colorInput = make("input", { type: "color", value: "#7A5600", tabindex: "-1", "aria-hidden": "true", class: "dm-rt-color-input", "data-action": "color" });
    var colorBtn = button({ text: "A", title: "Text colour", action: "pick", value: "color", cls: "dm-rt-swatch" });
    colorBtn.style.setProperty("--swatch", colorInput.value);
    var markInput = make("input", { type: "color", value: "#fff0a8", tabindex: "-1", "aria-hidden": "true", class: "dm-rt-color-input", "data-action": "highlight" });
    var markBtn = button({ text: "ab", title: "Highlight", action: "pick", value: "highlight", cls: "dm-rt-swatch dm-rt-swatch--mark" });
    markBtn.style.setProperty("--swatch", markInput.value);
    g.appendChild(colorBtn); g.appendChild(colorInput);
    g.appendChild(markBtn); g.appendChild(markInput);

    g = group();
    g.appendChild(button({ icon: "ul", title: "Bulleted list", action: "command", cmd: "insertUnorderedList", state: "insertUnorderedList" }));
    g.appendChild(button({ icon: "ol", title: "Numbered list", action: "command", cmd: "insertOrderedList", state: "insertOrderedList" }));
    g.appendChild(button({ icon: "outdent", title: "Decrease indent", action: "command", cmd: "outdent" }));
    g.appendChild(button({ icon: "indent", title: "Increase indent", action: "command", cmd: "indent" }));

    g = group();
    [["left", "Align left", "justifyLeft"], ["center", "Centre", "justifyCenter"], ["right", "Align right", "justifyRight"], ["justify", "Justify", "justifyFull"]]
      .forEach(function (b) { g.appendChild(button({ icon: b[0], title: b[1], action: "command", cmd: b[2], state: b[2] })); });

    g = group();
    var linkBtn = button({ icon: "link", title: "Link (Ctrl+K)", label: "Insert link", action: "panel", value: "link" });
    g.appendChild(linkBtn);
    g.appendChild(button({ icon: "unlink", title: "Remove link", action: "command", cmd: "unlink" }));
    g.appendChild(button({ icon: "table", title: "Insert table", action: "panel", value: "table" }));
    g.appendChild(button({ icon: "hr", title: "Horizontal line", action: "command", cmd: "insertHorizontalRule" }));
    g.appendChild(button({ icon: "symbols", title: "Insert symbol", action: "panel", value: "symbols" }));

    g = group();
    g.appendChild(button({ icon: "clear", title: "Clear formatting", action: "clear" }));
    var expandBtn = button({ icon: "expand", title: "Full screen", action: "expand", state: "expand" });
    g.appendChild(expandBtn);

    footer.appendChild(status);
    footer.appendChild(count);
    host.appendChild(toolbar);
    host.appendChild(panel);
    host.appendChild(surface);
    host.appendChild(footer);
    source.insertAdjacentElement("beforebegin", host);
    host.appendChild(source);

    var editorRequired = source.required;
    source.required = false;
    source.hidden = true;
    source.setAttribute("aria-hidden", "true");
    source.tabIndex = -1;
    surface.setAttribute("aria-required", String(editorRequired));
    try { document.execCommand("defaultParagraphSeparator", false, "p"); } catch (_e) { /* optional */ }

    function load(value) {
      value = value || "";
      if (source.dataset.richTextInitialHtml === "true") surface.innerHTML = value;
      else surface.innerHTML = plainToHtml(value);
      if (!surface.innerHTML) surface.innerHTML = "<p><br></p>";
    }
    var initialValue = source.value;
    load(initialValue);

    // ---- selection ------------------------------------------------------
    var savedRange = null;
    function inside(node) { return node && (node === surface || surface.contains(node)); }
    function saveRange() {
      var sel = window.getSelection();
      if (sel && sel.rangeCount && inside(sel.anchorNode)) savedRange = sel.getRangeAt(0).cloneRange();
    }
    function restoreRange() {
      // Focusing fires our own focus handler, which would save the caret the
      // browser places at the start; hold on to the real selection first.
      var range = savedRange;
      surface.focus({ preventScroll: true });
      var sel = window.getSelection();
      if (range && sel) { sel.removeAllRanges(); sel.addRange(range); savedRange = range; }
    }
    function closestInEditor(selector) {
      var sel = window.getSelection();
      var node = sel && sel.rangeCount ? sel.anchorNode : null;
      if (!inside(node)) return null;
      var el = node.nodeType === 1 ? node : node.parentElement;
      el = el && el.closest(selector);
      return inside(el) && el !== surface ? el : null;
    }

    // ---- state ----------------------------------------------------------
    function setStatus(text, isError) {
      status.textContent = text || defaultHint;
      status.classList.toggle("dm-rt-hint--error", !!isError);
    }
    function serialize() {
      if (!hasContent(surface)) return "";
      // Drop the trailing <br> browsers leave after text; keep deliberate blank lines.
      var html = surface.innerHTML.replace(/([^>])<br>(<\/(?:p|div|li|h[2-4]|blockquote|pre)>)/g, "$1$2").trim();
      // Stored values always carry markup, so an "&amp;" is never read as plain text.
      return /<[a-z]/i.test(html) ? html : "<p>" + html + "</p>";
    }
    function sync() {
      source.value = serialize();
      var empty = !hasContent(surface);
      host.classList.toggle("dm-rt-empty", empty && !surface.querySelector("li"));
      source.setCustomValidity(editorRequired && empty ? "Please fill out this field." : "");
      surface.setAttribute("aria-invalid", String(editorRequired && empty && host.classList.contains("dm-rt-invalid")));
      var words = (surface.textContent || "").trim().match(/\S+/g) || [];
      count.textContent = words.length + (words.length === 1 ? " word" : " words");
    }
    function refreshState() {
      toolbar.querySelectorAll("[data-state]").forEach(function (btn) {
        if (btn === expandBtn) return;
        var on = false;
        try { on = document.queryCommandState(btn.dataset.state); } catch (_e) { /* unsupported */ }
        btn.setAttribute("aria-pressed", String(on));
      });
      var block = "";
      try { block = String(document.queryCommandValue("formatBlock") || "").toLowerCase().replace(/[<>]/g, ""); } catch (_e) { /* unsupported */ }
      blockSelect.value = BLOCKS.some(function (b) { return b[0] === block; }) ? block : "p";
    }
    function changed() { sync(); saveRange(); refreshState(); }

    // ---- commands -------------------------------------------------------
    function run(command, value, css) {
      restoreRange();
      exec(command, value, css);
      changed();
    }
    function applySize(size) {
      restoreRange();
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed) { setStatus("Select the text to resize first."); return; }
      // execCommand only knows sizes 1–7; mark with 7, then swap in the real size.
      exec("fontSize", "7", false);
      surface.querySelectorAll('font[size="7"]').forEach(function (font) {
        var span = document.createElement("span");
        span.style.fontSize = size;
        while (font.firstChild) span.appendChild(font.firstChild);
        span.querySelectorAll("span").forEach(function (inner) { inner.style.fontSize = ""; if (!inner.getAttribute("style")) inner.removeAttribute("style"); });
        font.parentNode.replaceChild(span, font);
      });
      changed();
    }
    function clearFormatting() {
      restoreRange();
      exec("removeFormat");
      exec("unlink");
      exec("formatBlock", "<p>");
      changed();
    }
    function insertTable(rows, cols, header) {
      var html = "<table><tbody>";
      for (var r = 0; r < rows; r += 1) {
        html += "<tr>";
        for (var c = 0; c < cols; c += 1) html += (header && r === 0 ? "<th>" : "<td>") + "<br>" + (header && r === 0 ? "</th>" : "</td>");
        html += "</tr>";
      }
      html += "</tbody></table><p><br></p>";
      run("insertHTML", html);
      var first = surface.querySelector("table:last-of-type th, table:last-of-type td");
      if (first) {
        var range = document.createRange();
        range.selectNodeContents(first);
        range.collapse(true);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        saveRange();
      }
    }

    // ---- panels (link, table, symbols) ----------------------------------
    var openPanel = null;
    function closePanel(refocus) {
      if (!openPanel) return;
      panel.hidden = true;
      panel.innerHTML = "";
      toolbar.querySelectorAll('[data-action="panel"]').forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
      openPanel = null;
      if (refocus) restoreRange();
    }
    function field(labelText, input) {
      var wrap = make("label", { class: "dm-rt-field" });
      wrap.appendChild(make("span", {}, labelText));
      wrap.appendChild(input);
      return wrap;
    }
    function panelButton(text, cls) {
      return make("button", { type: "button", class: "dm-rt-pbtn" + (cls ? " " + cls : "") }, text);
    }
    function showPanel(kind, trigger) {
      if (openPanel === kind) { closePanel(true); return; }
      closePanel(false);
      saveRange();
      openPanel = kind;
      panel.hidden = false;
      if (trigger) trigger.setAttribute("aria-expanded", "true");
      var form = make("div", { class: "dm-rt-panel__body", role: "group" });
      panel.appendChild(form);

      if (kind === "link") {
        var existing = closestInEditor("a");
        var sel = window.getSelection();
        if (!existing && (!sel || sel.isCollapsed)) {
          closePanel(true);
          setStatus("Select the words you want to turn into a link.");
          return;
        }
        form.setAttribute("aria-label", "Link");
        var url = make("input", { type: "text", inputmode: "url", class: "dm-rt-input", placeholder: "https://example.com or name@example.com", autocomplete: "off" });
        url.value = existing ? existing.getAttribute("href") || "" : "";
        var newTab = make("input", { type: "checkbox" });
        newTab.checked = !!(existing && existing.target === "_blank");
        var tabLabel = make("label", { class: "dm-rt-check" });
        tabLabel.appendChild(newTab);
        tabLabel.appendChild(document.createTextNode(" Open in a new tab"));
        var apply = panelButton(existing ? "Update" : "Add link", "dm-rt-pbtn--primary");
        var cancel = panelButton("Cancel");
        form.appendChild(field("Link address", url));
        form.appendChild(tabLabel);
        if (existing) {
          var remove = panelButton("Remove link");
          remove.addEventListener("click", function () {
            selectNode(existing);
            closePanel(false);
            run("unlink");
          });
          form.appendChild(remove);
        }
        form.appendChild(cancel);
        form.appendChild(apply);
        var submit = function () {
          var href = safeHref(url.value);
          if (!href) { url.setCustomValidity("Enter a web address, email or page path."); url.reportValidity(); return; }
          closePanel(false);
          if (existing) selectNode(existing);
          run("createLink", href);
          var link = closestInEditor("a") || existing;
          if (link) {
            if (newTab.checked) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
            else { link.removeAttribute("target"); link.removeAttribute("rel"); }
          }
          changed();
        };
        url.addEventListener("input", function () { url.setCustomValidity(""); });
        url.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submit(); } });
        apply.addEventListener("click", submit);
        cancel.addEventListener("click", function () { closePanel(true); });
        url.focus();
      } else if (kind === "table") {
        form.setAttribute("aria-label", "Insert table");
        var rows = make("input", { type: "number", min: "1", max: "20", value: "3", class: "dm-rt-input dm-rt-input--num" });
        var cols = make("input", { type: "number", min: "1", max: "8", value: "3", class: "dm-rt-input dm-rt-input--num" });
        var head = make("input", { type: "checkbox" });
        head.checked = true;
        var headLabel = make("label", { class: "dm-rt-check" });
        headLabel.appendChild(head);
        headLabel.appendChild(document.createTextNode(" Header row"));
        var insert = panelButton("Insert table", "dm-rt-pbtn--primary");
        var cancelT = panelButton("Cancel");
        form.appendChild(field("Rows", rows));
        form.appendChild(field("Columns", cols));
        form.appendChild(headLabel);
        form.appendChild(cancelT);
        form.appendChild(insert);
        var clamp = function (input, max) { return Math.min(max, Math.max(1, parseInt(input.value, 10) || 1)); };
        insert.addEventListener("click", function () {
          var r = clamp(rows, 20), c = clamp(cols, 8), h = head.checked;
          closePanel(false);
          insertTable(r, c, h);
        });
        [rows, cols].forEach(function (input) {
          input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); insert.click(); } });
        });
        cancelT.addEventListener("click", function () { closePanel(true); });
        rows.focus();
      } else if (kind === "symbols") {
        form.setAttribute("aria-label", "Insert symbol");
        var grid = make("div", { class: "dm-rt-symbol-grid" });
        SYMBOLS.forEach(function (symbol) {
          var b = make("button", { type: "button", class: "dm-rt-symbol", title: "Insert " + symbol }, symbol);
          b.addEventListener("mousedown", function (e) { e.preventDefault(); });
          b.addEventListener("click", function () { run("insertText", symbol); });
          grid.appendChild(b);
        });
        form.appendChild(grid);
        var done = panelButton("Done");
        done.addEventListener("click", function () { closePanel(true); });
        form.appendChild(done);
        grid.firstChild.focus();
      }
    }
    function selectNode(node) {
      var range = document.createRange();
      range.selectNodeContents(node);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      savedRange = range.cloneRange();
    }
    panel.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePanel(true); }
    });

    // ---- full screen ----------------------------------------------------
    function setExpanded(on) {
      host.classList.toggle("dm-rich-editor--full", on);
      document.documentElement.classList.toggle("dm-rt-noscroll", on);
      expandBtn.setAttribute("aria-pressed", String(on));
      expandBtn.title = on ? "Exit full screen (Esc)" : "Full screen";
      expandBtn.replaceChild(icon(on ? "collapse" : "expand"), expandBtn.firstChild);
      surface.focus({ preventScroll: true });
    }

    // ---- toolbar events -------------------------------------------------
    toolbar.addEventListener("mousedown", function (event) {
      // Keep the text selection while a button is pressed.
      if (event.target.closest("button")) event.preventDefault();
    });
    toolbar.addEventListener("click", function (event) {
      var control = event.target.closest("button[data-action]");
      if (!control) return;
      var action = control.dataset.action;
      if (action === "command") { closePanel(false); run(control.dataset.cmd); }
      else if (action === "panel") showPanel(control.dataset.value, control);
      else if (action === "clear") { closePanel(false); clearFormatting(); }
      else if (action === "expand") setExpanded(!host.classList.contains("dm-rich-editor--full"));
      else if (action === "pick") {
        saveRange();
        (control.dataset.value === "color" ? colorInput : markInput).click();
      }
    });
    toolbar.addEventListener("change", function (event) {
      var control = event.target;
      var action = control.dataset.action;
      if (action === "block") {
        run("formatBlock", "<" + control.value + ">");
      } else if (action === "size") {
        if (control.value) applySize(control.value);
        control.value = "";
      } else if (action === "font") {
        if (control.value) run("fontName", control.value, true);
        control.value = "";
      } else if (action === "color") {
        colorBtn.style.setProperty("--swatch", control.value);
        run("foreColor", control.value, true);
      } else if (action === "highlight") {
        markBtn.style.setProperty("--swatch", control.value);
        restoreRange();
        if (!exec("hiliteColor", control.value, true)) exec("backColor", control.value, true);
        changed();
      }
    });
    // Arrow keys move between toolbar controls (ARIA toolbar pattern), so
    // Tab goes straight from the toolbar to the writing area.
    var controls = Array.prototype.filter.call(toolbar.querySelectorAll("button, select"), function (c) { return c.tabIndex !== -1; });
    controls.forEach(function (c, i) { c.tabIndex = i === 0 ? 0 : -1; });
    toolbar.addEventListener("keydown", function (event) {
      var index = controls.indexOf(document.activeElement);
      if (index < 0) return;
      var next = null;
      if (event.key === "ArrowRight") next = controls[(index + 1) % controls.length];
      else if (event.key === "ArrowLeft") next = controls[(index - 1 + controls.length) % controls.length];
      else if (event.key === "Home") next = controls[0];
      else if (event.key === "End") next = controls[controls.length - 1];
      if (!next) return;
      event.preventDefault();
      controls[index].tabIndex = -1;
      next.tabIndex = 0;
      next.focus();
    });

    // ---- surface events -------------------------------------------------
    surface.addEventListener("input", function () {
      host.classList.remove("dm-rt-invalid");
      setStatus("");
      changed();
    });
    surface.addEventListener("keydown", function (event) {
      var mod = event.ctrlKey || event.metaKey;
      if (mod && !event.shiftKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        saveRange();
        showPanel("link", linkBtn);
      } else if (event.key === "Escape" && host.classList.contains("dm-rich-editor--full")) {
        event.preventDefault();
        setExpanded(false);
      }
    });
    ["keyup", "mouseup", "focus"].forEach(function (type) {
      surface.addEventListener(type, function () { saveRange(); refreshState(); });
    });
    surface.addEventListener("paste", function (event) {
      var data = event.clipboardData;
      if (!data) return;
      var markup = data.getData("text/html");
      if (!markup) {
        if (data.files && data.files.length) { event.preventDefault(); setStatus("Images can't be added here; they were left out."); }
        return; // Plain text: the browser inserts it as typed text.
      }
      event.preventDefault();
      var cleaned = cleanPastedHtml(markup);
      if (cleaned[0].trim()) exec("insertHTML", cleaned[0]);
      else exec("insertText", data.getData("text/plain"));
      setStatus(cleaned[1] ? "Images and media can't be added here; they were left out." : "");
      changed();
    });
    surface.addEventListener("drop", function (event) {
      if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length) {
        event.preventDefault();
        setStatus("Files can't be dropped into the text; use the upload fields instead.");
      }
    });
    surface.addEventListener("click", function (event) {
      // Ctrl/Cmd-click follows a link, as in word processors.
      var link = event.target.closest && event.target.closest("a[href]");
      if (link && (event.ctrlKey || event.metaKey)) window.open(link.href, "_blank", "noopener");
    });

    document.addEventListener("mousedown", function (event) {
      if (openPanel && !host.contains(event.target)) closePanel(false);
    });

    // ---- form integration -----------------------------------------------
    source.addEventListener("invalid", function (event) {
      event.preventDefault();
      host.classList.add("dm-rt-invalid");
      surface.setAttribute("aria-invalid", "true");
      setStatus("This field is required.", true);
      surface.focus();
    });
    if (source.form) {
      source.form.addEventListener("submit", sync);
      source.form.addEventListener("reset", function () {
        window.setTimeout(function () { load(initialValue); host.classList.remove("dm-rt-invalid"); setStatus(""); sync(); });
      });
    }
    sync();
  }

  function init(root) {
    root = root || document;
    if (root.matches && root.matches("textarea[data-rich-text='true']")) attach(root);
    if (root.querySelectorAll) root.querySelectorAll("textarea[data-rich-text='true']").forEach(attach);
  }
  function start() {
    init(document);
    // Django Admin inlines and control-room "add another" rows arrive later.
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) { if (node.nodeType === 1) init(node); });
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  window.DMRichText = { init: init };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
