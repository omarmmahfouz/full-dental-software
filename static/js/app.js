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
      var height = size[1] || imageHeight + 2 * margin;
      var pdf = new window.jspdf.jsPDF({ unit: "mm", format: [width, height], orientation: width > height ? "l" : "p" });
      pdf.addImage(canvas.toDataURL("image/jpeg", 0.92), "JPEG", margin, margin, width - 2 * margin,
                   Math.min(imageHeight, height - 2 * margin));
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
})();
