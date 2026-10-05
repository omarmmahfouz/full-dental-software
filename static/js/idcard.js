// ID cards (the patient form, the documents of a file): take the card with the camera inside the page (a frame shows
// where to hold it) or choose a photo; the photo is checked (sharp, light, near enough), the card is cut out of the
// background, and its details are read here on the PC or tablet, without internet: the national ID number (the
// digits are compared with drawn digits), then the name, the address and the city on the front and the occupation
// and the marital status on the back (static/vendor/tesseract, Arabic). What is read fills the empty boxes of the
// form, marked in yellow: the secretary checks it and can change any of it. Loaded by includes/id_check_texts.html.
(function () {
  "use strict";
  var idTexts = document.querySelector("[data-id-check-texts]");
  if (!idTexts) return;
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
    else if (mean > 238) checks.push(["bad", idText("bright")]);
    else if (mean > 222) checks.push(["warn", idText("bright")]);
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

  // ---- A tighter cut: the card's straight edges. Near each side, the first line (from the outside) where most of
  // the line changes brightness at once is the card's edge (a line of text inside changes only in places).
  function tighten(card) {
    var q = greys(card), g = q.g, w = q.w, h = q.h, T = 22;
    function rowCover(y) {
      var on = 0, from = Math.round(w * 0.1), to = Math.round(w * 0.9);
      for (var x = from; x < to; x++) if (Math.abs(g[(y + 1) * w + x] - g[(y - 1) * w + x]) > T) on++;
      return on / (to - from);
    }
    function colCover(x) {
      var on = 0, from = Math.round(h * 0.1), to = Math.round(h * 0.9);
      for (var y = from; y < to; y++) if (Math.abs(g[y * w + x + 1] - g[y * w + x - 1]) > T) on++;
      return on / (to - from);
    }
    function edge(cover, size, fromEnd) {
      var band = Math.round(size * 0.16);
      for (var i = 1; i < band; i++) {
        var at = fromEnd ? size - 1 - i : i;
        if (at > 0 && at < size - 1 && cover(at) >= 0.45) return at;
      }
      return fromEnd ? size - 1 : 0;
    }
    var top = edge(rowCover, h, false), bottom = edge(rowCover, h, true);
    var left = edge(colCover, w, false), right = edge(colCover, w, true);
    var bw = right - left, bh = bottom - top, ratio = Math.max(bw, bh) / Math.max(1, Math.min(bw, bh));
    if (bw < w * 0.6 || bh < h * 0.6 || ratio < 1.35 || ratio > 1.85) return card;  // not sure: keep it as it is
    if (left === 0 && top === 0 && right === w - 1 && bottom === h - 1) return card;
    var scale = card.width / w, out = document.createElement("canvas");
    out.width = Math.round(bw * scale); out.height = Math.round(bh * scale);
    out.getContext("2d").drawImage(card, left * scale, top * scale, out.width, out.height, 0, 0, out.width, out.height);
    return out;
  }

  // ---- The camera inside the page: the live picture with a frame the size of an ID card; the photo keeps what is
  // inside the frame. Browsers allow the camera on https:// pages and on the server PC itself (localhost) only;
  // elsewhere the box opens the tablet's own camera, as before.
  var canCamera = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && window.isSecureContext !== false;
  // The camera used last on this PC or tablet is used again; "Switch camera" goes through every camera it has
  // (the back and the front of a tablet, a USB document camera on a PC; round 15).
  var CAMERA_KEY = "id-camera";
  function savedCamera() { try { return localStorage.getItem(CAMERA_KEY) || ""; } catch (e) { return ""; } }
  function openCamera(onTaken) {
    var box = document.createElement("div"), stream = null, facing = "environment", cameraId = savedCamera(), cameras = [];
    box.className = "id-camera";
    box.setAttribute("role", "dialog");
    box.innerHTML = '<video playsinline muted autoplay></video><div class="id-camera-frame"><span></span></div>' +
      '<div class="id-camera-tip"></div><div class="id-camera-bar">' +
      '<button type="button" class="btn btn-light" data-cam="cancel"><i class="bi bi-x-lg"></i> <span></span></button>' +
      '<button type="button" class="id-camera-shutter" data-cam="take"></button>' +
      '<button type="button" class="btn btn-light" data-cam="switch"><i class="bi bi-arrow-repeat"></i> <span></span></button></div>';
    box.querySelector(".id-camera-tip").textContent = idText("camera-tip");
    box.querySelector("[data-cam='cancel'] span").textContent = idText("cancel");
    box.querySelector("[data-cam='switch'] span").textContent = idText("switch-camera");
    box.querySelector("[data-cam='take']").setAttribute("aria-label", idText("take"));
    document.body.appendChild(box);
    document.body.classList.add("id-camera-open");
    var video = box.querySelector("video");
    function stop() { if (stream) stream.getTracks().forEach(function (track) { track.stop(); }); stream = null; }
    function close() {
      stop(); box.remove(); document.body.classList.remove("id-camera-open");
      document.removeEventListener("keydown", onKey);
    }
    function onKey(event) { if (event.key === "Escape") close(); }
    function start() {
      stop();
      var wanted = { width: { ideal: 1920 }, height: { ideal: 1080 } };
      if (cameraId) wanted.deviceId = { exact: cameraId }; else wanted.facingMode = { ideal: facing };
      navigator.mediaDevices.getUserMedia({ audio: false, video: wanted }).then(function (got) {
        stream = got; video.srcObject = got;
        var playing = video.play(); if (playing && playing.catch) playing.catch(function () {});
        var settings = got.getVideoTracks()[0] && got.getVideoTracks()[0].getSettings ? got.getVideoTracks()[0].getSettings() : {};
        if (settings.deviceId) cameraId = settings.deviceId;
        if (navigator.mediaDevices.enumerateDevices) {
          navigator.mediaDevices.enumerateDevices().then(function (all) {
            cameras = all.filter(function (device) { return device.kind === "videoinput" && device.deviceId; });
          });
        }
      }).catch(function () {
        if (cameraId) { cameraId = ""; start(); return; }  // the camera used last is not there any more
        close(); window.alert(idText("camera-error"));
      });
    }
    function nextCamera() {
      if (cameras.length > 1) {
        var at = cameras.findIndex(function (device) { return device.deviceId === cameraId; });
        cameraId = cameras[(at + 1) % cameras.length].deviceId;
        try { localStorage.setItem(CAMERA_KEY, cameraId); } catch (e) {}
      } else {
        facing = facing === "environment" ? "user" : "environment"; cameraId = "";
      }
      start();
    }
    function grab() {
      // The frame on the screen, in the pixels of the camera (the picture fills the screen: object-fit cover), and a
      // little around it: the card's own edges cut it again (tighten).
      var vw = video.videoWidth, vh = video.videoHeight;
      if (!vw || !vh) return null;
      var screen = video.getBoundingClientRect(), frame = box.querySelector(".id-camera-frame span").getBoundingClientRect();
      var scale = Math.max(screen.width / vw, screen.height / vh);
      var offX = (screen.width - vw * scale) / 2, offY = (screen.height - vh * scale) / 2;
      var fx = (frame.left - screen.left - offX) / scale, fy = (frame.top - screen.top - offY) / scale;
      var fw = frame.width / scale, fh = frame.height / scale, mx = fw * 0.05, my = fh * 0.05;
      var x = Math.max(0, fx - mx), y = Math.max(0, fy - my);
      var w = Math.min(vw - x, fw + 2 * mx), h = Math.min(vh - y, fh + 2 * my), canvas = document.createElement("canvas");
      canvas.width = Math.round(w); canvas.height = Math.round(h);
      canvas.getContext("2d").drawImage(video, x, y, w, h, 0, 0, canvas.width, canvas.height);
      return canvas;
    }
    box.addEventListener("click", function (event) {
      var button = event.target.closest("[data-cam]");
      if (!button) return;
      var what = button.getAttribute("data-cam");
      if (what === "cancel") close();
      else if (what === "switch") nextCamera();
      else if (what === "take") {
        var shot = grab();
        if (!shot) return;
        box.classList.add("is-taken");
        setTimeout(function () { close(); onTaken(shot); }, 120);
      }
    });
    document.addEventListener("keydown", onKey);
    start();
  }

  // ---- Reading the words of the card (Arabic): tesseract, loaded only when a card is read.
  var ocrBase = idTexts.getAttribute("data-ocr-base") || "", ocrWorker = null;
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (window.Tesseract) { resolve(); return; }
      var script = document.createElement("script");
      script.src = src; script.onload = function () { resolve(); }; script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  function worker() {
    if (!ocrBase) return Promise.reject(new Error("no reader"));
    if (!ocrWorker) {
      var base = new URL(ocrBase, window.location.href).href;
      ocrWorker = loadScript(base + "tesseract.min.js").then(function () {
        return window.Tesseract.createWorker("ara", 1, {
          workerPath: base + "worker.min.js", corePath: base + "core/", langPath: base + "lang",
          workerBlobURL: false, cacheMethod: "none", gzip: true, logger: function () {}
        });
      });
      ocrWorker.catch(function () { ocrWorker = null; });
    }
    return ocrWorker;
  }
  function plain(text) {
    // Arabic without the spelling differences (أ/إ/آ/ا, ة/ه, ى/ي) and the marks, one space between words.
    return (text || "").replace(/[ً-ْـ]/g, "").replace(/[أإآ]/g, "ا").replace(/ة/g, "ه")
      .replace(/ى/g, "ي").replace(/\s+/g, " ").trim();
  }
  function lettersOnly(line) { return line.replace(/[^ء-ي\s]/g, " ").replace(/\s+/g, " ").trim(); }
  function digitCount(line) { return (line.match(/[0-9٠-٩۰-۹]/g) || []).length; }
  var HEADER = /جمهوري|مصر العربي|بطاق|تحقيق|الشخصي/;
  function readFront(text) {
    // The front: the first name, then the rest of the name, then the address (one or two lines), then the number.
    var lines = text.split("\n").map(function (line) { return line.replace(/[|_\[\]{}<>~"'`‎‏]/g, " ").trim(); })
      .filter(function (line) { return lettersOnly(line).length >= 2 && !HEADER.test(line); });
    var name = [], address = [];
    for (var i = 0; i < lines.length; i++) {
      if (digitCount(lines[i]) >= 10) break;  // the number's line: the end of the details
      if (name.length < 2 && !digitCount(lines[i]) && address.length === 0) name.push(lettersOnly(lines[i]));
      else if (address.length < 2) address.push(lines[i].replace(/\s+/g, " "));
    }
    var full = name.join(" ").split(" ").filter(function (word) { return word.length > 1 || word === "و"; }).join(" ");
    return { name: full.split(" ").length >= 3 ? full : "", address: address.join(" - "), number: nationalIdIn(text) };
  }
  // The marital status words, as written on the back (a word read with a letter or two wrong still counts).
  var MARITAL = { married: ["متزوج", "متزوجه"], single: ["اعزب", "عزباء", "انسه"], divorced: ["مطلق", "مطلقه"],
                  widowed: ["ارمل", "ارمله"] };
  var NOT_JOB = /ذكر|انثي|مسلم|مسيح|متزوج|اعزب|عزباء|مطلق|ارمل|ساري|البطاق|سجل|مدني|الزوج|جمهوري|الديان|النوع/;
  function distance(a, b) {
    var row = [], i, j;
    for (j = 0; j <= b.length; j++) row[j] = j;
    for (i = 1; i <= a.length; i++) {
      var last = row[0]; row[0] = i;
      for (j = 1; j <= b.length; j++) {
        var keep = row[j];
        row[j] = Math.min(row[j] + 1, row[j - 1] + 1, last + (a[i - 1] === b[j - 1] ? 0 : 1));
        last = keep;
      }
    }
    return row[b.length];
  }
  function readBack(text) {
    // The back: the occupation (a line of words alone), the gender, the religion and the marital status.
    var lines = text.split("\n").map(function (line) { return plain(line); }).filter(Boolean), best = null, job = "";
    lines.forEach(function (line) {
      lettersOnly(line).split(" ").forEach(function (word) {
        Object.keys(MARITAL).forEach(function (code) {
          MARITAL[code].forEach(function (known) {
            var d = distance(word, known);
            if (d <= (word.length >= 5 ? 2 : 1) && (!best || d < best.d)) best = { code: code, d: d };
          });
        });
      });
      var words = lettersOnly(line);
      if (!job && words.length >= 3 && !digitCount(line) && !NOT_JOB.test(line)) job = words;
    });
    return { marital: best ? best.code : "", occupation: job };
  }
  function linesOf(result) {
    var lines = [];
    (result.data.blocks || []).forEach(function (block) {
      (block.paragraphs || []).forEach(function (paragraph) {
        (paragraph.lines || []).forEach(function (line) {
          var text = (line.text || "").trim();
          if (text) lines.push({ text: text, top: line.bbox.y0, bottom: line.bbox.y1, conf: line.confidence });
        });
      });
    });
    return lines;
  }
  function together(first, second) {
    // The lines of two readings of the same part: a line found by one only is added, in its place from the top.
    var lines = first.slice();
    second.forEach(function (line) {
      var same = lines.filter(function (other) {
        var shared = Math.min(other.bottom, line.bottom) - Math.max(other.top, line.top);
        return shared / Math.max(other.bottom - other.top, line.bottom - line.top, 1) > 0.6;
      })[0];
      if (!same) lines.push(line);
      else if (line.conf > same.conf) lines[lines.indexOf(same)] = line;
    });
    return lines.sort(function (a, b) { return a.top - b.top; }).map(function (line) { return line.text; });
  }
  function sizedTo(source, width) {
    // The card at one width: the reader loses big letters (a photo from near) as well as small ones.
    var canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = Math.round(source.height * width / source.width);
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
  }
  function recognize(card, side) {
    // The front's words are on its right part (the photo is on the left), the back's everywhere. Read twice, as one
    // block of text and as words apart: each way loses a short line (the first name) the other one finds.
    var big = sizedTo(card, 1400), area = side === "front" ? part(big, 0.3, 0.02, 0.98, 0.98) : part(big, 0.02, 0.02, 0.98, 0.98);
    var output = { text: true, blocks: true, hocr: false, tsv: false };
    return worker().then(function (reader) {
      var block;
      return reader.setParameters({ tessedit_pageseg_mode: "6" })
        .then(function () { return reader.recognize(area, {}, output); })
        .then(function (result) { block = linesOf(result); return reader.setParameters({ tessedit_pageseg_mode: "11" }); })
        .then(function () { return reader.recognize(area, {}, output); })
        .then(function (result) { var lines = together(block, linesOf(result)); return lines.join("\n"); });
    });
  }

  // ---- The details of an Egyptian national ID number (like apps/core/utils.py parse_egyptian_national_id).
  function nidDetails(number) {
    if (!validNationalId(number)) return null;
    return { born: new Date((number[0] === "2" ? 1900 : 2000) + parseInt(number.substr(1, 2), 10),
                            parseInt(number.substr(3, 2), 10) - 1, parseInt(number.substr(5, 2), 10)),
             gender: parseInt(number[12], 10) % 2 ? "M" : "F", governorate: number.substr(7, 2) };
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function setField(field, value, fromCard) {
    // Fill a box of the form (a list, a date with its calendar, or text) and mark it as read from the card.
    if (!field || value === undefined || value === null || value === "") return false;
    if (field._flatpickr && value instanceof Date) field._flatpickr.setDate(value, false);
    else if (value instanceof Date) field.value = pad(value.getDate()) + "/" + pad(value.getMonth() + 1) + "/" + value.getFullYear();
    else field.value = value;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
    field.setAttribute("data-auto-filled", "1");
    if (fromCard) field.classList.add("is-filled-from-card");
    return true;
  }
  function emptyOrAuto(field) { return field && (!field.value || field.hasAttribute("data-auto-filled")); }
  // Typing (or reading) the national ID fills the date of birth, the gender and the governorate when they are empty
  // (or were filled from an earlier number): the secretary sees them and can change them.
  document.querySelectorAll("input[data-nid-fills]").forEach(function (input) {
    var form = input.form;
    function fillFromNumber() {
      var type = form.querySelector("[name='id_type']");
      if (type && type.value && type.value !== "nid") return;
      var details = nidDetails((input.value || "").replace(/\s/g, ""));
      if (!details) return;
      [["birth_date", details.born], ["gender", details.gender], ["governorate", details.governorate]].forEach(function (pair) {
        var field = form.querySelector("[name='" + pair[0] + "']");
        if (!emptyOrAuto(field)) return;
        var current = field.value;
        if (pair[0] === "birth_date" && field._flatpickr && field._flatpickr.selectedDates[0] &&
            field._flatpickr.selectedDates[0].getTime() === pair[1].getTime()) return;
        if (current !== pair[1]) setField(field, pair[1], false);
      });
    }
    input.addEventListener("change", fillFromNumber);
    input.addEventListener("input", function () { if ((input.value || "").replace(/\s/g, "").length === 14) fillFromNumber(); });
  });

  function cityIn(text, form) {
    // The city of the governorate's list named in the address (like apps/core/egypt.py city_in).
    var input = form && form.querySelector("input[data-city-list]"), lists;
    if (!input) return "";
    try { lists = JSON.parse(input.getAttribute("data-city-list")); } catch (e) { return ""; }
    var governorate = (form.querySelector("[name='governorate']") || {}).value || "", address = plain(text);
    var order = [lists[governorate] || []].concat(Object.keys(lists).filter(function (code) { return code !== governorate; })
      .map(function (code) { return lists[code]; }));
    for (var i = 0; i < order.length; i++) {
      var found = order[i].filter(function (city) { return address.indexOf(plain(city)) >= 0; });
      found = found.filter(function (city) {
        return !found.some(function (other) { return other !== city && plain(other).indexOf(plain(city)) >= 0; });
      });
      if (found.length) {
        found.sort(function (a, b) { return address.indexOf(plain(a)) - address.indexOf(plain(b)); });
        return found[0];
      }
    }
    return "";
  }

  function setupIdCheck(input) {
    var panel = document.createElement("div"), state = null;
    panel.className = "id-check card mt-2"; panel.hidden = true;
    input.insertAdjacentElement("afterend", panel);
    var form = input.form, side = input.getAttribute("data-id-card"), patientForm = !!(form && form.querySelector("[name='full_name']"));
    function field(name) { return form && form.querySelector("[name='" + name + "']"); }
    function idTypeIsCard() { var type = field("id_type"); return !type || !type.value || type.value === "nid"; }
    function kindIsCard() {
      var kind = form && form.querySelector("select[name='kind']");
      return !kind || ["id_front", "id_back", "passport"].indexOf(kind.value) >= 0;
    }
    function cardSide() {
      if (side !== "any") return side;
      var kind = form && form.querySelector("select[name='kind']");
      return kind && kind.value === "id_back" ? "back" : "front";
    }
    if (canCamera) {
      var camera = document.createElement("button");
      camera.type = "button"; camera.className = "btn btn-primary id-camera-open-btn";
      camera.innerHTML = '<i class="bi bi-camera"></i> <span></span>';
      camera.querySelector("span").textContent = idText("camera");
      input.insertAdjacentElement("beforebegin", camera);
      camera.addEventListener("click", function () {
        openCamera(function (shot) {
          state = { photo: shot, turn: 0, whole: false, name: "camera-" + cardSide() + ".jpg", camera: true };
          show();
        });
      });
    }
    function button(label, icon, action) {
      return '<button type="button" class="btn btn-sm btn-outline-secondary" data-id-action="' + action + '"><i class="bi ' +
        icon + '"></i> ' + label + "</button>";
    }
    function line(place, icon, html) {
      var row = document.createElement("div");
      row.innerHTML = '<i class="bi ' + icon + '"></i> ' + html;
      place.appendChild(row);
      return row;
    }
    function show() {
      var photo = turned(state.photo, state.turn);
      var box = state.whole || state.camera ? null : findCard(photo);
      var card = photo;
      if (box) {
        card = document.createElement("canvas");
        card.width = Math.round(box.w); card.height = Math.round(box.h);
        card.getContext("2d").drawImage(photo, box.x, box.y, box.w, box.h, 0, 0, card.width, card.height);
      }
      if (!state.whole) card = tighten(card);
      var checks = photoQuality(card, state.camera ? card : photo);
      if (!state.whole && !state.camera && !box) checks.push(["warn", idText("no-card")]);
      if (card.height > card.width) checks.push(["warn", idText("upright")]);
      var good = !checks.some(function (c) { return c[0] === "bad"; });
      panel.innerHTML = '<div class="card-body d-flex flex-wrap gap-3 align-items-start"><img class="id-check-preview" alt="">' +
        '<div class="flex-grow-1"><div class="fw-semibold mb-1">' + (good ? '<i class="bi bi-check-circle-fill text-success"></i> ' + idText(checks.length ? "fair" : "good")
        : '<i class="bi bi-x-octagon-fill text-danger"></i> ' + idText("retake")) + '</div><ul class="id-check-list"></ul>' +
        '<div class="id-check-read small mb-2"></div><div class="d-flex flex-wrap gap-2">' +
        button(idText("turn-left"), "bi-arrow-counterclockwise", "left") + button(idText("turn-right"), "bi-arrow-clockwise", "right") +
        (box || state.whole ? button(state.whole ? idText("card-only") : idText("whole"), "bi-bounding-box", "whole") : "") +
        button(idText("again"), state.camera ? "bi-camera" : "bi-image", "again") + "</div></div></div>";
      panel.querySelector(".id-check-preview").src = card.toDataURL("image/jpeg", 0.8);
      var list = panel.querySelector(".id-check-list");
      checks.forEach(function (c) {
        var li = document.createElement("li");
        li.className = "is-" + c[0];
        li.textContent = c[1];
        list.appendChild(li);
      });
      if (box || state.camera) { var li = document.createElement("li"); li.className = "is-ok"; li.textContent = idText("card-found"); list.appendChild(li); }
      panel.hidden = false;
      var kept = input.parentElement.querySelector("[data-kept-photo]");
      if (kept) kept.hidden = true;  // the new photo replaces the one kept from the last try
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
      if (patientForm && idTypeIsCard()) read(sized);  // read even a poor photo: the boxes stay to be checked
    }
    function read(card) {
      var place = panel.querySelector(".id-check-read"), token = state.token = {}, which = cardSide();
      place.innerHTML = "";
      var status = document.createElement("div");
      status.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ';
      status.appendChild(document.createTextNode(idText(which === "front" ? "reading" : "reading-back")));
      place.appendChild(status);
      var filled = [];
      function done() {
        if (token !== state.token) return;
        status.remove();
        if (filled.length) {
          line(place, "bi-magic text-success", "").appendChild(document.createTextNode(idText("filled-list") + " " + filled.join("، ") + "."));
        } else if (!place.querySelector("[data-id-action='use']")) {
          line(place, "bi-info-circle", "").appendChild(document.createTextNode(idText("read-none")));
        }
      }
      function offer(name, value, label) {
        // A box already written differently: show what the card says, with "Use it".
        var target = field(name);
        if (!target || !value) return;
        if (emptyOrAuto(target)) {
          if (target.value !== value) { setField(target, value, true); }
          filled.push(label);
          return;
        }
        if (plain(target.value) === plain(value)) return;
        var row = line(place, "bi-exclamation-triangle text-warning", "");
        row.appendChild(document.createTextNode(idText("card-says") + " "));
        var shown = document.createElement("b"); shown.textContent = value; row.appendChild(shown);
        row.appendChild(document.createTextNode(" (" + label + ") "));
        var use = document.createElement("button");
        use.type = "button"; use.className = "btn btn-sm btn-link p-0 align-baseline"; use.setAttribute("data-id-action", "use");
        use.textContent = idText("use");
        use.addEventListener("click", function () { setField(target, value, true); row.remove(); });
        row.appendChild(use);
      }
      var number = which === "front" ? readCard(card) : Promise.resolve("");
      number.then(function (found) {
        if (token !== state.token) return;
        if (found) offer("national_id", found, idText("label-number"));
        return recognize(card, which).then(function (text) {
          if (token !== state.token) return;
          if (which === "front") {
            var front = readFront(text);
            if (!found && front.number) offer("national_id", front.number, idText("label-number"));
            offer("full_name", front.name, idText("label-name"));
            offer("address", front.address, idText("label-address"));
            var city = cityIn(front.address, form);
            if (city) offer("city", city, idText("label-city"));
          } else {
            var back = readBack(text);
            offer("marital_status", back.marital, idText("label-marital"));
            offer("occupation", back.occupation, idText("label-occupation"));
          }
        });
      }).catch(function () {}).then(done);
    }
    panel.addEventListener("click", function (event) {
      var action = event.target.closest("[data-id-action]");
      if (!action || !state) return;
      var what = action.getAttribute("data-id-action");
      if (what === "left") { state.turn = (state.turn + 270) % 360; show(); }
      else if (what === "right") { state.turn = (state.turn + 90) % 360; show(); }
      else if (what === "whole") { state.whole = !state.whole; show(); }
      else if (what === "again") {
        var camera = state.camera;
        input.value = ""; panel.hidden = true; state = null;
        if (camera && canCamera) input.parentElement.querySelector(".id-camera-open-btn").click(); else input.click();
      }
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
  document.querySelectorAll("input[type=file][data-id-card]").forEach(setupIdCheck);
})();
