/* The Paper Reader's small helpers: confirm before a step, a send button that works once, the date picker,
   and the list of registered patients while typing in "whose file". No build step. */
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-confirm]");
    if (button && !window.confirm(button.getAttribute("data-confirm"))) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.method.toLowerCase() !== "post") { return; }
    if (form.dataset.sent) { event.preventDefault(); return; }
    form.dataset.sent = "1";
    var button = event.submitter;
    if (button && button.name) {  // the pressed button's value still goes with the form
      var keep = document.createElement("input");
      keep.type = "hidden"; keep.name = button.name; keep.value = button.value;
      form.appendChild(keep);
    }
    if (button) {
      button.disabled = true;
      button.innerHTML = document.body.dataset.savingText || "…";
    }
  });

  var arabic = document.documentElement.lang === "ar";
  if (window.flatpickr) {
    document.querySelectorAll('input[placeholder="dd/mm/yyyy"]').forEach(function (input) {
      window.flatpickr(input, {dateFormat: "d/m/Y", allowInput: true, locale: arabic && window.flatpickr.l10ns.ar ? "ar" : "default"});
    });
  }

  var list = document.getElementById("known-patients");
  var box = document.querySelector('input[list="known-patients"]');
  if (list && box) {
    var timer;
    box.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var text = box.value.trim();
        if (text.length < 2) { return; }
        fetch(list.dataset.lookup + "?q=" + encodeURIComponent(text), {credentials: "same-origin"})
          .then(function (response) { return response.json(); })
          .then(function (data) {
            list.innerHTML = "";
            data.results.forEach(function (row) {
              var option = document.createElement("option");
              option.value = row.value; option.label = row.label; option.textContent = row.label;
              list.appendChild(option);
            });
          });
      }, 250);
    });
  }
})();
