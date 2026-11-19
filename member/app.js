/* TraderWatch Member PWA — app.js
 * Vanilla JS, tiada framework. Routing hash (termasuk #/signal?id=N),
 * data offline-first (SW), install flow, chart TWChart + TradingView lazy-mount,
 * signal-first home, auth SEBENAR melalui auth.js (window.TWAuth + 'tw-auth-ready'),
 * seksyen "Signal anda" (RPC get_signals), kalkulator saiz posisi,
 * skrin prestasi (#/performance) — kiraan R client-side dari signal-status.json.
 */
(function () {
  'use strict';

  var $ = function (sel, el) { return (el || document).querySelector(sel); };
  var $$ = function (sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); };

  var ROUTES = ['home', 'markets', 'tools', 'learn', 'account', 'signal', 'performance'];
  var MYT = 'Asia/Kuala_Lumpur';
  var LOGIN_URL = '../login.html?next=' + encodeURIComponent('/member/');

  var state = {
    route: 'home',
    online: navigator.onLine,
    signal: null,
    status: null,
    dataFromCache: false,
    chartSymbol: 'OANDA:XAUUSD',
    chartMounted: false,
    deferredPrompt: null,
    swReg: null,
    toastTimer: null,
    marketMode: 'app',
    barsCache: {},
    detail: null,
    detailBars: null,
    detailIsRpc: false,
    signalQuery: {},
    marketChart: null,
    signalChart: null,
    perfDays: 0,
    perfChart: null
  };

  /* ---------- Ikon SVG (inline, stroke currentColor) ---------- */

  var ICONS = {
    radar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1" fill="currentColor"/><path d="M12 12 18.5 5.5"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v4h-4"/></svg>',
    lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    wifiOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 8.5a15 15 0 0 1 20 0"/><path d="M5.5 12.5a10 10 0 0 1 13 0"/><path d="M9 16.5a5 5 0 0 1 6 0"/><circle cx="12" cy="20" r="1" fill="currentColor"/><path d="m3 3 18 18"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 6 12 12"/><path d="m18 6-12 12"/></svg>',
    calc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8.5 7h7"/><path d="M8.5 12h.01"/><path d="M12 12h.01"/><path d="M15.5 12h.01"/><path d="M8.5 16h.01"/><path d="M12 16h.01"/><path d="M15.5 16h.01"/></svg>'
  };

  /* ---------- Utiliti ---------- */

  function fmtPair(raw) {
    var p = String(raw || '').toUpperCase().replace(/[^A-Z]/g, '');
    if (p.length === 6) return p.slice(0, 3) + '/' + p.slice(3);
    return p || '—';
  }

  function fmtNum(n, digits) {
    if (typeof n !== 'number' || !isFinite(n)) return '—';
    return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  // Desimal ikut magnitud harga: XAU/XAG 2, BTC 0.
  function priceDigits(price) {
    var p = Math.abs(price || 0);
    if (p >= 10000) return 0;
    if (p >= 1000) return 2;
    if (p >= 100) return 1;
    return 2;
  }

  function fmtPrice(n) {
    if (typeof n !== 'number' || !isFinite(n)) return '—';
    return fmtNum(n, priceDigits(n));
  }

  // ts UTC naive → Date (tambah Z); ISO beroffset dikekalkan.
  function toDate(ts) {
    if (!ts) return null;
    var s = String(ts);
    if (/(Z|[+-]\d{2}:?\d{2})$/.test(s)) return new Date(s);
    return new Date(s + 'Z');
  }

  function fmtDateShort(iso) {
    try {
      var d = iso instanceof Date ? iso : toDate(iso);
      return new Intl.DateTimeFormat('ms-MY', {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
        hour12: false, timeZone: MYT
      }).format(d);
    } catch (e) { return ''; }
  }

  function fmtTime(iso) {
    try {
      var d = iso instanceof Date ? iso : toDate(iso);
      return new Intl.DateTimeFormat('ms-MY', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: MYT
      }).format(d);
    } catch (e) { return ''; }
  }

  function toast(msg) {
    var el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () { el.hidden = true; }, 3500);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function pairSlug(pair) {
    return String(pair || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  // isFinite(null) = true — guard nombor sebenar untuk paras signal (tp2:null dll).
  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  /* ---------- Prestasi: kiraan rasmi (metodologi dashboard member) ---------- */
  /* BLOCK:perf-start — fungsi tulen di antara penanda ini boleh diuji dalam node.
   * Hanya 'tp'/'sl' = decided (win rate = TP/(TP+SL)). 'collected' = exit manual,
   * diasingkan. expired/cancelled/active/pending BUKAN kalah. Agregat guna R
   * (unit pips/usd bercampur). Cutoff statsSince: enjin disahkan 19 Okt 2026. */
  var PERF_SINCE = '2026-10-19T08:00:00+08:00';

  function computePerformance(signals, opts) {
    opts = opts || {};
    var now = typeof opts.now === 'number' ? opts.now : Date.now();
    var since = Date.parse(opts.since || PERF_SINCE);
    if (!isFinite(since)) since = 0;
    var days = opts.days > 0 ? opts.days : 0; // 0 = semua
    var windowStart = days ? Math.max(since, now - days * 86400000) : since;

    var out = {
      decided: 0, tp: 0, sl: 0, collected: 0, expired: 0, active: 0, pending: 0, cancelled: 0,
      winRate: null, netR: 0, avgWinR: null, maxDrawdownR: 0,
      daily: [], perPair: [], windowStart: windowStart, dataStart: null, now: now
    };
    if (!signals || typeof signals !== 'object') return out;

    var dayFmt = null;
    try {
      dayFmt = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Kuala_Lumpur', year: 'numeric', month: '2-digit', day: '2-digit'
      });
    } catch (e) { /* fallback ISO di bawah */ }

    var dayR = {}, pairs = {}, winRs = [], dataStart = null;
    Object.keys(signals).forEach(function (id) {
      var s = signals[id];
      if (!s || typeof s !== 'object') return;
      var st = String(s.status || '').toLowerCase();
      // Status semasa (tiada tarikh tutup) sentiasa dikira — ia masih berjalan.
      if (st === 'active' || st === 'pending') { out[st]++; return; }
      // Tarikh signal = masa siaran dari key (PAIR_YYYYMMDD_HHMMSS, MYT).
      // Prestasi dikira dari AWAL signal diterbitkan — bukan tarikh tutup
      // batch (signal lama 19-25 Okt ditutup serentak pada 26 Okt).
      var km = /^([A-Z]{6})_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
      var t = km ? Date.UTC(+km[2], +km[3] - 1, +km[4], +km[5], +km[6], +km[7]) - 8 * 3600000 : NaN;
      if (!isFinite(t)) {
        var closedTs = s.entry_at || s.closed || s.expired_at || null;
        t = closedTs ? Date.parse(closedTs) : NaN;
      }
      if (!isFinite(t) || t < since) return; // rekod legacy diabaikan
      // Mula rekod decided global (untuk label tempoh jujur) — bebas window dipilih.
      if ((st === 'tp' || st === 'sl') && (dataStart === null || t < dataStart)) dataStart = t;
      if (t < windowStart) return; // luar tempoh yang dipilih
      if (st === 'collected' || st === 'expired' || st === 'cancelled') { out[st]++; return; }
      if (st !== 'tp' && st !== 'sl') return;

      var r = typeof s.r === 'number' && isFinite(s.r) ? s.r : 0;
      out.decided++; out[st]++;
      out.netR += r;
      if (st === 'tp') winRs.push(r);
      var pair = String(id.split('_')[0] || '').toUpperCase();
      if (!pairs[pair]) pairs[pair] = { pair: pair, tp: 0, sl: 0, netR: 0 };
      pairs[pair][st]++; pairs[pair].netR += r;
      var day = dayFmt ? dayFmt.format(new Date(t)) : new Date(t).toISOString().slice(0, 10);
      dayR[day] = (dayR[day] || 0) + r;
    });

    out.dataStart = dataStart;
    if (out.decided) out.winRate = 100 * out.tp / out.decided;
    if (winRs.length) {
      out.avgWinR = winRs.reduce(function (a, b) { return a + b; }, 0) / winRs.length;
    }
    // Siri harian MYT: [tarikh, R hari itu, R terkumpul]; drawdown = puncak→lembah.
    var cum = 0, peak = 0, dd = 0;
    Object.keys(dayR).sort().forEach(function (d) {
      cum += dayR[d];
      if (cum > peak) peak = cum;
      if (cum - peak < dd) dd = cum - peak;
      out.daily.push([d, dayR[d], cum]);
    });
    out.maxDrawdownR = dd;
    out.perPair = Object.keys(pairs).map(function (k) {
      var p = pairs[k];
      p.wr = p.tp + p.sl ? 100 * p.tp / (p.tp + p.sl) : null;
      return p;
    }).sort(function (a, b) { return b.netR - a.netR; });
    return out;
  }

  // Label tempoh JUJUR (corak periodLabel() members-tools-2.js): jika rekod
  // bermula lebih lewat daripada window, jangan claim "30 hari" penuh.
  function perfPeriodLabel(perf, days) {
    if (perf.dataStart !== null && perf.dataStart > perf.windowStart) {
      var n = Math.max(1, Math.ceil((perf.now - perf.dataStart) / 86400000));
      var label;
      try {
        label = new Intl.DateTimeFormat('ms-MY', {
          day: 'numeric', month: 'short', timeZone: 'Asia/Kuala_Lumpur'
        }).format(new Date(perf.dataStart));
      } catch (e) { label = new Date(perf.dataStart).toISOString().slice(5, 10); }
      return 'Sejak ' + label + ' · ' + n + ' hari';
    }
    return days ? days + ' hari' : 'Semua';
  }
  /* BLOCK:perf-end */

  function fmtR(n, digits) {
    if (typeof n !== 'number' || !isFinite(n)) return '—';
    var d = digits == null ? 2 : digits;
    var sign = n > 0 ? '+' : (n < 0 ? '−' : '');
    return sign + Math.abs(n).toFixed(d) + 'R';
  }

  /* ---------- Service worker ---------- */

  function registerSW() {
    if (!('serviceWorker' in navigator)) return;
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('./sw.js?v=20261120m11', { scope: './' })
        .then(function (reg) { state.swReg = reg; })
        .catch(function () { /* SW gagal daftar — app masih berfungsi online */ });
    });
  }

  /* ---------- Routing (hash + query) ---------- */

  function parseHash() {
    var h = location.hash || '';
    var m = /^#\/([a-z]+)/.exec(h);
    var route = m && ROUTES.indexOf(m[1]) !== -1 ? m[1] : 'home';
    var query = {};
    var qi = h.indexOf('?');
    if (qi !== -1) {
      h.slice(qi + 1).split('&').forEach(function (kv) {
        if (!kv) return;
        var p = kv.split('=');
        try { query[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || ''); }
        catch (e) { query[p[0]] = p[1] || ''; }
      });
    }
    return { route: route, query: query };
  }

  function navigate(route, query) {
    query = query || {};
    if (route !== 'signal' && state.route === route && $('.screen.active')) {
      // klik tab semasa: skrol ke atas
      $('#main').scrollTop = 0;
      return;
    }
    var prev = state.route;
    state.route = route;

    $$('.screen').forEach(function (sec) {
      var active = sec.getAttribute('data-route') === route;
      sec.hidden = !active;
      sec.classList.toggle('active', active);
    });

    $$('.tab').forEach(function (tab) {
      var active = tab.getAttribute('data-route') === route;
      tab.classList.toggle('active', active);
      if (active) tab.setAttribute('aria-current', 'page');
      else tab.removeAttribute('aria-current');
    });

    $('#main').scrollTop = 0;

    // Chart: lazy mount bila Markets dibuka, buang bila keluar
    if (route === 'markets') mountMarkets();
    else if (prev === 'markets') { unmountChart(); destroyMarketChart(); }

    if (route === 'signal') openSignal(query);
    else if (prev === 'signal') destroySignalChart();

    if (route === 'performance') renderPerformance();
    else if (prev === 'performance') destroyPerfChart();
  }

  function initRouting() {
    $$('.tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        location.hash = '#/' + tab.getAttribute('data-route');
      });
    });
    window.addEventListener('hashchange', function () {
      var p = parseHash();
      navigate(p.route, p.query);
    });
    var p = parseHash();
    navigate(p.route, p.query);
  }

  /* ---------- Data ---------- */

  function fetchJSON(url) {
    return fetch(url, { cache: 'no-cache' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
  }

  // Bars melalui fetch('data/...') supaya SW stale-while-revalidate berfungsi offline.
  // SW fallback boleh pulangkan JSON null — sahkan bentuk data.
  function fetchBars(slug) {
    if (state.barsCache[slug]) return Promise.resolve(state.barsCache[slug]);
    var file = 'data/bars-' + slug + '.json';
    return fetchJSON(file)
      .then(function (data) {
        if (!data || !Array.isArray(data.bars) || !data.bars.length) return null;
        state.barsCache[slug] = data;
        return data;
      })
      .catch(function () { return null; });
  }

  function latestClosedISO() {
    var signals = (state.status && state.status.signals) || {};
    var latest = null;
    Object.keys(signals).forEach(function (k) {
      var c = signals[k].closed;
      if (c && (!latest || new Date(c) > new Date(latest))) latest = c;
    });
    return latest;
  }

  function cacheTimestamp() {
    if (state.status && state.status.updated) return state.status.updated;
    return latestClosedISO();
  }

  function updateCacheBadges() {
    var stamp = cacheTimestamp();
    var text = 'Data cache' + (stamp ? ' · ' + fmtTime(stamp) : '');
    ['signalCacheBadge', 'resultsCacheBadge', 'perfCacheBadge'].forEach(function (id) {
      var el = $('#' + id);
      if (!el) return; // badge prestasi hanya wujud bila skrin prestasi dirender
      el.textContent = text;
      el.hidden = !state.dataFromCache;
    });
  }

  function loadData() {
    state.dataFromCache = !state.online;
    // landing-stats.json TIDAK disync ke member/ (feed internal) — tile "Signal anda"
    // datang dari RPC get_signals(), tile aktif dikira dari signal-status.json.
    return Promise.all([
      fetchJSON('data/landing-signal.json').catch(function () { return null; }),
      fetchJSON('data/signal-status.json').catch(function () { return null; })
    ]).then(function (results) {
      state.signal = results[0];
      state.status = results[1];
      renderStats();
      renderSignal();
      renderResults();
      renderHomePerf();
      if (state.route === 'performance') renderPerformance();
      if (state.route === 'signal' && state.detailIsRpc && state.signalQuery.id) {
        openRpcSignal(state.signalQuery.id); // merge status rasmi bila data tiba
      }
      updateCacheBadges();
    });
  }

  /* ---------- Auth sebenar (auth.js → window.TWAuth) ---------- */

  function twAuth() { return window.TWAuth || null; }
  function isGuest() { var a = twAuth(); return !(a && a.isMember); }

  function initials(name) {
    var parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return 'A';
    var s = parts[0].charAt(0);
    if (parts.length > 1) s += parts[parts.length - 1].charAt(0);
    return s.toUpperCase();
  }

  function renderModeChip() {
    var el = $('#modeChip');
    if (!el) return;
    var a = twAuth();
    if (a && a.isMember) {
      el.textContent = 'AHLI · ' + String(a.plan || 'free').toUpperCase();
      el.className = 'chip chip-lime';
    } else {
      el.textContent = 'TETAMU';
      el.className = 'chip chip-muted';
    }
  }

  function renderAvatar() {
    var btn = $('#avatarBtn');
    if (!btn) return;
    var a = twAuth();
    if (a && a.isMember) {
      btn.textContent = initials(a.profile && a.profile.name);
      btn.hidden = false;
    } else {
      btn.hidden = true;
    }
  }

  function renderProfile() {
    var card = $('#profileCard');
    if (!card) return;
    var a = twAuth();
    if (a && a.isMember) {
      var name = (a.profile && a.profile.name) || 'Ahli';
      var email = (a.session && a.session.user && a.session.user.email) || '';
      card.innerHTML =
        '<div class="avatar avatar-member" aria-hidden="true">' + esc(initials(name)) + '</div>' +
        '<div class="profile-body">' +
          '<h3>' + esc(name) + ' <span class="chip chip-plan-free">FREE</span></h3>' +
          (email ? '<p class="profile-email">' + esc(email) + '</p>' : '') +
          '<div class="btn-row">' +
            '<button class="btn btn-ghost btn-sm" id="signOutBtn" type="button">Log keluar</button>' +
          '</div>' +
        '</div>';
    } else {
      card.innerHTML =
        '<div class="avatar" aria-hidden="true">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 5-5.5 8-5.5s6.5 1.5 8 5.5"/></svg>' +
        '</div>' +
        '<div class="profile-body">' +
          '<h3>Log masuk ke akaun anda</h3>' +
          '<p>Log masuk untuk akses penuh signal, chart beranotasi dan dashboard.</p>' +
          '<div class="btn-row">' +
            '<a class="btn btn-primary btn-sm" href="' + LOGIN_URL + '">Log masuk</a>' +
          '</div>' +
        '</div>';
    }
    var planCard = $('#planCard');
    if (planCard) planCard.hidden = !(a && a.isMember);
  }

  /* ---------- Home: "Signal anda" (RPC get_signals, mod ahli sahaja) ---------- */

  function renderMySignals() {
    var card = $('#mySignalsCard');
    var list = $('#mySignalsList');
    if (!card || !list) return;
    var a = twAuth();
    if (!a || !a.isMember) { card.hidden = true; return; }
    card.hidden = false;

    var planChip = $('#mySignalsPlanChip');
    if (planChip) { planChip.textContent = 'TERKINI'; planChip.className = 'chip chip-muted'; }

    // Semua ahli FREE (tiada tiering). Papar signal TERKINI sahaja untuk setiap
    // pair; signal dah tutup (SL/TP/expired/cancelled) diarkibkan — tidak dipapar
    // di sini (ada dalam "Keputusan terkini" / Prestasi).
    var CLOSED = ['tp', 'sl', 'expired', 'cancelled', 'collected', 'closed', 'void'];
    var statusMap = (state.status && state.status.signals) || {};
    var byPair = {};
    (a.signals || []).forEach(function (s) {
      var key = statusKeyFor(s.pair, s.posted_at);
      var st = key && statusMap[key] ? String(statusMap[key].status || '').toLowerCase() : '';
      if (CLOSED.indexOf(st) !== -1) return; // arkib: signal dah tutup
      var p = String(s.pair || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
      if (!p) return;
      var t = toDate(s.posted_at);
      var ms = t ? t.getTime() : 0;
      if (!byPair[p] || ms > byPair[p].ms) byPair[p] = { s: s, ms: ms };
    });
    var rows = Object.keys(byPair).map(function (p) { return byPair[p].s; })
      .sort(function (x, y) { return (toDate(y.posted_at) || 0) - (toDate(x.posted_at) || 0); });

    var note = $('#mySignalsNote');
    if (note) note.hidden = false;

    if (!rows.length) {
      list.innerHTML = '<li class="results-empty">Tiada signal aktif sekarang. Signal terkini akan muncul di sini.</li>';
      return;
    }

    list.innerHTML = rows.map(function (s) {
      var date = '<span class="result-date">' + esc(fmtDateShort(s.posted_at)) + '</span>';
      return '<li class="mysig-row clickable">' +
        '<a class="result-link" href="#/signal?id=' + encodeURIComponent(s.id) + '" title="Buka detail signal">' +
          '<span class="result-pair">' + esc(fmtPair(s.pair)) + '</span>' +
          sideChip(s.side) +
          '<span class="mysig-entry">' + fmtPrice(parseFloat(s.entry)) + '</span>' +
          date +
          '<svg class="mysig-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>' +
        '</a>' +
      '</li>';
    }).join('');
  }

  function renderAuthUI() {
    renderModeChip();
    renderAvatar();
    renderProfile();
    renderMySignals();
    renderStats();
    renderSignal();
    if (state.route === 'signal' && state.detailIsRpc && state.signalQuery.id) {
      openRpcSignal(state.signalQuery.id);
    }
  }

  function initAuth() {
    window.addEventListener('tw-auth-ready', renderAuthUI);
    $('#avatarBtn').addEventListener('click', function () { location.hash = '#/account'; });
    // Delegated: kad profil dijana semula setiap perubahan auth
    $('#profileCard').addEventListener('click', function (e) {
      if (!e.target.closest('#signOutBtn')) return;
      var a = twAuth();
      if (!a || !a.signOut) { location.replace('../login.html'); return; }
      Promise.resolve(a.signOut()).then(function () {
        location.replace('../login.html'); // fallback jika SIGNED_OUT tidak redirect
      });
    });
    renderAuthUI();
  }

  /* ---------- Home: stats ---------- */

  function renderStats() {
    var signals = (state.status && state.status.signals) || {};
    var keys = Object.keys(signals);
    var closedCount = keys.filter(function (k) {
      var s = signals[k].status;
      return ['tp', 'sl', 'expired', 'cancelled', 'collected'].indexOf(s) !== -1;
    }).length;
    var activeCount = keys.filter(function (k) {
      var s = String(signals[k].status || '').toLowerCase();
      return s === 'active' || s === 'pending';
    }).length;

    // "Signal anda": kiraan RPC get_signals() mod ahli; tetamu = '–'.
    var a = twAuth();
    $('#statMySignals').textContent = (a && a.isMember) ? String((a.signals || []).length) : '–';
    $('#statActive').textContent = state.status ? activeCount : '–';
    $('#statClosed').textContent = state.status ? closedCount : '–';
  }

  /* ---------- Chips side/status ---------- */

  function sideChip(side) {
    return String(side || '').toLowerCase() === 'sell'
      ? '<span class="chip chip-sell">SELL</span>'
      : '<span class="chip chip-buy">BUY</span>';
  }

  function statusChip(status) {
    var st = String(status || '').toLowerCase();
    if (['active', 'live', 'pending'].indexOf(st) !== -1) return '<span class="chip chip-live">LIVE</span>';
    if (st === 'expired') return '<span class="chip chip-amber">EXPIRED</span>';
    if (!st) return '<span class="chip chip-muted">SIARAN</span>'; // RPC: keputusan belum direkod
    return '<span class="chip chip-closed">CLOSED</span>';
  }

  /* ---------- Home: hero signal card ---------- */

  function renderSignal() {
    var box = $('#signalCard');
    var hero = $('#heroCard');
    var sig = state.signal;

    if (!sig || typeof sig !== 'object' || !sig.pair) {
      hero.classList.remove('tappable');
      box.innerHTML =
        '<div class="empty-state">' +
          ICONS.radar +
          '<h4>Tiada signal aktif sekarang</h4>' +
          '<p>Enjin AI mengimbas pasaran. Signal baru akan dipaparkan di sini sebaik diterbitkan.</p>' +
          '<button class="btn btn-ghost btn-sm" type="button" data-action="refresh">' + ICONS.refresh + ' Refresh</button>' +
        '</div>';
      return;
    }

    hero.classList.add('tappable');
    var guest = isGuest();
    var d = priceDigits(sig.entry || sig.sl || 0);

    // Tetamu (offline, tiada sesi): level di-blur + overlay lock → log masuk.
    // Ahli (auth sebenar): level penuh.
    box.innerHTML =
      '<div class="signal-top">' +
        '<span class="signal-pair">' + esc(fmtPair(sig.pair)) + '</span>' +
        (sig.timeframe ? '<span class="signal-tf">' + esc(sig.timeframe) + '</span>' : '') +
        sideChip(sig.side) + statusChip(sig.status) +
      '</div>' +
      '<div class="levels-wrap">' +
        '<div class="levels' + (guest ? ' blurred' : '') + '"' + (guest ? ' aria-hidden="true"' : '') + '>' +
          '<div class="level"><span class="level-label">ENTRY</span><span class="level-value">' + fmtNum(sig.entry, d) + '</span></div>' +
          '<div class="level"><span class="level-label">STOP LOSS</span><span class="level-value sl">' + fmtNum(sig.sl, d) + '</span></div>' +
          '<div class="level"><span class="level-label">TAKE PROFIT</span><span class="level-value tp">' + fmtNum(sig.tp, d) + '</span></div>' +
        '</div>' +
        (guest
          ? '<div class="lock-overlay">' +
              ICONS.lock +
              '<p>Log masuk untuk lihat level penuh signal.</p>' +
              '<a class="btn btn-primary btn-sm" href="' + LOGIN_URL + '">Log masuk</a>' +
            '</div>'
          : '') +
      '</div>' +
      '<p class="signal-hint">Ketik untuk chart beranotasi + sebab entry →</p>';
  }

  /* ---------- Home: keputusan terkini ---------- */

  function renderResults() {
    var list = $('#resultsList');
    var signals = (state.status && state.status.signals) || {};

    // Signal expired mungkin hanya ada expired_at (tiada closed).
    function closedOf(s) { return s.closed || s.expired_at || null; }

    var rows = Object.keys(signals)
      .map(function (id) {
        var s = signals[id];
        return { id: id, pair: id.split('_')[0], data: s };
      })
      .filter(function (r) { return r.data && closedOf(r.data); })
      .sort(function (a, b) { return new Date(closedOf(b.data)) - new Date(closedOf(a.data)); })
      .slice(0, 6);

    if (!rows.length) {
      list.innerHTML = '<li class="results-empty">Belum ada keputusan direkodkan.</li>';
      return;
    }

    list.innerHTML = rows.map(function (r) {
      var d = r.data;
      var st = String(d.status || '').toLowerCase();
      var chip, chipClass;
      if (st === 'tp' || st === 'collected') { chip = 'TP'; chipClass = 'chip-tp'; }
      else if (st === 'sl') { chip = 'SL'; chipClass = 'chip-sl'; }
      else { chip = 'EXP'; chipClass = 'chip-exp'; }

      var pipsHtml = '<span class="result-pips flat">—</span>';
      if (typeof d.pips === 'number' && isFinite(d.pips)) {
        var usd = d.unit === 'usd';
        var sign = d.pips > 0 ? '+' : (d.pips < 0 ? '−' : '');
        var val = (usd ? '$' : '') + fmtNum(Math.abs(d.pips), 1);
        var cls = d.pips > 0 ? 'pos' : (d.pips < 0 ? 'neg' : 'flat');
        pipsHtml = '<span class="result-pips ' + cls + '">' + sign + val + '</span>';
      }

      var inner =
        '<span class="result-pair">' + esc(fmtPair(r.pair)) + '</span>' +
        '<span class="chip ' + chipClass + '">' + chip + '</span>' +
        pipsHtml +
        '<span class="result-date">' + esc(fmtDateShort(closedOf(d))) + '</span>';

      return '<li class="result-row">' + inner + '</li>';
    }).join('');
  }

  /* ---------- Markets: chart app (TWChart) + TradingView ---------- */

  function destroyMarketChart() {
    if (state.marketChart) { state.marketChart.destroy(); state.marketChart = null; }
  }

  function destroySignalChart() {
    if (state.signalChart) { state.signalChart.destroy(); state.signalChart = null; }
  }

  function marketSourceLabel(data) {
    var src = String((data && data.source) || '');
    if (/coinbase/i.test(src) && String(data.pair).toUpperCase() === 'BTCUSD') return 'Coinbase';
    return 'Swissquote';
  }

  function mountAppChart() {
    var wrap = $('#appChartWrap');
    var box = $('#chartBox');
    var canvas = $('#marketCanvas');
    var empty = $('#marketChartEmpty');
    var badge = $('#marketDataBadge');
    wrap.hidden = false;
    box.hidden = true;
    unmountChart();
    destroyMarketChart();

    var slug = pairSlug(state.chartSymbol.split(':')[1] || state.chartSymbol);
    $('#marketPairChip').textContent = fmtPair(slug) + ' · M15';
    $('#marketDisclaimer').textContent = 'Data: Swissquote/Coinbase · bukan quote broker anda.';

    fetchBars(slug).then(function (data) {
      if (state.route !== 'markets' || state.marketMode !== 'app') return;
      if (!data) {
        canvas.hidden = true;
        empty.hidden = false;
        badge.hidden = true;
        return;
      }
      canvas.hidden = false;
      empty.hidden = true;
      var bars = data.bars;
      var lastClose = bars[bars.length - 1][4];
      if (window.TWChart) {
        state.marketChart = TWChart.render(canvas, { bars: bars, lastPrice: { price: lastClose } });
      }
      // Badge: kemas kini MYT dari updated (UTC naive) · sumber; offline = data cache.
      var stamp = data.updated ? fmtTime(toDate(data.updated)) : '';
      if (!state.online) {
        badge.textContent = 'Data cache' + (stamp ? ' · ' + stamp + ' MYT' : '');
        badge.classList.add('cache');
      } else {
        badge.textContent = 'Kemas kini ' + (stamp ? stamp + ' MYT' : '—') + ' · ' + marketSourceLabel(data);
        badge.classList.remove('cache');
      }
      badge.hidden = false;
    });
  }

  function mountMarkets() {
    if (state.marketMode === 'tv') {
      $('#appChartWrap').hidden = true;
      $('#chartBox').hidden = false;
      destroyMarketChart();
      $('#marketDisclaimer').textContent = 'Data: TradingView · bukan quote broker anda.';
      mountChart();
    } else {
      mountAppChart();
    }
  }

  /* ---------- Markets: TradingView lazy mount (mod TV, online sahaja) ---------- */

  function mountChart() {
    var box = $('#chartBox');
    if (!state.online) {
      unmountChart();
      box.innerHTML =
        '<div class="chart-offline">' +
          ICONS.wifiOff +
          '<strong>Chart perlukan sambungan internet</strong>' +
          '<span>Sambung semula untuk memuatkan chart TradingView secara langsung. Chart app boleh digunakan offline.</span>' +
        '</div>';
      return;
    }

    box.innerHTML = '';
    var wrap = document.createElement('div');
    wrap.className = 'tradingview-widget-container';
    var inner = document.createElement('div');
    inner.className = 'tradingview-widget-container__widget';
    inner.style.height = '100%';
    var script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: state.chartSymbol,
      interval: '15',
      timezone: MYT,
      theme: 'dark',
      style: '1',
      locale: 'en',
      backgroundColor: 'rgba(18, 24, 19, 1)',
      gridColor: 'rgba(38, 51, 42, 0.4)',
      allow_symbol_change: false,
      calendar: false,
      hide_volume: false,
      support_host: 'https://www.tradingview.com'
    });
    wrap.appendChild(inner);
    wrap.appendChild(script);
    box.appendChild(wrap);
    state.chartMounted = true;
  }

  function unmountChart() {
    $('#chartBox').innerHTML = '';
    state.chartMounted = false;
  }

  function initMarkets() {
    $$('.chip-select').forEach(function (chip) {
      chip.addEventListener('click', function () {
        if (chip.classList.contains('active')) return;
        $$('.chip-select').forEach(function (c) {
          c.classList.toggle('active', c === chip);
          c.setAttribute('aria-pressed', c === chip ? 'true' : 'false');
        });
        state.chartSymbol = chip.getAttribute('data-symbol');
        if (state.route === 'markets') mountMarkets(); // remount bila pair ditukar
      });
    });

    try {
      var storedMode = localStorage.getItem('tw-chartmode');
      if (storedMode === 'tv' || storedMode === 'app') state.marketMode = storedMode;
    } catch (e) { /* abaikan */ }
    syncMarketModeUI();
    $$('#marketModeToggle .seg-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-chartmode');
        if (mode === state.marketMode) return;
        state.marketMode = mode;
        try { localStorage.setItem('tw-chartmode', mode); } catch (e) { /* abaikan */ }
        syncMarketModeUI();
        if (state.route === 'markets') mountMarkets();
      });
    });
  }

  function syncMarketModeUI() {
    $$('#marketModeToggle .seg-btn').forEach(function (btn) {
      var active = btn.getAttribute('data-chartmode') === state.marketMode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  /* ---------- Signal: detail + chart beranotasi ---------- */

  // Key signal-status.json = PAIR + tarikh siaran MYT (corak dashboard lama).
  function statusKeyFor(pair, iso) {
    try {
      var d = toDate(iso);
      if (!d || isNaN(d.getTime())) return '';
      var q = new Intl.DateTimeFormat('en-CA', {
        timeZone: MYT, year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
      }).formatToParts(d).reduce(function (a, x) { a[x.type] = x.value; return a; }, {});
      return String(pair || '').toUpperCase().replace(/[^A-Z0-9]/g, '') + '_' +
        q.year + q.month + q.day + '_' + q.hour + q.minute + q.second;
    } catch (e) { return ''; }
  }

  function rpcNum(v) {
    var n = parseFloat(v);
    return isFinite(n) ? n : null;
  }

  // Detail signal RPC (#/signal?id=N): level dari get_signals(), status rasmi
  // di-merge dari signal-status.json bila key sepadan. RPC tiada analisis —
  // kad sebab entry disembunyikan (jangan reka sebab).
  function openRpcSignal(id) {
    var box = $('#signalDetail');
    destroySignalChart();
    var a = twAuth();
    var row = a && (a.signals || []).filter(function (s) { return String(s.id) === String(id); })[0];

    if (!row) {
      box.innerHTML =
        '<div class="card"><div class="empty-state">' +
          ICONS.radar +
          '<h4>Signal tidak dijumpai</h4>' +
          '<p>Signal ini tiada dalam senarai akaun anda. Kembali ke halaman utama.</p>' +
          '<a class="btn btn-primary btn-sm" href="#/home">Kembali</a>' +
        '</div></div>';
      return;
    }
    var sig = {
      pair: row.pair,
      side: row.side,
      entry: rpcNum(row.entry),
      sl: rpcNum(row.sl),
      tp: rpcNum(row.tp),
      posted_at: row.posted_at,
      status: null
    };
    var st = state.status && state.status.signals &&
      state.status.signals[statusKeyFor(row.pair, row.posted_at)];
    if (st) {
      sig.status = st.status;
      sig.closed = st.closed || null;
      sig.expired_at = st.expired_at || null;
    }

    state.detail = sig;
    state.detailIsRpc = true;
    fetchBars(pairSlug(sig.pair)).then(function (data) {
      if (state.route !== 'signal') return;
      state.detailBars = data ? data.bars : null;
      renderSignalDetail(sig, state.detailBars);
    });
  }

  function openSignal(query) {
    state.signalQuery = query || {};
    state.detailIsRpc = false;
    if (state.signalQuery.id) { openRpcSignal(state.signalQuery.id); return; }
    // Query legacy tidak disokong → kembali ke home.
    if (Object.keys(state.signalQuery).length) { location.replace('#/home'); return; }
    var box = $('#signalDetail');
    destroySignalChart();
    box.innerHTML =
      '<div class="skeleton sk-line w60"></div>' +
      '<div class="skeleton sk-block"></div>' +
      '<div class="skeleton sk-line w40"></div>';

    fetchJSON('data/landing-signal.json').catch(function () { return null; }).then(function (sig) {
      if (state.route !== 'signal') return;
      if (!sig || typeof sig !== 'object' || !sig.pair) {
        box.innerHTML =
          '<div class="card"><div class="empty-state">' +
            ICONS.radar +
            '<h4>Tiada signal aktif sekarang</h4>' +
            '<p>Enjin AI mengimbas pasaran. Signal baru akan dipaparkan di sini sebaik diterbitkan.</p>' +
            '<a class="btn btn-primary btn-sm" href="#/home">Kembali ke Signals</a>' +
          '</div></div>';
        return;
      }
      return fetchBars(pairSlug(sig.pair)).then(function (data) {
        if (state.route !== 'signal') return;
        state.detail = sig;
        state.detailBars = data ? data.bars : null;
        renderSignalDetail(sig, state.detailBars);
      });
    });
  }

  function buildOverlays(sig) {
    var ov = [];
    var d = priceDigits(sig.entry || sig.sl || 0);
    var hasPoi = isNum(sig.poi_low) && isNum(sig.poi_high);
    if (hasPoi) {
      ov.push({ type: 'zone', from: sig.poi_low, to: sig.poi_high, color: 'lime', label: 'ZON POI' });
    }
    if (isNum(sig.entry) && isNum(sig.sl)) {
      ov.push({ type: 'zone', from: Math.min(sig.entry, sig.sl), to: Math.max(sig.entry, sig.sl), color: 'red', label: 'RISIKO' });
    }
    if (isNum(sig.entry) && isNum(sig.tp)) {
      ov.push({ type: 'zone', from: Math.min(sig.entry, sig.tp), to: Math.max(sig.entry, sig.tp), color: 'lime', label: 'GANJARAN' });
    }
    if (isNum(sig.entry)) {
      ov.push({ type: 'line', price: sig.entry, color: 'lime', dash: true, label: 'ENTRY ' + fmtNum(sig.entry, d) });
    }
    if (isNum(sig.sl)) {
      ov.push({ type: 'line', price: sig.sl, color: 'red', dash: false, label: 'SL ' + fmtNum(sig.sl, d) });
    }
    if (isNum(sig.tp)) {
      ov.push({ type: 'line', price: sig.tp, color: 'lime', dash: false, label: 'TP ' + fmtNum(sig.tp, d) });
    }
    if (isNum(sig.tp2)) {
      ov.push({ type: 'line', price: sig.tp2, color: 'lime', dash: true, label: 'TP2 ' + fmtNum(sig.tp2, d) });
    }
    return ov;
  }

  function buildMarkers(sig) {
    var mk = [];
    if (sig.posted_at) mk.push({ ts: sig.posted_at, color: 'lime', label: 'SIARAN' });
    if (sig.expired_at) {
      mk.push({ ts: sig.expired_at, color: 'amber', label: 'LUPUT' });
    } else {
      var endTs = sig.closed_at || sig.closed;
      var st = String(sig.status || '').toLowerCase();
      if (endTs && (st === 'tp' || st === 'collected')) mk.push({ ts: endTs, color: 'lime', label: 'TP' });
      else if (endTs && st === 'sl') mk.push({ ts: endTs, color: 'red', label: 'SL' });
    }
    return mk;
  }

  function levelsGridHTML(sig) {
    var d = priceDigits(sig.entry || sig.sl || 0);
    var hasPoi = isNum(sig.poi_low) && isNum(sig.poi_high);
    var entryVal = hasPoi
      ? fmtNum(sig.poi_low, d) + '–' + fmtNum(sig.poi_high, d)
      : fmtNum(sig.entry, d);
    var rr = sig.rr;
    if (!(typeof rr === 'number' && isFinite(rr)) && isNum(sig.entry) && isNum(sig.sl) && isNum(sig.tp) && sig.entry !== sig.sl) {
      rr = Math.abs(sig.tp - sig.entry) / Math.abs(sig.entry - sig.sl);
    }

    var tiles =
      '<div class="level"><span class="level-label">ENTRY' + (hasPoi ? ' · ZON POI' : '') + '</span><span class="level-value big">' + entryVal + '</span></div>' +
      '<div class="level"><span class="level-label">STOP LOSS</span><span class="level-value big sl">' + fmtNum(sig.sl, d) + '</span></div>' +
      '<div class="level"><span class="level-label">TAKE PROFIT (TP1)</span><span class="level-value big tp">' + fmtNum(sig.tp, d) + '</span></div>' +
      (isNum(sig.tp2)
        ? '<div class="level"><span class="level-label">TAKE PROFIT 2</span><span class="level-value big tp">' + fmtNum(sig.tp2, d) + '</span></div>'
        : '') +
      '<div class="level"><span class="level-label">RISK : REWARD</span><span class="level-value big">' + (typeof rr === 'number' && isFinite(rr) ? fmtNum(rr, 2) : '—') + '</span></div>';

    // Tetamu = blur + lock → log masuk; ahli = level penuh.
    var gate = isGuest();
    return '<div class="levels-wrap">' +
      '<div class="level-grid' + (gate ? ' blurred' : '') + '"' + (gate ? ' aria-hidden="true"' : '') + '>' + tiles + '</div>' +
      (gate
        ? '<div class="lock-overlay">' +
            ICONS.lock +
            '<p>Log masuk untuk lihat level penuh signal.</p>' +
            '<a class="btn btn-primary btn-sm" href="' + LOGIN_URL + '">Log masuk</a>' +
          '</div>'
        : '') +
    '</div>';
  }

  function reasonCardHTML(sig) {
    var summary = sig.summary_ms || sig.summary || '';
    var hasConf = Array.isArray(sig.confluence) && sig.confluence.length;
    // Kad sebab entry hanya dipaparkan bila ada analisis sebenar dari enjin.
    if (!summary && !hasConf && !sig.reason) return '';
    var html = '<section class="card" aria-label="Sebab entry">' +
      '<div class="card-head"><h3>Sebab entry</h3></div>' +
      '<p class="reason-summary">' + esc(summary) + '</p>';

    if (hasConf) {
      html += '<ul class="conf-list">' + sig.confluence.map(function (c) {
        var pass = !!c.pass;
        return '<li class="conf-item">' +
          '<span class="conf-icon ' + (pass ? 'pass' : 'fail') + '">' + (pass ? ICONS.check : ICONS.x) + '</span>' +
          '<span class="conf-text">' + esc(c.gate) +
            (c.note ? '<span class="conf-note">' + esc(c.note) + '</span>' : '') +
          '</span>' +
        '</li>';
      }).join('') + '</ul>';
    }
    if (sig.reason) {
      html += '<p class="reason-mono">' + esc(sig.reason) + '</p>';
    }
    html += '</section>';
    return html;
  }

  function timelineHTML(sig) {
    var st = String(sig.status || '').toLowerCase();
    var endLabel, endTs = sig.expired_at || sig.closed_at || sig.closed;
    if (!st) endLabel = 'Keputusan belum direkod';
    else if (st === 'expired') endLabel = 'Expired';
    else if (st === 'tp' || st === 'collected') endLabel = 'Take Profit';
    else if (st === 'sl') endLabel = 'Stop Loss';
    else if (st === 'cancelled') endLabel = 'Cancelled';
    else endLabel = 'Aktif — menunggu keputusan';

    var posted = sig.posted_at ? fmtDateShort(sig.posted_at) : '—';
    var end = endTs ? fmtDateShort(endTs) : '';
    return '<section class="card" aria-label="Lifecycle signal">' +
      '<div class="card-head"><h3>Timeline</h3></div>' +
      '<div class="timeline">' +
        '<div class="tl-item"><strong>Posted</strong><span>' + esc(posted) + ' MYT</span></div>' +
        '<div class="tl-item end"><strong>' + esc(endLabel) + '</strong><span>' + (end ? esc(end) + ' MYT' : '—') + '</span></div>' +
      '</div>' +
    '</section>';
  }

  function renderSignalDetail(sig, bars) {
    var box = $('#signalDetail');
    destroySignalChart();

    var html =
      '<div class="sig-head">' +
        '<span class="sig-pair">' + esc(fmtPair(sig.pair)) + '</span>' +
        (sig.timeframe ? '<span class="signal-tf">' + esc(sig.timeframe) + '</span>' : '') +
        sideChip(sig.side) + statusChip(sig.status) +
      '</div>';

    // Kad chart beranotasi
    html += '<section class="card chart-card" aria-label="Chart beranotasi">' +
      '<canvas id="signalCanvas" class="tw-canvas" aria-label="Chart candlestick beranotasi"></canvas>' +
      '<div class="chart-offline chart-empty" id="signalChartEmpty"' + (bars ? ' hidden' : '') + '>' +
        ICONS.wifiOff +
        '<strong>Chart perlukan data bar</strong>' +
        '<span>Sambung internet untuk memuatkan data bar. Level signal masih dipaparkan di bawah.</span>' +
      '</div>' +
      '<div class="chart-legend" aria-hidden="true">' +
        '<span class="legend-chip"><span class="dot dot-lime"></span>Entry</span>' +
        '<span class="legend-chip"><span class="dot dot-red"></span>SL</span>' +
        '<span class="legend-chip"><span class="dot dot-lime"></span>TP</span>' +
        '<span class="legend-chip"><span class="dot dot-poi"></span>Zon POI</span>' +
      '</div>' +
    '</section>';

    // Grid level
    html += '<section class="card" aria-label="Level signal">' +
      '<div class="card-head"><h3>Level</h3>' + (sig.timeframe ? '<span class="chip chip-muted">' + esc(sig.timeframe) + '</span>' : '') + '</div>' +
      levelsGridHTML(sig) +
    '</section>';

    // Sebab entry + confluence
    html += reasonCardHTML(sig);

    // Timeline lifecycle
    html += timelineHTML(sig);

    // Prefill kalkulator
    html += '<button class="btn btn-primary btn-block" type="button" data-action="to-tools">' +
      ICONS.calc + ' Kira saiz posisi untuk signal ini</button>' +
    '<p class="disclaimer">Educational only. Trading involves substantial risk.</p>';

    box.innerHTML = html;

    var canvas = $('#signalCanvas');
    if (bars && window.TWChart) {
      canvas.hidden = false;
      state.signalChart = TWChart.render(canvas, {
        bars: bars,
        overlays: buildOverlays(sig),
        markers: buildMarkers(sig),
        lastPrice: { price: bars[bars.length - 1][4] }
      });
    } else {
      canvas.hidden = true;
    }
  }

  function initSignal() {
    // Delegated: butang prefill tools + hero card tappable
    $('#signalDetail').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-action="to-tools"]');
      if (!btn) return;
      var sig = state.detail;
      if (sig && isNum(sig.entry)) $('#calcEntry').value = String(sig.entry);
      if (sig && isNum(sig.sl)) $('#calcSl').value = String(sig.sl);
      // balance/risk kekal seperti pengguna tetapkan
      calcPosition();
      location.hash = '#/tools';
      toast('Entry & SL diprefill dari signal.');
    });

    $('#heroCard').addEventListener('click', function (e) {
      if (e.target.closest('a, button')) return;
      if (!state.signal || !state.signal.pair) return;
      location.hash = '#/signal';
    });
  }

  /* ---------- Prestasi: skrin #/performance + kad home ---------- */

  function destroyPerfChart() {
    if (state.perfChart) { state.perfChart.destroy(); state.perfChart = null; }
  }

  function ringSVG(pct) {
    var r = 34, c = 2 * Math.PI * r;
    var p = Math.max(0, Math.min(100, pct || 0));
    return '<svg viewBox="0 0 84 84" aria-hidden="true">' +
      '<circle cx="42" cy="42" r="' + r + '" fill="none" stroke="rgba(242, 245, 239, 0.12)" stroke-width="8"/>' +
      '<circle cx="42" cy="42" r="' + r + '" fill="none" stroke="#c6f36b" stroke-width="8" stroke-linecap="round" ' +
        'stroke-dasharray="' + (c * p / 100).toFixed(1) + ' ' + c.toFixed(1) + '" transform="rotate(-90 42 42)"/>' +
    '</svg>';
  }

  function perfTile(label, value, cls) {
    return '<div class="perf-tile"><span class="stat-value ' + (cls || '') + '">' + value + '</span>' +
      '<span class="stat-label">' + label + '</span></div>';
  }

  function perfBarsHTML(perf) {
    var rows = [
      ['TP', perf.tp, 'lime'],
      ['SL', perf.sl, 'red'],
      ['Expired', perf.expired, 'amber'],
      ['Collected', perf.collected, 'muted'],
      ['Active', perf.active, 'ink'],
      ['Pending', perf.pending, 'ink']
    ];
    var max = Math.max.apply(null, rows.map(function (r) { return r[1]; }).concat([1]));
    return '<section class="card" aria-label="Taburan status signal">' +
      '<div class="card-head"><h3>Taburan status</h3></div>' +
      '<div class="perf-bars">' + rows.map(function (r) {
        var pct = r[1] ? Math.max(2, 100 * r[1] / max) : 0;
        return '<div class="perf-bar-row">' +
          '<span class="perf-bar-label">' + r[0] + '</span>' +
          '<span class="perf-bar-track"><span class="perf-bar-fill ' + r[2] + '" style="width:' + pct.toFixed(1) + '%"></span></span>' +
          '<span class="perf-bar-count">' + r[1] + '</span>' +
        '</div>';
      }).join('') + '</div>' +
      '<p class="perf-note">Expired ≠ rugi — setup luput tanpa entry. Collected = exit manual (TP dikutip), diasingkan dari win rate.</p>' +
    '</section>';
  }

  function perfMethodHTML() {
    return '<section class="card perf-method" aria-label="Cara kiraan prestasi">' +
      '<div class="card-head"><h3>Cara kiraan</h3></div>' +
      '<ul class="perf-method-list">' +
        '<li>Win rate = TP ÷ (TP + SL) sahaja. Hanya signal yang benar-benar diputuskan dikira.</li>' +
        '<li>1R = risiko setiap trade. Net R = jumlah gandaan risiko — bukan jumlah pips.</li>' +
        '<li>Agregat guna R kerana unit berbeza antara pair (BTC dalam USD, lain dalam pips).</li>' +
        '<li>Collected (exit manual) dan expired diasingkan — bukan kemenangan atau kekalahan automatik.</li>' +
        '<li>Rekod legacy sebelum 19 Okt 2026 diabaikan; enjin disahkan bermula tarikh itu.</li>' +
        '<li>Graf prestasi mengikut tarikh signal diterbitkan — dipapar dari awal rekod, bukan tarikh tutup batch.</li>' +
        '<li>Masa dipapar dalam waktu Malaysia (MYT). Keputusan lepas bukan jaminan keputusan akan datang.</li>' +
      '</ul>' +
    '</section>';
  }

  function renderPerformance() {
    var box = $('#perfBody');
    if (!box) return;
    destroyPerfChart();

    var signals = state.status && state.status.signals;
    if (!signals) {
      box.innerHTML =
        '<div class="skeleton sk-line w40"></div>' +
        '<div class="skeleton sk-block"></div>' +
        '<div class="skeleton sk-block"></div>' +
        '<div class="skeleton sk-line w60"></div>';
      return;
    }

    var days = state.perfDays; // 7, 30 atau 0 (semua)
    var perf = computePerformance(signals, { days: days });
    var html = '<div class="perf-meta">' +
      '<span class="chip chip-muted">' + esc(perfPeriodLabel(perf, days)) + '</span>' +
      '<span class="cache-badge" id="perfCacheBadge" hidden></span>' +
    '</div>';

    if (!perf.decided) {
      html += '<section class="card"><div class="empty-state">' +
        ICONS.radar +
        '<h4>Belum ada signal diputuskan dalam tempoh ini</h4>' +
        '<p>Cuba tempoh lebih panjang — rekod penuh enjin bermula 19 Okt 2026.</p>' +
      '</div></section>';
      html += perfBarsHTML(perf) + perfMethodHTML();
      html += '<p class="disclaimer">Educational only. Trading involves substantial risk.</p>';
      box.innerHTML = html;
      updateCacheBadges();
      return;
    }

    // Kad ringkasan: ring win rate + Net R + tiles.
    html += '<section class="card perf-summary" aria-label="Ringkasan prestasi">' +
      '<div class="card-head"><h3>Ringkasan</h3></div>' +
      '<div class="perf-hero">' +
        '<div class="perf-ring">' + ringSVG(perf.winRate) +
          '<span class="perf-ring-text">' + fmtNum(perf.winRate, 1) + '%</span>' +
        '</div>' +
        '<div class="perf-hero-nums">' +
          '<span class="stat-label">Win rate · TP/(TP+SL)</span>' +
          '<span class="perf-netr-big ' + (perf.netR >= 0 ? 'pos' : 'neg') + '">' + fmtR(perf.netR) + '</span>' +
          '<span class="stat-label">Net R · ' + perf.decided + ' signal diputuskan</span>' +
        '</div>' +
      '</div>' +
      '<div class="perf-tiles">' +
        perfTile('TP', perf.tp, 'lime') +
        perfTile('SL', perf.sl, 'red') +
        perfTile('Collected', perf.collected, '') +
        perfTile('Expired', perf.expired, 'amber') +
        perfTile('Purata RR menang', perf.avgWinR == null ? '—' : fmtNum(perf.avgWinR, 2) + 'R', '') +
        perfTile('Max drawdown', fmtR(perf.maxDrawdownR, 1), perf.maxDrawdownR < 0 ? 'red' : '') +
      '</div>' +
    '</section>';

    // Equity curve: cumulative R mengikut hari (MYT).
    html += '<section class="card chart-card" aria-label="Equity curve R terkumpul">' +
      '<div class="card-head"><h3>Equity curve · R terkumpul</h3><span class="chip chip-muted">harian</span></div>' +
      '<canvas id="perfEquityCanvas" class="tw-canvas perf-canvas" aria-label="Graf R terkumpul mengikut hari"></canvas>' +
    '</section>';

    html += perfBarsHTML(perf);

    // Jadual per-pair (isih Net R desc).
    html += '<section class="card" aria-label="Prestasi mengikut pair">' +
      '<div class="card-head"><h3>Prestasi per pair</h3><span class="chip chip-muted">isih Net R ↓</span></div>' +
      '<div class="perf-table-wrap"><table class="perf-table">' +
        '<thead><tr><th scope="col">Pair</th><th scope="col" class="num">TP</th><th scope="col" class="num">SL</th>' +
        '<th scope="col" class="num">WR%</th><th scope="col" class="num">Net R</th></tr></thead>' +
        '<tbody>' + perf.perPair.map(function (p) {
          return '<tr' + (p.pair === 'XAUUSD' ? ' class="highlight"' : '') + '>' +
            '<th scope="row">' + esc(fmtPair(p.pair)) + '</th>' +
            '<td class="num">' + p.tp + '</td>' +
            '<td class="num">' + p.sl + '</td>' +
            '<td class="num">' + (p.wr == null ? '—' : fmtNum(p.wr, 0) + '%') + '</td>' +
            '<td class="num ' + (p.netR > 0 ? 'pos' : (p.netR < 0 ? 'neg' : '')) + '">' + fmtR(p.netR) + '</td>' +
          '</tr>';
        }).join('') + '</tbody>' +
      '</table></div>' +
    '</section>';

    html += perfMethodHTML();
    html += '<p class="disclaimer">Educational only. Trading involves substantial risk.</p>';
    box.innerHTML = html;

    var canvas = $('#perfEquityCanvas');
    if (canvas && window.TWChart && perf.daily.length) {
      var points = perf.daily.map(function (d) {
        return [Date.parse(d[0] + 'T00:00:00+08:00'), d[2]];
      });
      state.perfChart = TWChart.line(canvas, { points: points, zeroLine: true });
    }
    updateCacheBadges();
  }

  function initPerformance() {
    $$('#perfPeriodChips .chip-select').forEach(function (chip) {
      chip.addEventListener('click', function () {
        var v = chip.getAttribute('data-days');
        var days = v === 'all' ? 0 : parseInt(v, 10);
        if (days === state.perfDays) return;
        state.perfDays = days;
        $$('#perfPeriodChips .chip-select').forEach(function (c) {
          var active = c === chip;
          c.classList.toggle('active', active);
          c.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (state.route === 'performance') renderPerformance();
      });
    });
  }

  // Sparkline SVG ringkas untuk kad prestasi compact di home.
  function sparklineSVG(vals) {
    if (!vals || vals.length < 2) return '';
    var W = 96, H = 34;
    var min = Math.min.apply(null, vals.concat([0]));
    var max = Math.max.apply(null, vals.concat([0]));
    if (max === min) max = min + 1;
    var pts = vals.map(function (v, i) {
      return (2 + i * (W - 4) / (vals.length - 1)).toFixed(1) + ',' +
        (H - 3 - (v - min) / (max - min) * (H - 6)).toFixed(1);
    });
    var last = pts[pts.length - 1].split(',');
    return '<svg class="perf-spark" viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" aria-hidden="true">' +
      '<polyline points="' + pts.join(' ') + '" fill="none" stroke="#c6f36b" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
      '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="2.5" fill="#c6f36b"/>' +
    '</svg>';
  }

  function renderHomePerf() {
    var wrEl = $('#homePerfWR');
    if (!wrEl) return;
    var netEl = $('#homePerfNetR'), subEl = $('#homePerfSub'),
        sparkEl = $('#homePerfSpark'), periodEl = $('#homePerfPeriod');
    var signals = state.status && state.status.signals;
    if (!signals) {
      wrEl.textContent = '–';
      netEl.textContent = '–';
      subEl.textContent = 'Memuatkan rekod…';
      return;
    }
    var perf = computePerformance(signals, { days: 0 });
    periodEl.textContent = perfPeriodLabel(perf, 0);
    if (!perf.decided) {
      wrEl.textContent = '—';
      netEl.textContent = '—';
      netEl.className = 'perf-netr';
      subEl.textContent = 'Belum ada signal diputuskan';
      sparkEl.innerHTML = '';
      return;
    }
    wrEl.textContent = fmtNum(perf.winRate, 1) + '%';
    netEl.textContent = fmtR(perf.netR);
    netEl.className = 'perf-netr ' + (perf.netR >= 0 ? 'pos' : 'neg');
    subEl.textContent = perf.tp + ' TP · ' + perf.sl + ' SL · ' + perf.decided + ' diputuskan';
    sparkEl.innerHTML = sparklineSVG(perf.daily.map(function (d) { return d[2]; }));
  }

  /* ---------- Tools: kalkulator saiz posisi ---------- */

  function calcPosition() {
    var balance = parseFloat($('#calcBalance').value);
    var riskPct = parseFloat($('#calcRisk').value);
    var entry = parseFloat($('#calcEntry').value);
    var sl = parseFloat($('#calcSl').value);

    var riskUsdEl = $('#calcRiskUsd');
    var lotEl = $('#calcLot');

    if (!(balance > 0) || !(riskPct > 0)) {
      riskUsdEl.textContent = '–';
      lotEl.textContent = '–';
      return;
    }
    var riskUsd = balance * riskPct / 100;
    riskUsdEl.textContent = '$' + fmtNum(riskUsd, 2);

    var dist = Math.abs(entry - sl);
    if (!(entry > 0) || !(sl > 0) || !(dist > 0)) {
      lotEl.textContent = '–';
      return;
    }
    // 1 lot XAU = 100 oz → kerugian per lot = jarak harga × 100
    var lot = riskUsd / (dist * 100);
    lotEl.textContent = fmtNum(lot, 2);
  }

  function initTools() {
    ['calcBalance', 'calcRisk', 'calcEntry', 'calcSl'].forEach(function (id) {
      $('#' + id).addEventListener('input', calcPosition);
    });
    calcPosition();
  }

  /* ---------- Online / offline ---------- */

  function updateNetworkUI() {
    var pill = $('#netPill');
    $('#netLabel').textContent = state.online ? 'LIVE' : 'OFFLINE';
    pill.classList.toggle('offline', !state.online);
    $('#offlineBanner').hidden = state.online;
    updateCacheBadges();
    if (state.route === 'markets') mountMarkets();
  }

  function initNetwork() {
    window.addEventListener('online', function () {
      state.online = true;
      updateNetworkUI();
      loadData(); // segar semula data bila kembali online
    });
    window.addEventListener('offline', function () {
      state.online = false;
      updateNetworkUI();
    });
    updateNetworkUI();
  }

  /* ---------- Install flow ---------- */

  function isIOS() {
    var ua = navigator.userAgent || '';
    return /iphone|ipad|ipod/i.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }

  function isStandalone() {
    return navigator.standalone === true ||
      window.matchMedia('(display-mode: standalone)').matches;
  }

  function showInstallBanner() {
    if (isStandalone()) return;
    try {
      if (localStorage.getItem('tw-install-dismissed') === '1') return;
    } catch (e) { /* storage disekat */ }
    $('#installBanner').hidden = false;
  }

  function hideInstallBanner() {
    $('#installBanner').hidden = true;
  }

  function openIosModal() { $('#iosModal').hidden = false; }
  function closeIosModal() { $('#iosModal').hidden = true; }

  function doInstall() {
    if (isStandalone()) {
      toast('App sudah dipasang di peranti ini.');
      return;
    }
    if (state.deferredPrompt) {
      state.deferredPrompt.prompt();
      state.deferredPrompt.userChoice.then(function (choice) {
        if (choice && choice.outcome === 'accepted') hideInstallBanner();
        state.deferredPrompt = null;
      });
      return;
    }
    if (isIOS()) {
      openIosModal();
      return;
    }
    toast('Gunakan menu pelayar → "Install app" / "Add to Home Screen".');
  }

  function initInstall() {
    window.addEventListener('beforeinstallprompt', function (e) {
      e.preventDefault();
      state.deferredPrompt = e;
      showInstallBanner();
    });
    window.addEventListener('appinstalled', function () {
      state.deferredPrompt = null;
      hideInstallBanner();
      toast('TraderWatch berjaya dipasang.');
    });

    $('#installBannerBtn').addEventListener('click', doInstall);
    $('#accountInstall').addEventListener('click', doInstall);
    $('#pitchInstall').addEventListener('click', doInstall);
    $('#installDismiss').addEventListener('click', function () {
      hideInstallBanner();
      try { localStorage.setItem('tw-install-dismissed', '1'); } catch (e) { /* abaikan */ }
    });

    $('#iosModalClose').addEventListener('click', closeIosModal);
    $('#iosModal').addEventListener('click', function (e) {
      if (e.target === this) closeIosModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !$('#iosModal').hidden) closeIosModal();
    });

    if (isIOS() && !isStandalone()) showInstallBanner();
  }

  /* ---------- Init ---------- */

  function init() {
    registerSW();

    // Tarikh Malaysia (jika elemen wujud) + tahun footer
    var gd = $('#greetDate');
    if (gd) {
      try {
        gd.textContent = new Intl.DateTimeFormat('ms-MY', {
          weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: MYT
        }).format(new Date());
      } catch (e) {
        gd.textContent = new Date().toLocaleDateString();
      }
    }
    $('#year').textContent = String(new Date().getFullYear());

    initAuth();
    initRouting();
    initMarkets();
    initSignal();
    initPerformance();
    initTools();
    initNetwork();
    initInstall();

    // Refresh (delegated — butang dalam empty state dijana dinamik)
    $('#signalCard').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-action="refresh"]');
      if (!btn) return;
      $('#signalCard').innerHTML =
        '<div class="skeleton sk-line w60"></div>' +
        '<div class="skeleton sk-block"></div>' +
        '<div class="skeleton sk-line w40"></div>';
      loadData();
    });

    loadData();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();