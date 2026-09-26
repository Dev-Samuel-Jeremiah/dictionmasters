/* The control room's Analytics page (templates/manage/analytics.html).

   The server works out every number (apps/manage/analytics.py) and hands it
   over as JSON; this draws it. Charts are plain SVG: thin marks from one
   baseline, a hairline grid, a tooltip on hover and on keyboard focus, and a
   table view and CSV for every chart so no value is only reachable by hover.
   Text from the data is always set with textContent. */

(function () {
  "use strict";

  var root = document.querySelector("[data-analytics]");
  var source = document.getElementById("analytics-data");
  if (!root || !source) return;
  var D = JSON.parse(source.textContent);
  var SVGNS = "http://www.w3.org/2000/svg";
  var BLUE = "#1846E0", GOLD = "#D9A200", PREV = "#A9BDF6";

  /* ---------- formatting ---------- */

  function compact(n) {
    var a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, "") + "B";
    if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
    if (a >= 1e4) return (n / 1e3).toFixed(0) + "K";
    return Math.round(n).toLocaleString("en-GB");
  }
  function full(n) { return Number(n).toLocaleString("en-GB", { maximumFractionDigits: 2 }); }
  function fmt(n, kind, short) {
    if (n === null || n === undefined) return "—";
    if (kind === "naira") return "₦" + (short ? compact(n) : full(n));
    if (kind === "percent") return full(n) + "%";
    return short ? compact(n) : full(n);
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS(SVGNS, tag);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }
  function niceMax(v) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v)));
    var f = v / p;
    var step = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
    return step * p;
  }
  function delta(change, upIsGood, previous, kind) {
    var node = el("span", "an-delta");
    if (change !== null && change !== undefined && Math.abs(change) >= 1000 && previous !== undefined) {
      // A huge percentage off a tiny base says nothing: give the base instead.
      node.classList.add(change > 0 === (upIsGood !== false) ? "is-good" : "is-bad");
      node.textContent = (change > 0 ? "▲ up from " : "▼ down from ") + fmt(previous, kind) + " in the previous period";
      return node;
    }
    if (change === null || change === undefined) {
      node.textContent = "No earlier data to compare";
      node.classList.add("is-flat");
      return node;
    }
    var up = change > 0, flat = change === 0;
    node.classList.add(flat ? "is-flat" : (up === (upIsGood !== false) ? "is-good" : "is-bad"));
    node.textContent = (flat ? "● " : up ? "▲ " : "▼ ") + (up ? "+" : "") + full(change) + "% vs previous period";
    return node;
  }

  /* ---------- tooltip ---------- */

  var tip = root.querySelector("[data-tip]");
  function showTip(evt, title, rows) {
    tip.textContent = "";
    tip.appendChild(el("p", "an-tip__title", title));
    rows.forEach(function (r) {
      var row = el("p", "an-tip__row");
      var key = el("span", "an-tip__key"); key.style.background = r.color || BLUE;
      row.appendChild(key);
      row.appendChild(el("strong", null, r.value));
      row.appendChild(el("span", "an-tip__name", r.name));
      tip.appendChild(row);
    });
    tip.hidden = false;
    var x, y;
    if (evt && evt.clientX !== undefined && evt.type.indexOf("pointer") === 0) { x = evt.clientX; y = evt.clientY; }
    else { var b = evt.target.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top; }
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14));
    var top = y - h - 12 < 8 ? y + 18 : y - h - 12;
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hideTip() { tip.hidden = true; }
  window.addEventListener("scroll", hideTip, { passive: true });

  /* ---------- column chart (one baseline, one axis) ---------- */

  function columns(host, opts) {
    host.textContent = "";
    var labels = opts.labels, values = opts.values, prev = opts.previous;
    var W = Math.max(host.clientWidth, 280), H = opts.height || 260;
    var m = { t: 12, r: 12, b: 34, l: 56 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var peak = Math.max.apply(null, values.concat(prev || [], [0]));
    // Counts get whole-number ticks: four equal steps of at least 1.
    var top = opts.format === "number" ? Math.max(4, Math.ceil(niceMax(peak) / 4) * 4) : niceMax(peak);
    var s = svg("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": opts.title });
    var y = function (v) { return m.t + ih - (v / top) * ih; };

    for (var i = 0; i <= 4; i++) {
      var v = top * i / 4, yy = Math.round(y(v)) + 0.5;
      s.appendChild(svg("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, class: "an-gridline" }));
      var t = svg("text", { x: m.l - 8, y: yy + 4, class: "an-axis", "text-anchor": "end" });
      t.textContent = fmt(v, opts.format, true); s.appendChild(t);
    }

    var n = values.length, band = iw / n;
    var bw = Math.max(2, Math.min(24, band - 4));
    var every = Math.max(1, Math.ceil(n / Math.floor(iw / 64)));
    var maxI = values.indexOf(Math.max.apply(null, values));

    values.forEach(function (val, i) {
      var cx = m.l + band * i + band / 2;
      var h0 = Math.max(0, ih - (y(val) - m.t));
      if (val > 0) {
        var x0 = cx - bw / 2, yTop = y(val), r = Math.min(4, bw / 2, h0);
        var d = "M" + x0 + "," + (m.t + ih) + "V" + (yTop + r) + "Q" + x0 + "," + yTop + " " + (x0 + r) + "," + yTop +
                "H" + (x0 + bw - r) + "Q" + (x0 + bw) + "," + yTop + " " + (x0 + bw) + "," + (yTop + r) + "V" + (m.t + ih) + "Z";
        s.appendChild(svg("path", { d: d, fill: BLUE, class: "an-bar" }));
      }
      if (i % every === 0) {
        var lt = svg("text", { x: cx, y: H - 12, class: "an-axis", "text-anchor": "middle" });
        lt.textContent = labels[i]; s.appendChild(lt);
      }
      var hit = svg("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, fill: "transparent", tabindex: 0, class: "an-hit",
                              "aria-label": labels[i] + ": " + fmt(val, opts.format) });
      var rows = [{ name: opts.name, value: fmt(val, opts.format), color: BLUE }];
      if (prev) rows.push({ name: "Previous period", value: fmt(prev[i] || 0, opts.format), color: PREV });
      var show = function (e) { showTip(e, labels[i], rows); hit.classList.add("is-hot"); };
      hit.addEventListener("pointermove", show);
      hit.addEventListener("focus", show);
      hit.addEventListener("pointerleave", function () { hideTip(); hit.classList.remove("is-hot"); });
      hit.addEventListener("blur", function () { hideTip(); hit.classList.remove("is-hot"); });
      s.appendChild(hit);
    });

    if (prev && prev.length) {
      var pts = prev.slice(0, n).map(function (v, i) { return (m.l + band * i + band / 2) + "," + y(v); }).join(" ");
      s.appendChild(svg("polyline", { points: pts, fill: "none", stroke: PREV, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", class: "an-line" }));
    }

    // One label: the peak.
    if (values[maxI] > 0 && opts.labelPeak !== false) {
      var px = m.l + band * maxI + band / 2;
      var pk = svg("text", { x: Math.min(W - m.r - 4, Math.max(m.l + 4, px)), y: y(values[maxI]) - 6, class: "an-peak", "text-anchor": "middle" });
      pk.textContent = fmt(values[maxI], opts.format, true); s.appendChild(pk);
    }
    host.appendChild(s);
    if (!values.some(function (v) { return v > 0; })) {
      host.appendChild(el("p", "an-empty", "Nothing in this period yet."));
    }
  }

  /* ---------- horizontal bars ---------- */

  function hbars(host, items, opts) {
    host.textContent = "";
    if (!items.length || !items.some(function (d) { return d.value > 0; })) {
      host.appendChild(el("p", "an-empty", opts.empty || "Nothing in this period yet."));
      return;
    }
    var max = Math.max.apply(null, items.map(function (d) { return d.value; }));
    var total = items.reduce(function (a, d) { return a + d.value; }, 0);
    var list = el("ul", "an-hbars");
    items.forEach(function (d) {
      var li = el("li", "an-hbar");
      li.tabIndex = 0;
      var head = el("div", "an-hbar__head");
      head.appendChild(el("span", "an-hbar__label", d.label));
      var val = el("span", "an-hbar__value", fmt(d.value, opts.format));
      if (opts.share && total) val.appendChild(el("small", null, " · " + Math.round(d.value / total * 100) + "%"));
      head.appendChild(val);
      var track = el("div", "an-hbar__track");
      var fill = el("div", "an-hbar__fill");
      fill.style.width = Math.max(1.5, d.value / max * 100) + "%";
      track.appendChild(fill);
      li.appendChild(head); li.appendChild(track);
      var show = function (e) { showTip(e, d.label, [{ name: opts.name, value: fmt(d.value, opts.format) }]); };
      li.addEventListener("pointermove", show); li.addEventListener("focus", show);
      li.addEventListener("pointerleave", hideTip); li.addEventListener("blur", hideTip);
      list.appendChild(li);
    });
    host.appendChild(list);
  }

  /* ---------- sparkline ---------- */

  function spark(host, values, w, h) {
    host.textContent = "";
    if (!values || values.length < 2) return;
    w = w || 120; h = h || 32;
    var max = Math.max.apply(null, values.concat([1]));
    var step = w / (values.length - 1);
    var pts = values.map(function (v, i) { return [i * step, h - 3 - (v / max) * (h - 6)]; });
    var s = svg("svg", { width: w, height: h, viewBox: "0 0 " + w + " " + h, "aria-hidden": "true", class: "an-spark" });
    var area = "M0," + h + " " + pts.map(function (p) { return "L" + p[0] + "," + p[1]; }).join(" ") + " L" + w + "," + h + "Z";
    s.appendChild(svg("path", { d: area, fill: BLUE, "fill-opacity": 0.1 }));
    s.appendChild(svg("polyline", { points: pts.map(function (p) { return p.join(","); }).join(" "), fill: "none", stroke: PREV, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    var last = pts[pts.length - 1];
    s.appendChild(svg("circle", { cx: last[0] - 1, cy: last[1], r: 4, fill: BLUE, stroke: "#fff", "stroke-width": 2 }));
    host.appendChild(s);
  }

  /* ---------- tables, CSV ---------- */

  function csv(name, header, rows) {
    var esc = function (v) { v = v === null || v === undefined ? "" : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var text = [header].concat(rows).map(function (r) { return r.map(esc).join(","); }).join("\n");
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
    a.download = "diction-masters-" + name + "-" + D.period.from + "-to-" + D.period.to + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function table(header, rows, numericCols) {
    var t = el("table", "an-table");
    var thead = el("thead"), tr = el("tr");
    header.forEach(function (h, i) { var th = el("th", numericCols && numericCols.indexOf(i) > -1 ? "is-num" : "", h); th.scope = "col"; tr.appendChild(th); });
    thead.appendChild(tr); t.appendChild(thead);
    var tb = el("tbody");
    rows.forEach(function (r) {
      var row = el("tr");
      r.forEach(function (c, i) { row.appendChild(el("td", numericCols && numericCols.indexOf(i) > -1 ? "is-num" : "", c)); });
      tb.appendChild(row);
    });
    t.appendChild(tb);
    return t;
  }

  function wireCard(card, draw, tableRows, header, numeric, csvName, csvRows) {
    var plot = card.querySelector("[data-plot]"), tbl = card.querySelector("[data-table]");
    var btn = card.querySelector("[data-view-table]"), dl = card.querySelector("[data-csv]");
    if (btn) btn.addEventListener("click", function () {
      var on = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = on ? "Chart" : "Table";
      tbl.hidden = !on; plot.hidden = on;
      var legend = card.querySelector("[data-legend]"); if (legend) legend.hidden = on;
      if (on) { tbl.textContent = ""; tbl.appendChild(table(header(), tableRows(), numeric)); }
    });
    if (dl) dl.addEventListener("click", function () { csv(csvName, header(), (csvRows || tableRows)()); });
    draw();
    return draw;
  }

  /* ---------- the page ---------- */

  var redraws = [];

  // Headline and totals.
  var rev = D.kpis[0];
  root.querySelector("[data-hero]").textContent = fmt(rev.value, "naira");
  var hd = root.querySelector("[data-hero-delta]"); hd.replaceWith(delta(rev.change, true, rev.previous, "naira"));
  spark(root.querySelector("[data-hero-spark]"), rev.series, 320, 56);
  root.querySelectorAll("[data-total]").forEach(function (dd) {
    var k = dd.getAttribute("data-total");
    dd.textContent = fmt(D.totals[k], k === "revenue_all" ? "naira" : "number");
  });

  // Tiles (the headline revenue is already above).
  var tiles = root.querySelector("[data-tiles]");
  D.kpis.slice(1).forEach(function (k) {
    var tile = el("article", "an-card an-tile");
    var lab = el("p", "an-label", k.label);
    if (k.hint) { lab.title = k.hint; lab.appendChild(el("span", "an-info", " ⓘ")); }
    tile.appendChild(lab);
    tile.appendChild(el("p", "an-tile__value", fmt(k.value, k.format)));
    tile.appendChild(delta(k.change, k.up_is_good, k.previous, k.format));
    var sp = el("div", "an-tile__spark"); tile.appendChild(sp);
    tiles.appendChild(tile);
    spark(sp, k.series, 120, 30);
  });

  // Revenue over time.
  (function () {
    var card = root.querySelector('[data-chart="revenue"]');
    var compare = card.querySelector("[data-compare]");
    var legend = card.querySelector("[data-legend]");
    function drawLegend() {
      legend.textContent = "";
      var a = el("span", "an-key"); a.appendChild(el("i", "an-key__bar")); a.appendChild(document.createTextNode("This period")); legend.appendChild(a);
      if (compare.checked) { var b = el("span", "an-key"); b.appendChild(el("i", "an-key__line")); b.appendChild(document.createTextNode("Previous period (" + D.period.prev_label + ")")); legend.appendChild(b); }
    }
    var draw = function () {
      drawLegend();
      columns(card.querySelector("[data-plot]"), { labels: D.labels, values: D.revenue.current, previous: compare.checked ? D.revenue.previous : null, format: "naira", name: "Revenue", title: "Revenue over time" });
    };
    compare.addEventListener("change", draw);
    redraws.push(wireCard(card, draw,
      function () { return D.labels.map(function (l, i) { return [l, fmt(D.revenue.current[i], "naira"), fmt(D.revenue.previous[i] || 0, "naira")]; }); },
      function () { return [D.period.grain.charAt(0).toUpperCase() + D.period.grain.slice(1), "Revenue", "Previous period"]; }, [1, 2], "revenue",
      function () { return D.labels.map(function (l, i) { return [l, D.revenue.current[i], D.revenue.previous[i] || 0]; }); }));
  })();

  // A chart with chips: one series at a time, always in the same blue.
  function chipChart(key, series, allLabel, name) {
    var card = root.querySelector('[data-chart="' + key + '"]');
    var chips = card.querySelector("[data-chips]");
    var totals = D.labels.map(function (_l, i) { return series.reduce(function (a, s) { return a + (s.values[i] || 0); }, 0); });
    var options = [{ key: "all", label: allLabel, values: totals }].concat(series);
    var current = options[0];
    options.forEach(function (o) {
      var sum = o.values.reduce(function (a, b) { return a + b; }, 0);
      var b = el("button", "an-chip" + (o === current ? " is-on" : ""), o.label + " · " + compact(sum));
      b.type = "button"; b.setAttribute("aria-pressed", String(o === current));
      b.addEventListener("click", function () {
        current = o;
        chips.querySelectorAll("button").forEach(function (x) { x.classList.remove("is-on"); x.setAttribute("aria-pressed", "false"); });
        b.classList.add("is-on"); b.setAttribute("aria-pressed", "true");
        draw();
      });
      chips.appendChild(b);
    });
    var draw = function () {
      columns(card.querySelector("[data-plot]"), { labels: D.labels, values: current.values, format: "number", name: current.label, title: name + ": " + current.label });
    };
    redraws.push(wireCard(card, draw,
      function () { return D.labels.map(function (l, i) { return [l].concat(options.map(function (o) { return full(o.values[i] || 0); })); }); },
      function () { return ["Period"].concat(options.map(function (o) { return o.label; })); },
      options.map(function (_o, i) { return i + 1; }), key,
      function () { return D.labels.map(function (l, i) { return [l].concat(options.map(function (o) { return o.values[i] || 0; })); }); }));
  }
  chipChart("signups", D.signups.series.map(function (s) { return { label: s.label, values: s.values }; }), "All sign-ups", "New sign-ups");
  chipChart("activity", D.activity.series.filter(function (s) { return s.total > 0; }).map(function (s) { return { label: s.label, values: s.values }; }), "All activity", "Learning activity");

  // Breakdowns.
  function barCard(key, items, format, name, share, empty) {
    var card = root.querySelector('[data-chart="' + key + '"]');
    var draw = function () { hbars(card.querySelector("[data-plot]"), items, { format: format, name: name, share: share, empty: empty }); };
    card.querySelector("[data-csv]").addEventListener("click", function () {
      csv(key, [name === "Students" ? "Level" : "Item", name], items.map(function (d) { return [d.label, d.value]; }));
    });
    draw();
  }
  barCard("audience", D.breakdowns.audience, "naira", "Revenue", true);
  barCard("plans", D.breakdowns.plans, "naira", "Revenue", true);
  barCard("levels", D.breakdowns.levels, "number", "Students", false, "No students have a level yet.");

  // Subscriptions now.
  (function () {
    var body = root.querySelector("[data-subscriptions] [data-body]");
    [["school", "Schools"], ["learner", "Adults & students"]].forEach(function (pair) {
      var s = D.subscriptions[pair[0]], total = s.active + s.trial + s.expired;
      var block = el("div", "an-subs");
      block.appendChild(el("p", "an-subs__title", pair[1] + " · " + full(total)));
      var bar = el("div", "an-stack");
      [["active", "Paid", "is-paid"], ["trial", "On free trial", "is-trial"], ["expired", "Ended", "is-ended"]].forEach(function (seg) {
        if (!s[seg[0]]) return;
        var part = el("span", "an-stack__seg " + seg[2]);
        part.style.flexGrow = s[seg[0]];
        part.tabIndex = 0;
        var show = function (e) { showTip(e, pair[1], [{ name: seg[1], value: full(s[seg[0]]), color: seg[2] === "is-paid" ? BLUE : seg[2] === "is-trial" ? GOLD : "#C9D0E2" }]); };
        part.addEventListener("pointermove", show); part.addEventListener("focus", show);
        part.addEventListener("pointerleave", hideTip); part.addEventListener("blur", hideTip);
        bar.appendChild(part);
      });
      if (!total) bar.appendChild(el("span", "an-stack__seg is-empty"));
      block.appendChild(bar);
      var keys = el("ul", "an-keys");
      [["active", "Paid", "is-paid"], ["trial", "On free trial", "is-trial"], ["expired", "Ended", "is-ended"]].forEach(function (seg) {
        var li = el("li"); li.appendChild(el("i", "an-dot " + seg[2]));
        li.appendChild(el("strong", null, full(s[seg[0]]))); li.appendChild(document.createTextNode(" " + seg[1]));
        keys.appendChild(li);
      });
      block.appendChild(keys);
      body.appendChild(block);
    });
  })();

  // Payment health.
  (function () {
    var h = D.health, body = root.querySelector("[data-health] [data-body]");
    var tried = h.success + h.failed + h.abandoned + h.pending;
    var rate = tried ? Math.round(h.success / tried * 100) : null;
    var meter = el("div", "an-meter");
    meter.appendChild(el("p", "an-meter__value", rate === null ? "—" : rate + "%"));
    meter.appendChild(el("p", "an-label", "of checkouts were paid"));
    var track = el("div", "an-meter__track"); var fill = el("div", "an-meter__fill");
    fill.style.width = (rate || 0) + "%"; track.appendChild(fill); meter.appendChild(track);
    track.setAttribute("role", "img"); track.setAttribute("aria-label", (rate || 0) + "% of checkouts paid");
    body.appendChild(meter);
    var dl = el("dl", "an-facts");
    [["✓ Paid", h.success], ["✕ Failed", h.failed], ["↩ Not completed", h.abandoned], ["… Pending", h.pending],
     ["Plans given free", h.grants], ["Promo discounts", fmt(h.discount, "naira")]].forEach(function (f) {
      var d = el("div"); d.appendChild(el("dt", null, f[0])); d.appendChild(el("dd", null, typeof f[1] === "number" ? full(f[1]) : f[1])); dl.appendChild(d);
    });
    body.appendChild(dl);
    if (D.breakdowns.channels.length) {
      body.appendChild(el("p", "an-label an-gap", "How they paid"));
      var methods = el("div"); body.appendChild(methods);
      hbars(methods, D.breakdowns.channels, { format: "number", name: "Payments", share: true });
    }
    if (h.promos.length) {
      body.appendChild(el("p", "an-label an-gap", "Promo codes used"));
      body.appendChild(table(["Code", "Uses", "Discount"], h.promos.map(function (p) { return [p.code, full(p.uses), fmt(p.off, "naira")]; }), [1, 2]));
    }
  })();

  // Sortable, searchable lists.
  function list(key, header, rows, raw, numeric, filterFn) {
    var card = root.querySelector('[data-list="' + key + '"]');
    var body = card.querySelector("[data-body]"), search = card.querySelector("[data-search]");
    var status = card.querySelector("[data-status]");
    var sortCol = null, asc = false;
    function visible() {
      var q = (search.value || "").trim().toLowerCase();
      var idx = raw.map(function (_r, i) { return i; }).filter(function (i) {
        return (!q || rows[i].join(" ").toLowerCase().indexOf(q) > -1) && (!filterFn || filterFn(raw[i], status && status.value));
      });
      if (sortCol !== null) idx.sort(function (a, b) {
        var x = raw[a][sortCol], y = raw[b][sortCol];
        var r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return asc ? r : -r;
      });
      return idx;
    }
    function draw() {
      body.textContent = "";
      var idx = visible();
      if (!raw.length) { body.appendChild(el("p", "an-empty", "Nothing in this period yet.")); return; }
      var t = table(header, idx.map(function (i) { return rows[i]; }), numeric);
      t.querySelectorAll("th").forEach(function (th, col) {
        var b = el("button", "an-sort", header[col]); b.type = "button";
        if (sortCol === col) { b.appendChild(document.createTextNode(asc ? " ▲" : " ▼")); th.setAttribute("aria-sort", asc ? "ascending" : "descending"); }
        b.addEventListener("click", function () { if (sortCol === col) asc = !asc; else { sortCol = col; asc = numeric.indexOf(col) === -1; } draw(); });
        th.textContent = ""; th.appendChild(b);
      });
      body.appendChild(t);
      body.appendChild(el("p", "an-count", idx.length + " of " + raw.length + " shown"));
    }
    search.addEventListener("input", draw);
    if (status) status.addEventListener("change", draw);
    card.querySelector("[data-csv]").addEventListener("click", function () { csv(key, header, visible().map(function (i) { return raw[i]; })); });
    draw();
  }

  var st = { active: "Paid", trial: "Free trial", expired: "Ended", none: "No plan" };
  function method(channel) {
    if (!channel) return "—";
    var t = channel.replace(/_/g, " ");
    return t === "ussd" ? "USSD" : t.charAt(0).toUpperCase() + t.slice(1);
  }
  list("schools",
    ["School", "Code", "Joined", "Teachers", "Students", "Teacher limit", "Plan", "Status", "Access until", "Revenue (period)", "Revenue (all time)"],
    D.schools.map(function (s) { return [s.name, s.code, s.joined, full(s.teachers), full(s.students), s.limit === null ? "No limit" : full(s.limit), s.plan || "—", st[s.state] || s.state, s.until || "—", fmt(s.revenue_period, "naira"), fmt(s.revenue_all, "naira")]; }),
    D.schools.map(function (s) { return [s.name, s.code, s.joined, s.teachers, s.students, s.limit === null ? "" : s.limit, s.plan, st[s.state] || s.state, s.until, s.revenue_period, s.revenue_all]; }),
    [3, 4, 5, 9, 10]);
  list("payments",
    ["When", "Account", "Email", "Customer", "Plan", "Amount", "Discount", "Method", "Status", "Reference"],
    D.payments.map(function (p) { return [p.when, p.account, p.email, p.type, p.plan, fmt(p.amount, "naira"), fmt(p.discount, "naira"), method(p.channel), p.status, p.reference]; }),
    D.payments.map(function (p) { return [p.when, p.account, p.email, p.type, p.plan, p.amount, p.discount, p.channel, p.status, p.reference]; }),
    [5, 6],
    function (r, wanted) { return !wanted || r[8] === wanted; });

  // Charts follow the width of their card.
  var timer;
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { redraws.forEach(function (d) { d(); }); }, 150);
  });
  var printBtn = root.querySelector("[data-print]");
  if (printBtn) printBtn.addEventListener("click", function () { window.print(); });
})();
