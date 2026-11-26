(function () {
  if (window.TWMaintenance) return;
  var BANNER_ID = 'tw-maint-banner';
  var FLAG_URL = '/data/maintenance.json?t=' + Date.now();
  var MSG = '⚠️ TraderWatch under maintenance, sorry for any inconvenience during maintenance periods 🙏🏻';

  function css() {
    if (document.getElementById(BANNER_ID + '-css')) return;
    var st = document.createElement('style');
    st.id = BANNER_ID + '-css';
    st.textContent =
      '#' + BANNER_ID + '{position:fixed;top:env(safe-area-inset-top,0px);left:0;right:0;z-index:2147483646;' +
      'background:#b7f36b;color:#0a100c;font:700 13px/1.35 -apple-system,Inter,system-ui,sans-serif;' +
      'text-align:center;padding:10px max(42px,calc(34px + env(safe-area-inset-right,0px))) 10px max(14px,env(safe-area-inset-left,0px));' +
      'box-shadow:0 4px 14px #0008}' +
      '#' + BANNER_ID + ' .twm-x{position:absolute;right:max(8px,env(safe-area-inset-right,0px));top:50%;transform:translateY(-50%);' +
      'background:none;border:none;color:#0a100c;font-size:16px;font-weight:800;cursor:pointer;padding:4px 8px}' +
      '@media(max-width:520px){' +
      'html.tw-maint-on .appbar{margin-top:calc(var(--tw-maint-h,0px) + env(safe-area-inset-top,0px))!important;padding-top:10px!important}' +
      'html.tw-maint-on .dm-head{margin-top:calc(var(--tw-maint-h,0px) + env(safe-area-inset-top,0px))!important;padding-top:10px!important}' +
      'html.tw-maint-on #sheet{max-height:calc(92% - var(--tw-maint-h,0px) - env(safe-area-inset-top,0px))}' +
      '}';
    document.head.appendChild(st);
  }

  function measure() {
    var b = document.getElementById(BANNER_ID);
    if (!b) return;
    document.documentElement.style.setProperty('--tw-maint-h', b.offsetHeight + 'px');
  }

  function hide() {
    var el = document.getElementById(BANNER_ID);
    if (el) el.remove();
    document.documentElement.classList.remove('tw-maint-on');
    document.documentElement.style.removeProperty('--tw-maint-h');
  }

  function show(dismissable) {
    if (document.getElementById(BANNER_ID)) { measure(); return; }
    css();
    var b = document.createElement('div');
    b.id = BANNER_ID;
    b.setAttribute('role', 'status');
    b.innerHTML = '<span>' + MSG + '</span>' +
      '<button class="twm-x" aria-label="Tutup banner">✕</button>';
    b.querySelector('.twm-x').onclick = function () {
      hide();
      try { sessionStorage.setItem('tw-maint-dismissed', '1'); } catch (e) {}
    };
    document.body.appendChild(b);
    document.documentElement.classList.add('tw-maint-on');
    measure();
  }

  function check() {
    fetch('/data/maintenance.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var on = !!(d && d.maintenance === true);
        try {
          if (!on && sessionStorage.getItem('tw-maint-dismissed') === '1') {
            hide();
            return;
          }
        } catch (e) {}
        if (on) {
          try { sessionStorage.removeItem('tw-maint-dismissed'); } catch (e) {}
          show();
        } else {
          hide();
        }
      })
      .catch(function () { /* fail senyap - tiada banner */ });
  }

  window.addEventListener('resize', measure);
  window.addEventListener('orientationchange', measure);

  function boot() {
    check();
    setInterval(check, 60000);   // semak tiap 1 minit — on/off serta-merta
  }
  if (document.body) boot(); else document.addEventListener('DOMContentLoaded', boot);

  window.TWMaintenance = { check: check };
})();
