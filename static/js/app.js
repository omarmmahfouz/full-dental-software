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

  // Convert Arabic-Indic digits to Western digits while typing in number-like fields.
  var arabicDigits = /[٠-٩۰-۹]/g;
  document.addEventListener("input", function (event) {
    var el = event.target;
    if (!el.matches || !el.matches("input[data-digits], input[type=tel]")) return;
    if (arabicDigits.test(el.value)) {
      el.value = el.value.replace(arabicDigits, function (d) {
        var code = d.charCodeAt(0);
        return String(code >= 0x06F0 ? code - 0x06F0 : code - 0x0660);
      });
    }
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
