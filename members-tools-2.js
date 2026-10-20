/*!
 * TraderWatch members-tools-2.js  (pasang SELEPAS members-tools.js)
 * Dalam members.html, letak dua tag script berturutan dengan atribut defer:
 * members-tools.js dahulu, kemudian members-tools-2.js.
 *
 * Pilihan tetapan: sebelum kedua-dua skrip, tetapkan
 *   window.TW_CONFIG = { tzOffset: 8, supportUrl: 'https://t.me/USERNAME?text=' };
 */
(function () {
  'use strict';

  var CFG = Object.assign({
    tzOffset: 8,        // zon masa "Posted" pada laman (8 = Malaysia)
    statsDays: 30,
    // Only count signals closed on/after this moment in Prestasi. Set to the
    // day the verified signal engine started so legacy/backfilled records do
    // not inflate win rate or pips. Empty string = count everything.
    statsSince: '2026-10-19T08:00:00+08:00',
    supportUrl: '',     // kosong = sembunyi butang "Tanya"
    brand: 'TraderWatch'
  }, window.TW_CONFIG || {});

  // ---------- Storan ----------
  function ls(k, def) {
    try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : def; }
    catch (e) { return def; }
  }
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  // ---------- CSS ----------
  var css = `
#tw-bar.tw2-on{gap:0}
#tw-bar.tw2-on .tw-stats{display:none}
.tw2{background:#fff;border:1px solid #dfe6f0;border-radius:22px;overflow:hidden;box-shadow:0 8px 28px rgba(27,42,74,.08);margin:0 0 4px}
.tw2 *{box-sizing:border-box}
.tw2-band{background:linear-gradient(135deg,#14213d 0%,#24427a 55%,#3d6fc4 100%);color:#fff;padding:18px 18px 16px}
.tw2-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px}
.tw2-brand{font-size:20px;font-weight:700;letter-spacing:-.01em}
.tw2-open{font-size:13px;color:rgba(255,255,255,.78);margin-top:4px;display:flex;align-items:center;gap:8px;line-height:1.4}
.tw2-live{flex:none;width:8px;height:8px;border-radius:50%;background:#7fe0a3;box-shadow:0 0 0 4px rgba(127,224,163,.22)}
.tw2-live.off{background:#9fb0cc;box-shadow:none}
.tw2-fav{flex:none;display:inline-flex;align-items:center;gap:6px;font:inherit;font-size:13px;font-weight:600;color:#fff;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:7px 12px;cursor:pointer;transition:background .15s}
.tw2-fav:hover{background:rgba(255,255,255,.2)}
.tw2-fav[aria-pressed="true"]{background:#fff;color:#14213d;border-color:#fff}
.tw2-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@media(min-width:720px){.tw2-kpis{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:600px){
.tw2{border-radius:16px;margin-left:0;margin-right:0}
.tw2-band{padding:16px 14px 14px}
.tw2-top{align-items:center;margin-bottom:12px}
.tw2-brand{font-size:18px}.tw2-open{font-size:12px}
.tw2-fav{padding:7px 10px;font-size:12px}
.tw2-kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.tw2-k{min-height:76px;padding:10px;grid-template-columns:1fr}.tw2-kx{display:none}.tw2-kv{font-size:22px}.tw2-kl,.tw2-ks{font-size:11px}
.tw2-tabs{margin:10px 10px 0;padding:3px;gap:3px;overflow-x:auto;scroll-snap-type:x proximity}
.tw2-tab{flex:0 0 auto;padding:9px 11px;font-size:12px;scroll-snap-align:start}.tw2-tab svg{width:16px;height:16px}
.tw2-hint{padding:8px 12px 10px}.tw2-panel{padding:12px 10px 14px}
.tw2-grid.two{grid-template-columns:1fr}.tw2-box{padding:12px}.tw2-tiles{grid-template-columns:1fr}
.tw2-in,.tw-row{grid-template-columns:1fr}
.tw2-pr{grid-template-columns:72px 1fr 34px 46px;font-size:12px;gap:5px}
.tw2-jr{grid-template-columns:1fr;gap:8px}.tw2-seg{justify-self:start}.tw2-x{position:absolute;right:12px}
.tw-actions{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px!important;align-items:stretch!important}
.tw-actions .tw-btn{width:100%;padding:8px 6px;font-size:12px;border-radius:10px;min-height:38px}
.tw-actions .tw-rr{grid-column:1/-1;margin:0;text-align:left;font-size:12px}
}
.tw2-k{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.16);border-radius:16px;padding:12px 14px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:2px 8px;min-height:78px}
.tw2-ks{min-width:0}
.tw2-kl{grid-column:1/-1;font-size:12px;color:rgba(255,255,255,.72)}
.tw2-kv{font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
.tw2-ks{grid-column:1;font-size:12px;color:rgba(255,255,255,.7)}
.tw2-kx{grid-row:2/4;grid-column:2;display:flex;align-items:center}
.tw2-k.warn{background:rgba(255,120,120,.18);border-color:rgba(255,160,160,.5)}
.tw2-tabs{display:flex;gap:4px;margin:14px 14px 0;padding:4px;background:#f1f5fb;border-radius:16px;overflow-x:auto;scrollbar-width:none}
.tw2-tabs::-webkit-scrollbar{display:none}
.tw2-tab{flex:1 0 auto;display:inline-flex;align-items:center;justify-content:center;gap:7px;font:inherit;font-size:14px;font-weight:600;color:#5b6b85;background:none;border:0;border-radius:12px;padding:10px 14px;cursor:pointer;white-space:nowrap;transition:background .15s,color .15s}
.tw2-tab:hover{color:#1b2a4a}
.tw2-tab[aria-selected="true"]{background:#fff;color:#1b2a4a;box-shadow:0 2px 8px rgba(27,42,74,.12)}
.tw2-tab svg{flex:none}
.tw2-hint{font-size:12px;color:#7a889e;text-align:center;padding:10px 14px 12px}
.tw2-panel{padding:16px 14px 18px;animation:tw2in .18s ease-out}
.tw2-panel[hidden]{display:none}
@keyframes tw2in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.tw2-panel{animation:none}.tw2-fav,.tw2-tab{transition:none}}
.tw2-grid{display:grid;gap:14px}
@media(min-width:720px){.tw2-grid.two{grid-template-columns:1.15fr 1fr}}
.tw2-box{background:#f8fafd;border:1px solid #e6ecf4;border-radius:16px;padding:14px;min-width:0}
.tw2-box.full{grid-column:1/-1}
.tw2-h{font-size:13px;font-weight:700;color:#5b6b85;margin:0 0 10px}
.tw2-big{font-size:28px;font-weight:700;color:#1b2a4a;letter-spacing:-.02em;line-height:1.1}
.tw2-sub{font-size:13px;color:#7a889e;margin:2px 0 0}
.tw2-note{font-size:12px;color:#7a889e;margin:8px 0 0;line-height:1.5}
.tw2-pos{color:#23703f}.tw2-neg{color:#a63232}
.tw2-pr{display:grid;grid-template-columns:86px 1fr 40px 56px;gap:8px;align-items:center;font-size:13px;padding:5px 0;color:#1b2a4a}
.tw2-pr>span:nth-child(3),.tw2-pr>span:nth-child(4){text-align:right}
.tw2-track{height:8px;background:#e6ecf4;border-radius:6px;overflow:hidden}
.tw2-fillb{height:100%;border-radius:6px;background:#3d6fc4}
.tw2-tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.tw2-tile{background:#fff;border:1px solid #e6ecf4;border-radius:14px;padding:12px}
.tw2-tile b{display:block;font-size:22px;color:#1b2a4a}
.tw2-tile span{font-size:12px;color:#7a889e}
.tw2-in{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tw2-f{display:grid;gap:5px;font-size:13px;color:#5b6b85}
.tw2-f input,.tw2-f select{font:inherit;font-size:16px;color:#1b2a4a;background:#fff;border:1px solid #dfe6f0;border-radius:12px;padding:10px 12px;width:100%}
.tw2-f input:focus-visible,.tw2-f select:focus-visible,.tw2-tab:focus-visible,.tw2-fav:focus-visible,.tw2-btn:focus-visible,.tw2-seg button:focus-visible,.tw2-sw button:focus-visible{outline:2px solid #3d6fc4;outline-offset:2px}
.tw2-gauge{height:12px;border-radius:8px;background:#e6ecf4;overflow:hidden;margin:8px 0 6px}
.tw2-gauge>div{height:100%;border-radius:8px;background:linear-gradient(90deg,#2f9e5b,#e0b43a 70%,#c0392b);transition:width .3s}
.tw2-jr{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;background:#fff;border:1px solid #e6ecf4;border-radius:14px;padding:10px 12px;margin-bottom:8px}
.tw2-jm b{display:block;font-size:14px;color:#1b2a4a}
.tw2-jm span{font-size:12px;color:#7a889e}
.tw2-seg{display:inline-flex;background:#f1f5fb;border-radius:10px;padding:3px;gap:2px}
.tw2-seg button{font:inherit;font-size:12px;font-weight:700;color:#5b6b85;background:none;border:0;border-radius:8px;padding:6px 9px;cursor:pointer}
.tw2-seg button[aria-pressed="true"].o{background:#fff;color:#1b2a4a}
.tw2-seg button[aria-pressed="true"].t{background:#e3f4e8;color:#23703f}
.tw2-seg button[aria-pressed="true"].s{background:#fdecec;color:#a63232}
.tw2-seg button[aria-pressed="true"].b{background:#eceff3;color:#4a566b}
.tw2-x{font:inherit;border:0;background:none;color:#a63232;cursor:pointer;font-size:20px;line-height:1;padding:4px 6px}
.tw2-btn{font:inherit;font-size:14px;font-weight:600;color:#1b2a4a;background:#eef3fb;border:0;border-radius:12px;padding:10px 14px;cursor:pointer}
.tw2-btn:hover{background:#e3ebf8}
.tw2-row{display:flex;flex-wrap:wrap;gap:8px}
.tw2-tl{display:grid;gap:7px}
.tw2-tlr{display:grid;grid-template-columns:70px 1fr;gap:8px;align-items:center;font-size:13px;color:#1b2a4a}
.tw2-tlt{position:relative;height:16px;background:#eef2f8;border-radius:8px;overflow:hidden}
.tw2-tlt i{position:absolute;top:0;bottom:0;border-radius:8px;opacity:.38}
.tw2-tlr.on .tw2-tlt i{opacity:1}
.tw2-tlr .nm{display:flex;align-items:center;gap:6px}
.tw2-tlr .nm u{width:7px;height:7px;border-radius:50%;background:#c3ccdb;display:inline-block}
.tw2-tlr.on .nm u{background:#2f9e5b}
.tw2-tlw{position:relative;margin-left:78px;height:16px;font-size:11px;color:#7a889e}
.tw2-tlw span{position:absolute;transform:translateX(-50%)}
.tw2-now{position:absolute;top:0;bottom:0;width:2px;background:#14213d;z-index:2}
.tw2-tlwrap{position:relative}
.tw2-tlnow{position:absolute;top:0;bottom:0;left:78px;right:0;pointer-events:none}
.tw2-sr{display:grid;grid-template-columns:44px 1fr;gap:8px;align-items:center;font-size:13px;margin:4px 0}
.tw2-st{position:relative;height:10px;background:#e6ecf4;border-radius:6px}
.tw2-sf{position:absolute;top:0;height:10px;border-radius:6px}
.tw2-ev{display:grid;gap:8px}
.tw2-evc{background:#fff;border:1px solid #e6ecf4;border-radius:14px;padding:10px 12px;font-size:14px;color:#1b2a4a}
.tw2-evc small{display:block;color:#7a889e;font-size:12px}
.tw2-evc a{color:#2c5aa8;font-weight:600}
.tw2-sw{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #eef2f8}
.tw2-sw:last-of-type{border-bottom:0}
.tw2-sw b{display:block;font-size:14px;color:#1b2a4a}
.tw2-sw span{font-size:12px;color:#7a889e}
.tw2-sw button{flex:none;width:46px;height:28px;border-radius:999px;border:0;background:#c9d3e3;position:relative;cursor:pointer;transition:background .15s}
.tw2-sw button::after{content:"";position:absolute;top:3px;left:3px;width:22px;height:22px;border-radius:50%;background:#fff;transition:transform .15s;box-shadow:0 1px 3px rgba(0,0,0,.25)}
.tw2-sw button[aria-checked="true"]{background:#2f6fd0}
.tw2-sw button[aria-checked="true"]::after{transform:translateX(18px)}
.tw2-panel .tw-calc{border:0;padding:0;background:none}
.tw2-panel .tw-calc>summary{display:none}
.tw2-panel .tw-calc-body{padding:0;max-width:520px}
.tw-btn.on{background:#1b2a4a;color:#fff}
html.tw-dark{filter:invert(.92) hue-rotate(180deg);background:#fff}
html.tw-dark iframe,html.tw-dark img,html.tw-dark video{filter:invert(1) hue-rotate(180deg)}
/* Mobile tidy-up: keep cards from overflowing the viewport */
@media(max-width:600px){
.wrap{width:calc(100% - 24px)}
.page{padding:20px 0 56px}
.welcome{gap:10px;margin-bottom:18px}
.upgrade{padding:14px 16px;gap:10px;margin-bottom:24px}
.block{margin-top:30px}
.chartbox{border-radius:12px}
.tabs{overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
.sig{padding:14px}
.sig-top{margin-bottom:12px}
.tw2 .tw2-kx{display:none!important}
.tw2 .tw2-k{min-height:82px!important;grid-template-columns:1fr!important;align-content:center}
.tw2 .tw2-kv{font-size:22px}.tw2 .tw2-kl,.tw2 .tw2-ks{font-size:11px}
.sig .lock{flex-wrap:wrap;gap:8px}
}
`;
  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  // ---------- Pembantu ----------
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svgEl(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function icon(paths) {
    var s = svgEl('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none',
      stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round',
      'stroke-linejoin': 'round', 'aria-hidden': 'true' });
    paths.split('|').forEach(function (d) { s.appendChild(svgEl('path', { d: d })); });
    return s;
  }
  var ICONS = {
    perf: 'M4 19V5|M4 19h16|M8 15l3-4 3 2 4-6',
    calc: 'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z|M8 7h8|M8 12h2|M14 12h2|M8 16h2|M14 16h2',
    jr: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4z|M8 8h8|M8 12h6',
    sim: 'M3 17l5-5 4 3 8-9|M16 6h4v4',
    mkt: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z|M3 12h18|M12 3c3 3 3 15 0 18|M12 3c-3 3-3 15 0 18',
    set: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z|M12 2v3|M12 19v3|M2 12h3|M19 12h3|M5 5l2 2|M17 17l2 2|M19 5l-2 2|M7 17l-2 2'
  };
  function fmt(n, d) { return (n > 0 ? '+' : '') + n.toFixed(d == null ? 1 : d); }
  function cls(n) { return n > 0 ? 'tw2-pos' : (n < 0 ? 'tw2-neg' : ''); }
  function prettyPair(p) { return p.slice(0, 3) + '/' + p.slice(3); }

  function field(label, kind, props) {
    var w = el('label', 'tw2-f');
    w.appendChild(el('span', null, label));
    var i = document.createElement(kind);
    if (kind === 'input') {
      i.type = 'number'; i.step = 'any'; i.min = '0';
      i.setAttribute('inputmode', 'decimal');
    }
    Object.keys(props || {}).forEach(function (k) { i[k] = props[k]; });
    w.appendChild(i);
    return { wrap: w, input: i };
  }

  function box(title, full) {
    var b = el('div', 'tw2-box' + (full ? ' full' : ''));
    if (title) b.appendChild(el('p', 'tw2-h', title));
    return b;
  }

  function flash(btn, text) {
    var old = btn.getAttribute('data-label') || btn.textContent;
    btn.setAttribute('data-label', old);
    btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1400);
  }

  // ---------- Data ----------
  function allSignals() {
    var s = window.TWStatus;
    if (!s || !s.signals) return [];
    var out = [];
    Object.keys(s.signals).forEach(function (k) {
      var m = k.match(/^([A-Z]{6})_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/);
      if (!m) return;
      var o = s.signals[k];
      out.push({
        key: k, pair: m[1], hour: +m[5], status: o.status, pips: o.pips,
        r: o.r, closed: o.closed,
        t: Date.UTC(+m[2], +m[3] - 1, +m[4], +m[5], +m[6], +m[7]) - CFG.tzOffset * 3600000
      });
    });
    return out.sort(function (a, b) { return a.t - b.t; });
  }
  function closedSignals(days) {
    var cut = days ? Date.now() - days * 86400000 : 0;
    if (CFG.statsSince) {
      var since = Date.parse(CFG.statsSince);
      if (isFinite(since) && since > cut) cut = since;
    }
    return allSignals().filter(function (x) {
      return (x.status === 'tp' || x.status === 'sl') && x.t >= cut;
    });
  }
  // Honest period label: never claim "30 hari" when the tracking window is
  // shorter than that because statsSince started later.
  function periodLabel() {
    var days = CFG.statsDays;
    if (CFG.statsSince) {
      var since = Date.parse(CFG.statsSince);
      if (isFinite(since)) {
        var elapsed = (Date.now() - since) / 86400000;
        if (elapsed < days) {
          if (elapsed < 1) return 'hari ini';
          return Math.ceil(elapsed) + ' hari';
        }
      }
    }
    return days + ' hari';
  }
  function sessionOf(hour) {
    var u = (hour - CFG.tzOffset + 24) % 24;
    if (u >= 21 || u < 7) return 'Asia';
    if (u < 12) return 'London';
    return 'New York';
  }

  // ---------- Grafik ----------
  var gid = 0;
  function areaChart(pts, H, color) {
    var W = 320, P = 10;
    var min = Math.min.apply(null, pts.concat([0])), max = Math.max.apply(null, pts.concat([0]));
    if (max === min) max = min + 1;
    var X = function (i) { return P + i * (W - 2 * P) / Math.max(1, pts.length - 1); };
    var Y = function (v) { return H - P - (v - min) / (max - min) * (H - 2 * P); };
    var id = 'tw2g' + (++gid);
    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': 'Graf' });
    svg.style.display = 'block';
    var defs = svgEl('defs');
    var lg = svgEl('linearGradient', { id: id, x1: 0, y1: 0, x2: 0, y2: 1 });
    lg.appendChild(svgEl('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': '0.28' }));
    lg.appendChild(svgEl('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': '0' }));
    defs.appendChild(lg); svg.appendChild(defs);
    svg.appendChild(svgEl('line', { x1: P, x2: W - P, y1: Y(0), y2: Y(0), stroke: '#c9d3e3', 'stroke-dasharray': '3 4' }));
    var line = pts.map(function (v, i) { return X(i).toFixed(1) + ',' + Y(v).toFixed(1); });
    svg.appendChild(svgEl('polygon', {
      points: X(0).toFixed(1) + ',' + Y(0).toFixed(1) + ' ' + line.join(' ') + ' ' +
        X(pts.length - 1).toFixed(1) + ',' + Y(0).toFixed(1),
      fill: 'url(#' + id + ')'
    }));
    svg.appendChild(svgEl('polyline', { points: line.join(' '), fill: 'none', stroke: color,
      'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    svg.appendChild(svgEl('circle', { cx: X(pts.length - 1), cy: Y(pts[pts.length - 1]), r: 4.5,
      fill: '#fff', stroke: color, 'stroke-width': 2.5 }));
    return svg;
  }

  function sparkline(pts) {
    var W = 84, H = 30;
    var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
    if (max === min) max = min + 1;
    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, 'aria-hidden': 'true', 'class': 'sp' });
    svg.appendChild(svgEl('polyline', {
      points: pts.map(function (v, i) {
        return (2 + i * (W - 4) / Math.max(1, pts.length - 1)).toFixed(1) + ',' +
          (H - 3 - (v - min) / (max - min) * (H - 6)).toFixed(1);
      }).join(' '),
      fill: 'none', stroke: '#ffffff', 'stroke-width': 2.2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    return svg;
  }

  function ring(pct) {
    var R = 20, C = 2 * Math.PI * R;
    var svg = svgEl('svg', { viewBox: '0 0 52 52', width: 52, height: 52, 'aria-hidden': 'true' });
    svg.appendChild(svgEl('circle', { cx: 26, cy: 26, r: R, fill: 'none', stroke: 'rgba(255,255,255,.2)', 'stroke-width': 6 }));
    svg.appendChild(svgEl('circle', {
      cx: 26, cy: 26, r: R, fill: 'none', stroke: '#7fe0a3', 'stroke-width': 6, 'stroke-linecap': 'round',
      'stroke-dasharray': (C * pct / 100).toFixed(1) + ' ' + C.toFixed(1), transform: 'rotate(-90 26 26)'
    }));
    return svg;
  }

  // ---------- Rangka UI ----------
  var ui = { panels: {}, tabs: {}, active: null };
  var lastSig = '';
  var feedApplied = false;
  var TABS = [['perf', 'Prestasi'], ['calc', 'Kalkulator'], ['jr', 'Jurnal'],
              ['sim', 'Simulator'], ['mkt', 'Pasaran'], ['set', 'Tetapan']];

  function kpi(label) {
    var k = el('div', 'tw2-k');
    k.appendChild(el('span', 'tw2-kl', label));
    var v = el('b', 'tw2-kv', '–');
    var s = el('span', 'tw2-ks', '');
    var x = el('div', 'tw2-kx');
    k.appendChild(v); k.appendChild(x); k.appendChild(s);
    return { wrap: k, val: v, sub: s, x: x };
  }

  // Motion band artwork (grid + drawn price line) shared with #signals
  var TW_BAND_SVG = '<svg class="tw-band-svg" viewBox="0 0 970 430" preserveAspectRatio="none" aria-hidden="true">  <defs>    <linearGradient id="twg-band" x1="0" y1="0" x2="0" y2="1">      <stop offset="0" style="stop-color:var(--tw-accent)" stop-opacity=".35"/>      <stop offset="1" style="stop-color:var(--tw-accent)" stop-opacity="0"/>    </linearGradient>  </defs>  <path class="tw-area" d="M0,332 L24,341 L48,344 L73,346 L97,352 L121,363 L146,349 L170,334 L194,340 L218,344 L242,358 L267,371 L291,356 L315,336 L340,338 L364,331 L388,314 L412,293 L436,301 L461,315 L485,291 L509,303 L534,302 L558,304 L582,319 L606,332 L630,347 L655,331 L679,344 L703,318 L728,325 L752,303 L776,280 L800,256 L824,242 L849,231 L873,243 L897,218 L922,221 L946,215 L970,217 L970,430 L0,430 Z" fill="url(#twg-band)"/>  <path class="tw-line" pathLength="1" d="M0,332 L24,341 L48,344 L73,346 L97,352 L121,363 L146,349 L170,334 L194,340 L218,344 L242,358 L267,371 L291,356 L315,336 L340,338 L364,331 L388,314 L412,293 L436,301 L461,315 L485,291 L509,303 L534,302 L558,304 L582,319 L606,332 L630,347 L655,331 L679,344 L703,318 L728,325 L752,303 L776,280 L800,256 L824,242 L849,231 L873,243 L897,218 L922,221 L946,215 L970,217" fill="none" style="stroke:var(--tw-accent)" stroke-width="2.5" stroke-opacity=".85" stroke-linejoin="round"/>  <circle r="5" style="fill:var(--tw-accent-soft)">    <animateMotion dur="8s" repeatCount="indefinite" keyPoints="0;1;1" keyTimes="0;.85;1" calcMode="linear" path="M0,332 L24,341 L48,344 L73,346 L97,352 L121,363 L146,349 L170,334 L194,340 L218,344 L242,358 L267,371 L291,356 L315,336 L340,338 L364,331 L388,314 L412,293 L436,301 L461,315 L485,291 L509,303 L534,302 L558,304 L582,319 L606,332 L630,347 L655,331 L679,344 L703,318 L728,325 L752,303 L776,280 L800,256 L824,242 L849,231 L873,243 L897,218 L922,221 L946,215 L970,217"/>    <animate attributeName="opacity" dur="8s" repeatCount="indefinite" values="1;1;0;0" keyTimes="0;.85;.9;1"/>  </circle></svg>';

  function buildUI() {
    var bar = document.getElementById('tw-bar');
    if (!bar || document.getElementById('tw2')) return;
    bar.classList.add('tw2-on');
    var root = el('section', 'tw2 tw2-motion');
    root.id = 'tw2';

    // Jalur utama
    var band = el('div', 'tw2-band tw-band-motion');
    band.insertAdjacentHTML('afterbegin', TW_BAND_SVG);
    var top = el('div', 'tw2-top');
    var left = el('div');
    var planName = /max member/i.test(document.body.innerText || '') ? 'Max' : 'Pro';
    left.appendChild(el('div', 'tw2-brand', planName + ' toolkit'));
    var open = el('div', 'tw2-open');
    ui.live = el('span', 'tw2-live off');
    ui.openTxt = el('span', null, '');
    open.appendChild(ui.live); open.appendChild(ui.openTxt);
    left.appendChild(open);
    var fav = el('button', 'tw2-fav');
    fav.type = 'button';
    fav.setAttribute('aria-pressed', 'false');
    fav.textContent = '★ Kegemaran';
    fav.addEventListener('click', function () {
      window.TW_ONLY_STARRED = !window.TW_ONLY_STARRED;
      fav.setAttribute('aria-pressed', String(!!window.TW_ONLY_STARRED));
      document.dispatchEvent(new Event('tw-refilter'));
    });
    top.appendChild(left); top.appendChild(fav);
    band.appendChild(top);

    var grid = el('div', 'tw2-kpis');
    ui.kWin = kpi('Win rate ' + periodLabel());
    ui.kPips = kpi('Pips ' + periodLabel());
    ui.kStreak = kpi('TP berturut-turut');
    ui.kRisk = kpi('Baki risiko hari ini');
    [ui.kWin, ui.kPips, ui.kStreak, ui.kRisk].forEach(function (k) { grid.appendChild(k.wrap); });
    band.appendChild(grid);

    // Tabs + hint belong inside the full toolkit visual. Tab panels remain
    // below so long-form tools keep their original light background.
    var tabs = el('div', 'tw2-tabs');
    tabs.setAttribute('role', 'tablist');
    TABS.forEach(function (t) {
      var b = el('button', 'tw2-tab');
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', 'false');
      b.appendChild(icon(ICONS[t[0]]));
      b.appendChild(document.createTextNode(t[1]));
      b.addEventListener('click', function () { showTab(ui.active === t[0] ? null : t[0]); });
      ui.tabs[t[0]] = b;
      tabs.appendChild(b);
    });
    band.appendChild(tabs);
    ui.hint = el('p', 'tw2-hint', 'Pilih tab untuk buka alat.');
    band.appendChild(ui.hint);
    root.appendChild(band);

    // Tab panels
    TABS.forEach(function (t) {
      var p = el('div', 'tw2-panel');
      p.hidden = true;
      p.setAttribute('role', 'tabpanel');
      ui.panels[t[0]] = p;
      root.appendChild(p);
    });

    buildPerf(ui.panels.perf);
    var calc = document.getElementById('tw-calc');
    if (calc) { calc.open = false; ui.panels.calc.appendChild(calc); }
    buildJournal(ui.panels.jr);
    buildSim(ui.panels.sim);
    buildMarket(ui.panels.mkt);
    buildSettings(ui.panels.set);

    bar.insertBefore(root, bar.firstChild);

    // Filters + lot calculator live outside the card by default, which leaves
    // white strips above/below the motion panel. Move them inside so the
    // toolkit reads as one full-bleed dark surface.
    var tools = el('div', 'tw2-tools');
    var filters = bar.querySelector('.tw-filters');
    var calcEl = document.getElementById('tw-calc');
    if (filters) tools.appendChild(filters);
    if (calcEl) tools.appendChild(calcEl);
    if (tools.children.length) band.appendChild(tools);

  }

  function showTab(id) {
    ui.active = id;
    TABS.forEach(function (t) {
      var on = t[0] === id;
      ui.panels[t[0]].hidden = !on;
      ui.tabs[t[0]].setAttribute('aria-selected', String(on));
    });
    ui.hint.hidden = !!id;
    if (id === 'mkt') renderSessions();
  }
  document.addEventListener('tw-calc-open', function () { showTab('calc'); });

  // ---------- KPI ----------
  function renderKpi() {
    var list = closedSignals(CFG.statsDays);
    var wins = list.filter(function (x) { return x.status === 'tp'; }).length;
    var pips = list.reduce(function (a, x) { return a + (x.pips || 0); }, 0);
    var cur = 0;
    for (var i = list.length - 1; i >= 0 && list[i].status === 'tp'; i--) cur++;

    ui.kWin.x.textContent = '';
    if (list.length) {
      var pct = Math.round(wins / list.length * 100);
      ui.kWin.val.textContent = pct + '%';
      ui.kWin.sub.textContent = wins + ' daripada ' + list.length;
      ui.kWin.x.appendChild(ring(pct));
    } else {
      ui.kWin.val.textContent = '–';
      ui.kWin.sub.textContent = 'Belum ada data';
    }

    ui.kPips.x.textContent = '';
    if (list.length) {
      ui.kPips.val.textContent = fmt(pips);
      ui.kPips.sub.textContent = list.length + ' signal';
      var c = 0, pts = [0];
      list.forEach(function (x) { c += x.pips || 0; pts.push(c); });
      ui.kPips.x.appendChild(sparkline(pts));
    } else {
      ui.kPips.val.textContent = '–';
      ui.kPips.sub.textContent = '';
    }

    ui.kStreak.val.textContent = list.length ? String(cur) : '–';
    ui.kStreak.sub.textContent = list.length ? (cur ? 'signal terkini menang' : 'signal terakhir SL') : '';

    if (ui.limit) {
      var d = dayStats();
      var rem = d.limit + d.net - d.open;
      ui.kRisk.val.textContent = d.limit ? rem.toFixed(1) + '%' : '–';
      ui.kRisk.sub.textContent = d.limit ? 'had harian ' + d.limit + '%' : 'Tetapkan had';
      ui.kRisk.wrap.classList.toggle('warn', !!d.limit && rem <= 0);
    }
  }

  function renderOpenBoard() {
    var act = allSignals().filter(function (x) { return x.status === 'active'; });
    var risk = parseFloat(ui.defRisk ? ui.defRisk.value : 1) || 0;
    ui.live.className = 'tw2-live' + (act.length ? '' : ' off');
    ui.openTxt.textContent = act.length
      ? act.length + ' signal terbuka (' + act.map(function (x) { return prettyPair(x.pair); }).join(', ') +
        ') · risiko serentak ≈ ' + (act.length * risk).toFixed(1) + '%'
      : 'Tiada signal terbuka sekarang';
  }

  // ---------- Prestasi ----------
  function buildPerf(p) {
    ui.perfBody = el('div', 'tw2-grid two');
    p.appendChild(ui.perfBody);
  }

  function renderPerf() {
    var b = ui.perfBody;
    b.textContent = '';
    var list = closedSignals(CFG.statsDays);
    if (!list.length) {
      var e = box(null, true);
      e.appendChild(el('p', 'tw2-sub', 'Belum ada signal ditutup dalam ' + periodLabel() + '.'));
      b.appendChild(e);
      return;
    }

    var cum = 0, pts = [0];
    list.forEach(function (x) { cum += x.pips || 0; pts.push(cum); });
    var cur = 0, best = 0, run = 0;
    list.forEach(function (x) {
      if (x.status === 'tp') { run++; if (run > best) best = run; } else { run = 0; }
    });
    for (var i = list.length - 1; i >= 0 && list[i].status === 'tp'; i--) cur++;

    var c1 = box('Pips kumulatif');
    var big = el('div', 'tw2-big ' + cls(cum), fmt(cum) + ' pips');
    c1.appendChild(big);
    c1.appendChild(el('p', 'tw2-sub', list.length + ' signal · TP berturut-turut terbaik: ' + best));
    var chartWrap = el('div');
    chartWrap.style.marginTop = '10px';
    chartWrap.appendChild(areaChart(pts, 150, cum >= 0 ? '#2f9e5b' : '#c0392b'));
    c1.appendChild(chartWrap);
    b.appendChild(c1);

    var byPair = {}, bySes = {};
    list.forEach(function (x) {
      var p = byPair[x.pair] = byPair[x.pair] || { w: 0, n: 0, pips: 0 };
      p.n++; if (x.status === 'tp') p.w++; p.pips += x.pips || 0;
      var sn = sessionOf(x.hour);
      var q = bySes[sn] = bySes[sn] || { w: 0, n: 0, pips: 0 };
      q.n++; if (x.status === 'tp') q.w++; q.pips += x.pips || 0;
    });

    var c2 = box('Ikut pair');
    Object.keys(byPair).sort(function (a, c) { return byPair[c].pips - byPair[a].pips; }).forEach(function (k) {
      var m = byPair[k], pct = Math.round(m.w / m.n * 100);
      var r = el('div', 'tw2-pr');
      r.appendChild(el('span', null, prettyPair(k) + ' (' + m.n + ')'));
      var tr = el('div', 'tw2-track');
      var f = el('div', 'tw2-fillb');
      f.style.width = pct + '%';
      tr.appendChild(f);
      r.appendChild(tr);
      r.appendChild(el('span', null, pct + '%'));
      r.appendChild(el('span', cls(m.pips), fmt(m.pips)));
      c2.appendChild(r);
    });
    b.appendChild(c2);

    var c3 = box('Ikut sesi', true);
    var tiles = el('div', 'tw2-tiles');
    // Tetingkap sesi dalam waktu Malaysia, supaya ahli faham julat setiap satu.
    var SESS = [
      { k: 'Asia', w: '05:00–15:00 MY' },
      { k: 'London', w: '15:00–20:00 MY' },
      { k: 'New York', w: '20:00–04:00 MY' }
    ];
    SESS.forEach(function (s) {
      var m = bySes[s.k];
      var t = el('div', 'tw2-tile');
      t.appendChild(el('span', null, s.k));
      t.appendChild(el('b', null, m ? Math.round(m.w / m.n * 100) + '%' : '–'));
      t.appendChild(el('span', m ? cls(m.pips) : 'tw2-sub',
                       m ? fmt(m.pips) + ' pips · ' + m.n : 'Belum ada signal ditutup'));
      t.appendChild(el('span', 'tw2-sub', s.w));
      tiles.appendChild(t);
    });
    c3.appendChild(tiles);
    var csv = el('button', 'tw2-btn', 'Muat turun CSV');
    csv.type = 'button';
    csv.style.marginTop = '12px';
    csv.addEventListener('click', function () { downloadCsv(list); });
    c3.appendChild(csv);
    b.appendChild(c3);
  }

  function downloadCsv(list) {
    var rows = ['key,pair,status,pips,r,closed'];
    list.forEach(function (x) {
      rows.push([x.key, prettyPair(x.pair), x.status, x.pips == null ? '' : x.pips,
        x.r == null ? '' : x.r, x.closed || ''].join(','));
    });
    var blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'traderwatch-prestasi.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  // ---------- Jurnal + had risiko ----------
  var J_KEY = 'tw2-journal';

  function buildJournal(p) {
    var g = el('div', 'tw2-grid two');

    var a = box('Had risiko harian');
    ui.gaugeTxt = el('div', 'tw2-big', '–');
    a.appendChild(ui.gaugeTxt);
    var gauge = el('div', 'tw2-gauge');
    ui.gaugeFill = el('div');
    ui.gaugeFill.style.width = '0%';
    gauge.appendChild(ui.gaugeFill);
    a.appendChild(gauge);
    ui.gaugeSub = el('p', 'tw2-sub', '');
    a.appendChild(ui.gaugeSub);
    var row = el('div', 'tw2-in');
    row.style.marginTop = '14px';
    var lim = field('Had rugi harian (%)', 'input', { value: String(ls('tw2-limit', 3)) });
    var dr = field('Risiko lalai per trade (%)', 'input', { value: String(ls('tw2-risk', 1)) });
    ui.limit = lim.input; ui.defRisk = dr.input;
    row.appendChild(lim.wrap); row.appendChild(dr.wrap);
    a.appendChild(row);
    [ui.limit, ui.defRisk].forEach(function (n) {
      n.addEventListener('input', function () {
        lsSet('tw2-limit', parseFloat(ui.limit.value) || 0);
        lsSet('tw2-risk', parseFloat(ui.defRisk.value) || 0);
        renderJournal();
        renderOpenBoard();
      });
    });
    g.appendChild(a);

    var bx = box('Jurnal trade');
    ui.jStats = el('p', 'tw2-sub', '');
    ui.jStats.style.marginBottom = '10px';
    ui.jList = el('div');
    bx.appendChild(ui.jStats);
    bx.appendChild(ui.jList);
    bx.appendChild(el('p', 'tw2-note', 'Jurnal disimpan dalam browser ini sahaja. Tekan Jurnal pada kad signal untuk tambah.'));
    g.appendChild(bx);
    p.appendChild(g);
  }

  function journal() { return ls(J_KEY, []); }
  function saveJournal(j) { lsSet(J_KEY, j); renderJournal(); }

  function entryR(e) {
    if (e.result === 'tp') return e.rr || 0;
    if (e.result === 'sl') return -1;
    if (e.result === 'be') return 0;
    return null;
  }

  function dayStats() {
    var start = new Date(); start.setHours(0, 0, 0, 0);
    var net = 0, open = 0;
    journal().forEach(function (e) {
      if (e.ts < start.getTime()) return;
      var r = entryR(e);
      if (r == null) open += e.risk; else net += r * e.risk;
    });
    return { net: net, open: open, limit: parseFloat(ui.limit.value) || 0 };
  }

  function renderJournal() {
    if (!ui.jList) return;
    var j = journal();
    var d = dayStats();
    var remaining = d.limit + d.net - d.open;
    if (d.limit) {
      var used = Math.max(0, Math.min(100, (d.limit - remaining) / d.limit * 100));
      ui.gaugeFill.style.width = used.toFixed(0) + '%';
      ui.gaugeTxt.textContent = remaining.toFixed(1) + '% baki';
      ui.gaugeSub.textContent = remaining <= 0
        ? 'Had dicapai atau risiko terbuka terlebih. Elak trade baharu hari ini.'
        : 'daripada had ' + d.limit + '% · terbuka ' + d.open.toFixed(1) + '% · keputusan hari ini ' + fmt(d.net) + '%';
    } else {
      ui.gaugeFill.style.width = '0%';
      ui.gaugeTxt.textContent = '–';
      ui.gaugeSub.textContent = 'Tetapkan had rugi harian untuk amaran automatik.';
    }

    var closed = j.filter(function (e) { return entryR(e) != null; });
    var wins = closed.filter(function (e) { return e.result === 'tp'; }).length;
    var netR = closed.reduce(function (a, e) { return a + entryR(e); }, 0);
    var netP = closed.reduce(function (a, e) { return a + entryR(e) * e.risk; }, 0);
    ui.jStats.textContent = closed.length
      ? closed.length + ' trade ditutup · menang ' + Math.round(wins / closed.length * 100) +
        '% · ' + fmt(netR) + 'R · ' + fmt(netP) + '% akaun'
      : 'Belum ada trade ditutup.';

    ui.jList.textContent = '';
    if (!j.length) {
      ui.jList.appendChild(el('p', 'tw2-note', 'Jurnal kosong.'));
    }
    j.slice().sort(function (a, b) { return b.ts - a.ts; }).slice(0, 20).forEach(function (e) {
      var r = el('div', 'tw2-jr');
      var m = el('div', 'tw2-jm');
      m.appendChild(el('b', null, prettyPair(e.pair) + ' ' + e.side));
      var er = entryR(e);
      m.appendChild(el('span', null, 'Risiko ' + e.risk + '%' + (er == null ? '' : ' · ' + fmt(er) + 'R')));
      r.appendChild(m);
      var seg = el('div', 'tw2-seg');
      [['open', 'Buka', 'o'], ['tp', 'TP', 't'], ['sl', 'SL', 's'], ['be', 'BE', 'b']].forEach(function (o) {
        var bt = el('button', o[2], o[1]);
        bt.type = 'button';
        bt.setAttribute('aria-pressed', String(e.result === o[0]));
        bt.addEventListener('click', function () {
          var all = journal();
          all.forEach(function (x) { if (x.id === e.id) x.result = o[0]; });
          saveJournal(all);
        });
        seg.appendChild(bt);
      });
      r.appendChild(seg);
      var del = el('button', 'tw2-x', '×');
      del.type = 'button';
      del.setAttribute('aria-label', 'Padam entri');
      del.addEventListener('click', function () {
        saveJournal(journal().filter(function (x) { return x.id !== e.id; }));
      });
      r.appendChild(del);
      ui.jList.appendChild(r);
    });
    renderKpi();
  }

  function addJournal(d, btn) {
    var risk = parseFloat(ui.defRisk.value) || 1;
    var all = journal();
    var id = d.key || (d.pair + d.entry);
    if (all.some(function (x) { return x.id === id; })) { flash(btn, 'Sudah ada'); return; }
    var st = dayStats();
    if (st.limit && risk > st.limit + st.net - st.open) {
      if (!confirm('Trade ini akan melebihi had rugi harian anda. Tetap tambah?')) return;
    }
    var rr = Math.abs(d.tp - d.entry) / Math.abs(d.entry - d.sl);
    all.push({ id: id, pair: d.code, side: d.side, risk: risk, rr: rr, result: 'open', ts: Date.now() });
    saveJournal(all);
    flash(btn, 'Ditambah');
  }

  // ---------- Simulator ----------
  function buildSim(p) {
    var g = el('div', 'tw2-grid two');
    var a = box('Tetapan simulasi');
    var bal = field('Baki mula (USD)', 'input', { value: '1000' });
    var rsk = field('Risiko per trade (%)', 'input', { value: '1' });
    var per = field('Tempoh', 'select');
    [['7', '7 hari'], ['30', '30 hari'], ['90', '90 hari']].forEach(function (o) {
      var op = document.createElement('option');
      op.value = o[0]; op.textContent = o[1];
      if (o[0] === '30') op.selected = true;
      per.input.appendChild(op);
    });
    var stack = el('div');
    stack.style.display = 'grid'; stack.style.gap = '10px';
    stack.appendChild(bal.wrap); stack.appendChild(rsk.wrap); stack.appendChild(per.wrap);
    a.appendChild(stack);
    a.appendChild(el('p', 'tw2-note', 'Simulasi teori: ikut semua signal. Spread dan slippage diabaikan.'));
    g.appendChild(a);

    var r = box('Keputusan');
    ui.simBig = el('div', 'tw2-big', '–');
    ui.simSub = el('p', 'tw2-sub', 'Memuatkan data…');
    ui.simChart = el('div');
    ui.simChart.style.marginTop = '10px';
    r.appendChild(ui.simBig); r.appendChild(ui.simSub); r.appendChild(ui.simChart);
    g.appendChild(r);
    p.appendChild(g);

    ui.simIn = { bal: bal.input, rsk: rsk.input, per: per.input };
    Object.keys(ui.simIn).forEach(function (k) { ui.simIn[k].addEventListener('input', runSim); });
  }

  function runSim() {
    if (!ui.simIn) return;
    var start = parseFloat(ui.simIn.bal.value), risk = parseFloat(ui.simIn.rsk.value);
    var days = parseInt(ui.simIn.per.value, 10);
    ui.simChart.textContent = '';
    ui.simBig.className = 'tw2-big';
    if (!(start > 0) || !(risk > 0)) {
      ui.simBig.textContent = '–';
      ui.simSub.textContent = 'Masukkan baki dan risiko yang sah.';
      return;
    }
    var list = closedSignals(days), used = 0, skipped = 0;
    var bal = start, peak = start, dd = 0, pts = [start];
    list.forEach(function (x) {
      if (typeof x.r !== 'number') { skipped++; return; }
      used++;
      bal *= 1 + risk / 100 * x.r;
      pts.push(bal);
      if (bal > peak) peak = bal;
      var cur = (peak - bal) / peak * 100;
      if (cur > dd) dd = cur;
    });
    if (!used) {
      ui.simBig.textContent = '–';
      ui.simSub.textContent = 'Belum ada data R (nisbah untung/rugi) dalam tempoh ini.';
      return;
    }
    var ret = (bal / start - 1) * 100;
    ui.simBig.textContent = '$' + bal.toFixed(2);
    ui.simBig.className = 'tw2-big ' + cls(ret);
    ui.simSub.textContent = fmt(ret) + '% · drawdown maksimum ' + dd.toFixed(1) + '% · ' + used +
      ' signal' + (skipped ? ' (' + skipped + ' tiada data R)' : '');
    ui.simChart.appendChild(areaChart(pts.map(function (v) { return v - start; }), 120, ret >= 0 ? '#2f9e5b' : '#c0392b'));
  }

  // ---------- Pasaran ----------
  var SESS = [
    ['Sydney', 21, 6, '#8aa4d6'], ['Tokyo', 0, 9, '#d9829d'],
    ['London', 7, 16, '#4f93e0'], ['New York', 12, 21, '#3fb582']
  ];
  var BEST = [
    ['EUR/USD, GBP/USD', 'London dan New York'], ['USD/JPY', 'Tokyo dan New York'],
    ['AUD/USD', 'Sydney dan Tokyo'], ['USD/CAD', 'New York'], ['XAU/USD', 'London dan New York']
  ];

  function buildMarket(p) {
    var g = el('div', 'tw2-grid two');
    ui.sessBox = box('Sesi pasaran (waktu anda: UTC+' + CFG.tzOffset + ')', true);
    ui.strBox = box('Kekuatan mata wang');
    ui.evBox = box('Acara Max');
    var best = box('Masa sesuai ikut pair');
    BEST.forEach(function (x) {
      var r = el('div', 'tw2-pr');
      r.style.gridTemplateColumns = '1fr 1fr';
      r.appendChild(el('span', null, x[0]));
      var s = el('span', null, x[1]);
      s.style.textAlign = 'right'; s.style.color = '#5b6b85';
      r.appendChild(s);
      best.appendChild(r);
    });
    g.appendChild(ui.sessBox);
    g.appendChild(ui.strBox);
    g.appendChild(best);
    g.appendChild(ui.evBox);
    p.appendChild(g);
    renderSessions();
    setInterval(function () { if (ui.active === 'mkt') renderSessions(); }, 30000);
  }

  function renderSessions() {
    var box_ = ui.sessBox;
    box_.textContent = '';
    box_.appendChild(el('p', 'tw2-h', 'Sesi pasaran (waktu anda: UTC+' + CFG.tzOffset + ')'));
    var now = new Date();
    var utc = now.getUTCHours() + now.getUTCMinutes() / 60;
    var local = (utc + CFG.tzOffset + 24) % 24;
    var openNames = [];
    var wrap = el('div', 'tw2-tlwrap');
    var tl = el('div', 'tw2-tl');
    SESS.forEach(function (s) {
      var on = s[1] < s[2] ? (utc >= s[1] && utc < s[2]) : (utc >= s[1] || utc < s[2]);
      if (on) openNames.push(s[0]);
      var row = el('div', 'tw2-tlr' + (on ? ' on' : ''));
      var nm = el('span', 'nm');
      nm.appendChild(el('u'));
      nm.appendChild(document.createTextNode(s[0]));
      row.appendChild(nm);
      var track = el('div', 'tw2-tlt');
      var a = (s[1] + CFG.tzOffset) % 24, z = (s[2] + CFG.tzOffset) % 24;
      var segs = a < z ? [[a, z]] : [[a, 24], [0, z]];
      segs.forEach(function (sg) {
        var i = el('i');
        i.style.left = (sg[0] / 24 * 100) + '%';
        i.style.width = ((sg[1] - sg[0]) / 24 * 100) + '%';
        i.style.background = s[3];
        track.appendChild(i);
      });
      row.appendChild(track);
      tl.appendChild(row);
    });
    wrap.appendChild(tl);
    var nowLayer = el('div', 'tw2-tlnow');
    var mark = el('div', 'tw2-now');
    mark.style.left = (local / 24 * 100) + '%';
    nowLayer.appendChild(mark);
    wrap.appendChild(nowLayer);
    box_.appendChild(wrap);
    var ticks = el('div', 'tw2-tlw');
    [0, 6, 12, 18, 24].forEach(function (h) {
      var sp = el('span', null, (h < 10 ? '0' : '') + h + ':00');
      sp.style.left = (h / 24 * 100) + '%';
      ticks.appendChild(sp);
    });
    box_.appendChild(ticks);
    var line = openNames.length ? 'Sedang buka: ' + openNames.join(', ') + '.' : 'Semua sesi utama tutup.';
    if (openNames.indexOf('London') > -1 && openNames.indexOf('New York') > -1) {
      line += ' London dan New York bertindih, biasanya paling aktif.';
    }
    box_.appendChild(el('p', 'tw2-note', line));
  }

  function renderMarketData() {
    var s = window.TWStatus || {};
    ui.strBox.textContent = '';
    ui.strBox.appendChild(el('p', 'tw2-h', 'Kekuatan mata wang'));
    if (s.strength) {
      var keys = Object.keys(s.strength);
      var mx = Math.max.apply(null, keys.map(function (k) { return Math.abs(s.strength[k]); })) || 1;
      keys.sort(function (a, c) { return s.strength[c] - s.strength[a]; }).forEach(function (k) {
        var v = s.strength[k];
        var row = el('div', 'tw2-sr');
        row.appendChild(el('span', null, k));
        var tr = el('div', 'tw2-st');
        var f = el('div', 'tw2-sf');
        var w = Math.abs(v) / mx * 50;
        f.style.width = w + '%';
        f.style.left = v >= 0 ? '50%' : (50 - w) + '%';
        f.style.background = v >= 0 ? '#2f9e5b' : '#c0392b';
        tr.appendChild(f);
        row.appendChild(tr);
        ui.strBox.appendChild(row);
      });
    } else {
      ui.strBox.appendChild(el('p', 'tw2-note', 'Belum ada data.'));
    }
    ui.evBox.textContent = '';
    ui.evBox.appendChild(el('p', 'tw2-h', 'Acara Max'));
    var evs = el('div', 'tw2-ev');
    if (s.events && s.events.length) {
      s.events.forEach(function (ev) {
        var c = el('div', 'tw2-evc');
        c.appendChild(document.createTextNode(ev.title || ''));
        c.appendChild(el('small', null, ev.date || ''));
        if (ev.url && /^https?:\/\//.test(ev.url)) {
          var a = el('a', null, 'Buka pautan');
          a.href = ev.url; a.target = '_blank'; a.rel = 'noopener';
          c.appendChild(a);
        }
        evs.appendChild(c);
      });
    } else {
      evs.appendChild(el('p', 'tw2-note', 'Tiada acara akan datang.'));
    }
    ui.evBox.appendChild(evs);
  }

  // ---------- Tetapan ----------
  function filterSelects() {
    return document.querySelectorAll('#tw-bar .tw-filters select');
  }

  function switchRow(label, desc, on, cb) {
    var r = el('div', 'tw2-sw');
    var t = el('div');
    t.appendChild(el('b', null, label));
    t.appendChild(el('span', null, desc));
    var b = el('button');
    b.type = 'button';
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-label', label);
    b.setAttribute('aria-checked', String(!!on));
    b.addEventListener('click', function () {
      var nv = b.getAttribute('aria-checked') !== 'true';
      b.setAttribute('aria-checked', String(nv));
      cb(nv);
    });
    r.appendChild(t); r.appendChild(b);
    return { row: r, btn: b };
  }

  function chartsEl() {
    var c = document.getElementById('charts');
    if (c) return c;
    var hs = document.querySelectorAll('h1,h2,h3');
    for (var i = 0; i < hs.length; i++) {
      if (/live charts/i.test(hs[i].textContent)) return hs[i].parentElement;
    }
    return null;
  }

  function applyDark(on) {
    document.documentElement.classList.toggle('tw-dark', on);
    lsSet('tw2-dark', on);
  }
  function applySimple(on) {
    var c = chartsEl();
    if (c) c.style.display = on ? 'none' : '';
    lsSet('tw2-simple', on);
  }

  function buildSettings(p) {
    var bx = box(null, true);
    var dark = !!ls('tw2-dark', false);
    applyDark(dark);
    bx.appendChild(switchRow('Tema gelap', 'Tukar paparan kepada warna gelap.', dark, applyDark).row);
    var simple = switchRow('Mod mudah', 'Sembunyikan carta supaya hanya signal dipaparkan.',
      !!ls('tw2-simple', false), applySimple);
    ui.simpleSwitch = simple.btn;
    bx.appendChild(simple.row);

    var feed = el('div');
    feed.style.marginTop = '14px';
    feed.appendChild(el('p', 'tw2-h', 'Feed saya'));
    var row = el('div', 'tw2-row');
    var save = el('button', 'tw2-btn', 'Simpan penapis semasa');
    var use = el('button', 'tw2-btn', 'Guna penapis saya');
    save.type = 'button'; use.type = 'button';
    save.addEventListener('click', function () {
      var s = filterSelects();
      if (s.length < 3) return;
      lsSet('tw2-feed', { pair: s[0].value, side: s[1].value, type: s[2].value });
      flash(save, 'Disimpan');
    });
    use.addEventListener('click', function () { applyFeed(); flash(use, 'Digunakan'); });
    row.appendChild(save); row.appendChild(use);
    feed.appendChild(row);
    feed.appendChild(el('p', 'tw2-note', 'Penapis ini dipakai automatik setiap kali anda buka halaman. Untuk notifikasi ikut pair, guna topik Telegram.'));
    bx.appendChild(feed);
    p.appendChild(bx);
  }

  function applyFeed() {
    var f = ls('tw2-feed', null), s = filterSelects();
    if (!f || s.length < 3) return;
    [f.pair, f.side, f.type].forEach(function (v, i) {
      s[i].value = v;
      s[i].dispatchEvent(new Event('change'));
    });
  }

  // ---------- Butang pada kad ----------
  function enhanceCards() {
    var stars = ls('tw2-stars', []);
    var cards = document.querySelectorAll('[data-tw="1"]');
    cards.forEach(function (c) {
      var d = c._tw;
      if (!d || c.getAttribute('data-tw2') === '1') return;
      var act = c.querySelector('.tw-actions');
      if (!act) return;
      c.setAttribute('data-tw2', '1');
      var id = d.key || (d.pair + d.entry);
      c.setAttribute('data-star', stars.indexOf(id) > -1 ? '1' : '0');

      var star = el('button', 'tw-btn', stars.indexOf(id) > -1 ? '★' : '☆');
      star.type = 'button';
      star.setAttribute('aria-label', 'Tanda kegemaran');
      star.addEventListener('click', function () {
        var s = ls('tw2-stars', []), i = s.indexOf(id);
        if (i > -1) s.splice(i, 1); else s.push(id);
        lsSet('tw2-stars', s);
        var on = i === -1;
        c.setAttribute('data-star', on ? '1' : '0');
        star.textContent = on ? '★' : '☆';
        document.dispatchEvent(new Event('tw-refilter'));
      });

      var jr = el('button', 'tw-btn', 'Jurnal');
      jr.type = 'button';
      jr.addEventListener('click', function () { addJournal(d, jr); });

      var sh = el('button', 'tw-btn', 'Kongsi');
      sh.type = 'button';
      sh.addEventListener('click', function () { shareCard(d); });

      act.insertBefore(star, act.firstChild);
      act.appendChild(jr);
      act.appendChild(sh);

      if (CFG.supportUrl) {
        var q = el('button', 'tw-btn', 'Tanya');
        q.type = 'button';
        q.addEventListener('click', function () {
          var txt = 'Soalan tentang signal ' + d.pair + ' ' + d.side + ' (' + (d.key || '') + ')';
          window.open(CFG.supportUrl + encodeURIComponent(txt), '_blank', 'noopener');
        });
        act.appendChild(q);
      }
    });
  }

  // ---------- Kongsi sebagai imej ----------
  function shareCard(d) {
    var W = 1080, H = 1350;
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    var g = cv.getContext('2d');
    var gr = g.createLinearGradient(0, 0, W, H);
    gr.addColorStop(0, '#14213d'); gr.addColorStop(1, '#3d6fc4');
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    var sans = '-apple-system, "Segoe UI", Roboto, Arial, sans-serif';
    g.fillStyle = '#ffffff';
    g.font = '700 52px ' + sans;
    g.fillText(CFG.brand, 80, 130);
    g.font = '700 150px ' + sans;
    g.fillText(d.pair, 80, 340);
    g.fillStyle = d.side === 'BUY' ? '#7fe0a3' : '#ff9b9b';
    g.font = '700 80px ' + sans;
    g.fillText(d.side + (d.type ? ' · ' + d.type : ''), 80, 450);

    var rows = [['Entry', d.entry, '#ffffff'], ['SL', d.sl, '#ffb3b3'], ['TP', d.tp, '#a6efc0']];
    g.font = '600 64px ' + sans;
    rows.forEach(function (r, i) {
      var y = 640 + i * 130;
      g.fillStyle = 'rgba(255,255,255,.7)';
      g.textAlign = 'left';
      g.fillText(r[0], 80, y);
      g.fillStyle = r[2];
      g.textAlign = 'right';
      g.fillText(String(r[1]), W - 80, y);
    });
    g.textAlign = 'left';
    var rr = Math.abs(d.tp - d.entry) / Math.abs(d.entry - d.sl);
    g.fillStyle = '#ffffff';
    g.font = '600 56px ' + sans;
    var line = 'R:R 1:' + rr.toFixed(1);
    var labels = { tp: 'TP hit', sl: 'SL hit', active: 'Active', expired: 'Tamat', cancelled: 'Dibatalkan' };
    if (d.status && labels[d.status]) line += ' · ' + labels[d.status];
    g.fillText(line, 80, 1090);
    g.fillStyle = 'rgba(255,255,255,.65)';
    g.font = '400 34px ' + sans;
    g.fillText('Bukan nasihat kewangan. Dagangan melibatkan risiko tinggi.', 80, 1250);

    cv.toBlob(function (blob) {
      if (!blob) return;
      var file = new File([blob], 'traderwatch-signal.png', { type: 'image/png' });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: CFG.brand + ' ' + d.pair }).catch(function () {});
      } else {
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'traderwatch-' + d.code + '.png';
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
      }
    }, 'image/png');
  }

  // ---------- Kitaran ----------
  document.addEventListener('tw-run', function () {
    buildUI();
    if (!ui.perfBody) return;
    enhanceCards();
    var sig = JSON.stringify(window.TWStatus || {});
    if (sig !== lastSig) {
      lastSig = sig;
      renderPerf();
      renderMarketData();
      renderOpenBoard();
      runSim();
      renderKpi();
    }
    if (!feedApplied) {
      feedApplied = true;
      applyFeed();
      if (ls('tw2-simple', false)) applySimple(true);
      renderJournal();
    }
  });
})();
