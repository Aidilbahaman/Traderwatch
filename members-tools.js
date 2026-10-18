/*!
 * TraderWatch members-tools.js
 * Pasang: letak tag script dengan src="members-tools.js" dan atribut defer
 * dalam members.html, sebelum penutup body.
 *
 * Ciri: penapis signal, butang copy, status TP/SL, statistik 30 hari,
 *       lot size calculator (+ butang "Kira lot" pada setiap signal).
 * Skrip ini baca kad signal yang sudah dipaparkan, jadi tak perlu ubah
 * kod sedia ada. Status dibaca daripada signal-status.json (dikemas kini
 * oleh Hermes agent).
 */
(function () {
  'use strict';

  // ---------- Tetapan ----------
  var CONFIG = {
    statusUrl: 'signal-status.json',
    maxOnly: false,         // false = aktif untuk Pro dan Max; Free tidak mendapat toolkit
    minPlan: 'pro',         // plan minimum yang layak
    statsDays: 30
  };

  var PAIRS = {
    EURUSD: { pip: 0.0001, val: function () { return 10; } },
    GBPUSD: { pip: 0.0001, val: function () { return 10; } },
    AUDUSD: { pip: 0.0001, val: function () { return 10; } },
    USDJPY: { pip: 0.01,   val: function (p) { return 1000 / p; } },
    USDCAD: { pip: 0.0001, val: function (p) { return 10 / p; } },
    XAUUSD: { pip: 0.1,    val: function () { return 10; } }
  };

  var STATUS_LABEL = {
    active: 'Active', tp: 'TP hit', sl: 'SL hit', expired: 'Tamat', cancelled: 'Dibatalkan'
  };

  var statusData = null;      // dimuat daripada JSON
  var scheduled = false;

  // ---------- CSS ----------
  var css = [
    '.tw-bar{display:grid;gap:10px;margin:0 0 16px}',
    '.tw-filters{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}',
    '.tw-filters select{font:inherit;font-size:15px;color:#1b2a4a;background:#fff;border:1px solid #dfe6f0;border-radius:10px;padding:10px 8px;width:100%;min-width:0}',
    '.tw-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}',
    '.tw-stat{background:#fff;border:1px solid #dfe6f0;border-radius:12px;padding:10px 12px}',
    '.tw-stat b{display:block;font-size:20px;color:#1b2a4a}',
    '.tw-stat span{font-size:12px;color:#7a889e}',
    '.tw-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:12px}',
    '.tw-btn{font:inherit;font-size:14px;font-weight:600;color:#1b2a4a;background:#eef3fb;border:0;border-radius:999px;padding:8px 14px;cursor:pointer}',
    '.tw-btn:active{transform:scale(.97)}',
    '.tw-btn:focus-visible,.tw-filters select:focus-visible,.tw-calc input:focus-visible,.tw-calc select:focus-visible{outline:2px solid #3d6fc4;outline-offset:2px}',
    '.tw-rr{font-size:13px;color:#5b6b85;margin-left:auto}',
    '.tw-badge{display:inline-block;font-size:12px;font-weight:700;border-radius:999px;padding:4px 10px;margin-left:8px}',
    '.tw-badge.active{background:#e6eefb;color:#2c5aa8}',
    '.tw-badge.tp{background:#e3f4e8;color:#23703f}',
    '.tw-badge.sl{background:#fdecec;color:#a63232}',
    '.tw-badge.expired,.tw-badge.cancelled{background:#eceff3;color:#6a768a}',
    '.tw-empty{text-align:center;color:#7a889e;font-size:14px;padding:12px 0}',
    '.tw-calc{background:#fff;border:1px solid #dfe6f0;border-radius:14px;padding:4px 14px}',
    '.tw-calc summary{cursor:pointer;font-weight:700;color:#1b2a4a;padding:10px 0;font-size:16px}',
    '.tw-calc-body{display:grid;gap:12px;padding:4px 0 14px}',
    '.tw-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}',
    '.tw-field{display:grid;gap:5px;font-size:13px;color:#5b6b85}',
    '.tw-field input,.tw-field select{font:inherit;font-size:16px;color:#1b2a4a;background:#f6f8fc;border:1px solid #dfe6f0;border-radius:10px;padding:10px;width:100%;box-sizing:border-box}',
    '.tw-out{background:#eef3fb;border-radius:12px;padding:12px;font-size:14px;color:#1b2a4a;line-height:1.5}',
    '.tw-out b{display:block;font-size:24px}',
    '.tw-out.err{background:#fdecec;color:#a63232}',
    '.tw-note{margin:0;font-size:12px;color:#7a889e}'
  ].join('');
  var styleEl = document.createElement('style');
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // ---------- Pembantu ----------
  function isEligible() {
    var text = document.body.innerText || '';
    return /\b(Pro|Max) Member\b/i.test(text);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // Cari semua kad signal: naik dari teks "Posted ..." sehingga
  // ancestor yang mengandungi dua "Posted" (kad = satu tahap di bawahnya).
  function findCards() {
    var root = findSignalsRoot();
    if (!root) return [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var cards = [], seen = [];
    var node;
    while ((node = walker.nextNode())) {
      if (!/^\s*Posted\s/i.test(node.nodeValue)) continue;
      var cur = node.parentElement, prev = cur;
      while (cur && cur !== root) {
        var n = (cur.innerText.match(/Posted\s/gi) || []).length;
        if (n > 1) break;
        prev = cur;
        cur = cur.parentElement;
      }
      if (prev && seen.indexOf(prev) === -1) {
        seen.push(prev);
        cards.push(prev);
      }
    }
    return cards;
  }

  function findSignalsRoot() {
    return document.getElementById('signals') ||
      (function () {
        var hs = document.querySelectorAll('h1,h2,h3');
        for (var i = 0; i < hs.length; i++) {
          if (/^\s*signals\s*$/i.test(hs[i].textContent)) {
            return hs[i].parentElement;
          }
        }
        return null;
      })();
  }

  function findSignalsHeading() {
    var hs = document.querySelectorAll('h1,h2,h3');
    for (var i = 0; i < hs.length; i++) {
      if (/^\s*signals\s*$/i.test(hs[i].textContent)) return hs[i];
    }
    return null;
  }

  function parseCard(card) {
    if (card.dataset && card.dataset.key) {
      return {
        pair: String(card.dataset.pair || '').replace(/^([A-Z]{3})([A-Z]{3})$/, '$1/$2'),
        code: String(card.dataset.pair || '').replace(/[^A-Z]/g, ''),
        side: card.dataset.side || '',
        type: card.dataset.type === 'M1' ? 'scalping' : (card.dataset.type || ''),
        entry: parseFloat(card.dataset.entry),
        sl: parseFloat(card.dataset.sl),
        tp: parseFloat(card.dataset.tp),
        key: card.dataset.key
      };
    }
    var t = card.innerText || '';
    var pair = (t.match(/\b([A-Z]{3})\/([A-Z]{3})\b/) || []);
    if (!pair[0]) return null;
    var num = function (label) {
      var m = t.match(new RegExp(label + '\\s*([0-9]+(?:\\.[0-9]+)?)'));
      return m ? parseFloat(m[1]) : null;
    };
    var side = (t.match(/\b(BUY|SELL)\b/) || [])[1];
    var tf = (t.match(/\b(M1|M5|M15|M30|H1|H4|D1)\b/) || [])[1] || '';
    var scalp = /scalping/i.test(t);
    var posted = t.match(/Posted\s+(\d{2})\/(\d{2})\/(\d{4}),?\s+(\d{2}):(\d{2}):(\d{2})/);
    var key = null;
    if (posted) {
      key = pair[1] + pair[2] + '_' + posted[3] + posted[2] + posted[1] +
        '_' + posted[4] + posted[5] + posted[6];
    }
    return {
      pair: pair[1] + '/' + pair[2],
      code: pair[1] + pair[2],
      side: side,
      type: scalp ? 'scalping' : tf,
      entry: num('Entry'),
      sl: num('SL'),
      tp: num('TP'),
      key: key
    };
  }

  function decimals(n) {
    var s = String(n);
    return s.indexOf('.') === -1 ? 0 : s.split('.')[1].length;
  }

  function copyText(text, btn) {
    var done = function () {
      var old = btn.textContent;
      btn.textContent = 'Disalin';
      setTimeout(function () { btn.textContent = old; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else { fallback(); }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  // ---------- Kad signal ----------
  function enhanceCard(card) {
    if (card.getAttribute('data-tw') === '1') return;
    var d = parseCard(card);
    if (!d || d.entry == null || d.sl == null || d.tp == null) return;
    card.setAttribute('data-tw', '1');
    card._tw = d;

    var risk = Math.abs(d.entry - d.sl);
    var rr = risk ? (Math.abs(d.tp - d.entry) / risk) : 0;

    var actions = el('div', 'tw-actions');
    var copy = el('button', 'tw-btn', 'Copy');
    copy.type = 'button';
    copy.addEventListener('click', function () {
      copyText(
        d.pair + ' ' + d.side + '\nEntry ' + d.entry + '\nSL ' + d.sl + '\nTP ' + d.tp,
        copy
      );
    });
    var lot = el('button', 'tw-btn', 'Kira lot');
    lot.type = 'button';
    lot.addEventListener('click', function () {
      fillCalc(d.code, d.entry, d.sl);
    });
    actions.appendChild(copy);
    actions.appendChild(lot);
    if (rr) actions.appendChild(el('span', 'tw-rr', 'R:R 1:' + rr.toFixed(1)));
    card.appendChild(actions);

    var badge = el('span', 'tw-badge');
    badge.hidden = true;
    badge.setAttribute('data-tw-badge', '1');
    var host = card.querySelector('[class*="badge"],[class*="tag"],[class*="side"]');
    // letak badge di sebelah tajuk pair
    var title = findFirstTextEl(card, d.pair);
    (title || card).appendChild(badge);
  }

  function findFirstTextEl(card, text) {
    var all = card.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      if (all[i].children.length === 0 && all[i].textContent.trim() === text) {
        return all[i];
      }
    }
    return null;
  }

  function applyStatus() {
    if (!statusData || !statusData.signals) return;
    var cards = document.querySelectorAll('[data-tw="1"]');
    for (var i = 0; i < cards.length; i++) {
      var c = cards[i], d = c._tw;
      var b = c.querySelector('[data-tw-badge="1"]');
      if (!b || !d.key) continue;
      var s = statusData.signals[d.key];
      if (!s || !STATUS_LABEL[s.status]) { b.hidden = true; continue; }
      var label = STATUS_LABEL[s.status];
      if ((s.status === 'tp' || s.status === 'sl') && typeof s.pips === 'number') {
        label += ' ' + (s.pips > 0 ? '+' : '') + s.pips.toFixed(1) + ' pips';
      }
      b.textContent = label;
      b.className = 'tw-badge ' + s.status;
      b.hidden = false;
      c._tw.status = s.status;
    }
  }

  // ---------- Bar penapis + statistik ----------
  var filterEls = {};
  var statEls = {};

  function buildBar() {
    if (document.getElementById('tw-bar')) return;
    var heading = findSignalsHeading();
    if (!heading) return;

    var bar = el('div', 'tw-bar');
    bar.id = 'tw-bar';

    var stats = el('div', 'tw-stats');
    [['win', 'Win rate'], ['pips', 'Jumlah pips'], ['count', 'Signal ditutup']].forEach(function (p) {
      var box = el('div', 'tw-stat');
      var b = el('b', null, '–');
      box.appendChild(b);
      box.appendChild(el('span', null, p[1] + ' (' + CONFIG.statsDays + ' hari)'));
      statEls[p[0]] = b;
      stats.appendChild(box);
    });
    bar.appendChild(stats);

    var f = el('div', 'tw-filters');
    f.appendChild(makeSelect('pair', [['', 'Semua pair']].concat(
      Object.keys(PAIRS).map(function (k) { return [k.slice(0, 3) + '/' + k.slice(3), k.slice(0, 3) + '/' + k.slice(3)]; })
    )));
    f.appendChild(makeSelect('side', [['', 'BUY/SELL'], ['BUY', 'BUY'], ['SELL', 'SELL']]));
    f.appendChild(makeSelect('type', [['', 'Semua jenis'], ['scalping', 'Scalping'], ['H1', 'H1']]));
    bar.appendChild(f);

    bar.appendChild(buildCalc());
    heading.insertAdjacentElement('afterend', bar);
  }

  function makeSelect(name, opts) {
    var s = document.createElement('select');
    s.setAttribute('aria-label', name);
    opts.forEach(function (o) {
      var op = document.createElement('option');
      op.value = o[0];
      op.textContent = o[1];
      s.appendChild(op);
    });
    s.addEventListener('change', applyFilters);
    filterEls[name] = s;
    return s;
  }

  function applyFilters() {
    var cards = document.querySelectorAll('[data-tw="1"]');
    var shown = 0;
    for (var i = 0; i < cards.length; i++) {
      var d = cards[i]._tw;
      var ok = (!filterEls.pair.value || d.pair === filterEls.pair.value) &&
               (!filterEls.side.value || d.side === filterEls.side.value) &&
               (!filterEls.type.value || d.type === filterEls.type.value) &&
               (!window.TW_ONLY_STARRED || cards[i].getAttribute('data-star') === '1');
      cards[i].style.display = ok ? '' : 'none';
      if (ok) shown++;
    }
    var bar = document.getElementById('tw-bar');
    var empty = document.getElementById('tw-empty');
    if (cards.length && !shown) {
      if (!empty) {
        empty = el('div', 'tw-empty', 'Tiada signal sepadan dengan penapis ini.');
        empty.id = 'tw-empty';
        bar.appendChild(empty);
      }
    } else if (empty) { empty.remove(); }
  }

  function renderStats() {
    if (!statusData || !statusData.signals || !statEls.win) return;
    var cutoff = Date.now() - CONFIG.statsDays * 86400000;
    var wins = 0, losses = 0, pips = 0;
    Object.keys(statusData.signals).forEach(function (k) {
      var s = statusData.signals[k];
      var m = k.match(/_(\d{4})(\d{2})(\d{2})_/);
      if (m && new Date(+m[1], +m[2] - 1, +m[3]).getTime() < cutoff) return;
      if (s.status === 'tp') { wins++; pips += s.pips || 0; }
      else if (s.status === 'sl') { losses++; pips += s.pips || 0; }
    });
    var total = wins + losses;
    statEls.win.textContent = total ? Math.round(wins / total * 100) + '%' : '–';
    statEls.pips.textContent = total ? (pips > 0 ? '+' : '') + pips.toFixed(1) : '–';
    statEls.count.textContent = String(total);
  }

  // ---------- Lot calculator ----------
  var calc = {};

  function buildCalc() {
    var det = document.createElement('details');
    det.className = 'tw-calc';
    det.id = 'tw-calc';
    det.appendChild(el('summary', null, 'Lot size calculator'));
    var body = el('div', 'tw-calc-body');

    var pairField = field('Pair', 'select');
    Object.keys(PAIRS).forEach(function (k) {
      var o = document.createElement('option');
      o.value = k;
      o.textContent = k.slice(0, 3) + '/' + k.slice(3);
      pairField.input.appendChild(o);
    });
    calc.pair = pairField.input;
    body.appendChild(pairField.wrap);

    var r1 = el('div', 'tw-row');
    var bal = field('Baki akaun (USD)', 'input', { value: '1000' });
    var rsk = field('Risiko (%)', 'input', { value: '1' });
    calc.bal = bal.input; calc.risk = rsk.input;
    r1.appendChild(bal.wrap); r1.appendChild(rsk.wrap);
    body.appendChild(r1);

    var r2 = el('div', 'tw-row');
    var en = field('Entry', 'input', {});
    var sl = field('Stop loss', 'input', {});
    calc.entry = en.input; calc.sl = sl.input;
    r2.appendChild(en.wrap); r2.appendChild(sl.wrap);
    body.appendChild(r2);

    calc.out = el('div', 'tw-out', 'Masukkan Entry dan SL untuk kira lot.');
    calc.out.setAttribute('aria-live', 'polite');
    body.appendChild(calc.out);
    body.appendChild(el('p', 'tw-note', 'Anggaran sahaja. Nilai pip bergantung pada broker dan kadar tukaran.'));
    det.appendChild(body);

    try {
      var saved = JSON.parse(localStorage.getItem('tw-calc') || '{}');
      if (saved.bal) calc.bal.value = saved.bal;
      if (saved.risk) calc.risk.value = saved.risk;
    } catch (e) {}

    [calc.pair, calc.bal, calc.risk, calc.entry, calc.sl].forEach(function (n) {
      n.addEventListener('input', runCalc);
    });
    [calc.bal, calc.risk].forEach(function (n) {
      n.addEventListener('change', function () {
        try {
          localStorage.setItem('tw-calc', JSON.stringify({ bal: calc.bal.value, risk: calc.risk.value }));
        } catch (e) {}
      });
    });
    return det;
  }

  function field(label, kind, attrs) {
    var wrap = el('label', 'tw-field');
    wrap.appendChild(el('span', null, label));
    var input = document.createElement(kind);
    if (kind === 'input') {
      input.type = 'number';
      input.setAttribute('inputmode', 'decimal');
      input.step = 'any';
      input.min = '0';
      if (attrs && attrs.value) input.value = attrs.value;
    }
    wrap.appendChild(input);
    return { wrap: wrap, input: input };
  }

  function runCalc() {
    var cfg = PAIRS[calc.pair.value];
    var bal = parseFloat(calc.bal.value);
    var risk = parseFloat(calc.risk.value);
    var entry = parseFloat(calc.entry.value);
    var sl = parseFloat(calc.sl.value);
    calc.out.classList.remove('err');
    if (!entry || !sl) { calc.out.textContent = 'Masukkan Entry dan SL untuk kira lot.'; return; }
    if (entry === sl) { calc.out.classList.add('err'); calc.out.textContent = 'Entry dan SL tidak boleh sama.'; return; }
    if (!(bal > 0) || !(risk > 0)) { calc.out.classList.add('err'); calc.out.textContent = 'Baki dan risiko mesti lebih daripada 0.'; return; }
    var pips = Math.abs(entry - sl) / cfg.pip;
    var riskUsd = bal * risk / 100;
    var lots = Math.floor(riskUsd / (pips * cfg.val(entry)) * 100) / 100;
    calc.out.innerHTML = '';
    calc.out.appendChild(el('b', null, lots.toFixed(2) + ' lot'));
    calc.out.appendChild(document.createTextNode(
      'Risiko $' + riskUsd.toFixed(2) + ' (' + risk + '%) · SL ' + pips.toFixed(1) + ' pips'
    ));
  }

  function fillCalc(code, entry, sl) {
    var det = document.getElementById('tw-calc');
    if (!det) return;
    det.open = true;
    calc.pair.value = code;
    calc.entry.value = entry;
    calc.sl.value = sl;
    runCalc();
    document.dispatchEvent(new Event('tw-calc-open'));
    det.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // ---------- Kitaran utama ----------
  function run() {
    scheduled = false;
    if (!isEligible()) return;
    buildBar();
    findCards().forEach(enhanceCard);
    applyStatus();
    applyFilters();
    renderStats();
    document.dispatchEvent(new Event('tw-run'));
  }

  document.addEventListener('tw-refilter', function () { applyFilters(); });

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    setTimeout(run, 250);
  }

  function loadStatus() {
    fetch(CONFIG.statusUrl + '?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { statusData = j; window.TWStatus = j; schedule(); })
      .catch(function () {});
  }

  new MutationObserver(function (muts) {
    // abaikan perubahan yang kita buat sendiri
    for (var i = 0; i < muts.length; i++) {
      var t = muts[i].target;
      var elt = t.nodeType === 1 ? t : t.parentElement;
      if (elt && elt.closest && (elt.closest('#tw-bar') || elt.closest('[data-tw="1"]'))) continue;
      schedule();
      return;
    }
  }).observe(document.body, { childList: true, subtree: true });

  loadStatus();
  setInterval(loadStatus, 60000);
  schedule();
})();
