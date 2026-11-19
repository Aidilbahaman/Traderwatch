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

  function toLogin() { location.replace(LOGIN_URL); }

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

    sb.auth.onAuthStateChange(function (event) {
      if (event === 'SIGNED_OUT') {
        if (navigator.onLine) toLogin();
        else guest(); // offline: kekal dalam app, mod tetamu cache
      }
    });

    sb.auth.getSession().then(function (res) {
      var session = res && res.data && res.data.session;
      if (!session) session = storedSession();
      if (!session) {
        if (navigator.onLine) toLogin();
        else guest();
        return;
      }
      return loadMember(sb, session);
    }).catch(function () {
      var session = storedSession();
      if (session) { loadMember(sb, session); return; }
      if (navigator.onLine) toLogin();
      else guest();
    });
  }

  boot();
})();