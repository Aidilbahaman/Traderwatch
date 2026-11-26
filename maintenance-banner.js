(function () {
  if (window.TWMaintenance) return;
  var BANNER_ID = 'tw-maint-banner';
  var FLAG_URL = '/data/maintenance.json?t=' + Date.now();
  var MSG = '⚠️ TraderWatch under maintenance, sorry for any inconvenience during maintenance periods 🙏🏻';

  function css() {
    var st = document.createElement('style');
    st.id = BANNER_ID + '-css';
    st.textContent =
      '#' + BANNER_ID + '{position:fixed;top:0;left:0;right:0;z-index:9999;' +
      'background:#b7f36b;color:#0a100c;font:700 13px/1.35 -apple-system,Inter,system-ui,sans-serif;' +
      'text-align:center;padding:10px 44px 10px 14px;box-shadow:0 2px 10px #0008}' +
      '#' + BANNER_ID + ' .twm-x{position:absolute;right:10px;top:50%;transform:translateY(-50%);' +
      'background:none;border:none;color:#0a100c;font-size:16px;font-weight:800;cursor:pointer;padding:4px 8px}';
    document.head.appendChild(st);
  }

  function show(dismissable) {
    if (document.getElementById(BANNER_ID)) return;
    css();
    var b = document.createElement('div');
    b.id = BANNER_ID;
    b.setAttribute('role', 'status');
    b.innerHTML = '<span>' + MSG + '</span>' +
      '<button class="twm-x" aria-label="Tutup banner">✕</button>';
    b.querySelector('.twm-x').onclick = function () {
      b.remove();
      try { sessionStorage.setItem('tw-maint-dismissed', '1'); } catch (e) {}
    };
    document.body.appendChild(b);
  }

  function check() {
    fetch('/data/maintenance.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var on = !!(d && d.maintenance === true);
        try {
          if (!on && sessionStorage.getItem('tw-maint-dismissed') === '1') {
            var el = document.getElementById(BANNER_ID); if (el) el.remove();
            return;
          }
        } catch (e) {}
        if (on) {
          try { sessionStorage.removeItem('tw-maint-dismissed'); } catch (e) {}
          show();
        } else {
          var el = document.getElementById(BANNER_ID);
          if (el) el.remove();
        }
      })
      .catch(function () { /* fail senyap - tiada banner */ });
  }

  function boot() {
    check();
    setInterval(check, 60000);   // semak tiap 1 minit — on/off serta-merta
  }
  if (document.body) boot(); else document.addEventListener('DOMContentLoaded', boot);

  window.TWMaintenance = { check: check };
})();
