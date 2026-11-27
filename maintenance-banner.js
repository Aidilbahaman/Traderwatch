(function () {
  if (window.TWMaintenance) return;
  var OVERLAY_ID = 'tw-maint-overlay';
  var STYLE_ID = 'tw-maint-overlay-css';

  function injectCss() {
    if (document.getElementById(STYLE_ID)) return;
    var st = document.createElement('style');
    st.id = STYLE_ID;
    st.textContent =
      '@keyframes twMaintFloat{' +
        '0%,100%{transform:translateY(0) rotate(-3deg) scale(1,1);filter:drop-shadow(0 6px 16px rgba(183,243,107,.38))}' +
        '25%{transform:translateY(-6px) rotate(2.5deg) scale(.97,1.04);filter:drop-shadow(0 10px 22px rgba(125,211,252,.46))}' +
        '50%{transform:translateY(-2px) rotate(4deg) scale(1.04,.96);filter:drop-shadow(0 7px 20px rgba(183,243,107,.54))}' +
        '75%{transform:translateY(-7px) rotate(-2deg) scale(.98,1.03);filter:drop-shadow(0 11px 24px rgba(183,243,107,.48))}' +
      '}' +
      '@keyframes twMaintPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.42;transform:scale(.78)}}' +
      '@keyframes twMaintIn{from{opacity:0;transform:translateY(10px) scale(.97)}to{opacity:1;transform:none}}' +
      '#' + OVERLAY_ID + '{' +
        'position:fixed;inset:0;z-index:2147483645;' +
        'display:flex;align-items:center;justify-content:center;' +
        'padding:calc(max(18px,env(safe-area-inset-top,0px)) + 10px) max(16px,env(safe-area-inset-right,0px)) calc(max(18px,env(safe-area-inset-bottom,0px)) + 10px) max(16px,env(safe-area-inset-left,0px));' +
        'background:radial-gradient(75% 50% at 22% 10%,rgba(183,243,107,.14),transparent 62%),' +
                   'radial-gradient(65% 48% at 82% 88%,rgba(74,222,128,.10),transparent 60%),' +
                   'rgba(6,10,7,.76);' +
        'backdrop-filter:blur(16px) saturate(140%);-webkit-backdrop-filter:blur(16px) saturate(140%);' +
        'font-family:-apple-system,BlinkMacSystemFont,"Inter","SF Pro Display",system-ui,sans-serif;' +
        'color:#eef5ef;overflow-y:auto;-webkit-overflow-scrolling:touch;' +
      '}' +
      /* On member app mobile: sit neatly between topbar+ticker and bottom nav like the preview */
      '#' + OVERLAY_ID + '.twm-member{' +
        'padding-top:calc(env(safe-area-inset-top,0px) + 92px);' +
        'padding-bottom:calc(env(safe-area-inset-bottom,0px) + 92px);' +
      '}' +
      '@media(min-width:841px){' +
        '#' + OVERLAY_ID + '.twm-member{padding-top:32px;padding-bottom:32px}' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-card{' +
        'position:relative;width:100%;max-width:390px;margin:auto;' +
        'border-radius:26px;padding:26px 22px 24px;text-align:center;' +
        'background:radial-gradient(92% 55% at 50% 0%,rgba(183,243,107,.15),transparent 68%),rgba(12,19,14,.90);' +
        'backdrop-filter:blur(24px) saturate(155%);-webkit-backdrop-filter:blur(24px) saturate(155%);' +
        'border:1px solid rgba(183,243,107,.34);' +
        'box-shadow:0 24px 64px rgba(0,0,0,.62),inset 0 1px 0 rgba(255,255,255,.10),0 0 42px rgba(183,243,107,.10);' +
        'animation:twMaintIn .32s cubic-bezier(.22,1,.36,1) both;' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-top{display:flex;flex-direction:column;align-items:center;gap:11px;margin-bottom:16px}' +
      '#' + OVERLAY_ID + ' .twm-ico{' +
        'width:88px;height:88px;border-radius:22px;' +
        'background:radial-gradient(circle at 50% 45%,rgba(183,243,107,.22),rgba(183,243,107,.04) 72%);' +
        'border:1px solid rgba(183,243,107,.34);' +
        'display:grid;place-items:center;overflow:hidden;' +
        'box-shadow:0 0 28px rgba(183,243,107,.24);' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-ico img{' +
        'width:78px;height:78px;object-fit:contain;display:block;' +
        'filter:drop-shadow(0 6px 14px rgba(183,243,107,.32));' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-pill{' +
        'display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:999px;' +
        'font-size:10px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;' +
        'color:#b7f36b;background:rgba(183,243,107,.12);border:1px solid rgba(183,243,107,.32);' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-dot{' +
        'width:6px;height:6px;border-radius:50%;background:#b7f36b;' +
        'box-shadow:0 0 8px #b7f36b;animation:twMaintPulse 1.6s ease-in-out infinite;' +
      '}' +
      '#' + OVERLAY_ID + ' h2{' +
        'margin:0 0 6px;font-size:20px;font-weight:900;line-height:1.22;letter-spacing:-.015em;color:#f6fbf7;' +
      '}' +
      '#' + OVERLAY_ID + ' h2 span{color:#b7f36b}' +
      '#' + OVERLAY_ID + ' .twm-lead{margin:0 0 14px;font-size:13.5px;font-weight:700;color:#cde2d1}' +
      '#' + OVERLAY_ID + ' .twm-copy{display:flex;flex-direction:column;gap:10px;margin:0 0 16px;font-size:12.8px;line-height:1.55;color:#9db2a2}' +
      '#' + OVERLAY_ID + ' .twm-copy p{margin:0}' +
      '#' + OVERLAY_ID + ' .twm-copy .twm-warm{color:#dcebe0;font-weight:600}' +
      '#' + OVERLAY_ID + ' .twm-div{height:1px;width:100%;margin:14px 0;background:linear-gradient(90deg,transparent,rgba(183,243,107,.32),transparent)}' +
      '#' + OVERLAY_ID + ' .twm-cdbox{margin:0 0 14px;padding:11px 10px 10px;border-radius:16px;background:rgba(183,243,107,.06);border:1px solid rgba(183,243,107,.22)}' +
      '#' + OVERLAY_ID + ' .twm-cdlab{margin:0 0 8px;font-size:9.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:#9db2a2}' +
      '#' + OVERLAY_ID + ' .twm-cdgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}' +
      '#' + OVERLAY_ID + ' .twm-cdu{padding:7px 4px 6px;border-radius:11px;background:rgba(8,14,10,.72);border:1px solid rgba(255,255,255,.08)}' +
      '#' + OVERLAY_ID + ' .twm-cdu b{display:block;font-size:18px;font-weight:900;line-height:1.1;color:#b7f36b;font-variant-numeric:tabular-nums;letter-spacing:-.02em}' +
      '#' + OVERLAY_ID + ' .twm-cdu span{display:block;margin-top:2px;font-size:8.5px;font-weight:750;letter-spacing:.06em;text-transform:uppercase;color:#7e9484}' +
      '@keyframes twTgSweep{0%{transform:translateX(-140%) skewX(-18deg)}42%,100%{transform:translateX(260%) skewX(-18deg)}}' +
      '@keyframes twTgBob{0%,100%{transform:translate(0,0)}50%{transform:translate(2px,-1.5px)}}' +
      '#' + OVERLAY_ID + ' .twm-tg{' +
        'position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;gap:10px;' +
        'width:100%;margin:0 0 15px;padding:11px 16px;border-radius:14px;text-decoration:none;' +
        'background:linear-gradient(135deg,rgba(42,171,238,.20) 0%,rgba(56,189,248,.10) 55%,rgba(183,243,107,.12) 100%);' +
        'border:1px solid rgba(56,189,248,.42);' +
        'box-shadow:0 8px 24px rgba(0,0,0,.32),0 0 22px rgba(42,171,238,.16),inset 0 1px 0 rgba(255,255,255,.14);' +
        'color:#eef8ff;cursor:pointer;transition:transform .16s cubic-bezier(.22,1,.36,1),border-color .18s,box-shadow .18s;' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-tg::after{' +
        'content:"";position:absolute;top:0;bottom:0;left:0;width:42%;pointer-events:none;' +
        'background:linear-gradient(90deg,transparent,rgba(255,255,255,.16),transparent);' +
        'animation:twTgSweep 3.8s ease-in-out infinite;' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-tg:hover{transform:translateY(-1.5px);border-color:rgba(125,211,252,.72);box-shadow:0 12px 28px rgba(0,0,0,.4),0 0 28px rgba(56,189,248,.28)}' +
      '#' + OVERLAY_ID + ' .twm-tg:active{transform:scale(.98)}' +
      '#' + OVERLAY_ID + ' .twm-tg-ico{' +
        'width:30px;height:30px;border-radius:10px;flex:none;display:grid;place-items:center;' +
        'background:linear-gradient(135deg,#38bdf8,#229ed9);color:#fff;' +
        'box-shadow:0 4px 12px rgba(34,158,217,.45);' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-tg-ico svg{width:16px;height:16px;display:block;animation:twTgBob 2.4s ease-in-out infinite}' +
      '#' + OVERLAY_ID + ' .twm-tg-tx{text-align:left;min-width:0;flex:1}' +
      '#' + OVERLAY_ID + ' .twm-tg-tx b{display:block;font-size:12.8px;font-weight:800;line-height:1.2;color:#f3faff}' +
      '#' + OVERLAY_ID + ' .twm-tg-tx small{display:block;margin-top:2px;font-size:10.5px;font-weight:600;color:#9cc9e4}' +
      '#' + OVERLAY_ID + ' .twm-tg-arr{flex:none;font-size:15px;font-weight:800;color:#7dd3fc;transition:transform .16s}' +
      '#' + OVERLAY_ID + ' .twm-tg:hover .twm-tg-arr{transform:translateX(3px)}' +
      '#' + OVERLAY_ID + ' .twm-back{margin:0 0 5px;font-size:14px;font-weight:800;color:#f3faf4}' +
      '#' + OVERLAY_ID + ' .twm-tag{margin:0 0 12px;font-size:11.8px;font-weight:700;color:#b7f36b}' +
      '#' + OVERLAY_ID + ' .twm-sign{margin:0;font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#7e9484}' +
      '@media(prefers-reduced-motion:reduce){#' + OVERLAY_ID + ' .twm-ico img,#' + OVERLAY_ID + ' .twm-dot,#' + OVERLAY_ID + ' .twm-card{animation:none!important}}';
    document.head.appendChild(st);
  }

  var DEFAULT_REOPEN = '2026-11-30T06:00:00+08:00';
  var BGM_SRC = '/assets/traderwatch-soundtrack.mp3?v=20261128a';
  var reopenTs = Date.parse(DEFAULT_REOPEN);
  var cdTimer = null;
  var bgm = null;
  var unlockBound = false;

  function unlockPlay() {
    if (!bgm) return;
    bgm.muted = false;
    var p = bgm.play();
    if (p && typeof p.then === 'function') {
      p.then(unbindUnlock).catch(function () {});
    } else {
      unbindUnlock();
    }
  }

  function bindUnlock() {
    if (unlockBound) return;
    unlockBound = true;
    document.addEventListener('pointerdown', unlockPlay, true);
    document.addEventListener('touchstart', unlockPlay, true);
    document.addEventListener('keydown', unlockPlay, true);
    document.addEventListener('wheel', unlockPlay, true);
  }

  function unbindUnlock() {
    if (!unlockBound) return;
    unlockBound = false;
    document.removeEventListener('pointerdown', unlockPlay, true);
    document.removeEventListener('touchstart', unlockPlay, true);
    document.removeEventListener('keydown', unlockPlay, true);
    document.removeEventListener('wheel', unlockPlay, true);
  }

  function startBgm() {
    if (!bgm) {
      bgm = document.createElement('audio');
      bgm.src = BGM_SRC;
      bgm.autoplay = true;
      bgm.loop = true;
      bgm.preload = 'auto';
      bgm.volume = 0.6;
      bgm.muted = false;
      bgm.setAttribute('playsinline', '');
      bgm.style.display = 'none';
      (document.body || document.documentElement).appendChild(bgm);
    }
    bgm.muted = false;
    var p = bgm.play();
    if (p && typeof p.then === 'function') {
      p.then(unbindUnlock).catch(bindUnlock);
    }
  }

  function stopBgm() {
    unbindUnlock();
    if (bgm) {
      try { bgm.pause(); bgm.currentTime = 0; bgm.remove(); } catch (e) {}
      bgm = null;
    }
  }

  function pad2(n) { return n < 10 ? '0' + n : String(n); }

  function tickCountdown() {
    var dEl = document.getElementById('twmCdD');
    if (!dEl) return;
    var diff = reopenTs - Date.now();
    if (!isFinite(diff) || diff <= 0) {
      dEl.textContent = '00';
      document.getElementById('twmCdH').textContent = '00';
      document.getElementById('twmCdM').textContent = '00';
      document.getElementById('twmCdS').textContent = '00';
      return;
    }
    var sec = Math.floor(diff / 1000);
    var d = Math.floor(sec / 86400); sec %= 86400;
    var h = Math.floor(sec / 3600); sec %= 3600;
    var m = Math.floor(sec / 60); sec %= 60;
    dEl.textContent = pad2(d);
    document.getElementById('twmCdH').textContent = pad2(h);
    document.getElementById('twmCdM').textContent = pad2(m);
    document.getElementById('twmCdS').textContent = pad2(sec);
  }

  function hide() {
    if (cdTimer) { clearInterval(cdTimer); cdTimer = null; }
    stopBgm();
    var el = document.getElementById(OVERLAY_ID);
    if (el) el.remove();
    document.documentElement.classList.remove('tw-maint-on');
  }

  function show(reopenIso) {
    if (reopenIso) {
      var parsed = Date.parse(reopenIso);
      if (isFinite(parsed)) reopenTs = parsed;
    }
    if (document.getElementById(OVERLAY_ID)) { tickCountdown(); return; }
    injectCss();
    var isMember = !!document.getElementById('phone');
    var wrap = document.createElement('div');
    wrap.id = OVERLAY_ID;
    if (isMember) wrap.className = 'twm-member';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-label', 'TraderWatch Maintenance');
    wrap.innerHTML =
      '<div class="twm-card">' +
        '<div class="twm-top">' +
          '<div class="twm-ico"><img src="/member/icons/poring-mascot.webp?v=20261128a" width="78" height="78" alt="TraderWatch Mascot"></div>' +
          '<div class="twm-pill"><span class="twm-dot"></span>System Upgrade</div>' +
        '</div>' +
        '<h2>WE’RE MAKING <span>TRADERWATCH BETTER.</span></h2>' +
        '<p class="twm-lead">Great things happen behind the scenes.</p>' +
        '<div class="twm-copy">' +
          '<p>TraderWatch is temporarily unavailable while we work on system upgrades and improvements.</p>' +
          '<p>No worries. We’re using this time to build a better experience for everyone.</p>' +
          '<p class="twm-warm">Enjoy your holiday. Take a moment to recharge.</p>' +
        '</div>' +
        '<div class="twm-div"></div>' +
        '<div class="twm-cdbox">' +
          '<div class="twm-cdlab">Estimated Reopen · Mon 6:00 AM MYT</div>' +
          '<div class="twm-cdgrid">' +
            '<div class="twm-cdu"><b id="twmCdD">00</b><span>Days</span></div>' +
            '<div class="twm-cdu"><b id="twmCdH">00</b><span>Hours</span></div>' +
            '<div class="twm-cdu"><b id="twmCdM">00</b><span>Mins</span></div>' +
            '<div class="twm-cdu"><b id="twmCdS">00</b><span>Secs</span></div>' +
          '</div>' +
        '</div>' +
        '<a class="twm-tg" href="https://t.me/traderwatchworldwide" target="_blank" rel="noopener noreferrer">' +
          '<span class="twm-tg-ico" aria-hidden="true">' +
            '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.9 4.6c.3-1.2-.8-2.1-1.9-1.7L2.7 9.6c-1.2.5-1.1 2.2.1 2.6l4.4 1.4 1.7 5.3c.3 1 1.6 1.3 2.3.5l2.5-2.5 4.5 3.3c.9.7 2.2.2 2.5-.9l3.2-14.7zM9.2 13.5l8.8-5.6-6.9 6.9-.3 3.2-1.2-3.8-3.2-1 2.8.3z"/></svg>' +
          '</span>' +
          '<span class="twm-tg-tx">' +
            '<b>Join Official Telegram</b>' +
            '<small>Get live upgrade &amp; launch updates</small>' +
          '</span>' +
          '<span class="twm-tg-arr" aria-hidden="true">→</span>' +
        '</a>' +
        '<p class="twm-back">We’ll be back soon.</p>' +
        '<p class="twm-tag">Better experience. Smarter trading. One step ahead.</p>' +
        '<p class="twm-sign">— TraderWatch</p>' +
      '</div>';
    document.body.appendChild(wrap);
    document.documentElement.classList.add('tw-maint-on');
    startBgm();
    tickCountdown();
    if (cdTimer) clearInterval(cdTimer);
    cdTimer = setInterval(tickCountdown, 1000);
  }

  function check() {
    fetch('/data/maintenance.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.maintenance === true) show(d.reopen_at || DEFAULT_REOPEN);
        else hide();
      })
      .catch(function () {});
  }

  function boot() {
    check();
    setInterval(check, 60000);
  }
  if (document.body) boot(); else document.addEventListener('DOMContentLoaded', boot);

  window.TWMaintenance = { check: check, show: show, hide: hide };
})();
