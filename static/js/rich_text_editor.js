(function () {
  "use strict";

  var symbols = ["æ", "ɑ", "ɒ", "ə", "ɛ", "ɜː", "ɪ", "iː", "ʊ", "uː", "ʌ", "ɔː", "θ", "ð", "ŋ", "ʃ", "ʒ", "tʃ", "dʒ", "ˈ", "ˌ", "ː", "…", "—", "–", "£", "€", "©", "™", "→", "←", "±", "×", "÷", "°", "•"];
  var sizes = [
    ["12px", "Small"], ["14px", "14 px"], ["16px", "Normal"],
    ["18px", "18 px"], ["22px", "Large"], ["28px", "28 px"], ["36px", "36 px"]
  ];

  function make(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(label, title, action, value) {
    var node = make("button", { type: "button", class: "dm-rt-btn", title: title, "aria-label": title, "data-action": action }, label);
    if (value !== undefined) node.dataset.value = value;
    return node;
  }

  function safeTextHtml(value) {
    return value.split(/\r?\n/).map(function (line) {
      return line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }).join("<br>");
  }

  function attach(source) {
    if (source.dataset.richTextReady || source.dataset.richText !== "true" || source.disabled || source.readOnly) return;
    // Django Admin clones empty inline rows. Leave the prototype untouched so
    // the newly inserted row can be initialized with its own event handlers.
    if (source.closest(".empty-form")) return;
    source.dataset.richTextReady = "true";

    var host = make("section", { class: "dm-rich-editor", "aria-label": "Rich text editor" });
    var toolbar = make("div", { class: "dm-rt-toolbar", role: "toolbar", "aria-label": "Text formatting" });
    var surface = make("div", {
      class: "dm-rt-surface",
      contenteditable: "true",
      role: "textbox",
      "aria-multiline": "true",
      spellcheck: "true",
      tabindex: "0"
    });
    var footer = make("div", { class: "dm-rt-footer" });
    var count = make("span", { class: "dm-rt-count", "aria-live": "polite" }, "0 words");
    var hint = make("span", { class: "dm-rt-hint" }, "Formatting is shown to learners.");

    var label = source.id ? document.querySelector('label[for="' + CSS.escape(source.id) + '"]') : null;
    if (label) {
      var editorId = source.id + "-editor";
      surface.id = editorId;
      label.htmlFor = editorId;
      if (label.id) surface.setAttribute("aria-labelledby", label.id);
    }

    var groups = [];
    function group() {
      var box = make("div", { class: "dm-rt-group" });
      toolbar.appendChild(box);
      groups.push(box);
      return box;
    }

    var g = group();
    [
      ["↶", "Undo", "undo"], ["↷", "Redo", "redo"], ["B", "Bold", "bold"],
      ["I", "Italic", "italic"], ["U", "Underline", "underline"], ["S̶", "Strikethrough", "strikeThrough"],
      ["x₂", "Subscript", "subscript"], ["x²", "Superscript", "superscript"]
    ].forEach(function (item) { g.appendChild(button(item[0], item[1], "command", item[2])); });

    g = group();
    var blocks = make("select", { class: "dm-rt-select", "aria-label": "Paragraph style", title: "Paragraph style", "data-action": "block" });
    [["p", "Paragraph"], ["h2", "Heading 2"], ["h3", "Heading 3"], ["h4", "Heading 4"], ["blockquote", "Quote"], ["pre", "Code block"]].forEach(function (entry) {
      blocks.appendChild(make("option", { value: entry[0] }, entry[1]));
    });
    g.appendChild(blocks);
    var fontSize = make("select", { class: "dm-rt-select dm-rt-size", "aria-label": "Text size", title: "Text size", "data-action": "size" });
    fontSize.appendChild(make("option", { value: "" }, "Size"));
    sizes.forEach(function (entry) { fontSize.appendChild(make("option", { value: entry[0] }, entry[1])); });
    g.appendChild(fontSize);
    var fontFamily = make("select", { class: "dm-rt-select dm-rt-font", "aria-label": "Font family", title: "Font family", "data-action": "font" });
    fontFamily.appendChild(make("option", { value: "" }, "Font"));
    [["Georgia, serif", "Georgia"], ["Arial, sans-serif", "Arial"], ["Times New Roman, serif", "Times New Roman"], ["Verdana, sans-serif", "Verdana"], ["Courier New, monospace", "Monospace"]].forEach(function (entry) {
      fontFamily.appendChild(make("option", { value: entry[0] }, entry[1]));
    });
    g.appendChild(fontFamily);

    g = group();
    [["• List", "Insert bulleted list", "insertUnorderedList"], ["1. List", "Insert numbered list", "insertOrderedList"],
      ["⇤", "Decrease indent", "outdent"], ["⇥", "Increase indent", "indent"]]
      .forEach(function (item) { g.appendChild(button(item[0], item[1], "command", item[2])); });

    g = group();
    [["↤", "Align left", "justifyLeft"], ["↔", "Centre", "justifyCenter"],
      ["↦", "Align right", "justifyRight"], ["☰", "Justify", "justifyFull"]]
      .forEach(function (item) { g.appendChild(button(item[0], item[1], "command", item[2])); });

    g = group();
    g.appendChild(button("Link", "Add link", "link"));
    g.appendChild(button("Unlink", "Remove link", "command", "unlink"));
    g.appendChild(button("Table", "Insert a table", "table"));
    g.appendChild(button("―", "Insert horizontal line", "command", "insertHorizontalRule"));
    var colorLabel = make("label", { class: "dm-rt-color", title: "Text colour" }, "A");
    colorLabel.appendChild(make("input", { type: "color", value: "#14213d", "aria-label": "Text colour", "data-action": "color" }));
    g.appendChild(colorLabel);
    var markLabel = make("label", { class: "dm-rt-color dm-rt-highlight", title: "Highlight colour" }, "▰");
    markLabel.appendChild(make("input", { type: "color", value: "#fff0a8", "aria-label": "Highlight colour", "data-action": "highlight" }));
    g.appendChild(markLabel);

    g = group();
    var palette = make("details", { class: "dm-rt-symbols" });
    palette.appendChild(make("summary", { title: "Insert a symbol", "aria-label": "Insert a symbol" }, "Ω Symbols"));
    var grid = make("div", { class: "dm-rt-symbol-grid" });
    symbols.forEach(function (symbol) {
      grid.appendChild(button(symbol, "Insert " + symbol, "insert", symbol));
    });
    palette.appendChild(grid);
    g.appendChild(palette);
    g.appendChild(button("Tx", "Clear formatting", "command", "removeFormat"));

    var editorLabel = label ? label.textContent.trim().replace(/\s*required\s*$/i, "") : "Rich text";
    surface.setAttribute("aria-label", editorLabel || "Rich text");

    host.appendChild(toolbar);
    host.appendChild(surface);
    footer.appendChild(hint);
    footer.appendChild(count);
    host.appendChild(footer);
    source.insertAdjacentElement("beforebegin", host);
    host.appendChild(source);
    var editorRequired = source.required;
    source.hidden = true;
    source.required = false;
    source.setAttribute("aria-hidden", "true");
    source.tabIndex = -1;
    surface.setAttribute("aria-required", String(editorRequired));

    var initial = source.value || "";
    if (source.dataset.richTextInitialHtml === "true") surface.innerHTML = initial;
    else surface.innerHTML = safeTextHtml(initial);

    var savedRange = null;
    function saveRange() {
      var selection = window.getSelection();
      if (selection && selection.rangeCount && surface.contains(selection.anchorNode)) {
        savedRange = selection.getRangeAt(0).cloneRange();
      }
    }
    function restoreRange() {
      surface.focus({ preventScroll: true });
      if (savedRange) {
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(savedRange);
      }
    }
    function sync() {
      source.value = surface.innerHTML;
      var empty = !(surface.textContent || "").trim();
      source.setCustomValidity(editorRequired && empty ? "Please fill out this field." : "");
      surface.setAttribute("aria-invalid", String(editorRequired && empty));
      var words = (surface.textContent || "").trim().match(/\S+/g) || [];
      count.textContent = words.length + (words.length === 1 ? " word" : " words");
      saveRange();
    }
    function runCommand(command, value) {
      restoreRange();
      surface.focus({ preventScroll: true });
      try { document.execCommand("styleWithCSS", false, true); } catch (_error) { /* Optional browser command. */ }
      document.execCommand(command, false, value || null);
      sync();
    }
    function wrapSelection(styleName, styleValue) {
      restoreRange();
      var selection = window.getSelection();
      if (!selection || !selection.rangeCount || selection.isCollapsed) return;
      var range = selection.getRangeAt(0);
      if (!surface.contains(range.commonAncestorContainer)) return;
      var span = document.createElement("span");
      span.style[styleName] = styleValue;
      span.appendChild(range.extractContents());
      range.insertNode(span);
      selection.removeAllRanges();
      var next = document.createRange();
      next.selectNodeContents(span);
      selection.addRange(next);
      savedRange = next.cloneRange();
      sync();
    }
    function insertText(text) {
      restoreRange();
      var selection = window.getSelection();
      var range;
      if (selection && selection.rangeCount && surface.contains(selection.anchorNode)) {
        range = selection.getRangeAt(0);
      } else {
        range = document.createRange();
        range.selectNodeContents(surface);
        range.collapse(false);
      }
      range.deleteContents();
      var node = document.createTextNode(text);
      range.insertNode(node);
      range.setStartAfter(node);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      savedRange = range.cloneRange();
      sync();
    }

    toolbar.addEventListener("mousedown", function (event) {
      if (event.target.closest("button")) event.preventDefault();
    });
    toolbar.addEventListener("click", function (event) {
      var control = event.target.closest("[data-action]");
      if (!control) return;
      var action = control.dataset.action;
      if (action === "command") runCommand(control.dataset.value);
      else if (action === "insert") insertText(control.dataset.value);
      else if (action === "link") {
        restoreRange();
        var selected = window.getSelection();
        if (!selected || selected.isCollapsed) { window.alert("Select the text you want to link first."); return; }
        var url = window.prompt("Enter a web address or email link:", "https://");
        if (url) runCommand("createLink", url.trim());
      }
    });
    toolbar.addEventListener("change", function (event) {
      var control = event.target.closest("[data-action]");
      if (!control) return;
      var action = control.dataset.action;
      if (action === "block") {
        if (control.value === "blockquote") runCommand("formatBlock", "blockquote");
        else runCommand("formatBlock", "<" + control.value + ">");
      } else if (action === "size") {
        if (control.value) wrapSelection("fontSize", control.value);
        control.value = "";
      } else if (action === "font") {
        if (control.value) runCommand("fontName", control.value);
        control.value = "";
      } else if (action === "color") wrapSelection("color", control.value);
      else if (action === "highlight") wrapSelection("backgroundColor", control.value);
    });
    surface.addEventListener("input", sync);
    source.addEventListener("invalid", function (event) {
      event.preventDefault();
      surface.focus();
      surface.classList.add("dm-rt-invalid");
    });
    surface.addEventListener("input", function () { surface.classList.remove("dm-rt-invalid"); });
    surface.addEventListener("keyup", saveRange);
    surface.addEventListener("mouseup", saveRange);
    surface.addEventListener("focus", saveRange);
    source.form.addEventListener("submit", sync);
    sync();
  }

  function init(root) {
    (root || document).querySelectorAll("textarea[data-rich-text='true']").forEach(attach);
  }
  function start() {
    init(document);
    var observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches && node.matches("textarea[data-rich-text='true']")) attach(node);
          init(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
