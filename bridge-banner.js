/* TraderWatch market/bridge state provider (no visible header).
 * Reads /data/mt5-bridge.json every minute (written by engine/mt5_data.py health)
 * and exposes window.TWMarket + dispatches "twmarket" events so pair cards can
 * show per-card "Market closed" labels instead of a global banner.
 *
 *   TWMarket.ok        true when MT5 bridge is up
 *   TWMarket.market    "open" | "closed"  (forex/metals session)
 *   TWMarket.nextOpen  Date of next forex open (UTC; render in client's own tz)
 *   TWMarket.closed()  true when bridge down OR forex market closed
 *   TWMarket.isPairClosed(symbol)  true for FOREX/METALS when market closed;
 *                                  always false for BTCUSD (crypto trades 24/7)
 */
(function () {
  if (window.TWMarket) return;

  var state = { ok: null, market: null, nextOpen: null, checkedAt: null, error: null };
  var CRYPTO = { BTCUSD: true };   // crypto pairs stay live on weekends

  function emit() {
    window.dispatchEvent(new CustomEvent("twmarket", { detail: state }));
  }
  function parse(s) {
    state.ok = (s.ok === true);
    state.market = s.market || null;
    state.nextOpen = s.next_open ? new Date(s.next_open) : null;
    state.checkedAt = s.checked_at ? new Date(s.checked_at) : null;
    state.error = s.last_error || null;
  }
  function poll() {
    fetch("/data/mt5-bridge.json?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) { if (s) { parse(s); emit(); } })
      .catch(function () { /* keep last known state on network blip */ });
  }

  window.TWMarket = {
    get ok() { return state.ok; },
    get market() { return state.market; },
    get nextOpen() { return state.nextOpen; },
    get checkedAt() { return state.checkedAt; },
    isPairClosed: function (symbol) {
      var s = String(symbol || "").toUpperCase().replace("/", "").replace(" ", "");
      return !CRYPTO[s] && state.market === "closed";
    },
    closed: function () { return state.market === "closed" || state.ok === false; }
  };

  poll();
  setInterval(poll, 60000);

  /* ----------------------------------------------------------------------
   * AI maintenance banner (2026-11-25).
   * Reads /data/ai-maintenance.json written by llm_analyst.py when EVERY
   * model in the chain fails (quota / maintenance / 503). Without this the
   * engine returns None and the UI silently shows a normal-looking HOLD.
   * Dev sees it too — the banner names the failing models so switching the
   * active LLM in the backend is immediate.
   * -------------------------------------------------------------------- */
  (function aiMaint() {
    var el = null, last = null;
    var CSS = "position:fixed;top:0;left:0;right:0;z-index:2147483647;" +
      "background:#3a1418;color:#ffd9dc;border-bottom:1px solid #ff5d6c;" +
      "padding:9px 14px;font:600 12px/1.45 system-ui,-apple-system,sans-serif;" +
      "text-align:center;box-shadow:0 4px 18px #0008;cursor:pointer";
    function render(s) {
      var active = !!(s && s.active);
      if (!active) {
        if (el) { el.remove(); el = null; }
        last = null;
        return;
      }
      var sig = JSON.stringify(s);
      if (sig === last) return;
      last = sig;
      if (!el) {
        el = document.createElement("div");
        el.id = "tw-ai-maint";
        el.setAttribute("role", "alert");
        el.style.cssText = CSS;
        el.onclick = function () { el.remove(); el = null; last = null; };
        (document.body || document.documentElement).appendChild(el);
      }
      var models = (s.models || []).join(", ");
      var when = s.checked_at ? new Date(s.checked_at).toLocaleTimeString() : "";
      el.innerHTML = "⚠ <b>AI SIGNAL ENGINE OFFLINE</b> — " +
        "semua model gagal. " + (models ? "Model: " + models + ". " : "") +
        (when ? "Sejak " + when + ". " : "") +
        "Hubungi dev / tukar LLM aktif. <span style='opacity:.7'>(ketuk untuk tutup)</span>";
    }
    function poll() {
      fetch("/data/ai-maintenance.json?t=" + Date.now(), { cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(render)
        .catch(function () { /* network blip — keep last banner */ });
    }
    poll();
    setInterval(poll, 30000);
  })();
})();