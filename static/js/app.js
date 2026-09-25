// Small helpers used across pages. No build step, works offline.
(function () {
  "use strict";

  // Ask before running dangerous actions: <button data-confirm="...">
  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-confirm]");
    if (target && !window.confirm(target.getAttribute("data-confirm"))) {
      event.preventDefault();
      event.stopPropagation();
    }
  });

  // "Back" goes to the previous page of this system; without one it goes to the home page.
  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-back]");
    if (!link) return;
    if (window.history.length > 1 && document.referrer && document.referrer.indexOf(window.location.host) >= 0) {
      event.preventDefault();
      window.history.back();
    }
  });

  // Convert Arabic-Indic digits to Western digits while typing in number-like fields.
  var arabicDigits = /[٠-٩۰-۹]/g;
  document.addEventListener("input", function (event) {
    var el = event.target;
    if (!el.matches || !el.matches("input[data-digits], input[type=tel], input.js-date, input[data-autocomplete-url]")) return;
    if (arabicDigits.test(el.value)) {
      el.value = el.value.replace(arabicDigits, function (d) {
        var code = d.charCodeAt(0);
        return String(code >= 0x06F0 ? code - 0x06F0 : code - 0x0660);
      });
    }
  });

  // Errors after saving show in a box that must be read; closing it goes to the first wrong field.
  function popup(title, lines) {
    if (!window.bootstrap) { window.alert(title + "\n" + lines.join("\n")); return; }
    var box = document.createElement("div");
    box.className = "modal fade";
    box.tabIndex = -1;
    box.innerHTML = '<div class="modal-dialog modal-dialog-centered"><div class="modal-content border-danger">' +
      '<div class="modal-header bg-danger-subtle"><h5 class="modal-title"></h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
      '<div class="modal-body"><ul class="mb-0"></ul></div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-primary" data-bs-dismiss="modal">OK</button></div></div></div>';
    box.querySelector(".modal-title").textContent = title;
    lines.forEach(function (line) {
      var item = document.createElement("li");
      item.textContent = line;
      box.querySelector("ul").appendChild(item);
    });
    document.body.appendChild(box);
    box.addEventListener("hidden.bs.modal", function () { box.remove(); });
    new window.bootstrap.Modal(box).show();
  }
  window.appPopup = popup;
  document.querySelectorAll(".modal[data-show-on-load]").forEach(function (box) {
    if (!window.bootstrap) return;
    box.addEventListener("hidden.bs.modal", function () {
      var wrong = document.querySelector(".errorlist");
      var field = wrong && wrong.parentNode.querySelector("input, select, textarea");
      if (field) { field.scrollIntoView({ block: "center" }); field.focus(); }
    });
    new window.bootstrap.Modal(box).show();
  });

  // Mobiles are checked while typing: the number of digits, and whether another file already has it.
  document.addEventListener("change", function (event) {
    var el = event.target;
    if (!el.matches || !el.matches("input[data-phone-check-url]") || !el.value.trim()) return;
    fetch(el.getAttribute("data-phone-check-url") + (el.getAttribute("data-phone-check-url").indexOf("?") < 0 ? "?" : "&") +
          "phone=" + encodeURIComponent(el.value), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        el.classList.toggle("is-invalid", !!data.message);
        if (data.message) popup(data.title || "", [data.message]);
      });
  });

  // Dates are always dd/mm/yyyy: a calendar to pick from, or type the date (e.g. an old visit).
  function setupDates(root) {
    if (!window.flatpickr) return;
    var arabic = document.documentElement.lang === "ar" && window.flatpickr.l10ns.ar;
    root.querySelectorAll("input.js-date").forEach(function (el) {
      if (el._flatpickr) return;
      window.flatpickr(el, {
        dateFormat: "d/m/Y",
        allowInput: true,
        disableMobile: true,
        monthSelectorType: "dropdown",
        locale: Object.assign({}, arabic || window.flatpickr.l10ns.default, { firstDayOfWeek: 6 })
      });
    });
  }
  setupDates(document);
  document.addEventListener("formset:added", function () { setupDates(document); });

  // Room schedule: a date on a usual surgery day makes the shift a surgery day (it can still be changed).
  document.addEventListener("change", function (event) {
    var el = event.target;
    if (!el.matches || !el.matches("input[data-surgery-days]")) return;
    var parts = el.value.split("/");
    var select = el.form && el.form.querySelector("select[name=day_type]");
    if (parts.length !== 3 || !select) return;
    var day = new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
    var weekday = String((day.getDay() + 6) % 7);  // Monday = 0, as in the settings
    var surgery = el.getAttribute("data-surgery-days").split(",").indexOf(weekday) >= 0;
    select.value = surgery ? "surgery" : "regular";
  });

  // Search as you type: <input data-autocomplete-url="..."> gets a list of suggestions;
  // choosing one puts its value (e.g. the file number) in the box and shows the name under it.
  function setupAutocomplete(input) {
    if (input._autocomplete) return;
    input._autocomplete = true;
    var url = input.getAttribute("data-autocomplete-url");
    var menu = document.createElement("div");
    menu.className = "dropdown-menu autocomplete-menu";
    var chosen = document.createElement("div");
    chosen.className = "form-text text-success autocomplete-chosen";
    input.parentNode.classList.add("position-relative");
    input.insertAdjacentElement("afterend", menu);
    menu.insertAdjacentElement("afterend", chosen);
    var timer = null, results = [], active = -1, request = 0;

    function hide() { menu.classList.remove("show"); active = -1; }
    function highlight() {
      menu.querySelectorAll(".dropdown-item").forEach(function (item, i) {
        item.classList.toggle("active", i === active);
      });
    }
    function pick(result) {
      input.value = result.value;
      chosen.textContent = "\u2713 " + result.label;
      hide();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    function show(list) {
      results = list;
      menu.innerHTML = "";
      if (!list.length) {
        var empty = document.createElement("span");
        empty.className = "dropdown-item-text text-muted small";
        empty.textContent = menu.getAttribute("data-empty") || "\u2014";
        menu.appendChild(empty);
      }
      list.forEach(function (result, i) {
        var item = document.createElement("button");
        item.type = "button";
        item.className = "dropdown-item";
        item.textContent = result.label;
        item.addEventListener("mousedown", function (event) { event.preventDefault(); pick(results[i]); });
        menu.appendChild(item);
      });
      active = list.length ? 0 : -1;
      highlight();
      menu.classList.add("show");
    }
    input.addEventListener("input", function () {
      chosen.textContent = "";
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 2) { hide(); return; }
      timer = setTimeout(function () {
        var mine = ++request;
        fetch(url + (url.indexOf("?") < 0 ? "?" : "&") + "q=" + encodeURIComponent(q), {
          headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin"
        }).then(function (r) { return r.json(); }).then(function (data) {
          if (mine === request) show(data.results || []);
        }).catch(hide);
      }, 200);
    });
    input.addEventListener("keydown", function (event) {
      if (!menu.classList.contains("show")) return;
      if (event.key === "ArrowDown") { active = Math.min(active + 1, results.length - 1); highlight(); event.preventDefault(); }
      else if (event.key === "ArrowUp") { active = Math.max(active - 1, 0); highlight(); event.preventDefault(); }
      else if (event.key === "Enter" && active >= 0) { pick(results[active]); event.preventDefault(); }
      else if (event.key === "Escape") { hide(); }
    });
    input.addEventListener("blur", function () { setTimeout(hide, 150); });
  }
  document.querySelectorAll("input[data-autocomplete-url]").forEach(setupAutocomplete);
  document.addEventListener("focusin", function (event) {
    if (event.target.matches && event.target.matches("input[data-autocomplete-url]")) setupAutocomplete(event.target);
  });

  // A chosen picture (e.g. the ID scan) shows at once under the file box.
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("input[type=file]") || !input.files || !input.files[0]) return;
    var file = input.files[0];
    var preview = input.parentNode.querySelector("img.file-preview");
    if (!/^image\//.test(file.type)) { if (preview) preview.remove(); return; }
    if (!preview) {
      preview = document.createElement("img");
      preview.className = "file-preview";
      input.insertAdjacentElement("afterend", preview);
    }
    preview.src = URL.createObjectURL(file);
  });

  // Dynamic formsets: <div data-formset="prefix"> with a <template> row and an "add" button.
  document.querySelectorAll("[data-formset]").forEach(function (box) {
    var prefix = box.getAttribute("data-formset");
    var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    var template = box.querySelector("template");
    var rows = box.querySelector("[data-formset-rows]");
    var addButton = box.querySelector("[data-formset-add]");
    if (!total || !template || !rows || !addButton) return;
    addButton.addEventListener("click", function () {
      var index = parseInt(total.value, 10);
      var html = template.innerHTML.replace(/__prefix__/g, String(index));
      rows.insertAdjacentHTML("beforeend", html);
      total.value = String(index + 1);
      document.dispatchEvent(new CustomEvent("formset:added", { detail: { prefix: prefix } }));
    });
  });
})();
