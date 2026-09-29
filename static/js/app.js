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
      if (link.hasAttribute("data-back") && window.history.length > 1 && document.referrer &&
          document.referrer.indexOf(window.location.host) >= 0) window.history.back();
      else window.location.href = link.href;
    });
  }, true);
  window.addEventListener("beforeunload", function (event) {
    if (dirtyForm && !leaving && document.contains(dirtyForm)) { event.preventDefault(); event.returnValue = ""; }
  });

  // "Report a problem" (user menu): sent without leaving the page, so nothing typed is lost.
  var problemForm = document.querySelector("#report-problem form");
  if (problemForm) {
    problemForm.addEventListener("submit", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      var done = problemForm.querySelector("[data-problem-done]");
      var error = problemForm.querySelector("[data-problem-error]");
      var send = problemForm.querySelector("[data-problem-send]");
      done.hidden = error.hidden = true;
      send.disabled = true;
      fetch(problemForm.action, {
        method: "POST", body: new FormData(problemForm), credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.ok) {
          done.textContent = data.message;
          done.hidden = false;
          problemForm.querySelector("textarea").value = "";
          problemForm.querySelector("input[type=file]").value = "";
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
    var check = function () {
      fetch(pollUrl + "?since=" + lastSeen, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.ok ? r.json() : null; })
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

  // Cards and tiles appear one after the other, top to bottom (only those on the first screen).
  if (!reduceMotion) {
    var order = 0;
    document.querySelectorAll("main .quick-tile, main .visit-step, main .stat-card, main .card, main .my-week-day, main .now-col").forEach(function (el) {
      if (order >= 14 || el.closest(".reveal") || el.querySelector(".modal") || el.closest(".modal")) return;
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
    var start = null, duration = Math.min(900, 350 + target * 8);
    el.textContent = "0";
    var step = function (now) {
      if (start === null) start = now;
      var t = Math.min((now - start) / duration, 1);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) window.requestAnimationFrame(step);
    };
    window.requestAnimationFrame(step);
  });

  // The menu entry of the page being shown is marked (the longest address that matches wins).
  (function markActive() {
    var path = window.location.pathname, best = null, bestLength = 0;
    document.querySelectorAll(".app-navbar .navbar-nav > .nav-item").forEach(function (item) {
      item.querySelectorAll("a[href]").forEach(function (link) {
        var href = link.getAttribute("href");
        if (!href || href === "#" || href.charAt(0) !== "/") return;
        href = href.split("?")[0];
        var matches = href === "/" ? path === "/" : path.indexOf(href) === 0;
        if (matches && href.length > bestLength) { best = item; bestLength = href.length; }
      });
    });
    var top = best && best.querySelector(":scope > .nav-link");
    if (top) { top.classList.add("is-active"); top.setAttribute("aria-current", "page"); }
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
  function snapshot(target) {
    return loadScript(document.body.getAttribute("data-vendor-html2canvas")).then(function () {
      document.body.classList.add("is-snapshot");
      return window.html2canvas(target, { scale: 2, backgroundColor: "#ffffff", useCORS: true,
                                          onclone: function (doc) { doc.body.classList.add("is-snapshot"); } })
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
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-save-as]");
    if (!button) return;
    var target = document.querySelector(button.getAttribute("data-save-target"));
    if (!target) return;
    var kind = button.getAttribute("data-save-as"), name = button.getAttribute("data-save-name") || "document";
    button.disabled = true;
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
      // A frame from one corner to the other, kept to the chosen shape (4:3, 1:1) and inside the photo.
      var w = Math.abs(x1 - x0), h = Math.abs(y1 - y0);
      if (state.ratio) {
        var aspect = base.width / base.height;  // normalised height of a frame of normalised width w
        if (w / h * aspect > state.ratio) w = h * state.ratio / aspect; else h = w * aspect / state.ratio;
      }
      var x = x1 < x0 ? x0 - w : x0, y = y1 < y0 ? y0 - h : y0;
      return { x: Math.max(0, x), y: Math.max(0, y), w: Math.min(w, 1 - Math.max(0, x)), h: Math.min(h, 1 - Math.max(0, y)) };
    }
    stage.addEventListener("pointerdown", function (event) {
      if (!base) return;
      var p = point(event), c = state.crop;
      stage.setPointerCapture(event.pointerId);
      if (event.target.closest("[data-crop-corner]")) drag = { mode: "size", x0: c.x, y0: c.y };
      else if (event.target === frame) drag = { mode: "move", p: p, c: Object.assign({}, c) };
      else drag = { mode: "draw", x0: p.x, y0: p.y };
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
      stage.addEventListener(name, function () { drag = null; });
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
    frame.innerHTML = '<span class="photo-crop-corner" data-crop-corner></span>';
  });

  // ID card photos taken with the tablet (the patient form, the documents): check the photo is good (sharp, light,
  // near enough), cut the card out of the background, and read the national ID number from it. The reading is
  // done here on the tablet (static/vendor/tesseract), without internet; the secretary checks the number.
  var idTexts = document.querySelector("[data-id-check-texts]");
  var GOVERNORATES = ["01", "02", "03", "04", "11", "12", "13", "14", "15", "16", "17", "18", "19", "21", "22", "23",
                      "24", "25", "26", "27", "28", "29", "31", "32", "33", "34", "35", "88"];
  function idText(name) { return idTexts.getAttribute("data-" + name) || ""; }
  function scaledCanvas(source, maxSide) {
    var w = source.naturalWidth || source.width, h = source.naturalHeight || source.height;
    var scale = Math.min(1, maxSide / Math.max(w, h)), canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale)); canvas.height = Math.max(1, Math.round(h * scale));
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
  }
  function turned(source, turn) {
    var canvas = document.createElement("canvas"), side = turn % 180 !== 0;
    canvas.width = side ? source.height : source.width; canvas.height = side ? source.width : source.height;
    var ctx = canvas.getContext("2d");
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(turn * Math.PI / 180);
    ctx.drawImage(source, -source.width / 2, -source.height / 2);
    return canvas;
  }
  function greys(canvas) {
    var small = scaledCanvas(canvas, 500), px = small.getContext("2d").getImageData(0, 0, small.width, small.height).data;
    var out = new Float32Array(small.width * small.height);
    for (var i = 0, j = 0; i < px.length; i += 4, j++) out[j] = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    return { g: out, w: small.width, h: small.height, rgba: px };
  }
  function photoQuality(card, photo) {
    // Light, glare and sharpness of the card; sharpness is the edges (Laplacian) against the contrast.
    var q = greys(card), g = q.g, w = q.w, h = q.h, n = g.length, sum = 0, glare = 0;
    for (var i = 0; i < n; i++) { sum += g[i]; if (g[i] > 250) glare++; }
    var mean = sum / n, varG = 0, lapSum = 0, lapSq = 0, count = 0;
    for (i = 0; i < n; i++) varG += (g[i] - mean) * (g[i] - mean);
    varG /= n;
    for (var y = 1; y < h - 1; y++) for (var x = 1; x < w - 1; x++) {
      var k = y * w + x, lap = 4 * g[k] - g[k - 1] - g[k + 1] - g[k - w] - g[k + w];
      lapSum += lap; lapSq += lap * lap; count++;
    }
    var lapVar = lapSq / count - (lapSum / count) * (lapSum / count);
    var sharp = varG ? lapVar / varG * 100 : 0, checks = [];
    var shortSide = Math.min(photo.width, photo.height);
    if (mean < 60) checks.push(["bad", idText("dark")]);
    else if (mean > 215) checks.push(["bad", idText("bright")]);
    if (glare / n > 0.06) checks.push(["warn", idText("glare")]);
    if (sharp < 8) checks.push(["bad", idText("blurry")]);
    else if (sharp < 20) checks.push(["warn", idText("soft")]);
    if (shortSide < 700 || Math.max(card.width, card.height) < 700) checks.push(["warn", idText("small")]);
    return checks;
  }
  function findCard(photo) {
    // Like apps/patients/idcard.py: the card is what differs from the colour around the edges of the photo.
    var q = greys(photo), w = q.w, h = q.h, px = q.rgba, edge = [[], [], []];
    function take(x, y) { var k = (y * w + x) * 4; edge[0].push(px[k]); edge[1].push(px[k + 1]); edge[2].push(px[k + 2]); }
    for (var x = 0; x < w; x += 3) { take(x, 0); take(x, h - 1); }
    for (var y = 0; y < h; y += 3) { take(0, y); take(w - 1, y); }
    var bg = edge.map(function (band) { band.sort(function (a, b) { return a - b; }); return band[band.length >> 1]; });
    var rows = new Uint16Array(h), cols = new Uint16Array(w);
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      var k = (y * w + x) * 4;
      var d = 0.299 * Math.abs(px[k] - bg[0]) + 0.587 * Math.abs(px[k + 1] - bg[1]) + 0.114 * Math.abs(px[k + 2] - bg[2]);
      if (d > 35) { rows[y]++; cols[x]++; }
    }
    function span(list, size, length) {
      var first = -1, last = -1;
      for (var i = 0; i < length; i++) if (list[i] > size * 0.08) { if (first < 0) first = i; last = i; }
      return [first, last];
    }
    var ys = span(rows, w, h), xs = span(cols, h, w);
    if (ys[0] < 0 || xs[0] < 0) return null;
    var bw = xs[1] - xs[0] + 1, bh = ys[1] - ys[0] + 1, area = bw * bh / (w * h);
    var ratio = Math.max(bw, bh) / Math.max(1, Math.min(bw, bh));
    if (area < 0.15 || area > 0.92 || ratio < 1.3 || ratio > 1.9) return null;
    var scale = photo.width / w, margin = 0.01 * Math.max(photo.width, photo.height);
    var left = Math.max(0, xs[0] * scale - margin), top = Math.max(0, ys[0] * scale - margin);
    return { x: left, y: top, w: Math.min(photo.width - left, bw * scale + 2 * margin),
             h: Math.min(photo.height - top, bh * scale + 2 * margin) };
  }
  function validNationalId(n) {
    if (!/^[23]\d{13}$/.test(n)) return false;
    var year = (n[0] === "2" ? 1900 : 2000) + parseInt(n.substr(1, 2), 10);
    var month = parseInt(n.substr(3, 2), 10), day = parseInt(n.substr(5, 2), 10);
    var born = new Date(year, month - 1, day);
    return month >= 1 && month <= 12 && born.getDate() === day && born <= new Date() &&
      GOVERNORATES.indexOf(n.substr(7, 2)) >= 0;
  }
  function nationalIdIn(text) {
    var latin = text.replace(/[٠-٩]/g, function (d) { return String(d.charCodeAt(0) - 0x0660); })
                    .replace(/[۰-۹]/g, function (d) { return String(d.charCodeAt(0) - 0x06F0); })
                    .replace(/(\d)[ .\-]+(?=\d)/g, "$1");
    var runs = latin.match(/\d{14,}/g) || [];
    for (var r = 0; r < runs.length; r++) {
      for (var i = 0; i + 14 <= runs[r].length; i++) {
        if (validNationalId(runs[r].substr(i, 14))) return runs[r].substr(i, 14);
      }
    }
    return "";
  }
  // Reading the national ID number: the 14 Arabic digits (٠١٢٣٤٥٦٧٨٩) printed at the bottom of the card. Each mark
  // on a line of the card is cut out and compared with the ten digits drawn in a few fonts; the number is kept only
  // when it is a valid national ID (a real date of birth, a governorate), so a wrong reading is not written.
  var DIGITS = "٠١٢٣٤٥٦٧٨٩", GRID_W = 20, GRID_H = 30, digitModels = null;
  function inkOf(canvas) {
    var ctx = canvas.getContext("2d"), px = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    var n = canvas.width * canvas.height, grey = new Uint8Array(n), hist = new Uint32Array(256);
    for (var i = 0, j = 0; j < n; i += 4, j++) {
      grey[j] = Math.round(0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]); hist[grey[j]]++;
    }
    // Otsu: the grey level that best splits the ink from the card.
    var total = 0, sumB = 0, wB = 0, best = 0, threshold = 128;
    for (i = 0; i < 256; i++) total += i * hist[i];
    for (i = 0; i < 256; i++) {
      wB += hist[i]; if (!wB) continue;
      var wF = n - wB; if (!wF) break;
      sumB += i * hist[i];
      var between = wB * wF * Math.pow(sumB / wB - (total - sumB) / wF, 2);
      if (between > best) { best = between; threshold = i; }
    }
    var ink = new Uint8Array(n);
    for (j = 0; j < n; j++) ink[j] = grey[j] <= threshold ? 1 : 0;
    return { ink: ink, w: canvas.width, h: canvas.height };
  }
  function features(bits, box, lineTop, lineHeight) {
    // The mark shrunk into a small grid (keeping its shape), with its size and place on the line.
    var grid = new Float32Array(GRID_W * GRID_H), bw = box.r - box.l + 1, bh = box.b - box.t + 1;
    var scale = Math.max(bw / GRID_W, bh / GRID_H), offX = (GRID_W - bw / scale) / 2, offY = (GRID_H - bh / scale) / 2;
    var counts = new Float32Array(GRID_W * GRID_H);
    for (var y = box.t; y <= box.b; y++) for (var x = box.l; x <= box.r; x++) {
      var gx = Math.min(GRID_W - 1, Math.floor((x - box.l) / scale + offX)), gy = Math.min(GRID_H - 1, Math.floor((y - box.t) / scale + offY));
      counts[gy * GRID_W + gx]++; grid[gy * GRID_W + gx] += bits.ink[y * bits.w + x];
    }
    for (var k = 0; k < grid.length; k++) grid[k] = counts[k] ? grid[k] / counts[k] : 0;
    // The teeth on top (٢ has one, ٣ two): the most separate pieces of ink met across the top third.
    var teeth = 0;
    for (y = box.t; y <= box.t + Math.round(bh * 0.35); y++) {
      var runs = 0, was = 0;
      for (x = box.l; x <= box.r; x++) { var on = bits.ink[y * bits.w + x]; if (on && !was) runs++; was = on; }
      teeth = Math.max(teeth, runs);
    }
    return { grid: grid, aspect: bw / bh, height: bh / lineHeight, middle: ((box.t + box.b) / 2 - lineTop) / lineHeight,
             teeth: Math.min(teeth, 4) };
  }
  function boxesOf(bits, top, bottom) {
    // The marks of one line, left to right: runs of columns with ink.
    var boxes = [], inRun = false, start = 0;
    function close(end) {
      var t = bottom, b = top, count = 0;
      for (var y = top; y <= bottom; y++) for (var x = start; x <= end; x++) if (bits.ink[y * bits.w + x]) {
        count++; if (y < t) t = y; if (y > b) b = y;
      }
      if (count > 2) boxes.push({ l: start, r: end, t: t, b: b });
    }
    for (var x = 0; x < bits.w; x++) {
      var any = false;
      for (var y = top; y <= bottom && !any; y++) any = bits.ink[y * bits.w + x] === 1;
      if (any && !inRun) { inRun = true; start = x; }
      if (!any && inRun) { inRun = false; close(x - 1); }
    }
    if (inRun) close(bits.w - 1);
    // Two digits that touch (a blurred photo) make one mark wider than it is tall (a digit is taller than wide):
    // cut it where the ink is thinnest.
    var split = [];
    boxes.forEach(function (box) {
      var width = box.r - box.l + 1;
      if (boxes.length < 6 || width < (bottom - top + 1) * 1.15) { split.push(box); return; }
      var best = -1, least = Infinity;
      for (var x = box.l + Math.round(width * 0.3); x <= box.l + Math.round(width * 0.7); x++) {
        var ink = 0;
        for (var y = box.t; y <= box.b; y++) ink += bits.ink[y * bits.w + x];
        if (ink < least) { least = ink; best = x; }
      }
      [[box.l, best - 1], [best + 1, box.r]].forEach(function (cols) {
        var t = box.b, b = box.t;
        for (var y = box.t; y <= box.b; y++) for (var x = cols[0]; x <= cols[1]; x++) if (bits.ink[y * bits.w + x]) {
          if (y < t) t = y; if (y > b) b = y;
        }
        if (b >= t) split.push({ l: cols[0], r: cols[1], t: t, b: b });
      });
    });
    return split;
  }
  function buildDigitModels() {
    var fonts = ["700 60px Cairo", "400 60px Cairo", "bold 60px serif", "60px serif", "bold 60px sans-serif",
                 "60px sans-serif", "bold 60px monospace", "bold 60px Tahoma", "bold 60px Arial"];
    var models = [];
    fonts.forEach(function (font) {
      var canvas = document.createElement("canvas"); canvas.width = 900; canvas.height = 110;
      var ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#000"; ctx.font = font; ctx.textBaseline = "alphabetic";
      for (var d = 0; d < 10; d++) ctx.fillText(DIGITS[d], 20 + d * 85, 80);
      var bits = inkOf(canvas), boxes = boxesOf(bits, 0, canvas.height - 1);
      if (boxes.length !== 10) return;  // this font does not draw the ten digits apart
      var top = Math.min.apply(null, boxes.map(function (b) { return b.t; }));
      var bottom = Math.max.apply(null, boxes.map(function (b) { return b.b; }));
      boxes.forEach(function (box, d) {
        var f = features(bits, box, top, bottom - top + 1); f.digit = d; models.push(f);
      });
    });
    return models;
  }
  function classify(f) {
    var ranked = digitModels.map(function (m) {
      var d = 0;
      for (var k = 0; k < f.grid.length; k++) d += (f.grid[k] - m.grid[k]) * (f.grid[k] - m.grid[k]);
      d = d / f.grid.length + 0.6 * Math.pow(f.height - m.height, 2) + 0.25 * Math.pow(Math.log(f.aspect / m.aspect), 2) +
          0.3 * Math.pow(f.middle - m.middle, 2) + 0.04 * Math.abs(f.teeth - m.teeth);
      return { digit: m.digit, d: d };
    }).sort(function (a, b) { return a.d - b.d; });
    var second = ranked.find(function (r) { return r.digit !== ranked[0].digit; });
    return [ranked[0].digit, second ? second.digit : ranked[0].digit];
  }
  function numberOnLines(bits) {
    // Lines of the card (rows with ink), then every run of 14 marks that reads as a valid national ID.
    var rows = new Uint32Array(bits.h), lines = [], y, x;
    for (y = 0; y < bits.h; y++) for (x = 0; x < bits.w; x++) rows[y] += bits.ink[y * bits.w + x];
    var inLine = false, start = 0;
    for (y = 0; y <= bits.h; y++) {
      var has = y < bits.h && rows[y] > bits.w * 0.004;
      if (has && !inLine) { inLine = true; start = y; }
      if (!has && inLine) { inLine = false; if (y - start >= bits.h * 0.018) lines.push([start, y - 1]); }
    }
    for (var l = lines.length - 1; l >= 0; l--) {  // the number is near the bottom
      var boxes = boxesOf(bits, lines[l][0], lines[l][1]);
      if (boxes.length < 14) continue;
      var height = lines[l][1] - lines[l][0] + 1;
      var reads = boxes.map(function (box) { return classify(features(bits, box, lines[l][0], height)); });
      for (var i = 0; i + 14 <= reads.length; i++) {
        var first = reads.slice(i, i + 14).map(function (r) { return DIGITS[r[0]]; }).join("");
        var found = nationalIdIn(first);
        if (found) return found;
        for (var k = 0; k < 14; k++) {  // one digit read wrong: try its second choice
          var fixed = first.slice(0, k) + DIGITS[reads[i + k][1]] + first.slice(k + 1);
          found = nationalIdIn(fixed);
          if (found) return found;
        }
      }
    }
    return "";
  }
  function part(canvas, left, top, right, bottom) {
    // A part of the card, as fractions of its width and height.
    var out = document.createElement("canvas"), x = Math.round(canvas.width * left), y = Math.round(canvas.height * top);
    out.width = Math.round(canvas.width * (right - left)); out.height = Math.round(canvas.height * (bottom - top));
    out.getContext("2d").drawImage(canvas, x, y, out.width, out.height, 0, 0, out.width, out.height);
    return out;
  }
  function readCard(card) {
    var ready = document.fonts && document.fonts.load ? document.fonts.load("700 60px Cairo", DIGITS) : Promise.resolve();
    return ready.catch(function () {}).then(function () {
      if (!digitModels) digitModels = buildDigitModels();
      var big = scaledCanvas(card, 2000);
      if (big.width < 1800) {
        var up = document.createElement("canvas");
        up.width = 1800; up.height = Math.round(big.height * 1800 / big.width);
        up.getContext("2d").drawImage(big, 0, 0, up.width, up.height);
        big = up;
      }
      // The whole card, then its right part only (the photo on the left can reach the number's line), then the same
      // upside down.
      var upside = turned(big, 180), tries = [];
      [big, upside].forEach(function (side) {  // without the edges of the photo around the card
        [0.03, 0.3, 0.38, 0.45].forEach(function (left) { tries.push(part(side, left, 0.03, 0.97, 0.97)); });
      });
      for (var i = 0; i < tries.length; i++) {
        var found = numberOnLines(inkOf(tries[i]));
        if (found) return found;
      }
      return "";
    });
  }
  function setupIdCheck(input) {
    var panel = document.createElement("div"), state = null;
    panel.className = "id-check card mt-2"; panel.hidden = true;
    input.insertAdjacentElement("afterend", panel);
    var form = input.form, reads = input.getAttribute("data-id-card") === "front";
    function nidField() { return form && form.querySelector("input[name='national_id']"); }
    function idTypeIsCard() {
      var type = form && form.querySelector("[name='id_type']");
      return !type || !type.value || type.value === "nid";
    }
    function kindIsCard() {
      var kind = form && form.querySelector("select[name='kind']");
      return !kind || ["id_front", "id_back", "passport"].indexOf(kind.value) >= 0;
    }
    function button(label, icon, action) {
      return '<button type="button" class="btn btn-sm btn-outline-secondary" data-id-action="' + action + '"><i class="bi ' +
        icon + '"></i> ' + label + "</button>";
    }
    function show() {
      var photo = turned(state.photo, state.turn);
      var box = state.whole ? null : findCard(photo);
      var card = photo;
      if (box) {
        card = document.createElement("canvas");
        card.width = Math.round(box.w); card.height = Math.round(box.h);
        card.getContext("2d").drawImage(photo, box.x, box.y, box.w, box.h, 0, 0, card.width, card.height);
      }
      var checks = photoQuality(card, photo);
      if (!state.whole && !box) checks.push(["warn", idText("no-card")]);
      if (card.height > card.width) checks.push(["warn", idText("upright")]);
      var good = !checks.some(function (c) { return c[0] === "bad"; });
      panel.innerHTML = '<div class="card-body d-flex flex-wrap gap-3 align-items-start"><img class="id-check-preview" alt="">' +
        '<div class="flex-grow-1"><div class="fw-semibold mb-1">' + (good ? '<i class="bi bi-check-circle-fill text-success"></i> ' + idText(checks.length ? "fair" : "good")
        : '<i class="bi bi-x-octagon-fill text-danger"></i> ' + idText("retake")) + '</div><ul class="id-check-list"></ul>' +
        '<div class="id-check-read small mb-2"></div><div class="d-flex flex-wrap gap-2">' +
        button(idText("turn-left"), "bi-arrow-counterclockwise", "left") + button(idText("turn-right"), "bi-arrow-clockwise", "right") +
        (box || state.whole ? button(state.whole ? idText("card-only") : idText("whole"), "bi-bounding-box", "whole") : "") +
        button(idText("again"), "bi-camera", "again") + "</div></div></div>";
      panel.querySelector(".id-check-preview").src = card.toDataURL("image/jpeg", 0.8);
      var list = panel.querySelector(".id-check-list");
      checks.forEach(function (c) {
        var li = document.createElement("li");
        li.className = "is-" + c[0];
        li.textContent = c[1];
        list.appendChild(li);
      });
      if (box) { var li = document.createElement("li"); li.className = "is-ok"; li.textContent = idText("card-found"); list.appendChild(li); }
      panel.hidden = false;
      // What is uploaded: the card cut out (smaller, quicker on the Wi-Fi), as a JPEG.
      var sized = scaledCanvas(card, 1600);
      sized.toBlob(function (blob) {
        if (!blob || typeof DataTransfer === "undefined") return;
        try {
          var transfer = new DataTransfer();
          transfer.items.add(new File([blob], state.name.replace(/\.[^.]+$/, "") + "-card.jpg", { type: "image/jpeg" }));
          input.files = transfer.files;
        } catch (error) { /* this browser keeps the photo as taken; the server cuts the card out */ }
      }, "image/jpeg", 0.9);
      if (reads && good && idTypeIsCard() && nidField()) read(sized);
    }
    function read(card) {
      var place = panel.querySelector(".id-check-read"), field = nidField();
      place.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + idText("reading");
      var token = state.token = {};
      readCard(card).then(function (number) {
        if (token !== state.token) return;
        if (!number) { place.textContent = idText("read-none"); return; }
        var current = (field.value || "").replace(/\s/g, "");
        if (!current) {
          field.value = number;
          field.dispatchEvent(new Event("input", { bubbles: true }));
          field.dispatchEvent(new Event("change", { bubbles: true }));
          field.classList.add("is-filled-from-card");
          place.innerHTML = '<i class="bi bi-magic text-success"></i> ' + idText("filled").replace("%s", '<b class="ltr">' + number + "</b>");
        } else if (current !== number) {
          place.innerHTML = '<i class="bi bi-exclamation-triangle text-warning"></i> ' +
            idText("differs").replace("%s", '<b class="ltr">' + number + "</b>") +
            ' <button type="button" class="btn btn-sm btn-link p-0 align-baseline" data-id-action="use">' + idText("use") + "</button>";
          place.querySelector("[data-id-action='use']").addEventListener("click", function () {
            field.value = number; field.dispatchEvent(new Event("change", { bubbles: true }));
            place.innerHTML = '<i class="bi bi-check2 text-success"></i> ' + idText("filled").replace("%s", '<b class="ltr">' + number + "</b>");
          });
        } else {
          place.innerHTML = '<i class="bi bi-check2-all text-success"></i> ' + idText("same");
        }
      }).catch(function () { if (token === state.token) place.textContent = idText("read-none"); });
    }
    panel.addEventListener("click", function (event) {
      var action = event.target.closest("[data-id-action]");
      if (!action || !state) return;
      var what = action.getAttribute("data-id-action");
      if (what === "left") { state.turn = (state.turn + 270) % 360; show(); }
      else if (what === "right") { state.turn = (state.turn + 90) % 360; show(); }
      else if (what === "whole") { state.whole = !state.whole; show(); }
      else if (what === "again") { input.value = ""; panel.hidden = true; state = null; input.click(); }
    });
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file || !/^image\//.test(file.type) || /-card\.jpg$/.test(file.name) || !kindIsCard()) {
        if (!file || !/-card\.jpg$/.test(file.name)) panel.hidden = true;
        return;
      }
      var image = new Image(), url = URL.createObjectURL(file);
      image.onload = function () {
        state = { photo: scaledCanvas(image, 2400), turn: 0, whole: false, name: file.name };
        URL.revokeObjectURL(url);
        show();
      };
      image.src = url;
    });
  }
  if (idTexts) document.querySelectorAll("input[type=file][data-id-card]").forEach(setupIdCheck);

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
})();
