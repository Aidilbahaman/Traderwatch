/* TraderWatch Member — auth.js
 * Auth Supabase SEBENAR (corak rasmi dashboard lama: supabase-js 2.45.4 CDN,
 * getSession(), profiles.select('name,plan'), RPC get_signals()).
 * Dimuat sebelum app.js.Expose window.TWAuth + event 'tw-auth-ready'.
 *
 * Guard:
 *  - Tiada session + ONLINE  → redirect ../login.html?next=%2Fmember%2F
 *  - Tiada session + OFFLINE → mod tetamu cache + banner offline (app mesti buka offline)
 *  - Ada session (localStorage supabase) → mod ahli, walaupun offline
 *  - CDN supabase gagal load → app shell tetap jalan, mod tetamu, jangan halaman kosong
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
    signOut: function () { return Promise.resolve(); }
  };
  window.TWAuth = auth;

  function ready() {
    try { window.dispatchEvent(new CustomEvent('tw-auth-ready')); } catch (e) { /* abaikan */ }
  }

  function toLogin(reason) {
    location.replace(LOGIN_URL + '&bounce=1' + (reason ? '&err=' + encodeURIComponent(reason) : ''));
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
    var punca = blocked
      ? 'Pelayar anda menyekat data laman (cookies / localStorage). Session login tidak dapat disimpan, jadi setiap halaman melantun balik ke login.'
      : (stored
        ? 'Session lama dijumpai tetapi tidak sah (expired / refresh gagal). Log masuk semula diperlukan.'
        : 'Session tidak dijumpai selepas login. Ini biasanya berlaku dalam mod private / incognito, dalam app installed yang berasingan daripada browser, atau pelayar yang memadam data laman.');
    var div = document.createElement('div');
    div.id = 'twAuthDiag';
    div.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#0a0e0b;color:#f2f5ef;padding:28px 22px calc(28px + env(safe-area-inset-bottom,0px));overflow:auto;font:15px/1.55 Inter,system-ui,-apple-system,sans-serif';
    div.innerHTML =
      '<div style="max-width:430px;margin:0 auto">' +
      '<div style="width:44px;height:44px;border-radius:14px;background:#c6f36b;color:#10170b;display:grid;place-items:center;font-weight:900;font-size:22px;margin-bottom:16px">T</div>' +
      '<h2 style="margin:0 0 8px;font-size:22px;letter-spacing:-.02em">Login tidak dapat diteruskan</h2>' +
      '<p style="margin:0 0 14px;color:#ffd479;font-size:14px">' + punca + '</p>' +
      '<ol style="margin:0 0 18px;padding-left:20px;color:#93a096;font-size:13.5px;display:grid;gap:8px">' +
      '<li>Buka <b style="color:#f2f5ef">traderwatch.org/login.html</b> terus dalam tetingkap <b style="color:#f2f5ef">Safari / Chrome biasa</b> — bukan mod private, bukan app installed.</li>' +
      '<li>iPhone: Settings → Safari → pastikan <b style="color:#f2f5ef">Block All Cookies</b> dimatikan.</li>' +
      '<li>Akaun baru: klik link pengesahan dalam emel dahulu (check spam), kemudian log masuk.</li>' +
      '<li>Jika guna app installed: log masuk melalui pelayar biasa dahulu, atau install semula app dari traderwatch.org.</li>' +
      '</ol>' +
      '<div style="display:flex;gap:10px;margin-bottom:16px">' +
      '<button id="twDiagRetry" type="button" style="flex:1;background:#c6f36b;color:#10170b;border:0;border-radius:14px;padding:13px;font-weight:750;font-size:14px;cursor:pointer">Cuba lagi</button>' +
      '<button id="twDiagLogin" type="button" style="flex:1;background:transparent;color:#f2f5ef;border:1px solid #26332a;border-radius:14px;padding:13px;font-weight:750;font-size:14px;cursor:pointer">Halaman login</button>' +
      '</div>' +
      '<details style="color:#93a096;font-size:11.5px"><summary style="cursor:pointer">Butiran teknikal (untuk admin)</summary>' +
      '<pre style="white-space:pre-wrap;background:#121813;border:1px solid #26332a;border-radius:12px;padding:12px;margin-top:8px;font-size:11px">' +
      'storageOK: ' + !blocked + '\n' +
      'storedToken: ' + (stored ? 'ada (expires_at ' + stored.expires_at + ')' : 'tiada') + '\n' +
      'online: ' + navigator.onLine + '\n' +
      'referrer: ' + (document.referrer || '(tiada)') + '\n' +
      'ua: ' + navigator.userAgent.slice(0, 160) +
      '</pre></details>' +
      '</div>';
    document.body.appendChild(div);
    document.getElementById('twDiagRetry').addEventListener('click', function () { location.href = './'; });
    document.getElementById('twDiagLogin').addEventListener('click', function () { location.href = LOGIN_URL; });
    guest(); // app di belakang tetap render (mod tetamu), panel di atas
  }

  function guest() {
    auth.session = null;
    auth.profile = null;
    auth.signals = [];
    auth.isMember = false;
    auth.plan = 'free';
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
    auth.plan = auth.profile.plan === 'pro' ? 'pro' : 'free';
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
      if (p) auth.profile = { name: p.name || fallbackName(session), plan: p.plan === 'pro' ? 'pro' : 'free' };
      if (s) auth.signals = s;
      auth.plan = auth.profile.plan === 'pro' ? 'pro' : 'free';
      if (p || s) writeCache();
      ready();
    });
  }

  function boot() {
    // CDN gagal load (offline pertama kali) → shell tetap jalan, mod tetamu.
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
      var fromLogin = /login\.html/.test(document.referrer || '');
      if (fromLogin || !storageOK()) { showAuthDiag(); return; }
      toLogin('');
    }

    sb.auth.onAuthStateChange(function (event) {
      if (event === 'SIGNED_OUT') {
        if (!navigator.onLine) { guest(); return; } // offline: kekal dalam app
        var fromLogin = /login\.html/.test(document.referrer || '');
        if (fromLogin || !storageOK()) { showAuthDiag(); return; }
        toLogin('');
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