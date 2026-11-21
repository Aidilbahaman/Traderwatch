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
})();