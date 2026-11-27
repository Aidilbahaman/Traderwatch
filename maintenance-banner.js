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
        'width:64px;height:64px;border-radius:20px;' +
        'background:radial-gradient(circle at 50% 45%,rgba(183,243,107,.24),rgba(183,243,107,.04) 72%);' +
        'border:1px solid rgba(183,243,107,.34);' +
        'display:grid;place-items:center;' +
        'box-shadow:0 0 28px rgba(183,243,107,.24);' +
      '}' +
      '#' + OVERLAY_ID + ' .twm-ico img{' +
        'width:48px;height:48px;object-fit:contain;display:block;' +
        'transform-origin:50% 62%;animation:twMaintFloat 3.2s ease-in-out infinite;' +
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
      '#' + OVERLAY_ID + ' .twm-back{margin:0 0 5px;font-size:14px;font-weight:800;color:#f3faf4}' +
      '#' + OVERLAY_ID + ' .twm-tag{margin:0 0 12px;font-size:11.8px;font-weight:700;color:#b7f36b}' +
      '#' + OVERLAY_ID + ' .twm-sign{margin:0;font-size:11px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:#7e9484}' +
      '@media(prefers-reduced-motion:reduce){#' + OVERLAY_ID + ' .twm-ico img,#' + OVERLAY_ID + ' .twm-dot,#' + OVERLAY_ID + ' .twm-card{animation:none!important}}';
    document.head.appendChild(st);
  }

  function hide() {
    var el = document.getElementById(OVERLAY_ID);
    if (el) el.remove();
    document.documentElement.classList.remove('tw-maint-on');
  }

  function show() {
    if (document.getElementById(OVERLAY_ID)) return;
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
          '<div class="twm-ico"><img src="/member/icons/starling-mascot.png?v=20261127b" width="48" height="48" alt="Starling AI"></div>' +
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
        '<p class="twm-back">We’ll be back soon.</p>' +
        '<p class="twm-tag">Better experience. Smarter trading. One step ahead.</p>' +
        '<p class="twm-sign">— TraderWatch</p>' +
      '</div>';
    document.body.appendChild(wrap);
    document.documentElement.classList.add('tw-maint-on');
  }

  function check() {
    fetch('/data/maintenance.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.maintenance === true) show();
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
