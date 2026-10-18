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
    tzOffset: 8,        // zon masa masa "Posted" pada laman (8 = Malaysia)
    statsDays: 30,
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
  var css = [
    '.tw2{display:grid;gap:10px}',
    '.tw2-chips{display:flex;flex-wrap:wrap;gap:8px}',
    '.tw2-chip{font:inherit;font-size:14px;font-weight:600;color:#1b2a4a;background:#fff;border:1px solid #dfe6f0;border-radius:999px;padding:8px 14px;cursor:pointer}',
    '.tw2-chip[aria-pressed="true"]{background:#1b2a4a;color:#fff;border-color:#1b2a4a}',
    '.tw2-sec{background:#fff;border:1px solid #dfe6f0;border-radius:14px;padding:2px 14px}',
    '.tw2-sec>summary{cursor:pointer;font-weight:700;font-size:16px;color:#1b2a4a;padding:12px 0}',
    '.tw2-body{display:grid;gap:12px;padding:2px 0 14px}',
    '.tw2-h{font-size:13px;font-weight:700;color:#5b6b85;margin:4px 0 0}',
    '.tw2-tbl{display:grid;gap:4px;font-size:14px}',
    '.tw2-tr{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:6px;padding:6px 0;border-bottom:1px solid #eef2f8}',
    '.tw2-tr span:nth-child(n+2){text-align:right}',
    '.tw2-tr.head{color:#7a889e;font-size:12px}',
    '.tw2-pos{color:#23703f}.tw2-neg{color:#a63232}',
    '.tw2-note{font-size:12px;color:#7a889e;margin:0}',
    '.tw2-banner{border-radius:12px;padding:10px 12px;font-size:14px;background:#eef3fb;color:#1b2a4a}',
    '.tw2-banner.warn{background:#fdecec;color:#a63232}',
    '.tw2-j{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #eef2f8;font-size:14px}',
    '.tw2-j select{font:inherit;font-size:14px;border:1px solid #dfe6f0;border-radius:8px;padding:6px;background:#f6f8fc;color:#1b2a4a}',
    '.tw2-x{font:inherit;border:0;background:none;color:#a63232;cursor:pointer;font-size:18px;line-height:1}',
    '.tw2-in{display:grid;grid-template-columns:1fr 1fr;gap:10px}',
    '.tw2-f{display:grid;gap:5px;font-size:13px;color:#5b6b85}',
    '.tw2-f input,.tw2-f select{font:inherit;font-size:16px;color:#1b2a4a;background:#f6f8fc;border:1px solid #dfe6f0;border-radius:10px;padding:10px;width:100%;box-sizing:border-box}',
    '.tw2-bar{display:grid;grid-template-columns:44px 1fr;gap:8px;align-items:center;font-size:13px}',
    '.tw2-track{position:relative;height:10px;background:#eef2f8;border-radius:6px}',
    '.tw2-fill{position:absolute;top:0;height:10px;border-radius:6px}',
    '.tw2-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;background:#b8c2d3}',
    '.tw2-dot.on{background:#2f9e5b}',
    '.tw2-ev a{color:#2c5aa8;font-weight:600}',
    '.tw-btn.on{background:#1b2a4a;color:#fff}',
    '.tw2-btn-s{font:inherit;font-size:14px;font-weight:600;color:#1b2a4a;background:#eef3fb;border:0;border-radius:10px;padding:10px 14px;cursor:pointer}',
    '.tw2-chip:focus-visible,.tw2-btn-s:focus-visible,.tw2-f input:focus-visible,.tw2-f select:focus-visible,.tw2-sec>summary:focus-visible{outline:2px solid #3d6fc4;outline-offset:2px}',
    'html.tw-dark{filter:invert(.92) hue-rotate(180deg);background:#fff}',
    'html.tw-dark iframe,html.tw-dark img,html.tw-dark video{filter:invert(1) hue-rotate(180deg)}'
  ].join('');
  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  // ---------- Pembantu ----------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function fmt(n, d) { return (n > 0 ? '+' : '') + n.toFixed(d == null ? 1 : d); }
  function cls(n) { return n > 0 ? 'tw2-pos' : (n < 0 ? 'tw2-neg' : ''); }

  function section(title) {
    var det = el('details', 'tw2-sec');
    det.appendChild(el('summary', null, title));
    var body = el('div', 'tw2-body');
    det.appendChild(body);
    return { det: det, body: body };
  }

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

  // Senarai signal daripada JSON status
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
    return allSignals().filter(function (x) {
      return (x.status === 'tp' || x.status === 'sl') && x.t >= cut;
    });
  }
  function prettyPair(p) { return p.slice(0, 3) + '/' + p.slice(3); }
  function sessionOf(hour) {
    var u = (hour - CFG.tzOffset + 24) % 24;
    if (u >= 21 || u < 7) return 'Asia';
    if (u < 12) return 'London';
    return 'New York';
  }

  // ---------- Rangka UI ----------
  var ui = {};
  var lastSig = '';
  var feedApplied = false;

  function buildUI() {
    var bar = document.getElementById('tw-bar');
    if (!bar || document.getElementById('tw2')) return;
    var root = el('div', 'tw2');
    root.id = 'tw2';

    var chips = el('div', 'tw2-chips');
    var starChip = el('button', 'tw2-chip', '★ Kegemaran sahaja');
    starChip.type = 'button';
    starChip.setAttribute('aria-pressed', 'false');
    starChip.addEventListener('click', function () {
      window.TW_ONLY_STARRED = !window.TW_ONLY_STARRED;
      starChip.setAttribute('aria-pressed', String(!!window.TW_ONLY_STARRED));
      document.dispatchEvent(new Event('tw-refilter'));
    });
    chips.appendChild(starChip);
    root.appendChild(chips);

    ui.openBoard = el('div', 'tw2-banner');
    root.appendChild(ui.openBoard);

    ui.perf = section('Prestasi');
    ui.jr = section('Jurnal dan had risiko');
    ui.sim = section('Simulator akaun');
    ui.mkt = section('Pasaran');
    ui.set = section('Tetapan');
    [ui.perf, ui.jr, ui.sim, ui.mkt, ui.set].forEach(function (s) { root.appendChild(s.det); });

    buildJournal();
    buildSim();
    buildMarket();
    buildSettings();
    bar.appendChild(root);
  }

  // ---------- Prestasi ----------
  function renderPerf() {
    var b = ui.perf.body;
    b.textContent = '';
    var list = closedSignals(CFG.statsDays);
    if (!list.length) {
      b.appendChild(el('p', 'tw2-note', 'Belum ada signal ditutup dalam ' + CFG.statsDays + ' hari.'));
      return;
    }

    // Equity curve
    b.appendChild(el('p', 'tw2-h', 'Pips kumulatif'));
    var cum = 0, pts = [0];
    list.forEach(function (x) { cum += x.pips || 0; pts.push(cum); });
    b.appendChild(equitySvg(pts));

    // Streak
    var cur = 0, best = 0, run = 0;
    list.forEach(function (x) {
      if (x.status === 'tp') { run++; if (run > best) best = run; } else { run = 0; }
    });
    for (var i = list.length - 1; i >= 0 && list[i].status === 'tp'; i--) cur++;
    b.appendChild(el('p', 'tw2-note',
      'TP berturut-turut sekarang: ' + cur + ' · rekod terbaik: ' + best));

    // Ikut pair
    b.appendChild(el('p', 'tw2-h', 'Ikut pair'));
    var byPair = {}, bySes = {};
    list.forEach(function (x) {
      var p = byPair[x.pair] = byPair[x.pair] || { w: 0, n: 0, pips: 0 };
      p.n++; if (x.status === 'tp') p.w++; p.pips += x.pips || 0;
      var sn = sessionOf(x.hour);
      var q = bySes[sn] = bySes[sn] || { w: 0, n: 0, pips: 0 };
      q.n++; if (x.status === 'tp') q.w++; q.pips += x.pips || 0;
    });
    b.appendChild(table(byPair, prettyPair));
    b.appendChild(el('p', 'tw2-h', 'Ikut sesi (Asia, London, New York)'));
    b.appendChild(table(bySes, function (k) { return k; }));

    var csv = el('button', 'tw2-btn-s', 'Muat turun CSV');
    csv.type = 'button';
    csv.addEventListener('click', function () { downloadCsv(list); });
    b.appendChild(csv);
  }

  function table(map, label) {
    var t = el('div', 'tw2-tbl');
    var h = el('div', 'tw2-tr head');
    ['', 'Win rate', 'Pips'].forEach(function (x) { h.appendChild(el('span', null, x)); });
    t.appendChild(h);
    Object.keys(map).sort(function (a, c) { return map[c].pips - map[a].pips; }).forEach(function (k) {
      var m = map[k];
      var r = el('div', 'tw2-tr');
      r.appendChild(el('span', null, label(k) + ' (' + m.n + ')'));
      r.appendChild(el('span', null, Math.round(m.w / m.n * 100) + '%'));
      r.appendChild(el('span', cls(m.pips), fmt(m.pips)));
      t.appendChild(r);
    });
    return t;
  }

  function equitySvg(pts) {
    var W = 320, H = 120, P = 8, NS = 'http://www.w3.org/2000/svg';
    var min = Math.min.apply(null, pts.concat([0])), max = Math.max.apply(null, pts.concat([0]));
    if (max === min) max = min + 1;
    var X = function (i) { return P + i * (W - 2 * P) / Math.max(1, pts.length - 1); };
    var Y = function (v) { return H - P - (v - min) / (max - min) * (H - 2 * P); };
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('width', '100%');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Graf pips kumulatif');
    var z = document.createElementNS(NS, 'line');
    z.setAttribute('x1', P); z.setAttribute('x2', W - P);
    z.setAttribute('y1', Y(0)); z.setAttribute('y2', Y(0));
    z.setAttribute('stroke', '#c9d3e3'); z.setAttribute('stroke-dasharray', '3 3');
    svg.appendChild(z);
    var line = document.createElementNS(NS, 'polyline');
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', pts[pts.length - 1] >= 0 ? '#2f9e5b' : '#c0392b');
    line.setAttribute('stroke-width', '2.5');
    line.setAttribute('stroke-linejoin', 'round');
    line.setAttribute('points', pts.map(function (v, i) { return X(i).toFixed(1) + ',' + Y(v).toFixed(1); }).join(' '));
    svg.appendChild(line);
    var tx = document.createElementNS(NS, 'text');
    tx.setAttribute('x', P); tx.setAttribute('y', 14);
    tx.setAttribute('text-anchor', 'start');
    tx.setAttribute('font-size', '12');
    tx.setAttribute('fill', '#5b6b85');
    tx.textContent = fmt(pts[pts.length - 1]) + ' pips';
    svg.appendChild(tx);
    return svg;
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

  function renderOpenBoard() {
    var act = allSignals().filter(function (x) { return x.status === 'active'; });
    var risk = parseFloat(ui.defRisk ? ui.defRisk.value : 1) || 0;
    if (!act.length) { ui.openBoard.textContent = 'Tiada signal terbuka sekarang.'; return; }
    ui.openBoard.textContent = act.length + ' signal terbuka (' +
      act.map(function (x) { return prettyPair(x.pair); }).join(', ') +
      '). Jika anda ikut semua, risiko serentak ≈ ' + (act.length * risk).toFixed(1) + '%.';
  }

  // ---------- Jurnal + had risiko ----------
  var J_KEY = 'tw2-journal';

  function buildJournal() {
    var b = ui.jr.body;
    var row = el('div', 'tw2-in');
    var lim = field('Had rugi harian (%)', 'input', { value: String(ls('tw2-limit', 3)) });
    var dr = field('Risiko lalai per trade (%)', 'input', { value: String(ls('tw2-risk', 1)) });
    ui.limit = lim.input; ui.defRisk = dr.input;
    row.appendChild(lim.wrap); row.appendChild(dr.wrap);
    b.appendChild(row);
    [ui.limit, ui.defRisk].forEach(function (n) {
      n.addEventListener('input', function () {
        lsSet('tw2-limit', parseFloat(ui.limit.value) || 0);
        lsSet('tw2-risk', parseFloat(ui.defRisk.value) || 0);
        renderJournal();
        renderOpenBoard();
      });
    });
    ui.riskBanner = el('div', 'tw2-banner');
    ui.jStats = el('p', 'tw2-note');
    ui.jList = el('div');
    b.appendChild(ui.riskBanner);
    b.appendChild(ui.jStats);
    b.appendChild(ui.jList);
    b.appendChild(el('p', 'tw2-note', 'Jurnal disimpan dalam browser ini sahaja.'));
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
    ui.riskBanner.className = 'tw2-banner' + (d.limit && remaining <= 0 ? ' warn' : '');
    ui.riskBanner.textContent = d.limit
      ? (remaining <= 0
          ? 'Had rugi harian dicapai atau terlebih risiko terbuka. Elak trade baharu hari ini.'
          : 'Baki risiko hari ini: ' + remaining.toFixed(1) + '% daripada had ' + d.limit + '%.')
      : 'Tetapkan had rugi harian untuk amaran automatik.';

    var closed = j.filter(function (e) { return entryR(e) != null; });
    var wins = closed.filter(function (e) { return e.result === 'tp'; }).length;
    var netR = closed.reduce(function (a, e) { return a + entryR(e); }, 0);
    var netP = closed.reduce(function (a, e) { return a + entryR(e) * e.risk; }, 0);
    ui.jStats.textContent = closed.length
      ? 'Trade ditutup: ' + closed.length + ' · menang ' + Math.round(wins / closed.length * 100) +
        '% · ' + fmt(netR) + 'R · ' + fmt(netP) + '% akaun'
      : 'Belum ada trade ditutup dalam jurnal.';

    ui.jList.textContent = '';
    j.slice().sort(function (a, b) { return b.ts - a.ts; }).slice(0, 20).forEach(function (e) {
      var r = el('div', 'tw2-j');
      r.appendChild(el('span', null, prettyPair(e.pair) + ' ' + e.side + ' · ' + e.risk + '%'));
      var sel = document.createElement('select');
      sel.setAttribute('aria-label', 'Keputusan trade');
      [['open', 'Terbuka'], ['tp', 'TP'], ['sl', 'SL'], ['be', 'BE']].forEach(function (o) {
        var op = document.createElement('option');
        op.value = o[0]; op.textContent = o[1];
        if (e.result === o[0]) op.selected = true;
        sel.appendChild(op);
      });
      sel.addEventListener('change', function () {
        var all = journal();
        all.forEach(function (x) { if (x.id === e.id) x.result = sel.value; });
        saveJournal(all);
      });
      var del = el('button', 'tw2-x', '×');
      del.type = 'button';
      del.setAttribute('aria-label', 'Padam entri');
      del.addEventListener('click', function () {
        saveJournal(journal().filter(function (x) { return x.id !== e.id; }));
      });
      r.appendChild(sel);
      r.appendChild(del);
      ui.jList.appendChild(r);
    });
  }

  function addJournal(d, btn) {
    var risk = parseFloat(ui.defRisk.value) || 1;
    var all = journal();
    var id = d.key || (d.pair + d.entry);
    if (all.some(function (x) { return x.id === id; })) {
      flash(btn, 'Sudah ada');
      return;
    }
    var st = dayStats();
    if (st.limit && risk > st.limit + st.net - st.open) {
      if (!confirm('Trade ini akan melebihi had rugi harian anda. Tetap tambah?')) return;
    }
    var rr = Math.abs(d.tp - d.entry) / Math.abs(d.entry - d.sl);
    all.push({ id: id, pair: d.code, side: d.side, risk: risk, rr: rr, result: 'open', ts: Date.now() });
    saveJournal(all);
    flash(btn, 'Ditambah');
  }

  function flash(btn, text) {
    var old = btn.getAttribute('data-label') || btn.textContent;
    btn.setAttribute('data-label', old);
    btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1400);
  }

  // ---------- Simulator ----------
  function buildSim() {
    var b = ui.sim.body;
    var row = el('div', 'tw2-in');
    var bal = field('Baki mula (USD)', 'input', { value: '1000' });
    var rsk = field('Risiko (%)', 'input', { value: '1' });
    row.appendChild(bal.wrap); row.appendChild(rsk.wrap);
    b.appendChild(row);
    var per = field('Tempoh', 'select');
    [['7', '7 hari'], ['30', '30 hari'], ['90', '90 hari']].forEach(function (o) {
      var op = document.createElement('option');
      op.value = o[0]; op.textContent = o[1];
      if (o[0] === '30') op.selected = true;
      per.input.appendChild(op);
    });
    b.appendChild(per.wrap);
    ui.simOut = el('div', 'tw2-banner', 'Memuatkan data…');
    b.appendChild(ui.simOut);
    b.appendChild(el('p', 'tw2-note', 'Simulasi teori: ikut semua signal, spread dan slippage diabaikan.'));
    ui.simIn = { bal: bal.input, rsk: rsk.input, per: per.input };
    Object.keys(ui.simIn).forEach(function (k) { ui.simIn[k].addEventListener('input', runSim); });
  }

  function runSim() {
    if (!ui.simIn) return;
    var start = parseFloat(ui.simIn.bal.value), risk = parseFloat(ui.simIn.rsk.value);
    var days = parseInt(ui.simIn.per.value, 10);
    if (!(start > 0) || !(risk > 0)) { ui.simOut.textContent = 'Masukkan baki dan risiko yang sah.'; return; }
    var list = closedSignals(days), used = 0, skipped = 0;
    var bal = start, peak = start, dd = 0;
    list.forEach(function (x) {
      if (typeof x.r !== 'number') { skipped++; return; }
      used++;
      bal *= 1 + risk / 100 * x.r;
      if (bal > peak) peak = bal;
      var cur = (peak - bal) / peak * 100;
      if (cur > dd) dd = cur;
    });
    if (!used) { ui.simOut.textContent = 'Belum ada data R (nisbah untung/rugi) dalam tempoh ini.'; return; }
    var ret = (bal / start - 1) * 100;
    ui.simOut.textContent = '$' + bal.toFixed(2) + ' (' + fmt(ret) + '%) · drawdown maksimum ' +
      dd.toFixed(1) + '% · ' + used + ' signal' + (skipped ? ' (' + skipped + ' tiada data R)' : '');
  }

  // ---------- Pasaran ----------
  var SESS = [
    ['Sydney', 21, 6], ['Tokyo', 0, 9], ['London', 7, 16], ['New York', 12, 21]
  ];
  var BEST = [
    ['EUR/USD, GBP/USD', 'London dan New York'],
    ['USD/JPY', 'Tokyo dan New York'],
    ['AUD/USD', 'Sydney dan Tokyo'],
    ['USD/CAD', 'New York'],
    ['XAU/USD', 'London dan New York']
  ];

  function buildMarket() {
    var b = ui.mkt.body;
    ui.sessBox = el('div');
    ui.strBox = el('div');
    ui.evBox = el('div');
    b.appendChild(ui.sessBox);
    b.appendChild(ui.strBox);
    b.appendChild(ui.evBox);
    renderSessions();
    setInterval(renderSessions, 30000);
  }

  function renderSessions() {
    var h = new Date().getUTCHours();
    var box = ui.sessBox;
    box.textContent = '';
    box.appendChild(el('p', 'tw2-h', 'Sesi pasaran sekarang'));
    var open = [];
    SESS.forEach(function (s) {
      var on = s[1] < s[2] ? (h >= s[1] && h < s[2]) : (h >= s[1] || h < s[2]);
      if (on) open.push(s[0]);
      var r = el('div');
      var dot = el('span', 'tw2-dot' + (on ? ' on' : ''));
      r.appendChild(dot);
      r.appendChild(document.createTextNode(s[0] + (on ? ' · buka' : ' · tutup')));
      r.style.fontSize = '14px';
      r.style.padding = '3px 0';
      box.appendChild(r);
    });
    if (open.indexOf('London') > -1 && open.indexOf('New York') > -1) {
      box.appendChild(el('p', 'tw2-note', 'London dan New York bertindih: biasanya paling aktif.'));
    }
    box.appendChild(el('p', 'tw2-h', 'Masa sesuai ikut pair'));
    BEST.forEach(function (x) {
      var p = el('p', 'tw2-note', x[0] + ': ' + x[1]);
      box.appendChild(p);
    });
  }

  function renderMarketData() {
    var s = window.TWStatus || {};
    ui.strBox.textContent = '';
    if (s.strength) {
      ui.strBox.appendChild(el('p', 'tw2-h', 'Kekuatan mata wang'));
      var keys = Object.keys(s.strength);
      var mx = Math.max.apply(null, keys.map(function (k) { return Math.abs(s.strength[k]); })) || 1;
      keys.sort(function (a, c) { return s.strength[c] - s.strength[a]; }).forEach(function (k) {
        var v = s.strength[k];
        var row = el('div', 'tw2-bar');
        row.appendChild(el('span', null, k));
        var tr = el('div', 'tw2-track');
        var f = el('div', 'tw2-fill');
        var w = Math.abs(v) / mx * 50;
        f.style.width = w + '%';
        f.style.left = v >= 0 ? '50%' : (50 - w) + '%';
        f.style.background = v >= 0 ? '#2f9e5b' : '#c0392b';
        tr.appendChild(f);
        row.appendChild(tr);
        ui.strBox.appendChild(row);
      });
    }
    ui.evBox.textContent = '';
    if (s.events && s.events.length) {
      ui.evBox.appendChild(el('p', 'tw2-h', 'Sesi live dan acara Max'));
      s.events.forEach(function (ev) {
        var p = el('p', 'tw2-note tw2-ev');
        p.appendChild(document.createTextNode((ev.date || '') + ' · ' + (ev.title || '') + ' '));
        if (ev.url && /^https?:\/\//.test(ev.url)) {
          var a = el('a', null, 'Buka');
          a.href = ev.url; a.target = '_blank'; a.rel = 'noopener';
          p.appendChild(a);
        }
        ui.evBox.appendChild(p);
      });
    }
  }

  // ---------- Tetapan ----------
  function filterSelects() {
    return document.querySelectorAll('#tw-bar .tw-filters select');
  }

  function buildSettings() {
    var b = ui.set.body;
    var chips = el('div', 'tw2-chips');

    var dark = el('button', 'tw2-chip', 'Tema gelap');
    dark.type = 'button';
    var applyDark = function (on) {
      document.documentElement.classList.toggle('tw-dark', on);
      dark.setAttribute('aria-pressed', String(on));
      lsSet('tw2-dark', on);
    };
    dark.addEventListener('click', function () { applyDark(!document.documentElement.classList.contains('tw-dark')); });
    applyDark(!!ls('tw2-dark', false));

    var simple = el('button', 'tw2-chip', 'Mod mudah');
    simple.type = 'button';
    var applySimple = function (on) {
      var c = chartsEl();
      if (c) c.style.display = on ? 'none' : '';
      simple.setAttribute('aria-pressed', String(on));
      lsSet('tw2-simple', on);
    };
    simple.addEventListener('click', function () { applySimple(simple.getAttribute('aria-pressed') !== 'true'); });
    ui.applySimple = applySimple;
    simple.setAttribute('aria-pressed', 'false');

    chips.appendChild(dark);
    chips.appendChild(simple);
    b.appendChild(chips);
    b.appendChild(el('p', 'tw2-note', 'Mod mudah menyembunyikan carta supaya hanya signal dipaparkan.'));

    b.appendChild(el('p', 'tw2-h', 'Feed saya'));
    var row = el('div', 'tw2-chips');
    var save = el('button', 'tw2-btn-s', 'Simpan penapis semasa');
    var use = el('button', 'tw2-btn-s', 'Guna penapis saya');
    save.type = 'button'; use.type = 'button';
    save.addEventListener('click', function () {
      var s = filterSelects();
      if (s.length < 3) return;
      lsSet('tw2-feed', { pair: s[0].value, side: s[1].value, type: s[2].value });
      flash(save, 'Disimpan');
    });
    use.addEventListener('click', function () { applyFeed(); flash(use, 'Digunakan'); });
    row.appendChild(save); row.appendChild(use);
    b.appendChild(row);
    b.appendChild(el('p', 'tw2-note', 'Penapis ini dipakai automatik setiap kali anda buka halaman. Untuk notifikasi mengikut pair, guna topik Telegram.'));
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
    if (!ui.perf) return;
    enhanceCards();
    var sig = JSON.stringify(window.TWStatus || {});
    if (sig !== lastSig) {
      lastSig = sig;
      renderPerf();
      renderMarketData();
      renderOpenBoard();
      runSim();
    }
    if (!feedApplied) {
      feedApplied = true;
      applyFeed();
      if (ls('tw2-simple', false) && ui.applySimple) ui.applySimple(true);
      renderJournal();
    }
  });
})();
