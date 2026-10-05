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

  // The pages opened in this tab are kept in order (the "trail"; a page sending a form leaves it): the browser's own
  // back button skips a form already saved (pageInsteadOfForm). The "Up" button at the top of a page is a plain link
  // to the page above it, the "folder" it belongs to (round 14: it used to go back one step, like the browser).
  var TRAIL = "page-trail";
  var here = window.location.pathname + window.location.search;
  function readTrail() { try { return JSON.parse(sessionStorage.getItem(TRAIL) || "[]"); } catch (e) { return []; } }
  function writeTrail(trail) { try { sessionStorage.setItem(TRAIL, JSON.stringify(trail.slice(-30))); } catch (e) {} }
  function updateTrail() {
    var trail = readTrail(), sent = null;
    try { sent = sessionStorage.getItem("page-sent"); sessionStorage.removeItem("page-sent"); } catch (e) {}
    if (sent) trail = trail.filter(function (page) { return page.url !== sent; });
    for (var i = 0; i < trail.length; i++) {
      if (trail[i].url === here) { trail = trail.slice(0, i); break; }  // back on a page already in the trail
    }
    if (!document.body.classList.contains("login-page")) {
      trail.push({ url: here, title: document.title.split(" · ")[0] });
    }
    writeTrail(trail);
    return trail;
  }
  updateTrail();
  window.addEventListener("pageshow", function (event) { if (event.persisted) updateTrail(); });

  // The address a form is sent to. Not form.action: a button named "action" (the reception board's Arrived, Left...)
  // hides it, and the form went to "[object RadioNodeList]" (round 15).
  function formAddress(form) {
    return new URL(form.getAttribute("action") || window.location.href, window.location.href).href;
  }

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
  // A pop-up inside a card or a tab that moves (an animation, a hover lift) opened under its own grey backdrop, so
  // its OK and its cross could not be pressed (round 15). A pop-up with nothing to send goes to the end of the page
  // before it opens; one holding fields of a form stays in the form (the cards no longer keep a transform).
  document.addEventListener("show.bs.modal", function (event) {
    var box = event.target;
    if (box.parentElement === document.body) return;
    if (box.closest("form") && box.querySelector("input:not([type=hidden]), select, textarea")) return;
    document.body.appendChild(box);
  });
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

  // A form that opens WhatsApp in a new tab (the message to many, round 15): this tab shows the next one.
  document.addEventListener("submit", function (event) {
    if (event.target.matches && event.target.matches("form[data-reload-after-send]")) {
      setTimeout(function () { window.location.reload(); }, 1200);
    }
  });

  // A tick that shows its own boxes (round 15): data-reveals="name,name" names the fields shown only while it is
  // ticked (e.g. "An old paper file" shows the file number; a GBR shows its details). A field with an error stays.
  function revealFrom(box) {
    var form = box.form || document;
    box.getAttribute("data-reveals").split(",").forEach(function (name) {
      form.querySelectorAll('[name="' + name.trim() + '"], [name^="' + name.trim() + '_"]').forEach(function (el) {
        var wrap = el.closest("[class*='col-']") || el.parentNode;
        wrap.hidden = !box.checked && !wrap.querySelector(".errorlist");
      });
    });
  }
  document.querySelectorAll("input[data-reveals]").forEach(function (box) {
    revealFrom(box);
    box.addEventListener("change", function () { revealFrom(box); });
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
  // A patient chosen in a box with data-reload-with="patient" opens the page again for him while nothing else is
  // typed yet (e.g. a complaint: his earlier complaints show first, round 15).
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("input[data-reload-with]") || !input.value.trim()) return;
    var typed = Array.prototype.some.call(input.form ? input.form.querySelectorAll("textarea") : [], function (box) {
      return box.value.trim();
    });
    if (typed) return;
    var url = new URL(window.location.href);
    url.searchParams.set(input.getAttribute("data-reload-with"), input.value.trim());
    if (input.form) input.form.setAttribute("data-no-leave-warning", "");
    window.location.href = url.toString();
  });
  document.addEventListener("focusin", function (event) {
    if (event.target.matches && event.target.matches("input[data-autocomplete-url]")) setupAutocomplete(event.target);
  });

  // A chosen picture shows at once under the file box (an ID card shows in its own check, static/js/idcard.js).
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (!input.matches || !input.matches("input[type=file]:not([data-id-card])") || !input.files || !input.files[0]) return;
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

  // Unsaved data: after typing in a form, leaving the page asks "Save / Leave without saving / Stay".
  // Forms marked data-no-leave-warning (and search forms, which use GET) are not watched, and links
  // inside data-in-page-links are handled by the page itself (e.g. the day grid fills the booking form).
  var dirtyForm = null;
  var leaving = false;
  function watched(form) {
    return form && (form.getAttribute("method") || "").toLowerCase() === "post" && !form.hasAttribute("data-no-leave-warning");
  }
  function markDirty(event) {
    var form = event.target.form || (event.target.closest && event.target.closest("form"));
    if (watched(form)) dirtyForm = form;
  }
  document.addEventListener("input", markDirty);
  document.addEventListener("change", markDirty);
  // A form sent back with errors still holds data that is not saved.
  document.querySelectorAll("form").forEach(function (form) {
    if (watched(form) && form.querySelector(".errorlist, .is-invalid")) dirtyForm = form;
  });
  // A closed part of a form (optional, or filled before) opens when it holds an error.
  document.querySelectorAll("form details").forEach(function (part) {
    if (part.querySelector(".errorlist, .is-invalid")) part.open = true;
  });
  var nativeSubmit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () {
    if (this === dirtyForm || !dirtyForm) { dirtyForm = null; leaving = true; }
    return nativeSubmit.apply(this, arguments);
  };
  var leaveBox = document.getElementById("leave-warning");
  var pendingLeave = null;
  function askBeforeLeaving(go) {
    if (!leaveBox || !window.bootstrap) { if (window.confirm(leaveBox ? leaveBox.querySelector(".modal-body").textContent : "")) go(); return; }
    pendingLeave = go;
    window.bootstrap.Modal.getOrCreateInstance(leaveBox).show();
  }
  if (leaveBox) {
    leaveBox.addEventListener("click", function (event) {
      var button = event.target.closest("[data-leave]");
      if (!button) return;
      var form = dirtyForm;
      window.bootstrap.Modal.getOrCreateInstance(leaveBox).hide();
      if (button.getAttribute("data-leave") === "save" && form) {
        var submitter = form.querySelector("button:not([type=button]):not([name]).btn-primary, button[type=submit].btn-primary") ||
                        form.querySelector("button:not([type=button]):not([name])");
        if (form.requestSubmit) { form.requestSubmit(submitter || undefined); } else { dirtyForm = null; leaving = true; nativeSubmit.call(form); }
      } else if (pendingLeave) {
        dirtyForm = null;
        leaving = true;
        pendingLeave();
      }
      pendingLeave = null;
    });
  }
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (dirtyForm && form !== dirtyForm && !form.hasAttribute("data-no-leave-warning") && document.contains(dirtyForm)) {
      event.preventDefault();
      var submitter = event.submitter;
      askBeforeLeaving(function () {
        if (submitter && submitter.name) {
          var extra = document.createElement("input");
          extra.type = "hidden"; extra.name = submitter.name; extra.value = submitter.value;
          form.appendChild(extra);
        }
        nativeSubmit.call(form);
      });
      return;
    }
    if (form === dirtyForm) { dirtyForm = null; leaving = true; }
  });
  document.addEventListener("click", function (event) {
    if (!dirtyForm || !document.contains(dirtyForm) || event.defaultPrevented) return;
    var link = event.target.closest("a[href]");
    if (!link || link.target === "_blank" || link.hasAttribute("download") || link.hasAttribute("data-bs-toggle") ||
        link.closest("[data-in-page-links]") || event.ctrlKey || event.metaKey || event.shiftKey) return;
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    askBeforeLeaving(function () {
      window.location.href = link.href;
    });
  }, true);
  window.addEventListener("beforeunload", function (event) {
    if (dirtyForm && !leaving && document.contains(dirtyForm)) { event.preventDefault(); event.returnValue = ""; }
  });

  // "Report a problem" (user menu): sent without leaving the page, so nothing typed is lost. A picture of the page,
  // a video of the screen (where the browser allows it) or a photo / video chosen goes with it (round 13).
  var problemForm = document.querySelector("#report-problem form"), attached = null;
  function attach(file) {
    attached = file;
    var box = problemForm.querySelector("[data-problem-attached]"), preview = box.querySelector("[data-problem-preview]");
    if (preview._url) URL.revokeObjectURL(preview._url);
    preview.innerHTML = "";
    box.hidden = !file;
    if (!file) return;
    preview._url = URL.createObjectURL(file.blob);
    var shown = document.createElement(file.field === "video" ? "video" : "img");
    shown.src = preview._url;
    if (file.field === "video") { shown.controls = true; shown.muted = true; }
    preview.appendChild(shown);
    box.querySelector("[data-problem-name]").textContent = file.name + " (" + Math.max(1, Math.round(file.blob.size / 1024)) + " KB)";
  }
  function stamp() {
    var now = new Date(), pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) + "-" + pad(now.getHours()) + pad(now.getMinutes());
  }
  if (problemForm) {
    var problemBox = document.getElementById("report-problem"), problemTexts = document.querySelector("[data-problem-texts]");
    function problemModal(show) {
      // Hiding waits until the window is gone (a window that is still closing cannot be opened again).
      if (!window.bootstrap) return Promise.resolve();
      var modal = window.bootstrap.Modal.getOrCreateInstance(problemBox);
      if (show) { modal.show(); return Promise.resolve(); }
      if (!problemBox.classList.contains("show")) return Promise.resolve();
      return new Promise(function (resolve) {
        problemBox.addEventListener("hidden.bs.modal", function () { setTimeout(resolve, 60); }, { once: true });
        modal.hide();
      });
    }
    problemForm.querySelector("[data-problem-file]").addEventListener("change", function (event) {
      var file = event.target.files && event.target.files[0];
      if (file) attach({ field: /^video\//.test(file.type) ? "video" : "screenshot", blob: file, name: file.name });
      event.target.value = "";
    });
    problemForm.querySelector("[data-problem-remove]").addEventListener("click", function () { attach(null); });
    // A picture of what is on the screen now (the page under the window), taken here.
    problemForm.querySelector("[data-problem-shot]").addEventListener("click", function () {
      problemModal(false).then(function () {
        return loadScript(document.body.getAttribute("data-vendor-html2canvas")).then(function () {
          return window.html2canvas(document.body, { scale: 1, backgroundColor: "#ffffff", x: window.scrollX, y: window.scrollY,
                                                     width: window.innerWidth, height: window.innerHeight,
                                                     onclone: function (doc) { doc.body.classList.add("is-snapshot"); plainColours(doc); },
                                                     ignoreElements: function (el) { return el.id === "report-problem" || el.classList.contains("modal-backdrop"); } });
        }).then(function (canvas) {
          return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.85); });
        }).then(function (blob) {
          if (blob) attach({ field: "screenshot", blob: blob, name: "page-" + stamp() + ".jpg" });
        });
      }).catch(function () { window.alert(problemTexts.getAttribute("data-error")); })
        .then(function () { problemModal(true); });
    });
    // A video of the screen: the browser asks which window or screen; Stop (or 3 minutes) ends it.
    var recordButton = problemForm.querySelector("[data-problem-record]");
    var canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia && window.MediaRecorder);
    recordButton.hidden = !canRecord;
    problemForm.querySelector("[data-problem-record-help]").hidden = !canRecord;
    problemForm.querySelector("[data-problem-film-help]").hidden = canRecord;
    recordButton.addEventListener("click", function () {
      var bar = document.querySelector("[data-problem-recording]"), clock = bar.querySelector("[data-problem-clock]");
      // The browser asks for the screen at once (it must follow the tap), then the window closes.
      var asked = navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 12 }, audio: false });
      asked.catch(function () {});  // answered below
      problemModal(false).then(function () { return asked; }).then(function (stream) {
        var type = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].filter(function (t) {
          return !MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(t);
        })[0];
        var recorder = new MediaRecorder(stream, type ? { mimeType: type, videoBitsPerSecond: 900000 } : undefined);
        var parts = [], started = Date.now(), timer;
        recorder.ondataavailable = function (event) { if (event.data && event.data.size) parts.push(event.data); };
        recorder.onstop = function () {
          clearInterval(timer); bar.hidden = true;
          stream.getTracks().forEach(function (track) { track.stop(); });
          if (parts.length) attach({ field: "video", blob: new Blob(parts, { type: "video/webm" }), name: "screen-" + stamp() + ".webm" });
          problemModal(true);
        };
        function stop() { if (recorder.state !== "inactive") recorder.stop(); }
        stream.getVideoTracks()[0].addEventListener("ended", stop);
        bar.querySelector("[data-problem-stop]").onclick = stop;
        timer = setInterval(function () {
          var seconds = Math.floor((Date.now() - started) / 1000);
          clock.textContent = Math.floor(seconds / 60) + ":" + (seconds % 60 < 10 ? "0" : "") + seconds % 60;
          if (seconds >= 180) stop();
        }, 500);
        bar.hidden = false;
        recorder.start(1000);
      }).catch(function (problem) {
        if (!problem || problem.name !== "NotAllowedError") window.alert(problemTexts.getAttribute("data-record-error"));
        problemModal(true);
      });
    });
    problemForm.addEventListener("submit", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      var done = problemForm.querySelector("[data-problem-done]");
      var error = problemForm.querySelector("[data-problem-error]");
      var send = problemForm.querySelector("[data-problem-send]");
      done.hidden = error.hidden = true;
      send.disabled = true;
      var body = new FormData(problemForm);
      if (attached) body.set(attached.field, attached.blob, attached.name);
      fetch(formAddress(problemForm), {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.ok) {
          done.textContent = data.message;
          done.hidden = false;
          problemForm.querySelector("textarea").value = "";
          attach(null);
        } else {
          error.textContent = (data.errors || []).join(" ");
          error.hidden = false;
        }
      }).catch(function () {
        error.textContent = "!";
        error.hidden = false;
      }).then(function () { send.disabled = false; });
    }, true);
  }

  // Day planner of today: a red line at the current time (by this computer's clock), moved every minute.
  function drawNowLines() {
    document.querySelectorAll(".daygrid[data-now-first]").forEach(function (grid) {
      var now = new Date();
      var minutes = now.getHours() * 60 + now.getMinutes() - parseInt(grid.getAttribute("data-now-first"), 10);
      var top = minutes / parseInt(grid.getAttribute("data-now-slot"), 10) * parseInt(grid.getAttribute("data-now-row"), 10);
      var inside = top >= 0 && top <= parseInt(grid.getAttribute("data-now-height"), 10);
      grid.querySelectorAll(".daygrid-body").forEach(function (column) {
        var line = column.querySelector(".daygrid-now");
        if (!line) {
          line = document.createElement("div");
          line.className = "daygrid-now";
          column.appendChild(line);
        }
        line.hidden = !inside;
        line.style.top = top + "px";
      });
      if (inside && !grid._scrolled && !grid.closest("form")) {
        grid._scrolled = true;
        var first = grid.querySelector(".daygrid-now");
        if (first) window.scrollTo({ top: Math.max(first.getBoundingClientRect().top + window.scrollY - 200, 0) });
      }
    });
  }
  drawNowLines();
  setInterval(drawNowLines, 60000);
  document.addEventListener("daygrid:loaded", drawNowLines);

  // Up button: appears once the page is scrolled down.
  var toTop = document.querySelector("[data-to-top]");
  if (toTop) {
    var showTop = function () { toTop.classList.toggle("is-visible", window.scrollY > 400); };
    window.addEventListener("scroll", showTop, { passive: true });
    toTop.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });
    showTop();
  }

  // New notifications (e.g. "your patient arrived"): a pop-up and a short sound, checked every 30 seconds.
  var pollUrl = document.body.getAttribute("data-poll-url");
  if (pollUrl) {
    var lastSeen = parseInt(document.body.getAttribute("data-last-notification") || "0", 10);
    var audio = null;
    var soundOff = function () { try { return localStorage.getItem("alert-sound") === "off"; } catch (e) { return false; } };
    var unlock = function () {
      if (audio) return;
      try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { audio = null; }
    };
    document.addEventListener("click", unlock, { once: true });
    document.addEventListener("keydown", unlock, { once: true });
    var chime = function () {
      if (!audio || soundOff()) return;
      if (audio.state === "suspended") audio.resume();
      [[880, 0], [1320, 0.18]].forEach(function (note) {
        var osc = audio.createOscillator(), gain = audio.createGain(), start = audio.currentTime + note[1];
        osc.frequency.value = note[0];
        osc.type = "sine";
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.3, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);
        osc.connect(gain).connect(audio.destination);
        osc.start(start);
        osc.stop(start + 0.4);
      });
    };
    var toasts = document.querySelector("[data-toasts]");
    var showToast = function (item) {
      var box = document.createElement("a");
      box.className = "app-toast level-" + item.level;
      box.href = item.url;
      box.innerHTML = "<b></b><span></span>";
      box.querySelector("b").textContent = item.title;
      box.querySelector("span").textContent = item.message;
      var close = document.createElement("button");
      close.type = "button";
      close.className = "btn-close btn-close-sm";
      close.addEventListener("click", function (event) { event.preventDefault(); box.remove(); });
      box.appendChild(close);
      toasts.appendChild(box);
      setTimeout(function () { box.remove(); }, 20000);
    };
    var setBadge = function (count) {
      document.querySelectorAll("[data-bell]").forEach(function (bell) {
        var badge = bell.querySelector(".notif-badge");
        if (!badge && count) {
          badge = document.createElement("span");
          badge.className = "badge rounded-pill bg-danger notif-badge";
          bell.appendChild(badge);
        }
        if (!badge) return;
        if (count > (parseInt(badge.textContent, 10) || 0)) {
          badge.classList.remove("is-bumped");
          void badge.offsetWidth;
          badge.classList.add("is-bumped");
        }
        badge.textContent = count;
        badge.hidden = !count;
      });
    };
    // Time in the system (round 14): the check says whether the person typed, tapped or scrolled since the last one.
    var usedSince = false;
    ["pointerdown", "keydown", "wheel", "touchstart", "input"].forEach(function (name) {
      document.addEventListener(name, function () { usedSince = true; }, { passive: true, capture: true });
    });
    var check = function () {
      var active = usedSince && !document.hidden ? "&active=1" : "";
      usedSince = false;
      fetch(pollUrl + "?since=" + lastSeen + active, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) {
          // Logged out after no use (or by the owner): show the login page, not the patient's data.
          if (r.status === 401 || r.redirected && /\/login\//.test(r.url)) { window.location.reload(); return null; }
          return r.ok ? r.json() : null;
        })
        .then(function (data) {
          if (!data) return;
          setBadge(data.unread);
          data["new"].forEach(showToast);
          if (data["new"].length) chime();
          lastSeen = Math.max(lastSeen, data.last || 0);
        }).catch(function () {});
    };
    setInterval(check, 30000);
    var soundButton = document.querySelector("[data-sound-toggle]");
    if (soundButton) {
      var showSound = function () {
        soundButton.querySelector("[data-sound-on]").hidden = soundOff();
        soundButton.querySelector("[data-sound-off]").hidden = !soundOff();
      };
      soundButton.addEventListener("click", function (event) {
        event.stopPropagation();
        try { localStorage.setItem("alert-sound", soundOff() ? "on" : "off"); } catch (e) {}
        showSound();
        unlock();
        chime();
      });
      showSound();
    }
  }

  // ------------------------------------------------------------------ the look: motion and touch
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var canHover = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  // The page slides in once; the class is taken off afterwards so it never gets in the way.
  var main = document.querySelector("main.page-enter");
  if (main) main.addEventListener("animationend", function () { main.classList.remove("page-enter"); }, { once: true });

  // On the home page the cards and tiles appear one after the other, quickly (only those on the first screen). Other
  // pages show everything at once: nobody waits for a box to arrive before working.
  if (!reduceMotion && window.location.pathname === "/") {
    var order = 0;
    document.querySelectorAll("main .quick-tile, main .visit-step, main .stat-card, main .card, main .my-week-day, main .now-col").forEach(function (el) {
      if (order >= 10 || el.closest(".reveal") || el.querySelector(".modal") || el.closest(".modal")) return;
      var box = el.getBoundingClientRect();
      if (box.top > window.innerHeight || box.height === 0) return;
      el.style.setProperty("--i", order++);
      el.classList.add("reveal");
      el.addEventListener("animationend", function () { el.classList.remove("reveal"); el.style.removeProperty("--i"); }, { once: true });
    });
  }

  // Numbers on the home page count up to their value.
  document.querySelectorAll(".stat-value").forEach(function (el) {
    if (reduceMotion || el.children.length || !/^\d{1,6}$/.test(el.textContent.trim())) return;
    var target = parseInt(el.textContent.trim(), 10);
    if (target < 2) return;
    var start = null, duration = Math.min(500, 250 + target * 4);
    el.textContent = "0";
    var step = function (now) {
      if (start === null) start = now;
      var t = Math.min((now - start) / duration, 1);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) window.requestAnimationFrame(step);
    };
    window.requestAnimationFrame(step);
  });

  // Wide screens: the side rail can show icons only (it opens over the page when pointed at); each PC remembers it.
  document.querySelectorAll("[data-rail-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var compact = document.body.classList.toggle("rail-compact");
      try { localStorage.setItem("rail", compact ? "compact" : "wide"); } catch (e) {}
      button.blur();
    });
  });
  // A tap on a group of the narrow rail (a tablet held sideways, e.g. the Academy) opens the rail with that group
  // open. It used to close the group of the page shown (open, but hidden while the rail was narrow), so the tap
  // looked lost and a second tap was needed (round 15).
  // The finger's first touch also widened the rail, so the entries moved under it and the tap landed on another one
  // (Complaints instead of the Academy). Now the entry under the finger when it touched is the one opened.
  var railNav = document.querySelector(".app-navbar"), railTap = null;
  if (railNav) {
    railNav.addEventListener("pointerdown", function (event) {
      railTap = null;
      if (event.pointerType === "mouse" || !document.body.classList.contains("rail-compact") ||
          railNav.classList.contains("rail-open") || railNav.offsetWidth >= 120 ||
          !window.matchMedia("(min-width: 1200px)").matches) return;
      railTap = event.target.closest && event.target.closest("a[href], button");
    }, true);
    railNav.addEventListener("click", function (event) {
      var target = railTap;
      railTap = null;
      if (!target || !window.bootstrap) return;
      event.preventDefault();
      event.stopPropagation();
      railNav.classList.add("rail-open");
      if (target.matches(".me-auto .dropdown-toggle")) {
        target.focus();
        window.bootstrap.Dropdown.getOrCreateInstance(target).show();
      } else {
        target.click();  // a page of its own (Reception today, Complaints...), the bell, the place switch
      }
    }, true);
    document.addEventListener("pointerdown", function (event) {
      if (!railNav.contains(event.target)) railNav.classList.remove("rail-open");
    });
  }

  // The menu entry of the page being shown is marked (the longest address that matches wins).
  (function markActive() {
    var path = window.location.pathname, best = null, bestLink = null, bestLength = 0;
    document.querySelectorAll(".app-navbar .navbar-nav > .nav-item").forEach(function (item) {
      item.querySelectorAll("a[href]").forEach(function (link) {
        var href = link.getAttribute("href");
        if (!href || href === "#" || href.charAt(0) !== "/") return;
        href = href.split("?")[0];
        var matches = href === "/" ? path === "/" : path.indexOf(href) === 0;
        if (matches && href.length > bestLength) { best = item; bestLink = link; bestLength = href.length; }
      });
    });
    var top = best && best.querySelector(":scope > .nav-link");
    if (top) { top.classList.add("is-active"); top.setAttribute("aria-current", "page"); }
    // On wide screens the menu is a side rail: the group of this page is open and its entry is marked.
    if (bestLink && bestLink.classList.contains("dropdown-item")) {
      bestLink.classList.add("is-current");
      var menu = bestLink.closest(".dropdown-menu"), toggle = menu && menu.parentElement.querySelector(":scope > .dropdown-toggle");
      // Never the person's own menu (Settings is in it): opened, it covered the Settings pages on wide screens and
      // tablets held sideways (round 14).
      if (menu && toggle && !menu.closest(".user-menu") && window.matchMedia("(min-width: 1200px)").matches) {
        menu.classList.add("show"); toggle.classList.add("show"); toggle.setAttribute("aria-expanded", "true");
      }
    }
  })();

  // A thin bar at the top while the next page loads, so a tap always shows it was taken.
  var progress = document.querySelector("[data-nav-progress]");
  var progressTimer = null;
  function stopProgress() { clearTimeout(progressTimer); if (progress) progress.classList.remove("is-loading"); }
  function startProgress() {
    if (!progress) return;
    progress.classList.add("is-loading");
    clearTimeout(progressTimer);
    progressTimer = setTimeout(stopProgress, 10000);  // e.g. a file download, where the page stays
  }
  var DOWNLOADS = /(\/media\/|export|download|backup|\.zip|\.csv|\.xlsx|\.docx|\/word\/)/i;
  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0 || link.target === "_blank" ||
        link.hasAttribute("download") || link.hasAttribute("data-bs-toggle") || /^(mailto|tel|whatsapp):/.test(href) ||
        link.host !== window.location.host || DOWNLOADS.test(href)) return;
    setTimeout(function () { if (!event.defaultPrevented) startProgress(); }, 0);
  });
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.target === "_blank" || DOWNLOADS.test(form.getAttribute("action") || "")) return;
    setTimeout(function () { if (!event.defaultPrevented && !form.hasAttribute("data-no-progress")) startProgress(); }, 0);
  });
  window.addEventListener("pageshow", stopProgress);

  // Hints: closing one hides it on this page from now on (in this browser); switching hints on brings them all back.
  var userId = document.body.getAttribute("data-user");
  if (document.body.hasAttribute("data-hints-reset")) {
    try {
      Object.keys(localStorage).forEach(function (key) {
        if (key.indexOf("hint-hidden:" + userId + ":") === 0) localStorage.removeItem(key);
      });
    } catch (e) {}
  }
  document.addEventListener("click", function (event) {
    var close = event.target.closest && event.target.closest("[data-hint-close]");
    if (!close) return;
    var box = close.closest(".page-hint");
    try { localStorage.setItem("hint-hidden:" + userId + ":" + box.getAttribute("data-hint-key"), "1"); } catch (e) {}
    var tip = window.bootstrap && window.bootstrap.Tooltip.getInstance(close);
    if (tip) tip.dispose();
    box.classList.add("is-leaving");
    setTimeout(function () { box.remove(); }, 320);
  });

  // "Saved" messages fade away by themselves after a few seconds; errors and warnings stay until closed.
  document.querySelectorAll(".app-message[data-auto-hide]").forEach(function (box) {
    var timer = setTimeout(function hide() {
      if (box.matches(":hover")) { timer = setTimeout(hide, 2000); return; }
      box.classList.add("is-leaving");
      setTimeout(function () { box.remove(); }, 380);
    }, 7000);
    box.addEventListener("close.bs.alert", function () { clearTimeout(timer); });
  });

  // Short explanations on icon buttons when the mouse rests on them (not on touch screens, where they get in the way).
  if (canHover && window.bootstrap) {
    var tips = [];
    document.querySelectorAll(".btn[title], .nav-link[title]:not([data-bs-toggle]), [data-hint-close][title], [data-tip]").forEach(function (el) {
      if (el.hasAttribute("data-tip") && !el.getAttribute("title")) el.setAttribute("title", el.getAttribute("data-tip"));
      tips.push(window.bootstrap.Tooltip.getOrCreateInstance(el, { trigger: "hover", delay: { show: 350, hide: 50 } }));
    });
    document.addEventListener("click", function () { tips.forEach(function (tip) { tip.hide(); }); }, true);
  }

  // A table row with one destination opens it from anywhere in the row: easier to hit with a finger.
  document.querySelectorAll("table.table > tbody > tr").forEach(function (row) {
    if (row.querySelector("form, button, input, select, textarea, [data-bs-toggle]")) return;
    var links = row.querySelectorAll("a[href]");
    if (!links.length) return;
    var href = links[0].getAttribute("href");
    for (var i = 1; i < links.length; i++) { if (links[i].getAttribute("href") !== href) return; }
    if (!href || href.charAt(0) === "#" || links[0].target === "_blank" || links[0].host !== window.location.host ||
        links[0].hasAttribute("data-confirm") || links[0].hasAttribute("download")) return;
    row.classList.add("row-link");
    row.addEventListener("click", function (event) {
      if (event.target.closest("a") || (window.getSelection && String(window.getSelection()))) return;
      links[0].click();
    });
  });

  // A row that opens in place (the complaints): one tap shows the row under it (the complaint and a comment box).
  document.querySelectorAll("tr[data-expand-row]").forEach(function (row) {
    var panel = row.nextElementSibling;
    if (!panel) return;
    function toggle() {
      var open = panel.hidden;
      panel.hidden = !open;
      row.setAttribute("aria-expanded", open ? "true" : "false");
      row.classList.toggle("is-open", open);
      if (open) { var box = panel.querySelector("textarea"); if (box && window.matchMedia("(pointer: fine)").matches) box.focus(); }
    }
    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, select, textarea, label") || (window.getSelection && String(window.getSelection()))) return;
      toggle();
    });
    row.addEventListener("keydown", function (event) {
      if ((event.key === "Enter" || event.key === " ") && event.target === row) { event.preventDefault(); toggle(); }
    });
  });
  // A comment written on the spot is saved without leaving the page, and shows at once under the others.
  document.querySelectorAll("form[data-complaint-comment]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.fetch || !window.FormData) return;
      event.preventDefault();
      var box = form.querySelector("textarea"), error = form.querySelector("[data-comment-error]"), button = form.querySelector("button");
      error.hidden = true;
      if (!box.value.trim()) { box.focus(); return; }
      button.disabled = true;
      fetch(formAddress(form), { method: "POST", body: new FormData(form), credentials: "same-origin",
                           headers: { "X-Requested-With": "fetch" } })
        .then(function (response) { return response.json(); })
        .then(function (answer) {
          if (!answer.ok) throw new Error(answer.error || "");
          var list = form.parentElement.querySelector("[data-comment-list]"), holder = document.createElement("ul");
          holder.innerHTML = answer.html;
          var empty = list.querySelector("li.text-muted.small:only-child");
          if (empty && !empty.querySelector("strong")) empty.remove();
          var item = holder.firstElementChild;
          item.classList.add("is-new");
          list.appendChild(item);
          box.value = "";
        })
        .catch(function (problem) { error.textContent = (problem && problem.message) || "!"; error.hidden = false; })
        .then(function () { button.disabled = false; });
    });
  });

  // Long forms: Save and Cancel stay at the bottom of the screen while scrolling.
  document.querySelectorAll("form[method=post], form[method=POST]").forEach(function (form) {
    if (form.closest(".modal") || form.offsetHeight < window.innerHeight * 1.15) return;
    var last = form.lastElementChild;
    while (last && (last.matches("script, template, .modal, input[type=hidden]") || last.offsetHeight === 0)) last = last.previousElementSibling;
    if (!last || !last.querySelector("button.btn-primary, button[type=submit]")) return;
    if (last.querySelector("input:not([type=hidden]), select, textarea, table")) return;
    last.classList.add("form-actions", "is-sticky");
  });

  // Log-in page: the eye shows the password while typing it.
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-show-password]");
    if (!button) return;
    var input = document.querySelector(button.getAttribute("data-show-password"));
    if (!input) return;
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    button.querySelector(".bi").className = "bi " + (show ? "bi-eye-slash" : "bi-eye");
    input.focus();
  });

  // Choice buttons (e.g. how the patient paid): the Fawry machine is asked only when Fawry is pressed.
  function syncFawryMachine(group) {
    var form = group.closest("form");
    var machine = form && form.querySelector("select[name$='fawry_machine']");
    if (!machine) return;
    var picked = group.querySelector("input:checked");
    var box = machine.closest("[class*='col-']") || machine.parentNode;
    box.hidden = !(picked && picked.value === "fawry");
  }
  document.querySelectorAll("[data-choice-buttons]").forEach(function (group) {
    syncFawryMachine(group);
    group.addEventListener("change", function () { syncFawryMachine(group); });
  });

  // Save a printout as a picture or a PDF, or send it (receipts, prescriptions, bills):
  //   <button data-save-as="jpeg|pdf|share" data-save-target="#receipt" data-save-name="PR-000012"
  //           data-page="80mm|a5|a4" data-phone="2010..." data-text="...">
  // The two libraries are on this server (static/vendor) and load the first time they are needed.
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (document.querySelector('script[src="' + src + '"]')) { resolve(); return; }
      var script = document.createElement("script");
      script.src = src; script.onload = resolve; script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  // html2canvas reads rgb() colours only: the colours the page mixes (color-mix gives "color(srgb …)") are written
  // back as rgba() on the copy it draws (its copies of ::before and ::after are elements there too).
  function rgbOf(value) {
    return value.replace(/color\(srgb\s+([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)(?:\s*\/\s*([-\d.e]+%?))?\)/g,
      function (whole, r, g, b, a) {
        function c(v) { return Math.round(Math.max(0, Math.min(1, parseFloat(v))) * 255); }
        var alpha = a === undefined ? 1 : (a.slice(-1) === "%" ? parseFloat(a) / 100 : parseFloat(a));
        return "rgba(" + c(r) + ", " + c(g) + ", " + c(b) + ", " + alpha + ")";
      });
  }
  function plainColours(doc) {
    var view = doc.defaultView;
    var names = Array.prototype.filter.call(view.getComputedStyle(doc.documentElement), function (name) {
      return /color|shadow|image|^fill$|^stroke$/.test(name);
    });
    doc.querySelectorAll("*").forEach(function (el) {
      var style = view.getComputedStyle(el);
      names.forEach(function (prop) {
        var value = style.getPropertyValue(prop);
        if (value && value.indexOf("color(") >= 0) el.style.setProperty(prop, rgbOf(value), "important");
      });
    });
  }
  // html2canvas stretches a picture placed with object-fit (cover / contain): on the copy it draws, such a picture
  // becomes a box with the photo as its background, which it draws the right way.
  function fittedPictures(doc) {
    var view = doc.defaultView;
    doc.querySelectorAll("img").forEach(function (img) {
      var style = view.getComputedStyle(img), fit = style.objectFit;
      if (fit !== "cover" && fit !== "contain") return;
      var box = doc.createElement("div");
      box.style.cssText = "display:block;width:" + style.width + ";height:" + style.height + ";background:url(\"" +
        (img.currentSrc || img.src).replace(/"/g, "%22") + "\") center / " + fit + " no-repeat";
      img.replaceWith(box);
    });
  }
  function snapshot(target, layout) {
    // layout: a class put on the copy that is drawn (e.g. "pdf-layout": the photo pages take the shape of A4).
    // The picture stays under 16 million dots, the most a tablet's browser can draw.
    var scale = Math.min(2, Math.sqrt(16e6 / Math.max(1, target.offsetWidth * Math.max(target.offsetHeight, 1100))));
    return loadScript(document.body.getAttribute("data-vendor-html2canvas")).then(function () {
      document.body.classList.add("is-snapshot");
      return window.html2canvas(target, { scale: scale, backgroundColor: "#ffffff", useCORS: true,
                                          onclone: function (doc) {
                                            doc.body.classList.add("is-snapshot");
                                            if (layout) doc.body.classList.add(layout);
                                            plainColours(doc);
                                            fittedPictures(doc);
                                          } })
        .finally(function () { document.body.classList.remove("is-snapshot"); });
    });
  }
  function download(blob, name) {
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob); link.download = name;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 4000);
  }
  var PAGES = { "80mm": [80, null], a5: [148, 210], a4: [210, 297] };
  function toPdf(canvas, page) {
    return loadScript(document.body.getAttribute("data-vendor-jspdf")).then(function () {
      var size = PAGES[page] || PAGES.a4;
      var width = size[0], margin = page === "80mm" ? 2 : 8;
      var imageHeight = (width - 2 * margin) * canvas.height / canvas.width;
      var height = size[1] || imageHeight + 2 * margin + 1;
      var orientation = width > height ? "l" : "p";
      var pdf = new window.jspdf.jsPDF({ unit: "mm", format: [width, height], orientation: orientation });
      // A long page (e.g. a whole case report) goes on as many pages as it needs.
      var pixelsPerMm = canvas.width / (width - 2 * margin);
      var slice = Math.floor((height - 2 * margin) * pixelsPerMm);
      for (var top = 0; top < canvas.height; top += slice) {
        var part = document.createElement("canvas");
        part.width = canvas.width; part.height = Math.min(slice, canvas.height - top);
        part.getContext("2d").drawImage(canvas, 0, top, part.width, part.height, 0, 0, part.width, part.height);
        if (top > 0) pdf.addPage([width, height], orientation);
        pdf.addImage(part.toDataURL("image/jpeg", 0.92), "JPEG", margin, margin, width - 2 * margin,
                     part.height / pixelsPerMm);
      }
      return pdf.output("blob");
    });
  }
  // A report made of parts (data-save-blocks=".pdf-block, .pdf-page", round 14): each part is drawn on its own and
  // the parts are laid on A4 pages one after the other; a .pdf-page (e.g. 4 or 6 photos) fills a page of its own.
  // Before, the whole report was one long picture cut into pages: photos were cut in half, and a long report was too
  // big for a tablet to draw, so nothing was saved.
  function blocksToPdf(blocks, page) {
    return loadScript(document.body.getAttribute("data-vendor-jspdf")).then(function () {
      var size = PAGES[page] || PAGES.a4, W = size[0], H = size[1], margin = 10;
      var pdf = new window.jspdf.jsPDF({ unit: "mm", format: [W, H], orientation: "p" });
      var cw = W - 2 * margin, ch = H - 2 * margin, y = margin, empty = true;
      function newPage() { if (!empty) pdf.addPage([W, H], "p"); y = margin; empty = true; }
      function put(canvas, x, top, w, h) {
        pdf.addImage(canvas.toDataURL("image/jpeg", 0.9), "JPEG", x, top, w, h);
        empty = false;
      }
      var chain = Promise.resolve();
      Array.prototype.forEach.call(blocks, function (block) {
        if (!block.offsetHeight) return;
        chain = chain.then(function () { return snapshot(block, "pdf-layout"); }).then(function (canvas) {
          var w = cw, h = cw * canvas.height / canvas.width;
          if (block.classList.contains("pdf-page")) {
            newPage();
            if (h > ch) { w = w * ch / h; h = ch; }
            put(canvas, margin + (cw - w) / 2, margin, w, h);
            y = margin + ch + 1;  // the next part starts a new page
            return;
          }
          if (y + h > margin + ch && !empty) newPage();
          if (h <= ch) { put(canvas, margin, y, w, h); y += h + 4; return; }
          var perMm = canvas.width / cw, slice = Math.floor(ch * perMm);  // taller than a page: cut it
          for (var top = 0; top < canvas.height; top += slice) {
            if (top > 0) newPage();
            var part = document.createElement("canvas");
            part.width = canvas.width; part.height = Math.min(slice, canvas.height - top);
            part.getContext("2d").drawImage(canvas, 0, top, part.width, part.height, 0, 0, part.width, part.height);
            put(part, margin, margin, cw, part.height / perMm);
            y = margin + part.height / perMm + 4;
          }
        });
      });
      return chain.then(function () { return pdf.output("blob"); });
    });
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-save-as]");
    if (!button) return;
    var target = document.querySelector(button.getAttribute("data-save-target"));
    if (!target) return;
    var kind = button.getAttribute("data-save-as"), name = button.getAttribute("data-save-name") || "document";
    button.disabled = true;
    var blocks = button.getAttribute("data-save-blocks");
    if (blocks && kind === "pdf") {
      document.body.classList.add("is-saving");
      blocksToPdf(target.querySelectorAll(blocks), button.getAttribute("data-page"))
        .then(function (blob) { download(blob, name + ".pdf"); })
        .catch(function (error) {
          if (window.console) console.error(error);
          window.alert(button.getAttribute("data-error") || String(error));
        })
        .finally(function () { button.disabled = false; document.body.classList.remove("is-saving"); });
      return;
    }
    snapshot(target).then(function (canvas) {
      if (kind === "pdf") return toPdf(canvas, button.getAttribute("data-page")).then(function (blob) { download(blob, name + ".pdf"); });
      return new Promise(function (resolve) { canvas.toBlob(resolve, "image/jpeg", 0.92); }).then(function (blob) {
        if (kind !== "share") { download(blob, name + ".jpg"); return; }
        var file = new File([blob], name + ".jpg", { type: "image/jpeg" });
        var text = button.getAttribute("data-text") || "";
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          return navigator.share({ files: [file], text: text }).catch(function () {});
        }
        // No sharing in this browser (e.g. on the clinic's http network): save the picture, then open the chat.
        download(blob, name + ".jpg");
        var phone = button.getAttribute("data-phone");
        if (phone) window.open("https://wa.me/" + phone + "?text=" + encodeURIComponent(text), "_blank", "noopener");
        var note = button.getAttribute("data-saved-note");
        if (note) window.alert(note);
      });
    }).catch(function () {}).finally(function () { button.disabled = false; });
  });

  // Settings: "Find a list…" hides the lists whose name does not have the words typed (round 14).
  var listFind = document.querySelector("[data-list-find]");
  if (listFind) {
    listFind.addEventListener("input", function () {
      var words = listFind.value.trim().toLowerCase(), any = false;
      document.querySelectorAll("[data-list-group]").forEach(function (group) {
        var shown = 0;
        group.querySelectorAll("[data-list-item]").forEach(function (item) {
          var on = !words || item.textContent.toLowerCase().indexOf(words) >= 0;
          item.classList.toggle("d-none", !on);
          if (on) shown += 1;
        });
        group.hidden = shown === 0;
        any = any || shown > 0;
      });
      var none = document.querySelector("[data-list-none]");
      if (none) none.hidden = any;
    });
  }

  // Settings → Access by role (round 14): one role at a time; the role shown is kept in the address (#role-…).
  var accessForm = document.querySelector("[data-access-roles]");
  if (accessForm) {
    var showRole = function (code) {
      var found = false;
      accessForm.querySelectorAll("[data-role-panel]").forEach(function (panel) {
        var on = panel.getAttribute("data-role-panel") === code;
        panel.hidden = !on; found = found || on;
      });
      accessForm.querySelectorAll("[data-role-tab]").forEach(function (tab) {
        var on = tab.getAttribute("data-role-tab") === code;
        tab.classList.toggle("active", on);
        tab.setAttribute("aria-current", on ? "true" : "false");
      });
      return found;
    };
    accessForm.addEventListener("click", function (event) {
      var tab = event.target.closest("[data-role-tab]");
      if (!tab) return;
      showRole(tab.getAttribute("data-role-tab"));
      try { history.replaceState(history.state, "", "#role-" + tab.getAttribute("data-role-tab")); } catch (error) {}
    });
    if (window.location.hash.indexOf("#role-") === 0) showRole(window.location.hash.slice(6));
  }

  // "How many photos on each page?" (includes/photos_per_page.html, round 14): the button that opened it is the
  // one made blue; the texts typed on the page (the log book's descriptions) go with the choice.
  var perPage = document.getElementById("photos-per-page");
  if (perPage) {
    perPage.addEventListener("show.bs.modal", function (event) {
      var wanted = event.relatedTarget && event.relatedTarget.getAttribute("data-per-page-do");
      perPage.querySelectorAll("[data-per-page-button]").forEach(function (button) {
        var main = button.getAttribute("data-per-page-button") === wanted;
        button.classList.toggle("btn-primary", main);
        button.classList.toggle("btn-outline-primary", !main);
        button.style.order = main ? 2 : 1;
      });
    });
    perPage.querySelector("form").addEventListener("submit", function () {
      var form = this;
      document.querySelectorAll("[data-desc-code]").forEach(function (box) {
        var input = document.createElement("input");
        input.type = "hidden"; input.name = "desc_" + box.getAttribute("data-desc-code"); input.value = box.innerText.trim();
        form.appendChild(input);
      });
    });
  }
  // data-auto-do="print|pdf": the page opened again with the choice: print it or save it once the photos are in.
  var autoDo = document.querySelector("[data-auto-do]");
  if (autoDo) {
    try {
      var cleanUrl = new URL(window.location.href);
      cleanUrl.searchParams.delete("do");
      history.replaceState(history.state, "", cleanUrl.pathname + cleanUrl.search);
    } catch (error) { /* an old browser: the address keeps "do" */ }
    window.addEventListener("load", function () {
      setTimeout(function () {
        if (autoDo.getAttribute("data-auto-do") === "print") { window.print(); return; }
        var saver = document.querySelector("[data-save-as=pdf][data-save-blocks]");
        if (saver) saver.click();
      }, 300);
    });
  }

  // data-save-auto: the page was opened to be saved (e.g. "Export the file → PDF"): save it once it has loaded.
  var autoSave = document.querySelector("[data-save-auto]");
  if (autoSave) window.addEventListener("load", function () { setTimeout(function () { autoSave.click(); }, 300); });

  // data-copy="text": puts the text on the clipboard (e.g. the folder of a CBCT), and shows a tick for a moment.
  // navigator.clipboard needs https; on the clinic's http network the older way is used.
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-copy]");
    if (!button) return;
    var text = button.getAttribute("data-copy");
    var done = function () {
      var icon = button.querySelector(".bi");
      if (!icon) return;
      icon.className = "bi bi-check2 text-success";
      setTimeout(function () { icon.className = "bi bi-clipboard"; }, 1500);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done);
      return;
    }
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { if (document.execCommand("copy")) done(); } catch (error) { /* the text stays visible to copy by hand */ }
    document.body.removeChild(area);
  });

  // Photo editor (charting/photo_edit.html): turn, mirror, crop and lighten a photo here in the page, then send
  // the result (a JPEG) to the server, which keeps the photo as it was taken.
  document.querySelectorAll("[data-photo-editor]").forEach(function (box) {
    var view = box.querySelector("[data-edit-view]"), frame = box.querySelector("[data-crop]");
    var stage = box.querySelector(".photo-editor-stage"), loading = box.querySelector("[data-loading]");
    var image = new Image(), base = null, drag = null;
    var MAX_VIEW = 1400, MAX_OUT = 4000, MIN = 0.05;
    var state = { turn: 0, flipX: false, flipY: false, ratio: 4 / 3, crop: null,
                  adjust: { brightness: 0, contrast: 0, saturation: 0 } };

    function oriented(maxSide) {
      var w = image.naturalWidth, h = image.naturalHeight, turned = state.turn % 180 !== 0;
      var outW = turned ? h : w, outH = turned ? w : h;
      var scale = Math.min(1, maxSide / Math.max(outW, outH));
      var canvas = document.createElement("canvas");
      canvas.width = Math.round(outW * scale); canvas.height = Math.round(outH * scale);
      var ctx = canvas.getContext("2d");
      ctx.translate(canvas.width / 2, canvas.height / 2);
      ctx.scale(state.flipX ? -1 : 1, state.flipY ? -1 : 1);
      ctx.rotate(state.turn * Math.PI / 180);
      ctx.drawImage(image, -w * scale / 2, -h * scale / 2, w * scale, h * scale);
      return canvas;
    }
    function cssFilter() {
      var a = state.adjust;
      return "brightness(" + (1 + a.brightness / 100) + ") contrast(" + (1 + a.contrast / 100) + ") saturate(" +
        (1 + a.saturation / 100) + ")";
    }
    function fullFrame() {
      if (!state.ratio) return { x: 0, y: 0, w: 1, h: 1 };
      var W = base.width, H = base.height, w = W, h = w / state.ratio;
      if (h > H) { h = H; w = h * state.ratio; }
      return { x: (W - w) / 2 / W, y: (H - h) / 2 / H, w: w / W, h: h / H };
    }
    function showFrame() {
      var c = state.crop;
      frame.hidden = false;
      frame.style.left = c.x * 100 + "%"; frame.style.top = c.y * 100 + "%";
      frame.style.width = c.w * 100 + "%"; frame.style.height = c.h * 100 + "%";
    }
    function render(keepCrop) {
      base = oriented(MAX_VIEW);
      view.width = base.width; view.height = base.height;
      view.getContext("2d").drawImage(base, 0, 0);
      view.style.filter = cssFilter();
      if (!keepCrop || !state.crop) state.crop = fullFrame();
      showFrame();
    }
    function point(event) {
      var rect = view.getBoundingClientRect();
      return { x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
               y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)) };
    }
    function shape(x0, y0, x1, y1) {
      // A frame from one corner to the other, kept to the chosen shape (4:3, 1:1) and inside the photo (the corner
      // being dragged stays on the photo, so shrinking to the shape keeps the frame inside it).
      x1 = Math.min(1, Math.max(0, x1)); y1 = Math.min(1, Math.max(0, y1));
      var w = Math.abs(x1 - x0), h = Math.abs(y1 - y0);
      if (state.ratio) {
        var aspect = base.width / base.height;  // normalised height of a frame of normalised width w
        if (w / h * aspect > state.ratio) w = h * state.ratio / aspect; else h = w * aspect / state.ratio;
      }
      var x = x1 < x0 ? x0 - w : x0, y = y1 < y0 ? y0 - h : y0;
      return { x: x, y: y, w: w, h: h };
    }
    // Round 14: the frame has a handle at each corner (inside the photo, big enough for a finger): dragging a corner
    // resizes the frame from the opposite corner, dragging inside moves it, dragging outside draws a new one. A frame
    // that fills the whole photo is shrunk from the corners (before, only a half-hidden corner could, so a 4:3 photo
    // could not be cropped on a tablet).
    stage.addEventListener("pointerdown", function (event) {
      if (!base) return;
      var p = point(event), c = state.crop, corner = event.target.closest("[data-crop-corner]");
      stage.setPointerCapture(event.pointerId);
      if (corner) {
        var where = corner.getAttribute("data-crop-corner");
        drag = { mode: "size", x0: where.indexOf("w") >= 0 ? c.x + c.w : c.x, y0: where.indexOf("n") >= 0 ? c.y + c.h : c.y };
      } else if (event.target === frame || frame.contains(event.target)) drag = { mode: "move", p: p, c: Object.assign({}, c) };
      else drag = { mode: "draw", x0: p.x, y0: p.y };
      frame.classList.add("is-dragging");
      event.preventDefault();
    });
    stage.addEventListener("pointermove", function (event) {
      if (!drag) return;
      var p = point(event);
      if (drag.mode === "move") {
        var c = drag.c;
        state.crop = { x: Math.min(1 - c.w, Math.max(0, c.x + p.x - drag.p.x)),
                       y: Math.min(1 - c.h, Math.max(0, c.y + p.y - drag.p.y)), w: c.w, h: c.h };
      } else {
        var next = shape(drag.x0, drag.y0, p.x, p.y);
        if (next.w >= MIN && next.h >= MIN) state.crop = next;
      }
      showFrame();
    });
    ["pointerup", "pointercancel"].forEach(function (name) {
      stage.addEventListener(name, function () { drag = null; frame.classList.remove("is-dragging"); });
    });
    box.querySelectorAll("[data-edit]").forEach(function (button) {
      button.addEventListener("click", function () {
        var what = button.getAttribute("data-edit");
        if (what === "left") { state.turn = (state.turn + 270) % 360; render(); }
        else if (what === "right") { state.turn = (state.turn + 90) % 360; render(); }
        else if (what === "flip") { state.flipX = !state.flipX; render(); }
        else if (what === "flip-v") { state.flipY = !state.flipY; render(); }
        else if (what === "reset") {
          state.turn = 0; state.flipX = state.flipY = false;
          state.adjust = { brightness: 0, contrast: 0, saturation: 0 };
          box.querySelectorAll("[data-adjust]").forEach(function (input) { input.value = 0; });
          render();
        } else if (what === "save") save(button);
      });
    });
    box.querySelectorAll("[data-ratio]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.ratio = parseFloat(button.getAttribute("data-ratio")) || 0;
        box.querySelectorAll("[data-ratio]").forEach(function (other) {
          other.classList.toggle("active", other === button);
          other.setAttribute("aria-pressed", other === button ? "true" : "false");
        });
        state.crop = fullFrame(); showFrame();
      });
    });
    box.querySelectorAll("[data-adjust]").forEach(function (input) {
      input.addEventListener("input", function () {
        state.adjust[input.getAttribute("data-adjust")] = parseInt(input.value, 10) || 0;
        view.style.filter = cssFilter();
      });
    });
    function adjustPixels(ctx, width, height) {
      var a = state.adjust;
      if (!a.brightness && !a.contrast && !a.saturation) return;
      var light = 1 + a.brightness / 100, contrast = 1 + a.contrast / 100, colour = 1 + a.saturation / 100;
      var data = ctx.getImageData(0, 0, width, height), px = data.data;
      for (var i = 0; i < px.length; i += 4) {
        var r = (px[i] * light - 128) * contrast + 128, g = (px[i + 1] * light - 128) * contrast + 128,
            b = (px[i + 2] * light - 128) * contrast + 128;
        var grey = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        px[i] = grey + (r - grey) * colour; px[i + 1] = grey + (g - grey) * colour; px[i + 2] = grey + (b - grey) * colour;
      }
      ctx.putImageData(data, 0, 0);
    }
    function save(button) {
      button.disabled = true; loading.hidden = false;
      setTimeout(function () {  // let the page show the spinner first
        var full = oriented(MAX_OUT), c = state.crop;
        var sx = Math.round(c.x * full.width), sy = Math.round(c.y * full.height);
        var sw = Math.max(1, Math.round(c.w * full.width)), sh = Math.max(1, Math.round(c.h * full.height));
        var out = document.createElement("canvas");
        out.width = sw; out.height = sh;
        var ctx = out.getContext("2d");
        ctx.drawImage(full, sx, sy, sw, sh, 0, 0, sw, sh);
        adjustPixels(ctx, sw, sh);
        out.toBlob(function (blob) {
          var data = new FormData();
          data.append("image", blob, "photo.jpg");
          data.append("csrfmiddlewaretoken", box.querySelector("[name=csrfmiddlewaretoken]").value);
          fetch(box.getAttribute("data-save-url"), { method: "POST", body: data, credentials: "same-origin",
                                                     headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (response) { return response.json(); })
            .then(function (answer) {
              if (answer.ok) { window.location.href = answer.next; return; }
              throw new Error(answer.error);
            })
            .catch(function (error) {
              window.alert((error && error.message) || box.getAttribute("data-error"));
              button.disabled = false; loading.hidden = true;
            });
        }, "image/jpeg", 0.92);
      }, 30);
    }
    image.onload = function () { loading.hidden = true; render(); };
    image.onerror = function () { loading.hidden = true; window.alert(box.getAttribute("data-error")); };
    image.src = box.getAttribute("data-src");
    frame.innerHTML = ["nw", "ne", "sw", "se"].map(function (where) {
      return '<span class="photo-crop-corner corner-' + where + '" data-crop-corner="' + where + '"></span>';
    }).join("");
  });

  // The city list follows the governorate (the patient form): input[data-city-list] gets a list of the cities of the
  // governorate chosen, and "Other" to write a place that is not on it (apps/core/egypt.py). The text box keeps the
  // value that is saved; without JavaScript it is an ordinary box.
  document.querySelectorAll("input[data-city-list]").forEach(function (input) {
    var lists, OTHER = "__other__";
    try { lists = JSON.parse(input.getAttribute("data-city-list")); } catch (e) { return; }
    var form = input.form, governorate = form && form.querySelector("[name='" + (input.getAttribute("data-governorate") || "governorate") + "']");
    if (!governorate) return;
    var select = document.createElement("select"), shownFor = governorate.value;
    select.className = "form-select city-select" + (input.classList.contains("is-invalid") ? " is-invalid" : "");
    select.id = input.id + "_list";
    input.insertAdjacentElement("beforebegin", select);
    var label = form.querySelector("label[for='" + input.id + "']");
    if (label) label.setAttribute("for", select.id);
    function cities() { return lists[governorate.value] || []; }
    function add(value, text) {
      var option = document.createElement("option");
      option.value = value; option.textContent = text;
      select.appendChild(option);
    }
    function sync() {
      var list = cities();
      select.hidden = !list.length;
      if (!list.length) { input.hidden = false; return; }
      if (!input.value) { select.value = ""; input.hidden = true; }
      else if (list.indexOf(input.value) >= 0) { select.value = input.value; input.hidden = true; }
      else { select.value = OTHER; input.hidden = false; }
    }
    function build() {
      select.innerHTML = "";
      add("", input.getAttribute("data-choose-label") || "—");
      cities().forEach(function (city) { add(city, city); });
      add(OTHER, input.getAttribute("data-other-label") || "…");
      sync();
    }
    select.addEventListener("change", function () {
      if (select.value === OTHER) {
        if (cities().indexOf(input.value) >= 0) input.value = "";
        input.hidden = false; input.focus();
      } else { input.value = select.value; input.hidden = true; }
    });
    governorate.addEventListener("change", function () {
      // A city chosen from the list of the governorate before is cleared; a place written by hand stays.
      if (input.value && (lists[shownFor] || []).indexOf(input.value) >= 0 && cities().indexOf(input.value) < 0) input.value = "";
      shownFor = governorate.value;
      build();
    });
    input.addEventListener("change", sync);
    build();
  });

  // The signature pad (user menu → My signature, a doctor's page): drawn with a finger, the tablet's pen or the
  // mouse, and saved as a picture cut to the signature. A photo of a signature on paper becomes a drawing too: the
  // paper turns transparent and the ink dark blue (apps/core/signatures.py).
  document.querySelectorAll("canvas[data-signature-pad]").forEach(function (canvas) {
    var form = canvas.closest("form"), ctx = canvas.getContext("2d", { willReadFrequently: true }), drawing = false, drawn = false, last = null;
    var INK = "#0b2a6b";
    canvas.style.touchAction = "none";
    function point(event) {
      var box = canvas.getBoundingClientRect();
      return { x: (event.clientX - box.left) * canvas.width / box.width, y: (event.clientY - box.top) * canvas.height / box.height };
    }
    canvas.addEventListener("pointerdown", function (event) {
      event.preventDefault();
      if (canvas.setPointerCapture) canvas.setPointerCapture(event.pointerId);
      drawing = true; drawn = true; last = point(event);
      ctx.fillStyle = INK; ctx.beginPath(); ctx.arc(last.x, last.y, 2.4, 0, Math.PI * 2); ctx.fill();
      form.querySelector("[data-signature-empty]").hidden = true;
    });
    canvas.addEventListener("pointermove", function (event) {
      if (!drawing) return;
      event.preventDefault();
      var now = point(event);
      ctx.strokeStyle = INK; ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.lineWidth = event.pointerType === "pen" && event.pressure ? 2.5 + 4 * event.pressure : 4.5;
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(now.x, now.y); ctx.stroke();
      last = now;
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach(function (name) {
      canvas.addEventListener(name, function () { drawing = false; });
    });
    form.querySelector("[data-signature-clear]").addEventListener("click", function () {
      ctx.clearRect(0, 0, canvas.width, canvas.height); drawn = false;
    });
    var photo = form.querySelector("[data-signature-photo]");
    if (photo) photo.addEventListener("change", function () {
      var file = photo.files && photo.files[0];
      if (!file) return;
      var image = new Image(), url = URL.createObjectURL(file);
      image.onload = function () {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        var scale = Math.min(canvas.width / image.width, canvas.height / image.height);
        var w = image.width * scale, h = image.height * scale;
        ctx.drawImage(image, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h);
        var data = ctx.getImageData(0, 0, canvas.width, canvas.height), px = data.data;
        for (var i = 0; i < px.length; i += 4) {
          var light = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
          if (light > 150) px[i + 3] = 0;
          else { px[i] = 11; px[i + 1] = 42; px[i + 2] = 107; px[i + 3] = Math.min(255, Math.round((150 - light) * 3)); }
        }
        ctx.putImageData(data, 0, 0);
        URL.revokeObjectURL(url); drawn = true; photo.value = "";
      };
      image.src = url;
    });
    function trimmed() {
      // Only the part that holds the signature, with a small margin.
      var px = ctx.getImageData(0, 0, canvas.width, canvas.height).data, top = canvas.height, left = canvas.width, right = -1, bottom = -1;
      for (var y = 0; y < canvas.height; y++) for (var x = 0; x < canvas.width; x++) {
        if (px[(y * canvas.width + x) * 4 + 3] > 20) { if (x < left) left = x; if (x > right) right = x; if (y < top) top = y; if (y > bottom) bottom = y; }
      }
      if (right < 0) return null;
      var pad = 12, out = document.createElement("canvas");
      left = Math.max(0, left - pad); top = Math.max(0, top - pad);
      out.width = Math.min(canvas.width, right + pad) - left; out.height = Math.min(canvas.height, bottom + pad) - top;
      out.getContext("2d").drawImage(canvas, left, top, out.width, out.height, 0, 0, out.width, out.height);
      return out;
    }
    form.addEventListener("submit", function (event) {
      var cut = drawn ? trimmed() : null;
      if (!cut) { event.preventDefault(); form.querySelector("[data-signature-empty]").hidden = false; return; }
      form.querySelector("[data-signature-value]").value = cut.toDataURL("image/png");
    });
  });

  // Dynamic formsets: <div data-formset="prefix"> with a <template> row and "add" buttons.
  // A page can have several row lists (e.g. the plan's implant and restorative parts):
  // <button data-formset-add="implant"> adds to <tbody data-formset-rows="implant">.
  function filterCategory(rows) {
    var category = rows.getAttribute("data-category");
    if (!category) return;
    rows.querySelectorAll("select").forEach(function (select) {
      Array.prototype.forEach.call(select.options, function (option) {
        var other = option.hasAttribute("data-category") && option.getAttribute("data-category") !== category && !option.selected;
        option.hidden = other;
        option.disabled = other;
      });
    });
  }
  document.querySelectorAll("[data-formset-rows][data-category]").forEach(filterCategory);
  document.querySelectorAll("[data-formset]").forEach(function (box) {
    var prefix = box.getAttribute("data-formset");
    var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    var template = box.querySelector("template");
    if (!total || !template) return;
    box.querySelectorAll("[data-formset-add]").forEach(function (addButton) {
      addButton.addEventListener("click", function () {
        var target = addButton.getAttribute("data-formset-add");
        var rows = box.querySelector(target ? '[data-formset-rows="' + target + '"]' : "[data-formset-rows]");
        if (!rows) return;
        var index = parseInt(total.value, 10);
        rows.insertAdjacentHTML("beforeend", template.innerHTML.replace(/__prefix__/g, String(index)));
        total.value = String(index + 1);
        var row = rows.lastElementChild;
        var phase = rows.getAttribute("data-phase");
        var phaseSelect = phase && row.querySelector("select[name$='-phase']");
        if (phaseSelect) phaseSelect.value = phase;
        filterCategory(rows);
        document.dispatchEvent(new CustomEvent("formset:added", { detail: { prefix: prefix, row: row } }));
      });
    });
  });
  window.addFormsetRow = function (prefix) {
    var box = document.querySelector('[data-formset="' + prefix + '"]');
    var button = box && box.querySelector("[data-formset-add]");
    if (!button) return null;
    button.click();
    var rows = box.querySelectorAll("[data-formset-rows] > *");
    return rows[rows.length - 1];
  };

  // Tooth picker: every <input data-teeth-picker="multi"> or <select data-teeth-picker="single">
  // gets a button that opens the tooth chart (templates/includes/teeth_picker.html).
  // Teeth missing on the patient's chart come from data-teeth-missing on the box or its form.
  var UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28];
  var LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38];
  var ALL_TEETH = UPPER.concat(LOWER);
  function chartOrder(teeth) {
    return teeth.filter(function (t, i) { return ALL_TEETH.indexOf(t) >= 0 && teeth.indexOf(t) === i; })
      .sort(function (a, b) { return ALL_TEETH.indexOf(a) - ALL_TEETH.indexOf(b); });
  }
  function parseTeeth(text) {
    var teeth = [];
    String(text || "").split(/[\s,،;؛+\/&]+/).forEach(function (token) {
      var range = token.match(/^(\d{2})[-–](\d{2})$/);
      if (range) {
        var start = parseInt(range[1], 10), end = parseInt(range[2], 10);
        var arch = UPPER.indexOf(start) >= 0 ? UPPER : LOWER;
        var i = arch.indexOf(start), j = arch.indexOf(end);
        if (i < 0 || j < 0) return;
        teeth = teeth.concat(arch.slice(Math.min(i, j), Math.max(i, j) + 1));
      } else if (/^\d{2}$/.test(token)) {
        teeth.push(parseInt(token, 10));
      }
    });
    return chartOrder(teeth);
  }
  var picker = document.getElementById("teeth-picker");
  var pickerState = null;
  function drawPicker() {
    picker.querySelectorAll("[data-tooth]").forEach(function (button) {
      var tooth = parseInt(button.getAttribute("data-tooth"), 10);
      button.classList.toggle("active", pickerState.chosen.indexOf(tooth) >= 0);
      button.classList.toggle("missing", pickerState.missing.indexOf(tooth) >= 0);
    });
    var chosen = picker.querySelector("[data-chosen]");
    if (chosen) chosen.textContent = pickerState.chosen.length ? chartOrder(pickerState.chosen).join(", ") : "—";
  }
  function openPicker(options) {
    if (!picker || !window.bootstrap) return;
    pickerState = {
      chosen: chartOrder(options.value || []), missing: options.missing || [],
      single: !!options.single, done: options.done
    };
    picker.querySelectorAll("[data-hint-multi], [data-title-multi]").forEach(function (el) { el.hidden = pickerState.single; });
    picker.querySelectorAll("[data-title-single]").forEach(function (el) { el.hidden = !pickerState.single; });
    drawPicker();
    window.bootstrap.Modal.getOrCreateInstance(picker).show();
  }
  function finishPicker() {
    var state = pickerState;
    window.bootstrap.Modal.getOrCreateInstance(picker).hide();
    if (state && state.done) state.done(chartOrder(state.chosen));
  }
  if (picker) {
    [["upper", UPPER], ["lower", LOWER]].forEach(function (jaw) {
      var row = picker.querySelector('[data-jaw="' + jaw[0] + '"]');
      jaw[1].forEach(function (tooth, i) {
        if (i === 8) {
          var midline = document.createElement("span");
          midline.className = "teeth-picker-midline";
          row.appendChild(midline);
        }
        var button = document.createElement("button");
        button.type = "button";
        button.className = "teeth-picker-tooth";
        button.setAttribute("data-tooth", tooth);
        button.textContent = tooth;
        row.appendChild(button);
      });
    });
    picker.addEventListener("click", function (event) {
      var toothButton = event.target.closest("[data-tooth]");
      var action = event.target.closest("[data-pick]");
      if (toothButton && pickerState) {
        var tooth = parseInt(toothButton.getAttribute("data-tooth"), 10);
        if (pickerState.single) { pickerState.chosen = [tooth]; finishPicker(); return; }
        var at = pickerState.chosen.indexOf(tooth);
        if (at >= 0) pickerState.chosen.splice(at, 1); else pickerState.chosen.push(tooth);
        drawPicker();
      } else if (action && pickerState) {
        var what = action.getAttribute("data-pick");
        if (what === "clear") pickerState.chosen = [];
        if (what === "missing") pickerState.chosen = chartOrder(pickerState.chosen.concat(pickerState.missing));
        if (what === "done") { finishPicker(); return; }
        drawPicker();
      }
    });
  }
  function missingFor(el) {
    var holder = el.closest("[data-teeth-missing]");
    return holder ? parseTeeth(holder.getAttribute("data-teeth-missing")) : [];
  }
  window.teethPicker = { open: openPicker, parse: parseTeeth, missingFor: missingFor };
  function setupTeethPicker(el) {
    if (el._teethPicker || !picker) return;
    el._teethPicker = true;
    var single = el.getAttribute("data-teeth-picker") === "single";
    var group = document.createElement("div");
    group.className = "input-group flex-nowrap";
    el.parentNode.insertBefore(group, el);
    group.appendChild(el);
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-outline-primary teeth-picker-open";
    button.title = picker.querySelector(single ? "[data-title-single]" : "[data-title-multi]").textContent;
    button.innerHTML = '<i class="bi bi-grid-3x3-gap"></i>';
    group.appendChild(button);
    button.addEventListener("click", function () {
      openPicker({
        value: parseTeeth(el.value), missing: missingFor(el), single: single,
        done: function (teeth) {
          el.value = single ? String(teeth[0] || "") : teeth.join(", ");
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    });
  }
  document.querySelectorAll("[data-teeth-picker]").forEach(setupTeethPicker);
  document.addEventListener("formset:added", function (event) {
    var row = event.detail && event.detail.row;
    if (row) row.querySelectorAll("[data-teeth-picker]").forEach(setupTeethPicker);
  });
  // Shade guide: under each <select data-shade> the tabs of the chosen guide (VITA classical or 3D-Master, from
  // the <select data-shade-guide> of the same form) and under <select data-stump> the stump tabs, in their colours
  // (from <script id="shade-guides">). Tapping a tab chooses it; the list shows only the chosen guide's shades.
  var guideData = document.getElementById("shade-guides");
  var guides = guideData ? JSON.parse(guideData.textContent) : null;
  function guideFor(form) {
    var select = form && form.querySelector("select[data-shade-guide]");
    return select ? select.value : "";
  }
  function drawTabs(select, tabs) {
    var box = select._shadeTabs;
    if (!box) {
      box = document.createElement("div");
      box.className = "shade-tabs";
      select.parentNode.insertBefore(box, select.nextSibling);
      select._shadeTabs = box;
    }
    box.innerHTML = "";
    tabs.forEach(function (tab) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "shade-tab" + (select.value === tab.name ? " is-chosen" : "");
      button.style.setProperty("--shade", tab.colour);
      button.textContent = tab.name;
      button.title = tab.name;
      button.addEventListener("click", function () {
        select.value = select.value === tab.name && !select.required ? "" : tab.name;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      box.appendChild(button);
    });
  }
  function setupShade(select) {
    var form = select.form;
    function refresh() {
      var guide = guideFor(form);
      var label = "";
      var guideSelect = form && form.querySelector("select[data-shade-guide]");
      if (guideSelect && guideSelect.value) label = guideSelect.options[guideSelect.selectedIndex].text;
      Array.prototype.forEach.call(select.querySelectorAll("optgroup"), function (group) {
        group.hidden = !!label && group.label !== label;
        group.disabled = group.hidden;
      });
      var chosen = select.options[select.selectedIndex];
      if (chosen && chosen.parentNode.disabled) select.value = "";
      if (guides) drawTabs(select, guides.guides[guide] || []);
    }
    select.addEventListener("change", function () {
      var guideSelect = form && form.querySelector("select[data-shade-guide]");
      if (guideSelect && !guideSelect.value && select.value) {  // choosing a shade first picks its guide
        var group = select.options[select.selectedIndex].parentNode;
        Array.prototype.forEach.call(guideSelect.options, function (o) { if (o.text === group.label) guideSelect.value = o.value; });
        form.querySelectorAll("select[data-shade]").forEach(function (other) { other._refreshShade && other._refreshShade(); });
      }
      refresh();
    });
    select._refreshShade = refresh;
    refresh();
  }
  document.querySelectorAll("select[data-shade]").forEach(setupShade);
  document.querySelectorAll("select[data-shade-guide]").forEach(function (guideSelect) {
    guideSelect.addEventListener("change", function () {
      (guideSelect.form || document).querySelectorAll("select[data-shade]").forEach(function (s) { s._refreshShade && s._refreshShade(); });
    });
  });
  if (guides) document.querySelectorAll("select[data-stump]").forEach(function (select) {
    drawTabs(select, guides.stump);
    select.addEventListener("change", function () { drawTabs(select, guides.stump); });
  });

  // Saving: a form sent is sent once. The button shows "Saving…" and a second tap does nothing, so a slow network
  // never makes two bills or two bookings. The page with the form leaves the trail (see Back) and the browser's own
  // back button, too, goes to the page before the form instead of showing the saved form again.
  var SAVING = document.body.getAttribute("data-saving-text") || "…";
  function release(form) {
    form.removeAttribute("data-submitting");
    form.querySelectorAll("button[data-saving]").forEach(function (button) {
      button.disabled = false;
      button.innerHTML = button._label;
      button.removeAttribute("data-saving");
    });
  }
  // For the browser's own back button: the form page's place in the history becomes the page before it (after a new
  // record, back shows the list it came from), or for an edit form (…/5/edit/ opened from …/5/) the page before
  // that one, as saving opens …/5/ again. Only for the main form of a page, not the small buttons of a page.
  function pageInsteadOfForm(form) {
    var fields = form.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea");
    if (form.hasAttribute("data-no-leave-warning") || fields.length < 2) return null;
    var trail = readTrail();
    if (trail.length < 2 || trail[trail.length - 1].url !== here) return null;
    var opener = trail[trail.length - 2], path = window.location.pathname;
    var editOf = /\/(edit|change)\/$/.test(path) && path.replace(/(edit|change)\/$/, "") === opener.url.split("?")[0];
    if (editOf && trail.length >= 3) return trail[trail.length - 3].url;
    return opener.url;
  }
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || (form.getAttribute("method") || "").toLowerCase() !== "post" ||
        form.target === "_blank") return;
    if (form.hasAttribute("data-submitting")) { event.preventDefault(); return; }
    var download = form.hasAttribute("data-no-progress") || DOWNLOADS.test(form.getAttribute("action") || "") ||
                   (event.submitter && DOWNLOADS.test(event.submitter.getAttribute("formaction") || ""));
    var button = event.submitter;
    if (!download) {
      form.setAttribute("data-submitting", "");
      try { sessionStorage.setItem("page-sent", here); } catch (e) {}
      var instead = pageInsteadOfForm(form);
      if (instead && window.history.replaceState) {
        // The addresses are fixed first: after replaceState the page's own address is another one.
        form.setAttribute("action", formAddress(form));
        if (button && button.hasAttribute("formaction")) button.setAttribute("formaction", button.formAction);
        window.history.replaceState(window.history.state, "", instead);
      }
      setTimeout(function () { release(form); }, 20000);  // e.g. no answer from the server: it can be sent again
    }
    if (button && button.tagName === "BUTTON" && !download) {
      setTimeout(function () {  // after the browser has taken the button's name and value
        button._label = button.innerHTML;
        button.setAttribute("data-saving", "");
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> ' + SAVING;
      }, 0);
    }
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) document.querySelectorAll("form[data-submitting]").forEach(release);
  });

  // A notice closed with its × stays closed in this tab (e.g. the easy-password notice); it comes back next login.
  document.querySelectorAll("[data-hide-for-now]").forEach(function (box) {
    var key = "hidden:" + box.getAttribute("data-hide-for-now");
    try { if (sessionStorage.getItem(key)) { box.remove(); return; } } catch (e) {}
    var button = box.querySelector("[data-hide-now]");
    if (button) button.addEventListener("click", function () {
      try { sessionStorage.setItem(key, "1"); } catch (e) {}
      box.remove();
    });
  });

  // Drafts: nothing typed is lost. When a main form is sent, what was typed is kept in this browser for a day. The
  // server marks a good save (the "saved" cookie of SavedMarkMiddleware): the draft is then dropped. If the network or
  // the server stopped, the next time the form is opened a bar offers to put the data back. Passwords, files and the
  // security token are never kept, and each person sees only their own drafts. A form opts out with data-no-draft.
  (function drafts() {
    var store;
    try { store = window.localStorage; store.setItem("draft-test", "1"); store.removeItem("draft-test"); } catch (e) { return; }
    var user = document.body.getAttribute("data-user");
    if (!user) return;
    var ALL = "draft:", PREFIX = ALL + user + ":", DAY = 24 * 60 * 60 * 1000, now = Date.now();  // each person's own
    var path = window.location.pathname + window.location.search;
    function mainForms() {
      return Array.prototype.filter.call(document.querySelectorAll("form"), function (form) {
        return (form.getAttribute("method") || "").toLowerCase() === "post" && !form.hasAttribute("data-no-leave-warning") &&
          !form.hasAttribute("data-no-draft") &&
          form.querySelectorAll("input:not([type=hidden]):not([type=password]), select, textarea").length >= 3;
      });
    }
    function keyOf(form, where) { return PREFIX + where + "#" + mainForms().indexOf(form); }
    function each(fn, prefix) {
      for (var i = store.length - 1; i >= 0; i--) {
        var key = store.key(i);
        if (key && key.indexOf(prefix || PREFIX) === 0) {
          var draft = null;
          try { draft = JSON.parse(store.getItem(key)); } catch (e) {}
          fn(key, draft);
        }
      }
    }
    function snapshot(form) {
      var fields = [];
      Array.prototype.forEach.call(form.elements, function (el) {
        var type = (el.type || "").toLowerCase();
        if (!el.name || el.disabled || el.name === "csrfmiddlewaretoken" ||
            ["password", "file", "submit", "button", "reset"].indexOf(type) >= 0) return;
        if (type === "checkbox" || type === "radio") fields.push({n: el.name, v: el.value, c: el.checked});
        else if (el.tagName === "SELECT" && el.multiple) {
          fields.push({n: el.name, m: Array.prototype.filter.call(el.options, function (o) { return o.selected; })
            .map(function (o) { return o.value; })});
        } else fields.push({n: el.name, v: el.value});
      });
      return fields;
    }
    function putBack(form, fields) {
      fields.forEach(function (field) {
        var els = form.querySelectorAll('[name="' + field.n.replace(/"/g, '\\"') + '"]');
        Array.prototype.forEach.call(els, function (el) {
          if (field.c !== undefined) { if (el.value === field.v) el.checked = field.c; }
          else if (field.m) Array.prototype.forEach.call(el.options, function (o) { o.selected = field.m.indexOf(o.value) >= 0; });
          else if (el.type !== "checkbox" && el.type !== "radio") el.value = field.v;
          el.dispatchEvent(new Event("change", { bubbles: true }));
        });
      });
    }
    // A good save: drop the drafts of the last minutes. Old drafts go after a day.
    var saved = /(?:^|; )saved=(\d+)/.exec(document.cookie);
    if (saved) {
      document.cookie = "saved=; Max-Age=0; path=/; SameSite=Lax";
      each(function (key, draft) { if (!draft || draft.t >= now - 10 * 60 * 1000) store.removeItem(key); });
    }
    each(function (key, draft) { if (!draft || now - draft.t > DAY) store.removeItem(key); }, ALL);
    var template = document.getElementById("draft-bar");
    mainForms().forEach(function (form) {
      var key = keyOf(form, path);
      if (form.querySelector(".errorlist, .is-invalid")) { store.removeItem(key); return; }  // the data is on the page
      var draft = null;
      try { draft = JSON.parse(store.getItem(key)); } catch (e) {}
      if (!draft || !template) return;
      var bar = template.content.firstElementChild.cloneNode(true);
      var when = new Date(draft.t);
      bar.querySelector("[data-draft-time]").textContent =
        ("0" + when.getHours()).slice(-2) + ":" + ("0" + when.getMinutes()).slice(-2);
      bar.querySelector("[data-draft-restore]").addEventListener("click", function () {
        putBack(form, draft.f);
        store.removeItem(key);
        bar.remove();
        form.dispatchEvent(new Event("input", { bubbles: true }));
      });
      bar.querySelector("[data-draft-discard]").addEventListener("click", function () { store.removeItem(key); bar.remove(); });
      form.parentNode.insertBefore(bar, form);
    });
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (mainForms().indexOf(form) < 0 || form.hasAttribute("data-no-progress")) return;
      try { store.setItem(keyOf(form, path), JSON.stringify({t: Date.now(), f: snapshot(form)})); } catch (e) {}
    }, true);
  })();
})();
