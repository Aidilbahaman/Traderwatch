/* TraderWatch Member — auth.js
 * Auth Supabase SEBENAR (corak rasmi dashboard lama: supabase-js 2.45.4 CDN,
 * getSession(), profiles.select('name,plan'), RPC get_signals()).
 * Dimuat sebelum app.js. Expose window.TWAuth + event 'tw-auth-ready'.
 *
 * Guard:
 *  - Tiada session + ONLINE  → redirect ../login.html?next=%2Fmember%2F
 *  - Tiada session + OFFLINE → mod cache + banner offline (app mesti buka offline)
 *  - Ada session (localStorage supabase) → mod ahli, walaupun offline
 *  - CDN supabase gagal load → app shell tetap jalan, tanpa sesi, jangan halaman kosong
 */
(function () {
  'use strict';

  var SUPABASE_URL = 'https://vicfiftvhxemuhxxmkxk.supabase.co';
  var SUPABASE_KEY = 'sb_publishable_4LzgHiCMUXmXUOkPtvIHVw_F7ks9otV';
  var LOGIN_URL = '../login.html?next=' + encodeURIComponent('/member/');
  var STORAGE_KEY = 'sb-vicfiftvhxemuhxxmkxk-auth-token';
  var CACHE_KEY = 'tw-member-cache';

  var auth = {
    session: null,
    profile: null,
    signals: [],
    isMember: false,
    plan: 'free',
    isPaid: false,
    signOut: function () { return Promise.resolve(); }
  };
  window.TWAuth = auth;

  function ready() {
    try { window.dispatchEvent(new CustomEvent('tw-auth-ready')); } catch (e) { /* abaikan */ }
  }

  function toLogin(why) {
    // URL redirect membawa diagnosis: why (punca), ref (datang dari mana),
    // app (1 = dalam installed PWA). supaya punca boleh dibaca dari URL sahaja.
    var ref = /login\.html/.test(document.referrer || '') ? 'login' : (document.referrer ? 'other' : 'none');
    var app = 0;
    try { app = (navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches) ? 1 : 0; } catch (e) { /* abaikan */ }
    location.replace(LOGIN_URL + '&bounce=1&why=' + encodeURIComponent(why || 'nosession') + '&ref=' + ref + '&app=' + app);
  }

  // Beacon diagnostik (fire-and-forget, keepalive supaya sempat hantar
  // sebelum redirect). Tiada credential dihantar — metadata sahaja.
  function beacon(event, detail) {
    try {
      fetch(SUPABASE_URL + '/rest/v1/auth_diag', {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', apikey: SUPABASE_KEY, Authorization: 'Bearer ' + SUPABASE_KEY, Prefer: 'return=minimal' },
        body: JSON.stringify({ event: event, detail: detail || {} })
      }).catch(function () { /* abaikan */ });
    } catch (e) { /* abaikan */ }
  }

  function diagDetail(why) {
    var stored = storedSession();
    var ref = /login\.html/.test(document.referrer || '') ? 'login' : (document.referrer ? 'other' : 'none');
    var app = 0, dm = 'browser';
    try {
      app = (navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches) ? 1 : 0;
      dm = window.matchMedia('(display-mode: standalone)').matches ? 'standalone' : (window.matchMedia('(display-mode: minimal-ui)').matches ? 'minimal-ui' : 'browser');
    } catch (e) { /* abaikan */ }
    return {
      why: why, ref: ref, app: app, dm: dm,
      refUrl: (document.referrer || '').slice(0, 200),
      sbKeys: (function () { try { return Object.keys(localStorage).filter(function (k) { return k.indexOf('sb-') === 0; }); } catch (e) { return []; } })(),
      inApp: inAppBrowser(),
      storageOK: storageOK(),
      token: stored ? { exp: stored.expires_at } : null,
      now: Math.floor(Date.now() / 1000),
      ua: (navigator.userAgent || '').slice(0, 220),
      uid: (stored && stored.user && stored.user.id) || null
    };
  }

  // Browser dalam aplikasi (Telegram/WhatsApp/IG/chat) = storage sementara,
  // session hilang setiap kali dibuka → loop login. iOS WebView generik
  // dikesan melalui ketiadaan token Safari/CriOS/FxiOS pada UA iPhone.
  function inAppBrowser() {
    var ua = navigator.userAgent || '';
    if (/Telegram|WhatsApp|Instagram|FBAN|FBAV|Line\/|Twitter|MicroMessenger|Snapchat/i.test(ua)) return true;
    if (/; wv\)/.test(ua)) return true; // Android WebView
    if (/iPhone|iPad|iPod/.test(ua) && /AppleWebKit/.test(ua) && !/Safari\/|CriOS|FxiOS|EdgiOS/.test(ua)) return true;
    return false;
  }

  // Probe: pelayar menyekat localStorage (Block All Cookies / private /
  // WebView terasing)? Supabase fallback ke memory → session hilang setiap
  // navigasi → loop login tanpa henti. Ini punca utama "tak boleh login".
  function storageOK() {
    try {
      var k = 'tw-storage-probe';
      localStorage.setItem(k, '1');
      var ok = localStorage.getItem(k) === '1';
      localStorage.removeItem(k);
      return ok;
    } catch (e) { return false; }
  }

  // Loop breaker: jika baru datang dari login tetapi session masih tiada,
  // JANGAN redirect lagi — papar skrin diagnostik dengan punca + langkah fix.
  function showAuthDiag() {
    var blocked = !storageOK();
    var stored = storedSession();
    beacon('diag_shown', diagDetail('panel'));
    var inApp = inAppBrowser();
    var punca = blocked
      ? 'Pelayar anda menyekat penyimpanan data laman, jadi sesi login tidak dapat dikekalkan. Sila benarkan cookies untuk traderwatch.org dan cuba lagi.'
      : (stored
        ? 'Sesi login anda telah tamat tempoh. Sila log masuk semula untuk meneruskan.'
        : 'Sesi login tidak dijumpai. Ini biasanya berlaku dalam mod private / incognito atau apabila pelayar memadam data laman. Sila log masuk semula melalui pelayar biasa.');
    var inAppWarn = inApp
      ? '<p style="margin:0 0 14px;background:rgba(255,212,121,.12);border:1px solid rgba(255,212,121,.4);border-radius:12px;padding:12px;color:#ffd479;font-size:13.5px"><b>Pelayar dalam aplikasi dikesan</b> (Telegram / WhatsApp / chat). Sesi login tidak kekal dalam pelayar ini. Ketik <b>⋯</b> → <b>&quot;Open in Safari / Chrome&quot;</b>, kemudian log masuk di pelayar biasa untuk akses kekal.</p>'
      : '';
    var div = document.createElement('div');
    div.id = 'twAuthDiag';
    div.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#0a0e0b;color:#f2f5ef;padding:28px 22px calc(28px + env(safe-area-inset-bottom,0px));overflow:auto;font:15px/1.55 Inter,system-ui,-apple-system,sans-serif';
    div.innerHTML =
      '<div style="max-width:430px;margin:0 auto">' +
      '<div style="width:44px;height:44px;border-radius:14px;background:#c6f36b;color:#10170b;display:grid;place-items:center;font-weight:900;font-size:22px;margin-bottom:16px">T</div>' +
      '<h2 style="margin:0 0 8px;font-size:22px;letter-spacing:-.02em">Login tidak dapat diteruskan</h2>' +
      inAppWarn +
      '<p style="margin:0 0 14px;color:#ffd479;font-size:14px">' + punca + '</p>' +
      '<ol style="margin:0 0 18px;padding-left:20px;color:#93a096;font-size:13.5px;display:grid;gap:8px">' +
      '<li>Buka <b style="color:#f2f5ef">traderwatch.org/login.html</b> terus dalam tetingkap <b style="color:#f2f5ef">Safari / Chrome biasa</b> — bukan mod private, bukan app installed.</li>' +
      '<li>iPhone: Settings → Safari → pastikan <b style="color:#f2f5ef">Block All Cookies</b> dimatikan.</li>' +
      '<li>Akaun baru: klik pautan pengesahan dalam emel dahulu (semak folder spam), kemudian log masuk.</li>' +
      '<li>Jika guna app yang dipasang: log masuk melalui pelayar biasa dahulu, atau pasang semula app dari traderwatch.org.</li>' +
      '</ol>' +
      '<div style="display:flex;gap:10px;margin-bottom:16px">' +
      '<button id="twDiagRetry" type="button" style="flex:1;background:#c6f36b;color:#10170b;border:0;border-radius:14px;padding:13px;font-weight:750;font-size:14px;cursor:pointer">Cuba lagi</button>' +
      '<button id="twDiagLogin" type="button" style="flex:1;background:transparent;color:#f2f5ef;border:1px solid #26332a;border-radius:14px;padding:13px;font-weight:750;font-size:14px;cursor:pointer">Halaman login</button>' +
      '</div>' +
      '</div>';
    document.body.appendChild(div);
    document.getElementById('twDiagRetry').addEventListener('click', function () { location.href = './'; });
    document.getElementById('twDiagLogin').addEventListener('click', function () { location.href = LOGIN_URL; });
    guest(); // app di belakang tetap render, panel di atas
  }

  function guest() {
    auth.session = null;
    auth.profile = null;
    auth.signals = [];
    auth.isMember = false;
    auth.plan = 'free';
    auth.isPaid = false;
    ready();
  }

  function fallbackName(session) {
    var u = (session && session.user) || {};
    var meta = u.user_metadata || {};
    return meta.name || (u.email ? String(u.email).split('@')[0] : 'Ahli');
  }

  // Offline: tokenexpired tak boleh di-refresh — baca session terus dari
  // localStorage supaya mod ahli masih berfungsi tanpa internet.
  function storedSession() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var s = JSON.parse(raw);
      if (s && s.access_token && s.user) return s;
    } catch (e) { /* storage rosak/disekat */ }
    return null;
  }

  function readCache() {
    try {
      var c = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
      if (c && typeof c === 'object') return c;
    } catch (e) { /* abaikan */ }
    return null;
  }

  function writeCache() {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({
        profile: auth.profile, signals: auth.signals, at: Date.now()
      }));
    } catch (e) { /* storage penuh/disekat */ }
  }

  function loadMember(sb, session) {
    auth.session = session;
    auth.isMember = true;
    var cached = readCache();
    auth.profile = (cached && cached.profile) || { name: fallbackName(session), plan: 'free' };
    auth.signals = (cached && Array.isArray(cached.signals)) ? cached.signals : [];
    auth.plan = String(auth.profile.plan || 'free').toLowerCase();
    auth.isPaid = auth.plan !== 'free';
    ready(); // render segera (cache/offline), kemudian segar semula di bawah

    var uid = session.user && session.user.id;
    var pP = uid
      ? sb.from('profiles').select('name,plan').eq('id', uid).single()
          .then(function (r) { return r.data || null; })
          .catch(function () { return null; })
      : Promise.resolve(null);
    var sP = sb.rpc('get_signals')
      .then(function (r) { if (r.error) throw r.error; return r.data || []; })
      .catch(function () { return null; });

    return Promise.all([pP, sP]).then(function (res) {
      var p = res[0], s = res[1];
      if (p) auth.profile = { name: p.name || fallbackName(session), plan: String(p.plan || 'free').toLowerCase() };
      if (s) auth.signals = s;
      auth.plan = String(auth.profile.plan || 'free').toLowerCase();
    auth.isPaid = auth.plan !== 'free';
      if (p || s) writeCache();
      beacon('member_ok', { plan: auth.plan, inApp: inAppBrowser(), ua: (navigator.userAgent || '').slice(0, 220) });
      ready();
    });
  }

  function boot() {
    // CDN gagal load (offline pertama kali) → shell tetap jalan, tanpa sesi.
    if (!window.supabase || !window.supabase.createClient) { guest(); return; }

    var sb;
    try { sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY); }
    catch (e) { guest(); return; }

    auth.signOut = function () {
      try { return sb.auth.signOut().catch(function () { /* abaikan */ }); }
      catch (e) { return Promise.resolve(); }
    };

    // Tiada session: redirect ke login SEKALI sahaja. Jika baru datang dari
    // login (atau storage disekat), papar diagnostik — jangan loop.
    function noSession() {
      if (!navigator.onLine) { guest(); return; }
      beacon('bounce_nosession', diagDetail('nosession'));
      var fromLogin = /login\.html/.test(document.referrer || '');
      if (fromLogin || !storageOK()) { showAuthDiag(); return; }
      toLogin('nosession');
    }

    sb.auth.onAuthStateChange(function (event) {
      if (event === 'SIGNED_OUT') {
        if (!navigator.onLine) { guest(); return; } // offline: kekal dalam app
        beacon('signed_out', diagDetail('signedout'));
        var fromLogin = /login\.html/.test(document.referrer || '');
        if (fromLogin || !storageOK()) { showAuthDiag(); return; }
        toLogin('signedout');
      }
    });

    sb.auth.getSession().then(function (res) {
      var session = res && res.data && res.data.session;
      if (!session) session = storedSession();
      if (!session) { noSession(); return; }
      return loadMember(sb, session);
    }).catch(function () {
      var session = storedSession();
      if (session) { loadMember(sb, session); return; }
      noSession();
    });
  }

  boot();
})();