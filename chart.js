/* TraderWatch PWA — chart.js
 * Renderer candlestick + garis canvas boleh guna semula, offline-capable, vanilla JS.
 * API: window.TWChart.render(canvas, {bars, overlays, markers, lastPrice})
 *      window.TWChart.line(canvas, {points:[[ts,value],...], zeroLine:true})
 *      → {destroy, redraw}. Auto-resize (ResizeObserver), DPR-aware.
 * bars: [[ts,o,h,l,c],...] ts UTC naive → dipapar MYT (Asia/Kuala_Lumpur).
 * Tiada animasi; redraw pada resize / data baru / crosshair.
 */
(function () {
  'use strict';

  var COLORS = { lime: '#c6f36b', red: '#ff817d', amber: '#ffd479', ink: '#f2f5ef' };
  var GRID = 'rgba(38, 51, 42, 0.6)';
  var AXIS = '#93a096';
  var TAG_INK = '#0a0e0b';
  var FONT = 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif';
  var MYT = 'Asia/Kuala_Lumpur';

  var timeFmt, tipFmt, dayFmt;
  try {
    timeFmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: MYT });
    tipFmt = new Intl.DateTimeFormat('ms-MY', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: MYT });
    dayFmt = new Intl.DateTimeFormat('ms-MY', { day: 'numeric', month: 'short', timeZone: MYT });
  } catch (e) {
    timeFmt = { format: function (d) { return d.toISOString().slice(11, 16); } };
    tipFmt = timeFmt;
    dayFmt = { format: function (d) { return d.toISOString().slice(5, 10); } };
  }

  var instances = new WeakMap();

  /* ---------- Utiliti ---------- */

  // ts UTC naive ("2026-10-26T02:00:00") → tambah Z; ISO beroffset dikekalkan.
  function parseTs(ts) {
    if (typeof ts === 'number') return ts;
    var s = String(ts);
    if (/(Z|[+-]\d{2}:?\d{2})$/.test(s)) return Date.parse(s);
    return Date.parse(s + 'Z');
  }

  // Desimal ikut magnitud: XAU/XAG 2, BTC 0 (>=10k), sederhana 1.
  function digitsFor(price) {
    var p = Math.abs(price);
    if (p >= 10000) return 0;
    if (p >= 1000) return 2;
    if (p >= 100) return 1;
    return 2;
  }

  function fmtPrice(v, digits) { return v.toFixed(digits); }

  function rgba(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }

  function color(name) { return COLORS[name] || COLORS.ink; }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function numOk(v) { return typeof v === 'number' && isFinite(v); }

  function rr(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function niceStep(raw) {
    var pow = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var f = raw / pow;
    var m = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
    return m * pow;
  }

  /* ---------- Lukisan ---------- */

  function draw(inst) {
    var canvas = inst.canvas, ctx = inst.ctx, o = inst.opts;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h || inst.destroyed) return;

    var dpr = Math.min(window.devicePixelRatio || 1, 3);
    var bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var bars = o.bars || [];
    var n = bars.length;
    if (!n) return;

    var padTop = 20, padBottom = 22, padLeft = 8, padRight = 68;
    var plotW = w - padLeft - padRight;
    var plotH = h - padTop - padBottom;
    if (plotW < 20 || plotH < 20) return;

    // Skala Y: min/max bars + semua paras overlay + lastPrice, padding 6%.
    var min = Infinity, max = -Infinity;
    var i, ov;
    for (i = 0; i < n; i++) {
      if (bars[i][3] < min) min = bars[i][3];
      if (bars[i][2] > max) max = bars[i][2];
    }
    (o.overlays || []).forEach(function (z) {
      if (z.type === 'zone' && numOk(z.from) && numOk(z.to)) {
        min = Math.min(min, z.from, z.to);
        max = Math.max(max, z.from, z.to);
      } else if (z.type === 'line' && numOk(z.price)) {
        min = Math.min(min, z.price);
        max = Math.max(max, z.price);
      }
    });
    if (o.lastPrice && numOk(o.lastPrice.price)) {
      min = Math.min(min, o.lastPrice.price);
      max = Math.max(max, o.lastPrice.price);
    }
    if (!isFinite(min) || !isFinite(max)) return;
    if (max === min) { max += 1; min -= 1; }
    var pad = (max - min) * 0.06;
    var lo = min - pad, hi = max + pad;
    var digits = digitsFor((min + max) / 2);

    var slot = plotW / n;
    function x(idx) { return padLeft + slot * (idx + 0.5); }
    function y(v) { return padTop + (hi - v) / (hi - lo) * plotH; }

    inst.geom = { padLeft: padLeft, padTop: padTop, plotW: plotW, plotH: plotH, slot: slot, n: n, y: y, digits: digits };

    // Grid mendatar (~5 garisan) + label harga kanan.
    var step = niceStep((max - min) / 5);
    ctx.font = '600 10px ' + FONT;
    ctx.textBaseline = 'middle';
    for (var v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      var gy = y(v);
      ctx.strokeStyle = GRID;
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(padLeft, gy);
      ctx.lineTo(padLeft + plotW, gy);
      ctx.stroke();
      ctx.fillStyle = AXIS;
      ctx.textAlign = 'left';
      ctx.fillText(fmtPrice(v, digits), w - padRight + 6, gy);
    }

    // Label X: HH:MM MYT setiap ~8 bar (jarak minimum supaya tidak bertindih).
    var every = 8;
    while (every * slot < 48 && every < n) every += 8;
    ctx.fillStyle = AXIS;
    ctx.textAlign = 'center';
    ctx.font = '600 9.5px ' + FONT;
    for (i = 0; i < n; i += every) {
      var tx = x(i);
      if (tx > padLeft + plotW - 18) continue;
      ctx.fillText(timeFmt.format(new Date(parseTs(bars[i][0]))), tx, h - padBottom / 2);
    }

    // Zon overlay (lorek 8% + label kecil kiri).
    (o.overlays || []).forEach(function (z) {
      if (z.type !== 'zone' || !numOk(z.from) || !numOk(z.to)) return;
      var c = color(z.color);
      var y1 = y(Math.max(z.from, z.to)), y2 = y(Math.min(z.from, z.to));
      ctx.fillStyle = rgba(c, 0.08);
      ctx.fillRect(padLeft, y1, plotW, Math.max(1, y2 - y1));
      if (z.label) {
        ctx.fillStyle = c;
        ctx.font = '700 8.5px ' + FONT;
        ctx.textAlign = 'left';
        ctx.fillText(String(z.label).toUpperCase(), padLeft + 5, clamp(y1 + 9, padTop + 8, padTop + plotH - 4));
      }
    });

    // Candle: wick 1px, body ~60% slot (min 2px).
    for (i = 0; i < n; i++) {
      var b = bars[i];
      var bull = b[4] >= b[1];
      var c = bull ? COLORS.lime : COLORS.red;
      var cx = x(i);
      ctx.strokeStyle = c;
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(cx, y(b[2]));
      ctx.lineTo(cx, y(b[3]));
      ctx.stroke();
      var bodyW = Math.max(2, slot * 0.6);
      var top = y(Math.max(b[1], b[4]));
      var bodyH = Math.max(1, Math.abs(y(b[1]) - y(b[4])));
      ctx.fillStyle = c;
      ctx.fillRect(cx - bodyW / 2, top, bodyW, bodyH);
    }

    // Garisan overlay + tag harga kanan (latar warna, teks gelap).
    var tags = [];
    (o.overlays || []).forEach(function (z) {
      if (z.type !== 'line' || !numOk(z.price)) return;
      var c = color(z.color);
      var ly = y(z.price);
      ctx.strokeStyle = c;
      ctx.lineWidth = 1.2;
      ctx.setLineDash(z.dash ? [5, 4] : []);
      ctx.beginPath();
      ctx.moveTo(padLeft, ly);
      ctx.lineTo(padLeft + plotW, ly);
      ctx.stroke();
      ctx.setLineDash([]);
      tags.push({ y: ly, text: z.label || fmtPrice(z.price, digits), bg: c, fg: TAG_INK, border: null });
    });

    // lastPrice: garisan halus + tag kanan neutral.
    if (o.lastPrice && numOk(o.lastPrice.price)) {
      var lpy = y(o.lastPrice.price);
      ctx.strokeStyle = rgba(COLORS.ink, 0.45);
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(padLeft, lpy);
      ctx.lineTo(padLeft + plotW, lpy);
      ctx.stroke();
      tags.push({ y: lpy, text: fmtPrice(o.lastPrice.price, digits), bg: '#18211a', fg: COLORS.ink, border: '#26332a' });
    }

    // Elak tag bertindih: jarak minimum 18px.
    tags.sort(function (a, b) { return a.y - b.y; });
    var prevY = -Infinity;
    tags.forEach(function (t) {
      t.ty = clamp(Math.max(t.y, prevY + 18), padTop + 8, padTop + plotH - 8);
      prevY = t.ty;
    });
    tags.forEach(function (t) {
      var tw = padRight - 6, th = 16, tx2 = w - padRight + 3;
      rr(ctx, tx2, t.ty - th / 2, tw, th, 4);
      ctx.fillStyle = t.bg;
      ctx.fill();
      if (t.border) { ctx.strokeStyle = t.border; ctx.lineWidth = 1; ctx.stroke(); }
      var fs = 9.5;
      ctx.font = '700 ' + fs + 'px ' + FONT;
      var mw = ctx.measureText(t.text).width;
      if (mw > tw - 6) { fs = Math.max(7.5, fs * (tw - 6) / mw); ctx.font = '700 ' + fs + 'px ' + FONT; }
      ctx.fillStyle = t.fg;
      ctx.textAlign = 'center';
      ctx.fillText(t.text, tx2 + tw / 2, t.ty + 0.5);
    });

    // Markers: garisan menegak putus-putus + label atas.
    var t0 = parseTs(bars[0][0]), tN = parseTs(bars[n - 1][0]);
    (o.markers || []).forEach(function (m) {
      var t = parseTs(m.ts);
      if (!isFinite(t)) return;
      var frac = tN > t0 ? (t - t0) / (tN - t0) : 0;
      var idx = clamp(Math.round(frac * (n - 1)), 0, n - 1);
      var mx = x(idx);
      var c = color(m.color || 'ink');
      ctx.strokeStyle = rgba(c, 0.75);
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(mx, padTop);
      ctx.lineTo(mx, padTop + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      if (m.label) {
        ctx.font = '700 8.5px ' + FONT;
        var lw = ctx.measureText(m.label).width + 10;
        var lx = clamp(mx - lw / 2, padLeft, w - padRight - lw);
        rr(ctx, lx, 3, lw, 13, 4);
        ctx.fillStyle = 'rgba(10, 14, 11, 0.88)';
        ctx.fill();
        ctx.fillStyle = c;
        ctx.textAlign = 'center';
        ctx.fillText(m.label, lx + lw / 2, 10);
      }
    });

    // Crosshair + tooltip OHLC (penjuru atas kiri).
    if (inst.cross) {
      var ci = inst.cross.idx;
      var cb = bars[ci];
      var ccx = x(ci);
      var ccy = clamp(inst.cross.y, padTop, padTop + plotH);
      ctx.strokeStyle = rgba(COLORS.ink, 0.5);
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(ccx, padTop);
      ctx.lineTo(ccx, padTop + plotH);
      ctx.moveTo(padLeft, ccy);
      ctx.lineTo(padLeft + plotW, ccy);
      ctx.stroke();
      ctx.setLineDash([]);

      var when = tipFmt.format(new Date(parseTs(cb[0])));
      var rows = [
        ['O', fmtPrice(cb[1], digits), COLORS.ink],
        ['H', fmtPrice(cb[2], digits), COLORS.ink],
        ['L', fmtPrice(cb[3], digits), COLORS.ink],
        ['C', fmtPrice(cb[4], digits), cb[4] >= cb[1] ? COLORS.lime : COLORS.red]
      ];
      ctx.font = '600 10px ' + FONT;
      var boxW = ctx.measureText(when).width;
      rows.forEach(function (r) { boxW = Math.max(boxW, ctx.measureText(r[0] + '  ' + r[1]).width); });
      boxW += 20;
      var boxH = 14 * (rows.length + 1) + 10;
      var bx = padLeft + 4, by = padTop + 4;
      rr(ctx, bx, by, boxW, boxH, 8);
      ctx.fillStyle = 'rgba(10, 14, 11, 0.94)';
      ctx.fill();
      ctx.strokeStyle = '#26332a';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.textAlign = 'left';
      ctx.fillStyle = COLORS.ink;
      ctx.font = '700 10px ' + FONT;
      ctx.fillText(when, bx + 10, by + 13);
      ctx.font = '600 10px ' + FONT;
      rows.forEach(function (r, ri) {
        var ry = by + 13 + (ri + 1) * 14;
        ctx.fillStyle = AXIS;
        ctx.fillText(r[0], bx + 10, ry);
        ctx.fillStyle = r[2];
        ctx.fillText(r[1], bx + 26, ry);
      });
    }
  }

  /* ---------- Graf garis (equity curve / siri harian) ---------- */

  function fmtR(v, digits) {
    var s = v > 0 ? '+' : '';
    return s + v.toFixed(digits == null ? 1 : digits) + 'R';
  }

  function drawLine(inst) {
    var canvas = inst.canvas, ctx = inst.ctx, o = inst.opts;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h || inst.destroyed) return;

    var dpr = Math.min(window.devicePixelRatio || 1, 3);
    var bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var pts = (o.points || []).filter(function (p) { return numOk(p[1]) && isFinite(parseTs(p[0])); });
    var n = pts.length;
    if (!n) return;

    var padTop = 16, padBottom = 22, padLeft = 8, padRight = 46;
    var plotW = w - padLeft - padRight;
    var plotH = h - padTop - padBottom;
    if (plotW < 20 || plotH < 20) return;

    // Skala Y sentiasa termasuk 0 (garis zero) + min/max siri.
    var min = 0, max = 0, i;
    for (i = 0; i < n; i++) {
      if (pts[i][1] < min) min = pts[i][1];
      if (pts[i][1] > max) max = pts[i][1];
    }
    if (max === min) { max += 1; min -= 1; }
    var pad = (max - min) * 0.08;
    var lo = min - pad, hi = max + pad;

    var t0 = parseTs(pts[0][0]), tN = parseTs(pts[n - 1][0]);
    function x(idx) {
      if (n === 1 || tN === t0) return padLeft + plotW / 2;
      return padLeft + (parseTs(pts[idx][0]) - t0) / (tN - t0) * plotW;
    }
    function y(v) { return padTop + (hi - v) / (hi - lo) * plotH; }

    inst.geom = { padLeft: padLeft, padTop: padTop, plotW: plotW, plotH: plotH, n: n, x: x, y: y };

    // Grid mendatar + label Y (R).
    var step = niceStep((max - min) / 4);
    var digits = step >= 1 ? 0 : 1;
    ctx.font = '600 10px ' + FONT;
    ctx.textBaseline = 'middle';
    for (var v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      var gy = y(v);
      ctx.strokeStyle = GRID;
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(padLeft, gy);
      ctx.lineTo(padLeft + plotW, gy);
      ctx.stroke();
      ctx.fillStyle = AXIS;
      ctx.textAlign = 'left';
      ctx.fillText(fmtR(v, digits), w - padRight + 6, gy);
    }

    // Label X: tarikh ringkas MYT, jarak minimum supaya tidak bertindih.
    ctx.fillStyle = AXIS;
    ctx.textAlign = 'center';
    ctx.font = '600 9.5px ' + FONT;
    var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 56))));
    for (i = 0; i < n; i += every) {
      var tx = x(i);
      if (tx > padLeft + plotW - 16) continue;
      ctx.fillText(dayFmt.format(new Date(parseTs(pts[i][0]))), tx, h - padBottom / 2);
    }

    // Garis zero putus-putus.
    if (o.zeroLine !== false && lo < 0 && hi > 0) {
      var zy = y(0);
      ctx.strokeStyle = rgba(COLORS.ink, 0.4);
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padLeft, zy);
      ctx.lineTo(padLeft + plotW, zy);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Area fill bawah garis (ke garis zero) lime 10%.
    var baseY = y(Math.max(lo, Math.min(hi, 0)));
    ctx.beginPath();
    ctx.moveTo(x(0), baseY);
    for (i = 0; i < n; i++) ctx.lineTo(x(i), y(pts[i][1]));
    ctx.lineTo(x(n - 1), baseY);
    ctx.closePath();
    ctx.fillStyle = rgba(COLORS.lime, 0.10);
    ctx.fill();

    // Garis lime 2.5px.
    ctx.beginPath();
    for (i = 0; i < n; i++) {
      if (i === 0) ctx.moveTo(x(i), y(pts[i][1]));
      else ctx.lineTo(x(i), y(pts[i][1]));
    }
    ctx.strokeStyle = COLORS.lime;
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.setLineDash([]);
    ctx.stroke();

    // Titik akhir bulat.
    ctx.beginPath();
    ctx.arc(x(n - 1), y(pts[n - 1][1]), 3.5, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.lime;
    ctx.fill();
    ctx.strokeStyle = TAG_INK;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Crosshair + tooltip (tarikh, R harian, cumulative R).
    if (inst.cross) {
      var ci = inst.cross.idx;
      var cx = x(ci), cy = y(pts[ci][1]);
      ctx.strokeStyle = rgba(COLORS.ink, 0.5);
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(cx, padTop);
      ctx.lineTo(cx, padTop + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(cx, cy, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.lime;
      ctx.fill();
      ctx.strokeStyle = TAG_INK;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      var dayR = ci === 0 ? pts[0][1] : pts[ci][1] - pts[ci - 1][1];
      var when = dayFmt.format(new Date(parseTs(pts[ci][0])));
      var rows = [
        ['Harian', fmtR(dayR, 2), dayR >= 0 ? COLORS.lime : COLORS.red],
        ['Jumlah', fmtR(pts[ci][1], 2), pts[ci][1] >= 0 ? COLORS.lime : COLORS.red]
      ];
      ctx.font = '600 10px ' + FONT;
      var boxW = ctx.measureText(when).width;
      rows.forEach(function (r) { boxW = Math.max(boxW, ctx.measureText(r[0] + '  ' + r[1]).width); });
      boxW += 20;
      var boxH = 14 * (rows.length + 1) + 10;
      var bx = padLeft + 4, by = padTop + 4;
      if (cx < bx + boxW + 12) bx = Math.min(cx + 12, w - padRight - boxW);
      rr(ctx, bx, by, boxW, boxH, 8);
      ctx.fillStyle = 'rgba(10, 14, 11, 0.94)';
      ctx.fill();
      ctx.strokeStyle = '#26332a';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.textAlign = 'left';
      ctx.fillStyle = COLORS.ink;
      ctx.font = '700 10px ' + FONT;
      ctx.fillText(when, bx + 10, by + 13);
      ctx.font = '600 10px ' + FONT;
      rows.forEach(function (r, ri) {
        var ry = by + 13 + (ri + 1) * 14;
        ctx.fillStyle = AXIS;
        ctx.fillText(r[0], bx + 10, ry);
        ctx.fillStyle = r[2];
        ctx.fillText(r[1], bx + 52, ry);
      });
    }
  }

  /* ---------- API ---------- */

  function render(canvas, opts) {
    if (!canvas || !canvas.getContext) return null;
    var prev = instances.get(canvas);
    if (prev) prev.destroy();
    var ctx = canvas.getContext('2d');
    if (!ctx) return null;

    var inst = { canvas: canvas, ctx: ctx, opts: opts || {}, cross: null, geom: null, destroyed: false };

    function onPoint(e) {
      var g = inst.geom;
      if (!g) return;
      var rect = canvas.getBoundingClientRect();
      var px = e.clientX - rect.left;
      var py = e.clientY - rect.top;
      var idx = clamp(Math.floor((px - g.padLeft) / g.slot), 0, g.n - 1);
      inst.cross = { idx: idx, y: py };
      draw(inst);
    }
    function onLeave() {
      if (!inst.cross) return;
      inst.cross = null;
      draw(inst);
    }

    canvas.style.touchAction = 'pan-y'; // scroll menegak halaman kekal berfungsi
    canvas.addEventListener('pointermove', onPoint);
    canvas.addEventListener('pointerdown', onPoint);
    canvas.addEventListener('pointerleave', onLeave);
    canvas.addEventListener('pointercancel', onLeave);

    if (typeof ResizeObserver !== 'undefined') {
      inst.ro = new ResizeObserver(function () { draw(inst); });
      inst.ro.observe(canvas);
    } else {
      inst.onWinResize = function () { draw(inst); };
      window.addEventListener('resize', inst.onWinResize);
    }

    inst.destroy = function () {
      if (inst.destroyed) return;
      inst.destroyed = true;
      instances.delete(canvas);
      if (inst.ro) inst.ro.disconnect();
      if (inst.onWinResize) window.removeEventListener('resize', inst.onWinResize);
      canvas.removeEventListener('pointermove', onPoint);
      canvas.removeEventListener('pointerdown', onPoint);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('pointercancel', onLeave);
    };

    instances.set(canvas, inst);
    draw(inst);
    return { destroy: inst.destroy, redraw: function () { draw(inst); } };
  }

  // Graf garis: points [[ts, value], ...]. Crosshair pilih titik terdekat.
  function line(canvas, opts) {
    if (!canvas || !canvas.getContext) return null;
    var prev = instances.get(canvas);
    if (prev) prev.destroy();
    var ctx = canvas.getContext('2d');
    if (!ctx) return null;

    var inst = { canvas: canvas, ctx: ctx, opts: opts || {}, cross: null, geom: null, destroyed: false };

    function onPoint(e) {
      var g = inst.geom;
      if (!g) return;
      var rect = canvas.getBoundingClientRect();
      var px = e.clientX - rect.left;
      var best = 0, bestD = Infinity;
      for (var i = 0; i < g.n; i++) {
        var d = Math.abs(g.x(i) - px);
        if (d < bestD) { bestD = d; best = i; }
      }
      inst.cross = { idx: best };
      drawLine(inst);
    }
    function onLeave() {
      if (!inst.cross) return;
      inst.cross = null;
      drawLine(inst);
    }

    canvas.style.touchAction = 'pan-y'; // scroll menegak halaman kekal berfungsi
    canvas.addEventListener('pointermove', onPoint);
    canvas.addEventListener('pointerdown', onPoint);
    canvas.addEventListener('pointerleave', onLeave);
    canvas.addEventListener('pointercancel', onLeave);

    if (typeof ResizeObserver !== 'undefined') {
      inst.ro = new ResizeObserver(function () { drawLine(inst); });
      inst.ro.observe(canvas);
    } else {
      inst.onWinResize = function () { drawLine(inst); };
      window.addEventListener('resize', inst.onWinResize);
    }

    inst.destroy = function () {
      if (inst.destroyed) return;
      inst.destroyed = true;
      instances.delete(canvas);
      if (inst.ro) inst.ro.disconnect();
      if (inst.onWinResize) window.removeEventListener('resize', inst.onWinResize);
      canvas.removeEventListener('pointermove', onPoint);
      canvas.removeEventListener('pointerdown', onPoint);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('pointercancel', onLeave);
    };

    instances.set(canvas, inst);
    drawLine(inst);
    return { destroy: inst.destroy, redraw: function () { drawLine(inst); } };
  }

  window.TWChart = { render: render, line: line };
})();