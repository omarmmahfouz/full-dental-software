/* The design of the surgery chart (templates/surgery/_arch_designer.html), like a scanner's order form: choose a
   tool and tap the teeth. The tooth cards of the form below are filled as you tap: an implant ticks "simple
   implant" (or "guided"), an immediate implant ticks "extraction" and "immediate implant", an extraction ticks
   "extraction", an add-on (sinus, GBR...) ticks itself; a pontic goes in the hidden "pontics" field. The implant
   company is chosen once for all the implants. Then the sizes and lots, implant by implant, in a window
   (#implant-sequence) that writes into the same cards: nothing is saved until the form is. */
(function () {
  "use strict";
  var designer = document.querySelector("[data-arch-designer]");
  if (!designer) return;
  var form = designer.closest("form");
  var rowsBox = form.querySelector('[data-formset="sites"] [data-formset-rows]');
  var ponticsInput = form.querySelector("[data-arch-pontics]");
  var systemSelect = designer.querySelector("[data-arch-system]");
  var guidedSwitch = designer.querySelector("[data-arch-guided]");
  var texts = JSON.parse(document.getElementById("arch-texts").textContent);
  var UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28];
  var LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38];
  var ALL = UPPER.concat(LOWER);
  var PLACED = ["simple_implant", "immediate_implant", "guided"];
  var DETAILS = ["implant_system", "implant_diameter", "implant_length", "lot_number", "stock_choice",
                 "insertion_torque", "isq"];
  var ADDONS = Array.prototype.map.call(designer.querySelectorAll(".arch-addon"), function (b) { return b.dataset.tool; });
  var tool = "implant";

  function esc(text) {  // typed text (a lot number) shown as text, never as HTML
    var span = document.createElement("span");
    span.textContent = text == null ? "" : String(text);
    return span.innerHTML;
  }
  function order(teeth) {
    return teeth.filter(function (t, i) { return ALL.indexOf(t) >= 0 && teeth.indexOf(t) === i; })
      .sort(function (a, b) { return ALL.indexOf(a) - ALL.indexOf(b); });
  }
  function parse(text) {
    if (window.teethPicker) return window.teethPicker.parse(text);
    return order(String(text || "").split(/[^\d]+/).filter(Boolean).map(Number));
  }
  var missing = parse(designer.dataset.missing);

  // ---------------------------------------------------------------- the tooth cards of the form
  function cards() { return Array.prototype.slice.call(rowsBox.querySelectorAll(".site-card")); }
  function field(card, name) { return card.querySelector("[name$='-" + name + "']"); }
  function toothOf(card) { var s = field(card, "tooth"); return s && s.value ? parseInt(s.value, 10) : null; }
  function isDeleted(card) { var b = field(card, "DELETE"); return !!(b && b.checked); }
  function isSaved(card) { var id = card.querySelector("input[type=hidden][name$='-id']"); return !!(id && id.value); }
  function ticked(card, name) { var b = field(card, name); return !!(b && b.checked); }
  function tick(card, name, on) { var b = field(card, name); if (b) b.checked = !!on; }
  function anyTicked(card) {
    return Array.prototype.some.call(card.querySelectorAll("input[type=checkbox]"), function (b) {
      return b.checked && !/-(DELETE|subcrestal)$/.test(b.name);
    });
  }
  function cardOf(tooth) {
    return cards().filter(function (c) { return toothOf(c) === tooth && !isDeleted(c); })[0] || null;
  }
  function fire(el) { if (el) el.dispatchEvent(new Event("change", { bubbles: true })); }
  function clearDetails(card) {
    DETAILS.forEach(function (name) { var f = field(card, name); if (f) f.value = ""; });
    tick(card, "subcrestal", false);
  }
  function clearCard(card) {
    card.querySelectorAll("input[type=checkbox]").forEach(function (b) { if (!/-DELETE$/.test(b.name)) b.checked = false; });
    clearDetails(card);
    if (isSaved(card)) { tick(card, "DELETE", true); return; }
    var notes = field(card, "notes"), operator = field(card, "operator"), sticker = field(card, "sticker");
    if (notes) notes.value = "";
    if (operator) operator.value = "";
    if (sticker) sticker.value = "";
    field(card, "tooth").value = "";
  }
  function cardFor(tooth) {
    var card = cardOf(tooth);
    if (card) return card;
    card = cards().filter(function (c) { return toothOf(c) === tooth && isDeleted(c); })[0];  // removed, then back
    if (card) { tick(card, "DELETE", false); return card; }
    card = cards().filter(function (c) { return !isSaved(c) && !toothOf(c) && !anyTicked(c); })[0];
    if (!card) {
      var row = window.addFormsetRow && window.addFormsetRow("sites");
      card = row && (row.classList.contains("site-card") ? row : row.querySelector(".site-card"));
    }
    if (!card) return null;
    field(card, "tooth").value = String(tooth);
    return card;
  }
  function role(card) {
    if (!card) return "";
    var implant = PLACED.some(function (n) { return ticked(card, n); });
    if (implant && (ticked(card, "immediate_implant") || ticked(card, "extraction"))) return "immediate";
    if (implant) return "implant";
    if (ticked(card, "extraction")) return "extraction";
    return "";
  }
  function hasImplant(tooth) { var r = role(cardOf(tooth)); return r === "implant" || r === "immediate"; }
  function implantTeeth() { return order(cards().map(toothOf).filter(function (t) { return t && hasImplant(t); })); }
  function pontics() { return parse(ponticsInput.value); }
  function setPontics(list) { ponticsInput.value = order(list).join(", "); }
  function withCompany(card) {
    var system = field(card, "implant_system");
    if (system && !system.value && systemSelect.value) { system.value = systemSelect.value; fire(system); }
  }

  // ---------------------------------------------------------------- a tap on a tooth
  function apply(tooth) {
    var card = cardOf(tooth), current = role(card), isPontic = pontics().indexOf(tooth) >= 0;
    var guided = guidedSwitch.checked;
    var others = pontics().filter(function (t) { return t !== tooth; });
    if (tool === "clear") {
      if (card) clearCard(card);
      setPontics(others);
      return;
    }
    if (ADDONS.indexOf(tool) >= 0) {
      card = card || cardFor(tooth);
      if (!card) return;
      tick(card, tool, !ticked(card, tool));
      if (!anyTicked(card)) clearCard(card);
      return;
    }
    if (tool === "pontic") {
      if (isPontic) { setPontics(others); return; }
      if (card && (current === "implant" || current === "immediate")) {  // it was an implant: now a pontic
        PLACED.forEach(function (n) { tick(card, n, false); });
        clearDetails(card);
        if (!anyTicked(card)) clearCard(card);
      }
      setPontics(pontics().concat([tooth]));
      return;
    }
    if (current === tool) {  // the same tool again: take it off
      if (tool !== "extraction") { PLACED.forEach(function (n) { tick(card, n, false); }); clearDetails(card); }
      if (tool !== "implant") tick(card, "extraction", false);
      if (!anyTicked(card)) clearCard(card);
      return;
    }
    card = card || cardFor(tooth);
    if (!card) return;
    if (tool === "extraction") {  // an extracted tooth may stay a pontic of the bridge
      PLACED.forEach(function (n) { tick(card, n, false); });
      clearDetails(card);
      tick(card, "extraction", true);
      return;
    }
    setPontics(others);
    tick(card, "extraction", tool === "immediate");
    tick(card, "immediate_implant", tool === "immediate");
    tick(card, "simple_implant", tool === "implant" && !guided);
    tick(card, "guided", guided);
    withCompany(card);
  }

  // Full arch: the teeth between the first and the last implant of a jaw become pontics.
  function fillGaps() {
    var list = pontics();
    [UPPER, LOWER].forEach(function (jaw) {
      var at = jaw.map(function (t, i) { return hasImplant(t) ? i : -1; }).filter(function (i) { return i >= 0; });
      if (at.length < 2) return;
      for (var i = at[0] + 1; i < at[at.length - 1]; i++) {
        if (!hasImplant(jaw[i]) && list.indexOf(jaw[i]) < 0) list.push(jaw[i]);
      }
    });
    setPontics(list);
  }

  // ---------------------------------------------------------------- the drawing
  var buttons = {};
  [["upper", UPPER], ["lower", LOWER]].forEach(function (pair) {
    var row = designer.querySelector('.arch-row[data-jaw="' + pair[0] + '"]');
    pair[1].forEach(function (tooth, i) {
      if (i === 8) { var mid = document.createElement("span"); mid.className = "arch-midline"; row.appendChild(mid); }
      var button = document.createElement("button");
      button.type = "button";
      button.className = "arch-tooth";
      button.dataset.tooth = tooth;
      button.style.setProperty("--d", String(i < 8 ? 7 - i : i - 8));
      button.innerHTML = '<span class="arch-num">' + tooth + '</span><span class="arch-icon"></span><span class="arch-size"></span><span class="arch-addons"></span><span class="arch-bar"></span>';
      row.appendChild(button);
      buttons[tooth] = button;
    });
  });
  function sizeOf(card) {
    var d = field(card, "implant_diameter"), l = field(card, "implant_length");
    return d && l && d.value && l.value ? parseFloat(d.value) + "×" + parseFloat(l.value) : "";
  }
  function groups(list) {  // runs of implants and pontics side by side in each jaw
    var result = [];
    [UPPER, LOWER].forEach(function (jaw) {
      var run = [];
      jaw.forEach(function (t) {
        if (list.indexOf(t) >= 0) { run.push(t); } else { if (run.length) result.push(run); run = []; }
      });
      if (run.length) result.push(run);
    });
    return result;
  }
  function draw() {
    var ponticList = pontics(), implants = implantTeeth(), extractions = [];
    ALL.forEach(function (tooth) {
      var button = buttons[tooth], card = cardOf(tooth), r = role(card), pontic = ponticList.indexOf(tooth) >= 0;
      if (r === "extraction") extractions.push(tooth);
      var classes = ["arch-tooth"];
      if (r) classes.push("is-" + r);
      if (pontic) classes.push("is-pontic");
      if (missing.indexOf(tooth) >= 0) classes.push("is-missing");
      var size = card && (r === "implant" || r === "immediate") ? sizeOf(card) : "";
      if (size) classes.push("is-sized");
      button.className = classes.join(" ");
      var icon = "";
      if (r === "implant") icon = '<i class="bi bi-implant"></i>';
      if (r === "immediate") icon = '<i class="bi bi-x-lg"></i><i class="bi bi-implant"></i>';
      if (r === "extraction") icon = '<i class="bi bi-x-lg"></i>';
      if (pontic) icon += '<b class="arch-p">P</b>';
      button.querySelector(".arch-icon").innerHTML = icon;
      button.querySelector(".arch-size").textContent = size;
      button.querySelector(".arch-addons").textContent = card ? ADDONS.filter(function (n) { return ticked(card, n); })
        .map(function (n) { return designer.querySelector('.arch-addon[data-tool="' + n + '"] .arch-swatch').textContent; }).join("") : "";
      button.setAttribute("aria-pressed", r || pontic ? "true" : "false");
    });
    // A bar under each bridge or full arch.
    ALL.forEach(function (t) { buttons[t].classList.remove("bar-start", "bar-mid", "bar-end"); });
    var units = order(implants.concat(ponticList));
    var described = [];
    groups(units).forEach(function (run) {
      var withPontic = run.some(function (t) { return ponticList.indexOf(t) >= 0; });
      if (!withPontic || run.length < 2) return;
      run.forEach(function (t, i) { buttons[t].classList.add(i === 0 ? "bar-start" : i === run.length - 1 ? "bar-end" : "bar-mid"); });
      var on = run.filter(function (t) { return implants.indexOf(t) >= 0; }).length;
      described.push((run.length >= 10 ? texts.fullArch : texts.bridge) + " " + run[0] + "–" + run[run.length - 1] +
                     " (" + on + " " + texts.implants + ")");
    });
    var parts = [];
    if (implants.length) parts.push("<b>" + implants.length + "</b> " + texts.implants + " (" + implants.join(", ") + ")");
    if (ponticList.length) parts.push("<b>" + ponticList.length + "</b> " + texts.pontics + " (" + ponticList.join(", ") + ")");
    if (extractions.length) parts.push("<b>" + extractions.length + "</b> " + texts.extractions + " (" + extractions.join(", ") + ")");
    var summary = designer.querySelector("[data-arch-summary]");
    summary.innerHTML = parts.length ? parts.join(" · ") + (described.length ? "<div>" + described.join(" · ") + "</div>" : "") : texts.nothing;
    var count = document.querySelector("[data-arch-card-count]");
    if (count) count.textContent = String(cards().filter(function (c) { return toothOf(c) && !isDeleted(c); }).length);
  }

  // ---------------------------------------------------------------- the tools and the taps
  designer.addEventListener("click", function (event) {
    var toolButton = event.target.closest("[data-tool]");
    if (toolButton) {
      tool = toolButton.dataset.tool;
      designer.querySelectorAll("[data-tool]").forEach(function (b) { b.classList.toggle("is-active", b === toolButton); });
      return;
    }
    var tooth = event.target.closest("[data-tooth]");
    if (tooth) {
      apply(parseInt(tooth.dataset.tooth, 10));
      fire(ponticsInput);  // the form has changes to save
      draw();
      return;
    }
    if (event.target.closest("[data-arch-fill]")) { fillGaps(); fire(ponticsInput); draw(); return; }
    if (event.target.closest("[data-arch-sequence]")) openSequence();
  });
  systemSelect.addEventListener("change", function () {
    implantTeeth().forEach(function (t) {
      var system = field(cardOf(t), "implant_system");
      if (system && systemSelect.value && system.value !== systemSelect.value) { system.value = systemSelect.value; fire(system); }
    });
  });
  guidedSwitch.addEventListener("change", function () {
    implantTeeth().forEach(function (t) {
      var card = cardOf(t);
      if (role(card) === "implant") tick(card, "simple_implant", !guidedSwitch.checked);
      tick(card, "guided", guidedSwitch.checked);
    });
    draw();
  });
  form.addEventListener("change", function (event) { if (!designer.contains(event.target)) draw(); });

  // Start from the cards (an edited surgery, or a form sent back with an error).
  (function start() {
    var first = implantTeeth().map(cardOf)[0];
    if (first && field(first, "implant_system").value) systemSelect.value = field(first, "implant_system").value;
    var implants = implantTeeth();
    guidedSwitch.checked = implants.length > 0 && implants.every(function (t) { return ticked(cardOf(t), "guided"); });
    draw();
  })();

  // ---------------------------------------------------------------- implant by implant
  var box = document.getElementById("implant-sequence");
  var seq = { teeth: [], at: 0, lots: [] };
  function seqCard() { return cardOf(seq.teeth[seq.at]); }
  function seqField(name) { return box.querySelector('[data-seq-field="' + name + '"]'); }
  function writeCard(name, value) {
    var f = field(seqCard(), name);
    if (!f) return;
    if (f.type === "checkbox") f.checked = !!value; else f.value = value;
    fire(f);
  }
  function sameNumber(a, b) { return a !== "" && b !== "" && parseFloat(a) === parseFloat(b); }
  function showChips() {
    ["implant_diameter", "implant_length"].forEach(function (name) {
      var value = seqField(name).value;
      box.querySelectorAll('[data-seq-chips="' + name + '"] .seq-chip').forEach(function (chip) {
        chip.classList.toggle("is-active", sameNumber(chip.dataset.value, value));
        var inStock = seq.lots.some(function (row) {
          return name === "implant_diameter" ? sameNumber(row.diameter, chip.dataset.value)
            : sameNumber(row.length, chip.dataset.value) && (!seqField("implant_diameter").value || sameNumber(row.diameter, seqField("implant_diameter").value));
        });
        chip.classList.toggle("in-stock", inStock);
      });
    });
  }
  function showLots() {
    var holder = box.querySelector("[data-seq-lots]"), card = seqCard();
    var d = seqField("implant_diameter").value, l = seqField("implant_length").value;
    var chosen = field(card, "stock_choice") ? field(card, "stock_choice").value : "";
    var rows = seq.lots.filter(function (row) { return (!d || sameNumber(row.diameter, d)) && (!l || sameNumber(row.length, l)); });
    holder.innerHTML = "";
    if (!seqField("implant_system").value) { holder.innerHTML = '<span class="text-muted small">' + esc(holder.dataset.empty) + "</span>"; return; }
    if (!rows.length) { holder.innerHTML = '<span class="text-muted small">' + esc(texts.noneInStock) + "</span>"; return; }
    rows.forEach(function (row) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "seq-lot" + (row.value === chosen ? " is-active" : "");
      b.dataset.value = row.value;
      b.innerHTML = "<b>" + esc(row.diameter) + " × " + esc(row.length) + "</b> <span>" + esc(row.lot || "—") +
        "</span> <small>" + esc(row.left) + " " + esc(texts.left) + "</small>";
      b.title = row.label;
      holder.appendChild(b);
    });
  }
  function loadLots() {
    var system = seqField("implant_system").value;
    seq.lots = [];
    if (!system) { showLots(); showChips(); return; }
    fetch(designer.dataset.lotsUrl + "?system=" + encodeURIComponent(system), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) { seq.lots = data.lots || []; showLots(); showChips(); })
      .catch(function () { showLots(); });
  }
  function stickerPreview() {
    var img = box.querySelector("[data-seq-sticker]"), input = field(seqCard(), "sticker");
    var url = "";
    if (input && input.files && input.files[0]) url = URL.createObjectURL(input.files[0]);
    else { var link = input && input.closest("div").querySelector("a[href]"); url = link ? link.href : ""; }
    img.hidden = !url;
    if (url) img.src = url;
  }
  function showStep(at) {
    seq.at = Math.max(0, Math.min(at, seq.teeth.length - 1));
    var card = seqCard(), tooth = seq.teeth[seq.at];
    box.querySelector("[data-seq-title]").textContent = texts.tooth + " " + tooth;
    box.querySelector("[data-seq-count]").textContent = texts.implantOf.replace("{n}", seq.at + 1).replace("{total}", seq.teeth.length);
    var strip = box.querySelector("[data-seq-teeth]");
    strip.innerHTML = "";
    seq.teeth.forEach(function (t, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "seq-tooth" + (i === seq.at ? " is-current" : "") + (sizeOf(cardOf(t)) ? " is-done" : "");
      b.dataset.seqGo = i;
      b.textContent = t;
      strip.appendChild(b);
    });
    ["implant_system", "implant_diameter", "implant_length", "lot_number", "insertion_torque", "isq"].forEach(function (name) {
      var f = field(card, name);
      seqField(name).value = f ? f.value : "";
    });
    seqField("subcrestal").checked = ticked(card, "subcrestal");
    if (!seqField("implant_system").value && systemSelect.value) {
      seqField("implant_system").value = systemSelect.value;
      writeCard("implant_system", systemSelect.value);
    }
    box.querySelector("[data-seq-prev]").disabled = seq.at === 0;
    var next = box.querySelector("[data-seq-next]");
    next.querySelector("span").textContent = seq.at === seq.teeth.length - 1 ? next.dataset.lastText : next.dataset.nextText;
    stickerPreview();
    loadLots();
  }
  function openSequence() {
    seq.teeth = implantTeeth();
    if (!seq.teeth.length) { if (window.appPopup) window.appPopup(texts.implants, [texts.noImplant]); return; }
    var first = seq.teeth.filter(function (t) { return !sizeOf(cardOf(t)); })[0];
    showStep(first ? seq.teeth.indexOf(first) : 0);
    if (window.bootstrap) window.bootstrap.Modal.getOrCreateInstance(box).show();
  }
  if (box) {
    var nextButton = box.querySelector("[data-seq-next]");
    nextButton.dataset.nextText = nextButton.querySelector("span").textContent;
    box.querySelector("[data-seq-lots]").dataset.empty = box.querySelector("[data-seq-lots]").textContent.trim();
    box.addEventListener("click", function (event) {
      var chip = event.target.closest(".seq-chip");
      if (chip) {
        var name = chip.closest("[data-seq-chips]").dataset.seqChips;
        seqField(name).value = chip.dataset.value;
        writeCard(name, chip.dataset.value);
        if (field(seqCard(), "stock_choice") && field(seqCard(), "stock_choice").value) writeCard("stock_choice", "");
        showChips(); showLots();
        return;
      }
      var lot = event.target.closest(".seq-lot");
      if (lot) {
        var row = seq.lots.filter(function (r) { return r.value === lot.dataset.value; })[0];
        if (!row) return;
        var select = field(seqCard(), "stock_choice");
        if (select && !Array.prototype.some.call(select.options, function (o) { return o.value === row.value; })) {
          var option = document.createElement("option");
          option.value = row.value; option.textContent = row.label;
          option.dataset.diameter = row.diameter; option.dataset.length = row.length; option.dataset.lot = row.lot;
          select.appendChild(option);
        }
        seqField("implant_diameter").value = row.diameter;
        seqField("implant_length").value = row.length;
        seqField("lot_number").value = row.lot;
        writeCard("implant_diameter", row.diameter);
        writeCard("implant_length", row.length);
        writeCard("stock_choice", row.value);  // fills the lot on the card too
        writeCard("lot_number", row.lot);
        showChips(); showLots();
        return;
      }
      var go = event.target.closest("[data-seq-go]");
      if (go) { showStep(parseInt(go.dataset.seqGo, 10)); return; }
      if (event.target.closest("[data-seq-prev]")) { showStep(seq.at - 1); return; }
      if (event.target.closest("[data-seq-next]")) {
        if (seq.at < seq.teeth.length - 1) showStep(seq.at + 1);
        else if (window.bootstrap) window.bootstrap.Modal.getOrCreateInstance(box).hide();
        return;
      }
      if (event.target.closest("[data-seq-photo]")) {
        var input = field(seqCard(), "sticker");
        if (input) { input.setAttribute("capture", "environment"); input.click(); }
        return;
      }
      if (event.target.closest("[data-seq-same]") && seq.at > 0) {
        var before = cardOf(seq.teeth[seq.at - 1]);
        ["implant_system", "implant_diameter", "implant_length"].forEach(function (name) {
          seqField(name).value = field(before, name).value;
          writeCard(name, field(before, name).value);
        });
        loadLots();
      }
    });
    box.addEventListener("change", function (event) {
      var name = event.target.dataset.seqField;
      if (!name) return;
      writeCard(name, event.target.type === "checkbox" ? event.target.checked : event.target.value);
      if (name === "implant_system") { writeCard("stock_choice", ""); loadLots(); }
      if (name === "implant_diameter" || name === "implant_length") { showChips(); showLots(); }
      if (name === "lot_number") {  // typed by hand: not a lot from our stock
        var select = field(seqCard(), "stock_choice");
        if (select && select.value && select.selectedOptions[0] && select.selectedOptions[0].dataset.lot !== event.target.value) writeCard("stock_choice", "");
        showLots();
      }
    });
    box.addEventListener("input", function (event) {
      var name = event.target.dataset.seqField;
      if (name === "implant_diameter" || name === "implant_length") { showChips(); showLots(); }
    });
    form.addEventListener("change", function (event) {
      if (/-sticker$/.test(event.target.name || "") && box.classList.contains("show")) stickerPreview();
    });
    box.addEventListener("hidden.bs.modal", draw);
  }
})();
