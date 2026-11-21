/* TraderWatch MT5 bridge / market-status banner.
 * Single source of truth: /data/mt5-bridge.json (written every minute by
 * engine/mt5_data.py health). Three states:
 *   ok=false            -> red: bridge offline, live data paused (admin fixing)
 *   ok=true, market=closed -> amber: forex market closed + countdown to reopen,
 *                             shown in the CLIENT's own timezone (auto-detected
 *                             from the browser, so each country sees local time)
 *   ok=true, market=open   -> hidden
 * Self-injecting: just add <script src="/bridge-banner.js"></script> to a page.
 */
(function () {
  if (window.__twBridgeBanner) return;
  window.__twBridgeBanner = true;

  var bar = document.createElement("div");
  bar.id = "twBridgeBar";
  bar.setAttribute("role", "status");
  bar.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:2147483000;display:none;" +
    "padding:9px 14px;font:600 13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
    "text-align:center;color:#fff;box-shadow:0 2px 12px rgba(0,0,0,.35)";
  function mount() {
    if (document.body) document.body.appendChild(bar);
    else setTimeout(mount, 50);
  }
  mount();

  var mode = "ok";
  var nextOpen = null;

  function pad(n) { return String(n).padStart(2, "0"); }
  function countdown(ms) {
    if (ms <= 0) return "0h 00m 00s";
    var h = Math.floor(ms / 3600000);
    var m = Math.floor((ms % 3600000) / 60000);
    var s = Math.floor((ms % 60000) / 1000);
    return h + "h " + pad(m) + "m " + pad(s) + "s";
  }
  function localTime(d) {
    var tz = "UTC";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch (e) {}
    var txt;
    try {
      txt = d.toLocaleString(undefined, {
        timeZone: tz, weekday: "short", day: "numeric", month: "short",
        hour: "2-digit", minute: "2-digit", hour12: false
      });
    } catch (e) { txt = d.toUTCString(); }
    return { txt: txt, tz: tz };
  }

  function render() {
    if (mode === "down") {
      bar.style.background = "#b3261e";
      bar.innerHTML =
        "⚠️ MT5 data bridge offline — live data paused. Admin is restarting the bridge.";
      bar.style.display = "block";
    } else if (mode === "closed" && nextOpen) {
      var diff = nextOpen.getTime() - Date.now();
      if (diff <= 0) { bar.style.display = "none"; return; }
      var lt = localTime(nextOpen);
      bar.style.background = "#8a6d1a";
      bar.innerHTML =
        "🌙 Market closed — reopens <b>" + lt.txt + "</b> (" + lt.tz +
        ") · in <b>" + countdown(diff) + "</b>";
      bar.style.display = "block";
    } else {
      bar.style.display = "none";
    }
  }

  function poll() {
    fetch("/data/mt5-bridge.json?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (!s) return;
        if (s.ok === false) { mode = "down"; nextOpen = null; }
        else if (s.market === "closed" && s.next_open) {
          mode = "closed"; nextOpen = new Date(s.next_open);
        } else { mode = "ok"; nextOpen = null; }
        render();
      })
      .catch(function () { /* keep last known state on network blip */ });
  }

  poll();
  setInterval(poll, 60000);   // refresh status each minute
  setInterval(render, 1000);  // tick the countdown every second
})();