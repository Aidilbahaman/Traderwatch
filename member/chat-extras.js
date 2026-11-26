/* TraderWatch chat extras — GIF picker for the member chat composers.
 *
 * Loaded as a plain <script defer> so globals from the member app (sendDM,
 * sendMsg, apiFetch, lang, toast) are already defined when it runs.
 *
 * Design notes
 *  - GIF tab shows the built-in TraderWatch reaction pack (member/gifs). The
 *    grid paints cheap JPG posters; the animated .gif only loads in the bubble
 *    once it is actually sent, so opening the picker stays light on phones.
 *  - If the server has a provider key configured (features.gifs) it also
 *    searches remotely through /api/chat/gif, which proxies Klipy/Giphy
 *    server-side. Without a key the pack still works offline.
 */

  'use strict';

  var PACK_SRC = 'gifs/pack.json?v=20261126c';

  var S = {
    host: null, panel: null, target: null, input: null, onGif: null,
    kind: 'dm', packReady: false, pack: null, remote: false,
    query: '', reqId: 0, searchT: 0, built: false, busy: false
  };

  function L(en, ms) { return window.lang === 'en' ? en : ms; }
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function haptic(n) { try { if (window.hap) window.hap(n); } catch (e) {} }

  /* ---------- urls ---------- */
  var SAFE_HOSTS = /^(?:media\d?\.tenor\.com|c\.tenor\.com|static\d?\.klipy\.com|media\d?\.giphy\.com|i\.giphy\.com|traderwatch\.org)$/i;
  function safeGifUrl(u) {
    u = String(u || '').trim();
    if (/^\/member\/gifs\/[a-z0-9_-]{1,40}\.gif$/i.test(u)) return u;
    try {
      var ur = new URL(u);
      if (ur.protocol === 'https:' && SAFE_HOSTS.test(ur.hostname)) return ur.href;
    } catch (e) {}
    return '';
  }
  function safeStillUrl(u) {
    u = String(u || '').trim();
    if (/^\/member\/gifs\/[a-z0-9_-]{1,40}\.jpe?g$/i.test(u)) return u;
    return safeGifUrl(u);
  }
  window.twSafeGifUrl = safeGifUrl;

  /* ---------- panel markup ---------- */
  function build() {
    if (S.built) return;
    S.built = true;
    var p = document.createElement('div');
    p.className = 'cx-panel';
    p.id = 'cxPanel';
    p.setAttribute('role', 'dialog');
    p.setAttribute('aria-label', L('GIF picker', 'Pemilih GIF'));
    p.innerHTML =
      '<div class="cx-head">' +
        '<div class="cx-title"><span class="cx-ico">🎞️</span><span>' + esc(L('GIF', 'GIF')) + '</span></div>' +
        '<button class="cx-close" type="button" aria-label="' + esc(L('Close', 'Tutup')) + '">✕</button>' +
      '</div>' +
      '<div class="cx-search"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>' +
        '<input type="search" autocomplete="off" enterkeyhint="search" placeholder="' + esc(L('Search GIF…', 'Cari GIF…')) + '" aria-label="' + esc(L('Search GIF', 'Cari GIF')) + '">' +
        '<button class="cx-clear" type="button" aria-label="' + esc(L('Clear', 'Kosongkan')) + '">✕</button></div>' +
      '<div class="cx-body on">' +
        '<div class="cx-gifscroll"><div class="cx-gifwrap" data-gifs></div></div>' +
      '</div>' +
      '<div class="cx-foot">' + esc(L('Powered by', 'Dikuasakan oleh')) + ' <b>TRADERWATCH</b></div>';
    S.host.appendChild(p);
    S.panel = p;

    p.querySelector('.cx-close').onclick = close;
    var si = p.querySelector('.cx-search input');
    si.addEventListener('input', function () {
      p.querySelector('.cx-search').classList.toggle('has', !!si.value);
      S.query = si.value.trim().toLowerCase();
      drawGifs();
    });
    p.querySelector('.cx-clear').onclick = function () {
      si.value = ''; S.query = '';
      p.querySelector('.cx-search').classList.remove('has');
      si.focus();
      drawGifs();
    };
    p.querySelector('[data-gifs]').addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('[data-gif]') : null;
      if (!b) return;
      pickGif(b);
    });
    // keep focus (and the on-screen keyboard) off the panel, but let touch
    // scrolling through: only buttons swallow the pointer default.
    p.addEventListener('pointerdown', function (e) {
      if (e.target.closest && e.target.closest('button')) e.preventDefault();
    });
  }

  /* ---------- open / close / place ---------- */
  function place() {
    if (!S.panel || !S.target) return;
    var hostR = S.host.getBoundingClientRect();
    var cR = S.target.getBoundingClientRect();
    S.panel.style.left = Math.max(4, cR.left - hostR.left + 2) + 'px';
    S.panel.style.right = Math.max(4, hostR.right - cR.right + 2) + 'px';
    S.panel.style.bottom = Math.max(6, hostR.bottom - cR.top + 6) + 'px';
    S.panel.style.maxHeight = Math.max(220, Math.min(420, cR.top - hostR.top - 24)) + 'px';
  }

  function open(target, input, kind, onGif) {
    build();
    S.target = target; S.input = input; S.kind = kind; S.onGif = onGif;
    try { input.blur(); } catch (e) {}
    place();
    S.panel.classList.add('open');
    document.documentElement.classList.add('cx-open');
    loadPack(function () { drawGifs(); });
    document.addEventListener('pointerdown', outside, true);
    window.addEventListener('resize', place);
  }

  function close() {
    if (!S.panel) return;
    S.panel.classList.remove('open');
    document.documentElement.classList.remove('cx-open');
    document.removeEventListener('pointerdown', outside, true);
    window.removeEventListener('resize', place);
    document.querySelectorAll('.cx-btn.on').forEach(function (b) { b.classList.remove('on'); });
    S.target = null; S.input = null; S.onGif = null;
  }

  function outside(e) {
    if (!S.panel) return;
    if (S.panel.contains(e.target)) return;
    if (e.target.closest && e.target.closest('.cx-btn')) return;
    close();
  }
  window.twCloseChatExtras = close;

  /* ---------- gif grid ---------- */
  function loadPack(cb) {
    if (S.packReady) return cb();
    fetch(PACK_SRC, { cache: 'force-cache' })
      .then(function (r) { return r.ok ? r.json() : { g: [] }; })
      .then(function (d) { S.pack = (d && d.g) || []; S.packReady = true; cb(); })
      .catch(function () { S.pack = []; S.packReady = true; cb(); });
  }

  function drawGifs() {
    if (!S.panel || !S.packReady) return;
    var q = S.query;
    var local = (S.pack || []).filter(function (g) {
      if (!q) return true;
      return (g.title + ' ' + g.kw + ' ' + g.id).toLowerCase().indexOf(q) > -1;
    });
    renderGifs(local, false);
    if (q) remoteSearch(q);
  }

  function tile(g, still, url, title, showTitle) {
    var t = esc(title || 'GIF');
    // The pack posters already carry their own caption, so no text overlay —
    // the title lives in title/aria-label for hover + screen readers.
    return '<button class="cx-gif" type="button" data-gif="' + esc(g.id || url) + '" data-url="' + esc(url) + '" data-title="' + t + '" title="' + t + '" aria-label="' + t + '">' +
      '<img src="' + esc(still) + '" alt="' + t + '" loading="lazy" decoding="async" width="' + (g.w || 240) + '" height="' + (g.h || 240) + '">' +
      '</button>';
  }

  function renderGifs(list, remote) {
    var box = S.panel && S.panel.querySelector('[data-gifs]');
    if (!box) return;
    var local = list.map(function (g) {
      var u = safeGifUrl(g.url);
      if (!u) return '';
      return tile(g, safeStillUrl(g.poster) || u, u, g.title, true);
    }).join('');
    var html = '';
    if (local) {
      html += '<div class="cx-sec"><div class="cx-seclab">' +
        esc(L('TraderWatch pack', 'Pek TraderWatch')) + '</div><div class="cx-gifgrid">' + local + '</div></div>';
    } else if (!remote) {
      html += '<div class="cx-empty">' + esc(L('No GIF for that search. Try “laugh”, “nice”, “profit”.', 'Tiada GIF untuk carian itu. Cuba “lol”, “nice”, “untung”.')) + '</div>';
    }
    box.innerHTML = html || '<div class="cx-empty">' + esc(L('Searching…', 'Mencari…')) + '</div>';
  }

  function remoteSearch(q) {
    if (!S.remote || typeof window.apiFetch !== 'function' || S.busy) return;
    var id = ++S.reqId;
    clearTimeout(S.searchT);
    S.searchT = setTimeout(function () {
      S.busy = true;
      window.apiFetch('/api/chat/gif?q=' + encodeURIComponent(q)).then(function (r) {
        S.busy = false;
        if (id !== S.reqId || !r || !r.ok) return;
        var rows = (r.data && r.data.results) || [];
        if (!rows.length) return;
        var box = S.panel.querySelector('[data-gifs]');
        if (!box) return;
        var extra = rows.map(function (g) {
          var u = safeGifUrl(g.url);
          if (!u) return '';
          return tile(g, safeStillUrl(g.preview) || u, u, g.title, false);
        }).join('');
        if (extra) {
          box.insertAdjacentHTML('beforeend',
            '<div class="cx-sec"><div class="cx-seclab">' + esc(r.data.provider || 'GIF') +
            '</div><div class="cx-gifgrid">' + extra + '</div></div>');
        }
      }).catch(function () { S.busy = false; });
    }, 420);
  }

  function pickGif(b) {
    var url = b ? safeGifUrl(b.dataset.url) : '';
    if (!url) return;
    var img = b.querySelector('img');
    var w = parseInt(img && img.getAttribute('width'), 10) || 240;
    var h = parseInt(img && img.getAttribute('height'), 10) || 240;
    var gif = { id: b.dataset.gif, url: url, w: w, h: h, title: b.dataset.title || 'GIF' };
    haptic(8);
    var fn = S.onGif;
    close();
    if (typeof fn === 'function') fn(gif);
  }

  /* ---------- mount ---------- */
  function btn(kind, target, input, onGif) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'cx-btn';
    b.dataset.cx = kind;
    b.setAttribute('aria-label', L('Send a GIF', 'Hantar GIF'));
    b.title = L('Send a GIF', 'Hantar GIF');
    b.innerHTML = '<span class="cx-gifmark">GIF</span>';
    b.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var on = b.classList.contains('on');
      document.querySelectorAll('.cx-btn.on').forEach(function (x) { x.classList.remove('on'); });
      if (on) { close(); return; }
      b.classList.add('on');
      open(target, input, kind, onGif);
    });
    input.parentNode.insertBefore(b, input);
    return b;
  }

  function autoMount() {
    S.host = document.querySelector('.phone');
    if (!S.host) return;

    var dmComp = $('dmComp'), dmInp = $('dmInp');
    if (dmComp && dmInp && !dmComp.querySelector('.cx-btn')) {
      btn('dm', dmComp, dmInp, function (gif) {
        if (typeof window.sendDM === 'function') window.sendDM(null, gif);
      });
    }
    var comComp = $('composer'), comInp = $('msgInput');
    if (comComp && comInp && !comComp.querySelector('.cx-btn')) {
      btn('com', comComp, comInp, function (gif) {
        if (typeof window.sendMsg === 'function') window.sendMsg(gif);
      });
    }

    // close the picker when the DM sheet closes
    var sheet = $('dmSheet');
    if (sheet) {
      new MutationObserver(function () {
        if (!sheet.classList.contains('open') && S.kind === 'dm') close();
      }).observe(sheet, { attributes: true, attributeFilter: ['class'] });
    }
    // close on view switch (community composer lives inside a view)
    document.addEventListener('click', function (e) {
      var n = e.target.closest && e.target.closest('[data-nav],[data-view]');
      if (n && S.panel && S.panel.classList.contains('open')) close();
    }, true);
  }


  window.TWChatExtras = {
    mount: autoMount,
    close: close,
    setRemote: function (on) { S.remote = !!on; },
    isOpen: function () { return !!(S.panel && S.panel.classList.contains('open')); }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoMount);
  } else {
    autoMount();
  }

